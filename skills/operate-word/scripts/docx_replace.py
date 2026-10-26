#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Word 文書の文字列を、書式を保ったまま置換する。変更履歴付きの置換もできる。

    python docx_replace.py <in.docx> <out.docx> --find 旧 --replace 新 [--find 旧2 --replace 新2 ...]
                           [--track 校閲者名] [--dry-run] [--allow-missing]

Word は見た目が1語でも、内部では書式・校正記号・編集履歴の境目で複数の断片（run）に分けて保存する。
そのため python-docx の run 単位の置換では見つからないことが多い。このスクリプトは段落内の文字を
つないで検索し、一致した範囲の先頭の断片に置換後の文字を入れ、残りの断片から一致部分を取り除く。
置換後の文字は一致範囲の先頭の書式になる。

対象: 本文（表・コンテンツコントロール・テキストボックスの中を含む）、すべてのヘッダー・フッター、
脚注、文末脚注。変更履歴で挿入された文字は対象（場所に「他の変更履歴の挿入の中」と出す）、削除済みの
文字と削除済みのテキストボックスは対象外。フィールドの結果（目次・相互参照など）の文字も置換し、場所に
「フィールドの結果」と出す（Word でフィールドを更新すると元の計算結果に戻る）。
置換しないもの: 段落をまたぐ文字列、タブ・改行・図・脚注番号・フィールドの境目をまたぐ一致
（またいだまま置き換えると、タブや改行が置換後の文字の後ろへずれる）、リンク・コンテンツコントロール・
変更履歴の境目をまたぐ一致（リンクの範囲が変わる）。--track では、他の変更履歴の挿入の中にある一致も
置換しない。いずれも件数と前後の文字を出す。
--find は上から順に適用する。前の置換結果に後の --find が当たる（連鎖する）ときは注意を出す。

--track 校閲者名: 一致した文字を削除（w:del）、置換後の文字を挿入（w:ins）として記録する。
    日時は Word と同じく現地時刻に Z を付けて書き、番号は文書内の既存の番号と重ならないものを振る。

出力: --find ごとに、置換した件数と場所（本文・ヘッダー・脚注・テキストボックスなど）、置換しなかった
件数と理由。--dry-run は書き出さず、一致箇所の前後の文字も出す（--find ごとに20件まで）。
--dry-run でも置換は手元で上から順に行うので、件数は本番と同じになる。

終了コード:
    0  すべての --find が1件以上置換され、置換しなかった一致も無い。書き出した（--dry-run では一覧を出した）
    1  見つからない --find がある、または置換しなかった一致がある。--allow-missing が無ければ書き出さない
    2  引数の指定ミス、入力が存在しない・開けない、入力と出力が同じ、または python-docx が無い

