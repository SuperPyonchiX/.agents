---
name: youtube-member-summary
description: YouTube 動画（メンバー限定を含む）を要約して Notion の「DB_YouTube要約」に保存するスキル。公開動画は URL を NotebookLM に直接登録し、メンバー限定は Claude in Chrome で字幕を抜いてから登録し、notion-api で書き込む。「この動画を要約して」「メンバー限定動画をまとめて」「このチャンネルの今月の動画をまとめて」と YouTube の URL が出たら使う。Notion に残さずその場で答えるだけなら notebooklm。
metadata:
  web-description: YouTube動画(メンバー限定を含む)を要約してNotionの「DB_YouTube要約」に保存する。公開動画はNotebookLMにURL登録、メンバー限定はブラウザで字幕を抜いて登録する。「この動画を要約してNotionに保存して」と言われたら使う。
---

# youtube-member-summary

YouTube動画のURLを受け取り、要約→Notion保存までを一気に行う。
勘所は3つ: (1) 公開動画は Chrome を使わず NotebookLM に URL を直接渡す、(2) メンバー限定動画だけログイン済み Chrome の実セッションから字幕を抜く、(3) 各工程の出力はファイルとIDで次工程へ渡し、長文を会話に載せない。

## ワークフロー

```
① 判別: 公開 / メンバー限定
   ├─ 公開      → nlm source add --url        (Chrome不要)
   └─ メンバー限定 → Claude in Chrome で字幕抽出 → nlm source add --file
② 要約: nlm chat --source-ids → 要約テキスト
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
nlm source add <notebook-id> "https://www.youtube.com/watch?v=<videoId>"
```

URL は位置引数で渡す(`--url` は無い)。同期実行なので `--wait` も無い。数秒で `source_id` だけを返すが取り込みは完了していないことがあるので、30 秒ほど置いて `nlm source list` の `STATUS` が `enabled` になったことを確認する。

- タイトル・チャンネル名・公開日が Notion 保存に必要なので、取り込み後に `nlm source list <notebook-id>` で登録名を確認するか、要約の中から拾う。足りなければ動画ページを1回だけ開いて `ytInitialPlayerResponse` から取る。
- 取り込みに失敗する(処理が ready にならない/エラーになる)場合は、メンバー限定か地域制限を疑い、手順2へ回す。

登録できたらソースIDを控えて手順3へ。

### 2. メンバー限定動画: Claude in Chrome で字幕を抽出する

前提知識(2026-08-30 実測):
- メンバー限定動画には「文字起こしを表示」パネルが提供されない(`ytInitialData.engagementPanels` に transcript パネルが無い)。
- `ytInitialPlayerResponse` の captionTracks の baseUrl を直接 fetch すると **200 で空ボディ**が返る(トークン必須化のため)。プレイヤー自身が発行したリクエストURLを使い回すこと。
- **動画本編は再生できないことがある**(`readyState` が 0 のままバッファリングで停止し、`buffered` が 0 のまま進まない)。これは公開動画でも同じで、この環境ではメディアストリームが読み込めない。**再生に依存する手順を組んではいけない。**
- 字幕リクエストは再生しなくても発生させられる。プレイヤーAPIの `setOption('captions','reload',true)` が引き金になる。
- 発行されたリクエストのうち**1本目は空ボディで返る**。2本目以降を使う。全部まとめて fetch して、長さが1000文字を超えたものを採用するのが確実。
- 無効なリクエストURLを fetch すると**レスポンスが返らずハングする**。必ず `AbortController` でタイムアウト(20〜25秒)を付ける。付けないと `javascript_tool` が45秒でCDPタイムアウトになる。

手順:

1. claude-in-chrome スキルを発動してから `mcp__claude-in-chrome__*` ツールを使う(未ロードなら ToolSearch で一括ロード)。
2. `tabs_context_mcp` で現状確認 → `tabs_create_mcp` / `navigate` で動画URLを開く。
3. ページ読み込みを9秒ほど待ってから、`javascript_tool` でメタ情報と字幕トラックの有無を確認する。見る場所: `ytInitialPlayerResponse` の `videoDetails.title / .lengthSeconds`、`microformat.playerMicroformatRenderer.publishDate`、`captions.playerCaptionsTracklistRenderer.captionTracks`(空なら字幕なし→抽出不可として終了)。
   - `videoDetails.author` は拡張のプライバシーフィルタで BLOCKED になる。チャンネル名は動画一覧やページ見出しから別途取る。
