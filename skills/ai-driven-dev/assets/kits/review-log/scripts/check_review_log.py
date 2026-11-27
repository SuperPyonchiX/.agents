#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""レビュー記録（REVIEW_LOG.md）に未対応・確認待ちの指摘や、対応の書き漏れが無いかを検査する。

    python check_review_log.py REVIEW_LOG.md

ID・対象・指摘・対応・状態の列を持つ表をすべて読む（レビューの回ごとに表が分かれていてよい）。
状態は 未対応 / 確認待ち / 対応済み / 見送り の4つ。ID が〔〕のままの行は雛形とみなして数えない。
残っている未対応・確認待ちは1件1行で出すので、一覧を手で保守する必要はない。

終了コード:
    0  未対応・確認待ちが無く、不備なし（指摘が0件でも 0）
    1  未対応・確認待ちが残っている、または対応の書き漏れなどの不備がある
    2  引数の誤り、ファイルが読めない、指摘の表が1つも見つからない

依存は標準ライブラリのみ。
"""

import argparse
import re
import sys

COL_ID = {"id"}
COL_STATUS = {"状態", "status"}
COL_ACTION = {"対応", "対応内容"}
COL_COMMENT = {"指摘", "コメント"}
OPEN = {"未対応", "確認待ち"}
CLOSED = {"対応済み", "見送り"}
ORDER = ["未対応", "確認待ち", "対応済み", "見送り"]
EMPTY = {"", "-", "—"}
SEP_RE = re.compile(r":?-{2,}:?")
CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
FENCE_RE = re.compile(r"^(```|~~~)")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip() for c in CELL_SPLIT_RE.split(s)]


def read_tables(lines):
    tables, current, in_fence = [], None, False
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if FENCE_RE.match(s):
            in_fence, current = not in_fence, None
            continue
        if in_fence or not s.startswith("|"):
            current = None
            continue
        cells = split_row(s)
        if any(cells) and all(SEP_RE.fullmatch(c) for c in cells if c):
            continue
        if current is None:
            current = (n, [c.lower() for c in cells], [])
            tables.append(current)
        else:
            current[2].append((n, cells))
    return tables


def col(header, names):
    for i, c in enumerate(header):
        if c in names:
            return i
    return None


def check(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except OSError as e:
        return None, ["読み込めない (%s)" % e], {}
    errors = []
    counts = dict((s, 0) for s in ORDER)
    seen = set()
    found = False
    for hn, header, rows in read_tables(lines):
        c_id, c_st, c_ac, c_cm = (col(header, COL_ID), col(header, COL_STATUS),
                                  col(header, COL_ACTION), col(header, COL_COMMENT))
        if c_id is None or c_st is None or c_cm is None:
            continue
        found = True
        if c_ac is None:
            errors.append("%s:%d: 対応列がない" % (path, hn))
            continue
        for n, cells in rows:
            where = "%s:%d" % (path, n)
            if len(cells) != len(header):
                errors.append("%s: 列数が見出しと一致しない（%d 列、見出しは %d 列）"
                              % (where, len(cells), len(header)))
                continue
            rid = cells[c_id]
            if not rid or "〔" in rid:  # 雛形の行（ID が〔〕のまま）は数えない
                continue
            if rid in seen:
                errors.append("%s: 指摘IDが重複している: %s" % (where, rid))
            seen.add(rid)
            status = cells[c_st]
            if status not in OPEN and status not in CLOSED:
                errors.append("%s: %s の状態が不正: '%s'（%s のどれか）" % (where, rid, status, " / ".join(ORDER)))
                continue
            counts[status] += 1
            action = cells[c_ac]
            if status in OPEN:
                errors.append("%s: %s が %s のまま残っている: %s" % (where, rid, status, cells[c_cm][:60]))
            elif action in EMPTY or "〔" in action:
                what = "何をどこで変えたか" if status == "対応済み" else "見送る理由とユーザーの了承"
                errors.append("%s: %s は%sだが対応が空。%sを書くこと" % (where, rid, status, what))
    if not found:
        return None, ["ID・指摘・状態の列を持つ表が見つからない。"
                      "レビュー記録の雛形（review-log 部品の REVIEW_LOG.md）の形式を確認すること"], {}
    return True, errors, counts


def main(argv):
    ap = argparse.ArgumentParser(description="レビュー記録の未対応・書き漏れの検査")
    ap.add_argument("log", help="REVIEW_LOG.md のパス")
    args = ap.parse_args(argv)
    ok, errors, counts = check(args.log)
    for e in errors:
        print("ERROR  %s" % e)
    if ok is None:
        return 2
    print()
    print("指摘 %d 件（%s）" % (sum(counts.values()), " / ".join("%s %d" % (s, counts[s]) for s in ORDER)))
    print("ERROR %d 件" % len(errors))
    if errors:
        print("不合格。未対応・確認待ちを残したまま次の工程に進まないこと。")
        return 1
    print("合格。未対応の指摘はない。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
