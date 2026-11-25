"""発話を文字起こしして transcript.json に書く（E2）。

使い方:
  python transcribe.py <素材> --out edit/transcript.json [--model small] [--language ja] [--device auto]
  python transcribe.py <素材> --out edit/transcript.json --from-srt <既存の字幕.srt>

既定は faster-whisper（外部パッケージ。`pip install faster-whisper`）で単語ごとの時刻まで取る。
初回はモデルを Hugging Face から取得するので通信が要る。社外秘の素材でも音声は外に出ない（ローカル推論）。
--from-srt は、YouTube の自動字幕などの既存 SRT を同じ形に直すだけで、faster-whisper を使わない。
このとき単語の時刻は無いので、フィラーの自動カットは使えない。

出力の形:
  {"source": "...", "language": "ja", "engine": "faster-whisper:small",
   "segments": [{"start": 1.2, "end": 3.4, "text": "...",
                 "words": [{"start": 1.2, "end": 1.5, "word": "えー"}, ...]}]}

終了コード: 0 書き出した / 2 引数の誤り、faster-whisper が無い / 3 文字起こしに失敗した
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ffutil  # noqa: E402


def from_srt(src: str, srt: str) -> dict:
    try:
        text = Path(srt).read_text(encoding="utf-8-sig")
    except OSError as e:
        ffutil.die(f"SRT を読めない: {e}", 2)
    segs = [{"start": round(i["start"], 3), "end": round(i["end"], 3),
             "text": "".join(i["lines"]), "words": []} for i in ffutil.parse_srt(text)]
    if not segs:
        ffutil.die("SRT に字幕が1件も無い", 2)
    return {"source": src, "language": None, "engine": "srt", "segments": segs}


def with_whisper(src: str, model: str, language: str | None, device: str) -> dict:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        print("ERROR: faster-whisper が無い。`pip install faster-whisper` で入れる。"
              "入れられない環境では --from-srt で既存の字幕を使うか、文字起こし無し（E2 を飛ばす）で進める。",
              file=sys.stderr)
        sys.exit(2)
    try:
        wm = WhisperModel(model, device=device, compute_type="default")
        segments, info = wm.transcribe(src, language=language, word_timestamps=True,
                                       vad_filter=True, condition_on_previous_text=False)
        segs = []
        for s in segments:
            words = [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word}
                     for w in (s.words or [])]
            segs.append({"start": round(s.start, 3), "end": round(s.end, 3),
                         "text": s.text.strip(), "words": words})
    except Exception as e:  # モデルの取得失敗・デコード失敗をまとめて扱う
        ffutil.die(f"文字起こしに失敗した: {e}", 3)
    return {"source": src, "language": info.language, "engine": f"faster-whisper:{model}",
            "segments": segs}


def main() -> int:
    ffutil.setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="small", help="tiny/base/small/medium/large-v3。精度が要るなら large-v3")
    ap.add_argument("--language", default="ja")
    ap.add_argument("--device", default="auto", help="auto/cpu/cuda")
    ap.add_argument("--from-srt")
    a = ap.parse_args()
    if not Path(a.source).is_file():
        ffutil.die(f"素材が無い: {a.source}", 2)
    data = from_srt(a.source, a.from_srt) if a.from_srt else \
        with_whisper(a.source, a.model, a.language or None, a.device)
    ffutil.write_json(a.out, data)
    n_words = sum(len(s["words"]) for s in data["segments"])
    print(f"書き出し: {a.out}（{len(data['segments'])} 区間、単語の時刻 {n_words} 個）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
