#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF のページ操作・暗号化・フォーム記入を行う。入力は書き換えず、必ず別ファイルに出す。

    python pdf_ops.py merge   OUT IN1 IN2 [...]
    python pdf_ops.py split   IN --outdir DIR [--ranges 1-3,4-6]
    python pdf_ops.py rotate  IN OUT --degrees 90 [--pages 1-3]
    python pdf_ops.py stamp   IN OUT --stamp STAMP.pdf [--under]
    python pdf_ops.py encrypt IN OUT --password PW [--owner-password PW2]
    python pdf_ops.py decrypt IN OUT --password PW
    python pdf_ops.py list-fields IN
    python pdf_ops.py fill-form   IN OUT --data VALUES.json

split        --ranges を省くと1ページ1ファイル。範囲ごとに <IN名>-<範囲>.pdf を書き出す
rotate       時計回りに 90 の倍数で回す。--pages を省くと全ページ
stamp        STAMP.pdf の1ページ目を全ページに重ねる（透かし・社外秘印など）。--under で本文の下に敷く
list-fields  フォームのフィールド名・種類・現在値・選択肢を JSON で出す。fill-form の前に必ず見る
fill-form    VALUES.json は {"フィールド名": 値}。チェックボックスは list-fields の options にある値
             （例 "/Yes"）を入れる。存在しない名前が1つでもあれば何も書かずに終了コード1

成功時は書き出したパスを1行ずつ標準出力に出す。

終了コード:
    0  成功
    1  操作できなかった（パスワード違い、存在しないフィールド名、フォームが無い）
    2  引数の指定ミス、入力が存在しない、または依存パッケージが無い

