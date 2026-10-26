---
name: youtube-member-summary
description: YouTube動画（メンバー限定を含む）を要約してNotionの「DB_YouTube要約」に保存する。公開動画はNotebookLMにURL登録、メンバー限定はブラウザで字幕を抜いて登録する。「この動画を要約して」「メンバー限定動画をまとめて」で使う。Notion に残さないなら notebooklm。
---

# youtube-member-summary

YouTube動画のURLを受け取り、要約→Notion保存までを一気に行う。
勘所は3つ: (1) 公開動画は Chrome を使わず NotebookLM に URL を直接渡す、(2) メンバー限定動画だけログイン済み Chrome の実セッションから字幕を抜く、(3) 各工程の出力はファイルとIDで次工程へ渡し、長文を会話に載せない。

## 依存スキルの解決

利用可能なスキル一覧から notion-api の実体ディレクトリを解決し、以下の `<notion-api-dir>` をその絶対パスへ置き換える。作業ディレクトリや隣接配置を仮定しない。不在なら保存用本文とプロパティを残し、Notion保存は未完として必要なスキルを案内する。createの終了コード3では再作成せず、notion-apiの復旧手順に従う。

## ワークフロー

```
① 判別: 公開 / メンバー限定
   ├─ 公開      → nlm source add --url        (Chrome不要)
   └─ メンバー限定 → Claude in Chrome で字幕抽出 → nlm source add --file
② 要約: nlm notebook query --source-ids → 要約テキスト
③ 保存: DB_YouTube要約 にページ作成 (notion-api スキルのスクリプトで)
④ 報告: NotionページのURLをユーザーに伝える
```

各工程は前の出力が揃わなければ進まない。失敗したら「終了条件と失敗時の扱い」に従って止まる。

## 手順

### 0. 公開かメンバー限定かを判別する

判別の目印:
- チャンネルの動画一覧で、サムネイル脇に「メンバー限定」バッジが付いているか。
- 動画ページで、タイトル下に「メンバー限定」のラベルが出るか。
- 再生数が表示されないものはメンバー限定であることが多い(限定動画は再生数が非公開)。

分からなければ、まず**公開ルート(手順1)を試す**。NotebookLM が取り込めなければメンバー限定として手順2へ回す。判別のためだけに Chrome を開かない。

### 1. 公開動画: NotebookLM に URL を直接登録する

Chrome も文字起こし抽出も不要。

```
nlm source add <notebook-id> --url "https://www.youtube.com/watch?v=<videoId>" --wait
```

以下の例は nlm 0.10.0 のローカル help で確認した構文。実行前に `nlm --version`、`nlm source add --help` を照合し、違いがあれば導入版の help に従う。`--wait` で取り込み完了を待ち、返されたソースIDと `nlm source list <notebook-id>` の状態を確認する。対応版では `--youtube` も使える。

- タイトル・チャンネル名・公開日が Notion 保存に必要なので、取り込み後に `nlm source list <notebook-id>` で登録名を確認するか、要約の中から拾う。足りなければ動画ページを1回だけ開いて `ytInitialPlayerResponse` から取る。
- 取り込みに失敗する(処理が ready にならない/エラーになる)場合は、メンバー限定か地域制限を疑い、手順2へ回す。

登録できたらソースIDを控えて手順3へ。

### 2. メンバー限定動画: Claude in Chrome で字幕を抽出する

`references/member-transcript.md` を読み、その手順で字幕を抜く。要点は次の3つで、詳細と実測の根拠は参照先にある。

- **動画は再生しない。** この環境ではメディアが読み込めないことがある。字幕リクエストはプレイヤーAPIの `setOption('captions','reload',true)` で発生させる
- 字幕本文やURLをツール結果として返さない（拡張のプライバシーフィルタで BLOCKED になる）。返すのはステータスと文字数だけにし、全文は DOM 置換 + `get_page_text` で受け取る
- fetch には必ず `AbortController` で20〜25秒のタイムアウトを付ける

完了条件: `transcript_<videoId>.txt` が scratchpad にあり、末尾のタイムスタンプが動画の長さとおおむね一致すること。`nlm source add <notebook-id> --file transcript_<videoId>.txt --wait` で登録し、手順3へ進む。

