#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Word 文書（.docx）の構造と本文を Markdown 風に出す。

    python inspect_docx.py <docx> [--outline] [--section N] [--full] [--out FILE]

出力:
    - 冒頭: 用紙・向き・余白とヘッダー・フッターの文字（セクションごと。先頭ページ用・偶数ページ用は
      その設定が有効なときだけ。60字で切る）、
      使われている段落スタイル、表・画像（行内と浮動）・テキストボックス・脚注・文末脚注・コメント・
      変更履歴（挿入・削除。本文・ヘッダー・フッター・脚注の合計）・フィールドの数、本文の文字数
    - 本文: 段落と表を文書の順に。見出し（見出しスタイルか、スタイル・段落のアウトラインレベル）は #、
      箇条書き・段落番号は -、それ以外は [スタイル名] を前に付ける（標準スタイルは付けない）。
      変更履歴で挿入した文字は含め、削除した文字は含めない。コンテンツコントロールの中も出す。
      テキストボックスの文字は [テキストボックス] として段落の後に、脚注は [^番号] で本文に残し末尾に出す。
      表は Markdown の表。横に結合したセルは ←、縦に結合したセルは ↑ と出す。セルの中の入れ子の表と
      テキストボックスは [表: …] [テキストボックス: …] としてセルの中に出す
    --outline     見出しだけを §番号 付きで出す
    --section N   §N の見出しから、同じか上の階層の次の見出しの手前までと、そこで参照する脚注だけを出す
                  （冒頭の集計は出さない）
    --full        本文が長くても省略しない
    --out FILE    出力をファイルに書き、標準出力にはパスだけを出す

本文（脚注を含む）が LIMIT（2万字）を超え、--section / --full / --out のどれも無いときは、本文の代わりに
見出しの一覧を出す。見出しが1つも無い文書では、先頭から2万字までを出す。

終了コード:
    0  出力した
    1  開けない（壊れている、.docx ではない）
    2  引数の指定ミス（--section の番号が無いなど）、入力が存在しない、.doc、または python-docx が無い

