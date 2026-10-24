#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF のページ操作・暗号化・フォーム記入を行う。入力は書き換えず、必ず別ファイルに出す。

    python pdf_ops.py merge   OUT IN1 IN2 [...]
    python pdf_ops.py split   IN --outdir DIR [--ranges 1-3,4-6]
    python pdf_ops.py rotate  IN OUT --degrees 90 [--pages 1-3]
    python pdf_ops.py stamp   IN OUT --stamp STAMP.pdf [--under] [--pages 1-3]
    python pdf_ops.py encrypt IN OUT --password PW [--owner-password PW2]
    python pdf_ops.py decrypt IN OUT --password PW
    python pdf_ops.py list-fields IN
    python pdf_ops.py fill-form   IN OUT --data VALUES.json

split        --ranges を省くと1ページ1ファイル。範囲ごとに <IN名>-<範囲>.pdf を書き出す
rotate       時計回りに 90 の倍数で回す。--pages を省くと全ページ
stamp        STAMP.pdf の1ページ目を重ねる（透かし・社外秘印など）。--under で本文の下に敷く。
             各ページの見た目（回転を含む）の中央に正立で置き、ページより大きい印は縮める
list-fields  フォームのフィールド名・種類・現在値・選択肢・載っているページを1フィールド1行の JSON で出す。
             fill-form の前に必ず見る
fill-form    VALUES.json は {"フィールド名": 値}。チェックボックス・ラジオ・選択欄は list-fields の
             options にある値を入れる（"Yes" のように先頭の / だけ欠けたものは補う）。存在しない名前・
             選択肢に無い値が1つでもあれば何も書かずに終了コード1。記入したページ番号と、和文などを
             フィールドのフォントで表せないときの注意を標準エラーに出す

成功時は書き出したパスを1行ずつ標準出力に出す。

終了コード:
    0  成功
    1  操作できなかった（パスワード違い、存在しないフィールド名・選択肢に無い値、フォームが無い）
    2  引数の指定ミス（--pages・--ranges の書式違い・範囲外を含む）、入力が存在しない、
       VALUES.json が読めない、または依存パッケージが無い

依存: pypdf（pip install pypdf）。encrypt と AES の PDF の decrypt は cryptography も（pip install cryptography）
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path


PAGE_SPEC = re.compile(r"\s*\d+(\s*-\s*\d+)?\s*(,\s*\d+(\s*-\s*\d+)?\s*)*")


def parse_ranges(spec, total):
    """'1-3,5' → [(0, 3), (4, 5)]（0始まり・終端は含まない）。書式違い・逆順・範囲外は ValueError。"""
    if not PAGE_SPEC.fullmatch(spec):
        raise ValueError("ページ指定の書式が違う: %r（例 1-3,5）" % spec)
    ranges = []
    for part in spec.replace(" ", "").split(","):
        a, _, b = part.partition("-")
        start, end = int(a), int(b or a)
        if not 1 <= start <= end <= total:
            raise ValueError("ページ指定が範囲外か逆順: %s（全 %d ページ）" % (part, total))
        ranges.append((start - 1, end))
    return ranges


def pages_of(spec, total):
    if spec is None:
        return set(range(total))
    return {p for a, b in parse_ranges(spec, total) for p in range(a, b)}


class BrokenPdf(Exception):
    pass


def read(path, password=None):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    try:
        reader = PdfReader(str(path))
    except PdfReadError as e:
        raise BrokenPdf("PDF を開けない（壊れているか PDF ではない）: %s (%s)" % (path, e))
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
    ranges = parse_ranges(args.ranges, total) if args.ranges is not None else [(i, i + 1) for i in range(total)]
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


def fit_stamp(page, stamp_page):
    """印のページを、ページの見た目（/Rotate 適用後）の中央に正立で置く変換を返す。
    印のほうが大きければ縦横比を保って縮める。拡大はしない。"""
    from pypdf import Transformation
    box, sbox = page.cropbox, stamp_page.cropbox
    w, h = float(box.width), float(box.height)
    sw, sh = float(sbox.width), float(sbox.height)
    rot = page.rotation % 360
    vw, vh = (h, w) if rot in (90, 270) else (w, h)
    scale = min(1.0, vw / sw, vh / sh)
    # 印の中心を原点へ → 縮める → ページの回転を打ち消す → ページの中心へ
    t = (Transformation()
         .translate(-float(sbox.left) - sw / 2, -float(sbox.bottom) - sh / 2)
         .scale(scale, scale))
    if rot:
        t = t.rotate(rot)
    return t.translate(float(box.left) + w / 2, float(box.bottom) + h / 2)