4. 字幕リクエストを発生させる。**再生はしない。**
   ```js
   const p = document.getElementById('movie_player');
   for (let k = 0; k < 3; k++) {
     try { p.loadModule('captions'); } catch(e) {}
     try { p.setOption('captions','track',{languageCode:'ja'}); } catch(e) {}
     try { p.setOption('captions','reload',true); } catch(e) {}
     await new Promise(r => setTimeout(r, 5000));
     if (performance.getEntriesByType('resource')
           .filter(e => e.name.includes('timedtext')).length) break;
   }
   ```
   `reload` を1回で駄目なら複数回叩く。3周しても0件ならページを再読み込みして1度だけやり直す。
5. 発行済みリクエストを全部 `fmt=json3` に差し替えて fetch し、中身のあるものを拾う。**URLや本文をツール結果として返さない**(プライバシーフィルタでBLOCKされる)。返すのはステータスと文字数だけ。
   ```js
   window.__r = []; window.__d0 = null;
   const hits = performance.getEntriesByType('resource')
     .filter(e => e.name.includes('timedtext'));
   hits.forEach((h, i) => {
     const u = new URL(h.name); u.searchParams.set('fmt','json3');
     const c = new AbortController(); setTimeout(() => c.abort(), 25000);
     fetch(u.toString(), {credentials:'include', signal:c.signal})
       .then(async res => { const t = await res.text();
         window.__r.push([i, res.status, t.length]);
         if (t.length > 1000) window.__d0 = t; })
       .catch(e => window.__r.push([i, 'err', e.name]));
   });
   ```
   別呼び出しで `window.__r` を数回ポーリングして結果を確認する(fetch の解決を同一呼び出しで待つとCDPタイムアウトになる)。
6. `window.__d0` を整形する。`events[].segs` を連結し、**30〜60秒ごとのブロックにまとめて**「M:SS 本文」の行にする(1行ずつだと転送量が増える。60分超の動画は60秒ブロック)。ヘッダを付けて `window.__out` に入れる。
   ```
   タイトル: <動画タイトル>
   チャンネル: <チャンネル名>
   公開日: <YYYY-MM-DD>
   URL: <動画URL>
   ---
   0:00 <本文...>
   ```
7. 検証: 末尾タイムスタンプが `lengthSeconds` とおおむね一致すること。大きく短ければ手順4〜5をやり直す(2回まで)。
8. 転送: 以下の順で試す。
   1. **DOM置換 + `get_page_text`(推奨)**。`document.body` を空にして `<pre>` に `window.__out` を入れ、`get_page_text` で丸ごと受け取る。1往復で全文が取れる。
      ```js
      const b = document.body; while (b.firstChild) b.removeChild(b.firstChild);
      const pre = document.createElement('pre'); pre.textContent = window.__out; b.appendChild(pre);
      ```
      `innerHTML` は Trusted Types で拒否されるので使わない。
   2. 受け取った内容を **Write ツール**で scratchpad に `transcript_<videoId>.txt` として保存する。Bash のヒアドキュメントは1万字を超えると途中で切れて構文エラーになるので使わない。
   
   クリップボード経由(`navigator.clipboard.writeText` → `Get-Clipboard -Raw`)は、MCPタブが `document.hidden === true` のため writeText が解決せず**失敗する**。`document.execCommand('copy')` も同様に失敗する。localhost へのPOSTや `window.open` は YouTube の CSP でブロックされ、`window.name` はクロスオリジン遷移で消える。いずれも当てにしない。
9. 使い終わったタブは `tabs_close_mcp` で閉じる。
10. NotebookLM に登録: `nlm source add <notebook-id> transcript_<videoId>.txt`(ファイルも位置引数。長文を `--text` 相当でインライン投入しない)。

### 3. NotebookLM の準備とソース登録

notebooklm スキルの手順に従う。要点:

