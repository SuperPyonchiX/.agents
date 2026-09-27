---
name: narrated-video
description: 台本から VOICEVOX でナレーション音声を作り、Remotion の動画に尺を合わせて載せ、字幕とクレジットつきの解説動画（MP4）を書き出すスキル。音声は無料・ローカルで作る。「ナレーション付きの動画を作って」「音声つきの解説動画にして」「ずんだもんに読ませて動画にして」「この説明を動画にして」で使う。音声なしの動画や Remotion の書き方そのものは remotion-best-practices。
metadata:
  web-description: 台本から VOICEVOX でナレーション音声を作り、Remotion で尺を合わせて字幕・クレジットつきの解説動画（MP4）にする。「ナレーション付きの動画を作って」「音声つきの解説動画にして」「ずんだもんに読ませて」で使う。
---

# ナレーション付き解説動画を作る

Remotion の公式スキルは音声合成に有料の ElevenLabs を前提にしている。このスキルは VOICEVOX（無料・ローカル）に差し替え、**音声の長さを先に確定させてから画面の尺を決める**。画面を先に作って音声を後から当てると、読み終わる前にシーンが切り替わる。

勘所は3つ。(1) **尺の正本は音声** — `voicevox_tts.py` が wav の長さを計って `narration.json` に書き、雛形はそこから尺を計算する。手で秒数を書かない。(2) **読みと字幕を分ける** — VOICEVOX は英単語を読み間違えるので、読み上げ文（`text`）は仮名で書き、画面の表記は `subtitle` に書く。(3) **読み間違いは人の耳でしか分からない** — 最後にユーザーに聞いてもらう工程を省かない。

Remotion の書き方（アニメーション、レイアウト、フォント、画像）は `remotion-best-practices` スキルに従う。このスキルが持つのは、音声と尺と字幕の部分だけ。

## ワークフロー

```
N0 準備 → N1 台本（承認） → N2 音声生成 → [N3 組み立て → N4 検証] を最大3周 → N5 試聴（承認） → N6 納品
                    ↑______________ 読み間違い・内容の直し（該当シーンだけ） ______________|
```

| # | 工程 | 出力 |
|---|---|---|
| 0 | 準備 | Remotion プロジェクト、起動したエンジン |
| 1 | 台本 | `scenes.json`（ユーザー承認済み） |
| 2 | 音声生成 | `public/narration/<id>.wav`、`src/narration.json` |
| 3 | 組み立て | `src/NarratedVideo.tsx`、`out/<名前>.mp4` |
| 4 | 検証 | 尺の突き合わせ結果、シーンごとの静止画 |
| 5 | 試聴 | 直すシーンの一覧（無ければ空） |
| 6 | 納品 | MP4 のパスとクレジット表記 |

## 手順

### N0: 準備

1. 作業先を決める。既存の Remotion プロジェクトがあればそこ、無ければ `remotion-best-practices` の手順で作る（`npx create-video@latest --yes --blank --no-tailwind <名前>` の後に `npm install`）。
2. `npx remotion add @remotion/media` で音声コンポーネントを入れる。
3. `python scripts/voicevox_tts.py --list-speakers` を実行する。終了コード 1 ならエンジンが動いていない。`references/voicevox.md` の「エンジンの起動」に従って起動し、もう一度実行する。
4. 話者をユーザーに決めてもらう（指定が無ければ候補を2〜3人挙げる）。

**完了条件**: プロジェクトに `@remotion/media` が入り、`--list-speakers` が終了コード 0 で、話者の style id が決まっていること。

**戻り条件**: エンジンを起動しても接続できない、VOICEVOX が入っていない場合は、導入方法（`winget install HiroshibaKazuyuki.VOICEVOX.CPU`）を案内して止まる。

### N1: 台本

1. `references/voicevox.md` の「台本の書き方」を読む。
2. プロジェクト直下に `scenes.json` を書く。形は `scripts/voicevox_tts.py` の冒頭コメントのとおり（`speaker`・`speedScale`・`pauseAfter`・`scenes[]` の `id`・`text`・任意の `subtitle`）。
3. シーンごとに「字幕」と「画面に出すもの」を表にしてユーザーに見せ、承認を得る。

**完了条件**: `scenes.json` があり、全シーンの内容についてユーザーの承認を得たこと。

### N2: 音声生成

```
python scripts/voicevox_tts.py scenes.json --out public/narration --manifest src/narration.json
```

**完了条件**: 終了コード 0 で、全シーンの秒数とクレジット表記が標準出力に出たこと。

**戻り条件**: 終了コード 1 は N0 の手順3に戻る。2 は `scenes.json` を直す。3（合成失敗）はエンジンのログを見て、1回だけ再実行する。それでも 3 なら止まって報告する。