依存: python-docx（pip install python-docx）。同じフォルダの wordml.py を使う。
"""

import argparse
import copy
import datetime
import sys
from pathlib import Path

CONTEXT = 15         # 前後に出す文字数
MAX_CONTEXTS = 20    # --find ごとに出す一致箇所の上限


def location(label, p):
    from wordml import w
    a = p.getparent()
    while a is not None:
        if a.tag == w("txbxContent"):
            return label + "のテキストボックス"
        if a.tag == w("tbl"):
            return label + "の表"
        a = a.getparent()
    return label


def find_all(text, find):
    out, pos = [], text.find(find)
    while pos != -1:
        out.append(pos)
        pos = text.find(find, pos + len(find))
    return out


def search_text(ps):
    """検索用の文字列。図・脚注番号・フィールドの境目は長さ0にする（「である。」が脚注番号を挟んでいても
    見つかり、またぐ一致として報告できるように）。"""
    return "".join(x.text for x in ps if x.kind in ("text", "char"))


def layout(ps):
    """表示用の文字列（境目を ▫ や [^n] で残す）、検索位置→表示位置の対応、各要素の検索上の位置を返す。"""
    disp, where, pos_map = [], [], []
    off = n = 0
    for x in ps:
        if x.kind in ("barrier", "note"):
            where.append((x, off, off))
            t = "▫" if x.kind == "barrier" else x.text
            disp.append(t)
            n += len(t)
            continue
        for ch in x.text:
            pos_map.append(n)
            disp.append({"\t": "⇥", "\n": "↵"}.get(ch, ch))
            n += 1
        where.append((x, off, off + len(x.text)))
        off += len(x.text)
    pos_map.append(n)
    return "".join(disp), pos_map, where


def show(disp, pos_map, s, e):
    a, b = pos_map[s], pos_map[e]
    return "…%s【%s】%s…" % (disp[max(0, a - CONTEXT):a], disp[a:b], disp[b:b + CONTEXT])


def spans(where, s, e):
    """[s, e) に掛かる要素と、その中の範囲 (piece, lo, hi) を返す。長さ0の要素は内側にあるときだけ含める。"""
    out = []
    for x, a, b in where:
        if a == b:
            if x.kind != "text" and s < a < e:   # 空の w:t は含めない
                out.append((x, 0, 0))
        elif a < e and b > s:
            out.append((x, max(s, a) - a, min(e, b) - a))
    return out


class Tracker:
    """変更履歴の番号・校閲者・日時を配り、作った件数を数える（Fallback の複製は数えない）。"""

    def __init__(self, author, roots):
        from wordml import w
        self.author = author
        # Word は w:date を現地時刻として読み書きする（末尾の Z に反して）。本物の UTC を書くと、
        # 日本では Word の表示が9時間ずれることを Word 2021 で確かめた。Word に合わせて現地時刻に Z を付ける
        self.date = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        ids = [0]
        for root in roots:
            for el in root.iter():
                v = el.get(w("id")) if isinstance(el.tag, str) else None
                if v and v.lstrip("-").isdigit():
                    ids.append(int(v))
        self.next_id = max(ids) + 1
        self.ins = self.dels = 0

    def mark(self, tag):
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        el = OxmlElement(tag)
        el.set(qn("w:id"), str(self.next_id))
        el.set(qn("w:author"), self.author)
        el.set(qn("w:date"), self.date)
        self.next_id += 1
        return el


def isolate(t, lo, hi):
    """w:t の [lo, hi) だけを持つ run を作って返す。run の他の子（タブなど）や前後の文字は別の run に分ける。

    分けた run には元の書式（w:rPr）を写す。見た目は変わらない。
    """
    from wordml import w
    r = t.getparent()
    rpr = r.find(w("rPr"))
    # 1. run を「子1つにつき run 1つ」に分ける
    content = [c for c in r if c is not rpr]
    if len(content) > 1:
        for c in content:
            nr = copy.deepcopy(r)
            for k in list(nr):
                if k.tag != w("rPr"):
                    nr.remove(k)
            nr.append(c)          # c は元の run から移る
            r.addprevious(nr)
        r.getparent().remove(r)
        r = t.getparent()
    # 2. 文字を前・対象・後に分ける
    text = t.text or ""
    parts = [(text[:lo], False), (text[lo:hi], True), (text[hi:], False)]
    target = None
    for s, is_target in parts:
        if not s:
            continue
        nr = copy.deepcopy(r)
        nr.find(w("t")).text = s
        nr.find(w("t")).set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        r.addprevious(nr)
        if is_target:
            target = nr
    r.getparent().remove(r)
    return target


def tracked_replace(hits, repl, tracker, count):
    """一致範囲の run を w:del で包み、直後に置換後の文字を w:ins で入れる。"""
    from docx.oxml import OxmlElement
    from wordml import w
    runs = [isolate(x.el, lo, hi) for x, lo, hi in hits]
    first_rpr = runs[0].find(w("rPr"))
    # 隣り合う run は1つの w:del にまとめる
    groups = []
    for r in runs:
        if groups and groups[-1][-1].getnext() is r:
            groups[-1].append(r)
        else:
            groups.append([r])
    last_del = None
    tracker.dels += count          # 間に校正記号などがあって w:del が分かれても、置換1件につき1と数える
    for g in groups:
        d = tracker.mark("w:del")
        g[0].addprevious(d)
        for r in g:
            for t in r.findall(w("t")):
                t.tag = w("delText")
            d.append(r)
        last_del = d
    if repl:
        ins = tracker.mark("w:ins")
        nr = OxmlElement("w:r")
        if first_rpr is not None:
            nr.append(copy.deepcopy(first_rpr))
        t = OxmlElement("w:t")
        t.text = repl
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        nr.append(t)
        ins.append(nr)
        last_del.addnext(ins)
        tracker.ins += count


def plain_replace(hits, repl):
    first = True
    for x, lo, hi in hits:
        t = x.text
        new = t[:lo] + (repl if first else "") + t[hi:]
        first = False
        x.el.text = new
        x.el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def replace_in_paragraph(p, find, repl, tracker, result, label, count, fields):
    from wordml import INSERTED, has_ancestor, pieces
    ps = pieces(p)
    starts = find_all(search_text(ps), find)
    if not starts:
        return
    disp, pos_map, _ = layout(ps)
    where = location(label, p)
    in_revision = has_ancestor(p, INSERTED)    # 変更履歴で挿入されたテキストボックスの中など
    done, skipped = [], []
    # 後ろの一致から置換すると、前の一致の位置がずれない。前後の文字は置換前の段落から出す
    for s in reversed(starts):
        e = s + len(find)
        hits = spans(layout(pieces(p))[2], s, e)
        ctx = show(disp, pos_map, s, e)
        if any(x.kind != "text" for x, _, _ in hits):
            skipped.append(("タブ・改行・図・脚注番号・フィールドの境目をまたぐ", where, ctx))
            continue
        if len({id(x.run.getparent()) for x, _, _ in hits}) > 1:
            skipped.append(("リンク・コンテンツコントロール・変更履歴の境目をまたぐ", where, ctx))
            continue
        revised = in_revision or has_ancestor(hits[0][0].run, INSERTED, p)
        if tracker is not None and revised:
            skipped.append(("他の変更履歴の挿入の中", where, ctx))
            continue
        notes = []
        if revised:
            notes.append("他の変更履歴の挿入の中")
        if any(x.el in fields for x, _, _ in hits):
            notes.append("フィールドの結果")
        if tracker is not None:
            tracked_replace(hits, repl, tracker, count)
        else:
            plain_replace(hits, repl)
        done.append((where + ("・" + "・".join(notes) if notes else ""), ctx))
    if count:
        result["done"] += reversed(done)
        result["skipped"] += reversed(skipped)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="書式を保って文字列を置換する")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--find", action="append", required=True)
    ap.add_argument("--replace", action="append", required=True)
    ap.add_argument("--track", metavar="AUTHOR", help="変更履歴付きで置換し、この名前を校閲者にする")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-missing", action="store_true")
    args = ap.parse_args()

    try:
        import docx
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from wordml import DELETED, field_results, has_ancestor, in_fallback, stories, w
    except ImportError:
        print("python-docx が必要: pip install python-docx", file=sys.stderr)
        return 2
    if len(args.find) != len(args.replace):
        print("--find と --replace は同じ数だけ指定する", file=sys.stderr)
        return 2
    if any(not f for f in args.find):
        print("--find に空文字は指定できない", file=sys.stderr)
        return 2
    if args.track is not None and not args.track.strip():
        print("--track に校閲者名を指定する", file=sys.stderr)
        return 2
    src, dst = Path(args.input), Path(args.output)
    if not src.is_file():
        print("入力が存在しない: %s" % src, file=sys.stderr)
        return 2
    if src.resolve() == dst.resolve():
        print("出力を入力と同じパスにしない", file=sys.stderr)
        return 2
    try:
        doc = docx.Document(str(src))
    except Exception as e:  # 壊れた zip・docx 以外の形式で python-docx が投げる例外はまちまち
        print("開けない: %s (%s)" % (src, e), file=sys.stderr)
        return 2

    parts = stories(doc)
    tracker = Tracker(args.track, [root for _, root, _ in parts]) if args.track else None
    # 削除済みの変更履歴の中の段落（削除されたテキストボックスなど）は対象外
    paragraphs = [(label, root, p, not in_fallback(p)) for label, root, _ in parts
                  for p in root.iter(w("p")) if not has_ancestor(p, DELETED)]

    missing, skipped_any = [], False
    for i, (find, repl) in enumerate(zip(args.find, args.replace)):
        chained = [f for f in args.find[i + 1:] if f in repl]
        if chained:
            print("注意: 置換後の「%s」に後の --find「%s」が含まれる。上から順に適用するので連鎖して置換される"
                  % (repl, "」「".join(chained)))
        result = {"done": [], "skipped": []}
        fields = {id(root): field_results(root) for _, root, _ in parts}   # 置換で w:t が作り直されるので毎回
        for label, root, p, count in paragraphs:
            replace_in_paragraph(p, find, repl, tracker, result, label, count, fields[id(root)])
        done, skipped = result["done"], result["skipped"]
        places = {}
        for where, _ in done:
            places[where] = places.get(where, 0) + 1
        print("%s → %s: 置換 %d 件%s" % (find, repl, len(done),
              "（" + "、".join("%s %d" % kv for kv in places.items()) + "）" if places else ""))
        if args.dry_run:
            for where, ctx in done[:MAX_CONTEXTS]:
                print("  [%s] %s" % (where, ctx))
            if len(done) > MAX_CONTEXTS:
                print("  …ほか %d 件" % (len(done) - MAX_CONTEXTS))
        if skipped:
            skipped_any = True
            print("  置換しなかった %d 件:" % len(skipped))
            for reason, where, ctx in skipped[:MAX_CONTEXTS]:
                print("  [%s] %s（%s）" % (where, ctx, reason))
        if not done and not skipped:
            missing.append(find)

    if tracker is not None:
        print("変更履歴: 挿入 %d・削除 %d（校閲者 %s、%s）" % (tracker.ins, tracker.dels, tracker.author, tracker.date))
    bad = bool(missing) or skipped_any
    if args.dry_run:
        return 1 if bad else 0
    if missing:
        print("見つからない: %s" % ", ".join(missing), file=sys.stderr)
    if bad and not args.allow_missing:
        print("何も書き出していない（--allow-missing で置換できた分だけ書き出す）", file=sys.stderr)
        return 1
    for _, _, save in parts:
        if save:
            save()
    doc.save(str(dst))
    print(dst)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
