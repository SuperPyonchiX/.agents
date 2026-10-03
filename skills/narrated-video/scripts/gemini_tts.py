#!/usr/bin/env python3
"""Gemini TTS（Interactions API）でシーンごとのナレーション音声（wav）を作り、尺を計ってマニフェストに書く。

voicevox_tts.py と同じ形の narration.json を書くので、後工程（timeline.py・雛形）はエンジンを問わない。

使い方:
  python gemini_tts.py <scenes.json> --out <public/narration> --manifest <src/narration.json>
                       [--only s01,s03] [--model gemini-3.8-flash-tts]

scenes.json の形:
  {
    "engine": "gemini",
    "voice": "Puck",                 # 既定ボイス（references/gemini-tts.md の一覧から選ぶ）
    "style": "明るく元気に、テンポよく",  # 任意。全シーン共通の話し方
    "pauseAfter": 0.3,               # 任意。各シーンの後ろに足す無音の秒数（既定 0.3）
    "scenes": [ {"id": "s01", "text": "読み上げる文（<short pause> などのタグ可）",
                 "subtitle": "字幕に出す文（任意。省略時は text からタグを除いたもの）",
                 "style": "ここだけ驚いた感じで（任意。共通の style を上書き）"}, ... ]
  }

出力:
  <out>/<id>.wav    シーンごとの音声（24kHz・モノラル・16bit）
  <manifest>        {"credit": "", "speaker": {"engine": "gemini", "model", "voice"},
                     "scenes": [{"id", "text", "subtitle", "file", "seconds"}], "total_seconds": ..}

API キーは環境変数 GEMINI_API_KEY（無ければ GOOGLE_API_KEY）から読む。台本の文章は Google に送られる。

終了コード: 0 = 作った / 1 = API キーが無い・認証に失敗 / 2 = 引数・入力の誤り / 3 = 合成に失敗
依存: 標準ライブラリのみ
"""
import argparse
import base64
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import wave

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
RATE = 24000
TAG = re.compile(r"<[^<>]{1,30}>|\|[^|]{1,30}\|")


class AuthError(Exception):
    pass


class SynthError(Exception):
    pass


def request(key, model, voice, text, style, retries=4):
    content = {"type": "text", "text": text}
    if style:
        content["annotations"] = [{"type": "speech_metadata", "style": style}]
    body = {
        "model": model,
        "input": [{"type": "user_input", "content": [content]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }
    data = json.dumps(body).encode("utf-8")
    wait = 5
    for attempt in range(retries + 1):
        req = urllib.request.Request(ENDPOINT, data=data, method="POST", headers={
            "x-goog-api-key": key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            if e.code in (401, 403):
                raise AuthError(f"HTTP {e.code}: {detail}")
            if e.code in (429, 500, 503) and attempt < retries:
                print(f"WAIT   HTTP {e.code}。{wait} 秒待って再試行する")
                time.sleep(wait)
                wait *= 2
                continue
            raise SynthError(f"HTTP {e.code}: {detail}")
        except urllib.error.URLError as e:
            raise SynthError(str(e))
    raise SynthError("再試行の上限に達した")


def extract_audio(resp):
    audio = None
    for step in resp.get("steps", []):
        if step.get("type") != "model_output":
            continue
        for c in step.get("content", []):
            if c.get("type") == "audio" and c.get("data"):
                audio = c
    if audio is None:
        raise SynthError("応答に音声が無い: " + json.dumps(resp, ensure_ascii=False)[:300])
    raw = base64.b64decode(audio["data"])
    if raw[:4] == b"RIFF":
        with wave.open(io.BytesIO(raw), "rb") as w:
            return w.readframes(w.getnframes()), w.getframerate(), w.getnchannels(), w.getsampwidth()
    return raw, int(audio.get("sample_rate") or RATE), 1, 2  # ヘッダなしの L16


def write_wav(path, pcm, rate, channels, width, pause):
    pad = b"\x00" * (int(rate * pause) * channels * width)
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm + pad)
    return (len(pcm) + len(pad)) / float(rate * channels * width)


def rel_to_public(path):
    norm = os.path.abspath(path).replace("\\", "/")
    marker = "/public/"
    i = norm.rfind(marker)
    return norm[i + len(marker):] if i >= 0 else os.path.basename(norm)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("scenes")
    p.add_argument("--out", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--only")
    p.add_argument("--model", default="gemini-3.8-flash-tts")
    try:
        a = p.parse_args()
    except SystemExit:
        return 2

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        print("ERROR  環境変数 GEMINI_API_KEY が無い。references/gemini-tts.md の「API キー」に従って設定する")
        return 1
    try:
        cfg = json.load(open(a.scenes, encoding="utf-8"))
        voice = str(cfg["voice"])
        scenes = cfg["scenes"]
        ids = [s["id"] for s in scenes]
        assert all(str(s.get("text", "")).strip() for s in scenes), "text が空のシーンがある"
        assert len(ids) == len(set(ids)), "id が重複している"
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as e:
        print(f"ERROR  scenes.json が読めない: {e}")
        return 2
    pause = float(cfg.get("pauseAfter", 0.3))
    common_style = cfg.get("style", "")

    only = set(a.only.split(",")) if a.only else None
    if only and not only <= set(ids):
        print(f"ERROR  --only に scenes.json に無い id がある: {sorted(only - set(ids))}")
        return 2
    old = {}
    if only and os.path.isfile(a.manifest):
        old = {s["id"]: s for s in json.load(open(a.manifest, encoding="utf-8")).get("scenes", [])}

    os.makedirs(a.out, exist_ok=True)
    rows = []
    for s in scenes:
        subtitle = s.get("subtitle") or re.sub(r"\s+", " ", TAG.sub("", s["text"])).strip()
        wav_path = os.path.join(a.out, f"{s['id']}.wav")
        if only is not None and s["id"] not in only and s["id"] in old and os.path.isfile(wav_path):
            rows.append(dict(old[s["id"]], subtitle=subtitle))
            continue
        style = s.get("style") or common_style
        try:
            pcm, rate, ch, width = extract_audio(request(key, a.model, s.get("voice", voice), s["text"], style))
        except AuthError as e:
            print(f"ERROR  認証に失敗（API キーを確かめる）: {e}")
            return 1
        except SynthError as e:
            print(f"ERROR  {s['id']} の合成に失敗: {e}")
            return 3
        sec = round(write_wav(wav_path, pcm, rate, ch, width, pause), 3)
        rows.append({"id": s["id"], "text": s["text"], "subtitle": subtitle,
                     "file": rel_to_public(wav_path), "seconds": sec})
        print(f"OK     {s['id']}  {sec:6.2f} 秒  {s['text'][:30]}")

    manifest = {
        "credit": "",
        "speaker": {"engine": "gemini", "model": a.model, "voice": voice},
        "scenes": rows,
        "total_seconds": round(sum(r["seconds"] for r in rows), 3),
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.manifest)), exist_ok=True)
    with open(a.manifest, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"合計 {manifest['total_seconds']:.2f} 秒 / {len(rows)} シーン / モデル {a.model} / ボイス {voice}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
