# 納品の規格（音量・字幕・映像）

E0 で配信先を決めるとき、E4 で字幕を作るとき、E6 で `check.py` の結果を読むときに読む。
数値は 2026-11-25 に一次情報（規格書・配信事業者のガイド）で確認した。一次情報が無いものはそう書く。

## 音量（ラウドネス）

測り方は ITU-R BS.1770（LUFS / LKFS は同じ単位）。`ffutil.py` は ffmpeg の `ebur128` で測る。

| EDL の `target` | 積算ラウドネス | True Peak 上限 | 許容幅（check.py） | 根拠 |
|---|---|---|---|---|
| `youtube` | -14 LUFS | -1 dBTP | ±1 LU | 配信事業者の公式値は未公開。業界の測定値（下記）。YouTube は大きすぎる動画を下げるだけで、小さい動画は上げないという報告が多い。だから小さく納めると損をする |
| `podcast` | -16 LUFS | -1 dBTP | ±1 LU | Apple Podcasts の値として業界のまとめが挙げるもの（-16 ±1、-1 dBTP）。Apple の一次資料は未確認 |
| `broadcast` | -23 LUFS | -1 dBTP | ±1 LU | EBU R128（2020）。日本の放送（ARIB TR-B32、-24 LKFS）に出すときは EDL の値をそちらに合わせる |
| `internal` | -16 LUFS | -1 dBTP | ±1.5 LU | 社内向け・会議室で流す動画。ノート PC のスピーカーでも聞き取れる大きさ |

- 迷ったら `youtube`。SNS（Instagram・TikTok）も公開された目標値は無く、-14 前後が目安とされる
- 1分未満の動画では、ラウドネスレンジ（LRA）の値は当てにならない（EBU R128）。`check.py` は LRA を表示するだけで判定しない
- 声の大きさの揺れが大きい（LRA が 15 LU を超える）素材は、loudnorm で全体を合わせても小さい声が聞き取りにくい。👁 試聴で確かめ、必要なら素材ごとに `volume` を調整する（このスキルのスクリプトは扱わない。ユーザーに相談する）

出典: [EBU R 128 (2020)](https://tech.ebu.ch/docs/r/r128v4_0.pdf)（-23.0 LUFS、ライブなど合わせきれない場合 ±1.0 LU、-1 dBTP）、[Fora Soft: LUFS targets per platform 2026](https://www.forasoft.com/learn/audio-for-video/articles-audio/lufs-targets-per-platform-2026)（YouTube -14 / -1 dBTP、下げるだけ。Apple Podcasts -16 ±1）。YouTube が小さい音量を上げるかについては、[Sweetwater](https://www.sweetwater.com/insync/how-to-master-audio-for-youtube/) が上げると書いており、資料の間で食い違っている

## 字幕

### 2つの規格を使い分ける

Netflix の日本語字幕ガイドには、翻訳字幕（他言語のセリフを日本語にする）と、聴覚障害者向けの字幕（SDH。同じ言語のセリフをそのまま文字にする）の2種類の規格がある。
話し手の言葉をそのまま文字にするこのスキルの字幕は SDH に近いので、既定値は SDH の値を使う。

| 項目 | 既定（SDH 準拠） | 翻訳字幕の値 | スクリプトの引数 |
|---|---|---|---|
| 1行の文字数（全角1・半角0.5） | 16 | 13 | `--max-chars` |
| 行数 | 2行まで | 2行まで | `--max-lines` |
| 1秒あたりの文字数 | 7 まで（WARN） | 4 まで | `check.py --max-cps` |

ショート動画（縦型）は画面の幅が狭いので `--max-chars 12` 前後にする。

### 時間の規則（Netflix 共通の規則。24fps を基準に書かれている）

| 規則 | 値 | 判定 |
|---|---|---|
| 表示の最短 | 5/6 秒（20 フレーム）。日本語ガイドの絶対的な最短は 0.5 秒 | 0.5 秒未満 ERROR、5/6 秒未満 WARN |
| 表示の最長 | 7 秒 | 超えたら ERROR |
| 字幕どうしの隙間 | 2 フレーム以上。0.5 秒未満の隙間は 2 フレームまで詰める | 2 フレーム未満 ERROR |
| 語尾の後ろ | 次の字幕が無ければ、音声の終わりから 0.5 秒ほど残すのが理想 | `make_subs.py` は 0.3 秒足す |
| カットとの関係 | 発話がカットの直後 0.5 秒以内に始まるなら、字幕もカットの頭から出す。カットの直前 0.5 秒以内に終わるなら、カットまで延ばす（2 フレーム手前） | 👁 境目の画像で確かめる |

### 日本語の表記（翻訳字幕の流儀。テロップでは好みが分かれる）

- 句点「。」は使わず、文の区切りは全角スペースにする。読点「、」は半角スペースにする（`make_subs.py --punct strip`）
- 数字は1桁なら全角、2桁以上は半角。5桁以上は「１万2345」のように漢字を交える
- 言いよどみ・中断は三点リーダー（…）

### 位置と見た目

画面下の中央、白文字に黒の縁取り。画面の上に置くのは、下に大事な情報（画面録画の操作部分、人物の口元）があるときだけ。`render.py` の焼き込みは `subtitle_style` で変えられる（`edl-format.md`）。

出典: [Netflix Japanese Timed Text Style Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215767517-Japanese-Timed-Text-Style-Guide)、[Netflix Subtitle Timing Guidelines](https://partnerhelp.netflixstudios.com/hc/en-us/articles/360051554394-Timed-Text-Style-Guide-Subtitle-Timing-Guidelines)、[Netflix General Requirements](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements)

## 映像

- 解像度・fps は主素材に合わせる（`output` を省くと最初のクリップの素材から決まる）。素材が混在するときは EDL の `output` で決め、他の素材は黒帯つきで縮小される
- 縦型（ショート）にするときは `output` を `{"width": 1080, "height": 1920, "fit": "cover"}` にする。横長の素材は中央が縦に切り抜かれる。話し手が中央にいなければクリップの `center` で切り抜く位置をずらす。👁 境目の画像で顔が切れていないかを見る
- 書き出しは H.264（yuv420p）+ AAC 192kbps、`+faststart`。配信サイト・社内の再生環境のどちらでも再生できる組み合わせ