依存: pypdf（pip install pypdf）。encrypt と AES の PDF の decrypt は cryptography も（pip install cryptography）
"""

import argparse
import json
import sys
from pathlib import Path


def parse_ranges(spec, total):
    """'1-3,5' → [(0, 3), (4, 5)]（0始まり・終端は含まない）。"""
    ranges = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        start, end = max(1, start), min(total, end)
        if start <= end:
            ranges.append((start - 1, end))
    return ranges


def pages_of(spec, total):
    if not spec:
        return set(range(total))
    return {p for a, b in parse_ranges(spec, total) for p in range(a, b)}


def read(path, password=None):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        if not reader.decrypt(password or ""):
            return None
    return reader


def cmd_merge(args):
    from pypdf import PdfWriter
    writer = PdfWriter()
    for src in args.inputs:
        reader = read(src)
        if reader is None:
            print("パスワード付きで開けない: %s" % src, file=sys.stderr)
            return 1
        writer.append(reader)
    with open(args.out, "wb") as f:
        writer.write(f)
    print(args.out)
    return 0


def cmd_split(args):
    from pypdf import PdfWriter
    reader = read(args.input)
    if reader is None:
        print("パスワード付きで開けない", file=sys.stderr)
        return 1
    total = len(reader.pages)
    ranges = parse_ranges(args.ranges, total) if args.ranges else [(i, i + 1) for i in range(total)]
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.input).stem
    width = len(str(total))
    for a, b in ranges:
        writer = PdfWriter()
        for i in range(a, b):
            writer.add_page(reader.pages[i])
        label = "%0*d" % (width, a + 1) if b - a == 1 else "%0*d-%0*d" % (width, a + 1, width, b)
        out = outdir / ("%s-%s.pdf" % (stem, label))
        with open(out, "wb") as f:
            writer.write(f)
        print(out)
    return 0


def cmd_rotate(args):
    from pypdf import PdfWriter
    if args.degrees % 90 != 0:
        print("--degrees は 90 の倍数", file=sys.stderr)
        return 2
    reader = read(args.input)
    if reader is None:
        print("パスワード付きで開けない", file=sys.stderr)
        return 1
    writer = PdfWriter(clone_from=reader)
    for i in pages_of(args.pages, len(writer.pages)):
        writer.pages[i].rotate(args.degrees)
    with open(args.out, "wb") as f:
        writer.write(f)
    print(args.out)
    return 0


def cmd_stamp(args):
    from pypdf import PdfWriter
    reader = read(args.input)
    stamp = read(args.stamp)
    if reader is None or stamp is None:
        print("パスワード付きで開けない", file=sys.stderr)
        return 1
    stamp_page = stamp.pages[0]
    writer = PdfWriter(clone_from=reader)
    for page in writer.pages:
        page.merge_page(stamp_page, over=not args.under)
    with open(args.out, "wb") as f:
        writer.write(f)
    print(args.out)
    return 0


def cmd_encrypt(args):
    from pypdf import PdfWriter
    reader = read(args.input)
    if reader is None:
        print("既にパスワード付き。先に decrypt する", file=sys.stderr)
        return 1
    writer = PdfWriter(clone_from=reader)
    writer.encrypt(user_password=args.password,
                   owner_password=args.owner_password or args.password,
                   algorithm="AES-256")
    with open(args.out, "wb") as f:
        writer.write(f)
    print(args.out)
    return 0


def cmd_decrypt(args):
    from pypdf import PdfWriter
    reader = read(args.input, args.password)
    if reader is None:
        print("パスワードが違う", file=sys.stderr)
        return 1
    writer = PdfWriter(clone_from=reader)
    with open(args.out, "wb") as f:
        writer.write(f)
    print(args.out)
    return 0


def describe_fields(reader):
    fields = reader.get_fields() or {}
    result = []
    for name, f in fields.items():
        ftype = str(f.get("/FT", ""))
        item = {"name": name,
                "type": {"/Tx": "text", "/Btn": "button", "/Ch": "choice", "/Sig": "signature"}.get(ftype, ftype),
                "value": None if f.get("/V") is None else str(f.get("/V"))}
        states = f.get("/_States_")
        if states:
            item["options"] = [str(s) for s in states]
        elif f.get("/Opt"):
            item["options"] = [str(o[-1]) if isinstance(o, list) else str(o) for o in f.get("/Opt")]
        result.append(item)
    return result


def cmd_list_fields(args):
    reader = read(args.input)
    if reader is None:
        print("パスワード付きで開けない", file=sys.stderr)
        return 1
    fields = describe_fields(reader)
    if not fields:
        print("記入できるフォームフィールドが無い。見た目だけの様式なら文字を重ねる（stamp）しかない",
              file=sys.stderr)
        return 1
    print(json.dumps(fields, ensure_ascii=False, indent=2))
    return 0


def cmd_fill_form(args):
    from pypdf import PdfWriter
    reader = read(args.input)
    if reader is None:
        print("パスワード付きで開けない", file=sys.stderr)
        return 1
    values = json.loads(Path(args.data).read_text(encoding="utf-8"))
    known = {f["name"] for f in describe_fields(reader)}
    unknown = sorted(set(values) - known)
    if unknown:
        print("存在しないフィールド名: %s" % ", ".join(unknown), file=sys.stderr)
        return 1
    writer = PdfWriter(clone_from=reader)
    for page in writer.pages:
        writer.update_page_form_field_values(page, values, auto_regenerate=False)
    # ビューアに外観を作り直させる。これが無いと値が入っても表示されないことがある
    writer.set_need_appearances_writer(True)
    with open(args.out, "wb") as f:
        writer.write(f)
    print(args.out)
    return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="PDF のページ操作・暗号化・フォーム記入")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("merge")
    p.add_argument("out")
    p.add_argument("inputs", nargs="+")
    p = sub.add_parser("split")
    p.add_argument("input")
    p.add_argument("--outdir", required=True)
    p.add_argument("--ranges")
    p = sub.add_parser("rotate")
    p.add_argument("input")
    p.add_argument("out")
    p.add_argument("--degrees", type=int, required=True)
    p.add_argument("--pages")
    p = sub.add_parser("stamp")
    p.add_argument("input")
    p.add_argument("out")
    p.add_argument("--stamp", required=True)
    p.add_argument("--under", action="store_true")
    p = sub.add_parser("encrypt")
    p.add_argument("input")
    p.add_argument("out")
    p.add_argument("--password", required=True)
    p.add_argument("--owner-password")
    p = sub.add_parser("decrypt")
    p.add_argument("input")
    p.add_argument("out")
    p.add_argument("--password", required=True)
    p = sub.add_parser("list-fields")
    p.add_argument("input")
    p = sub.add_parser("fill-form")
    p.add_argument("input")
    p.add_argument("out")
    p.add_argument("--data", required=True)
    args = ap.parse_args()

    try:
        import pypdf  # noqa: F401
    except ImportError:
        print("pypdf が必要: pip install pypdf", file=sys.stderr)
        return 2
    inputs = args.inputs if args.cmd == "merge" else [args.input]
    for src in inputs:
        if not Path(src).is_file():
            print("入力が存在しない: %s" % src, file=sys.stderr)
            return 2
    out = getattr(args, "out", None)
    if out and any(Path(out).resolve() == Path(s).resolve() for s in inputs):
        print("出力を入力と同じパスにしない", file=sys.stderr)
        return 2
    handler = {
        "merge": cmd_merge, "split": cmd_split, "rotate": cmd_rotate, "stamp": cmd_stamp,
        "encrypt": cmd_encrypt, "decrypt": cmd_decrypt,
        "list-fields": cmd_list_fields, "fill-form": cmd_fill_form,
    }[args.cmd]
    from pypdf.errors import DependencyError
    try:
        return handler(args)
    except DependencyError:
        # AES の暗号化・復号は pypdf 単体ではできない
        print("AES の暗号化・復号には cryptography が必要: pip install cryptography", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
