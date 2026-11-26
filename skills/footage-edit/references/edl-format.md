# EDL（edl.json）の形とスクリプト

## ffmpeg の導入

スクリプトは ffmpeg と ffprobe を使う。`ffmpeg -version` が通らなければ入れる。

| OS | コマンド |
|---|---|
| Windows | `winget install Gyan.FFmpeg`（入れた後、ターミナルを開き直す） |
| macOS | `brew install ffmpeg` |
| Ubuntu / WSL | `sudo apt install ffmpeg` |

文字起こしを使うなら `pip install faster-whisper` も入れる。初回はモデルを Hugging Face から取得するので通信が要る（推論はローカルで、音声は外に出ない）。

## EDL

E3 で `draft_edl.py` の下書きを直すとき、手で EDL を書くときに読む。
EDL は「どの素材のどこを、どの順で、どう見せるか」の正本。`render.py`・`make_subs.py`・`check.py` はすべてこれを読む。
**秒数を他のファイルや会話に写して使わない。** 尺を変えたら EDL を直して、そこから作り直す。

## 実例

```json
{
  "version": 1,
  "target": "youtube",
  "output": {"width": 1920, "height": 1080, "fps": 30},
  "sources": {"main": "../raw/talk.mp4", "screen": "../raw/screen.mp4", "b1": "../raw/product.mp4"},
  "clips": [
    {"id": "c001", "src": "main", "in": 312.40, "out": 318.90, "note": "フック: 結論の一言を冒頭へ"},
    {"id": "c002", "src": "main", "in": 0.36, "out": 3.32, "note": ""},
    {"id": "c003", "src": "main", "in": 3.88, "out": 6.27, "zoom": 1.12, "note": ""},
    {"id": "c004", "src": "screen", "in": 10.0, "out": 18.5, "audio_shift": -0.3, "note": "画面録画へ J カット"},
    {"id": "c005", "src": "main", "in": 8.36, "out": 12.20, "jump_ok": true, "note": "テンポ優先で跳ねを残す"}
  ],
  "overlays": [
    {"src": "b1", "in": 2.0, "out": 5.5, "at_clip": "c005", "offset": 0.4, "note": "製品の外観"}
  ],
  "subtitles": "subs.srt",
  "burn_subtitles": true,
  "subtitle_style": {"font": "Meiryo", "size": 20, "outline": 2, "margin_v": 40},
  "music": {"src": "../raw/bgm.mp3", "gain_db": -20, "duck": true, "fade_out": 2.0}
}
```

パスは EDL ファイルのあるディレクトリからの相対か、絶対パス。

## 項目

| 項目 | 必須 | 意味 |
|---|---|---|
| `target` | | 音量の目標。`youtube`（既定）/ `podcast` / `broadcast` / `internal`。値は `delivery-specs.md` |
| `output` | | `width` `height` `fps` `fit`。省くと最初のクリップの素材に合わせる。`fit` は `contain`（既定。縦横比が違う素材は黒帯つきで縮める）か `cover`（出力の縦横比で切り抜いて埋める。縦型ショートで使う）。プレビュー（`--preview`）では幅 640 に縮む。手で書いた EDL で `fps` を省くと、`make_subs.py` は主素材の fps を使う |
| `sources` | ✓ | 素材のキーとパス。クリップと B ロールはキーで参照する |
| `clips` | ✓ | 出力に並べる順のクリップ。下表 |
| `overlays` | | B ロール。下表 |
| `subtitles` | | 出力の時間軸の SRT。`make_subs.py` が作る。null なら字幕なし |
| `burn_subtitles` | | true なら映像に焼き込む。false でも SRT は出力の隣に置く（配信サイトに字幕として上げる用） |
| `subtitle_style` | | 焼き込みの見た目。`font`（既定は Windows が Meiryo、macOS が Hiragino Sans、他は Noto Sans CJK JP）、`size`（20）、`outline`（2）、`margin_v`（下からの余白、40） |
| `music` | | BGM。`gain_db`（既定 -20）、`duck`（声が出ている間だけ下げる、既定 true）、`fade_out`（終わりのフェード秒、既定 2）。BGM が動画より短ければ繰り返す |

### クリップ

| 項目 | 必須 | 意味 |
|---|---|---|
| `id` | | 識別子。`check.py` の指摘と確認画像はこれで示す。省くと `c01`… |
| `src` | ✓ | `sources` のキー |
| `in` `out` | ✓ | 素材上の秒。映像の長さはフレーム単位に丸める |
| `zoom` | | 拡大率（既定 1.0）。パンチインに使う |
| `center` | | 拡大・切り抜きの中心 `[x, y]`（0〜1、既定 `[0.5, 0.5]`）。顔が上寄りなら `[0.5, 0.3]`。縦型（`fit: cover`）で話し手が左寄りなら `[0.3, 0.5]` |
| `audio_shift` | | このクリップの開始の境目で、音声だけを動かす秒。負: J カット（次の音が先に入る）、正: L カット（前の音が残る）。最初のクリップでは無視する。素材の外にはみ出すと `render.py` が終了コード 2 |
| `jump_ok` | | true なら、隠れていないジャンプカットとして WARN にしない（意図して残す跳ね） |
| `note` | | 残した理由・意図。E3 の計画表と、E6 の自己検査で使う |

