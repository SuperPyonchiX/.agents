#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIエージェントのセッション履歴から、ユーザー発話を期間で切り出して集計する。

H1（機械集計）で実行する。全発話をエージェントに読ませないために、
反復している依頼と、エージェントへの指摘・やり直し要求をここで拾っておく。

    python extract_history.py [--claude-history <history.jsonl>]
                              [--codex-sessions <sessions ディレクトリ>]
                              [--antigravity-dir <antigravity-cli ディレクトリ>]
                              [--days 30] [-o work/history-summary.json]
                              [--dump work/prompts.jsonl]

読める形式:
    Claude Code  ~/.claude/history.jsonl（1行1発話。display / timestamp[ms] / project / sessionId）
    Codex        ~/.codex/sessions/**/*.jsonl と *.jsonl.zst（event_msg の item_completed のうち
                 item.type=UserMessage。旧形式の user_message も読む。source が subagent と exec の
                 セッションは除外する。「# Context from my IDE setup:」「# Files mentioned by the user」の前置きは外す）
    Antigravity  ~/.gemini/antigravity-cli/（brain/<会話ID>/.system_generated/logs/transcript.jsonl の
                 USER_INPUT。<USER_REQUEST> の中身だけを取る。作業ディレクトリは
                 conversation_summaries.db の workspace_uris から引く。second-opinion スキルが
                 自動で投げた相談（作業コピー second-opinion-agy-*）は除外する）

集計するもの:
    by_project        プロジェクト（作業ディレクトリ）ごとの発話数とセッション数
    repeated          数字・パス・URL を伏せた発話の先頭が一致するもの（2セッション以上）
    terms             発話に出る語を、出現したセッション数で数えたもの（上位 60）
    corrections       指摘・やり直し要求らしい発話（語句で拾う目安。採否はエージェントが判断）
    with_image        画像を添えた発話の件数（見た目の指摘が多いかの目安）

除外するもの: スラッシュコマンド、! で始まるシェル実行、<command-name> などの制御出力、空行。
同じ本文・同じ日付の発話は1件にまとめる（Codex に取り込まれた Claude 履歴の重複を畳む）。

終了コード:
    0  集計した
    1  期間内の発話が0件
    2  引数の指定ミス（履歴が1つも指定されていない・パスが無い）、または .jsonl.zst を展開できない

