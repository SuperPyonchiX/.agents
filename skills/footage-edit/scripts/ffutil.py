"""footage-edit のスクリプトが共通で使う内部モジュール。単体では実行しない。

ffmpeg / ffprobe の呼び出し、EDL の読み込みと検証、時間の丸めをまとめる。
標準ライブラリのみ。ffmpeg と ffprobe は PATH 上にあること（無ければ終了コード 2）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 配信先ごとの音量の目標。出典は references/delivery-specs.md
TARGETS = {
    "youtube": {"lufs": -14.0, "tp": -1.0, "tol": 1.0},
    "podcast": {"lufs": -16.0, "tp": -1.0, "tol": 1.0},
    "broadcast": {"lufs": -23.0, "tp": -1.0, "tol": 1.0},
    "internal": {"lufs": -16.0, "tp": -1.0, "tol": 1.5},
}


def die(msg: str, code: int) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            die(f"{tool} が見つからない。ffmpeg を導入して PATH に通す"
                "（Windows: winget install Gyan.FFmpeg / macOS: brew install ffmpeg / "
                "Ubuntu: sudo apt install ffmpeg）", 2)


def run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def run_ok(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    p = run(cmd, cwd)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-15:])
        die(f"ffmpeg が失敗した: {' '.join(cmd[:6])} ...\n{tail}", 3)
    return p


def probe(path: str | Path) -> dict:
    p = run(["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)])
    if p.returncode != 0:
        die(f"素材を読めない: {path}\n{p.stderr.strip()[-500:]}", 2)
    info = json.loads(p.stdout)
    out = {"path": str(path), "duration": float(info["format"].get("duration", 0.0)),
           "video": None, "audio": None}
    for s in info.get("streams", []):
        if s.get("codec_type") == "video" and out["video"] is None \
                and s.get("disposition", {}).get("attached_pic", 0) == 0:
            fr = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1"
            num, _, den = fr.partition("/")
            fps = float(num) / float(den or 1) if float(den or 1) else 0.0
            out["video"] = {"width": int(s.get("width", 0)), "height": int(s.get("height", 0)),
                            "fps": round(fps, 3), "codec": s.get("codec_name")}
        elif s.get("codec_type") == "audio" and out["audio"] is None:
            out["audio"] = {"sample_rate": int(s.get("sample_rate", 0)),
                            "channels": int(s.get("channels", 0)), "codec": s.get("codec_name")}
    return out


_SIL_START = re.compile(r"silence_start: (-?[\d.]+)")
_SIL_END = re.compile(r"silence_end: (-?[\d.]+)")


def detect_silence(path: str, noise_db: float, min_dur: float, total: float) -> list[list[float]]:
    p = run_ok(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
                "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"])
    sil, start = [], None
    for line in p.stderr.splitlines():
        m = _SIL_START.search(line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = _SIL_END.search(line)
        if m and start is not None:
            sil.append([round(start, 3), round(float(m.group(1)), 3)])
            start = None
    if start is not None:
        sil.append([round(start, 3), round(total, 3)])
    return sil


def measure_loudness(path: str, af_prefix: str = "") -> dict:
    """ITU-R BS.1770 の積算ラウドネスと True Peak を ebur128 で測る。"""
    af = (af_prefix + "," if af_prefix else "") + "ebur128=peak=true"
    p = run_ok(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", af, "-f", "null", "-"])
    text = p.stderr
    summary = text[text.rfind("Summary:"):] if "Summary:" in text else ""
    def grab(pat: str) -> float | None:
        m = re.search(pat, summary)
        return float(m.group(1)) if m else None
    return {"lufs": grab(r"I:\s+(-?[\d.]+|-inf) LUFS") if "-inf" not in summary else None,
            "lra": grab(r"LRA:\s+(-?[\d.]+) LU"),
            "true_peak": grab(r"Peak:\s+(-?[\d.]+) dBFS")}


def load_edl(path: str | Path) -> tuple[dict, Path]:
    path = Path(path)
    try:
        edl = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        die(f"EDL を読めない: {path}: {e}", 2)
    base = path.resolve().parent
    for key in ("sources", "clips"):
        if key not in edl:
            die(f"EDL に {key} が無い（形式は references/edl-format.md）", 2)
    return edl, base


def src_path(edl: dict, base: Path, key: str) -> Path:
    if key not in edl["sources"]:
        die(f"sources に無い素材キー: {key}", 2)
    p = Path(edl["sources"][key])
    return p if p.is_absolute() else base / p


def out_spec(edl: dict, first_video: dict | None) -> dict:
    o = dict(edl.get("output") or {})
    if first_video:
        o.setdefault("width", first_video["width"])
        o.setdefault("height", first_video["height"])
        o.setdefault("fps", round(first_video["fps"]) or 30)
    o.setdefault("width", 1920)
    o.setdefault("height", 1080)
    o.setdefault("fps", 30)
    o["width"] -= o["width"] % 2
    o["height"] -= o["height"] % 2
    return o


def timeline(edl: dict, fps: float) -> list[dict]:
    """クリップを出力の時間軸に並べる。映像の尺はフレームに丸め、音声は J/L カットでずらす。

    返す各要素: id, src, in, frames, vdur, t0（出力上の開始秒）, a_in, a_dur
    audio_shift はそのクリップの開始の境目を音声だけ動かす秒数（負: J カット、正: L カット）。
    """
    clips = edl["clips"]
    if not clips:
        die("clips が空", 2)
    rows, t = [], 0.0
    shifts = [0.0] + [float(c.get("audio_shift", 0.0)) for c in clips[1:]] + [0.0]
    for i, c in enumerate(clips):
        try:
            cin, cout = float(c["in"]), float(c["out"])
        except (KeyError, TypeError, ValueError):
            die(f"クリップ {c.get('id', i)} の in/out が無いか数値でない", 2)
        if cout <= cin:
            die(f"クリップ {c.get('id', i)} は out <= in", 2)
        frames = max(1, round((cout - cin) * fps))
        vdur = frames / fps
        a_in = cin + shifts[i]
        a_dur = vdur + shifts[i + 1] - shifts[i]
        if a_dur <= 0:
            die(f"クリップ {c.get('id', i)} の audio_shift が大きすぎて音声の長さが 0 以下", 2)
        rows.append({"id": c.get("id", f"c{i + 1:02d}"), "src": c["src"], "in": cin,
                     "frames": frames, "vdur": vdur, "t0": t, "a_in": a_in, "a_dur": a_dur,
                     "zoom": float(c.get("zoom", 1.0)), "center": c.get("center", [0.5, 0.5])})
        t += vdur
    return rows


def overlay_rows(edl: dict, rows: list[dict]) -> list[dict]:
    """overlays（B ロール）を出力の時間軸の秒に直す。"""
    by_id = {r["id"]: r for r in rows}
    out = []
    for i, o in enumerate(edl.get("overlays") or []):
        if "at" in o:
            t0 = float(o["at"])
        elif o.get("at_clip") in by_id:
            t0 = by_id[o["at_clip"]]["t0"] + float(o.get("offset", 0.0))
        else:
            die(f"overlays[{i}] に at も有効な at_clip も無い", 2)
        oin, oout = float(o["in"]), float(o["out"])
        if oout <= oin:
            die(f"overlays[{i}] は out <= in", 2)
        out.append({"src": o["src"], "in": oin, "dur": oout - oin, "t0": t0,
                    "note": o.get("note", "")})
    return out


def write_json(path: str | Path, data) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fmt_ts(sec: float) -> str:
    sec = max(0.0, sec)
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(text: str) -> list[dict]:
    items = []
    blocks = re.split(r"\r?\n\s*\r?\n", text.strip().lstrip("\ufeff"))
    pat = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
    for b in blocks:
        lines = b.splitlines()
        for j, line in enumerate(lines):
            m = pat.search(line)
            if m:
                g = [int(x) for x in m.groups()]
                st = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                en = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                items.append({"start": st, "end": en, "lines": [x for x in lines[j + 1:] if x.strip()]})
                break
    return items


def char_width(s: str) -> float:
    """全角1・半角0.5で数える（Netflix の日本語ガイドの数え方）。"""
    import unicodedata
    return sum(1.0 if unicodedata.east_asian_width(ch) in ("F", "W", "A") else 0.5 for ch in s)


def setup_stdout() -> None:
    """Windows のコンソールでも日本語が化けないよう UTF-8 で出す。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
