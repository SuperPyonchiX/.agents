"""素材を測って analysis.json に書く（E1）。

使い方:
  python analyze.py <素材> [<素材> ...] --out edit/analysis.json
                    [--noise -35] [--min-silence 0.4] [--scene 0.35] [--no-scene]

素材ごとに、長さ・解像度・fps・音声の有無、無音区間（silencedetect）、発話区間（無音の補集合）、
画の切り替わり（scdet）、積算ラウドネスと True Peak を測る。

--noise は無音とみなす音量（dBFS）。屋外や空調の音が大きい素材は -30 前後に上げる。
--min-silence はこの秒数以上続いたものだけを無音とする。

終了コード: 0 測れた / 2 引数・素材の誤り、ffmpeg が無い / 3 ffmpeg が失敗した
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ffutil  # noqa: E402


def scene_changes(path: str, threshold: float) -> list[float]:
    p = ffutil.run_ok(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-an",
                    "-vf", f"scale=320:-2,scdet=threshold={threshold * 100:g}", "-f", "null", "-"])
    times = []
    for line in p.stderr.splitlines():
        m = re.search(r"lavfi\.scd\.time:\s*([\d.]+)", line)
        if m:
            times.append(round(float(m.group(1)), 3))
    return times


def speech_from_silence(silences: list[list[float]], total: float) -> list[list[float]]:
    speech, t = [], 0.0
    for s, e in silences:
        if s - t > 0.05:
            speech.append([round(t, 3), round(s, 3)])
        t = max(t, e)
    if total - t > 0.05:
        speech.append([round(t, 3), round(total, 3)])
    return speech


def main() -> int:
    ffutil.setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--noise", type=float, default=-35.0)
    ap.add_argument("--min-silence", type=float, default=0.4)
    ap.add_argument("--scene", type=float, default=0.35, help="画の切り替わりの閾値 0〜1")
    ap.add_argument("--no-scene", action="store_true", help="画の切り替わりを測らない（長い素材で時間を節約）")
    a = ap.parse_args()
    ffutil.require_ffmpeg()

    result = {"params": {"noise_db": a.noise, "min_silence": a.min_silence, "scene": a.scene},
              "sources": []}
    for src in a.sources:
        if not Path(src).is_file():
            ffutil.die(f"素材が無い: {src}", 2)
        info = ffutil.probe(src)
        total = info["duration"]
        entry = dict(info)
        if info["audio"]:
            entry["silences"] = ffutil.detect_silence(src, a.noise, a.min_silence, total)
            entry["speech"] = speech_from_silence(entry["silences"], total)
            entry["loudness"] = ffutil.measure_loudness(src)
        else:
            entry["silences"], entry["speech"], entry["loudness"] = [], [], None
        entry["scene_changes"] = scene_changes(src, a.scene) if info["video"] and not a.no_scene else []
        sil_total = sum(e - s for s, e in entry["silences"])
        entry["silence_ratio"] = round(sil_total / total, 3) if total else 0.0
        result["sources"].append(entry)
        v = info["video"] or {}
        loud = entry["loudness"] or {}
        print(f"{src}: {total:.1f}秒 {v.get('width', '-')}x{v.get('height', '-')} {v.get('fps', '-')}fps "
              f"発話区間 {len(entry['speech'])} 個 / 無音 {entry['silence_ratio'] * 100:.0f}% / "
              f"画の切り替わり {len(entry['scene_changes'])} 回 / "
              f"{loud.get('lufs')} LUFS, TP {loud.get('true_peak')} dBTP")
    ffutil.write_json(a.out, result)
    print(f"書き出し: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
