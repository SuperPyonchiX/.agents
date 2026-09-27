#!/usr/bin/env python3
"""narration.json から、各シーンの開始・中央フレームと動画全体のフレーム数を計算する。

雛形 NarratedVideo.tsx と同じ式（シーン尺 = ceil(秒 × fps) + 余白、最後にクレジット）で計算するので、
検証で `npx remotion still <id> --frame=<中央>` に渡す番号と、書き出した動画の長さの突き合わせに使う。

使い方:
  python scene_frames.py <src/narration.json> [--fps 30] [--tail 6] [--credit 60] [--mp4-seconds 14.77]

  --mp4-seconds  書き出した動画の実測秒数。渡すと計算値と比べ、1フレームを超えてずれたら終了コード 1

終了コード: 0 = 計算した（ずれなし） / 1 = 実測とずれている / 2 = 引数の誤り・マニフェストが読めない
依存: 標準ライブラリのみ
"""
import argparse
import json
import math
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("manifest")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--tail", type=int, default=6)
    p.add_argument("--credit", type=int, default=60)
    p.add_argument("--mp4-seconds", type=lambda v: float(v.strip().rstrip(",")))
    try:
        a = p.parse_args()
        scenes = json.load(open(a.manifest, encoding="utf-8"))["scenes"]
    except SystemExit:
        return 2
    except (OSError, ValueError, KeyError) as e:
        print(f"ERROR  マニフェストが読めない: {e}")
        return 2
    start = 0
    print("id\t開始\t中央\t尺")
    for s in scenes:
        n = math.ceil(s["seconds"] * a.fps) + a.tail
        print(f"{s['id']}\t{start}\t{start + n // 2}\t{n}")
        start += n
    total = start + a.credit
    print(f"credit\t{start}\t{start + a.credit // 2}\t{a.credit}")
    print(f"合計 {total} フレーム = {total / a.fps:.2f} 秒")
    if a.mp4_seconds is not None:
        diff = abs(a.mp4_seconds - total / a.fps)
        if diff > 1.0 / a.fps + 1e-6:
            print(f"NG     実測 {a.mp4_seconds:.3f} 秒と {diff:.3f} 秒ずれている")
            return 1
        print(f"OK     実測 {a.mp4_seconds:.3f} 秒と一致（差 {diff:.3f} 秒）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
