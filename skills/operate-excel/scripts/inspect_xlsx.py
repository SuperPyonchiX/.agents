#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Excel ブックの構造を、中身を全件読まずに把握する。

    python inspect_xlsx.py <xlsx> [--sheet NAME] [--rows 10] [--cols 15]

出力（Markdown）:
    - ブック全体: シート一覧（非表示を含む）、名前付き範囲、openpyxl で保存すると失われる恐れのある要素
    - シートごと: 使用範囲、行数・列数、数式セル数、結合セル、ウィンドウ枠の固定、印刷範囲、
      テーブル、入力規則・条件付き書式の数、先頭 --rows 行 × --cols 列のプレビュー
      （数式セルは「=式 → 保存されている計算結果」で表示）

終了コード:
    0  出力した
    1  開けない（壊れている、パスワード付き）
    2  引数の指定ミス、入力が存在しない、.xls など openpyxl が読めない形式、または openpyxl が無い

依存: openpyxl（pip install openpyxl）
"""

import argparse
import re
import sys
import zipfile
from pathlib import Path

# zip 内のパターン → openpyxl で読み込んで保存したときに起きること
AT_RISK = [
    (r"^xl/vbaProject\.bin$", "マクロ（VBA）。keep_vba=True で開き .xlsm で保存しないと消える"),
    (r"^xl/pivotTables/", "ピボットテーブル。保持はされるが更新・編集はできない"),
    (r"^xl/slicers/|^xl/slicerCaches/", "スライサー。保存すると消える"),
    (r"^xl/timelines/", "タイムライン。保存すると消える"),
    (r"^xl/ctrlProps/", "フォームコントロール（ボタン・チェックボックス）。保存すると消える"),
    (r"^xl/externalLinks/", "外部ブックへのリンク。リンク先の値は更新されない"),
    (r"^xl/drawings/vmlDrawing", "コメントの書式・図形（VML）。書式が失われることがある"),
]
SHAPE_RE = re.compile(rb"<xdr:sp[ >]")


def at_risk_items(path):
    items = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        for pattern, message in AT_RISK:
            if any(re.search(pattern, n) for n in names):
                items.append(message)
        for n in names:
            if n.startswith("xl/drawings/drawing") and n.endswith(".xml"):
                if SHAPE_RE.search(z.read(n)):
                    items.append("図形・テキストボックス（%s）。保存すると消える" % n)
    return items


def cell_text(cell, value_cell, limit=40):
    v = cell.value
    if v is None:
        return ""
    if isinstance(v, str) and v.startswith("="):
        cached = value_cell.value
        s = "%s → %s" % (v, "（未計算）" if cached is None else cached)
    else:
        s = str(v)
    s = s.replace("\n", " ").replace("|", "\\|")
    return s if len(s) <= limit else s[: limit - 1] + "…"


def describe_sheet(ws, ws_values, rows, cols):
    from openpyxl.utils import get_column_letter
    out = []
    state = "" if ws.sheet_state == "visible" else "（%s）" % ws.sheet_state
    out.append("## %s%s" % (ws.title, state))
    out.append("")
    formulas = sum(1 for row in ws.iter_rows() for c in row
                   if isinstance(c.value, str) and c.value.startswith("="))
    merged = [str(r) for r in ws.merged_cells.ranges]
    facts = [
        ("使用範囲", ws.dimensions),
        ("行数 × 列数", "%d × %d" % (ws.max_row, ws.max_column)),
        ("数式セル", formulas),
        ("結合セル", "%d 件 %s" % (len(merged), ", ".join(merged[:10]) + (" …" if len(merged) > 10 else ""))),
        ("ウィンドウ枠の固定", ws.freeze_panes or "なし"),
        ("印刷範囲", ws.print_area or "なし"),
        ("テーブル", ", ".join("%s(%s)" % (t.name, t.ref) for t in ws.tables.values()) or "なし"),
        ("入力規則", len(ws.data_validations.dataValidation)),
        ("条件付き書式", len(ws.conditional_formatting)),
    ]
    for k, v in facts:
        out.append("- %s: %s" % (k, v))
    out.append("")

    max_r = min(ws.max_row, rows)
    max_c = min(ws.max_column, cols)
    if max_r == 0 or max_c == 0 or ws.max_row == 1 and ws.max_column == 1 and ws["A1"].value is None:
        out.append("（空のシート）")
        return out
    header = ["行"] + [get_column_letter(c) for c in range(1, max_c + 1)]
    out.append("| " + " | ".join(header) + " |")
    out.append("|" + "---|" * len(header))
    for r in range(1, max_r + 1):
        cells = [cell_text(ws.cell(r, c), ws_values.cell(r, c)) for c in range(1, max_c + 1)]
        out.append("| %d | %s |" % (r, " | ".join(cells)))
    if ws.max_row > rows or ws.max_column > cols:
        out.append("")
        out.append("（先頭 %d 行 × %d 列のみ。全体は %d 行 × %d 列）" % (max_r, max_c, ws.max_row, ws.max_column))
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Excel ブックの構造を出す")
    ap.add_argument("xlsx")
    ap.add_argument("--sheet", help="このシートだけ出す")
    ap.add_argument("--rows", type=int, default=10)
    ap.add_argument("--cols", type=int, default=15)
    args = ap.parse_args()

    try:
        import openpyxl
    except ImportError:
        print("openpyxl が必要: pip install openpyxl", file=sys.stderr)
        return 2
    path = Path(args.xlsx)
    if not path.is_file():
        print("入力が存在しない: %s" % path, file=sys.stderr)
        return 2
    if path.suffix.lower() not in (".xlsx", ".xlsm", ".xltx", ".xltm"):
        print("openpyxl は %s を読めない。Excel か LibreOffice で .xlsx に変換してから扱う" % path.suffix,
              file=sys.stderr)
        return 2
    try:
        wb = openpyxl.load_workbook(path)
        wb_values = openpyxl.load_workbook(path, data_only=True)
        risks = at_risk_items(path)
    except (zipfile.BadZipFile, OSError, KeyError) as e:
        print("開けない（壊れているかパスワード付き）: %s (%s)" % (path, e), file=sys.stderr)
        return 1

    lines = ["# %s" % path.name, ""]
    lines.append("- シート: " + ", ".join(
        ws.title + ("" if ws.sheet_state == "visible" else "（%s）" % ws.sheet_state) for ws in wb.worksheets))
    names = list(wb.defined_names.keys()) if hasattr(wb.defined_names, "keys") else []
    lines.append("- 名前付き範囲: " + (", ".join(names) if names else "なし"))
    if risks:
        lines.append("- **openpyxl で保存すると失われる・壊れる恐れのある要素**:")
        lines += ["  - " + r for r in risks]
    else:
        lines.append("- openpyxl で保存して失われる要素: 検出なし")
    lines.append("")

    targets = [wb[args.sheet]] if args.sheet else wb.worksheets
    if args.sheet and args.sheet not in wb.sheetnames:
        print("シートが無い: %s（あるのは %s）" % (args.sheet, ", ".join(wb.sheetnames)), file=sys.stderr)
        return 2
    for ws in targets:
        lines += describe_sheet(ws, wb_values[ws.title], args.rows, args.cols)
        lines.append("")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
