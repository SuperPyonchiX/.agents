# コメントと変更履歴（校閲）

SKILL.md の手順2で、コメントを付ける・変更履歴付きで直す・既存の変更履歴を扱うときに読む。下のコードは Word 2021 で開けること、`inspect_docx.py` で件数が数えられることを確かめてある。

## コメント

python-docx 1.2 以降は API で付けられる。`pip show python-docx` で版を確かめる。

```python
doc.add_comment(paragraph.runs, text="対象範囲を明記すること", author="レビュー担当", initials="RV")
```

第1引数はコメントを掛ける範囲の run（1つか、連続する run のリスト）。語の一部にだけ掛けたいときは、段落全体に掛けてコメントの本文で範囲を書く。

## 変更履歴

**文言の置き換えは `docx_replace.py --track 校閲者名` を使う。** run の分割・書式の複写・`w:delText` への変換・番号の採番をスクリプトが行う。ここに書くのは、置換では表せない変更（段落を足す・消す）だけ。

python-docx には API が無いので XML を直接組む。変更履歴は `w:ins`（挿入）と `w:del`（削除）で run を包み、`w:id`（文書内で一意な番号）・`w:author`・`w:date`（現地時刻に Z を付ける。下のコードの注記を参照）を付ける。

```python
import datetime
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# Word は w:date を現地時刻として読み書きする（末尾の Z に反して）。本物の UTC を書くと日本では
# Word の表示が9時間ずれる（Word 2021 で確認）。Word に合わせて現地時刻に Z を付ける
NOW = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")


def next_rev_id(doc):
    """文書内の既存の w:id（変更履歴・コメント・ブックマーク）より大きい番号を返す。
    本文だけでなく、ヘッダー・フッター・脚注・コメントの部品も見る。"""
    import re
    ids = [0]
    for part in doc.part.package.iter_parts():
        if str(part.partname).startswith("/word/") and str(part.partname).endswith(".xml"):
            ids += [int(v) for v in re.findall(rb'w:id="(\d+)"', part.blob)]
    return max(ids) + 1


_rev_id = [None]


def rev_attrs(doc, el, author):
    if _rev_id[0] is None:
        _rev_id[0] = next_rev_id(doc)
    el.set(qn("w:id"), str(_rev_id[0]))
    _rev_id[0] += 1
    el.set(qn("w:author"), author)
    el.set(qn("w:date"), NOW)


def tracked_insert(doc, paragraph, text, author):
    """段落の末尾に、挿入として文字を足す。"""
    ins = OxmlElement("w:ins"); rev_attrs(doc, ins, author)
    r = OxmlElement("w:r"); t = OxmlElement("w:t")
    t.text = text; t.set(qn("xml:space"), "preserve")
    r.append(t); ins.append(r); paragraph._p.append(ins)


def tracked_delete(doc, run, author):
    """run 全体を削除扱いにする。w:t を w:delText に変え、w:del で包む。"""
    r = run._r
    for t in r.findall(qn("w:t")):
        t.tag = qn("w:delText")
    d = OxmlElement("w:del"); rev_attrs(doc, d, author)
    r.addprevious(d); d.append(r)
```

決まり:

- 削除した run の中の文字は `w:t` ではなく `w:delText` にする（OOXML の決まり）。`w:t` のまま `w:del` で包まない
- `run.text` 経由で読むと変更履歴の中の文字が抜ける（python-docx は `w:ins` の中の run を返さない）。中身の確認は `inspect_docx.py` で行う
- 段落ごと消すときは、全 run を削除扱いにするだけでは**空の段落が残る**（箇条書きなら記号だけの行になる）。段落記号も削除扱いにする。`w:pPr` の中の `w:rPr` に `w:del`（属性は同じ）を入れる。`w:rPr` の子要素の中では `w:del` を先頭に置く。この項目は OOXML の仕様に沿った書き方で、実機では確かめていない。使ったら Word で開いて確かめる
- 変更履歴付きで直したら、`inspect_docx.py` の「変更履歴の挿入・削除」（段落記号の分は別に出る）の増えた件数が、直した箇所の数と合うかを確かめる。包み忘れた変更は「変更履歴を表示」にしても見えない

## 見た目の確かめ方

`operate-pdf` の `to_pdf.py`（Word 経由）で作った PDF は、**変更履歴を反映した後の表示**になる。挿入した文字は普通の文字として、削除した文字は消えた状態で出る。変更履歴そのもの（色付きの挿入・取り消し線・コメント吹き出し）の見え方は PDF では確かめられないので、ユーザーに Word で開いて確かめてもらう。

## 既存の変更履歴を扱う

- 件数は `inspect_docx.py` の冒頭に出る（`変更履歴の挿入` `変更履歴の削除` `コメント`）
- 「変更履歴をすべて承諾した版」が欲しいと言われたら、XML で自前処理せず、ユーザーに Word の「すべての変更を反映」を使ってもらうのが確実。段落記号の削除の扱いを取り違えやすいため
- 変更履歴が残っている文書に `docx_replace.py` を当てると、削除済みの文字（`w:delText`）は対象外、挿入済みの文字（`w:ins` の中の `w:t`）は対象になる。`--track` のときは、挿入済みの文字の中の一致は置換せず、件数と箇所を出して終了コード1で止まる
