# 新しく作るときの雛形と注意点

SKILL.md の手順2で、Word 文書を新しく作るときに読む。下のコードは Word 2021 で開いて PDF に変換し、和文フォント（游ゴシック）が埋め込まれることを確かめてある。

## 雛形

```python
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt


def set_font(style, name):
    """欧文と和文の両方のフォントを指定する。テーマフォントの指定が残っているとそちらが勝つので消す。"""
    style.font.name = name
    rfonts = style.element.get_or_add_rPr().get_or_add_rFonts()
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        rfonts.attrib.pop(qn(attr), None)
    rfonts.set(qn("w:eastAsia"), name)


def add_page_number(paragraph):
    """段落に PAGE フィールド（ページ番号）を入れる。"""
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    paragraph._p.append(fld)


doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Mm(210), Mm(297)      # 既定は US Letter
sec.top_margin = sec.bottom_margin = Mm(25)
sec.left_margin = sec.right_margin = Mm(20)

for name in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3"):
    set_font(doc.styles[name], "游ゴシック")
doc.styles["Normal"].font.size = Pt(10.5)

doc.add_heading("基本設計書", level=0)                 # Title スタイル
doc.add_heading("1. 目的", level=1)
doc.add_paragraph("本書は○○の基本設計を示す。")
doc.add_paragraph("箇条書きは記号を打たずスタイルで作る", style="List Bullet")
doc.add_paragraph("番号付きは List Number", style="List Number")

table = doc.add_table(rows=1, cols=3)
table.style = "Table Grid"
for cell, text in zip(table.rows[0].cells, ("項目", "内容", "備考")):
    cell.text = text
row = table.add_row().cells
row[0].text, row[1].text = "入力", "CSV"

doc.add_page_break()
doc.add_heading("2. 構成", level=1)

footer = sec.footer.paragraphs[0]
footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
add_page_number(footer)

doc.save("out.docx")
```

## 落とし穴

| 症状 | 原因 | 対処 |
|---|---|---|
| 用紙が A4 にならない | python-docx の既定テンプレートは US Letter（216×279 mm） | 雛形のとおり `page_width` `page_height` を `Mm(210)` `Mm(297)` にする |
| 和文だけ明朝や別フォントになる | `font.name` は欧文フォントしか変えない。見出しはテーマフォントの指定が優先される | `set_font()` で `w:eastAsia` を設定し、テーマ属性を消す |
| 箇条書きの記号が二重になる・揃わない | 「・」や「●」を本文に直接打った | `List Bullet` / `List Number` スタイルを使う |
| 目次に見出しが出ない | 見出しを太字の本文で作った | `add_heading()`（組込みの見出しスタイル）を使う。目次そのものはユーザーが Word で「目次の更新」をする必要がある |
| 改行が段落にならない | `"\n"` を含む文字列を1段落に入れた | 段落ごとに `add_paragraph()` を呼ぶ |
| 表の列幅が崩れる | 列幅を指定していない | 各セルの `width` を `Mm()` で指定する（列単位の指定だけでは Word が無視することがある） |
| 画像がはみ出す | 画像の原寸で入れた | `doc.add_picture(path, width=Mm(150))` のように本文幅以下で入れる |

## テンプレートがあるとき

社内様式の `.dotx` や既存の `.docx` を渡されたら、それを `Document(path)` で開いて本文だけ差し替える。スタイル・ヘッダー・余白は様式のものを使い、`set_font()` などで上書きしない。`.dotx` は python-docx で直接開けないことがあるので、Word で `.docx` として保存し直してもらうか、同じ様式の既存文書を使う。
