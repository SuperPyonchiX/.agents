# コメントと変更履歴（校閲）

SKILL.md の手順2で、コメントを付ける・変更履歴付きで直す・既存の変更履歴を扱うときに読む。下のコードは Word 2021 で開けること、`inspect_docx.py` で件数が数えられることを確かめてある。

## コメント

python-docx 1.2 以降は API で付けられる。`pip show python-docx` で版を確かめる。

```python
doc.add_comment(paragraph.runs, text="対象範囲を明記すること", author="レビュー担当", initials="RV")
```

第1引数はコメントを掛ける範囲の run（1つか、連続する run のリスト）。語の一部にだけ掛けたいときは、先に `docx_replace.py` と同じ要領で run を分けるか、段落全体に掛けて本文で範囲を書く。

## 変更履歴

python-docx には API が無いので XML を直接組む。変更履歴は `w:ins`（挿入）と `w:del`（削除）で run を包み、`w:id`（文書内で一意な番号）・`w:author`・`w:date` を付ける。

```python
import datetime
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

NOW = datetime.datetime.now().replace(microsecond=0).isoformat() + "Z"
_rev_id = [1000]   # 既存の w:id と重ならない番号から始める


def rev_attrs(el, author):
    _rev_id[0] += 1
    el.set(qn("w:id"), str(_rev_id[0]))
    el.set(qn("w:author"), author)
    el.set(qn("w:date"), NOW)


def tracked_insert(paragraph, text, author):
    """段落の末尾に、挿入として文字を足す。"""
    ins = OxmlElement("w:ins"); rev_attrs(ins, author)
    r = OxmlElement("w:r"); t = OxmlElement("w:t")
    t.text = text; t.set(qn("xml:space"), "preserve")
    r.append(t); ins.append(r); paragraph._p.append(ins)


def tracked_delete(run, author):
    """run 全体を削除扱いにする。w:t を w:delText に変え、w:del で包む。"""
    r = run._r
    for t in r.findall(qn("w:t")):
        t.tag = qn("w:delText")
    d = OxmlElement("w:del"); rev_attrs(d, author)
    r.addprevious(d); d.append(r)
```

決まり:

- 削除した run の中の文字は `w:t` ではなく `w:delText` にする（OOXML の決まり）。`w:t` のまま `w:del` で包まない
- 語の一部だけを置き換えるときは、run を「前・対象・後」の3つに分けてから、対象の run を `tracked_delete`、直後に新しい文字を `w:ins` で入れる。分けた run には元の `w:rPr`（書式）を `copy.deepcopy` で写す
- 段落ごと消すときは、全 run を削除扱いにするだけでは**空の段落が残る**（箇条書きなら記号だけの行になる）。段落記号も削除扱いにする。`w:pPr` の中の `w:rPr` に `w:del`（属性は同じ）を入れる。`w:rPr` の子要素の中では `w:del` を先頭に置く。この項目と前の項目（run の分割）は OOXML の仕様に沿った書き方で、上のコードと違い実機では確かめていない。使ったら Word で開いて確かめる
- 変更履歴付きで直すときは、変えた箇所が漏れなく `w:ins` / `w:del` に入っているかを `inspect_docx.py` の件数と、直す前後の本文の差で確かめる。包み忘れた変更は「変更履歴を表示」にしても見えない

## 見た目の確かめ方

`pdf` の `to_pdf.py`（Word 経由）で作った PDF は、**変更履歴を反映した後の表示**になる。挿入した文字は普通の文字として、削除した文字は消えた状態で出る。変更履歴そのもの（色付きの挿入・取り消し線・コメント吹き出し）の見え方は PDF では確かめられないので、ユーザーに Word で開いて確かめてもらう。

## 既存の変更履歴を扱う

- 件数は `inspect_docx.py` の冒頭に出る（`変更履歴の挿入` `変更履歴の削除` `コメント`）
- 「変更履歴をすべて承諾した版」が欲しいと言われたら、XML で自前処理せず、ユーザーに Word の「すべての変更を反映」を使ってもらうのが確実。段落記号の削除の扱いを取り違えやすいため
- 変更履歴が残っている文書に `docx_replace.py` を当てると、削除済みの文字（`w:delText`）は対象外、挿入済みの文字（`w:ins` の中の `w:t`）は対象になる
