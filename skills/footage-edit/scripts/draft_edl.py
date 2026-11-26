"""analysis.json（と transcript.json）から、無音とフィラーを切った EDL の下書きを作る（E3 の土台）。

使い方:
  python draft_edl.py edit/analysis.json --out edit/edl.json [--source 0]
                      [--transcript edit/transcript.json] [--fillers えー,えっと,あのー,...]
                      [--pad-in 0.15] [--pad-out 0.25] [--merge-gap 0.35] [--min-clip 0.5]
                      [--punch-in 1.12] [--target youtube] [--fps 30]

規則（根拠は references/editing-principles.md の「無音とフィラー」）:
  - 発話区間の前に --pad-in、後ろに --pad-out 秒を残す（息継ぎと語尾の余韻を切らない）
  - 残す区間どうしの隙間が --merge-gap 秒未満ならつなげる（細切れのカットは不自然な詰め方になる）
  - transcript に単語の時刻があれば、--fillers に一致する単語を切り取る
  - --min-clip 秒未満になった区間は捨てる
  - 同じ素材のクリップが続く境目（ジャンプカット）では、--punch-in の倍率と等倍を交互に当てる。
    0 または 1 を渡すと当てない

出力は references/edl-format.md の形。これは下書きで、フックの並べ替え・B ロール・削る話題の判断は
エージェントが E3 で行う。

終了コード: 0 書き出した / 2 引数・入力の誤り
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ffutil  # noqa: E402

DEFAULT_FILLERS = "えー,えーと,えっと,えーっと,あー,あのー,そのー,うーん,んー"
_PUNCT = re.compile(r"[\s、。,.!?！？「」…]+$|^[\s、。,.!?！？「」…]+")


def norm_word(w: str) -> str:
    return _PUNCT.sub("", w.strip())


def subtract(intervals: list[list[float]], cuts: list[list[float]]) -> list[list[float]]:
    out = []
    for s, e in intervals:
        pieces = [[s, e]]
        for cs, ce in cuts:
            nxt = []
            for ps, pe in pieces:
                if ce <= ps or cs >= pe:
                    nxt.append([ps, pe])
                    continue
                if cs > ps:
                    nxt.append([ps, cs])
                if ce < pe:
                    nxt.append([ce, pe])
            pieces = nxt
        out.extend(pieces)
    return out


def main() -> int:
    ffutil.setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("analysis")
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", type=int, default=0, help="analysis.json の何番目の素材を主素材にするか")
    ap.add_argument("--transcript")
    ap.add_argument("--fillers", default=DEFAULT_FILLERS)
    ap.add_argument("--pad-in", type=float, default=0.15)
    ap.add_argument("--pad-out", type=float, default=0.25)
    ap.add_argument("--merge-gap", type=float, default=0.35)
    ap.add_argument("--min-clip", type=float, default=0.5)
    ap.add_argument("--punch-in", type=float, default=1.12)
    ap.add_argument("--target", default="youtube", choices=sorted(ffutil.TARGETS))
    ap.add_argument("--fps", type=float)
    a = ap.parse_args()

    try:
        ana = json.loads(Path(a.analysis).read_text(encoding="utf-8"))
        src = ana["sources"][a.source]
    except (OSError, json.JSONDecodeError, KeyError, IndexError) as e:
        ffutil.die(f"analysis.json を読めない、または --source が範囲外: {e}", 2)
    total = src["duration"]
    if not src.get("audio"):
        ffutil.die("主素材に音声が無いので無音で切れない。EDL は手で書く（references/edl-format.md）", 2)

    keep = []
    for s, e in src["speech"]:
        s2, e2 = max(0.0, s - a.pad_in), min(total, e + a.pad_out)
        if keep and s2 - keep[-1][1] < a.merge_gap:
            keep[-1][1] = max(keep[-1][1], e2)
        else:
            keep.append([s2, e2])

    filler_cuts = []
    if a.transcript:
        try:
            tr = json.loads(Path(a.transcript).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            ffutil.die(f"transcript.json を読めない: {e}", 2)
        fillers = {f.strip() for f in a.fillers.split(",") if f.strip()}
        for seg in tr.get("segments", []):
            for w in seg.get("words") or []:
                if norm_word(w["word"]) in fillers and w["end"] - w["start"] >= 0.12:
                    filler_cuts.append([w["start"] + 0.02, w["end"] - 0.02])
        if not any(seg.get("words") for seg in tr.get("segments", [])):
            print("注意: transcript に単語の時刻が無いので、フィラーは切っていない")
    pieces = subtract(keep, filler_cuts)
    pieces = [p for p in pieces if p[1] - p[0] >= a.min_clip]
    if not pieces:
        ffutil.die("残す区間が0個になった。--noise を上げて analyze.py をやり直すか、--min-clip を下げる", 2)

    out_dir = Path(a.out).resolve().parent
    rel = os.path.relpath(Path(src["path"]).resolve(), out_dir).replace("\\", "/")
    fps = a.fps or (round(src["video"]["fps"]) if src.get("video") else 30)
    clips, zoom_on = [], False
    for i, (s, e) in enumerate(pieces):
        jump = i > 0 and s - pieces[i - 1][1] > 0.001
        if jump and a.punch_in and a.punch_in > 1.0:
            zoom_on = not zoom_on
        clip = {"id": f"c{i + 1:03d}", "src": "main", "in": round(s, 3), "out": round(e, 3),
                "note": ""}
        if zoom_on and a.punch_in > 1.0:
            clip["zoom"] = a.punch_in
        clips.append(clip)
    edl = {"version": 1, "target": a.target,
           "output": {"fps": fps},
           "sources": {"main": rel},
           "clips": clips, "overlays": [], "subtitles": None, "burn_subtitles": False, "music": None}
    ffutil.write_json(a.out, edl)
    kept = sum(e - s for s, e in pieces)
    print(f"書き出し: {a.out}")
    print(f"クリップ {len(clips)} 個、残した長さ {kept:.1f}秒 / 元 {total:.1f}秒（{kept / total * 100:.0f}%）、"
          f"フィラー {len(filler_cuts)} 箇所を切った")
    return 0


if __name__ == "__main__":
    sys.exit(main())
