"""EDL どおりに素材を切ってつなぎ、B ロール・字幕・BGM・音量の調整まで済ませた MP4 を書き出す（E5）。

使い方:
  python render.py edit/edl.json --out out/<名前>.mp4 [--work edit/build] [--preview] [--clean]

工程:
  1. クリップごとに映像（等倍か punch-in の拡大、出力の解像度・fps にそろえる）と音声（J/L カットのずれ込み、
     境目に 10ms のフェード）を切り出す。中身が同じクリップは前回の切り出しを使い回す
  2. 映像・音声をそれぞれつなぐ
  3. BGM があれば声で自動的に下げて（サイドチェーン）混ぜる
  4. 配信先（EDL の target）の目標ラウドネスへ 2 パスの loudnorm で合わせる
  5. B ロールを重ね、burn_subtitles が true なら字幕を焼き込み、H.264/AAC で書き出す
字幕ファイルがあれば、焼き込むかどうかに関わらず出力と同じ名前の .srt を隣に置く。

--preview は幅 640 の軽い書き出し（確認用）。納品には使わない。

終了コード: 0 書き出した / 2 EDL・素材の誤り、ffmpeg が無い / 3 ffmpeg が失敗した
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ffutil  # noqa: E402


def default_font() -> str:
    if sys.platform.startswith("win"):
        return "Meiryo"
    if sys.platform == "darwin":
        return "Hiragino Sans"
    return "Noto Sans CJK JP"


def vfilter(W: int, H: int, fps: float, zoom: float, center, fit: str) -> str:
    """fit=contain: 縦横比を保って縮め、余りは黒帯。cover: 出力の縦横比で切り抜いて画面を埋める。"""
    f = [f"fps={fps:g}"]
    z = zoom if zoom and zoom > 1.0 else 1.0
    cx, cy = (center or [0.5, 0.5])[:2]
    if fit == "cover":
        A = W / H
        f.append(f"crop=trunc(min(iw\\,ih*{A:.6f})/{z}/2)*2:trunc(min(iw\\,ih*{A:.6f})/{z}/{A:.6f}/2)*2:"
                 f"(iw-ow)*{cx}:(ih-oh)*{cy}")
    elif z > 1.0:
        f.append(f"crop=trunc(iw/{z}/2)*2:trunc(ih/{z}/2)*2:(iw-iw/{z})*{cx}:(ih-ih/{z})*{cy}")
    f += [f"scale={W}:{H}:force_original_aspect_ratio=decrease",
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2", "setsar=1", "format=yuv420p"]
    return ",".join(f)


def cut_segments(edl, base, rows, spec, work: Path, preview: bool) -> tuple[list[Path], list[Path]]:
    W, H, fps = spec["width"], spec["height"], float(spec["fps"])
    crf, preset = ("30", "ultrafast") if preview else ("18", "veryfast")
    infos, vsegs, asegs = {}, [], []
    for r in rows:
        sp = ffutil.src_path(edl, base, r["src"])
        if r["src"] not in infos:
            if not sp.is_file():
                ffutil.die(f"素材が無い: {sp}", 2)
            infos[r["src"]] = ffutil.probe(sp)
        info = infos[r["src"]]
        if r["in"] + r["vdur"] > info["duration"] + 0.05:
            ffutil.die(f"クリップ {r['id']} の out が素材の長さ {info['duration']:.2f}秒 を超えている", 2)
        if r["a_in"] < 0 or r["a_in"] + r["a_dur"] > info["duration"] + 0.05:
            ffutil.die(f"クリップ {r['id']} の audio_shift で音声が素材の外にはみ出す", 2)
        if not info["video"]:
            ffutil.die(f"クリップ {r['id']} の素材に映像が無い（音声だけの素材は music に入れる）", 2)
        fit = spec.get("fit", "contain")
        key = json.dumps([str(sp), r["in"], r["frames"], r["zoom"], r["center"], W, H, fps, preview, fit])
        h = hashlib.sha1(key.encode()).hexdigest()[:10]
        v = work / f"v_{h}.mp4"
        if not v.exists():
            ffutil.run_ok(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                           "-ss", f"{r['in']:.3f}", "-i", str(sp), "-frames:v", str(r["frames"]), "-an",
                           "-vf", vfilter(W, H, fps, r["zoom"], r["center"], fit),
                           "-c:v", "libx264", "-preset", preset, "-crf", crf, "-r", f"{fps:g}",
                           "-video_track_timescale", "90000", str(v)])
        vsegs.append(v)
        akey = json.dumps([str(sp), r["a_in"], r["a_dur"]])
        ah = hashlib.sha1(akey.encode()).hexdigest()[:10]
        aw = work / f"a_{ah}.wav"
        if not aw.exists():
            d = r["a_dur"]
            fade = f"afade=t=in:d=0.01,afade=t=out:st={max(0.0, d - 0.01):.4f}:d=0.01"
            if info["audio"]:
                cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{r['a_in']:.4f}",
                       "-i", str(sp), "-vn", "-af", f"aresample=48000,apad,atrim=0:{d:.4f},{fade}",
                       "-ac", "2", "-c:a", "pcm_s16le", str(aw)]
            else:
                cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                       "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{d:.4f}", "-c:a", "pcm_s16le", str(aw)]
            ffutil.run_ok(cmd)
        asegs.append(aw)
    return vsegs, asegs


def concat(files: list[Path], out: Path, work: Path) -> None:
    lst = work / (out.stem + "_list.txt")
    lst.write_text("".join(f"file '{f.name}'\n" for f in files), encoding="utf-8")
    ffutil.run_ok(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                   "-i", lst.name, "-c", "copy", out.name], cwd=str(work))


def mix_music(edl, base, main_a: Path, total: float, work: Path) -> Path:
    m = edl.get("music")
    if not m:
        return main_a
    mp = Path(m["src"]) if Path(m["src"]).is_absolute() else base / m["src"]
    if not mp.is_file():
        ffutil.die(f"BGM が無い: {mp}", 2)
    gain = float(m.get("gain_db", -20))
    fo = float(m.get("fade_out", 2.0))
    chain = f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f},volume={gain}dB," \
            f"afade=t=out:st={max(0.0, total - fo):.3f}:d={fo}[m];"
    if m.get("duck", True):
        g = ("[0:a]asplit=2[v][sc];" + chain +
             "[m][sc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=500[md];"
             "[v][md]amix=inputs=2:normalize=0:duration=first[out]")
    else:
        g = chain + "[0:a][m]amix=inputs=2:normalize=0:duration=first[out]"
    out = work / "mix.wav"
    ffutil.run_ok(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(main_a),
                   "-stream_loop", "-1", "-i", str(mp), "-filter_complex", g, "-map", "[out]",
                   "-c:a", "pcm_s16le", str(out)])
    return out


def loudnorm_filter(audio: Path, target: dict) -> str:
    base = f"loudnorm=I={target['lufs']}:TP={target['tp']}:LRA=11"
    p = ffutil.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(audio),
                    "-af", base + ":print_format=json", "-f", "null", "-"])
    txt = p.stderr
    try:
        js = json.loads(txt[txt.rindex("{"):txt.rindex("}") + 1])
        return (base + f":measured_I={js['input_i']}:measured_TP={js['input_tp']}"
                f":measured_LRA={js['input_lra']}:measured_thresh={js['input_thresh']}"
                f":offset={js['target_offset']}:linear=true")
    except (ValueError, KeyError):
        print("注意: loudnorm の測定に失敗したので 1 パスで合わせる")
        return base


def main() -> int:
    ffutil.setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("edl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--work")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--clean", action="store_true", help="書き出し後に作業ディレクトリを消す")
    a = ap.parse_args()
    ffutil.require_ffmpeg()
    edl, base = ffutil.load_edl(a.edl)
    target = ffutil.TARGETS.get(edl.get("target", "youtube"))
    if target is None:
        ffutil.die(f"target は {sorted(ffutil.TARGETS)} のどれか", 2)

    first = ffutil.src_path(edl, base, edl["clips"][0]["src"]) if edl["clips"] else None
    spec = ffutil.out_spec(edl, ffutil.probe(first)["video"] if first and first.is_file() else None)
    if a.preview:
        spec["height"] = int(640 * spec["height"] / spec["width"]) // 2 * 2
        spec["width"] = 640
    fps = float(spec["fps"])
    rows = ffutil.timeline(edl, fps)
    ovs = ffutil.overlay_rows(edl, rows)
    total = rows[-1]["t0"] + rows[-1]["vdur"]

    work = Path(a.work) if a.work else Path(a.edl).resolve().parent / "build"
    work.mkdir(parents=True, exist_ok=True)
    print(f"クリップ {len(rows)} 個を切り出し中（{spec['width']}x{spec['height']} {fps:g}fps）")
    vsegs, asegs = cut_segments(edl, base, rows, spec, work, a.preview)
    main_v, main_a = work / "main_v.mp4", work / "main_a.wav"
    concat(vsegs, main_v, work)
    concat(asegs, main_a, work)
    audio = mix_music(edl, base, main_a, total, work)
    ln = loudnorm_filter(audio, target)

    inputs = ["-i", str(main_v), "-i", str(audio)]
    graph, last = [], "[0:v]"
    for k, o in enumerate(ovs):
        sp = ffutil.src_path(edl, base, o["src"])
        if not sp.is_file():
            ffutil.die(f"B ロールの素材が無い: {sp}", 2)
        inputs += ["-ss", f"{o['in']:.3f}", "-t", f"{o['dur']:.3f}", "-i", str(sp)]
        idx = 2 + k
        W, H = spec["width"], spec["height"]
        graph.append(f"[{idx}:v]fps={fps:g},scale={W}:{H}:force_original_aspect_ratio=increase,"
                     f"crop={W}:{H},setsar=1,format=yuv420p,setpts=PTS-STARTPTS+{o['t0']:.3f}/TB[o{k}]")
        graph.append(f"{last}[o{k}]overlay=eof_action=pass:enable='between(t,{o['t0']:.3f},"
                     f"{o['t0'] + o['dur']:.3f})'[b{k}]")
        last = f"[b{k}]"
    subs = edl.get("subtitles")
    sub_src = None
    if subs:
        sub_src = Path(subs) if Path(subs).is_absolute() else base / subs
        if not sub_src.is_file():
            ffutil.die(f"字幕ファイルが無い: {sub_src}", 2)
        if edl.get("burn_subtitles"):
            shutil.copyfile(sub_src, work / "burn.srt")
            st = edl.get("subtitle_style") or {}
            size = int(st.get("size", 20))
            style = (f"FontName={st.get('font', default_font())},FontSize={size},PrimaryColour=&H00FFFFFF,"
                     f"OutlineColour=&H00000000,BorderStyle=1,Outline={st.get('outline', 2)},Shadow=0,"
                     f"MarginV={st.get('margin_v', 40)},Alignment=2")
            graph.append(f"{last}subtitles=burn.srt:charenc=UTF-8:force_style='{style}'[vs]")
            last = "[vs]"
    graph.append(f"[1:a]{ln},aresample=48000[aout]")
    if last == "[0:v]":
        graph.insert(0, "[0:v]null[vout]")
        last = "[vout]"
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    crf, preset = ("30", "ultrafast") if a.preview else ("18", "medium")
    ffutil.run_ok(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + inputs +
                  ["-filter_complex", ";".join(graph), "-map", last, "-map", "[aout]",
                   "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", preset, "-crf", crf,
                   "-pix_fmt", "yuv420p", "-r", f"{fps:g}", "-c:a", "aac", "-b:a", "192k",
                   "-movflags", "+faststart", str(out)], cwd=str(work))
    if sub_src:
        shutil.copyfile(sub_src, out.with_suffix(".srt"))
    if a.clean:
        shutil.rmtree(work, ignore_errors=True)
    print(f"書き出し: {out}（{total:.2f}秒、クリップ {len(rows)}、B ロール {len(ovs)}、"
          f"字幕 {'焼き込み' if subs and edl.get('burn_subtitles') else ('別ファイル' if subs else 'なし')}、"
          f"BGM {'あり' if edl.get('music') else 'なし'}、目標 {target['lufs']} LUFS）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
