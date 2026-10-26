# python-pptx の補助関数と落とし穴

SKILL.md の手順2で、スライドを作る・並べ替える・消すときに読む。下の関数は PowerPoint 2021 で開いて PDF に変換し、結果を画像で確かめてある。

## 補助関数

```python
import io
import zipfile

from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Mm, Pt


def open_template(path):
    """テンプレート（.potx）を開く。python-pptx は .potx をそのまま渡すと ValueError で開かない。
    種類の宣言だけ .pptx に読み替えて開き、保存は .pptx にする。.pptx はそのまま開く。"""
    if not str(path).lower().endswith(".potx"):
        return Presentation(path)
    buf = io.BytesIO()
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(b"presentationml.template.main+xml", b"presentationml.presentation.main+xml")
            dst.writestr(item, data)
    buf.seek(0)
    return Presentation(buf)


def widen_to_16x9(prs):
    """既定テンプレート（4:3）を 16:9 にし、マスターとレイアウトの枠を横方向に伸ばす。
    スライドの大きさを変えるだけでは、枠が 4:3 の位置に残って左に寄る。スライドを足す前に呼ぶ。"""
    old_w = prs.slide_width
    prs.slide_width, prs.slide_height = Mm(338.67), Mm(190.5)
    factor = prs.slide_width / old_w
    for master in prs.slide_masters:
        for shapes in [master.shapes] + [layout.shapes for layout in master.slide_layouts]:
            for shape in shapes:
                # 自前の位置を持つ枠だけ伸ばす。位置を継承している枠は、伸ばした親に従う
                xfrm = shape._element.find(".//" + qn("a:xfrm"))
                if xfrm is None or xfrm.find(qn("a:off")) is None:
                    continue
                left, top, width, height = shape.left, shape.top, shape.width, shape.height
                shape.left, shape.width = int(left * factor), int(width * factor)
                shape.top, shape.height = top, height


def set_ja_font(text_frame, name="游ゴシック"):
    """枠内の全 run に欧文・和文フォントを指定する。font.name は欧文（a:latin）しか変えない。"""
    for p in text_frame.paragraphs:
        for r in p.runs:
            r.font.name = name
            rpr = r.font._rPr
            ea = rpr.find(qn("a:ea"))
            if ea is None:
                ea = rpr.makeelement(qn("a:ea"), {})
                rpr.find(qn("a:latin")).addnext(ea)
            ea.set("typeface", name)


def delete_slide(prs, index):
    """index 番目（0始まり）のスライドを削除する。python-pptx には API が無い。
    他のスライドからこのスライドへのリンク（クリックで移動など）は外す。リンク以外の参照があれば
    何も変えずに ValueError を出す。参照を残すと、消したスライドが保存時に残りと同じ部品名で書かれ、
    zip に同名の部品が2つできて PowerPoint で開けなくなる。"""
    sld_ids = prs.slides._sldIdLst
    sld_id = sld_ids[index]
    target = prs.part.related_part(sld_id.rId)
    links = []
    for slide in prs.slides:
        part = slide.part
        for rId in list(part.rels):
            rel = part.rels[rId]
            if part is target or rel.is_external or rel.target_part is not target:
                continue
            for el in part._element.xpath('.//*[@r:id="%s"]' % rId):
                if el.tag not in (qn("a:hlinkClick"), qn("a:hlinkHover")):
                    raise ValueError("スライド %d の %s が削除対象を参照している" % (prs.slides.index(slide) + 1, el.tag))
                links.append((part, el, rId))
    for part, el, rId in links:
        el.getparent().remove(el)
        part.drop_rel(rId)
    prs.part.drop_rel(sld_id.rId)
    sld_ids.remove(sld_id)
    # 部品名（slideN.xml）を詰め直す。これを省くと、後の add_slide が残りのスライドと同じ名前を付け、
    # 保存した zip に同名の部品が2つでき、スライドが1枚消えて別のスライドの複製になる
    prs.part.rename_slide_parts([s.rId for s in sld_ids])


def move_slide(prs, old, new):
    """スライドの順番を入れ替える（0始まり）。"""
    sld_ids = prs.slides._sldIdLst
    el = sld_ids[old]
    sld_ids.remove(el)
    sld_ids.insert(new, el)


def iter_text_frames(shapes):
    """図形の文字枠を、グループの中と表のセルまで含めて返す。slide.shapes の素朴なループは両方を取りこぼす。
    グラフの中の文字は返さない。"""
    for shape in shapes:
        if shape.shape_type is not None and str(shape.shape_type).startswith("GROUP"):
            yield from iter_text_frames(shape.shapes)
        elif getattr(shape, "has_table", False) and shape.has_table:
            for row in shape.table.rows:
                for cell in row.cells:
                    yield cell.text_frame
        elif shape.has_text_frame:
            yield shape.text_frame
```