依存: python-docx（pip install python-docx）。同じフォルダの wordml.py を使う。
"""

import argparse
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

LIMIT = 20000          # これを超える本文（脚注を含む）は、既定では見出しの一覧だけを出す
HEADER_CHARS = 60      # ヘッダー・フッターの文字はこの字数で切る
HEADING_RE = re.compile(r"^(Heading|見出し)\s*(\d)$")
TITLE_STYLES = {"Title", "表題"}
LIST_HINTS = ("List", "リスト", "箇条書き", "段落番号")
NORMAL_STYLES = {"Normal", "標準", "Body Text", "本文"}


class Reader:
    def __init__(self, doc):
        from wordml import w
        self.w = w
        self.styles = {}       # styleId → (名前, 見出しの階層, 番号付きか)
        for s in doc.styles.element.findall(w("style")):
            if s.get(w("type")) == "paragraph":
                self.styles[s.get(w("styleId"))] = s
        self.default = next((sid for sid, s in self.styles.items() if s.get(w("default")) in ("1", "true")), None)
        self.cache = {}
        self.used = Counter()      # 本文で使われている段落スタイル（文字のある段落だけ）

    def style_info(self, sid):
        """スタイルの名前・アウトラインレベル・番号付きかを、基にしたスタイルまでさかのぼって決める。"""
        from docx.styles import BabelFish
        w = self.w
        if sid in self.cache:
            return self.cache[sid]
        name, outline, numbered = "", None, None
        seen, cur = set(), sid
        while cur and cur not in seen and cur in self.styles:
            seen.add(cur)
            s = self.styles[cur]
            if not name:
                n = s.find(w("name"))
                name = BabelFish.internal2ui(n.get(w("val"))) if n is not None else cur
            ppr = s.find(w("pPr"))
            if ppr is not None:
                if outline is None and ppr.find(w("outlineLvl")) is not None:
                    outline = int(ppr.find(w("outlineLvl")).get(w("val")))
                num = ppr.find(w("numPr"))
                if numbered is None and num is not None:      # 近いスタイルの指定が勝つ（numId 0 は番号なし）
                    numid = num.find(w("numId"))
                    numbered = numid is None or numid.get(w("val")) != "0"
            based = s.find(w("basedOn"))
            cur = based.get(w("val")) if based is not None else None
        self.cache[sid] = (name or "Normal", outline, bool(numbered))   # 既定のスタイルが無い文書は標準扱い
        return self.cache[sid]

    def para(self, p):
        """(スタイル名, 見出しの階層 0=見出しでない, 番号付きか)"""
        w = self.w
        ppr = p.find(w("pPr"))
        sid = None
        if ppr is not None and ppr.find(w("pStyle")) is not None:
            sid = ppr.find(w("pStyle")).get(w("val"))
        name, outline, numbered = self.style_info(sid or self.default)
        if ppr is not None:
            if ppr.find(w("outlineLvl")) is not None:
                outline = int(ppr.find(w("outlineLvl")).get(w("val")))
            num = ppr.find(w("numPr"))
            if num is not None:
                numid = num.find(w("numId"))
                numbered = numid is None or numid.get(w("val")) != "0"
        level = 1 if name in TITLE_STYLES else 0
        m = HEADING_RE.match(name)
        if m:
            level = int(m.group(2))
        elif not level and outline is not None and outline < 9:
            level = outline + 1
        return name, level, numbered


def para_line(reader, p):
    from wordml import pieces, visible_text
    text = visible_text(pieces(p))
    style, level, numbered = reader.para(p)
    if not text.strip():
        return text, 0, ""
    reader.used[style] += 1
    if level:
        return text, level, "#" * level + " " + text
    if numbered or any(h in style for h in LIST_HINTS):
        return text, 0, "- " + text
    if style and style not in NORMAL_STYLES:
        return text, 0, "[%s] %s" % (style, text)
    return text, 0, text


def cell_text(reader, tc):
    """セルの文字。入れ子の表は [表: …]、テキストボックスは [テキストボックス: …] としてセルの中に出す。"""
    from wordml import pieces, textbox_paragraphs, visible_text, w
    out = []
    for b in blocks(tc):
        if b.tag == w("tbl"):
            rows = [" / ".join(cell_text(reader, c) for c in cells(r)) for r in rows_of(b)]
            out.append("[表: %s]" % " // ".join(rows))
            continue
        t = visible_text(pieces(b))
        if t.strip():
            out.append(t)
            reader.used[reader.para(b)[0]] += 1     # 表の中の段落もスタイルの集計に入れる
        for q in textbox_paragraphs(b):
            t = visible_text(pieces(q))
            if t.strip():
                out.append("[テキストボックス: %s]" % t)
    return " ".join(out).replace("\n", " ").replace("\t", " ").replace("|", "\\|")


def rows_of(tbl):
    """表の行。コンテンツコントロールで包まれた行（繰り返しセクションなど）の中も見る。"""
    from wordml import w
    return [el for el in tbl.iter(w("tr")) if _owner_table(el) is tbl]


def cells(tr):
    from wordml import w
    return [el for el in tr.iter(w("tc")) if el.getparent() is tr or _owner_row(el) is tr]


def _owner_table(el):
    from wordml import w
    a = el.getparent()
    while a is not None and a.tag != w("tbl"):
        a = a.getparent()
    return a


def _owner_row(el):
    from wordml import w
    a = el.getparent()
    while a is not None and a.tag != w("tr"):
        a = a.getparent()
    return a


def table_lines(reader, tbl):
    from wordml import w
    rows = []
    for tr in rows_of(tbl):
        row = []
        trpr = tr.find(w("trPr"))
        before = trpr.find(w("gridBefore")) if trpr is not None else None
        if before is not None:                    # 行の左側の空き列
            row += [""] * int(before.get(w("val")))
        for tc in cells(tr):
            tcpr = tc.find(w("tcPr"))
            span, vcont = 1, False
            if tcpr is not None:
                gs = tcpr.find(w("gridSpan"))
                if gs is not None:
                    span = int(gs.get(w("val")))
                vm = tcpr.find(w("vMerge"))
                vcont = vm is not None and vm.get(w("val"), "continue") == "continue"
            row.append("↑" if vcont else cell_text(reader, tc))
            row += ["←"] * (span - 1)
        rows.append(row)
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return out


def blocks(el):
    """本文の段落と表を文書の順に返す。コンテンツコントロール（w:sdt）と w:customXml の中へも降りる。"""
    from wordml import w
    for c in el:
        if c.tag == w("p"):
            yield c
        elif c.tag == w("tbl"):
            yield c
        elif c.tag in (w("sdt"), w("customXml")):
            inner = c.find(w("sdtContent")) if c.tag == w("sdt") else c
            if inner is not None:
                yield from blocks(inner)


def body_entries(reader, body):
    """本文を (見出しの階層, 行のリスト) の列にする。"""
    from wordml import pieces, textbox_paragraphs, visible_text, w
    out = []
    for b in blocks(body):
        if b.tag == w("tbl"):
            out.append((0, [""] + table_lines(reader, b) + [""]))
            continue
        text, level, line = para_line(reader, b)
        lines = [line]
        for q in textbox_paragraphs(b):
            t = visible_text(pieces(q))
            if t.strip():
                lines.append("[テキストボックス] " + t)
        out.append((level, lines))
    return out


def notes(parts):
    """脚注・文末脚注を [^n]: 本文 の行にする。区切り線用の脚注は出さない。"""
    from wordml import pieces, visible_text, w
    out = {"": [], "e": []}
    for label, root, _ in parts:
        if label not in ("脚注", "文末脚注"):
            continue
        prefix, tag = ("", w("footnote")) if label == "脚注" else ("e", w("endnote"))
        for n in root.findall(tag):
            if n.get(w("type")) not in (None, "normal"):
                continue
            text = " ".join(visible_text(pieces(p), notes=False) for p in n.iter(w("p"))).strip()
            out[prefix].append("[^%s%s]: %s" % (prefix, n.get(w("id")), text))
    return out[""], out["e"]


def summary(doc, path, reader, parts, notes_count, chars):
    from docx.oxml.ns import qn
    from wordml import in_fallback, pieces, visible_text, w
    lines = ["# %s" % path.name, ""]
    even = doc.settings.odd_and_even_pages_header_footer
    for i, s in enumerate(doc.sections, 1):
        if s.page_width is None:
            continue
        lines.append("- セクション%d: %.0f×%.0f mm（%s）、余白 上%.0f 下%.0f 左%.0f 右%.0f mm" % (
            i, s.page_width.mm, s.page_height.mm,
            "横" if s.page_width > s.page_height else "縦",
            s.top_margin.mm, s.bottom_margin.mm, s.left_margin.mm, s.right_margin.mm))
        kinds = [("ヘッダー", s.header), ("フッター", s.footer)]
        # 設定を外しても部品は残るので、表示される設定のときだけ出す
        if s.different_first_page_header_footer:
            kinds += [("先頭ページのヘッダー", s.first_page_header), ("先頭ページのフッター", s.first_page_footer)]
        if even:
            kinds += [("偶数ページのヘッダー", s.even_page_header), ("偶数ページのフッター", s.even_page_footer)]
        for label, part in kinds:
            if part.is_linked_to_previous:
                continue
            text = " / ".join(t for t in (visible_text(pieces(p)) for p in part._element.iter(w("p"))
                                          if not in_fallback(p)) if t.strip())
            if text:
                lines.append("  - %s: %s" % (label, text if len(text) <= HEADER_CHARS else text[:HEADER_CHARS] + "…"))
    lines.append("- 段落スタイル: " + ", ".join("%s(%d)" % kv for kv in reader.used.most_common()))

    roots = [root for _, root, _ in parts]
    body = doc.element.body
    fields = [f.get(qn("w:instr")) for r in roots for f in r.iter(qn("w:fldSimple"))]
    fields += [t.text for r in roots for t in r.iter(qn("w:instrText")) if t.text and t.text.strip()]

    def count(tags, root_list, mark=None):
        # 段落記号の変更（w:rPr の中の w:ins / w:del）は文字の変更と分けて数える。Fallback の複製は数えない
        n = 0
        for r in root_list:
            for el in r.iter(*tags):
                if in_fallback(el):
                    continue
                if mark is None or (el.getparent().tag == w("rPr")) == mark:
                    n += 1
        return n

    counts = [
        ("表", count([w("tbl")], [body])),
        ("画像", count(["{http://schemas.openxmlformats.org/drawingml/2006/picture}pic"], [body])),
        ("テキストボックス", count([w("txbxContent")], [body])),
        ("脚注", notes_count[0]),
        ("文末脚注", notes_count[1]),
    ]
    with zipfile.ZipFile(path) as z:
        if "word/comments.xml" in z.namelist():
            from lxml import etree
            counts.append(("コメント", len(etree.fromstring(z.read("word/comments.xml")).findall(w("comment")))))
    counts += [("変更履歴の挿入", count([w("ins")], roots, False)), ("変更履歴の削除", count([w("del")], roots, False))]
    marks = count([w("ins"), w("del")], roots, True)
    if marks:
        counts.append(("段落記号の挿入・削除", marks))
    lines.append("- " + "、".join("%s %d" % kv for kv in counts))
    kinds = Counter(f.strip().split()[0] for f in fields if f and f.strip())
    lines.append("- フィールド: " + (", ".join("%s(%d)" % kv for kv in kinds.most_common()) or "なし"))
    lines.append("- 本文: %d 字（脚注を含む）" % chars)
    lines.append("")
    return lines


def render(entries):
    out = []
    for _, lines in entries:
        for line in lines:
            if line or (out and out[-1] != ""):
                out.append(line)
    return out


def outline(entries):
    out, n = [], 0
    for level, lines in entries:
        if level:
            n += 1
            out.append("§%d %s" % (n, lines[0]))
    return out


def section(entries, number):
    n, start, level = 0, None, 0
    for i, (lv, _) in enumerate(entries):
        if lv:
            n += 1
            if n == number:
                start, level = i, lv
                continue
            if start is not None and lv <= level:
                return entries[start:i]
    return entries[start:] if start is not None else None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Word 文書の構造と本文を出す")
    ap.add_argument("docx")
    ap.add_argument("--outline", action="store_true", help="見出しだけ出す")
    ap.add_argument("--section", type=int, metavar="N", help="§N の節だけ出す")
    ap.add_argument("--full", action="store_true", help="長くても本文を省略しない")
    ap.add_argument("--out", help="出力をこのファイルに書く")
    args = ap.parse_args()

    try:
        import docx
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import wordml  # noqa: F401
    except ImportError:
        print("python-docx が必要: pip install python-docx", file=sys.stderr)
        return 2
    path = Path(args.docx)
    if not path.is_file():
        print("入力が存在しない: %s" % path, file=sys.stderr)
        return 2
    if path.suffix.lower() == ".doc":
        print(".doc は読めない。Word か LibreOffice で .docx に変換してから扱う", file=sys.stderr)
        return 2
    try:
        doc = docx.Document(str(path))
    except Exception as e:  # 壊れた zip・docx 以外の形式で python-docx が投げる例外はまちまち
        print("開けない: %s (%s)" % (path, e), file=sys.stderr)
        return 1

    from wordml import stories
    reader = Reader(doc)
    parts = stories(doc)
    entries = body_entries(reader, doc.element.body)
    foot, end = notes(parts)

    if args.section is not None:
        part = section(entries, args.section)
        if part is None:
            print("§%d の見出しが無い（--outline で番号を確かめる）" % args.section, file=sys.stderr)
            return 2
        body = render(part)
        refs = set(re.findall(r"\[\^(e?\d+)\]", "\n".join(body)))
        used = [n for n in foot + end if n[2:n.index("]")] in refs]
        text = "\n".join(body + ([""] + used if used else []))
    else:
        rendered = render(entries)
        if foot or end:
            rendered += ["", "## 脚注", ""] + foot + end
        chars = sum(len(line) for line in rendered)
        head = summary(doc, path, reader, parts, (len(foot), len(end)), chars)
        heads = outline(entries)
        if args.outline:
            body = heads
        elif chars > LIMIT and not (args.full or args.out):
            if heads:
                body = ["本文が %d 字あるので見出しの一覧だけを出す。--section N で節ごとに読むか、"
                        "--full か --out で全文を出す。" % chars, ""] + heads
            else:   # 見出しの無い文書は、先頭から LIMIT 字まで出す
                body, n = [], 0
                for line in rendered:
                    if n + len(line) > LIMIT:
                        break
                    body.append(line)
                    n += len(line)
                body += ["", "（見出しが無いので先頭 %d 字だけを出した。残り %d 字は --out FILE か --full で読む）"
                         % (n, chars - n)]
        else:
            body = rendered
        text = "\n".join(head + body)

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(args.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
