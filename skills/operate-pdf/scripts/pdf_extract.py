#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF から中身を取り出す。

    python pdf_extract.py meta   <pdf>
    python pdf_extract.py text   <pdf> [--pages 1-3] [--layout] [--out FILE]
    python pdf_extract.py tables <pdf> [--pages 1-3]
    python pdf_extract.py images <pdf> --outdir DIR [--pages 1-3]

meta    ページ数・用紙サイズ・暗号化・フォーム有無・しおり数・文書情報を JSON で出す。最初に必ずこれを見る
text    ページごとに "=== page N ===" で区切ってテキストを出す。--layout は段組みの位置を保つ
tables  表を Markdown の表にして出す（pdfplumber が必要）
images  埋め込み画像をファイルに書き出し、パスを1行ずつ出す

終了コード:
    0  取り出した
    1  取り出せなかった（text で文字がほぼ無い＝スキャン PDF の疑い、tables で表が0件、
       パスワード付きで開けない）
    2  引数の指定ミス、または依存パッケージが無い

依存: pypdf（pip install pypdf）。tables のみ pdfplumber（pip install pdfplumber）
"""

import argparse
import json
import sys
from pathlib import Path

# 1ページあたりこれ未満の文字数ならスキャン PDF を疑う
MIN_CHARS_PER_PAGE = 20


def parse_pages(spec, total):
    if not spec:
        return list(range(total))
    pages = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        pages.extend(p - 1 for p in range(start, end + 1) if 1 <= p <= total)
    return pages


def open_reader(path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        # 閲覧パスワードが空のもの（印刷・編集だけ制限）はこれで開ける
        if not reader.decrypt(""):
            return None
    return reader


def cmd_meta(reader, args):
    first = reader.pages[0] if reader.pages else None
    size = None
    if first is not None:
        w, h = float(first.mediabox.width), float(first.mediabox.height)
        size = {"width_pt": round(w, 1), "height_pt": round(h, 1),
                "width_mm": round(w / 72 * 25.4, 1), "height_mm": round(h / 72 * 25.4, 1)}
    info = {}
    if reader.metadata:
        for k, v in reader.metadata.items():
            info[str(k).lstrip("/")] = str(v)
    fields = reader.get_fields() or {}
    result = {
        "pages": len(reader.pages),
        "first_page_size": size,
        "encrypted": reader.is_encrypted,
        "form_fields": len(fields),
        "outline_items": len(reader.outline) if reader.outline else 0,
        "metadata": info,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_text(reader, args):
    pages = parse_pages(args.pages, len(reader.pages))
    chunks = []
    total_chars = 0
    for i in pages:
        page = reader.pages[i]
        if args.layout:
            text = page.extract_text(extraction_mode="layout")
        else:
            text = page.extract_text()
        text = text or ""
        total_chars += len(text.strip())
        chunks.append("=== page %d ===\n%s" % (i + 1, text))
    body = "\n\n".join(chunks)
    if args.out:
        Path(args.out).write_text(body, encoding="utf-8")
        print(args.out)
    else:
        print(body)
    if pages and total_chars < MIN_CHARS_PER_PAGE * len(pages):
        print("文字がほとんど取れない（%d 文字 / %d ページ）。スキャン PDF の疑い。OCR が要る"
              % (total_chars, len(pages)), file=sys.stderr)
        return 1
    return 0


def md_table(rows):
    rows = [[("" if c is None else str(c).replace("\n", " ").replace("|", "\\|")) for c in r] for r in rows]
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def cmd_tables(path, args):
    try:
        import pdfplumber
    except ImportError:
        print("tables には pdfplumber が必要: pip install pdfplumber", file=sys.stderr)
        return 2
    count = 0
    with pdfplumber.open(str(path)) as pdf:
        for i in parse_pages(args.pages, len(pdf.pages)):
            for j, table in enumerate(pdf.pages[i].extract_tables(), 1):
                if not table or not any(any(c for c in r) for r in table):
                    continue
                count += 1
                print("=== page %d table %d ===" % (i + 1, j))
                print(md_table(table))
                print()
    if count == 0:
        print("表が見つからない。罫線の無い表は text --layout で読む", file=sys.stderr)
        return 1
    return 0


def cmd_images(reader, args, path):
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    count = 0
    for i in parse_pages(args.pages, len(reader.pages)):
        for j, img in enumerate(reader.pages[i].images, 1):
            out = outdir / ("%s-p%d-%d%s" % (path.stem, i + 1, j, Path(img.name).suffix or ".bin"))
            out.write_bytes(img.data)
            print(out)
            count += 1
    if count == 0:
        print("埋め込み画像が無い", file=sys.stderr)
        return 1
    return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="PDF から中身を取り出す")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("meta")
    p.add_argument("pdf")
    p = sub.add_parser("text")
    p.add_argument("pdf")
    p.add_argument("--pages")
    p.add_argument("--layout", action="store_true")
    p.add_argument("--out")
    p = sub.add_parser("tables")
    p.add_argument("pdf")
    p.add_argument("--pages")
    p = sub.add_parser("images")
    p.add_argument("pdf")
    p.add_argument("--outdir", required=True)
    p.add_argument("--pages")
    args = ap.parse_args()

    path = Path(args.pdf)
    if not path.is_file():
        print("入力が存在しない: %s" % path, file=sys.stderr)
        return 2
    if args.cmd == "tables":
        return cmd_tables(path, args)

    try:
        import pypdf  # noqa: F401
    except ImportError:
        print("pypdf が必要: pip install pypdf", file=sys.stderr)
        return 2
    reader = open_reader(path)
    if reader is None:
        print("パスワード付きで開けない。pdf_ops.py decrypt で解除してから読む", file=sys.stderr)
        return 1
    if args.cmd == "meta":
        return cmd_meta(reader, args)
    if args.cmd == "text":
        return cmd_text(reader, args)
    return cmd_images(reader, args, path)


if __name__ == "__main__":
    sys.exit(main())
