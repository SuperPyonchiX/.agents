"""NotebookLM の要約回答を Notion 用の Markdown に整形し、変換後のブロックを検査する。

使い方:
    python normalize_summary.py normalize --answer q_<id>.json --url <動画URL> --notebook <ノートブック名> --out summaries/<id>.md [--field answer]
    python normalize_summary.py check --blocks blocks_<id>.json

normalize:
    --answer は nlm notebook query --json の出力か、回答本文だけのテキスト。JSON なら --field（既定 answer）の値を使う。
    出典マーカー・冒頭の前置き・末尾の追い質問・BOM・「〜向け説明」のラベルを落とし、
    大見出し3つを「## 見出し」、結論の各項目と小見出しを「- **本文**」に揃える。
    大見出しと小見出しの記法の揺れ（SKILL.md の表の A〜D）はここで吸収する。
    書き出した Markdown に「## 」がちょうど3つ、「####」と「***」が無いことを確かめる。

check:
    md2blocks.py の出力を読み、heading_2 がちょうど3つ、最初の heading_2 の直後が太字の bulleted_list_item、
    本文に「####」「***」「**」が残っていないことを確かめる。

終了コード: 0=整形・検査とも合格 / 1=検査不合格（理由を表示。投稿しない） / 2=引数・入力の不備
依存は標準ライブラリのみ。
"""
import argparse
import json
import re
import sys
from pathlib import Path

CITATION_RE = re.compile(r"\s?\[[0-9,\s\-–]+\]")
PREAMBLE_RE = re.compile(r"^[^\n]*(ソース|ご指定)[^\n]*要約を作成しました。\s*(\n-{3,})?\s*\n")
# 末尾の追い質問。空行に続く「絵文字で始まる最終ブロック」。絵文字は毎回変わるので範囲で受ける
TRAILER_RE = re.compile(r"\n\s*\n[←-⯿\U0001F000-\U0001FAFF][\s\S]*$")
LABEL_RE = re.compile(r"\*\*[^*\n]*向け説明\*\*\s*[:：]\s*")
BIG_RE = re.compile(r"^(#{0,4})\s*\*{0,2}\s*(\d)([\)\.])\s*(.+?)\s*$")
SUB_RE = re.compile(r"^#{3,4}\s+(.+?)\s*$")
ITEM_RE = re.compile(r"^(?:・\s*|[*-]\s+|\d+\.\s+)(.+)$")


def unbold(text):
    return text.replace("**", "").strip().rstrip(":：").strip()


def clean(text):
    text = text.lstrip("﻿").replace("\r\n", "\n")
    text = CITATION_RE.sub("", text)
    text = PREAMBLE_RE.sub("", text, count=1)
    text = TRAILER_RE.sub("", text.rstrip())
    return LABEL_RE.sub("", text)


def big_heading(line, expected):
    """大見出しなら見出し文字列を返す。番号が次に来るべき番号と一致するものだけを拾う。"""
    m = BIG_RE.match(line)
    if not m or int(m.group(2)) != expected:
        return None
    hashes, sep, title = m.group(1), m.group(3), m.group(4)
    if sep == "." and not hashes:  # D の「1. **本文**」は結論の項目であって見出しではない
        return None
    return unbold(title)


def sentences(text):
    return [s + "。" for s in (p.strip() for p in unbold(text).split("。")) if s]


def normalize(answer):
    out, section = [], 0
    for raw in clean(answer).split("\n"):
        line = raw.strip()
        title = big_heading(line, section + 1)
        if title:
            section += 1
            out += ["", "## " + title, ""]
            continue
        if section == 0 or not line:
            if line == "" and out and out[-1] != "":
                out.append("")
            continue  # 最初の大見出しより前は前置きとして落とす
        if line.startswith("---"):
            continue  # 区切りは見出しで足りる
        m = SUB_RE.match(line)
        if m:
            out.append("- **" + unbold(m.group(1)) + "**")
            continue
        if section == 1:
            m = ITEM_RE.match(line)
            items = [unbold(m.group(1))] if m else [s for s in sentences(line)]
            out += ["- **" + s + "**" for s in items if s]
            continue
        out.append(line)
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return body, section


def problems_in_markdown(md):
    found = []
    n = len(re.findall(r"^## ", md, flags=re.M))
    if n != 3:
        found.append("「## 」の見出しが {} 個（3個のはず）".format(n))
    if "####" in md:
        found.append("「####」が残っている")
    if "***" in md:
        found.append("「***」が残っている")
    return found


def cmd_normalize(args):
    try:
        raw = Path(args.answer).read_text(encoding="utf-8-sig")
    except OSError as e:
        print("回答ファイルを読めません: {}".format(e), file=sys.stderr)
        return 2
    answer = raw
    if raw.lstrip().startswith("{"):
        try:
            answer = json.loads(raw)[args.field]
        except (ValueError, KeyError, TypeError):
            print("JSON に {} がありません。nlm の実出力で本文のキーを確かめ --field で渡してください".format(args.field),
                  file=sys.stderr)
            return 2
    body, sections = normalize(answer)
    md = "> {}\n\n{}\n\n---\n\n---\n\nNotebookLM: {}\n".format(args.url, body, args.notebook)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    found = problems_in_markdown(md)
    if sections != 3:
        found.append("大見出しを {} 個しか拾えなかった。回答の見出しの記法が SKILL.md の表に無い形かもしれない".format(sections))
    for p in found:
        print("NG  " + p)
    print("{}  {}".format("OK" if not found else "NG", out))
    return 1 if found else 0


def texts(block):
    body = block.get(block.get("type"), {})
    return body.get("rich_text", [])


def cmd_check(args):
    try:
        blocks = json.loads(Path(args.blocks).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print("ブロック JSON を読めません: {}".format(e), file=sys.stderr)
        return 2
    found = []
    heads = [i for i, b in enumerate(blocks) if b.get("type") == "heading_2"]
    if len(heads) != 3:
        found.append("heading_2 が {} 個（3個のはず）".format(len(heads)))
    if heads:
        nxt = blocks[heads[0] + 1] if heads[0] + 1 < len(blocks) else {}
        rt = texts(nxt)
        if nxt.get("type") != "bulleted_list_item" or not rt or not all(
                (r.get("annotations") or {}).get("bold") for r in rt):
            found.append("結論の直後が太字の箇条書きになっていない（{}）".format(nxt.get("type")))
    for i, b in enumerate(blocks):
        content = "".join(r.get("text", {}).get("content", "") for r in texts(b))
        for mark in ("####", "***", "**"):
            if mark in content:
                found.append("ブロック {}（{}）に「{}」が残っている: {}".format(i, b.get("type"), mark, content[:40]))
                break
    for p in found:
        print("NG  " + p)
    print("OK" if not found else "NG")
    return 1 if found else 0


def main():
    parser = argparse.ArgumentParser(description="NotebookLM の要約を Notion 用に整形・検査する")
    sub = parser.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("normalize")
    n.add_argument("--answer", required=True)
    n.add_argument("--url", required=True)
    n.add_argument("--notebook", required=True)
    n.add_argument("--out", required=True)
    n.add_argument("--field", default="answer")
    c = sub.add_parser("check")
    c.add_argument("--blocks", required=True)
    args = parser.parse_args()
    sys.exit(cmd_normalize(args) if args.cmd == "normalize" else cmd_check(args))


if __name__ == "__main__":
    main()