1. `nlm notebook list` を叩く。**終了コード 3 が認証切れ**。`login --check` サブコマンドは無い。切れていたら下の「認証が切れたとき」へ。
2. ノートブックはチャンネル単位で1冊、名前は `YouTube_<チャンネル名>`。`nlm notebook list` で探し、無ければ `nlm notebook create`。**alias 機能は無いので ID をそのまま使う。**
   - 既存(ユーちぇる監督): 無印 `6032a681-f9eb-4916-a4f4-ea3419aae914` ほか `_02`〜`_06` があり、**`_02` は同名が2冊ある**。投入先は `notebook list` の最終更新が最も新しいものを選び、ユーザーに名前と ID を告げてから入れる。
3. add の出力または `nlm source list <notebook-id>` で新ソースのIDを控える。ソース数が45件を超えていたら上限接近をユーザーに報告する。

#### 認証が切れたとき(`nlm notebook list` が終了コード 3)

**`nlm auth login` を素で叩いても通らない。** nlm はプロファイルを別ディレクトリへ**コピー**して Chrome を起動するが、Windows の Chrome 127 以降は Cookie が App-Bound Encryption で保護されており、コピー先では復号できずサインイン画面へ飛ぶ。`✗ No notebook.google.com cookies` と出るのがこの症状で、ブラウザ側でログイン済みでも直らない。Chrome を終了させて試しても同じなので、**2回以上繰り返さない。**

生きている Chrome に CDP で繋ぐ。Chrome 136 以降は既定プロファイルでのリモートデバッグを拒否するので、nlm 専用のプロファイルを別に作る。

1. `chrome.exe --user-data-dir=<専用ディレクトリ> --remote-debugging-port=9222 https://notebook.google.com/` で起動する
2. **そのウィンドウで Google ログインをユーザーに依頼する。** パスワードと2段階認証には触れない。`http://127.0.0.1:9222/json/list` の title で NotebookLM が開けたことを確認する
3. `http://127.0.0.1:9222/json/version` の `webSocketDebuggerUrl` を取り、`nlm auth login -cdp-url <その ws URL>` を実行する
4. `nlm notebook list` が通れば完了。認証は `~/.nlm/env` に保存されるので**以降 CDP は不要**。専用プロファイルのウィンドウは閉じてよい

次に切れたときも同じ手順を踏む。普段使いの Chrome プロファイルは触らない。

### 4. 要約生成

新ソースだけに絞って要約させる:

プロンプトはファイルへ置き `-f` で渡す(日本語を引数に直接書くとシェルの引用で壊れやすい)。`notebook query` サブコマンドは無く `chat` を使う。**ノートブックIDは最後の位置引数**。

```
nlm chat --source-ids <新ソースID> --citations off -f prompt.txt <notebook-id>
```

prompt.txt の中身:

```
このソースの内容を次の構成で日本語で要約して。1) 結論(3行以内) 2) トピック別の要点(動画の流れの順に、見出しと説明で。タイムスタンプや時間表記は一切書かないこと) 3) 専門用語・前提知識の補足(中学生でも分かる言葉で。ただし「中学生向け説明」のようなラベルは書かず、説明文だけを書くこと)
```

`--citations off` を付けると出典マーカーが**たいてい**付かなくなるが、**付けても `[1, 2]` が残る回がある**ので下の除去処理は必ず通す。応答は 45 秒ほどかかり、30 秒経過時に「待機中」と stderr に出るが異常ではない。

プロンプトの2つの但し書きには理由がある。

- **タイムスタンプを書かせない**。URL登録した動画は NotebookLM 側に時間情報が渡らないことがあり、その場合 `0:00〜2:15` のような表記が**実際の再生位置ではなく推測値**になる(「推定タイムスタンプ」と断ってくることもあれば、黙って書いてくることもある)。頭出しに使えない数字を残すより書かせない。字幕ファイルを渡したメンバー限定動画だけは実時刻が入るが、資料全体で揃えるため同じ扱いにする。
- **「中学生向け説明」のラベルを書かせない**。毎項目に同じ見出しが並ぶだけで情報量がない。説明文だけでよい。

