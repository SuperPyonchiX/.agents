# playwright-cli 早見表（このスキルで使う分だけ）

playwright-cli（`@playwright/cli`、Apache-2.0）の全コマンドは `--help` と、同梱の SKILL.md（`--help` の冒頭にパスが出る）にある。ここには V0〜V4 で使うものだけを、使う順に置く。動作確認は 0.1.19 / Node 24 / Windows 11。

## 導入と起動（V0）

```bash
# グローバル導入なしで動く。毎回 npx で呼ぶか、シェルで alias を切る
npx -y @playwright/cli@latest --help
alias playwright-cli='npx -y @playwright/cli@latest'   # bash。PowerShell は function で同等

# 初回だけブラウザを入れる（入っていれば何もしない）
playwright-cli install-browser chromium

# 開いて移動。ユーザーの環境に合わせる（ダークモード等はアプリ側の状態で作る）
playwright-cli open http://localhost:50000
playwright-cli resize 1280 800
```

`goto` の URL に `&` を含むときは Windows の cmd/PowerShell で壊れる。`--%` か引用で逃がす（同梱 SKILL.md「Open parameters」の直前を参照）。

セッションは既定で1つ。並行して別の作業がブラウザを使う場合は `-s=<name>` で分ける。終わったら `close`、固まったら `kill-all`。

## 撮影（V0・V1・V3）

```bash
# 全体。baseline と、各周回の全体確認に使う
playwright-cli screenshot --filename=work/ui/baseline.png

# 要素だけ。ref は snapshot で得る
playwright-cli screenshot e15 --filename=work/ui/UI-001-before.png

# 高解像度が要るとき（細い線・小さい文字）
playwright-cli screenshot e15 --hires --filename=work/ui/UI-001-before.png
```

同じ条件で撮ること。**ホバー中・フォーカス中の見た目が指摘なら、撮る直前に `hover <ref>` / `click <ref>` で状態を作り、before と after で同じ操作をする。**

## 要素の特定（V1）

```bash
# 位置つきのスナップショット。[box=x,y,w,h] が付くので「右上の」「下に見切れている」と突き合わせられる
playwright-cli snapshot --boxes --filename=work/ui/snap.yml

# 文言から候補を絞る
playwright-cli find "コピー"
playwright-cli find --regex "/copy|コピー/i"

# 候補に赤枠を付けて撮り、ユーザーに「この要素で合っているか」を確認する
playwright-cli highlight e15 --style="outline: 3px solid red"
playwright-cli screenshot --filename=work/ui/UI-001-candidate.png
playwright-cli highlight --hide

# ユーザーに画面上で囲んでもらう。注釈付き画像・スナップショット・メモが返る
playwright-cli show --annotate

# 修正で触るセレクタを得る
playwright-cli eval "el => el.className" e15
playwright-cli generate-locator e15 --raw
```

`show --annotate` は、言葉やスクリーンショットからの特定が2回外れたら迷わず使う。ユーザーが囲んだ要素の ref がそのまま返るので取り違えが消える。

## 計測（V1・V3）

指摘を数値に落とす。before と after で**同じ式**を使う。

```bash
# 色・フォント・余白
playwright-cli --raw eval "el => { const s = getComputedStyle(el); return JSON.stringify({color: s.color, bg: s.backgroundColor, font: s.fontSize, pad: s.padding, margin: s.margin}) }" e15

# 位置とサイズ（見切れ・重なり）
playwright-cli --raw eval "el => JSON.stringify(el.getBoundingClientRect())" e15

# 親からはみ出しているか（見切れの判定）
playwright-cli --raw eval "el => { const r = el.getBoundingClientRect(); const p = el.parentElement.getBoundingClientRect(); return JSON.stringify({overflowRight: r.right - p.right, overflowBottom: r.bottom - p.bottom, scrollW: el.scrollWidth, clientW: el.clientWidth}) }" e15

# コントラスト比の材料（文字色と背景色）。比の計算は自分で行う（WCAG は 4.5:1 が目安）
playwright-cli --raw eval "el => { const s = getComputedStyle(el); return JSON.stringify([s.color, s.backgroundColor]) }" e15

# 見えているか（display/visibility/opacity と viewport 内か）
playwright-cli --raw eval "el => { const s = getComputedStyle(el); const r = el.getBoundingClientRect(); return JSON.stringify({display: s.display, vis: s.visibility, op: s.opacity, inView: r.top >= 0 && r.bottom <= innerHeight}) }" e15
```

`--raw` を付けると結果だけが返るので、台帳にそのまま貼れる。

## 修正の反映（V2→V3）

```bash
playwright-cli reload
# ビルドが要るアプリはビルド後に reload。ホットリロードでも、CSS のキャッシュが疑わしければ reload する
```

反映後に `snapshot` を取り直すと ref が振り直されることがある。**after の撮影・計測は、取り直した snapshot の ref で行う。** before と同じ ref をそのまま使わない。

## playwright-cli が使えない環境での代替

工程（V0〜V4）と台帳は変えない。撮影と計測の手段だけ置き換える。

| 環境 | 撮影 | 要素特定・計測 |
|---|---|---|
| Playwright MCP / Claude in Chrome がある | そのスクリーンショット機能 | そのスナップショット／JS 実行機能で同じ式を評価する |
| ブラウザ操作ツールが無い | ユーザーに同じ幅・同じ状態で撮ってもらう。**条件を台帳に書いてから依頼する** | DevTools の Console で上の式を実行してもらい、結果を貼ってもらう |

代替手段では `show --annotate` が無いので、要素の合意は「候補のセレクタを示し、ユーザーに DevTools で確認してもらう」で行う。
