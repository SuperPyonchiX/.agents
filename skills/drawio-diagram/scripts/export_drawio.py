#!/usr/bin/env python3
"""draw.io デスクトップ版の CLI で .drawio を PNG / SVG / PDF に書き出す。

使い方:
  python export_drawio.py <file.drawio> [-f png|svg|pdf] [-o 出力パス] [--page N] [--scale 2]
                          [--all-pages] [--exe draw.io 実行ファイルのパス]

  --page      書き出すページ（1 始まり）。省略時は 1 ページ目
  --all-pages 全ページを書き出す。png/svg はページごとに <名前>-<ページ番号>.<拡張子>、pdf は1ファイル
  --scale     拡大率。既定 2（資料に貼っても潰れない解像度）

draw.io の探し方（最初に見つかったものを使う）:
  --exe → 環境変数 DRAWIO_EXE → PATH 上の draw.io / drawio →
  Windows: %LOCALAPPDATA%\\Programs\\draw.io\\draw.io.exe, %ProgramFiles%\\draw.io\\draw.io.exe
  macOS: /Applications/draw.io.app/Contents/MacOS/draw.io
  Linux: /usr/bin/drawio, /opt/drawio/drawio

終了コード: 0 = 書き出した / 1 = 書き出しに失敗 / 2 = 引数の誤り / 3 = draw.io が見つからない
          4 = draw.io が起動直後に異常終了した（サンドボックス内など、権限の制限で起動できない）。
              再試行しても同じ結果になるので、繰り返さない

Windows では draw.io の異常終了時にエラーダイアログが出ないようにしてから起動する。
Linux では root なら --no-sandbox を付け、画面が無く xvfb-run があればその上で起動する。
依存: 標準ライブラリのみ（draw.io デスクトップ版 v27.0.2 以降を別途インストール。それより前はページ番号が 0 始まりで、別のページが出る）
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET


def find_exe(explicit):
    cands = [explicit, os.environ.get("DRAWIO_EXE"),
             shutil.which("draw.io"), shutil.which("drawio")]
    system = platform.system()
    if system == "Windows":
        for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles")):
            if base:
                cands += [os.path.join(base, "Programs", "draw.io", "draw.io.exe"),
                          os.path.join(base, "draw.io", "draw.io.exe")]
    elif system == "Darwin":
        cands.append("/Applications/draw.io.app/Contents/MacOS/draw.io")
    else:
        cands += ["/usr/bin/drawio", "/opt/drawio/drawio"]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def page_count(path):
    try:
        return max(1, len(ET.parse(path).getroot().findall("diagram")))
    except (OSError, ET.ParseError):
        return 1


class Crashed(Exception):
    pass


CRASH_MARKERS = ("FATAL:", "Access is denied", "アクセスが拒否されました")


def quiet_crash_dialogs():
    """子プロセスが異常終了しても Windows のエラーダイアログを出さない（子へ継承される）"""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        SEM_FAILCRITICALERRORS, SEM_NOGPFAULTERRORBOX, SEM_NOOPENFILEERRORBOX = 0x0001, 0x0002, 0x8000
        ctypes.windll.kernel32.SetErrorMode(
            SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX)
    except (OSError, AttributeError):
        pass


def launcher(exe):
    """Linux で draw.io（Electron）を起動するための前後の引数。root ではサンドボックスを切らないと起動直後に
    落ち（FATAL: Running as root without --no-sandbox）、画面の無い環境では xvfb-run が要る。
    コンテナや CI がこれに当たる。Electron の引数は入力ファイルの後ろに置く（前に置くと入力ファイルを見失う）"""
    if platform.system() != "Linux":
        return [exe], []
    pre, post = [exe], []
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        post.append("--no-sandbox")
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and shutil.which("xvfb-run"):
        pre = ["xvfb-run", "-a", exe]
    return pre, post


NOISE = ("dbus", "Checking for beta autoupdate", "Found package-type")


def tail(log, lines=15):
    """失敗時のログは末尾だけ出す（Linux では D-Bus の警告が何十行も混ざる）"""
    kept = [ln for ln in log.splitlines() if ln.strip() and not any(n in ln for n in NOISE)]
    return "\n".join(kept[-lines:])


def run(exe, src, fmt, out, page, scale):
    pre, post = launcher(exe)
    cmd = pre + ["-x", "-f", fmt, "-o", out, "-p", str(page), "--border", "10"]
    if fmt == "png":
        cmd += ["-s", str(scale)]
    if fmt == "pdf" and page == 0:
        cmd = pre + ["-x", "-f", fmt, "-o", out, "-a"]
    cmd += [src] + post
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    ok = r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 0
    log = (r.stdout or "") + (r.stderr or "")
    if not ok and any(m in log for m in CRASH_MARKERS):
        print(f"CRASH  {out}\n{tail(log)}".rstrip())
        raise Crashed()
    if not ok:
        print(f"FAIL   {out}\n{tail(log)}".rstrip())
    else:
        print(f"OK     {out}")
    return ok


for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def main():
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("src")
    p.add_argument("-f", "--format", default="png", choices=["png", "svg", "pdf"])
    p.add_argument("-o", "--output")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--all-pages", action="store_true")
    p.add_argument("--scale", type=float, default=2)
    p.add_argument("--exe")
    try:
        a = p.parse_args()
    except SystemExit:
        return 2
    if not os.path.isfile(a.src) or a.page < 1:
        print("ERROR  入力ファイルが無いか、--page が 1 未満")
        return 2
    if a.page > page_count(a.src):   # draw.io はページ数を超える番号でも黙って1ページ目を書き出す
        print(f"ERROR  --page {a.page} はページ数（{page_count(a.src)}）を超えている")
        return 2
    exe = find_exe(a.exe)
    if not exe:
        print("ERROR  draw.io デスクトップ版が見つからない。インストールするか --exe / DRAWIO_EXE で指定する"
              "（Windows: winget install JGraph.Draw）")
        return 3
    quiet_crash_dialogs()
    stem = os.path.splitext(a.output or a.src)[0]
    try:
        return export(exe, a, stem)
    except Crashed:
        print("ERROR  draw.io が起動直後に異常終了した。サンドボックスなど権限の制限が原因の可能性が高い。"
              "再試行せず、制限の無い環境での実行をユーザーに頼む")
        return 4


def export(exe, a, stem):
    if a.all_pages and a.format == "pdf":
        ok = run(exe, a.src, "pdf", f"{stem}.pdf", 0, a.scale)
    elif a.all_pages:
        ok = all(run(exe, a.src, a.format, f"{stem}-{i}.{a.format}", i, a.scale)
                 for i in range(1, page_count(a.src) + 1))
    else:
        out = a.output or f"{stem}.{a.format}"
        ok = run(exe, a.src, a.format, out, a.page, a.scale)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
