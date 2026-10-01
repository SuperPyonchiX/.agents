#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Word / Excel / PowerPoint ファイルを PDF に変換する（見た目の確認用）。

    python to_pdf.py <input> [--outdir DIR] [--engine auto|soffice|office]

変換エンジン:
    soffice  LibreOffice のヘッドレス変換。OS を問わない
    office   Windows の MS Office を PowerShell 経由の COM で操作する（Word / Excel / PowerPoint）
    auto     soffice が見つかればそれ、無ければ Windows なら office（既定）

対応する拡張子: .docx .doc .dotx .xlsx .xlsm .xls .pptx .ppt .potx .odt .ods .odp .rtf
出力: <outdir>/<入力の拡張子なしの名前>.pdf。outdir の既定は入力と同じフォルダ。
成功時は出力パスを1行だけ標準出力に出す。

終了コード:
    0  変換した
    1  変換に失敗した（エンジンのエラーを標準エラーに出す）
    2  引数の指定ミス、または入力が存在しない
    3  使える変換エンジンが無い（描画確認は手動に回す）

依存は標準ライブラリのみ。
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORD_EXT = {".docx", ".doc", ".dotx", ".odt", ".rtf"}
EXCEL_EXT = {".xlsx", ".xlsm", ".xls", ".ods"}
PPT_EXT = {".pptx", ".ppt", ".potx", ".odp"}

# 入出力パスは環境変数で渡す。PowerShell の引用符処理にパスを通さないため
PS_WORD = r"""
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject Word.Application
try {
  $app.AutomationSecurity = 3  # マクロを実行しない
  $app.Visible = $false
  $app.DisplayAlerts = 0
  $doc = $app.Documents.Open($env:TOPDF_IN, $false, $true)
  try { $doc.ExportAsFixedFormat($env:TOPDF_OUT, 17) } finally { $doc.Close($false) }
} finally { $app.Quit() }
"""

PS_EXCEL = r"""
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject Excel.Application
try {
  $app.AutomationSecurity = 3  # マクロを実行しない
  $app.Visible = $false
  $app.DisplayAlerts = $false
  $book = $app.Workbooks.Open($env:TOPDF_IN, 0, $true)
  try { $book.ExportAsFixedFormat(0, $env:TOPDF_OUT) } finally { $book.Close($false) }
} finally { $app.Quit() }
"""

PS_PPT = r"""
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject PowerPoint.Application
try {
  $app.AutomationSecurity = 3  # マクロを実行しない
  # ReadOnly=true, Untitled=false, WithWindow=false
  $pres = $app.Presentations.Open($env:TOPDF_IN, -1, 0, 0)
  try { $pres.SaveAs($env:TOPDF_OUT, 32) } finally { $pres.Close() }
} finally { $app.Quit() }
"""


def find_soffice():
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def office_available():
    return platform.system() == "Windows" and shutil.which("powershell") is not None


def convert_soffice(soffice, src, outdir):
    # 起動中の LibreOffice とプロファイルを奪い合わないよう、使い捨てのプロファイルを使う
    with tempfile.TemporaryDirectory() as profile:
        cmd = [
            soffice,
            "-env:UserInstallation=" + Path(profile).as_uri(),
            "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(src),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    out = outdir / (src.stem + ".pdf")
    if r.returncode != 0 or not out.is_file():
        sys.stderr.write(r.stdout + r.stderr)
        return None
    return out


def convert_office(src, outdir):
    ext = src.suffix.lower()
    if ext in WORD_EXT:
        script = PS_WORD
    elif ext in EXCEL_EXT:
        script = PS_EXCEL
    else:
        script = PS_PPT
    out = outdir / (src.stem + ".pdf")
    env = dict(os.environ, TOPDF_IN=str(src), TOPDF_OUT=str(out))
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, env=env, timeout=300,
    )
    if r.returncode != 0 or not out.is_file():
        sys.stderr.write(r.stdout + r.stderr)
        return None
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Office ファイルを PDF に変換する")
    ap.add_argument("input")
    ap.add_argument("--outdir")
    ap.add_argument("--engine", choices=["auto", "soffice", "office"], default="auto")
    args = ap.parse_args()

    src = Path(args.input).resolve()
    if not src.is_file():
        print("入力が存在しない: %s" % src, file=sys.stderr)
        return 2
    if src.suffix.lower() not in WORD_EXT | EXCEL_EXT | PPT_EXT:
        print("対応していない拡張子: %s" % src.suffix, file=sys.stderr)
        return 2
    outdir = Path(args.outdir).resolve() if args.outdir else src.parent
    outdir.mkdir(parents=True, exist_ok=True)

    soffice = find_soffice() if args.engine in ("auto", "soffice") else None
    if soffice:
        out = convert_soffice(soffice, src, outdir)
    elif args.engine in ("auto", "office") and office_available():
        out = convert_office(src, outdir)
    else:
        print("変換エンジンが無い（LibreOffice も Windows の MS Office も使えない）。描画確認は手動で行う",
              file=sys.stderr)
        return 3

    if out is None:
        print("変換に失敗した: %s" % src, file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
