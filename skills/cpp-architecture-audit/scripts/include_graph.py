#!/usr/bin/env python3
"""C/C++ の #include 依存グラフを機械抽出する。

使い方:
    python include_graph.py <ソースルート> [<ソースルート2> ...] [--top N]

対象拡張子: .c .cc .cpp .cxx .h .hh .hpp .hxx .inl
出力（標準出力・テキスト）:
    1. サマリ（ファイル数、依存エッジ数、循環の有無）
    2. 循環依存（強連結成分ごとに、構成ファイルを列挙）
    3. ファンイン上位 N（多くのファイルから include される = 変更影響が大きい）
    4. ファンアウト上位 N（多くを include する = 責務過多の疑い）

終了コード:
    0 = 正常終了（循環があっても 0。循環の有無は出力で判断する）
    2 = 引数エラー（ルートが存在しない等）

依存: 標準ライブラリのみ。
制約: プリプロセッサ条件 (#ifdef) は解釈しない。<> 形式の include は
      指定ルート内で解決できた場合のみエッジにする（システムヘッダは除外される）。
"""
import re
import sys
from pathlib import Path

EXTS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl"}
INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]')


def collect_sources(roots):
    files = {}
    for root in roots:
        for p in sorted(root.rglob("*")):
            if p.suffix.lower() in EXTS and p.is_file():
                files[p.resolve()] = root
    return files


def resolve_include(inc, src, roots, by_name):
    cand = (src.parent / inc).resolve()
    if cand in by_name:
        return cand
    for root in roots:
        cand = (root / inc).resolve()
        if cand in by_name:
            return cand
    tail = Path(inc).name.lower()
    matches = by_name.get(("name", tail), [])
    if len(matches) == 1:
        return matches[0]
    return None


def build_graph(files, roots):
    by_name = {p: True for p in files}
    names = {}
    for p in files:
        names.setdefault(("name", p.name.lower()), []).append(p)
    by_name.update(names)
    graph = {p: set() for p in files}
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"warn: 読めないファイルをスキップ: {p} ({e})", file=sys.stderr)
            continue
        for line in text.splitlines():
            m = INCLUDE_RE.match(line)
            if not m:
                continue
            target = resolve_include(m.group(1), p, roots, by_name)
            if target is not None and target != p:
                graph[p].add(target)
    return graph


def strongly_connected(graph):
    index = {}
    low = {}
    stack = []
    on_stack = set()
    sccs = []
    counter = [0]

    def strongconnect(v):
        work = [(v, iter(sorted(graph[v])))]
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        while work:
            node, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter[0]
                    counter[0] += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(sorted(graph[w]))))
                    advanced = True
                    break
                elif w in on_stack:
                    low[node] = min(low[node], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) > 1:
                    sccs.append(sorted(comp))

    for v in sorted(graph):
        if v not in index:
            strongconnect(v)
    return sccs


def rel(p, roots):
    for root in roots:
        try:
            return str(p.relative_to(root.resolve()))
        except ValueError:
            continue
    return str(p)


def main(argv):
    top_n = 15
    args = []
    it = iter(argv)
    for a in it:
        if a == "--top":
            try:
                top_n = int(next(it))
            except (StopIteration, ValueError):
                print("error: --top には整数を指定する", file=sys.stderr)
                return 2
        else:
            args.append(a)
    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    roots = []
    for a in args:
        r = Path(a)
        if not r.is_dir():
            print(f"error: ディレクトリが存在しない: {a}", file=sys.stderr)
            return 2
        roots.append(r)

    files = collect_sources(roots)
    graph = build_graph(files, roots)
    edges = sum(len(v) for v in graph.values())
    sccs = strongly_connected(graph)

    fan_in = {p: 0 for p in graph}
    for src, targets in graph.items():
        for t in targets:
            fan_in[t] += 1

    print(f"== サマリ ==")
    print(f"ファイル数: {len(files)} / 依存エッジ数: {edges} / 循環依存: {len(sccs)} 群")
    print()
    print(f"== 循環依存（強連結成分） ==")
    if not sccs:
        print("なし")
    for i, comp in enumerate(sorted(sccs, key=len, reverse=True), 1):
        print(f"[循環 {i}] {len(comp)} ファイル:")
        for p in comp:
            print(f"  - {rel(p, roots)}")
    print()
    print(f"== ファンイン上位 {top_n}（include される数。変更影響が大きい） ==")
    for p, n in sorted(fan_in.items(), key=lambda x: (-x[1], x[0]))[:top_n]:
        if n > 0:
            print(f"  {n:4d}  {rel(p, roots)}")
    print()
    print(f"== ファンアウト上位 {top_n}（include する数。責務過多の疑い） ==")
    for p, targets in sorted(graph.items(), key=lambda x: (-len(x[1]), x[0]))[:top_n]:
        if targets:
            print(f"  {len(targets):4d}  {rel(p, roots)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
