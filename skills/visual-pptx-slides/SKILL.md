---
name: visual-pptx-slides
description: 図解が主役の分かりやすいPowerPoint（.pptx）を、構成設計→python-pptxで生成→画像化して自己検査まで一貫して作る。「分かりやすいスライドを作って」「図解でパワポにして」「月まとめのスライド」「設計レビュー資料をpptxで」「報告資料をスライドに」で使う。既存pptxの編集や社内テンプレート準拠は operate-powerpoint。
---

# visual-pptx-slides

タイトルを読めば結論が分かり、図を見れば根拠が分かるスライドを .pptx で作る。部品集 `scripts/slidekit.py` で描き、`check_deck.py`（機械検査）と `render.py`（PNG 化して目視）で確かめてから渡す。

失敗しやすいのは2か所。**構成を決めずに描き始めて文字だらけになる**ことと、**生成したものを見ずに渡して、はみ出し・重なりが残る**こと。だから構成案はユーザーの承認を取ってから描き、描いたら必ず検証ループを回す。

## ワークフロー

```
1. 確認 ──▶ 2. 構成案 ──▶ [ユーザー承認] ──▶ 3. 生成 ──▶ 4. 検証ループ ──▶ 5. 納品
 (不足だけ質問)  outline.md                    build_deck.py   最大3周
```

直列の手順で、手順4だけがループ。停止してユーザーに聞くのは手順1（不足があるとき）と手順2の承認の2か所。

```
# 手順4（検査 → 判定 → 修正。最後に納品するのは必ず検査済みの deck.pptx）
for 周回 in 1..3:
    python <SKILL_DIR>/scripts/check_deck.py out/deck.pptx --theme <theme> --json check.json
        終了コード 2 → 検査不能。build_deck.py を直さず、原因（依存・theme 名）を解消して同じ周をやり直す
    python <SKILL_DIR>/scripts/render.py out/deck.pptx --out render --sheet
        終了コード 0 → 目視レビュー（下の「目視レビュー」）で不合格を列挙する
        終了コード 1・2 → 目視は「見た目未確認」とする（render/ には古い画像も残らない）
    log.md に「周回・deck.pptx の sha256・ERROR/WARN 件数・目視の結果・直した箇所」を追記する
    if ERROR 0 件 かつ 目視の不合格 0 件: break（成功。見た目未確認なら「機械検査のみ合格」）
    if 周回 == 3: break（直さずに止める。残りは未解決として報告する）
    if 前の周と同じ指摘が残った:
        同じ直し方をやめる。言葉を短くする → 領域を分け直す → パターンを替える、の順に方針を変える。
        変えられなければ、その指摘を残したまま手順5へ進み、未解決として報告する
    指摘のあったスライドのブロックだけを build_deck.py で直し、python build_deck.py で再生成する
```

最終周（3周目）では修正しない。直したら必ず次の周で検査するので、納品する deck.pptx と、check.json・render/render.json に記録された sha256 は一致する。

## 作業ディレクトリ

```
slides-work/<deck名>/
├── outline.md        # 手順2の構成案（承認されたら先頭に「承認済み」と書く）
├── build_deck.py     # 手順3。outline の「### n.」とブロックが 1 対 1
├── out/deck.pptx     # 成果物
├── render/           # slide-NN.png と sheet.png
├── check.json        # check_deck.py の結果
└── log.md            # 検証ループの周回記録
```

中断から再開するときは、ファイルの更新日時で古い成果物を使い回さないことを確かめてから入る。

| 状態 | 再開する手順 |
|---|---|
| outline.md が無い、または「承認済み」と無い | 手順1（outline.md があれば手順2の提示から） |
| build_deck.py が無い、または outline.md より古い | 手順3 |
| out/deck.pptx が無い、または build_deck.py より古い | 手順3の4（再生成） |
| 上のどれでもない | 手順4。log.md の最後の周回番号の次から数え、3周の上限を引き継ぐ |

## 準備

- `<SKILL_DIR>` はこの SKILL.md のあるディレクトリの絶対パス。以下のコマンドはこれで読み替える。
- `python -c "import pptx"` が失敗したら `pip install python-pptx` を実行する。ネットワーク制限で入らなければ、止まってユーザーに伝える。スクリプトも python-pptx が無ければ終了コード 2 で止まる。
- PNG 化には Windows の PowerPoint か LibreOffice（`soffice`）が要る。どちらも無いときは目視を省き、「見た目未確認・機械検査のみ合格」として納品時に明記する。
- 社内テンプレート（.potx・既存の様式）に合わせる必要がある依頼は、このスキルでは作らない。slidekit はテンプレートを読まず独自の theme で描くため。operate-powerpoint に任せる。