### N3〜N4: 組み立てと検証（最大3周）

```
N3 (初回のみ): assets/templates/NarratedVideo.tsx を src/ にコピーし、Root.tsx で <NarratedComposition /> を登録する
for 周回 in 1..3:
    N3: SCENE_VISUALS にシーンごとの画面を書く（remotion-best-practices に従う）
        npx tsc --noEmit → エラーなら直す
        npx remotion render Narrated out/<名前>.mp4
    N4: 映像の長さを測る
          npx remotion ffprobe -v error -select_streams v:0 -show_entries stream=duration -of csv=p=0 out/<名前>.mp4
        python scripts/scene_frames.py src/narration.json --mp4-seconds <測った秒数>
          終了コード 1 → 雛形の FPS・TAIL_FRAMES・CREDIT_FRAMES と --fps・--tail・--credit が食い違っている。そろえる
        表の「中央」フレームごとに npx remotion still Narrated out/<id>.png --frame=<中央> を実行し、画像を開いて確かめる
          - 字幕が画面の要素と重なっていないか、はみ出していないか
          - 画面がそのシーンの字幕の内容と合っているか
          - 最後のクレジット画面に narration.json の credit が出ているか
    if 直す点が無い:
        break
    直す点だけを直す
else:
    3周しても直す点が残る → 残った点を添えて現状を提示し、判断を仰ぐ
```

**完了条件**: `scene_frames.py` が終了コード 0、全シーンの静止画を目で見て直す点が無いこと。

### N5: 試聴

1. MP4 を `reveal-file` スキルでエクスプローラーに表示し（無ければパスを伝える）、ユーザーに通しで聞いてもらう。
2. 読み間違い・間の悪さ・内容の直しを、シーン id つきで受け取る。
3. 直すものがあれば、該当シーンの `text`（または `subtitle`）を直し、次で作り直して N3 のレンダリングからやり直す。

   ```
   python scripts/voicevox_tts.py scenes.json --out public/narration --manifest src/narration.json --only s02,s05
   ```

**完了条件**: ユーザーから「このままでよい」の回答を得たこと。

### N6: 納品

MP4 のパス、全体の秒数、クレジット表記（`VOICEVOX:キャラ名`）を伝える。公開・配布する予定があるなら、使ったキャラの利用規約を確認するよう添える（`references/voicevox.md`）。エンジン単体を起動していたら止める。

## 禁止事項

- **尺を手で書くこと**（`durationInFrames` に秒数から暗算した値を直書きするなど）。尺は必ず `narration.json` から計算する。
- **ユーザーに聞いてもらわずに完成とすること。** 静止画の検証では音声の読み間違いは分からない。
- **クレジット表記を消すこと。** 説明欄に書く場合を除き、クレジット画面は残す。
- 台本の文章を有料・外部の音声合成サービスに送ること（ユーザーが明示的に頼んだ場合を除く）。

## スクリプト

依存は標準ライブラリのみ。音声合成には VOICEVOX（無料）のエンジンを起動しておく。

`scripts/voicevox_tts.py` — N0（話者一覧）と N2・N5（音声生成）で使う。

```
python scripts/voicevox_tts.py --list-speakers [--host URL]
python scripts/voicevox_tts.py <scenes.json> --out <public/narration> --manifest <src/narration.json> [--only id,id] [--host URL]
```

シーンごとに wav を作り、長さを計って `narration.json`（`credit`・`speaker`・`scenes[]` の `id`・`text`・`subtitle`・`file`・`seconds`・`total_seconds`）に書く。`file` は `staticFile()` に渡す `public/` からの相対パス。`--only` は指定シーンだけ作り直してマニフェストの該当行を差し替える。終了コードは 0（作った）/ 1（エンジンに接続できない）/ 2（引数・入力の誤り）/ 3（合成に失敗）。

`scripts/scene_frames.py` — N4 で使う。

```
python scripts/scene_frames.py <src/narration.json> [--fps 30] [--tail 6] [--credit 60] [--mp4-seconds <秒>]
```

雛形と同じ式で各シーンの開始・中央フレームと全体のフレーム数を出す。`--mp4-seconds` を渡すと実測と比べ、1フレームを超えてずれたら終了コード 1。終了コードは 0（ずれなし）/ 1（ずれている）/ 2（引数の誤り・マニフェストが読めない）。

## テンプレートと参照ファイル

| ファイル | 使うとき |
|---|---|
| `assets/templates/NarratedVideo.tsx` | N3 の初回にコピーする。シーンの並べ方・音声・字幕・クレジット画面が入っている |
| `references/voicevox.md` | N0 でエンジンに接続できないとき、N1 で台本を書く前 |
