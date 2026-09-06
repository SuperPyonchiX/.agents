#!/usr/bin/env python3
"""Markdown ノートの `## 節` 直下に行を差し込む。

使い方:
    python append_daily.py <ノートのパス> [--template <雛形>] [--date YYYY-MM-DD] [--title <題名>]
                           (--section <節名> --line <行> [--line <行>]...)...

動作:
    - `--section` は直後の `--line` 群に効く。複数の節を1回で指定できる
    - 節内に `- 睡眠:` のような空欄行があり、新しい行がその接頭辞で始まれば空欄行を置き換える
    - 節の末尾が `-` だけの行なら、それを新しい行で置き換える
    - 同一の行が既にあれば書かず SKIP と出す
    - 節が無ければファイル末尾に `## 節名` を作って差し込む
    - ファイルが無ければ `--template` から作る。`{{date}}` と `{{title}}` を置き換える

終了コード:
    0  完了（全件 SKIP も含む）
    1  ファイルを作れない・雛形が無い・書き込みに失敗
    2  引数の指定ミス

依存: 標準ライブラリのみ。
"""
import datetime
import os
import sys


def parse_args(argv):
    if len(argv) < 2:
        return None
    path = argv[1]
    template = None
    date = datetime.date.today().isoformat()
    title = os.path.splitext(os.path.basename(path))[0]
    sections = []  # [(name, [lines])]
    i = 2
    while i < len(argv):
        a = argv[i]
        if a == "--template" and i + 1 < len(argv):
            template = argv[i + 1]; i += 2
        elif a == "--date" and i + 1 < len(argv):
            date = argv[i + 1]; i += 2
        elif a == "--title" and i + 1 < len(argv):
            title = argv[i + 1]; i += 2
        elif a == "--section" and i + 1 < len(argv):
            sections.append((argv[i + 1].strip(), [])); i += 2
        elif a == "--line" and i + 1 < len(argv):
            if not sections:
                return None
            sections[-1][1].append(argv[i + 1].rstrip()); i += 2
        else:
            return None
    if not sections or any(not lines for _, lines in sections):
        return None
    return path, template, date, title, sections


def ensure_file(path, template, date, title):
    if os.path.exists(path):
        return True
    if not template or not os.path.exists(template):
        print(f"ERROR: {path} が無く、雛形も指定されていない（--template）")
        return False
    with open(template, encoding="utf-8") as f:
        body = f.read().replace("{{date}}", date).replace("{{title}}", title)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"CREATE {path}（雛形 {template}）")
    return True


def section_bounds(lines, name):
    """`## name` の見出し行の次から、次の `## ` 見出しの直前までの範囲 [start, end) を返す。無ければ None。"""
    header = f"## {name}"
    for i, l in enumerate(lines):
        if l.rstrip() == header:
            j = i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                j += 1
            return i, j
    return None


def insert_line(lines, name, new):
    b = section_bounds(lines, name)
    if b is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([f"## {name}", new])
        return "ADD(節を新設)"
    start, end = b
    body = list(range(start + 1, end))
    # 重複
    for k in body:
        if lines[k].rstrip() == new:
            return "SKIP(同一行あり)"
    # 空欄の置換: `- 睡眠:` に対して `- 睡眠:6時間`
    prefix = new.split(":", 1)[0] + ":" if ":" in new else None
    if prefix:
        for k in body:
            if lines[k].rstrip() == prefix:
                lines[k] = new
                return "FILL(空欄を置換)"
    # 節末尾の `-` だけの行を置換
    last = None
    for k in body:
        if lines[k].strip():
            last = k
    if last is not None and lines[last].strip() == "-":
        lines[last] = new
        return "FILL(空の箇条書きを置換)"
    # 最後の非空行の直後に差し込む
    pos = (last + 1) if last is not None else start + 1
    lines.insert(pos, new)
    return "ADD"


def main(argv):
    parsed = parse_args(argv)
    if parsed is None:
        print(__doc__)
        return 2
    path, template, date, title, sections = parsed
    if not ensure_file(path, template, date, title):
        return 1
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    nl = "\r\n" if "\r\n" in text else "\n"   # 元ファイルの改行コードを保つ
    lines = text.replace("\r\n", "\n").split("\n")
    for name, new_lines in sections:
        for new in new_lines:
            result = insert_line(lines, name, new)
            print(f"{result}\t[{name}] {new}")
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(nl.join(lines).rstrip("\r\n") + nl)
    except OSError as e:
        print(f"ERROR: 書き込みに失敗: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
