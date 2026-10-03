---
name: narrated-video
description: 台本からナレーションを作り Remotion で尺を合わせて字幕つき MP4 にする。解説動画とビート同期の告知・CM 動画に対応。音声は Gemini TTS か VOICEVOX、3D は Blender か Three.js。「解説動画にして」「告知動画を作って」で使う。Remotion の書き方は remotion-best-practices。
---

# ナレーション付きの動画を作る

台本 → 音声 → 尺の決定 → 画面 → 書き出しの順に進める。**音声の長さを先に確定させてから画面の尺を決める。** 画面を先に作って音声を後から当てると、読み終わる前にシーンが切り替わる。

勘所は4つ。(1) **尺の正本は音声とタイムライン** — 音声スクリプトが wav の長さを `narration.json` に書き、`timeline.py` がそこから各シーンの開始と尺を `timeline.json` に決める。雛形はそれを読むだけで、手で秒数を書かない。(2) **告知・CM は拍に合わせる** — シーンの切り替えと動きを BPM の格子にそろえると、短い指示でも編集された動画に見える。(3) **3D は透過 PNG の連番にして 2D に重ねる** — Blender が2回で通らなければ Three.js に切り替える。(4) **読み間違いとリズムは人の耳でしか分からない** — 最後にユーザーに聞いてもらう工程を省かない。

Remotion の書き方（アニメーション、レイアウト、フォント、画像）は `remotion-best-practices` スキルに従う。このスキルが持つのは、音声・尺・拍・3D 素材・字幕の部分。

## ワークフロー

```
N0 準備（3つ決める） → N1 台本（承認） → N2 音声 → N2b タイムライン → [N2c 3D 素材]
    → [N3 組み立て → N4 検証] を最大3周 → N5 試聴（承認） → N6 納品
         ↑____________ 読み間違い・リズム・内容の直し（該当シーンだけ） ____________|
```

| # | 工程 | 出力 |
|---|---|---|
| 0 | 準備 | 種類・音声エンジン・3D の決定、Remotion プロジェクト |
| 1 | 台本 | `scenes.json`（ユーザー承認済み） |
| 2 | 音声 | `public/narration/<id>.wav`、`src/narration.json` |
| 2b | タイムライン | `src/timeline.json`（告知・CM なら `public/bgm/beat.wav` も） |
| 2c | 3D 素材 | `public/3d/<id>/0001.png〜`（3D を使うときだけ） |
| 3 | 組み立て | `src/NarratedVideo.tsx`、`out/<名前>.mp4` |
| 4 | 検証 | 尺の突き合わせ結果、シーンごとの静止画 |
| 5 | 試聴 | 直すシーンの一覧（無ければ空） |
| 6 | 納品 | MP4 のパスとクレジット表記 |

## 手順

### N0: 準備

1. 次の3つをユーザーに決めてもらう。依頼文から明らかなものは聞かずに決め、決めた値を1行で伝える。

   | 決めること | 選択肢 | 既定 |
   |---|---|---|
   | 種類 | 解説（落ち着いて説明する）／告知・CM（15〜30秒、ビートに合わせて動く） | 依頼文から判断 |
   | 音声 | Gemini（感情・テンションを指示できる。台本が Google に送られる）／VOICEVOX（無料・ローカル） | Gemini。社外秘の台本・API キーが無いときは VOICEVOX |
   | 3D | なし／Blender／Three.js | なし。告知・CM で立体的な見せ場が要るときは Blender |

   撮影済みの実写素材を切ってつなぐ編集や、ナレーションの無い動画はこのスキルの対象外。そう伝えて、ナレーション無しなら `remotion-best-practices` で作るか聞く。

2. 作業先を決める。既存の Remotion プロジェクトがあればそこ、無ければ `remotion-best-practices` の手順で作る（`npx create-video@latest --yes --blank --no-tailwind <名前>` の後に `npm install`）。
3. `npx remotion add @remotion/media` で音声コンポーネントを入れる。
4. 選んだものの準備を確かめる。

   | 選んだもの | 確かめ方 | 通らないとき |
   |---|---|---|
   | Gemini | 環境変数 `GEMINI_API_KEY` があること（値は表示しない） | `references/gemini-tts.md` の「API キー」を案内する。待てなければ VOICEVOX にするか聞く |
   | VOICEVOX | `python scripts/voicevox_tts.py --list-speakers` が終了コード 0 | `references/voicevox.md` の「エンジンの起動」 |
   | Blender | `python scripts/blender_render.py --find` が終了コード 0 | `references/blender.md` の「導入」。承認が無ければ Three.js にする |

5. 話者（VOICEVOX の style id か Gemini のボイス名）を決めてもらう。指定が無ければ候補を2〜3個挙げる。

**完了条件**: 3つの決定と話者が決まり、手順4の確かめ方がすべて通っていること。

**戻り条件**: どの音声エンジンも使えない場合は、導入方法を案内して止まる。

### N1: 台本