### B ロール

| 項目 | 必須 | 意味 |
|---|---|---|
| `src` | ✓ | `sources` のキー |
| `in` `out` | ✓ | 素材上の秒 |
| `at` | どちらか | 出力上の開始秒 |
| `at_clip` + `offset` | どちらか | クリップの頭からの秒。クリップを並べ替えても付いてくるので、こちらを使う |
| `note` | | 内容。確認画像の一覧に出る |

B ロールは映像だけを差し替え、音は主素材のまま流す。画面いっぱいに拡大して切り抜く。

## analysis.json

`analyze.py` が書く。E3 で読むのは `speech`（発話区間）と `scene_changes`（画の切り替わり）。

```json
{
  "params": {"noise_db": -35.0, "min_silence": 0.4, "scene": 0.35},
  "sources": [
    {"path": "raw/talk.mp4", "duration": 38.0,
     "video": {"width": 1280, "height": 720, "fps": 30.0, "codec": "h264"},
     "audio": {"sample_rate": 48000, "channels": 2, "codec": "aac"},
     "silences": [[6.016, 8.512], [16.021, 19.008]],
     "speech": [[0.512, 6.016], [8.512, 16.021]],
     "loudness": {"lufs": -28.4, "lra": 6.4, "true_peak": -26.2},
     "scene_changes": [12.4, 30.1],
     "silence_ratio": 0.3}
  ]
}
```

秒はすべて素材上の時刻。音声の無い素材は `audio` `loudness` が null、`speech` が空になる。

## スクリプトの呼び出しと終了コード

すべて `scripts/` にあり、標準ライブラリと ffmpeg / ffprobe だけで動く（`transcribe.py` の既定の動きだけが faster-whisper を使う）。
`analyze.py`・`render.py`・`check.py` は ffmpeg / ffprobe が無いと導入方法を出して終了コード 2 で止まる（`draft_edl.py`・`make_subs.py` は EDL・JSON を扱うだけで ffmpeg を使わない。`make_subs.py` は `output.fps` が無いときだけ ffprobe を使う）。
`ffutil.py` は共通処理の内部モジュールで、直接は実行しない。

| スクリプト | 工程 | 呼び出し | 終了コード |
|---|---|---|---|
| `analyze.py` | E1 | `python scripts/analyze.py <素材>... --out edit/analysis.json [--noise -35] [--min-silence 0.4] [--scene 0.35] [--no-scene]` | 0 測れた / 2 引数・素材の誤り / 3 ffmpeg が失敗 |
| `transcribe.py` | E2 | `python scripts/transcribe.py <素材> --out edit/transcript.json [--model small] [--language ja] [--device auto\|cpu\|cuda]`、既存字幕から作るなら `--from-srt <srt>` | 0 書いた / 2 引数の誤り・faster-whisper が無い / 3 文字起こしに失敗 |
| `draft_edl.py` | E3 | `python scripts/draft_edl.py edit/analysis.json --out edit/edl.json [--transcript edit/transcript.json] [--source 0] [--pad-in 0.15] [--pad-out 0.25] [--merge-gap 0.35] [--min-clip 0.5] [--punch-in 1.12] [--fillers ...] [--target youtube] [--fps 30]` | 0 書いた / 2 入力の誤り・残す区間が0個 |
| `make_subs.py` | E4 | `python scripts/make_subs.py edit/transcript.json edit/edl.json --out edit/subs.srt [--max-chars 16] [--punct strip\|keep] [--fps 30]`（字幕は2行まで） | 0 書いた / 2 入力の誤り |
| `render.py` | E5 | `python scripts/render.py edit/edl.json --out out/<名前>.mp4 [--preview] [--work edit/build] [--clean]` | 0 書いた / 2 EDL・素材の誤り / 3 ffmpeg が失敗 |
| `check.py` | E6 | `python scripts/check.py out/<名前>.mp4 --edl edit/edl.json [--srt ...] [--sheet edit/sheets] [--report edit/check.json] [--max-silence 1.0] [--silence-noise -40] [--max-chars 16] [--max-cps 7] [--target youtube]`。`--sheet` の先にある前回の `sheet_*.png` は消してから作り直す | 0 ERROR なし / 1 ERROR あり / 2 引数・入力の誤り |

`render.py` はクリップごとの切り出しを作業ディレクトリ（既定は EDL の隣の `build/`）に残し、中身が同じクリップは次回使い回す。EDL を直して書き出し直すときは速い。納品後に要らなければ `--clean`。

各スクリプトの詳しい引数は `python scripts/<名前>.py --help`。
