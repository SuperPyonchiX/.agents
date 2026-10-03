# Gemini TTS の準備と台本の書き方

N0 で音声エンジンに Gemini を選んだとき、N1 で台本を書く前に読む。

## API キー

`gemini_tts.py` は環境変数 `GEMINI_API_KEY`（無ければ `GOOGLE_API_KEY`）を読む。キーは会話に貼らせない。

1. Google AI Studio（https://aistudio.google.com/apikey）で API キーを作る
2. ユーザー環境変数に入れる。PowerShell なら `[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "<キー>", "User")`
3. 環境変数は Claude Code を起動し直すまで反映されない

**キーの取得と設定はユーザーにやってもらう。** エージェントはキーの値を聞かない・表示しない。

## 料金（2026-10 時点。公開前に https://ai.google.dev/gemini-api/docs/pricing で確かめる）

| モデル | 無料枠 | 有料（100万トークンあたり） |
|---|---|---|
| `gemini-3.8-flash-tts`（既定） | あり | 入力 $0.50・音声出力 $9.00（2027-01-01 から $1.00・$18.00） |
| `gemini-3.8-flash-lite-tts` | あり | 入力 $0.50・音声出力 $6.00（2027-01-01 から倍） |

- 無料枠は回数制限（RPM・1日の上限）がある。シーン数が多いと 429 が返る。スクリプトは 429 のとき待って再試行する
- Google AI Pro の契約者は、Google Developer Program の特典で毎月 $10 の Cloud クレジットを受け取れる（自動ではない。google.dev で「Activate Developer Benefits」を押し、Cloud プロジェクトを選ぶ必要がある）。Gemini アプリの契約そのものでは API は無料にならない
- 無料枠で送った内容は Google のサービス改善に使われることがある。**社外秘の台本は Gemini に送らず VOICEVOX にする**

## ボイスの選び方

`voice` に名前を書く。全30種。話し方の性格は名前ごとに決まっていて、日本語でもそのまま使える。

| 向いている動画 | 候補 |
|---|---|
| 告知・CM（テンション高め） | Puck（Upbeat）、Fenrir（Excitable）、Zephyr（Bright） |
| 解説（聞き取りやすさ優先） | Charon（Informative）、Kore（Firm）、Achird（Friendly） |
| 落ち着いた語り | Sulafat（Warm）、Zubenelgenubi（Casual）、Leda（Youthful） |

全30種: Zephyr, Puck, Charon, Kore, Fenrir, Leda, Orus, Aoede, Callirrhoe, Autonoe, Enceladus, Iapetus, Umbriel, Algieba, Despina, Erinome, Algenib, Rasalgethi, Laomedeia, Achernar, Alnilam, Schedar, Gacrux, Pulcherrima, Achird, Zubenelgenubi, Vindemiatrix, Sadachbia, Sadaltager, Sulafat

ユーザーが指定しなければ、動画の種類に合う候補を2〜3個挙げ、1シーンだけ試しに作って聞いてもらってから決める（`--only s01`）。

## 台本の書き方

VOICEVOX と違い、漢字かな混じりのままでよい。英単語も概ね読める。読み間違えたシーンだけ仮名に直す。

| 書くもの | ルール |
|---|---|
| `style`（全体） | 話し方を日本語の短い指示で書く。例「明るく元気に、テンポよく」「落ち着いた解説口調で」 |
| `style`（シーン） | そのシーンだけ変えたいとき。例「ここは驚いた感じで」「ささやくように」。全シーンに付けない（声の性格がぶれる） |
| `text` | 読み上げる文。間や息は `<short pause>` `<long pause>` `<breath>` `<laugh>` `<sigh>` で入れられる |
| `subtitle` | 省略すると `text` から `<...>` のタグを除いたものになる |

- 告知・CM は1シーン1文・5秒以内に収める。ビートに合わせるので、長い文は拍の途中で切れて見える
- テンションを上げたいときは `style` で指示する。`text` に「！」を重ねても効きは弱い
- 同じ文でも生成のたびに抑揚が変わる。気に入らないシーンは `--only` で作り直せばよい
