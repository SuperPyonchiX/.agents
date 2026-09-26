#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""確認シート（Markdown の表 または CSV）の結果を集計し、次の回のシートを切り出す。

    python sheet.py summary <sheet>
    python sheet.py next <sheet> -o <次の回のシート> [--round N]

シートの列（この順・この名前。CSV も同じ）:
    ID | 区分 | 確認すること | 手順 | 期待結果 | 結果 | メモ

    ID     S-01（スモーク）/ T-01（本体）/ R-01（回帰）。重複禁止
    区分   スモーク / 本体 / 回帰
    結果   OK / NG / 未実施 / 保留 のどれか。空欄は未記入として扱う

summary  件数・NG の ID・未記入の ID を JSON で標準出力へ出す
next     NG・未実施・未記入の行と、回帰（R-）の全行を、結果を空にして書き出す。
         OK と 保留 の行は載せない。前回のメモは「前回: 」を付けてメモ欄に残す

終了コード:
    0  summary: 全行が OK か保留（完了） / next: 書き出した
    1  summary: NG・未実施・未記入が残っている / next: 載せる行が0件（完了済み）
    2  引数の指定ミス、表が見つからない、列が足りない、ID の重複、結果欄に不正な値

依存は標準ライブラリのみ。
"""

import argparse
import csv
import io
import json
import os
import re
import sys

COLUMNS = ["ID", "区分", "確認すること", "手順", "期待結果", "結果", "メモ"]
RESULTS = {"OK", "NG", "未実施", "保留", ""}
CARRY = {"NG", "未実施", ""}


class SheetError(Exception):
    pass


def split_row(line):
    cells = line.strip()
    if cells.startswith("|"):
        cells = cells[1:]
    if cells.endswith("|"):
        cells = cells[:-1]
    # エスケープされた \| はセル内の文字として扱う
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", cells)]


def read_md(text):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        header = split_row(line)
        if "ID" in header and "結果" in header:
            rows = []
            for body in lines[i + 2:]:
                if not body.lstrip().startswith("|"):
                    break
                rows.append(split_row(body))
            return header, rows
    raise SheetError("ID と 結果 の列を持つ表が見つからない")


def read_csv(text):
    reader = list(csv.reader(io.StringIO(text)))
    if not reader:
        raise SheetError("CSV が空")
    return reader[0], reader[1:]


def load(path):
    if not os.path.isfile(path):
        raise SheetError("%s: ファイルがない" % path)
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    fmt = "csv" if path.lower().endswith(".csv") else "md"
    header, rows = read_csv(text) if fmt == "csv" else read_md(text)
    header = [h.strip() for h in header]
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise SheetError("列が足りない: %s" % ", ".join(missing))
    idx = {c: header.index(c) for c in COLUMNS}
    items, seen = [], set()
    for r in rows:
        if not any(x.strip() for x in r):
            continue
        r = r + [""] * (len(header) - len(r))
        item = {c: r[idx[c]].strip() for c in COLUMNS}
        if not item["ID"]:
            raise SheetError("ID が空の行がある: %s" % item["確認すること"])
        if item["ID"] in seen:
            raise SheetError("ID が重複している: %s" % item["ID"])
        seen.add(item["ID"])
        if item["結果"] not in RESULTS:
            raise SheetError("%s: 結果欄の値が不正 '%s'（OK / NG / 未実施 / 保留 / 空欄）"
                             % (item["ID"], item["結果"]))
        items.append(item)
    if not items:
        raise SheetError("行が1件もない")
    return fmt, items


def summarize(items):
    by = {k: [i["ID"] for i in items if i["結果"] == k] for k in ("OK", "NG", "未実施", "保留")}
    blank = [i["ID"] for i in items if i["結果"] == ""]
    smoke_ng = [i["ID"] for i in items if i["ID"].startswith("S-") and i["結果"] == "NG"]
    return {
        "total": len(items),
        "counts": {"OK": len(by["OK"]), "NG": len(by["NG"]), "未実施": len(by["未実施"]),
                   "保留": len(by["保留"]), "未記入": len(blank)},
        "ng": by["NG"],
        "not_run": by["未実施"],
        "blank": blank,
        "on_hold": by["保留"],
        "smoke_ng": smoke_ng,
        "done": not (by["NG"] or by["未実施"] or blank),
    }


def write(path, fmt, items, round_no):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if fmt == "csv":
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            for i in items:
                w.writerow([i[c] for c in COLUMNS])
        return
    esc = lambda s: s.replace("|", "\\|").replace("\n", "<br>")
    out = []
    if round_no:
        out.append("# 確認シート 第%d回\n" % round_no)
    out.append("| " + " | ".join(COLUMNS) + " |")
    out.append("|" + "---|" * len(COLUMNS))
    for i in items:
        out.append("| " + " | ".join(esc(i[c]) for c in COLUMNS) + " |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="確認シートの集計と次の回の切り出し")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("summary")
    s.add_argument("sheet")
    n = sub.add_parser("next")
    n.add_argument("sheet")
    n.add_argument("-o", "--output", required=True)
    n.add_argument("--round", type=int, default=0, help="見出しに入れる回数（Markdown のみ）")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    if not args.cmd:
        ap.print_usage()
        return 2

    try:
        fmt, items = load(args.sheet)
    except SheetError as e:
        print("ERROR  %s" % e)
        return 2

    if args.cmd == "summary":
        result = summarize(items)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["done"] else 1

    out_fmt = "csv" if args.output.lower().endswith(".csv") else "md"
    carried = []
    for i in items:
        if i["結果"] in CARRY or i["ID"].startswith("R-"):
            memo = ("前回: " + i["メモ"]) if i["メモ"] else ""
            carried.append(dict(i, 結果="", メモ=memo))
    if not carried:
        print("次の回に載せる行がない（全行が OK か保留）")
        return 1
    write(args.output, out_fmt, carried, args.round)
    print("%d 行を書き出した: %s" % (len(carried), args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
