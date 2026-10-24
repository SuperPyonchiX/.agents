#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Excel ブックの数式を再計算し、エラーになっているセルを洗い出す。

    python recalc_check.py <xlsx> [--engine auto|soffice|office] [--write-back]

openpyxl は数式の値を計算しないので、書いた数式が正しく評価されるかは表計算ソフトに計算させないと分からない。
このスクリプトはブックを一時フォルダにコピーし、コピーを再計算してから値を読む。元のファイルは変えない。
--write-back を付けると、Excel（office エンジン）で元のファイルを再計算して保存する
（計算結果を読む別のプログラムに渡すとき用。LibreOffice では書式が変わるので使えない）。

変換エンジン:
    soffice  LibreOffice で読み込み → xlsx で書き出すときに再計算させる。LibreOffice は計算結果が
             保存済みのセルを再計算しないので、コピーから数式セルの計算結果を消してから渡す
    office   Windows の MS Excel を PowerShell 経由の COM で操作し、CalculateFull してから保存する
    auto     soffice が見つかればそれ、無ければ Windows なら office（既定）

再計算後のブックは XML を直接読む（配列数式・共有数式も数える。空文字を返す数式は未計算と数えない）。

出力（JSON、1行）:
    engine         使ったエンジン
    formulas       数式セルの数
    errors         エラーのセル（先頭50件）[{sheet, cell, error, formula}]
    error_summary  エラーの種類ごとの件数
    uncalculated   再計算後も計算結果を持たない数式セルの数。0 でなければ再計算が効いていない（engine を変えて試す）

終了コード:
    0  エラーなし（uncalculated も 0）
    1  エラーのセルがある、または uncalculated が 0 でない
    2  引数の指定ミス、入力が存在しない、.xlsx / .xlsm 以外
    3  再計算に使えるエンジンが無い、再計算に失敗した、または時間切れ（10分）

