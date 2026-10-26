# -*- coding: utf-8 -*-
"""inspect_docx.py と docx_replace.py が共有する、WordprocessingML の文字の読み方。直接は実行しない。

python-docx の Paragraph.text は段落の直下の run と hyperlink しか見ないので、変更履歴で挿入した文字・
コンテンツコントロール（w:sdt）の中の文字を落とす。逆に段落の w:t を子孫まで集めると、テキストボックスの
中の段落を外側の段落とつないでしまう。ここでは段落が「自分で持つ」文字だけを、文書の順に区切りつきで返す。
"""

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def w(tag):
    return "{%s}%s" % (W_NS, tag)


# 文字として読まない（削除済み・移動元・段落の設定）
SKIP_CONTAINERS = {w("del"), w("moveFrom"), w("pPr"), w("sdtPr"), w("sdtEndPr"), w("customXmlPr"),
                   w("smartTagPr")}
# 中へ降りて読む（挿入・移動先・リンク・コンテンツコントロール）。単純フィールド（w:fldSimple）は
# 出入りに区切りを置いてから降りる
DESCEND = {w("ins"), w("moveTo"), w("hyperlink"), w("smartTag"), w("sdt"), w("sdtContent"),
           w("customXml"), w("dir"), w("bdo")}
# run の中で、文字にも区切りにもならないもの
RUN_IGNORE = {w("rPr"), w("lastRenderedPageBreak"), w("softHyphen"), w("instrText"), w("delText"),
              w("delInstrText"), w("annotationRef"), w("separator"), w("continuationSeparator"),
              w("footnoteRef"), w("endnoteRef")}

BARRIER = "￼"   # 図・脚注番号・フィールドの境目など、文字の途中に挟まる非文字


class Piece:
    """段落の中の1要素。kind は text（w:t。置換できる）/ char（タブ・改行・改行しないハイフン。見えるが
    置換できない）/ note（脚注・文末脚注の参照）/ barrier（図・フィールドの境目など。見えない）。"""
    __slots__ = ("kind", "text", "el", "run")

    def __init__(self, kind, text, el, run):
        self.kind, self.text, self.el, self.run = kind, text, el, run


def pieces(p):
    """段落 p が自分で持つ要素を文書の順に返す。テキストボックスの中の段落は含めない。"""
    out = []

    def run_children(r):
        for c in r:
            tag = c.tag
            if tag == w("t"):
                out.append(Piece("text", c.text or "", c, r))
            elif tag == w("tab") or tag == w("ptab"):
                out.append(Piece("char", "\t", c, r))
            elif tag in (w("br"), w("cr")):
                out.append(Piece("char", "\n", c, r))
            elif tag == w("noBreakHyphen"):
                out.append(Piece("char", "-", c, r))
            elif tag in (w("footnoteReference"), w("endnoteReference")):
                prefix = "" if tag == w("footnoteReference") else "e"
                out.append(Piece("note", "[^%s%s]" % (prefix, c.get(w("id"))), c, r))
            elif tag in RUN_IGNORE or not isinstance(tag, str):
                continue
            else:  # 図・テキストボックス・フィールドの境目・記号など
                out.append(Piece("barrier", BARRIER, c, r))

    def walk(el):
        for c in el:
            tag = c.tag
            if not isinstance(tag, str) or tag in SKIP_CONTAINERS:
                continue
            if tag == w("r"):
                run_children(c)
            elif tag in DESCEND:
                walk(c)
            elif tag == w("fldSimple"):
                out.append(Piece("barrier", BARRIER, c, None))
                walk(c)
                out.append(Piece("barrier", BARRIER, c, None))
            elif tag.startswith("{http://schemas.openxmlformats.org/officeDocument/2006/math}"):
                out.append(Piece("barrier", BARRIER, c, None))   # 数式

    walk(p)
    return out


def visible_text(ps, notes=True):
    """pieces を人が読む文字にする。区切りは消し、脚注の参照は [^n] で残す。"""
    return "".join(x.text for x in ps if x.kind in ("text", "char") or (notes and x.kind == "note"))


def in_fallback(el):
    """mc:Fallback（古い Word 向けの複製。テキストボックスは Choice と Fallback の2通り保存される）の中か。"""
    a = el.getparent()
    while a is not None:
        if a.tag == "{%s}Fallback" % MC_NS:
            return True
        a = a.getparent()
    return False


def textbox_paragraphs(p):
    """段落 p に置かれたテキストボックスの中の段落（Fallback の複製を除く）。"""
    return [q for q in p.iter(w("p")) if q is not p and not in_fallback(q)]


def has_ancestor(el, tags, stop=None):
    """el の祖先（stop の手前まで）に tags のどれかがあるか。"""
    a = el.getparent()
    while a is not None and a is not stop:
        if a.tag in tags:
            return True
        a = a.getparent()
    return False


DELETED = {w("del"), w("moveFrom")}
INSERTED = {w("ins"), w("moveTo")}


def field_results(root):
    """フィールドの結果（目次・相互参照・文書プロパティなどの表示文字）にある w:t の集合。

    複合フィールドは begin…separate…end が段落をまたぐ（目次など）ので、部品全体を文書の順に見る。
    """
    out, stack = set(), []
    for el in root.iter(w("fldChar"), w("t"), w("fldSimple")):
        if el.tag == w("fldSimple"):
            out.update(el.iter(w("t")))
        elif el.tag == w("fldChar"):
            kind = el.get(w("fldCharType"))
            if kind == "begin":
                stack.append("code")
            elif kind == "separate" and stack:
                stack[-1] = "result"
            elif kind == "end" and stack:
                stack.pop()
        elif stack and stack[-1] == "result":
            out.add(el)
    return out


REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
STORY_RELS = {REL + "header": "ヘッダー", REL + "footer": "フッター", REL + "footnotes": "脚注",
              REL + "endnotes": "文末脚注"}


def stories(doc):
    """置換・集計の対象になる文書の部品を (ラベル, ルート要素, 保存関数) で返す。

    本文と、本文から関係（relationship）でつながるヘッダー・フッター・脚注・文末脚注。部品名には頼らない。
    python-docx が型を持たない部品（脚注など）はバイト列から解析し、保存関数で書き戻す。
    """
    out, seen = [("本文", doc.element.body, None)], set()
    for rel in doc.part.rels.values():
        label = STORY_RELS.get(rel.reltype)
        if label is None or rel.is_external or id(rel.target_part) in seen:
            continue
        part = rel.target_part
        seen.add(id(part))
        if hasattr(part, "element"):
            out.append((label, part.element, None))
        else:
            root = etree.fromstring(part.blob)

            def save(part=part, root=root):
                part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            out.append((label, root, save))
    return out
