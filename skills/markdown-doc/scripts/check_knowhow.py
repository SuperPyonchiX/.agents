#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成AI活用ノウハウ記事の形式を検査する。

工程6（検証ループ）のゲートとして実行する。

    python check_knowhow.py <出力先>/knowhow/<slug>.md
    python check_knowhow.py <出力先>/knowhow/<slug>.md --index <出力先>/INDEX.md

終了コード:
    0  合格（WARN のみの場合も 0。内容は表示される）
    1  ERROR あり。直すまでユーザーに提示しない
    2  引数の指定ミス、またはファイルが読めない

見るのは形式だけである。「やったこと」を読んで再現できるか、
「効いたポイント」が一般論になっていないかは判定できないので、
SKILL.md の目視チェックリストと必ず併用すること。
依存は標準ライブラリのみ。
"""

import argparse
import os
import re
import sys

# 必須セクション（見出しの表記揺れを吸収する）
REQUIRED_SECTIONS = [
    ("概要", ("概要",)),
    ("やったこと", ("やったこと", "やったこと・手順", "手順")),
    ("効いたポイント", ("効いたポイント", "ポイント", "効いたこと")),
    ("つまずいたこと・避けること",
     ("つまずいたこと・避けること", "つまずいたこと", "避けること", "つまずき・避けること")),
    ("再利用プロンプト", ("再利用プロンプト", "再利用可能なプロンプト", "プロンプト")),
]

# 概要表に必要な行（左端セルの表記揺れを吸収する）
REQUIRED_META = [
    ("成果物", ("成果物", "作ったもの")),
    ("使ったAI・モデル", ("使ったai・モデル", "使ったai/モデル", "使ったai", "ai・モデル", "モデル")),
    ("所要", ("所要", "所要時間")),
    ("日付", ("日付", "実施日")),
]

PLACEHOLDER_RE = re.compile(r"〔|〕|\bTODO\b|〇〇|＿＿|\bXXX\b")
REASON_RE = re.compile(r"(理由|なぜ)\s*[:：]")
EMPTY_CELL = {"", "-", "—", "–", "未記入", "TBD"}

MAX_LINES_WARN = 100
MAX_LINES_ERROR = 140
MIN_POINTS = 2
MAX_STEPS_WARN = 8

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


class Report(object):
    def __init__(self):
        self.errors = []
        self.warns = []

    def error(self, where, msg):
        self.errors.append((where, msg))

    def warn(self, where, msg):
        self.warns.append((where, msg))

    def dump(self, path, stats):
        for where, msg in self.errors:
            print("ERROR  %s: %s" % (where, msg))
        for where, msg in self.warns:
            print("WARN   %s: %s" % (where, msg))
        print()
        print("%s: %d 行 / 効いたポイント %d 件 / やったこと %d 手"
              % (path, stats["lines"], stats["points"], stats["steps"]))
        print("ERROR %d 件 / WARN %d 件" % (len(self.errors), len(self.warns)))
        if self.errors:
            print("不合格。直してから再実行すること。合格したかのように報告しない。")
        else:
            print("合格。形式上の不備はない。目視チェックリストを別途当てること。")
        return 1 if self.errors else 0


def split_sections(lines):
    """`# 見出し` で本文を分割し、[(見出し, 開始行, 行リスト)] を返す。"""
    sections = []
    current = None
    in_fence = False
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and re.match(r"^#\s+\S", line):
            current = (line.lstrip("#").strip(), n, [])
            sections.append(current)
            continue
        if current is not None:
            current[2].append((n, line))
    return sections


def find_section(sections, aliases):
    for title, start, body in sections:
        normalized = title.replace(" ", "").replace("　", "").lower()
        for alias in aliases:
            if normalized == alias.replace(" ", "").lower():
                return (title, start, body)
    return None


def check_meta_table(path, body, rep):
    """概要表の必須行が存在し、値が埋まっているかを見る。"""
    rows = {}
    for n, line in body:
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        key = cells[0].replace(" ", "").replace("　", "").lower()
        rows[key] = (n, cells[1])

    for label, aliases in REQUIRED_META:
        hit = None
        for alias in aliases:
            hit = rows.get(alias.replace(" ", "").lower())
            if hit is not None:
                break
        if hit is None:
            rep.error(path, "概要表に「%s」の行がない"
                            "（assets/templates/knowhow-template.md の表を使うこと）" % label)
            continue
        n, value = hit
        if value in EMPTY_CELL:
            rep.error("%s:%d" % (path, n), "概要表の「%s」が空。分からない項目は「不明」と書くこと" % label)


def check_points(path, body, rep):
    """効いたポイントの件数と、各項目に理由が添えられているかを見る。"""
    count = 0
    in_fence = False
    for n, line in body:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        s = line.strip()
        if not re.match(r"^[-*]\s+\S", s):
            continue
        count += 1
        if not REASON_RE.search(s):
            rep.error("%s:%d" % (path, n),
                      "効いたポイントに理由がない: %s"
                      "（「— 理由: なぜ効いたか」を必ず添える）" % s[:40])
    if count < MIN_POINTS:
        rep.error(path, "効いたポイントが %d 件しかない（%d 件以上書くこと）。"
                        "書けないなら、そもそも記録に残す価値があるか見直す" % (count, MIN_POINTS))
    return count


def check_prompt(path, section, rep):
    """再利用プロンプト節にコードブロックがあるかを見る。"""
    _title, start, body = section
    fences = [n for n, line in body if line.lstrip().startswith("```")]
    if len(fences) < 2:
        rep.error("%s:%d" % (path, start),
                  "再利用プロンプト節にコードブロックがない。"
                  "次回そのまま投げられる形をバッククォート3つで囲んで書くこと")


def count_steps(body):
    count = 0
    in_fence = False
    for _n, line in body:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and re.match(r"^\s*\d+[.)]\s+\S", line):
            count += 1
    return count


def check_index(index_path, target_path, rep):
    """索引に当該ノウハウへのリンクが1行あるかを見る。"""
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        rep.error(index_path, "索引を読み込めない (%s)。"
                              "無ければ assets/templates/index-template.md から作ること" % e)
        return
    basename = os.path.basename(target_path)
    hits = re.findall(r"\]\(([^)]+)\)", text)
    for href in hits:
        if os.path.basename(href.split("#")[0].strip()) == basename:
            return
    rep.error(index_path, "%s へのリンクが索引にない。1行追記すること" % basename)


def check(path, index_path, rep):
    stats = {"lines": 0, "points": 0, "steps": 0}
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as e:
        rep.error(path, "読み込めない (%s)" % e)
        return stats, False

    stats["lines"] = len(lines)
    if len(lines) > MAX_LINES_ERROR:
        rep.error(path, "%d 行。長すぎる（上限 %d 行）。項目を削るのではなく、"
                        "テーマで件を分割して相互リンクすること" % (len(lines), MAX_LINES_ERROR))
    elif len(lines) > MAX_LINES_WARN:
        rep.warn(path, "%d 行。目安の %d 行を超えている。件の分割を検討すること"
                 % (len(lines), MAX_LINES_WARN))

    for n, line in enumerate(lines, 1):
        m = PLACEHOLDER_RE.search(line)
        if m:
            rep.error("%s:%d" % (path, n),
                      "テンプレートのプレースホルダが残っている: '%s'" % m.group(0))

    sections = split_sections(lines)
    found = {}
    for label, aliases in REQUIRED_SECTIONS:
        hit = find_section(sections, aliases)
        if hit is None:
            rep.error(path, "必須セクション「# %s」がない" % label)
        found[label] = hit

    if found["概要"]:
        check_meta_table(path, found["概要"][2], rep)
    if found["やったこと"]:
        stats["steps"] = count_steps(found["やったこと"][2])
        if stats["steps"] == 0:
            rep.error(path, "「やったこと」に番号付きの手順が1つもない")
        elif stats["steps"] > MAX_STEPS_WARN:
            rep.warn(path, "「やったこと」が %d 手ある。再現に必要な手数まで絞るか、件を分割すること"
                     % stats["steps"])
    if found["効いたポイント"]:
        stats["points"] = check_points(path, found["効いたポイント"][2], rep)
    if found["再利用プロンプト"]:
        check_prompt(path, found["再利用プロンプト"], rep)

    if index_path:
        check_index(index_path, path, rep)
    return stats, True


def main(argv):
    ap = argparse.ArgumentParser(description="生成AI活用ノウハウ記事の形式検査")
    ap.add_argument("knowhow", help="knowhow/<slug>.md")
    ap.add_argument("--index", help="INDEX.md。指定するとリンクの有無も検査する")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.knowhow):
        print("ERROR  %s: ファイルがない" % args.knowhow)
        return 2

    rep = Report()
    stats, _ok = check(args.knowhow, args.index, rep)
    return rep.dump(args.knowhow, stats)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