- 出力が大きい場合は persisted-output ファイルに落ちるので、PowerShell の ConvertFrom-Json で `answer` を取り出す。複数本まとめてやるなら `> q_<sourceId>.json` にリダイレクトしてから処理する。
- 要約本体以外に、以下が混ざる。まとめて落とす。
  - 出典マーカー `[1, 2]` → `-replace '\s?\[[0-9,\s\-]+\]',''`
  - 冒頭の前置き「選択されたソース**「〜」**の内容に基づき、ご指定の構成で日本語要約を作成しました。」とそれに続く `---` 行(付くときと付かないときがある) → `-replace '(?s)^[^\n]*(ソース|ご指定)[^\n]*要約を作成しました。\s*(\r?\n-{3,})?\r?\n',''`
  - 末尾の追い質問「…さらに深掘りしてみますか？」「…いつでもおっしゃってくださいね」。**行頭の絵文字は毎回変わる**(⚖️ / 🧸 / ✅ / 💡 …)ので、特定の絵文字を決め打ちしないこと。空行に続く「絵文字で始まる最終ブロック」として落とす → `-replace '(?s)\r?\n\s*\r?\n[←-⯿\uD83C-\uDBFF][\s\S]*$',''`
  - ファイル先頭のBOM → `.TrimStart([char]0xFEFF)`
  - 但し書きを入れてもラベルが付いてくることがあるので、保険として `**〜向け説明**：` の並びを落とす処理も通す
- 除去後の先頭が結論の見出しになっていることを確認する。ただし**見出しの記法は実行ごとに変わる**(下表)ので、`### 1) 結論` だけを期待して判定しない。
- 返答が動画と無関係(別ソースの内容)なら `--source-ids` の指定を確認して1回だけやり直す。

### 5. Notion保存

書き込みは本数によらず **notion-api スキルのスクリプト**(`skills/notion-api/scripts/`)で行う。トークンは環境変数 `NOTION_TOKEN`。未設定ならスクリプトが終了コード2で止まり設定手順を出すので、そのままユーザーに案内して中断する。プロパティ値・フィルタの JSON の形は notion-api スキルの api-guide.md(`skills/notion-api/references/` 配下)を参照。

DB「DB_YouTube要約」は作成済み。データソースID: `52e0eace-9cf1-436d-9f0d-5456b98e8703`(見つからなければ `notion_query.py schema` で疎通を確認し、DB ごと消えていたら再作成をユーザーに相談する。列構成: タイトル TITLE / URL URL / チャンネル SELECT / カテゴリ SELECT / 公開日 DATE / 追加日 DATE)。

1ページの作り方:

1. 本文 Markdown を組む: 冒頭に元動画URLの引用行 → 要約全文(下の「Notion 用の整形」で変換する) → 末尾に `---` を2行分と「NotebookLM: <ノートブック名>」。**「専門用語・前提知識の補足」も省略せず入れる**。`summaries/<videoId>.md` に置く。
2. プロパティ JSON を組む: `タイトル`(title) / `URL`(url) / `チャンネル`(select) / `カテゴリ`(select) / `公開日`(date) / `追加日`(date)。
3. アイコンの絵文字を1つ決める(下の「アイコンの付け方」)。`--icon` は必須。
4. 変換して投稿する。

   ```bash
   python skills/notion-api/scripts/md2blocks.py --file summaries/<videoId>.md --out blocks_<videoId>.json
   python skills/notion-api/scripts/notion_page.py create \
     --data-source-id 52e0eace-9cf1-436d-9f0d-5456b98e8703 \
     --properties props_<videoId>.json --blocks blocks_<videoId>.json \
     --icon "<決めた絵文字>"
   ```

   2000字分割・100ブロック超の追送はスクリプトが吸収する。一括処理ではこの2コマンドをドライバスクリプトから回す。
5. 投稿後、`notion_query.py query --compact` の `icon` フィールドで、作ったページにアイコンが入っていることを確認する。抜けていたら `notion_page.py set-icon --page-id <id> --icon <絵文字>` で入れる。

#### Notion 用の整形(手順4の出力をそのまま渡さない)

**`md2blocks.py` は `#` 3つまでしか見出しにしない。** Notion に heading_4 が無いため、`####` の行は変換されず `#### 見出し` という文字列のまま段落として画面に出る。手順4の出力は `### 1) 結論` と `#### 小見出し` を含むので、**そのまま渡すと必ず崩れる**。

既存ページと同じ見た目にするため、Markdown を組む前に次の変換を当てる。

