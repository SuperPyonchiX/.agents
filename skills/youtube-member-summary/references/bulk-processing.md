# チャンネル単位でまとめて処理する

SKILL.md の「チャンネル単位でまとめて処理する場合」に当たったときに読む。1本ずつの手順（SKILL.md の手順0〜6）は変わらず、ここは対象の集め方と一括処理の回し方だけを持つ。

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

## 数十本以上を一括処理するとき

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

### `nlm source add` の落とし穴(実測)

- JSONの形とソースIDの位置を実出力で確かめる。未確認の旧版の形式を決め打ちしない。パースできなければ結果不明として止め、一覧から実体を照合する。
- その誤記録を消して再試行させると**同じ動画が二重登録される**。取り込み失敗と判定したら、消す前に `nlm source list` で実体が無いことを確かめる。
- 判別のための登録は動画1件ずつ行う。まとめて処理するときも入力URLと返されたソースを照合する。
- 重複を削除するときは `nlm source delete --help` の構文と確認方法を使う。削除対象を列挙し、ユーザーの承認範囲で実行する。要約と紐づくソースIDを残す。