1. 選んだ音声エンジンの資料の「台本の書き方」を読む（Gemini は `references/gemini-tts.md`、VOICEVOX は `references/voicevox.md`）。
2. プロジェクト直下に `scenes.json` を書く。形は使う音声スクリプトの冒頭コメントのとおり。告知・CM は1シーン1文・5秒以内にする。
3. シーンごとに「字幕」「画面に出すもの」「3D の有無」（Gemini なら「話し方」も）を表にしてユーザーに見せ、承認を得る。

**完了条件**: `scenes.json` があり、全シーンの内容についてユーザーの承認を得たこと。

### N2: 音声

```
python scripts/gemini_tts.py scenes.json --out public/narration --manifest src/narration.json
python scripts/voicevox_tts.py scenes.json --out public/narration --manifest src/narration.json
```

選んだエンジンの方だけを実行する。Gemini で話者を試すときは `--only s01` で1シーンだけ作って聞いてもらう。

**完了条件**: 終了コード 0 で、全シーンの秒数が標準出力に出たこと。

**戻り条件**: 終了コード 1 は N0 の手順4に戻る。2 は `scenes.json` を直す。3（合成失敗）は1回だけ再実行し、それでも 3 なら止まって報告する。

### N2b: タイムライン

解説:

```
python scripts/timeline.py src/narration.json --out src/timeline.json
```

告知・CM（先に `references/beat-sync.md` を読み、BPM・パターン・`--snap` を決める）:

```
python scripts/timeline.py src/narration.json --out src/timeline.json --bpm 124 --pattern four --bgm public/bgm/beat.wav
```

**完了条件**: 終了コード 0 で、シーンごとの開始・中央・尺の表が出たこと。この表の値を N2c と N4 で使う。

### N2c: 3D 素材（3D を使うときだけ）

`references/blender.md` を読み、3D を使うシーンごとに作る。

```
for シーン in 3D を使うシーン:
    試行 = 0
    while 試行 < 2:
        scene_template.py をもとに blender/<id>.py を書く（2回目は前回のログを見て直す）
        python scripts/blender_render.py blender/<id>.py --out public/3d/<id> --frames <枚数> [--set ...]
        if 終了コード 0 かつ 1枚目と最後の1枚を開いて意図どおり:
            break
        試行 += 1
    else:
        そのシーンは Three.js（references/blender.md の「Three.js に切り替える」）で作ると決め、N3 で書く
```

**完了条件**: 3D を使う全シーンについて、連番 PNG がそろって目で確かめたか、Three.js で作ると決まったこと。

### N3〜N4: 組み立てと検証（最大3周）

```
N3 (初回のみ): assets/templates/NarratedVideo.tsx を src/ にコピーし、Root.tsx で <NarratedComposition /> を登録する
for 周回 in 1..3:
    N3: SCENE_VISUALS にシーンごとの画面を書く（remotion-best-practices に従う。
        3D は <BlenderClip>、拍に合わせる動きは useBeat()。references/beat-sync.md）
        npx tsc --noEmit → エラーなら直す
        npx remotion render Narrated out/<名前>.mp4
    N4: 映像の長さを測る
          npx remotion ffprobe -v error -select_streams v:0 -show_entries stream=duration -of csv=p=0 out/<名前>.mp4
        python scripts/timeline.py --check src/timeline.json --mp4-seconds <測った秒数>
          終了コード 1 → 雛形の Composition が timeline.json 以外から尺を取っている。timeline.json に戻す
        N2b の表の「中央」（告知・CM は「開始」も）のフレームごとに
          npx remotion still Narrated out/<id>.png --frame=<番号> を実行し、画像を開いて確かめる
          - 字幕が画面の要素と重なっていないか、はみ出していないか
          - 画面がそのシーンの字幕の内容と合っているか
          - 3D の素材が欠けていないか、背景と自然につながっているか
          - クレジットがある（timeline.json の credit が空でない）なら最後に出ているか
    if 直す点が無い:
        break
    直す点だけを直す
else:
    3周しても直す点が残る → 残った点を添えて現状を提示し、判断を仰ぐ
```

**完了条件**: `timeline.py --check` が終了コード 0、全シーンの静止画を目で見て直す点が無いこと。

### N5: 試聴

1. MP4 を `reveal-file` スキルでエクスプローラーに表示し（無ければパスを伝える）、ユーザーに通しで聞いてもらう。
2. 読み間違い・話し方・間・リズムのずれ・BGM の大きさ・内容の直しを、シーン id つきで受け取る。
3. 直すものがあれば、該当シーンの `text`・`subtitle`・`style` を直して `--only s02,s05` で音声を作り直し、N2b からやり直す（尺が変わるため）。BGM の大きさだけなら雛形の `BGM_VOLUME` を変えて N3 のレンダリングからやり直す。

**完了条件**: ユーザーから「このままでよい」の回答を得たこと。

### N6: 納品