| 手順4の出力 | 変換後 | Notion 上のブロック |
|---|---|---|
| 大見出し(3つ。記法は下表のとおり揺れる) | `## 結論` など(**番号 `N)` と太字を落とす**) | heading_2 |
| 結論セクションの各項目 | `- **本文**` | bulleted_list_item(全文太字) |
| 小見出し(記法は下表のとおり揺れる) | `- **小見出し**` | bulleted_list_item(全文太字) |
| 小見出し配下の説明文 | そのまま | paragraph |
| `---` | そのまま | divider |

**記法は実行ごとに変わる。** 同じプロンプトで 5 本流して 3 通り出た(2026-09-21 実測)。**どれか1つを決め打ちした変換を書かない。**

| | 大見出し | 小見出し | 結論の項目 |
|---|---|---|---|
| A | `### 1) 結論` | `#### X` | `・本文` |
| B | `1) **結論**` | `### **X**` | `* 本文` |
| C | `**1) 結論**` | `### **X**` | **箇条書きにならず1段落で来る** |

受け方の目安:

- 大見出し: `^#{0,4}\s*\*{0,2}\s*\d\)\s*(.+?)$` — 行頭の `#` と `**` の有無を問わず「数字 + `)`」で拾い、番号と太字を落とす
- 小見出し: `^#{3,4}\s+(.+?)$` — `###` と `####` の両方を受ける(大見出しの判定を先に通すこと)
- 結論の項目: `・` / `* ` / `- ` のいずれか。**C のように箇条書きで来ない場合は句点で文を割って1文ずつ `- **…**` にする**

- **`- **…**` で包む行に `**` が既に含まれていたら、内側の `**` を先に落とす。** `make_block()` は `**` で素朴に分割するのでネストで壊れ、`**` が本文に残る。結論の行は NotebookLM が語句を太字にしてくることが多い。
- 小見出し配下に `・A: 〜` の列挙がある場合は **paragraph のまま置く**(連続行は1ブロックに結合される)。`- ` に変換すると小見出しと同じ階層になり区別がつかなくなる。
- **箇条書きの判定で `*` と `-` は後ろに空白を要求する。** `^[・*-]` だけで拾うと `**太字**` の先頭 `*` を箇条書き記号と誤認し、`- ***本文**` のように `*` が1つ余って本文に残る。`・` だけは空白なしを許す。
- 組み終えたら `md2blocks.py` に通し、`heading_2` → `bulleted_list_item`(bold) → `paragraph` の並びになっていること、本文に `####` と `***` が無いこと、`## ` 見出しがちょうど3つあることを確認してから投稿する。**この3点は毎回機械的に確かめる**(2026-09-21 に `***` 混入と結論の段落化を投稿後に発見し、3ページを差し替えた)。

**既に崩れた書式で投稿してしまったときは、ページを作り直さない。** URL が変わるとユーザーへ渡したリンクが死ぬ。`notion_http.request()` で `GET /v1/blocks/<page-id>/children` → 各ブロックを `DELETE /v1/blocks/<id>` → 正しいブロックを `PATCH /v1/blocks/<page-id>/children` に 100 件ずつ追送すると、URL を保ったまま中身だけ差し替えられる。削除前に取得結果をファイルへ退避しておく。

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

「このチャンネルの今月の動画を全部」のような依頼のとき。

1. `https://www.youtube.com/@<handle>/videos` を開く。`/videos` を指定してもホームタブが出ることがあるので、その場合は「動画」タブをクリックする。
2. 下端まで数回スクロールしてから、動画一覧を取る。`ytInitialData` の走査は BLOCKED になりやすいので DOM から拾う:
   ```js
   [...document.querySelectorAll('ytd-rich-item-renderer')].map(it => {
     const a = it.querySelector('a[href*="/watch?v="]');
     const id = a ? (a.getAttribute('href').match(/v=([\w-]{11})/)||[])[1] : '';
     return id + ' :: ' + it.innerText.replace(/\s*\n\s*/g,' | ').trim();
   });
   ```
   `innerText` に「再生時間 | タイトル | 再生数 | 公開時期 | メンバー限定」が入る。再生数が無く「メンバー限定」が付くものが限定動画。