### 3. NotebookLM の準備とソース登録

notebooklm スキルの手順に従う。要点:

1. `nlm login --check` で認証を確認し、`nlm notebook list` で一覧を取得する。失敗理由を出力から判断し、認証切れなら下の手順へ進む。終了コードの数値だけで認証エラーと断定しない。
2. ノートブックはチャンネル単位で1冊、名前は `YouTube_<チャンネル名>`。`nlm notebook list` で探し、無ければ `nlm notebook create`。ID を控えて使う。alias は導入版の help を確認した場合だけ利用する。
   - 既存(ユーちぇる監督): 無印 `6032a681-f9eb-4916-a4f4-ea3419aae914` ほか `_02`〜`_06` があり、**`_02` は同名が2冊ある**。投入先は `notebook list` の最終更新が最も新しいものを選び、ユーザーに名前と ID を告げてから入れる。
3. add の出力または `nlm source list <notebook-id>` で新ソースのIDを控える。ソース数が45件を超えていたら上限接近をユーザーに報告する。

#### 認証が切れたとき

利用可能な notebooklm スキルの実体パスを解決し、認証手順に従う。`nlm login --help` を確認して利用者のログインを案内する。パスワードやCookieを出力しない。失敗した同じ操作は1回まで再試行し、改善しなければエラーを提示して止める。Chromeを無断終了しない。

### 4. 要約生成

新ソースだけに絞って要約させる:

質問文はUTF-8のファイルへ保存する。PowerShellでは内容を変数へ読み、1つの引数として渡す。構文は `nlm notebook query --help` と照合する。

```powershell
$query = Get-Content -LiteralPath prompt.txt -Raw -Encoding utf8
nlm notebook query <notebook-id> $query --source-ids <新ソースID> --json | Out-File -Encoding utf8 q_<videoId>.json
```

```bash
nlm notebook query <notebook-id> "$(cat prompt.txt)" --source-ids <新ソースID> --json > q_<videoId>.json
```

prompt.txt の中身:

```
このソースの内容を次の構成で日本語で要約して。1) 結論(3行以内) 2) トピック別の要点(動画の流れの順に、見出しと説明で。タイムスタンプや時間表記は一切書かないこと) 3) 専門用語・前提知識の補足(中学生でも分かる言葉で。ただし「中学生向け説明」のようなラベルは書かず、説明文だけを書くこと)
```

元の回答JSONは保存しておく。保存用本文から出典マーカーを除く場合も、根拠を確認できる元回答は残す。回答のJSON構造は導入版の実出力で確認し、本文フィールドを取り出す。

プロンプトの2つの但し書きには理由がある。

- **タイムスタンプを書かせない**。URL登録した動画は NotebookLM 側に時間情報が渡らないことがあり、その場合 `0:00〜2:15` のような表記が**実際の再生位置ではなく推測値**になる(「推定タイムスタンプ」と断ってくることもあれば、黙って書いてくることもある)。頭出しに使えない数字を残すより書かせない。字幕ファイルを渡したメンバー限定動画だけは実時刻が入るが、資料全体で揃えるため同じ扱いにする。
- **「中学生向け説明」のラベルを書かせない**。毎項目に同じ見出しが並ぶだけで情報量がない。説明文だけでよい。

- 回答の JSON（`--json` の出力）は `q_<videoId>.json` にそのまま保存する。整形は手順5のスクリプトが行うので、ここで出典マーカーや前置きを手で消さない。元の回答は根拠の確認用に残す
- 返答が動画と無関係(別ソースの内容)なら `--source-ids` の指定を確認して1回だけやり直す。

### 5. Notion保存

書き込みは本数によらず **notion-api スキルのスクリプト**(`<notion-api-dir>/scripts/`)で行う。トークンは環境変数 `NOTION_TOKEN`。未設定ならスクリプトが終了コード2で止まり設定手順を出すので、そのままユーザーに案内して中断する。プロパティ値・フィルタの JSON の形は notion-api スキルの api-guide.md(`<notion-api-dir>/references/` 配下)を参照。