def cmd_stamp(args):
    from pypdf import PdfWriter
    reader = read(args.input)
    stamp = read(args.stamp)
    if reader is None or stamp is None:
        print("パスワード付きで開けない", file=sys.stderr)
        return 1
    stamp_page = stamp.pages[0]
    if stamp_page.rotation % 360:
        # 印のページ自体に /Rotate があれば、見えている向きのまま中身に焼き込んでから重ねる
        stamp_page = PdfWriter(clone_from=stamp).pages[0]
        stamp_page.transfer_rotation_to_content()
    writer = PdfWriter(clone_from=reader)
    for i in pages_of(args.pages, len(writer.pages)):
        page = writer.pages[i]
        page.merge_transformed_page(stamp_page, fit_stamp(page, stamp_page), over=not args.under)
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


def qualified_name(node):
    """pypdf の get_fields() と同じ規則の完全名。/TM（対応付け名）があればそれを、無ければ /T を親から連結する。"""
    if "/TM" in node:
        return str(node["/TM"])
    parent = node.get("/Parent")
    own = str(node["/T"]) if "/T" in node else None
    if parent is None:
        return own or ""
    base = qualified_name(parent.get_object())
    if own is None:
        return base
    return base + "." + own if base else own


def widgets(reader):
    """ウィジェットごとに (完全名, 末端の /T, ページ番号1始まり) を返す。"""
    found = []
    for no, page in enumerate(reader.pages, 1):
        annots = page.get("/Annots")
        for annot in (annots.get_object() if annots is not None else []):
            node = annot.get_object()
            if node.get("/Subtype") != "/Widget":
                continue
            field = node if "/T" in node else node.get("/Parent").get_object() if node.get("/Parent") else node
            found.append((qualified_name(field), str(field.get("/T", "")), no))
    return found


def parse_opt(opt):
    """/Opt を [(保存値, 表示名)] にする。要素は文字列か [保存値, 表示名]。"""
    pairs = []
    for o in opt or []:
        o = o.get_object() if hasattr(o, "get_object") else o
        if isinstance(o, list):
            pairs.append((str(o[0]), str(o[-1])))
        else:
            pairs.append((str(o), str(o)))
    return pairs


def describe_fields(reader):
    fields = reader.get_fields() or {}
    where = {}
    for name, _, no in widgets(reader):
        if no not in where.setdefault(name, []):
            where[name].append(no)
    result = []
    for name, f in fields.items():
        ftype = str(f.get("/FT", ""))
        if name not in where:
            continue  # ウィジェットを持たない中間ノード（"親.子" の親）
        if ftype == "/Btn" and int(f.get("/Ff", 0)) & (1 << 16):
            continue  # 押しボタン。値を持たない
        value = f.get("/V")
        item = {"name": name,
                "type": {"/Tx": "text", "/Btn": "button", "/Ch": "choice", "/Sig": "signature"}.get(ftype, ftype),
                "value": None if value is None else [str(v) for v in value] if isinstance(value, list) else str(value),
                "pages": where.get(name, [])}
        flags = int(f.get("/Ff", 0))
        if ftype == "/Ch":
            pairs = parse_opt(f.get("/Opt"))
            if pairs:
                item["options"] = [v for v, _ in pairs]
                if any(v != label for v, label in pairs):
                    item["labels"] = [label for _, label in pairs]  # 画面に出る名前。値には options を使う
            if flags & (1 << 18):
                item["editable"] = True  # 選択肢に無い値も入れられるコンボボックス
            if flags & (1 << 21):
                item["multi"] = True  # 複数選択。値は文字列の配列
        elif f.get("/_States_"):
            item["options"] = [str(s) for s in f.get("/_States_")]
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
    # 1フィールド1行。フィールドが数十あっても読み切れる量に抑える
    print("[\n" + ",\n".join(json.dumps(f, ensure_ascii=False) for f in fields) + "\n]")
    return 0


