#!/usr/bin/env python3
"""Blender を画面なし（-b）で起動してシーンスクリプトを実行し、背景透過の連番 PNG を書き出させて枚数を確かめる。

使い方:
  python blender_render.py --find [--blender PATH]
  python blender_render.py <scene.py> --out <public/3d/<id>> --frames <枚数>
                           [--fps 30] [--width 1920] [--height 1080] [--blender PATH] [--timeout 900]
                           [--set key=value ...]

  scene.py には `-- --out <絶対パス> --frames N --fps F --width W --height H [--set key=value ...]` が渡る。
  scene.py は <out>/0001.png から連番で N 枚書き出す（assets/blender/scene_template.py がその実装例）。
  Blender の場所は --blender、環境変数 BLENDER、PATH、既定のインストール先の順に探す。

終了コード: 0 = N 枚そろった / 1 = Blender が見つからない / 2 = 引数の誤り /
            3 = レンダリング失敗（Blender の異常終了・時間切れ・枚数不足）
依存: 標準ライブラリのみ（Blender 本体は別途インストール）
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def find_blender(explicit):
    for cand in (explicit, os.environ.get("BLENDER")):
        if cand and os.path.isfile(cand):
            return cand
    found = shutil.which("blender")
    if found:
        return found
    patterns = [
        r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\BlenderFoundation.Blender*\**\blender.exe"),
        "/Applications/Blender.app/Contents/MacOS/Blender",
        "/usr/bin/blender", "/snap/bin/blender",
    ]
    hits = []
    for pat in patterns:
        hits += glob.glob(pat, recursive=True)
    return sorted(hits)[-1] if hits else None  # 版数の新しいものを優先


def rel_to_public(path):
    norm = os.path.abspath(path).replace("\\", "/")
    i = norm.rfind("/public/")
    return norm[i + len("/public/"):] if i >= 0 else os.path.basename(norm)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("scene", nargs="?")
    p.add_argument("--find", action="store_true")
    p.add_argument("--blender")
    p.add_argument("--out")
    p.add_argument("--frames", type=int)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--set", action="append", default=[])
    try:
        a = p.parse_args()
    except SystemExit:
        return 2

    exe = find_blender(a.blender)
    if not exe:
        print("ERROR  Blender が見つからない。references/blender.md の「導入」に従って入れるか、--blender で場所を渡す")
        return 1
    if a.find:
        print(exe)
        return 0
    if not (a.scene and a.out and a.frames and a.frames > 0):
        print("ERROR  scene.py・--out・--frames（1以上）を指定する")
        return 2
    if not os.path.isfile(a.scene):
        print(f"ERROR  シーンスクリプトが無い: {a.scene}")
        return 2

    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    for old in glob.glob(os.path.join(out, "*.png")):
        os.remove(old)
    cmd = [exe, "-b", "--factory-startup", "-P", os.path.abspath(a.scene), "--",
           "--out", out, "--frames", str(a.frames), "--fps", str(a.fps),
           "--width", str(a.width), "--height", str(a.height)]
    for kv in a.set:
        cmd += ["--set", kv]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=a.timeout)
    except subprocess.TimeoutExpired:
        print(f"ERROR  {a.timeout} 秒で終わらなかった。--frames か解像度を下げる、サンプル数を減らす")
        return 3
    log = (r.stdout or "") + (r.stderr or "")
    pngs = sorted(glob.glob(os.path.join(out, "*.png")))
    if r.returncode != 0 or len(pngs) != a.frames or "Traceback" in log:
        tail = "\n".join(log.strip().splitlines()[-25:])
        print(f"ERROR  レンダリング失敗（終了コード {r.returncode}、{len(pngs)}/{a.frames} 枚）\n{tail}")
        return 3
    print(f"OK     {len(pngs)} 枚 → {out}")
    print(f"       staticFile のパス: {rel_to_public(out)}/0001.png 〜 {os.path.basename(pngs[-1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
