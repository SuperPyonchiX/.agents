#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF から中身を取り出す。

    python pdf_extract.py meta   <pdf>
    python pdf_extract.py text   <pdf> [--pages 1-3] [--layout] [--out FILE]
    python pdf_extract.py tables <pdf> [--pages 1-3] [--out FILE]
    python pdf_extract.py images <pdf> --outdir DIR [--pages 1-3]

meta    ページ数・ページごとの用紙サイズと回転・暗号化・フォーム有無・しおり数・文書情報を JSON で出す。
        最初に必ずこれを見る。結合・分割・回転の結果もこれで確かめられる
text    ページごとに "=== page N ===" で区切ってテキストを出す。--layout は段組みの位置を保つ。
        2万字を超えるときは --out が要る（付けないと何も出さずに終了コード2）
tables  表を Markdown の表にして出す（pdfplumber が必要）。2万字を超えるときは --out が要る
images  埋め込み画像をファイルに書き出し、パスを1行ずつ出す

終了コード:
    0  取り出した
    1  取り出せなかった（text で文字がほぼ無いページがある＝スキャンの疑い。取れた分は出力済み。
       tables で表が0件、パスワード付きで開けない）
    2  引数の指定ミス（--pages の書式違い・範囲外を含む）、--out 無しで出力が大きすぎる、
       または依存パッケージが無い

依存: pypdf（pip install pypdf）。tables のみ pdfplumber（pip install pdfplumber）
"""

import argparse
import json
import re
import sys
from pathlib import Path

# 1ページあたりこれ未満の文字数なら、画像だけのページ（スキャン・文字のアウトライン化）を疑う
MIN_CHARS_PER_PAGE = 20
# --out を付けずに標準出力へ流してよい文字数の上限。会話に大量のテキストを流さないため
MAX_PRINT_CHARS = 20000


def parse_pages(spec, total):
    """'1-3,5' → [0, 1, 2, 4]（0始まり）。書式違い・逆順・範囲外は ValueError。"""
    if not spec:
        return list(range(total))
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


def runs(pages):
    """[0, 1, 2, 4] → '1-3,5'"""
    out = []
    for p in pages:
        if out and out[-1][1] == p - 1:
            out[-1][1] = p
        else:
            out.append([p, p])
    return ",".join("%d" % (a + 1) if a == b else "%d-%d" % (a + 1, b + 1) for a, b in out)


def open_reader(path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        # 閲覧パスワードが空のもの（印刷・編集だけ制限）はこれで開ける
        if not reader.decrypt(""):
            return None
    return reader


def page_layout(reader):
    """同じ用紙サイズ・回転が続くページをまとめて '1-2: 210x297mm' の形にする。"""
    groups = []
    for i, page in enumerate(reader.pages):
        box = page.mediabox
        key = "%dx%dmm" % (round(float(box.width) / 72 * 25.4), round(float(box.height) / 72 * 25.4))
        if page.rotation % 360:
            key += " 回転%d" % (page.rotation % 360)
        if groups and groups[-1][1] == key:
            groups[-1][0].append(i)
        else:
            groups.append(([i], key))
    return ["%s: %s" % (runs(ps), key) for ps, key in groups]


def cmd_meta(reader, args):
    info = {}
    if reader.metadata:
        for k, v in reader.metadata.items():
            if str(v).strip():
                info[str(k).lstrip("/")] = str(v)
    fields = reader.get_fields() or {}
    result = {
        "pages": len(reader.pages),
        "page_layout": page_layout(reader),
        "encrypted": reader.is_encrypted,
        "form_fields": len(fields),
        "outline_items": len(reader.outline) if reader.outline else 0,
        "metadata": info,
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


def cmd_text(reader, args):
    pages = parse_pages(args.pages, len(reader.pages))
    chunks = []
    sparse = []
    for i in pages:
        page = reader.pages[i]
        if args.layout:
            text = page.extract_text(extraction_mode="layout")
        else:
            text = page.extract_text()
        text = text or ""
        if len(text.strip()) < MIN_CHARS_PER_PAGE:
            sparse.append(i)
        chunks.append("=== page %d ===\n%s" % (i + 1, text))
    body = "\n\n".join(chunks)
    if args.out:
        Path(args.out).write_text(body, encoding="utf-8")
        print(args.out)
        print("%d ページ / %d 文字" % (len(pages), len(body)), file=sys.stderr)
    elif len(body) > MAX_PRINT_CHARS:
        print("%d ページで %d 文字ある。会話に流さないよう --out FILE で書き出すか、--pages で絞る"
              % (len(pages), len(body)), file=sys.stderr)
        return 2
    else:
        print(body)
    if sparse:
        print("文字がほとんど取れないページ: %s（全 %d ページ中 %d ページ）。スキャンか文字のアウトライン化の疑い。"
              "白紙・扉ページなら無視してよい。pdf_to_png.py --pages %s で見て確かめる"
              % (runs(sparse), len(pages), len(sparse), runs(sparse)), file=sys.stderr)
        return 1
    return 0


def md_table(rows):
    rows = [[("" if c is None else str(c).replace("\n", " ").replace("|", "\\|")) for c in r] for r in rows]
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def cmd_tables(reader, args, path):
    try:
        import pdfplumber
    except ImportError:
        print("tables には pdfplumber が必要: pip install pdfplumber", file=sys.stderr)
        return 2
    pages = parse_pages(args.pages, len(reader.pages))
    chunks = []
    with pdfplumber.open(str(path)) as pdf:
        for i in pages:
            for j, table in enumerate(pdf.pages[i].extract_tables(), 1):
                if not table or not any(any(c for c in r) for r in table):
                    continue
                chunks.append("=== page %d table %d ===\n%s\n" % (i + 1, j, md_table(table)))
    if not chunks:
        print("表が見つからない。罫線の無い表は text --layout で読む", file=sys.stderr)
        return 1
    body = "\n".join(chunks)
    if args.out:
        Path(args.out).write_text(body, encoding="utf-8")
        print(args.out)
        print("表 %d 件 / %d 文字" % (len(chunks), len(body)), file=sys.stderr)
    elif len(body) > MAX_PRINT_CHARS:
        print("表 %d 件で %d 文字ある。--out FILE で書き出すか、--pages で絞る" % (len(chunks), len(body)),
              file=sys.stderr)
        return 2
    else:
        print(body)
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
    p.add_argument("--out")
    p = sub.add_parser("images")
    p.add_argument("pdf")
    p.add_argument("--outdir", required=True)
    p.add_argument("--pages")
    args = ap.parse_args()

    path = Path(args.pdf)
    if not path.is_file():
        print("入力が存在しない: %s" % path, file=sys.stderr)
        return 2
    try:
        import pypdf  # noqa: F401
    except ImportError:
        print("pypdf が必要: pip install pypdf", file=sys.stderr)
        return 2
    reader = open_reader(path)
    if reader is None:
        print("パスワード付きで開けない。pdf_ops.py decrypt で解除してから読む", file=sys.stderr)
        return 1
    try:
        if args.cmd == "meta":
            return cmd_meta(reader, args)
        if args.cmd == "text":
            return cmd_text(reader, args)
        if args.cmd == "tables":
            return cmd_tables(reader, args, path)
        return cmd_images(reader, args, path)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