DB「DB_YouTube要約」は作成済み。データソースID: `52e0eace-9cf1-436d-9f0d-5456b98e8703`(見つからなければ `notion_query.py schema` で疎通を確認し、DB ごと消えていたら再作成をユーザーに相談する。列構成: タイトル TITLE / URL URL / チャンネル SELECT / カテゴリ SELECT / 公開日 DATE / 追加日 DATE)。

1ページの作り方:

1. 本文 Markdown を作る。`scripts/normalize_summary.py` が出典マーカー・前置き・末尾の追い質問・BOM・「〜向け説明」のラベルを落とし、見出しの記法の揺れを吸収して、冒頭の元動画URLの引用行と末尾の「NotebookLM: <ノートブック名>」まで付ける。**「専門用語・前提知識の補足」も省略せず入る。**

   ```bash
   python scripts/normalize_summary.py normalize --answer q_<videoId>.json --url "<動画URL>" \
     --notebook "<ノートブック名>" --out summaries/<videoId>.md
   ```

   終了コード1（NG）なら投稿しない。表示された理由を見て `references/notion-format.md` を読み、記法の表とスクリプトを直してから回し直す。回答の本文が `answer` 以外のキーにあれば `--field` で渡す
2. プロパティ JSON を組む: `タイトル`(title) / `URL`(url) / `チャンネル`(select) / `カテゴリ`(select) / `公開日`(date) / `追加日`(date)。
3. アイコンの絵文字を1つ決める(下の「アイコンの付け方」)。`--icon` は必須。
4. 変換して投稿する。

   ```bash
   python "<notion-api-dir>/scripts/md2blocks.py" --file summaries/<videoId>.md --out blocks_<videoId>.json
   python scripts/normalize_summary.py check --blocks blocks_<videoId>.json
   python "<notion-api-dir>/scripts/notion_page.py" create \
     --data-source-id 52e0eace-9cf1-436d-9f0d-5456b98e8703 \
     --properties props_<videoId>.json --blocks blocks_<videoId>.json \
     --icon "<決めた絵文字>" --progress progress_<videoId>.json
   ```

   `check` が終了コード1なら投稿しない（heading_2 が3つ、結論の直後が太字の箇条書き、本文に `####` `***` `**` が無いことを見ている。2026-09-21 に `***` 混入と結論の段落化を投稿後に見つけ、3ページを差し替えた）。2000字分割・100ブロック超の追送は notion_page.py が吸収する。一括処理ではこの3コマンドをドライバスクリプトから回す。

5. 投稿後、`notion_query.py query --compact` の `icon` フィールドで、作ったページにアイコンが入っていることを確認する。抜けていたら `notion_page.py set-icon --page-id <id> --icon <絵文字>` で入れる。

**既に崩れた書式で投稿してしまったときは、ページを作り直さない。** URL が変わるとユーザーへ渡したリンクが死ぬ。手順は `references/notion-format.md` の末尾にある。

#### アイコンの付け方

**アイコンなしのページを作らない。** 一覧で中身を見分ける手がかりがアイコンとタイトルしかなく、後から一括で付け直すのは手間がかかる。

選び方は**動画1本ごとの中身に寄せる**。カテゴリで機械的に決めない。同じ絵文字が並ぶと見分けがつかず、アイコンなしと変わらない。

- 主題そのものを表す絵文字を優先する。例: 円高・円安 💴 / 下落相場 📉 / 上昇相場 📈 / 為替介入・中央銀行 🏛️ / 米株安 🐻 / 大口・機関投資家 🐋 / 損切り・資金管理 ⚖️ / メンタル 🧠 / 体験談・ゲスト回 🎙️ / ライン・チャートパターン 📐
- 主題が絞れないときだけカテゴリの既定値に落とす: 相場解説 📊 / ファンダメンタルズ 🏛️ / テクニカル 📈 / 大口・市場構造 🐋 / エントリー・手法 🎯 / 資金管理 ⚖️ / メンタル・習慣 🧠 / 体験談・コラボ 🎙️
- 一括処理でも同じ。判定表にアイコン列を持たせ、`cat.tsv` と並べて `icon.tsv` に持ち、ドライバから `--icon` に渡す。

二重投入の防止と復旧:

- 投入済みを `posted.tsv` に記録する。**この記録は DB の実態(`notion_query.py query --compact` の結果)から作り直せるようにしておく**。手作業と自動投入が混ざると記録漏れで重複が出る。
- 重複が出たら URL プロパティでグルーピングし、古い1件を残して残りを `notion_page.py archive` でアーカイブする(ゴミ箱行きで復元可能)。完全削除はしない。

#### カテゴリの付け方

チャンネルの再生リストと同じ粒度で分類する。値は以下の8つ。

| カテゴリ | 中身 |
|---|---|
| 相場解説 | 日付ものの相場解説回 |
| ファンダメンタルズ | 金利・国債・中央銀行・経済指標・為替介入などの仕組み解説 |
| テクニカル | ライン・ローソク足・チャートパターン・インジケーター |
| 大口・市場構造 | 大口/機関投資家/ヘッジファンド/実需/オプション/フロー |
| エントリー・手法 | エントリー基準・トレードスタイル・勝ち方の型 |
| 資金管理 | ロット・損切り・リスクリワード |
| メンタル・習慣 | メンタル・習慣・向き不向き |
| 体験談・コラボ | 実体験/収支公開/ゲスト回 |

- **分類はタイトルのキーワードで機械的に付ける**(判定表を作って一括処理する)。取りこぼしは出る前提で、受け皿は「エントリー・手法」にする。
- 精度を上げたいと言われたら、要約本文を読んで付け直す。時間はかかる。
- 対象チャンネルの再生リストは `https://www.youtube.com/@<handle>/playlists` で確認できる(`lockupViewModel.contentType` に `PLAYLIST` が入っているものを拾う)。ただし再生リストは全動画を網羅せず重複もするので、**そのまま使わず分類軸の参考にとどめる**。

### 6. 報告

NotionページのURL、使用したノートブック名を伝える。scratchpadの transcript ファイルは消さない(再利用の可能性があるため)。

## チャンネル単位でまとめて処理する場合

「このチャンネルの今月の動画を全部」のような依頼のときは `references/bulk-processing.md` を読む。対象の一覧の取り方（DOM・innertube）、実日付の引き方、状態ファイル（`worklist.tsv` `state.tsv` ほか）、二重登録の防ぎ方がある。
対象リストをユーザーに見せてから実行に入る。1本あたり約85秒かかるので、1セッションで終わらない規模ならその旨と再開方法を先に伝える。

## スクリプト

`scripts/normalize_summary.py` — 依存は標準ライブラリのみ。

| サブコマンド | 使う場面 | 終了コード |
|---|---|---|
| `normalize --answer <回答> --url <URL> --notebook <名前> --out <md> [--field answer]` | 手順5の1。回答（JSON か本文テキスト）を Notion 用の Markdown にする | 0 合格 / 1 見出しが3つ拾えない・`####` `***` が残る（投稿しない）/ 2 引数・入力の不備 |
| `check --blocks <blocks.json>` | 手順5の4。md2blocks の出力を投稿前に検査する | 0 合格 / 1 構造が崩れている（投稿しない）/ 2 読めない |

## 終了条件と失敗時の扱い

- 成功: Notionページが作成され、URLをユーザーに報告した。
- 字幕トラックが無い(captionTracksが空): 抽出不可と報告して終了。別手段(音声ダウンロード等)へ勝手に進まない。
- Chrome拡張がyoutube.comの権限を持たない/タブ操作が2〜3回失敗: 状況を説明してユーザーに確認する。
- 字幕リクエストが3周叩いても発生しない、または有効なレスポンスが取れない: ブラウザの再起動を提案する(再起動で通るようになった実績がある)。勝手に再生を試み続けない。
- nlm が認証エラー: 手順3の「認証が切れたとき」へ進む。旧版の認証コマンドを推測で呼ばない。
- nlm が認証以外のエラーで失敗: エラーをそのまま提示して指示を待つ。要約だけClaudeが直接行う代替は、ユーザーが同意した場合のみ。
- Notion書き込み失敗: 要約テキストを会話に提示し、保存だけ後でやり直せる状態にして終了する。
- 想定外の入力(URLがYouTube動画でない、プレイリストURL等): 進めずに確認する。
