#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スキル本文を横断して、モデル更新時に見直すべき箇所を行単位で拾う。

本文監査（B1）で実行する。全スキルの本文をエージェントに通読させないために、
見直しの候補になる行だけをここで抜き出しておく。

    python scan_bodies.py <skills-dir> [-o work/body-scan.json] [--skills a,b,c]

拾うもの（kind）:
    model-ref      特定のモデル名・モデル ID・世代への言及。更新後に古くなっている可能性がある
    emphasis       強調語（必ず・絶対・禁止・IMPORTANT・MUST 等）。1スキル内の密度が高いと WARN。
                   新しいモデルほど強い強調に過剰反応しやすい
    risky          取り消しにくい操作（push・force・削除・公開・デプロイ・自動承認フラグ等）。
                   前後 5 行に確認・承認の語が無いものを WARN
    tool-specific  特定エージェント専用のツール名・機能名。移植性の規約に反していないか見る
    dated          年号と「最新」「現時点」等の組み合わせ。時点依存の記述

対象ファイル: 各スキルの SKILL.md と references/ 配下の .md。scripts/ は見ない。
コードブロック内も対象にする（手順として実行されるため）。

終了コード:
    0  走査した（候補の有無は問わない）
    2  引数の指定ミス

依存は標準ライブラリのみ。
"""

import argparse
import json
import os
import re
import sys

CONTEXT = 5                 # risky の確認語を探す前後の行数
EMPHASIS_DENSITY_WARN = 6.0 # 100 行あたりの強調語数がこれを超えたら WARN

PATTERNS = {
    "model-ref": re.compile(
        r"claude-(?:opus|sonnet|haiku|fable|instant|\d)[a-z0-9.\-]*|"
        r"\b(?:Opus|Sonnet|Haiku|Fable)\s*\d(?:\.\d)?|"
        r"\bGPT-?\d[\w.\-]*|\bo[134](?:-mini)?\b|\bGemini\s*\d[\w.]*",
        re.IGNORECASE),
    "emphasis": re.compile(
        r"必ず|絶対に?|決して|厳守|禁止|IMPORTANT|CRITICAL|\bMUST\b|\bNEVER\b|\bALWAYS\b"),
    "risky": re.compile(
        r"git\s+push|--force\b|push\s+-f\b|reset\s+--hard|rm\s+-rf|Remove-Item[^\n]*-Recurse|"
        r"--no-verify|--yes\b|--confirm\b|\boverwrite\b|auto-?merge|\bdeploy\b|デプロイ|"
        r"DROP\s+TABLE|\b(?:source|page|file)s?\s+delete\b|\bgh\s+pr\s+merge"),
    "tool-specific": re.compile(
        r"\bTodoWrite\b|\bTask\(|\bAskUserQuestion\b|\bWebFetch\b|\bWebSearch\b|\bmcp__\w+|"
        r"サブエージェント|subagent|\$ARGUMENTS|!`|context:\s*fork|allowed-tools|"
        r"disable-model-invocation|\bhooks?\b"),
    "dated": re.compile(r"(?:20\d\d)[年/\-].{0,20}(?:最新|現在|現時点|時点)|(?:最新|現時点).{0,20}20\d\d"),
}
# --confirm などのフラグ自体は確認の語として数えない（自動承認のフラグなので、むしろ疑う側）
CONFIRM_RE = re.compile(r"確認|承認|了承|合意|許可|尋ね|聞い|\bask\b|(?<!-)\bconfirm", re.IGNORECASE)


def target_files(skill_dir):
    files = []
    top = os.path.join(skill_dir, "SKILL.md")
    if os.path.isfile(top):
        files.append(top)
    ref = os.path.join(skill_dir, "references")
    for root, _, names in os.walk(ref):
        files += [os.path.join(root, n) for n in sorted(names) if n.endswith(".md")]
    return files


def scan_file(path, skill_dir):
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    rel = os.path.relpath(path, skill_dir).replace("\\", "/")
    hits, emphasis = [], 0
    in_front = bool(lines) and lines[0].strip() == "---"
    for i, line in enumerate(lines):
        if in_front:
            if i > 0 and line.strip() == "---":
                in_front = False
            continue  # frontmatter は audit_skills.py の担当
        for kind, pat in PATTERNS.items():
            m = pat.search(line)
            if not m:
                continue
            if kind == "emphasis":
                emphasis += len(pat.findall(line))
                continue
            hit = {"kind": kind, "file": rel, "line": i + 1, "match": m.group(0).strip(),
                   "text": line.strip()[:200]}
            if kind == "risky":
                window = lines[max(0, i - CONTEXT): i + CONTEXT + 1]
                hit["confirm_nearby"] = any(CONFIRM_RE.search(w) for w in window)
            hits.append(hit)
    return hits, emphasis, len(lines)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="スキル本文の見直し候補を抽出する")
    ap.add_argument("skills_dir")
    ap.add_argument("-o", "--output", default="work/body-scan.json")
    ap.add_argument("--skills", help="対象スキル名をカンマ区切りで絞る")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    if not os.path.isdir(args.skills_dir):
        print("ERROR  %s: ディレクトリがない" % args.skills_dir)
        return 2

    names = sorted(d for d in os.listdir(args.skills_dir)
                   if os.path.isfile(os.path.join(args.skills_dir, d, "SKILL.md")))
    if args.skills:
        wanted = [s.strip() for s in args.skills.split(",") if s.strip()]
        unknown = [s for s in wanted if s not in names]
        if unknown:
            print("ERROR  存在しないスキル: %s" % ", ".join(unknown))
            return 2
        names = wanted
    if not names:
        print("ERROR  %s: SKILL.md を持つスキルが無い" % args.skills_dir)
        return 2

    result = []
    for name in names:
        sdir = os.path.join(args.skills_dir, name)
        hits, emphasis, total = [], 0, 0
        for path in target_files(sdir):
            h, e, n = scan_file(path, sdir)
            hits += h
            emphasis += e
            total += n
        density = round(emphasis * 100.0 / total, 1) if total else 0.0
        warns = sum(1 for h in hits if h["kind"] == "risky" and not h["confirm_nearby"])
        warns += sum(1 for h in hits if h["kind"] in ("model-ref", "dated"))
        if density > EMPHASIS_DENSITY_WARN:
            warns += 1
        result.append({"skill": name, "lines": total, "emphasis": emphasis,
                       "emphasis_per_100": density, "emphasis_warn": density > EMPHASIS_DENSITY_WARN,
                       "warn_score": warns, "hits": hits})

    result.sort(key=lambda r: -r["warn_score"])
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"skills_dir": os.path.abspath(args.skills_dir), "skills": result},
                  f, ensure_ascii=False, indent=2)

    print("%-32s %6s %6s %6s %6s %6s %6s" % ("skill", "model", "risky!", "tool", "dated", "emph/100", "score"))
    for r in result:
        k = lambda kind: sum(1 for h in r["hits"] if h["kind"] == kind)
        risky_nc = sum(1 for h in r["hits"] if h["kind"] == "risky" and not h["confirm_nearby"])
        print("%-32s %6d %6d %6d %6d %8s %6d" % (r["skill"], k("model-ref"), risky_nc,
              k("tool-specific"), k("dated"),
              ("%.1f%s" % (r["emphasis_per_100"], "!" if r["emphasis_warn"] else "")), r["warn_score"]))
    print("出力 %s" % args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