## 手順

### 1. 確認する

会話と添付から次を拾い、足りないものだけを1回でまとめて質問する。

| 項目 | 例 | 無いときの既定 |
|---|---|---|
| 目的（聞き手に何をしてほしいか） | 来期の方針を承認してほしい | 質問する |
| 聞き手と前提知識 | 部内の設計者・AI は初心者 | 質問する |
| 形式 | 発表 20 分 / 配布のみ | 配布のみ・10 枚前後 |
| 資料タイプ | 動向まとめ / 技術説明 / 設計レビュー / 報告・提案 | 素材から判断して構成案に書く |
| 素材 | 議事録、数値、URL、画面の画像 | 質問する |
| theme | default（明るい）/ corporate（落ち着いた） | 社外・上位者向けなら corporate、それ以外 default |

数字・日付・固有名詞は素材にあるものだけを使う。素材が無い部分を推測で埋めない。調べてよいと言われ、検索手段があるときだけ調べ、出所を控える。

### 2. 構成案を作り、承認を取る

1. `references/design-principles.md` を読む（特に「2. タイトルは結論文」「8. デッキ全体の流れ」「9. 資料タイプ別の骨組み」）。
2. 資料タイプの骨組みを当て、各スライドのパターンを `references/layout-patterns.md` の早見表から選ぶ。
3. `assets/templates/outline.md` をコピーして埋め、`slides-work/<deck名>/outline.md` に保存する。
4. ユーザーに「タイトル読み」と「番号・パターン・タイトル」の一覧を見せ、承認か修正を求めて止まる。
5. 承認されたら outline.md の先頭に「承認済み」と書く。修正指示があれば反映して再提示する。

ユーザーがその場にいない（定期実行など）ときは、置いた前提を outline.md の先頭に書いて手順3へ進む。

### 3. 生成する

1. `references/slidekit-api.md` を読む。呼び出し方に迷ったら `assets/examples/demo_all_patterns.py` の同じパターンを見る。
2. `assets/templates/build_deck.py` を作業ディレクトリにコピーし、`SKILL_DIR` を埋める（または環境変数 `SLIDE_SKILL_DIR` を設定する）。
3. outline.md のスライドごとにブロックを書く。色は theme の色名、強調は `[[語]]`、補足の話はノート（`notes=`）へ。
4. `python build_deck.py` で `out/deck.pptx` を作る。例外が出たらそのスライドのブロックを直して再実行する。

### 4. 検証ループを回す

上の擬似コードのとおり。補足:

- `check_deck.py` の ERROR は必ず直す。WARN は直すか、直さない理由を log.md に1行書く。
- 直すのは指摘のあったスライドだけ。デッキ全体を作り直さない。

**目視レビュー**は、`references/visual-checklist.md` の A・V 項目（見た目）と C 項目（中身）を分けて当てる。

- 見た目（A・V）: `render/sheet.png` で全体を見たあと、**全スライドの PNG を1枚ずつ開く**。気になったものだけ開く見方はしない。
- 中身（C）: outline.md と素材を手元に置き、各スライドの数字・日付・出典を突き合わせる。画像だけでは判定できない。
- 別の作業者（レビュー担当のエージェントや人）に見た目を依頼できる環境では、次の形で依頼する。依頼できない環境では、自分が他人のデッキをレビューする立場に切り替えて同じことを行う。
  - 渡すもの: `render/` の PNG 全部、`references/visual-checklist.md`、出力先 `review.md` のパス
  - やってほしいこと: A・V 項目の不合格を `s5-V3: 右パネルの文字が箱の下端に接している` の形で列挙する
  - やらないこと: スライドやコードを直さない。構成の意図を推測して合格にしない
  - 迷ったら: 合否を決めずに「判断保留」として列挙する（判断保留は不合格と同じに扱う）
- 画像を見られない環境では、目視をユーザーに依頼する項目として納品時に挙げる。

### 5. 納品する

- 渡す前に、`out/deck.pptx` の sha256 が check.json の `sha256`（と、目視したなら render/render.json の `sha256`）と一致することを確かめる。一致しなければ手順4に戻る。
- `out/deck.pptx` を渡す。全体を一目で見せたいときは `render/sheet.png` も添える。
- 報告は短く: 枚数と構成の一言、検査の結果（成功 / 機械検査のみ合格 / 未解決あり）、未確認事項（outline.md の「未確認事項」）、検証ループで残った未解決の指摘。
- 描画の注意を render/render.json の `method` に合わせて1行添える。
  - `powerpoint`: PowerPoint で描いた画像。theme のフォント（既定 BIZ UDPGothic）が無い PC では別フォントで表示される。
  - `libreoffice`: LibreOffice で描いた画像で、PowerPoint とは文字幅や折り返しが変わりうる。`font_substitution` が `linux-fontconfig-alias` なら代替フォントで描いている。
  - 目視できなかった: 見た目は未確認。PowerPoint で開いて確かめてほしいと書く。

