"""文字起こしを EDL の出力時間軸に写して字幕（SRT）を作る（E4）。

使い方:
  python make_subs.py edit/transcript.json edit/edl.json --out edit/subs.srt
                      [--max-chars 16] [--punct strip|keep] [--fps 30]

切り取った区間の発話は字幕から消え、残した発話は出力上の時刻に付け替わる。
1枚の字幕は2行まで。句点・疑問符・0.6秒以上の間・文字数の上限・7秒のどれかで区切る。
時間の規則（根拠は references/delivery-specs.md の「字幕」）:
  - 1枚の表示は 5/6 秒以上 7 秒以下。短いものは後ろへ延ばす
  - 次の字幕との隙間は 2 フレーム以上。0.5 秒未満の隙間は 2 フレームまで詰める
  - 語尾の後ろに 0.3 秒の余韻を足す（次の字幕にかからない範囲で）
--punct strip は 。を消し、、を半角スペースにする（Netflix の日本語字幕の流儀）。keep はそのまま。

transcript に単語の時刻が無い（--from-srt で作った）ときは区間単位で写す。半分以上が切られた区間は捨てる。

字幕の文言は文字起こしのままなので、誤変換・固有名詞は E4 でエージェントが SRT を直接直す。
直した後に作り直すと上書きされるので、作り直すときは --out を別名にして差分を移す。

終了コード: 0 書き出した / 2 引数・入力の誤り
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ffutil  # noqa: E402

_CJK = re.compile(r"[぀-ヿ㐀-鿿]")
_END = re.compile(r"[。！？!?]$")


def map_time(t: float, rows: list[dict]) -> float | None:
    for r in rows:
        if r["in"] - 1e-6 <= t <= r["in"] + r["vdur"] + 1e-6:
            return r["t0"] + (t - r["in"])
    return None


def tokens(tr: dict, rows: list[dict]) -> list[dict]:
    toks = []
    has_words = any(s.get("words") for s in tr.get("segments", []))
    for seg in tr.get("segments", []):
        units = seg["words"] if has_words else [{"start": seg["start"], "end": seg["end"], "word": seg["text"]}]
        for w in units:
            if has_words:
                mid = (w["start"] + w["end"]) / 2
                t = map_time(mid, rows)
                if t is None:
                    continue
                d = w["end"] - w["start"]
                toks.append({"start": t - d / 2, "end": t + d / 2, "text": w["word"]})
            else:
                mapped = [(r, max(w["start"], r["in"]), min(w["end"], r["in"] + r["vdur"])) for r in rows]
                mapped = [(r, s, e) for r, s, e in mapped if e > s]
                kept = sum(e - s for _, s, e in mapped)
                if not mapped or kept < (w["end"] - w["start"]) * 0.5:
                    continue
                st = mapped[0][0]["t0"] + mapped[0][1] - mapped[0][0]["in"]
                en = mapped[-1][0]["t0"] + mapped[-1][2] - mapped[-1][0]["in"]
                toks.append({"start": st, "end": en, "text": w["word"], "whole": True})
    toks.sort(key=lambda x: x["start"])
    return toks


def joiner(text: str) -> str:
    return "" if _CJK.search(text) else " "


def clean(text: str, punct: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if punct == "strip":
        text = re.sub(r"。(?=.)", "　", text).rstrip("。")
        text = text.replace("、", " ")
    return text.strip()


def break_lines(text: str, max_chars: float) -> list[str]:
    if ffutil.char_width(text) <= max_chars:
        return [text]
    # 中央に近い区切り（空白・読点の後）を探す。無ければ中央で割る
    half = ffutil.char_width(text) / 2
    best, best_d, acc = None, 1e9, 0.0
    for i, ch in enumerate(text):
        acc += ffutil.char_width(ch)
        if ch in " 　、" and 0 < i < len(text) - 1:
            d = abs(acc - half)
            if d < best_d and acc <= max_chars:
                best, best_d = i + 1, d
    if best is None:
        # 助詞の後ろ（「は」「を」「で」…）で、中央に近いところを探す
        acc = 0.0
        for i, ch in enumerate(text[:-1]):
            acc += ffutil.char_width(ch)
            if ch in "はをがでにのともへや" and acc <= max_chars and abs(acc - half) < best_d \
                    and abs(acc - half) <= half * 0.5:
                best, best_d = i + 1, abs(acc - half)
    if best is None:
        acc = 0.0
        for i, ch in enumerate(text):
            acc += ffutil.char_width(ch)
            if acc >= half:
                best = i + 1
                break
    return [text[:best].strip(), text[best:].strip()]


def group(toks: list[dict], max_width: float, max_dur: float) -> list[dict]:
    caps, cur = [], None
    for t in toks:
        if t.get("whole"):
            if cur:
                caps.append(cur)
                cur = None
            caps.append({"start": t["start"], "end": t["end"], "text": t["text"]})
            continue
        if cur is not None:
            joined = cur["text"] + joiner(cur["text"] + t["text"]) + t["text"].strip()
            if (t["start"] - cur["end"] > 0.6 or ffutil.char_width(joined) > max_width
                    or t["end"] - cur["start"] > max_dur):
                caps.append(cur)
                cur = None
            else:
                cur["text"], cur["end"] = joined, t["end"]
        if cur is None:
            cur = {"start": t["start"], "end": t["end"], "text": t["text"].strip()}
        if _END.search(cur["text"]):
            caps.append(cur)
            cur = None
    if cur:
        caps.append(cur)
    return caps


def time_rules(caps: list[dict], fps: float, total: float) -> None:
    gap = 2 / fps
    for i, c in enumerate(caps):
        nxt = caps[i + 1]["start"] if i + 1 < len(caps) else total
        c["end"] = min(c["end"] + 0.3, nxt - gap)
        if c["end"] - c["start"] < 5 / 6:
            c["end"] = min(c["start"] + 5 / 6, nxt - gap)
        if nxt - c["end"] < 0.5 and i + 1 < len(caps):
            c["end"] = nxt - gap
        c["end"] = min(c["end"], c["start"] + 7.0, total)


def main() -> int:
    ffutil.setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript")
    ap.add_argument("edl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-chars", type=float, default=16, help="1行の上限（全角1・半角0.5）")
    ap.add_argument("--punct", choices=["strip", "keep"], default="strip")
    ap.add_argument("--fps", type=float)
    a = ap.parse_args()
    try:
        tr = json.loads(Path(a.transcript).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        ffutil.die(f"transcript.json を読めない: {e}", 2)
    edl, _ = ffutil.load_edl(a.edl)
    fps = a.fps or (edl.get("output") or {}).get("fps")
    if not fps:
        edl_base = Path(a.edl).resolve().parent
        sp = ffutil.src_path(edl, edl_base, edl["clips"][0]["src"])
        v = ffutil.probe(sp)["video"] if sp.is_file() else None
        fps = round(v["fps"]) if v and v["fps"] else 30
    fps = float(fps)
    rows = ffutil.timeline(edl, fps)
    total = rows[-1]["t0"] + rows[-1]["vdur"]
    caps = group(tokens(tr, rows), a.max_chars * 2, 7.0)
    time_rules(caps, fps, total)
    caps = [c for c in caps if c["end"] - c["start"] > 0.05 and c["text"].strip()]
    out = []
    for i, c in enumerate(caps, 1):
        lines = break_lines(clean(c["text"], a.punct), a.max_chars)
        out.append(f"{i}\n{ffutil.fmt_ts(c['start'])} --> {ffutil.fmt_ts(c['end'])}\n" + "\n".join(lines) + "\n")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(out), encoding="utf-8")
    print(f"書き出し: {a.out}（{len(caps)} 枚、出力の長さ {total:.1f}秒）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