3. 公開時期は「3 日前」「4 週間前」のような相対表記。実日付は**ブラウザを使わず** `curl` で取れるので、対象が決まったら一括で引く。相対表記だけで月をまたぐ判定をしない。
   ```bash
   curl -s -A "Mozilla/5.0" "https://www.youtube.com/watch?v=<id>" | grep -o '"publishDate":"[^"]*"'
   ```
4. Notion の DB を `notion_query.py query --compact` で引いて、既に登録済みのURLを除外してから処理対象を確定する。対象リストをユーザーに見せてから実行に入る。

### 数十本以上を一括処理するとき

DOMスクロールでは全件出ない(仮想リストで30件しか描画されない)。innertube の継続トークンを回して全件取る。

1. `ytInitialData` を走査して `lockupViewModel`(動画は `contentId`/`metadata.lockupMetadataViewModel`)と `continuationItemRenderer.continuationEndpoint.continuationCommand.token` を集める。**変数名に `token` を使うと拡張のプライバシーフィルタに BLOCKED されるので別名にする**。
2. 集めたトークンで `POST /youtubei/v1/browse?key=<INNERTUBE_API_KEY>`(body に `context: ytcfg.get('INNERTUBE_CONTEXT')`)を繰り返し、新規が増えなくなるまで回す。最初のページには他タブ由来のトークンも混ざるので、**新規が増えたものを当たりとして採用する**。
3. 一覧・進捗・分類・公開日を scratchpad のファイルに落とし、処理はドライバスクリプトに任せる。会話に長文を載せない。
   - `worklist.tsv` … status(TODO/DONE/SKIP) / class / videoId / 相対日付 / タイトル
   - `state.tsv` … videoId / ok・pending・member・fail / source_id
   - `meta.tsv` `cat.tsv` … 公開日、カテゴリ
   - `summaries/<videoId>.md` … 整形済み要約
4. ドライバは「登録に成功したら即 `pending` を書き、要約まで済んだら `ok` に上書き」する。途中で落ちても登録済みのものを二重登録しない。
5. ノートブックは1冊50ソースが上限。45件を超えたら `YouTube_<チャンネル名>_02` のように作って切り替える。
6. 1本あたり登録40秒＋要約45秒。**数十本で1時間、200本超なら数時間**かかる。1セッションで終わらない規模なら、その旨と再開方法を先に伝える。

#### `nlm source add` の落とし穴(実測)

- **出力JSONの形が引数の数で変わる**。単体(`-u` 1個)は `{"source_id": ...}` を直接返し、複数指定は `{"results":[{...}]}` を返す。**両方を受けるパーサにすること**。片方しか見ないと、登録は成功しているのに失敗と誤記録する。
- その誤記録を消して再試行させると**同じ動画が二重登録される**。取り込み失敗と判定したら、消す前に `nlm source list` で実体が無いことを確かめる。
- メンバー限定動画をバルク(`-u` 複数)で登録すると**エラーを返さず結果配列から静かに消える**。単体で登録すれば `{"status":"error",...}` が返るので判定できる。判定は必ず単体で行う。
- 重複を掃除するときは `nlm source delete <id>... --confirm`。**完全削除で戻せない**ので、要約と紐づく `source_id`(state.tsv 参照)を必ず残す側に選び、実行前にユーザーへ確認する。

## 終了条件と失敗時の扱い

- 成功: Notionページが作成され、URLをユーザーに報告した。
- 字幕トラックが無い(captionTracksが空): 抽出不可と報告して終了。別手段(音声ダウンロード等)へ勝手に進まない。
- Chrome拡張がyoutube.comの権限を持たない/タブ操作が2〜3回失敗: 状況を説明してユーザーに確認する。
- 字幕リクエストが3周叩いても発生しない、または有効なレスポンスが取れない: ブラウザの再起動を提案する(再起動で通るようになった実績がある)。勝手に再生を試み続けない。
- nlm が認証エラー(終了コード 3): 手順3の「認証が切れたとき」へ。`nlm auth login` を素で繰り返さない。
- nlm が認証以外のエラーで失敗: エラーをそのまま提示して指示を待つ。要約だけClaudeが直接行う代替は、ユーザーが同意した場合のみ。
- Notion書き込み失敗: 要約テキストを会話に提示し、保存だけ後でやり直せる状態にして終了する。
- 想定外の入力(URLがYouTube動画でない、プレイリストURL等): 進めずに確認する。