MP4 のパスと全体の秒数を伝える。VOICEVOX ならクレジット表記（`VOICEVOX:キャラ名`）と、公開前に使ったキャラの利用規約を確認するよう添える（`references/voicevox.md`）。Gemini なら、公開先が AI 生成音声の開示を求めるか（YouTube の「改変または合成されたコンテンツ」など）を確認するよう添える。`--bgm` で作った仮のドラムのまま公開するかも確かめる。エンジン単体を起動していたら止める。

## 禁止事項

- **尺を手で書くこと**（`durationInFrames` や `from` に秒数から暗算した値を直書きするなど）。尺は必ず `timeline.json` から取る。
- **ユーザーに聞いてもらわずに完成とすること。** 静止画の検証では読み間違いもリズムのずれも分からない。
- **VOICEVOX のクレジット表記を消すこと。** 説明欄に書く場合を除き、クレジット画面は残す。
- **ユーザーが Gemini を選んでいないのに台本を Gemini に送ること。** 社外秘の台本は送らない。
- **API キーの値を会話に出すこと、ファイルに書くこと。** 環境変数から読ませる。
- **Blender を3回以上試すこと。** 2回で通らなければ Three.js に切り替える。
- 3D モデル・BGM・画像を、利用条件を確かめずにネットから取ってきて使うこと。

## スクリプト

`gemini_tts.py`・`voicevox_tts.py`・`timeline.py`・`blender_render.py` はすべて標準ライブラリのみで動く。外部の前提は、Gemini は API キー、VOICEVOX はエンジンの起動、Blender は本体のインストール。

`scripts/gemini_tts.py` — N2・N5 で使う（Gemini を選んだとき）。

```
python scripts/gemini_tts.py <scenes.json> --out <public/narration> --manifest <src/narration.json> [--only id,id] [--model gemini-3.8-flash-tts]
```

`voicevox_tts.py` と同じ形の `narration.json` を書く（`credit` は空）。429 などの一時的なエラーは待って再試行する。終了コードは 0（作った）/ 1（API キーが無い・認証失敗）/ 2（引数・入力の誤り）/ 3（合成に失敗）。

`scripts/voicevox_tts.py` — N0（話者一覧）と N2・N5 で使う（VOICEVOX を選んだとき）。

```
python scripts/voicevox_tts.py --list-speakers [--host URL]
python scripts/voicevox_tts.py <scenes.json> --out <public/narration> --manifest <src/narration.json> [--only id,id] [--host URL]
```

シーンごとに wav を作り、長さを計って `narration.json`（`credit`・`speaker`・`scenes[]` の `id`・`text`・`subtitle`・`file`・`seconds`・`total_seconds`）に書く。終了コードは 0（作った）/ 1（エンジンに接続できない）/ 2（引数・入力の誤り）/ 3（合成に失敗）。

`scripts/timeline.py` — N2b（作る）と N4（確かめる）で使う。

```
python scripts/timeline.py <src/narration.json> --out <src/timeline.json> [--fps 30] [--tail 6] [--credit auto|<フレーム数>]
                           [--bpm N [--snap beat|bar] [--beats-per-bar 4] [--pattern four|half|break] [--bgm public/bgm/beat.wav]]
python scripts/timeline.py --check <src/timeline.json> --mp4-seconds <秒>
```

尺は `--bpm` なしなら `ceil(秒 × fps) + tail`、ありなら拍か小節の長さで切り上げる。`--credit auto` は `credit` が空なら 0。`--bgm` は指定の BPM・パターンでドラムを合成する。終了コードは 0（作った・ずれなし）/ 1（実測とずれている）/ 2（引数の誤り・入力が読めない）。

`scripts/blender_render.py` — N0（`--find`）と N2c で使う。

```
python scripts/blender_render.py --find [--blender PATH]
python scripts/blender_render.py <scene.py> --out <public/3d/<id>> --frames N [--fps 30] [--width 1920] [--height 1080] [--set key=value] [--blender PATH] [--timeout 900]
```

Blender を画面なしで起動してシーンスクリプトを実行し、連番 PNG が N 枚そろったかを確かめる。終了コードは 0（そろった）/ 1（Blender が見つからない）/ 2（引数の誤り）/ 3（異常終了・時間切れ・枚数不足。末尾のログを出す）。

## テンプレートと参照ファイル

| ファイル | 使うとき |
|---|---|
| `assets/templates/NarratedVideo.tsx` | N3 の初回にコピーする。シーンの並べ方・音声・BGM・字幕・クレジット・`useBeat()`・`BlenderClip` が入っている |
| `assets/blender/scene_template.py` | N2c で Blender のシーンを書き始めるとき |
| `references/gemini-tts.md` | N0 で Gemini を選んだとき（API キー・料金・ボイス）、N1 で台本を書く前 |
| `references/voicevox.md` | N0 で VOICEVOX を選んだとき（エンジンの起動）、N1 で台本を書く前 |
| `references/beat-sync.md` | 告知・CM で N2b の BPM を決める前、N3 で拍に合わせた動きを書く前 |
| `references/blender.md` | N0 で Blender が見つからないとき、N2c で素材を作る前、Three.js に切り替えるとき |
