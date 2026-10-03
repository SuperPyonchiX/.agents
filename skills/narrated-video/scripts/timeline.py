#!/usr/bin/env python3
"""narration.json からシーンの開始・尺を決めて timeline.json に書く。ビートに合わせる場合は拍の格子も出し、BGM も作る。

雛形 NarratedVideo.tsx は timeline.json だけを見て並べる。尺を決める式はこのスクリプトにしか無い。

使い方:
  作る:   python timeline.py <src/narration.json> --out <src/timeline.json>
                             [--fps 30] [--tail 6] [--credit auto|<フレーム数>]
                             [--bpm 120 [--snap beat|bar] [--beats-per-bar 4]
                              [--pattern four|half|break] [--bgm public/bgm/beat.wav]]
  確かめる: python timeline.py --check <src/timeline.json> --mp4-seconds <書き出した動画の秒数>

  尺の式    --bpm なし: ceil(秒 × fps) + tail
            --bpm あり: 上の値を拍（--snap beat）か小節（bar）の長さで切り上げ、開始を拍の頭にそろえる
  --credit  auto は narration.json の credit が空なら 0、あれば 60 フレーム
  --bgm     指定すると --pattern のドラムを動画の長さぶん合成して書く。手持ちの曲を使うなら指定せず、
            その曲の BPM を --bpm に渡す（timeline.json の bgm は null になるので雛形の BGM_FILE に書く）

timeline.json: {"fps", "bpm", "beatsPerBar", "totalFrames", "credit", "creditFrames", "bgm",
                "beats": [{"frame", "downbeat"}], "scenes": [{"id", "subtitle", "file", "from", "duration"}]}

終了コード: 0 = 作った・ずれなし / 1 = 実測とずれている（--check） / 2 = 引数の誤り・入力が読めない
依存: 標準ライブラリのみ
"""
import argparse
import array
import json
import math
import os
import random
import sys
import wave

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SR = 44100
# 1小節を16分音符16個で表す。K=キック S=スネア H=ハイハット
PATTERNS = {
    "four":  {"K": [0, 4, 8, 12], "S": [4, 12], "H": [2, 6, 10, 14]},
    "half":  {"K": [0, 10], "S": [8], "H": [0, 2, 4, 6, 8, 10, 12, 14]},
    "break": {"K": [0, 6, 10], "S": [4, 12], "H": [0, 2, 4, 6, 8, 10, 11, 12, 14]},
}


def kick():
    n = int(SR * 0.35)
    out, ph = [], 0.0
    for i in range(n):
        t = i / SR
        f = 45 + 110 * math.exp(-t * 30)
        ph += 2 * math.pi * f / SR
        out.append(math.sin(ph) * math.exp(-t * 9))
    return out


def snare(rng):
    n = int(SR * 0.22)
    return [(0.6 * rng.uniform(-1, 1) + 0.4 * math.sin(2 * math.pi * 190 * i / SR)) * math.exp(-i / SR * 22)
            for i in range(n)]


def hat(rng):
    n = int(SR * 0.05)
    prev, out = 0.0, []
    for i in range(n):
        x = rng.uniform(-1, 1)
        out.append((x - prev) * 0.5 * math.exp(-i / SR * 70))  # 差分で低域を落とす
        prev = x
    return out


def synth_bgm(path, bpm, pattern, seconds):
    rng = random.Random(0)
    voices = {"K": (kick(), 1.0), "S": (snare(rng), 0.55), "H": (hat(rng), 0.3)}
    n = int(SR * seconds)
    buf = array.array("f", bytes(4 * n))
    step = 60.0 / bpm / 4
    bar = 0
    while bar * 16 * step < seconds:
        for name, steps in PATTERNS[pattern].items():
            samples, gain = voices[name]
            for st in steps:
                start = int((bar * 16 + st) * step * SR)
                for j, v in enumerate(samples[: max(0, n - start)]):
                    buf[start + j] += v * gain
        bar += 1
    fade = min(n, SR)
    for i in range(fade):
        buf[n - fade + i] *= 1 - i / fade
    peak = max((abs(v) for v in buf), default=1.0) or 1.0
    pcm = array.array("h", (int(v / peak * 0.8 * 32767) for v in buf))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def rel_to_public(path):
    norm = os.path.abspath(path).replace("\\", "/")
    i = norm.rfind("/public/")
    return norm[i + len("/public/"):] if i >= 0 else os.path.basename(norm)