def check_values(values, fields, leaf_names):
    """値を種類・選択肢と突き合わせる。'Yes' のように先頭の / だけ欠けた値は補う。
    戻り値は (直した値, エラーの一覧)。"""
    by_name = {f["name"]: f for f in fields}
    fixed, errors = {}, []
    for name, value in values.items():
        f = by_name[name]
        options = f.get("options")
        # pypdf は完全名だけでなく末端の /T でも一致させるので、"name" を渡すと "group.name" にも書かれる
        clash = sorted(n for n, leaf in leaf_names if leaf == name and n != name)
        if clash:
            errors.append("%s: 末端の名前が同じフィールド（%s）にも書かれてしまうので、この PDF では書けない"
                          % (name, ", ".join(clash)))
            continue
        if f["type"] == "signature":
            errors.append("%s: 署名欄には書けない" % name)
            continue
        if f.get("multi"):
            if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
                errors.append("%s: 複数選択の欄なので値は文字列の配列で書く（選択肢 %s）" % (name, options))
                continue
            bad = [v for v in value if options and v not in options]
            if bad and not f.get("editable"):
                errors.append("%s: %r は選択肢に無い（選択肢 %s）" % (name, bad, options))
                continue
            fixed[name] = value
            continue
        if not isinstance(value, str):
            errors.append("%s: 値は文字列で書く（%r は不可。空にするなら \"\"）" % (name, value))
            continue
        if f["type"] == "button" and options:
            if value not in options and "/" + value in options:
                value = "/" + value
            if value not in options:
                errors.append("%s: %r は選択肢に無い（選択肢 %s）" % (name, value, options))
                continue
        if f["type"] == "choice" and options and not f.get("editable") and value not in options:
            hint = ""
            if value in f.get("labels", []):
                hint = "。表示名ではなく options の値を使う（%s）" % options[f["labels"].index(value)]
            errors.append("%s: %r は選択肢に無い（選択肢 %s）%s" % (name, value, options, hint))
            continue
        fixed[name] = value
    return fixed, errors


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def cmd_fill_form(args):
    from pypdf import PdfWriter
    reader = read(args.input)
    if reader is None:
        print("パスワード付きで開けない", file=sys.stderr)
        return 1
    try:
        values = json.loads(Path(args.data).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        print("VALUES.json が読めない: %s" % e, file=sys.stderr)
        return 2
    if not isinstance(values, dict) or not values:
        print("VALUES.json は {\"フィールド名\": 値} のオブジェクトにし、1件以上書く", file=sys.stderr)
        return 2
    fields = describe_fields(reader)
    unknown = sorted(set(values) - {f["name"] for f in fields})
    if unknown:
        print("存在しないフィールド名: %s" % ", ".join(unknown), file=sys.stderr)
        return 1
    placed = widgets(reader)
    values, errors = check_values(values, fields, {(n, leaf) for n, leaf, _ in placed})
    targets = sorted({no for n, _, no in placed if n in values})
    if values and not targets:
        errors.append("記入するフィールドがどのページにも載っていない（ウィジェットが無い）")
    if errors:
        print("値が不正なので何も書かない:\n" + "\n".join(errors), file=sys.stderr)
        return 1
    writer = PdfWriter(clone_from=reader)
    # pypdf はフィールドのフォント（多くは Helvetica）で表せない文字を警告だけ出して ? にする
    collect = _Collect()
    logging.getLogger("pypdf").addHandler(collect)
    try:
        for no in targets:
            writer.update_page_form_field_values(writer.pages[no - 1], values, auto_regenerate=False)
    finally:
        logging.getLogger("pypdf").removeHandler(collect)
    # ビューアに外観を作り直させる。これが無いと値が入っても表示されないことがある
    writer.set_need_appearances_writer(True)
    with open(args.out, "wb") as f:
        writer.write(f)
    print(args.out)
    # 書いた結果を読み直し、要求した値になったか・要求していないフィールドが変わっていないかを確かめる
    from pypdf import PdfReader
    after = {f["name"]: f["value"] for f in describe_fields(PdfReader(args.out))}
    before = {f["name"]: f["value"] for f in fields}
    wrong = [n for n, v in values.items() if after.get(n) != (v if isinstance(v, list) else str(v))]
    touched = [n for n in before if n not in values and after.get(n) != before[n]]
    if wrong or touched:
        print("書いた結果が要求と違う。出力を使わない: 値が違う %s / 要求外で変わった %s" % (wrong, touched),
              file=sys.stderr)
        return 1
    print("記入したページ: %s" % ",".join(map(str, targets)), file=sys.stderr)
    if any("not supported by font encoding" in m for m in collect.messages):
        print("注意: フィールドのフォントで表せない文字（和文など）がある。値は入ったが、表示はビューアが"
              "外観を作り直すかどうかに依る（作り直さないビューアでは ? や空欄になる）", file=sys.stderr)
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
    p.add_argument("--pages")
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
    except BrokenPdf as e:
        print(e, file=sys.stderr)
        return 1
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    except DependencyError:
        # AES の暗号化・復号は pypdf 単体ではできない
        print("AES の暗号化・復号には cryptography が必要: pip install cryptography", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
