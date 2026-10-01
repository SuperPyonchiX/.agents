---
name: pdf-file
description: PDF を読む・加工する・作るスキル。テキスト・表・画像の抽出、結合・分割・回転・透かし・暗号化、フォーム記入、Word・Excel・PowerPoint からの PDF 化、ページの画像化を Python スクリプトで行う。「PDF から文字を抜いて」「PDF を結合して」「ページを分けて」「PDF のフォームに記入して」「PDF にして」「スキャンした PDF を読みたい」で使う。
metadata:
  web-description: PDF の抽出（テキスト・表・画像）、結合・分割・回転・透かし・暗号化、フォーム記入、Office ファイルの PDF 化とページの画像化を行う。「PDF から文字を抜いて」「PDF を結合して」「フォームに記入して」「PDF にして」で使う。
---

# PDF ファイルの操作

PDF の読み取り・ページ操作・フォーム記入・新規作成を、`scripts/` の4本で行う。
失敗しやすいのは3点。スキャン PDF に気づかず「空でした」と返す、入力ファイルを上書きして元に戻せなくする、和文を reportlab で直接組んで文字化けさせる。

`to_pdf.py` と `pdf_to_png.py` は `xlsx-file` `docx-file` `pptx-file` からも見た目の確認に使う。

## 手順

### 1. 中身を把握する

最初に必ず `meta` を見る。ページ数・用紙サイズ・暗号化・フォームの有無で以降の分岐が決まる。

```
python scripts/pdf_extract.py meta <pdf>
```

パスワード付きで開けなければ（終了コード1）、ユーザーにパスワードを尋ねて `pdf_ops.py decrypt` で解除してから進む。**パスワードを推測して試さない。**

### 2. 目的で分岐する

| 目的 | やり方 |
|---|---|
| 文字を読む | `pdf_extract.py text`。段組み・帳票は `--layout`。数十ページを超えるなら `--out` でファイルに出し、必要な箇所だけ読む |
| 表を読む | `pdf_extract.py tables`（要 `pdfplumber`）。罫線の無い表は取れないので `text --layout` で読む |
| 埋め込み画像を取り出す | `pdf_extract.py images --outdir DIR` |
| 結合・分割・回転 | `pdf_ops.py merge / split / rotate` |
| 透かし・社外秘印 | 印だけを載せた1ページの PDF を作り（下の「新しく作る」の方法で）、`pdf_ops.py stamp` |
| 暗号化・解除 | `pdf_ops.py encrypt / decrypt`（AES は要 `cryptography`） |
| フォームに記入 | 下の「フォーム記入」 |
| スキャン PDF を読む | 下の「スキャン PDF」 |
| 新しく作る | 下の「新しく作る」 |
| ページの見た目を確かめる | `pdf_to_png.py` で画像にして読む |
| どれにも当てはまらない（注釈・しおりの編集、ページの一部の書き換えなど） | pypdf で書けるかを調べ、書けるならスクリプトを書き捨てで作り、出力は別名にする。書けなければ止まり、できないことと代替案（元の Word などから作り直す）をユーザーに示す |

`text` が終了コード1（文字がほとんど取れない）を返したら、空として報告せず「スキャン PDF」へ進む。

### フォーム記入

1. `pdf_ops.py list-fields <pdf>` でフィールド名・種類・選択肢を出す
2. 値を `{"フィールド名": 値}` の JSON に書く。チェックボックスとラジオは `options` にある値（例 `/Yes`）をそのまま使う
3. `pdf_ops.py fill-form <pdf> <out> --data values.json`
4. `pdf_to_png.py` で記入後のページを画像にし、値が枠に収まって表示されているか見る

`list-fields` が終了コード1（フィールドが無い）なら、見た目だけの様式。記入欄の位置に文字を載せた1ページを作って `stamp` で重ねる。座標合わせは画像で確かめながら行う。

### スキャン PDF

- 数ページなら `pdf_to_png.py --dpi 150` で画像にし、画像を読んで書き起こす
- 多いなら OCR を入れる。`pytesseract` と Tesseract 本体、日本語の学習データ（`jpn`）が要る。導入はユーザーに確認してから

