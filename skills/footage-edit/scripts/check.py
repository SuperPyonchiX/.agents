"""書き出した動画を検査する（E6）。機械で決まる項目を判定し、目で見る項目のために境目の画像を作る。

使い方:
  python check.py out/<名前>.mp4 --edl edit/edl.json [--srt out/<名前>.srt] [--target youtube]
                  [--max-silence 1.0] [--max-chars 16] [--max-cps 7] [--sheet edit/sheets]
                  [--report edit/check.json]

ERROR（1件でもあれば終了コード 1）:
  - 積算ラウドネスが目標 ±許容幅の外、True Peak が上限超え
  - 長さが EDL の合計と 2 フレームより大きくずれている
  - 0.5 秒以上の黒画面、--max-silence 秒以上の無音（間延び）
  - 字幕: 1行の文字数超過（全角1・半角0.5）、3行以上、0.5 秒未満・7 秒超の表示、
    重なり、2 フレーム未満の隙間、動画の外にはみ出した字幕
WARN（判定は人かエージェントの目に任せる）:
  - 字幕: 5/6 秒未満の表示、1秒あたりの文字数が --max-cps 超え
  - 3 秒以上の静止画面（画面録画では正常なことが多い）
  - 隠れていないジャンプカット（同じ素材・同じ拡大率のクリップが続き、B ロールでも覆っていない境目）

--sheet を付けると、カットと B ロールの出入りの境目ごとに直前・直後のコマを並べた画像を
sheet_01.png… に書き、どの行がどの境目かを sheets.md に書く。references/self-review.md で目視する。

終了コード: 0 ERROR なし / 1 ERROR あり / 2 引数・入力の誤り、ffmpeg が無い
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ffutil  # noqa: E402


def detect(path: str, vf: str, key_start: str, key_end: str) -> list[list[float]]:
    p = ffutil.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-an", "-vf", vf, "-f", "null", "-"])
    out, st = [], None
    for line in p.stderr.splitlines():
        m = re.search(key_start + r"[:=]\s*([\d.]+)", line)
        if m:
            st = float(m.group(1))
        m = re.search(key_end + r"[:=]\s*([\d.]+)", line)
        if m and st is not None:
            out.append([st, float(m.group(1))])
            st = None
    return out


def black_segments(path: str) -> list[list[float]]:
    p = ffutil.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-an",
                    "-vf", "blackdetect=d=0.5:pix_th=0.10", "-f", "null", "-"])
    return [[float(m.group(1)), float(m.group(2))]
            for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+)", p.stderr)]


def check_srt(items, total, fps, max_chars, max_cps, err, warn) -> None:
    gap_min = 2 / fps - 1e-3
    for i, it in enumerate(items, 1):
        d = it["end"] - it["start"]
        text = "".join(it["lines"])
        tag = f"字幕 {i}（{ffutil.fmt_ts(it['start'])}）"
        if len(it["lines"]) > 2:
            err.append(f"{tag}: {len(it['lines'])} 行ある（2行まで）")
        for ln in it["lines"]:
            if ffutil.char_width(ln) > max_chars:
                err.append(f"{tag}: 1行 {ffutil.char_width(ln):g} 文字で上限 {max_chars:g} を超える「{ln}」")
        if d < 0.5:
            err.append(f"{tag}: 表示 {d:.2f}秒（0.5秒未満は読めない）")
        elif d < 5 / 6:
            warn.append(f"{tag}: 表示 {d:.2f}秒（5/6秒未満）")
        if d > 7.0 + 1e-3:
            err.append(f"{tag}: 表示 {d:.2f}秒（7秒まで）")
        chars = len(re.sub(r"\s", "", text))
        if d > 0 and chars / d > max_cps:
            warn.append(f"{tag}: {chars / d:.1f} 文字/秒（{max_cps:g} 超え。要約するか表示を延ばす）")
        if it["end"] > total + 0.05:
            err.append(f"{tag}: 動画の終わり {total:.2f}秒 を過ぎて表示される")
        if i < len(items):
            g = items[i]["start"] - it["end"]
            if g < -1e-3:
                err.append(f"{tag}: 次の字幕と {-g:.2f}秒 重なる")
            elif g < gap_min:
                err.append(f"{tag}: 次の字幕との隙間が 2 フレーム未満")


def exposed_jumps(edl: dict, rows: list[dict], ovs: list[dict]) -> list[str]:
    clips = edl["clips"]
    res = []
    for i in range(1, len(rows)):
        a, b = rows[i - 1], rows[i]
        if a["src"] != b["src"] or abs(a["zoom"] - b["zoom"]) > 1e-3:
            continue
        if b["in"] - (a["in"] + a["vdur"]) < 0.05 and b["in"] >= a["in"]:
            continue  # 素材上で連続している（実質カットでない）
        t = b["t0"]
        if any(o["t0"] - 0.05 <= t <= o["t0"] + o["dur"] + 0.05 for o in ovs):
            continue
        if clips[i].get("jump_ok"):
            continue
        res.append(f"{b['id']}（{t:.2f}秒）")
    return res


def contact_sheets(video: str, points: list[tuple[str, float]], fps: float, outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("sheet_*.png"):
        old.unlink()
    frames_dir = outdir / "frames"
    frames_dir.mkdir(exist_ok=True)
    sheets, md = [], ["# 境目の確認画像", "", "各行は左が境目の直前、右が直後のコマ。", ""]
    per = 4
    for n in range(0, len(points), per):
        chunk = points[n:n + per]
        files = []
        for j, (label, t) in enumerate(chunk):
            for side, tt in (("a", t - 3 / fps), ("b", t + 3 / fps)):
                f = frames_dir / f"{n + j:03d}{side}.png"
                ffutil.run_ok(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss",
                               f"{max(0.0, tt):.3f}", "-i", video, "-frames:v", "1",
                               "-vf", "scale=480:-2", str(f)])
                files.append(f)
        sheet = outdir / f"sheet_{n // per + 1:02d}.png"
        ins, g = [], []
        for k, f in enumerate(files):
            ins += ["-i", str(f)]
        rows_lbl = []
        for r in range(len(chunk)):
            g.append(f"[{2 * r}:v][{2 * r + 1}:v]hstack=inputs=2[r{r}]")
            rows_lbl.append(f"[r{r}]")
        if len(chunk) > 1:
            g.append("".join(rows_lbl) + f"vstack=inputs={len(chunk)}[out]")
        else:
            g.append("[r0]null[out]")
        ffutil.run_ok(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + ins +
                      ["-filter_complex", ";".join(g), "-map", "[out]", "-frames:v", "1", str(sheet)])
        sheets.append(sheet)
        md.append(f"## {sheet.name}")
        md += [f"{r + 1}. {lbl}（{t:.2f}秒）" for r, (lbl, t) in enumerate(chunk)]
        md.append("")
    (outdir / "sheets.md").write_text("\n".join(md), encoding="utf-8")
    return sheets


def main() -> int:
    ffutil.setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--edl", required=True)
    ap.add_argument("--srt")
    ap.add_argument("--target", choices=sorted(ffutil.TARGETS))
    ap.add_argument("--max-silence", type=float, default=1.0)
    ap.add_argument("--silence-noise", type=float, default=-40.0)
    ap.add_argument("--max-chars", type=float, default=16)
    ap.add_argument("--max-cps", type=float, default=7.0)
    ap.add_argument("--sheet")
    ap.add_argument("--report")
    a = ap.parse_args()
    ffutil.require_ffmpeg()
    if not Path(a.video).is_file():
        ffutil.die(f"動画が無い: {a.video}", 2)
    edl, _ = ffutil.load_edl(a.edl)
    info = ffutil.probe(a.video)
    if not info["video"] or not info["audio"]:
        ffutil.die("映像か音声のストリームが無い", 2)
    fps = info["video"]["fps"] or 30.0
    rows = ffutil.timeline(edl, fps)
    ovs = ffutil.overlay_rows(edl, rows)
    expect = rows[-1]["t0"] + rows[-1]["vdur"]
    total = info["duration"]
    target = ffutil.TARGETS[a.target or edl.get("target", "youtube")]
    err, warn = [], []

    if abs(total - expect) > 2 / fps + 0.03:
        err.append(f"長さ {total:.2f}秒 が EDL の合計 {expect:.2f}秒 とずれている")
    loud = ffutil.measure_loudness(a.video)
    if loud["lufs"] is None or abs(loud["lufs"] - target["lufs"]) > target["tol"]:
        err.append(f"ラウドネス {loud['lufs']} LUFS が目標 {target['lufs']}±{target['tol']} の外")
    if loud["true_peak"] is not None and loud["true_peak"] > target["tp"] + 0.1:
        err.append(f"True Peak {loud['true_peak']} dBTP が上限 {target['tp']} を超える")
    for s, e in black_segments(a.video):
        err.append(f"黒画面 {s:.2f}〜{e:.2f}秒")
    for s, e in ffutil.detect_silence(a.video, a.silence_noise, a.max_silence, total):
        err.append(f"無音 {s:.2f}〜{e:.2f}秒（{e - s:.1f}秒の間延び）")
    for s, e in detect(a.video, "freezedetect=n=0.003:d=3", r"freeze_start", r"freeze_end"):
        warn.append(f"静止画面 {s:.2f}〜{e:.2f}秒（画面録画なら正常なこともある）")
    jumps = exposed_jumps(edl, rows, ovs)
    if jumps:
        warn.append(f"隠れていないジャンプカット {len(jumps)} 箇所: " + "、".join(jumps[:20]) +
                    (" ほか" if len(jumps) > 20 else ""))
    srt = Path(a.srt) if a.srt else Path(a.video).with_suffix(".srt")
    n_subs = 0
    if srt.is_file():
        items = ffutil.parse_srt(srt.read_text(encoding="utf-8-sig"))
        n_subs = len(items)
        check_srt(items, total, fps, a.max_chars, a.max_cps, err, warn)
    elif a.srt:
        ffutil.die(f"字幕ファイルが無い: {a.srt}", 2)

    sheets = []
    if a.sheet:
        pts = [(f"カット {r['id']}", r["t0"]) for r in rows[1:]]
        pts += [(f"B ロール入り {o['note'] or o['src']}", o["t0"]) for o in ovs]
        pts += [(f"B ロール明け {o['note'] or o['src']}", o["t0"] + o["dur"]) for o in ovs]
        pts.sort(key=lambda x: x[1])
        if pts:
            sheets = contact_sheets(a.video, pts, fps, Path(a.sheet))

    print(f"長さ {total:.2f}秒 / {loud['lufs']} LUFS / TP {loud['true_peak']} dBTP / LRA {loud['lra']} LU / "
          f"字幕 {n_subs} 枚")
    for e in err:
        print(f"ERROR: {e}")
    for w in warn:
        print(f"WARN: {w}")
    if sheets:
        print(f"確認画像: {len(sheets)} 枚（{Path(a.sheet) / 'sheets.md'}）")
    print("合格" if not err else f"不合格（ERROR {len(err)} 件）")
    if a.report:
        ffutil.write_json(a.report, {"duration": total, "expected": expect, "loudness": loud,
                                     "errors": err, "warnings": warn,
                                     "sheets": [str(s) for s in sheets]})
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
