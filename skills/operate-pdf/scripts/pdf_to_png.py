#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF の各ページを PNG にする（見た目を画像で確かめる用）。

    python pdf_to_png.py <pdf> [--outdir DIR] [--dpi 100] [--pages 1-3,5] [--max-pages 30]

出力: <outdir>/<pdf名>-p01.png …（ページ番号はページ数の桁でゼロ詰め）。outdir の既定は PDF と同じフォルダ。
書き出したパスを1行ずつ標準出力に出す。--pages を省くと先頭から --max-pages ページまで。
フォームの記入値も描く（ビューアと同じく、外観を作り直して表示する）。

終了コード:
    0  書き出した
    1  PDF を開けない（壊れている・パスワード付き）
    2  引数の指定ミス（--pages の書式違い・範囲外を含む）、または依存パッケージが無い

依存: pypdfium2, Pillow（pip install pypdfium2 pillow）
"""

import argparse
import re
import sys
from pathlib import Path


def parse_pages(spec, total):
    """'1-3,5' → [0, 1, 2, 4]（0始まり）。書式違い・逆順・範囲外は ValueError。"""
    if not re.fullmatch(r"\d+(-\d+)?(,\d+(-\d+)?)*", spec.replace(" ", "")):
        raise ValueError("ページ指定の書式が違う: %s（例 1-3,5）" % spec)
    pages = []
    for part in spec.replace(" ", "").split(","):
        a, _, b = part.partition("-")
        start, end = int(a), int(b or a)
        if not 1 <= start <= end <= total:
            raise ValueError("ページ指定が範囲外か逆順: %s（全 %d ページ）" % (part, total))
        pages.extend(p for p in range(start - 1, end) if p not in pages)
    return pages


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="PDF をページごとの PNG にする")
    ap.add_argument("pdf")
    ap.add_argument("--outdir")
    ap.add_argument("--dpi", type=int, default=100)
    ap.add_argument("--pages", help="例: 1-3,5（1始まり）")
    ap.add_argument("--max-pages", type=int, default=30)
    args = ap.parse_args()

    try:
        import pypdfium2 as pdfium
        import PIL  # noqa: F401  render().to_pil() が使う
    except ImportError:
        print("pypdfium2 と Pillow が必要: pip install pypdfium2 pillow", file=sys.stderr)
        return 2

    src = Path(args.pdf).resolve()
    if not src.is_file():
        print("入力が存在しない: %s" % src, file=sys.stderr)
        return 2
    outdir = Path(args.outdir).resolve() if args.outdir else src.parent
    outdir.mkdir(parents=True, exist_ok=True)

    try:
        doc = pdfium.PdfDocument(str(src))
    except Exception as e:  # pypdfium2 は壊れた PDF・パスワード付きで PdfiumError を出す
        print("PDF を開けない: %s (%s)" % (src, e), file=sys.stderr)
        return 1

    # フォームの記入値を描く。これが無いとフィールドが1つも画像に出ない
    doc.init_forms()
    total = len(doc)
    if args.pages:
        try:
            targets = parse_pages(args.pages, total)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
    else:
        targets = list(range(min(total, args.max_pages)))
        if total > args.max_pages:
            print("全 %d ページのうち先頭 %d ページだけ書き出す（--pages で指定できる）"
                  % (total, args.max_pages), file=sys.stderr)

    width = max(2, len(str(total)))
    scale = args.dpi / 72.0
    for i in targets:
        image = doc[i].render(scale=scale).to_pil()
        out = outdir / ("%s-p%0*d.png" % (src.stem, width, i + 1))
        image.save(out)
        print(out)
    doc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