`set_ja_font` は文字を入れた後に呼ぶ（run が無いと何もしない）。全スライドに当てるときは `iter_text_frames()` で回す（下の「最小の流れ」の最後）。

## 最小の流れ

```python
prs = Presentation()                       # テンプレートがあれば open_template("template.potx")
widen_to_16x9(prs)                         # テンプレートを使うときは呼ばない
s = prs.slides.add_slide(prs.slide_layouts[1])          # レイアウトは inspect_pptx.py --layouts で選ぶ
s.shapes.title.text = "結論：リリースは予定どおり 11 月"
tf = s.placeholders[1].text_frame
tf.text = "残課題は 3 件、すべて担当者が決まっている"
tf.add_paragraph().text = "性能試験は 10/20 に完了見込み"
s.notes_slide.notes_text_frame.text = "話す内容はノートへ"
for slide in prs.slides:                   # テンプレートを使うときは呼ばない（様式のフォントに任せる）
    for tf in iter_text_frames(slide.shapes):
        set_ja_font(tf)
prs.save("out.pptx")
```

## 落とし穴

| 症状 | 原因 | 対処 |
|---|---|---|
| 4:3 のスライドになる | python-pptx の既定テンプレートは 4:3（254×190.5 mm） | `widen_to_16x9()` を呼ぶ。大きさだけ変えると枠が左に寄る |
| 和文だけ別のフォントになる | `font.name` は `a:latin` しか変えない | `set_ja_font()` で `a:ea` も指定する |
| 文字が枠からあふれる | python-pptx は文字の量に合わせて縮小しない。自動調整の設定は PowerPoint で編集したときにしか効かない | 文字を減らすか枠を広げる。画像で確かめる |
| `Presentation("x.potx")` が ValueError（is not a PowerPoint file）になる | python-pptx は .potx の種類宣言を受け付けない | `open_template()` で開き、`.pptx` で保存する。マクロ付きの .potm は扱わない |
| スライドを消した後の保存ファイルを PowerPoint が開けない（zip に同名の部品が2つできる） | 消した後に足すと、python-pptx が残りと同じ部品名を付ける。他のスライドからリンクされたスライドを消すと、追加しなくても起きる | `delete_slide()`（リンクを外し、部品名を詰め直す）を使う。自前で `_sldIdLst` から消さない |
| 既存の文字を書き換えたら、フォント・色・太字が消えた | `shape.text = ...` や `paragraph.text = ...` は run を作り直し、run の書式を捨てる | 書式を残すなら `paragraph.runs[0].text = ...` で書き換え、残りの run は `.text = ""` にする |
| 表のセルやグループの中だけ和文フォントが変わらない | `slide.shapes` のループは表のセルとグループの中を回らない | `iter_text_frames()` で回す |
| スライドを複製したい | python-pptx に複製の API は無い。図形の XML を写すと画像やグラフの参照が切れる | 同じレイアウトから `add_slide` で作り直す。テンプレートの見本スライドは使った後に `delete_slide` で消す |
| 箇条書きの記号が出ない・二重になる | テキストボックスに「・」を打った | 本文プレースホルダ（レイアウトの OBJECT / BODY）に段落として入れる。字下げは `paragraph.level` |
| 表やグラフの位置が他の枠と重なる | 座標を目分量で決めた | `inspect_pptx.py --layouts` の枠の位置と大きさを使って配置し、`--check` で重なりを見る |