依存: 標準ライブラリのみ。再計算には LibreOffice か Windows の MS Excel が要る
"""

import argparse
import json
import os
import platform
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_LISTED = 50
TIMEOUT = 600
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
# 数式セルの計算結果 <v> を消す。<f> の直後に <v> が来るのは OOXML の要素順で決まっている
CACHED_VALUE_RE = re.compile(rb"(<f\b[^>]*/>|<f\b[^>]*>[^<]*</f>)<v>[^<]*</v>")

PS_EXCEL = r"""
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject Excel.Application
try {
  $app.AutomationSecurity = 3  # マクロを実行しない
  $app.Visible = $false
  $app.DisplayAlerts = $false
  $book = $app.Workbooks.Open($env:RECALC_PATH, 0, $false)
  try {
    $app.CalculateFull()
    $book.Save()
  } finally { $book.Close($false) }
} finally { $app.Quit() }
"""


def find_soffice():
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for c in (r"C:\Program Files\LibreOffice\program\soffice.exe",
              r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
              "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if os.path.isfile(c):
            return c
    return None


def recalc_office(path):
    env = dict(os.environ, RECALC_PATH=str(path))
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_EXCEL],
                       capture_output=True, text=True, env=env, timeout=TIMEOUT)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        return False
    return True


def strip_cached_values(src, dst):
    """src の数式セルから計算結果を消したコピーを dst に作る。"""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.startswith("xl/worksheets/") and info.filename.endswith(".xml"):
                data = CACHED_VALUE_RE.sub(rb"\1", data)
            zout.writestr(info, data)


def recalc_soffice(soffice, path, workdir):
    """path を LibreOffice で読み直して書き出したファイルのパスを返す。"""
    stripped = Path(workdir) / ("in" + path.suffix.lower())
    strip_cached_values(path, stripped)
    outdir = Path(workdir) / "lo-out"
    outdir.mkdir()
    profile = Path(workdir) / "lo-profile"
    cmd = [soffice, "-env:UserInstallation=" + profile.as_uri(), "--headless",
           "--convert-to", "xlsx", "--outdir", str(outdir), str(stripped)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    out = outdir / (stripped.stem + ".xlsx")
    if r.returncode != 0 or not out.is_file():
        sys.stderr.write(r.stdout + r.stderr)
        return None
    return out


def sheet_parts(z):
    """[(シート名, zip 内のパス)] をシートの並び順で返す。"""
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = {}
    for rel in rels.iter(NS_PKG + "Relationship"):
        t = rel.get("Target")
        target[rel.get("Id")] = t.lstrip("/") if t.startswith("/") else posixpath.normpath("xl/" + t)
    book = ET.fromstring(z.read("xl/workbook.xml"))
    return [(s.get("name"), target[s.get(NS_R + "id")]) for s in book.iter(NS + "sheet")
            if target.get(s.get(NS_R + "id"), "").startswith("xl/worksheets/")]


def scan(calculated):
    formulas = 0
    uncalculated = 0
    errors = []
    summary = Counter()
    with zipfile.ZipFile(calculated) as z:
        for name, part in sheet_parts(z):
            shared = {}  # 共有数式の si → 式を持つセル
            with z.open(part) as f:
                for _, el in ET.iterparse(f):
                    if el.tag != NS + "c":
                        continue
                    fe = el.find(NS + "f")
                    ve = el.find(NS + "v")
                    formula = None
                    if fe is not None:
                        formulas += 1
                        if ve is None:
                            uncalculated += 1
                        if fe.text:
                            formula = "=" + fe.text
                            if fe.get("t") == "shared":
                                shared[fe.get("si")] = el.get("r")
                        elif fe.get("t") == "shared":
                            formula = "（%s の共有数式）" % shared.get(fe.get("si"), "?")
                    if el.get("t") == "e" and ve is not None:
                        summary[ve.text] += 1
                        if len(errors) < MAX_LISTED:
                            errors.append({"sheet": name, "cell": el.get("r"), "error": ve.text,
                                           "formula": formula})
                    el.clear()
    return formulas, uncalculated, errors, summary


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="数式を再計算してエラーのセルを洗い出す")
    ap.add_argument("xlsx")
    ap.add_argument("--engine", choices=["auto", "soffice", "office"], default="auto")
    ap.add_argument("--write-back", action="store_true", help="Excel で元のファイルを再計算して保存する")
    args = ap.parse_args()

    src = Path(args.xlsx).resolve()
    if not src.is_file():
        print("入力が存在しない: %s" % src, file=sys.stderr)
        return 2
    if src.suffix.lower() not in (".xlsx", ".xlsm"):
        print(".xlsx / .xlsm のみ対応", file=sys.stderr)
        return 2

    is_windows = platform.system() == "Windows" and shutil.which("powershell")
    soffice = find_soffice() if args.engine in ("auto", "soffice") and not args.write_back else None
    if args.write_back and not is_windows:
        print("--write-back は Windows の MS Excel でのみ使える", file=sys.stderr)
        return 3

    with tempfile.TemporaryDirectory() as work:
        try:
            if args.write_back:
                engine = "office"
                calculated = src if recalc_office(src) else None
            elif soffice:
                engine = "soffice"
                calculated = recalc_soffice(soffice, src, work)
            elif args.engine in ("auto", "office") and is_windows:
                engine = "office"
                calculated = Path(work) / src.name
                shutil.copy2(src, calculated)
                if not recalc_office(calculated):
                    calculated = None
            else:
                print("再計算に使えるエンジンが無い（LibreOffice も Windows の MS Excel も使えない）", file=sys.stderr)
                return 3
        except subprocess.TimeoutExpired:
            print("再計算が %d 秒で終わらなかった（engine=%s）" % (TIMEOUT, engine), file=sys.stderr)
            return 3
        if calculated is None:
            print("再計算に失敗した（engine=%s）" % engine, file=sys.stderr)
            return 3
        try:
            formulas, uncalculated, errors, summary = scan(calculated)
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
            print("再計算後のブックを読めない: %s" % e, file=sys.stderr)
            return 3

    result = {"engine": engine, "formulas": formulas, "errors": errors,
              "error_summary": dict(summary), "uncalculated": uncalculated}
    print(json.dumps(result, ensure_ascii=False))
    if sum(summary.values()) > MAX_LISTED:
        print("エラーは %d 件。先頭 %d 件だけ列挙した" % (sum(summary.values()), MAX_LISTED), file=sys.stderr)
    return 1 if summary or uncalculated else 0


if __name__ == "__main__":
    sys.exit(main())
