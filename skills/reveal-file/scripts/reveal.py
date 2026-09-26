#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成したファイルを OS のファイルマネージャーで選択状態にして開く。

    python reveal.py <path> [<path> ...] [--dry-run]

OS ごとの動作:
    Windows      explorer /select,"<path>"
    WSL          wslpath -w で変換してから explorer.exe /select,
    macOS        open -R <path>
    Linux        FileManager1.ShowItems（D-Bus）で選択表示。無ければ親フォルダを xdg-open

ディレクトリを渡した場合は、そのディレクトリ自体を開く。
同じフォルダにある複数ファイルは、先頭の1件だけ選択して開く（ウィンドウを乱立させない）。

終了コード:
    0  開いた（--dry-run では実行予定のコマンドを表示した）
    1  存在しないパスがある。1件も開いていない
    2  引数の指定ミス
    3  GUI が使えない環境（SSH 越し・ディスプレイなし）か、対応するコマンドが無い

依存は標準ライブラリのみ。
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys


def is_wsl():
    if platform.system() != "Linux":
        return False
    try:
        with open("/proc/version", encoding="utf-8") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def is_remote_shell():
    return bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"))


def build_command(path):
    """(コマンド, shell 実行するか) を返す。対応手段が無ければ None。"""
    system = platform.system()
    is_dir = os.path.isdir(path)

    if system == "Windows":
        # explorer は /select, とパスを1つの引数として解釈するため、文字列で組み立てる
        if is_dir:
            return ('explorer "%s"' % path, False)
        return ('explorer /select,"%s"' % path, False)

    if is_wsl():
        win = subprocess.run(["wslpath", "-w", path], capture_output=True, text=True).stdout.strip()
        if not win:
            return None
        return (["explorer.exe", win] if is_dir else ["explorer.exe", "/select," + win], False)

    if system == "Darwin":
        return (["open", path] if is_dir else ["open", "-R", path], False)

    # Linux デスクトップ
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return None
    if not is_dir and shutil.which("dbus-send"):
        uri = "file://" + path
        return (["dbus-send", "--session", "--dest=org.freedesktop.FileManager1",
                 "--type=method_call", "/org/freedesktop/FileManager1",
                 "org.freedesktop.FileManager1.ShowItems",
                 "array:string:" + uri, "string:"], False)
    if shutil.which("xdg-open"):
        return (["xdg-open", path if is_dir else os.path.dirname(path)], False)
    return None


def pick_targets(paths):
    """フォルダごとに先頭1件へ絞る。"""
    seen, targets, skipped = set(), [], []
    for p in paths:
        key = p if os.path.isdir(p) else os.path.dirname(p)
        if key in seen:
            skipped.append(p)
            continue
        seen.add(key)
        targets.append(p)
    return targets, skipped


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap =argparse.ArgumentParser(description="ファイルをファイルマネージャーで選択表示する")
    ap.add_argument("paths", nargs="+", help="開くファイルまたはディレクトリ")
    ap.add_argument("--dry-run", action="store_true", help="実行せずにコマンドだけ表示する")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2

    paths = [os.path.abspath(os.path.expanduser(p)) for p in args.paths]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        for p in missing:
            print("NOT FOUND  %s" % p)
        return 1

    if is_remote_shell() and not args.dry_run:
        print("SKIP  SSH 越しのため GUI を開けない。パスだけ示す:")
        for p in paths:
            print("      %s" % p)
        return 3

    targets, skipped = pick_targets(paths)
    for p in targets:
        cmd = build_command(p)
        if cmd is None:
            print("SKIP  GUI のファイルマネージャーが使えない環境: %s" % p)
            return 3
        command, _ = cmd
        if args.dry_run:
            print("DRY-RUN  %s" % (command if isinstance(command, str) else " ".join(command)))
            continue
        # explorer は成功しても終了コード 1 を返すことがあるため、戻り値では判定しない
        subprocess.Popen(command)
        print("OPENED  %s" % p)
    for p in skipped:
        print("SAME-FOLDER  %s（同じフォルダのため選択表示は先頭の1件のみ）" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