## 終了条件と失敗時の扱い

- 成功: `check_deck.py` の ERROR 0 件、かつ目視チェックの不合格 0 件、かつ納品物の sha256 が検査結果と一致。
- 機械検査のみ合格: ERROR 0 件だが PNG 化できず目視していない。成功とは書かず、この名前で報告する。
- 検査不能: `check_deck.py` が終了コード 2。成功にも未解決にも数えない。原因を解消できなければ止まってユーザーに伝える。
- 上限: 検証ループ 3 周。3周目は直さずに止め、残った指摘を未解決として報告する。
- 収束しない: 同じ指摘が 2 周続いたら方針を変える（手順4の擬似コード）。
- 止まってユーザーに確認する: 素材が無く中身を書けないとき、承認前の構成案、python-pptx を入れられないとき、ユーザーが求めた図がどのパターンにも当てはまらず部品で組むと 1 枚に収まらないとき。

## 参照ファイル

| ファイル | 読むタイミング |
|---|---|
| `references/design-principles.md` | 手順2の最初に毎回。目視で迷ったときも |
| `references/layout-patterns.md` | 手順2でパターンを選ぶとき。情報量の上限を確かめるとき |
| `references/slidekit-api.md` | 手順3で build_deck.py を書くとき。エラーやはみ出しの直し方を探すとき |
| `references/visual-checklist.md` | 手順4の毎周 |
| `assets/templates/outline.md` | 手順2でコピーして使う |
| `assets/templates/build_deck.py` | 手順3でコピーして使う |
| `assets/examples/demo_all_patterns.py` | 手順3で呼び出し例を見たいとき（全パターンの見本。数値は架空） |
| `assets/themes/default.json` | 既定の配色（クリーム地・藍/碧/山吹/朱）を確かめる・変えるとき |
| `assets/themes/corporate.json` | 落ち着いた配色を使うとき。新しい theme はどちらかをコピーし、色名のキーをそろえる（フォントもここで変える） |

## スクリプト

依存パッケージ: `python-pptx`（slidekit.py・check_deck.py・build_deck.py に必須）、`Pillow`（render.py の `--sheet` に必須）、`PyMuPDF`（LibreOffice 経路で pdftoppm が無いときだけ）。無ければ導入方法を表示して終了コード 2 で止まる。

```
python <SKILL_DIR>/scripts/check_deck.py out/deck.pptx [--theme default] [--json check.json]
```
はみ出し・表のセルのあふれ・スライド外・小さすぎる文字・タイトル2行・泣き別れ・重なり・朱の多用・文字過多・theme 外の色を判定する。check.json には検査した pptx の sha256 が入る。

| 終了コード | 意味 | 次の動き |
|---|---|---|
| 0 | ERROR なし | 目視へ |
| 1 | ERROR あり | 指摘のスライドを直す |
| 2 | 検査不能（python-pptx が無い・pptx が読めない・theme が無いか壊れている） | build_deck.py は直さない。原因を解消して再実行 |

```
python <SKILL_DIR>/scripts/render.py out/deck.pptx --out render [--dpi 80] [--sheet]
```
スライドごとの PNG（`render/slide-NN.png`）と一覧（`render/sheet.png`）、使った方式と sha256 を記録した `render/render.json` を作る。Windows は PowerPoint → LibreOffice の順に、それ以外は LibreOffice を試し、失敗したら次の方式へ進む。開始時に古い画像を消す。

| 終了コード | 意味 | 次の動き |
|---|---|---|
| 0 | 成功。標準出力の1行目が `method: powerpoint` か `method: libreoffice` | 目視レビュー |
| 1 | 変換手段はあったが、すべて失敗（stderr に方式ごとの理由） | 見た目未確認として進める |
| 2 | 変換手段が無い、または Pillow など必要なパッケージが無い | 見た目未確認として進める（パッケージ不足なら導入して再実行） |

```
python <SKILL_DIR>/assets/examples/demo_all_patterns.py out/demo.pptx [theme]
```
全パターンの見本デッキを作る。slidekit を改修したときの回帰確認にも使う（生成 → check_deck → render）。
