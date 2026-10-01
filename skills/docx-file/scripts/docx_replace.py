#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Word 文書の文字列を、書式を保ったまま置換する。

    python docx_replace.py <in.docx> <out.docx> --find 旧 --replace 新 [--find 旧2 --replace 新2 ...]
                           [--dry-run] [--allow-missing]

Word は見た目が1語でも、内部では書式・校正記号・編集履歴の境目で複数の断片（run）に分けて保存する。
そのため python-docx の run 単位の置換では見つからないことが多い。このスクリプトは段落内の文字を
つないで検索し、一致した範囲の先頭の断片に置換後の文字を入れ、残りの断片から一致部分を取り除く。
置換後の文字は一致範囲の先頭の書式になる。

対象: 本文（表の中を含む）、全セクションのヘッダー・フッター。
段落をまたぐ文字列、脚注・テキストボックス内、変更履歴で削除済みの文字は対象外。

出力: 置換ごとの件数。--dry-run は書き出さず、一致箇所の前後の文字を出す。

終了コード:
    0  すべての --find が1件以上見つかり、置換して書き出した（--dry-run では一覧を出した）
    1  見つからない --find がある。--allow-missing が無ければ何も書き出さない
    2  引数の指定ミス、入力が存在しない、入力と出力が同じ、または python-docx が無い

依存: python-docx（pip install python-docx）
"""

import argparse
import sys
from pathlib import Path


def paragraphs(doc):
    """本文とヘッダー・フッターの全段落要素（w:p）を返す。"""
    from docx.oxml.ns import qn
    ps = list(doc.element.body.iter(qn("w:p")))
    seen = set()
    for s in doc.sections:
        for part in (s.header, s.footer, s.first_page_header, s.first_page_footer,
                     s.even_page_header, s.even_page_footer):
            if part.is_linked_to_previous:
                continue
            el = part._element
            if id(el) in seen:
                continue
            seen.add(id(el))
            ps += list(el.iter(qn("w:p")))
    return ps


def replace_in_paragraph(p, find, repl, dry_run, contexts):
    from docx.oxml.ns import qn
    nodes = [t for t in p.iter(qn("w:t"))]
    if not nodes:
        return 0
    texts = [t.text or "" for t in nodes]
    joined = "".join(texts)
    starts = []
    pos = joined.find(find)
    while pos != -1:
        starts.append(pos)
        pos = joined.find(find, pos + len(find))
    if not starts:
        return 0
    if dry_run:
        for s in starts:
            contexts.append("…%s【%s】%s…" % (joined[max(0, s - 15):s], find, joined[s + len(find):s + len(find) + 15]))
        return len(starts)

    # 後ろの一致から置換すると、前の一致の位置がずれない
    for s in reversed(starts):
        e = s + len(find)
        offset = 0
        first = True
        for i, t in enumerate(texts):
            a, b = offset, offset + len(t)
            offset = b
            if b <= s or a >= e:
                continue
            lo, hi = max(s, a) - a, min(e, b) - a
            if first:
                texts[i] = t[:lo] + repl + t[hi:]
                first = False
            else:
                texts[i] = t[:lo] + t[hi:]
    for node, text in zip(nodes, texts):
        if node.text != text:
            node.text = text
            # 先頭・末尾の空白を Word に捨てさせない
            node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return len(starts)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="書式を保って文字列を置換する")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--find", action="append", required=True)
    ap.add_argument("--replace", action="append", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-missing", action="store_true")
    args = ap.parse_args()

    try:
        import docx
    except ImportError:
        print("python-docx が必要: pip install python-docx", file=sys.stderr)
        return 2
    if len(args.find) != len(args.replace):
        print("--find と --replace は同じ数だけ指定する", file=sys.stderr)
        return 2
    if any(not f for f in args.find):
        print("--find に空文字は指定できない", file=sys.stderr)
        return 2
    src, dst = Path(args.input), Path(args.output)
    if not src.is_file():
        print("入力が存在しない: %s" % src, file=sys.stderr)
        return 2
    if src.resolve() == dst.resolve():
        print("出力を入力と同じパスにしない", file=sys.stderr)
        return 2

    doc = docx.Document(str(src))
    ps = paragraphs(doc)
    missing = []
    for find, repl in zip(args.find, args.replace):
        contexts = []
        n = sum(replace_in_paragraph(p, find, repl, args.dry_run, contexts) for p in ps)
        print("%s → %s: %d 件" % (find, repl, n))
        for c in contexts:
            print("  " + c)
        if n == 0:
            missing.append(find)

    if args.dry_run:
        return 1 if missing else 0
    if missing and not args.allow_missing:
        print("見つからない: %s。何も書き出していない" % ", ".join(missing), file=sys.stderr)
        return 1
    doc.save(str(dst))
    print(dst)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