依存は標準ライブラリのみ。ただし Codex の .jsonl.zst を読むには、Python 3.14 以降・zstandard
パッケージ・zstd コマンドのどれか1つが要る（この順に探す）。履歴には貼り付けた秘密情報が含まれうるので、
出力はローカルにだけ置き、外部サービスへ送らないこと。
"""

import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

SNIPPET = 160            # 例として残す発話の最大文字数
REPEAT_KEY_LEN = 24      # 反復判定に使う先頭文字数
MAX_EXAMPLES = 3
TOP_TERMS = 60
MAX_CORRECTIONS = 150

SKIP_PREFIX = ("/", "!", "<command-name>", "<local-command", "<command-message>",
               "<system-reminder>", "<task-notification>", "# AGENTS.md instructions", "Caveat:",
               "This session is being continued", "[Request interrupted by user")
# codex exec は second-opinion の相談や評価の被験者として自動で起動されるので、人の発話として数えない
CODEX_SKIP_SOURCES = ("exec",)
# IDE 拡張の文脈と、@ で添えた画像・ファイルの一覧。本題は「## My request:」の後ろにある
CODEX_PREAMBLE_HEADS = ("# Context from my IDE setup:", "# Files mentioned by the user")
PREAMBLE_IMAGE_RE = re.compile(r"^## [^\n]*\.(?:png|jpe?g|gif|webp|bmp)\b", re.M | re.I)
IDE_REQUEST_RE = re.compile(r"^## My request[^\n]*:\s*(.*)\Z", re.M | re.S)
IMAGE_RE = re.compile(r"\[(?:external unsupported block: image|Image #?\d*[^\]]*)\]\s*")

CORRECTION_RE = re.compile(
    r"違う|違います|ちがう|そうじゃな|そうではな|じゃなくて|ではなくて|"
    r"やめて|しないで|しなくていい|いらない|要らない|余計|勝手に|"
    r"直って(い)?ない|なおって(い)?ない|変わって(い)?ない|変わらな|変わらず|"
    r"戻して|元に戻|前にも|さっきも|何度も|言ったのに|言いました|"
    r"なんで|なぜ.{0,12}(した|しない|なる|ない)|間違|おかしい|効いてない|できてない"
)
MASK_RES = [
    (re.compile(r"https?://\S+"), "<URL>"),
    (re.compile(r"[A-Za-z]:[\\/][A-Za-z0-9_.\-\\/]+|(?:~|\.{1,2})?/[A-Za-z0-9_.\-/]+"), "<PATH>"),
    (re.compile(r"\[Pasted text #\d+[^\]]*\]"), "<PASTED>"),
    (re.compile(r"\d+"), "0"),
    (re.compile(r"\s+"), " "),
]
USER_REQUEST_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.S)
# second-opinion の ask_antigravity.py が作る作業コピー。人の発話ではないので数えない
AGY_AUTOMATED_WORKSPACE = "second-opinion-agy-"
AGY_AUTOMATED_PREFIX = "あなたは second-opinion スキルの相談先。"
TERM_RE = re.compile(r"[一-鿿]{2,}|[゠-ヿ]{3,}|[A-Za-z][A-Za-z0-9+#.\-]{2,}")
STOP_TERMS = frozenset([
    "お願い", "下さい", "ください", "します", "して", "これ", "それ", "確認", "対応",
    "修正", "作成", "追加", "実行", "内容", "今回", "以下", "場合", "ファイル", "the", "and",
    "PATH", "URL",
])


def strip_image(text):
    """画像添付のマーカーを外し、(本文, 画像付きか) を返す。"""
    t = text or ""
    cleaned = IMAGE_RE.sub("", t).strip()
    return cleaned, cleaned != t.strip()


def ok_prompt(text):
    t = (text or "").strip()
    return bool(t) and not t.startswith(SKIP_PREFIX)


def normalize(text):
    t = text.strip()
    for pat, rep in MASK_RES:
        t = pat.sub(rep, t)
    return t


def snippet(text):
    t = re.sub(r"\s+", " ", text.strip())
    return t if len(t) <= SNIPPET else t[:SNIPPET] + "…"


def read_claude(path, since):
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            ts = d.get("timestamp")
            if not isinstance(ts, (int, float)):
                continue
            when = dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc)
            text, image = strip_image(d.get("display", ""))
            if when < since or not ok_prompt(text):
                continue
            out.append({"tool": "claude", "time": when, "project": d.get("project") or "?",
                        "session": d.get("sessionId") or "?", "text": text, "image": image})
    return out


class ZstdUnavailable(Exception):
    """.jsonl.zst を展開する手段が無い。"""


def zstd_reader():
    """.zst を展開する関数を返す。Python 3.14 の標準 → zstandard → zstd コマンドの順に探す。"""
    try:
        from compression import zstd as std_zstd  # Python 3.14 以降の標準ライブラリ
        return lambda path: std_zstd.decompress(Path(path).read_bytes())
    except ImportError:
        pass
    try:
        import zstandard
        def read(path):
            with open(path, "rb") as f, zstandard.ZstdDecompressor().stream_reader(f) as r:
                return r.read()
        return read
    except ImportError:
        pass
    exe = shutil.which("zstd")
    if exe:
        return lambda path: subprocess.run([exe, "-dc", str(path)], check=True,
                                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
    return None


def codex_lines(path, unzstd):
    if path.endswith(".zst"):
        if unzstd is None:
            raise ZstdUnavailable(path)
        data = unzstd(path)
        return data.decode("utf-8", errors="replace").splitlines()
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


def codex_user_text(p):
    """event_msg の payload からユーザー発話を取り出し、(本文, 画像付きか) を返す。発話でなければ None。

    旧形式は payload.type=user_message の message。2026 年の形式は payload.type=item_completed で
    item.type=UserMessage の content[]（type=text の text、画像は local_image / image）。
    response_item の role=user は AGENTS.md の前置きつきの写しなので読まない（二重になる）。
    compacted の replacement_history も過去発話の再掲なので読まない。
    """
    if p.get("type") == "user_message":
        return strip_image(p.get("message", ""))
    item = p.get("item") or {}
    if p.get("type") != "item_completed" or item.get("type") != "UserMessage":
        return None
    texts, image = [], False
    for c in item.get("content") or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "text":
            texts.append(c.get("text") or "")
        elif c.get("type") in ("local_image", "image"):
            image = True
    text, marker = strip_image("\n".join(texts))
    return text, image or marker


def strip_codex_preamble(text):
    """Codex が発話の前に付ける前置き（IDE の文脈、@ で添えたファイルの一覧）を外す。

    (本題, 前置きに画像があったか) を返す。前置きがあるのに「## My request:」が無ければ本題は空。
    """
    if not text.startswith(CODEX_PREAMBLE_HEADS):
        return text, False
    m = IDE_REQUEST_RE.search(text)
    head = text[:m.start()] if m else text
    return (m.group(1).strip() if m else ""), bool(PREAMBLE_IMAGE_RE.search(head))


def read_codex(root, since):
    """Codex の sessions を読む。サブエージェントと codex exec（非対話の自動実行）のセッションは除外する。"""
    out = []
    paths = (glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)
             + glob.glob(os.path.join(root, "**", "*.jsonl.zst"), recursive=True))
    unzstd = zstd_reader() if any(x.endswith(".zst") for x in paths) else None
    for path in sorted(paths):
        meta, rows = {}, []
        try:
            lines = codex_lines(path, unzstd)
        except ZstdUnavailable:
            raise
        except Exception as e:  # 壊れた .zst など。1本の失敗で全体を止めず、黙っても捨てない
            print("WARN  %s: 読めなかった（%s）" % (path, e.__class__.__name__))
            continue
        for line in lines:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            p = d.get("payload") or {}
            if d.get("type") == "session_meta":
                meta = p
            elif d.get("type") == "event_msg":
                got = codex_user_text(p)
                if got is not None:
                    rows.append((d.get("timestamp"), got))
        source = meta.get("source")
        if (isinstance(source, dict) and "subagent" in source) or source in CODEX_SKIP_SOURCES:
            continue
        for ts, (raw, image) in rows:
            text, attached = strip_codex_preamble(raw)
            image = image or attached
            try:
                when = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except ValueError:
                continue
            if when < since or not ok_prompt(text):
                continue
            out.append({"tool": "codex", "time": when, "project": meta.get("cwd") or "?",
                        "session": meta.get("id") or os.path.basename(path), "text": text,
                        "image": image})
    return out


def uri_to_path(uri):
    u = urlparse(uri)
    if u.scheme != "file":
        return uri
    path = unquote(u.path)
    if re.match(r"/[A-Za-z]:", path):  # file:///D:/... → D:/...
        path = path[1:]
    return path


def agy_workspaces(root):
    """会話ID → 作業ディレクトリ。DB が読めなければ cache/last_conversations.json で補う。"""
    out = {}
    cache = os.path.join(root, "cache", "last_conversations.json")
    try:
        with open(cache, encoding="utf-8") as f:
            for ws, cid in json.load(f).items():
                out[cid] = ws
    except (OSError, ValueError, AttributeError):
        pass
    db = os.path.join(root, "conversation_summaries.db")
    if os.path.isfile(db):
        try:
            con = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)
            try:
                for cid, uris in con.execute(
                        "SELECT conversation_id, workspace_uris FROM conversation_summaries"):
                    try:
                        first = (json.loads(uris) or [None])[0]
                    except ValueError:
                        first = None
                    if first:
                        out[cid] = uri_to_path(first)
            finally:
                con.close()
        except sqlite3.Error as e:
            print("WARN  %s: 読めない（%s）。作業ディレクトリは分かる範囲だけ埋める" % (db, e))
    return out


def agy_user_text(content):
    m = USER_REQUEST_RE.search(content or "")
    return m.group(1) if m else (content or "")


def read_antigravity(root, since):
    workspaces = agy_workspaces(root)
    out = []
    for path in glob.glob(os.path.join(root, "brain", "*", ".system_generated", "logs",
                                       "transcript.jsonl")):
        cid = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(path))))
        project = workspaces.get(cid) or "?"
        if AGY_AUTOMATED_WORKSPACE in project:
            continue
        full = None
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "USER_INPUT" or d.get("source") != "USER_EXPLICIT":
                    continue
                content = d.get("content", "")
                if "content" in (d.get("truncated_fields") or []):
                    if full is None:
                        full = read_agy_full(path)
                    content = full.get(d.get("step_index"), content)
                text, image = strip_image(agy_user_text(content))
                if text.startswith(AGY_AUTOMATED_PREFIX):
                    continue
                try:
                    when = dt.datetime.fromisoformat(str(d.get("created_at")).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if when < since or not ok_prompt(text):
                    continue
                out.append({"tool": "antigravity", "time": when, "project": project,
                            "session": cid, "text": text, "image": image})
    return out


def read_agy_full(path):
    """transcript.jsonl で切り詰められた発話を transcript_full.jsonl から引く。"""
    full = {}
    try:
        with open(os.path.join(os.path.dirname(path), "transcript_full.jsonl"),
                  encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") == "USER_INPUT":
                    full[d.get("step_index")] = d.get("content", "")
    except OSError:
        pass
    return full


def dedupe(prompts):
    seen, out = set(), []
    for p in sorted(prompts, key=lambda x: x["time"]):
        key = (p["text"].strip(), p["time"].date())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def summarize(prompts, days):
    by_project = collections.defaultdict(lambda: {"prompts": 0, "sessions": set()})
    repeat = collections.defaultdict(lambda: {"count": 0, "sessions": set(), "examples": []})
    term_sessions = collections.defaultdict(set)
    corrections = []

    for p in prompts:
        bp = by_project[p["project"]]
        bp["prompts"] += 1
        bp["sessions"].add(p["session"])

        norm = normalize(p["text"])
        key = norm[:REPEAT_KEY_LEN]
        r = repeat[key]
        r["count"] += 1
        r["sessions"].add(p["session"])
        if len(r["examples"]) < MAX_EXAMPLES:
            r["examples"].append(snippet(p["text"]))

        for term in set(TERM_RE.findall(norm)):
            if term not in STOP_TERMS:
                term_sessions[term].add(p["session"])

        if len(p["text"]) <= 400 and CORRECTION_RE.search(p["text"]):
            corrections.append({"time": p["time"].isoformat(timespec="minutes"),
                                "project": p["project"], "session": p["session"],
                                "image": p["image"], "text": snippet(p["text"])})

    repeated = sorted(
        ({"key": k, "count": v["count"], "sessions": len(v["sessions"]), "examples": v["examples"]}
         for k, v in repeat.items() if len(v["sessions"]) >= 2),
        key=lambda x: (-x["sessions"], -x["count"]))
    terms = sorted(({"term": t, "sessions": len(s)} for t, s in term_sessions.items() if len(s) >= 2),
                   key=lambda x: -x["sessions"])[:TOP_TERMS]
    projects = sorted(({"project": k, "prompts": v["prompts"], "sessions": len(v["sessions"])}
                       for k, v in by_project.items()), key=lambda x: -x["prompts"])

    return {
        "period_days": days,
        "from": prompts[0]["time"].isoformat(timespec="minutes"),
        "to": prompts[-1]["time"].isoformat(timespec="minutes"),
        "total_prompts": len(prompts),
        "total_sessions": len({p["session"] for p in prompts}),
        "by_tool": dict(collections.Counter(p["tool"] for p in prompts)),
        "with_image": sum(1 for p in prompts if p["image"]),
        "by_project": projects,
        "repeated": repeated,
        "terms": terms,
        "corrections_total": len(corrections),
        "corrections": corrections[-MAX_CORRECTIONS:],
    }


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="セッション履歴のユーザー発話を集計する")
    ap.add_argument("--claude-history", help="Claude Code の history.jsonl")
    ap.add_argument("--codex-sessions", help="Codex の sessions ディレクトリ")
    ap.add_argument("--antigravity-dir", help="Antigravity CLI のデータディレクトリ（antigravity-cli）")
    ap.add_argument("--days", type=int, default=30, help="遡る日数（既定 30）")
    ap.add_argument("-o", "--output", default="work/history-summary.json", help="集計結果 JSON")
    ap.add_argument("--dump", help="期間内の全発話を JSONL で書き出す先（語で絞り込むとき用）")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2

    if not (args.claude_history or args.codex_sessions or args.antigravity_dir):
        print("ERROR  --claude-history / --codex-sessions / --antigravity-dir のどれかを指定する")
        return 2
    if args.claude_history and not os.path.isfile(args.claude_history):
        print("ERROR  %s: ファイルがない" % args.claude_history)
        return 2
    if args.codex_sessions and not os.path.isdir(args.codex_sessions):
        print("ERROR  %s: ディレクトリがない" % args.codex_sessions)
        return 2
    if args.antigravity_dir and not os.path.isdir(os.path.join(args.antigravity_dir, "brain")):
        print("ERROR  %s: brain ディレクトリがない（antigravity-cli のディレクトリを指定する）"
              % args.antigravity_dir)
        return 2
    if args.days <= 0:
        print("ERROR  --days は 1 以上")
        return 2

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    prompts = []
    if args.claude_history:
        prompts += read_claude(args.claude_history, since)
    if args.codex_sessions:
        try:
            prompts += read_codex(args.codex_sessions, since)
        except ZstdUnavailable as e:
            print("ERROR  %s: .jsonl.zst を展開できない。`pip install zstandard` か zstd コマンドを入れて"
                  "再実行する（Python 3.14 以降なら不要）。Codex を外すなら --codex-sessions を付けない" % e)
            return 2
    if args.antigravity_dir:
        prompts += read_antigravity(args.antigravity_dir, since)
    prompts = dedupe(prompts)
    if not prompts:
        print("期間内（直近 %d 日）の発話が0件" % args.days)
        return 1

    summary = summarize(prompts, args.days)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    if args.dump:
        os.makedirs(os.path.dirname(os.path.abspath(args.dump)), exist_ok=True)
        with open(args.dump, "w", encoding="utf-8") as f:
            for p in prompts:
                f.write(json.dumps({"time": p["time"].isoformat(timespec="minutes"),
                                    "tool": p["tool"], "project": p["project"],
                                    "session": p["session"], "image": p["image"],
                                    "text": p["text"]},
                                   ensure_ascii=False) + "\n")

    print("期間 %s 〜 %s / 発話 %d 件 / セッション %d 件 / %s"
          % (summary["from"], summary["to"], summary["total_prompts"],
             summary["total_sessions"], summary["by_tool"]))
    print("反復候補 %d 件 / 指摘候補 %d 件 / 出力 %s"
          % (len(summary["repeated"]), summary["corrections_total"], args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