def build(a):
    try:
        nar = json.load(open(a.manifest, encoding="utf-8"))
        rows = nar["scenes"]
    except (OSError, ValueError, KeyError) as e:
        print(f"ERROR  マニフェストが読めない: {e}")
        return 2
    credit = nar.get("credit", "")
    credit_frames = (60 if credit else 0) if a.credit == "auto" else int(a.credit)
    if a.bpm is not None and a.bpm <= 0:
        print("ERROR  --bpm は正の数にする")
        return 2

    scenes, cursor = [], 0
    if a.bpm:
        beat = a.fps * 60.0 / a.bpm
        unit = beat * (a.beats_per_bar if a.snap == "bar" else 1)
        units = 0
        for r in rows:
            n = math.ceil((math.ceil(r["seconds"] * a.fps) + a.tail) / unit)
            start, end = round(units * unit), round((units + n) * unit)
            scenes.append({"id": r["id"], "subtitle": r["subtitle"], "file": r["file"],
                           "from": start, "duration": end - start})
            units += n
        cursor = round(units * unit)
    else:
        for r in rows:
            n = math.ceil(r["seconds"] * a.fps) + a.tail
            scenes.append({"id": r["id"], "subtitle": r["subtitle"], "file": r["file"],
                           "from": cursor, "duration": n})
            cursor += n
    total = cursor + credit_frames

    beats = []
    if a.bpm:
        i = 0
        while round(i * beat) < total:
            beats.append({"frame": round(i * beat), "downbeat": i % a.beats_per_bar == 0})
            i += 1
    bgm = None
    if a.bgm:
        if not a.bpm:
            print("ERROR  --bgm には --bpm が要る")
            return 2
        synth_bgm(a.bgm, a.bpm, a.pattern, total / a.fps)
        bgm = rel_to_public(a.bgm)

    out = {"fps": a.fps, "bpm": a.bpm, "beatsPerBar": a.beats_per_bar, "totalFrames": total,
           "credit": credit, "creditFrames": credit_frames, "bgm": bgm, "beats": beats, "scenes": scenes}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("id\t開始\t中央\t尺")
    for s in scenes:
        print(f"{s['id']}\t{s['from']}\t{s['from'] + s['duration'] // 2}\t{s['duration']}")
    if credit_frames:
        print(f"credit\t{cursor}\t{cursor + credit_frames // 2}\t{credit_frames}")
    extra = f" / {a.bpm} BPM・{len(beats)} 拍" if a.bpm else ""
    extra += f" / BGM {a.bgm}（{a.pattern}）" if bgm else ""
    print(f"合計 {total} フレーム = {total / a.fps:.2f} 秒{extra}")
    return 0


def check(a):
    try:
        tl = json.load(open(a.check, encoding="utf-8"))
        total, fps = tl["totalFrames"], tl["fps"]
    except (OSError, ValueError, KeyError) as e:
        print(f"ERROR  timeline.json が読めない: {e}")
        return 2
    if a.mp4_seconds is None:
        print("ERROR  --check には --mp4-seconds が要る")
        return 2
    diff = abs(a.mp4_seconds - total / fps)
    if diff > 1.0 / fps + 1e-6:
        print(f"NG     実測 {a.mp4_seconds:.3f} 秒と計算 {total / fps:.3f} 秒が {diff:.3f} 秒ずれている")
        return 1
    print(f"OK     実測 {a.mp4_seconds:.3f} 秒と一致（差 {diff:.3f} 秒）")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("manifest", nargs="?")
    p.add_argument("--out")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--tail", type=int, default=6)
    p.add_argument("--credit", default="auto")
    p.add_argument("--bpm", type=float)
    p.add_argument("--snap", choices=["beat", "bar"], default="beat")
    p.add_argument("--beats-per-bar", type=int, default=4)
    p.add_argument("--pattern", choices=sorted(PATTERNS), default="four")
    p.add_argument("--bgm")
    p.add_argument("--check")
    p.add_argument("--mp4-seconds", type=lambda v: float(v.strip().rstrip(",")))
    try:
        a = p.parse_args()
    except SystemExit:
        return 2
    if a.check:
        return check(a)
    if not (a.manifest and a.out):
        print("ERROR  narration.json と --out を指定する（確かめるだけなら --check）")
        return 2
    if a.credit != "auto" and not a.credit.isdigit():
        print("ERROR  --credit は auto かフレーム数")
        return 2
    return build(a)


if __name__ == "__main__":
    sys.exit(main())