### 新しく作る

和文の PDF を reportlab で直接組むのは既定にしない。フォント登録を誤ると文字が化けるか欠ける。次の順で選ぶ。

1. 文書・帳票 → `docx-file` で Word を作り `to_pdf.py` で変換する
2. 表計算の帳票 → `xlsx-file` で作り `to_pdf.py`
3. 図や装飾の多い1枚もの → HTML を書き、ブラウザの印刷（Playwright の `page.pdf()` など）で PDF にする
4. それでも reportlab を使うなら、和文 TrueType フォント（例 `C:\Windows\Fonts\msgothic.ttc`、`ipaexg.ttf`）を `TTFont` で登録してから使う

作ったら必ず下の確認ループに通す。

## 見た目の確認ループ

PDF を作った・加工したときは、画像にして目で見てから渡す。

```
for 周回 in 1..3:
    python scripts/pdf_to_png.py <pdf> --dpi 100
    出力された PNG を全部読み、崩れ（文字化け・はみ出し・重なり・空白ページ・回転違い）を一覧にする
    if 崩れ 0件: break
    崩れの原因になっている元ファイルか手順だけを直して PDF を作り直す
else:
    3周で直らなければ、残っている崩れと試したことを報告する。直ったとは言わない
```

ページが多い場合、`pdf_to_png.py` は先頭30ページで止まる。変更したページを `--pages` で指定して見る。

## 禁止事項

- 入力 PDF を上書きすること。`pdf_ops.py` は出力に入力と同じパスを指定すると止まる
- `fill-form` で存在しないフィールド名を、似た名前のフィールドへ勝手に読み替えること
- スキャン PDF の `text` の結果（空や断片）を、そのまま内容として報告すること
- 数十ページ分のテキストを会話にそのまま流すこと。ファイルに出して必要箇所を読む。資料が3件以上、または合計1万字を超える要約・比較は `notebooklm` に回す

## スクリプト

すべて `--help` で引数が見られる。成功時は書き出したパスを標準出力に1行ずつ出す。

| スクリプト | 用途 | 依存 |
|---|---|---|
| `scripts/pdf_extract.py` | `meta` `text` `tables` `images` | `pypdf`。`tables` は `pdfplumber` |
| `scripts/pdf_ops.py` | `merge` `split` `rotate` `stamp` `encrypt` `decrypt` `list-fields` `fill-form` | `pypdf`。AES の暗号化・復号は `cryptography` |
| `scripts/to_pdf.py` | Word・Excel・PowerPoint を PDF にする | 標準ライブラリのみ。変換には LibreOffice か Windows の MS Office が要る |
| `scripts/pdf_to_png.py` | ページを PNG にする | `pypdfium2` `Pillow` |

導入は `pip install pypdf pdfplumber cryptography pypdfium2 pillow`。足りないパッケージがあるとスクリプトは終了コード2で止まり、入れるべきパッケージ名を出す。入れる前にユーザーに確認する。

終了コードは4本で揃えている。

| コード | 意味 | 次の動き |
|---|---|---|
| 0 | 成功 | 出力パスを使って先へ進む |
| 1 | 操作できなかった（スキャン PDF の疑い、表0件、パスワード違い、存在しないフィールド名、フォーム無し、変換失敗） | 標準エラーの理由に従って分岐する。同じ引数で再実行しない |
| 2 | 引数ミス・入力が無い・依存パッケージ不足 | 引数を直すか、パッケージ導入をユーザーに確認する |
| 3 | `to_pdf.py` のみ。変換エンジンが無い | 見た目の確認ができない旨を報告し、ユーザーに手元で開いて確かめてもらう |

`to_pdf.py` の変換エンジンは `--engine auto`（既定）で、LibreOffice（`soffice`）があればそれを、無ければ Windows の MS Office を PowerShell 経由で使う。出力は入力と同じフォルダの `<名前>.pdf`（`--outdir` で変更）。
