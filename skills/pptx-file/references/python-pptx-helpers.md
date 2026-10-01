# python-pptx の補助関数と落とし穴

SKILL.md の手順2で、スライドを作る・並べ替える・消すときに読む。下の関数は PowerPoint 2021 で開いて PDF に変換し、結果を画像で確かめてある。

## 補助関数

```python
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Mm, Pt


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
    """index 番目（0始まり）のスライドを削除する。python-pptx には API が無い。"""
    sld_ids = prs.slides._sldIdLst
    sld_id = sld_ids[index]
    prs.part.drop_rel(sld_id.rId)
    sld_ids.remove(sld_id)


def move_slide(prs, old, new):
    """スライドの順番を入れ替える（0始まり）。"""
    sld_ids = prs.slides._sldIdLst
    el = sld_ids[old]
    sld_ids.remove(el)
    sld_ids.insert(new, el)
```

`set_ja_font` は文字を入れた後に呼ぶ（run が無いと何もしない）。全スライドに当てるなら:

```python
for slide in prs.slides:
    for shape in slide.shapes:
        if shape.has_text_frame:
            set_ja_font(shape.text_frame)
```

## 最小の流れ

```python
prs = Presentation()                       # テンプレートがあれば Presentation("template.pptx")
widen_to_16x9(prs)                         # テンプレートを使うときは呼ばない
s = prs.slides.add_slide(prs.slide_layouts[1])          # レイアウトは inspect_pptx.py --layouts で選ぶ
s.shapes.title.text = "結論：リリースは予定どおり 11 月"
tf = s.placeholders[1].text_frame
tf.text = "残課題は 3 件、すべて担当者が決まっている"
tf.add_paragraph().text = "性能試験は 10/20 に完了見込み"
s.notes_slide.notes_text_frame.text = "話す内容はノートへ"
prs.save("out.pptx")
```

## 落とし穴

| 症状 | 原因 | 対処 |
|---|---|---|
| 4:3 のスライドになる | python-pptx の既定テンプレートは 4:3（254×190.5 mm） | `widen_to_16x9()` を呼ぶ。大きさだけ変えると枠が左に寄る |
| 和文だけ別のフォントになる | `font.name` は `a:latin` しか変えない | `set_ja_font()` で `a:ea` も指定する |
| 文字が枠からあふれる | python-pptx は文字の量に合わせて縮小しない。自動調整の設定は PowerPoint で編集したときにしか効かない | 文字を減らすか枠を広げる。画像で確かめる |
| スライドを複製したい | python-pptx に複製の API は無い。図形の XML を写すと画像やグラフの参照が切れる | 同じレイアウトから `add_slide` で作り直す。テンプレートの見本スライドは使った後に `delete_slide` で消す |
| 箇条書きの記号が出ない・二重になる | テキストボックスに「・」を打った | 本文プレースホルダ（レイアウトの OBJECT / BODY）に段落として入れる。字下げは `paragraph.level` |
| 表やグラフの位置が他の枠と重なる | 座標を目分量で決めた | `inspect_pptx.py --layouts` の枠の位置と大きさを使って配置し、`--check` で重なりを見る |
