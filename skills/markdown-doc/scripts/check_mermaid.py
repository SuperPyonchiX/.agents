#!/usr/bin/env python3
"""Markdown の mermaid 図を実際に描いて、レイアウトの崩れを機械で拾う。

mermaid は配置をブラウザの中で決めるので、ソースを読んでも線がどこを通るかは分からない。
render_mermaid.cjs がヘッドレス Chromium で描いて箱・線・ラベルの座標を返し、ここで判定する。
問題のある図だけを1件1行で出す。画像は作らない（--png を付けたときだけ撮る）。

検査項目:
  ERROR PARSE    構文エラーで描けない
  ERROR THROUGH  線が、自分の始点・終点でない箱の内側を 8px 以上通っている
  WARN  GRAZE    線が、そういう箱の角や縁をかすめている（内側に入るのは 8px 未満）
  ERROR CLUSTER  線が、始点も終点も入っていないサブグラフの内側を横切っている
  ERROR TITLE    線が、サブグラフの見出しの文字の上を通っている
  ERROR OVERLAP  箱同士、箱とサブグラフの枠、サブグラフ同士が重なっている（入れ子は除く）
  ERROR LABEL    線のラベルが、箱・別のラベル・別の線に重なっている
  ERROR SAMELINE 始点も終点も異なる2本の線が、20px 以上同じところを通っている
  WARN  PARALLEL 2本の線が 8px 以内の間隔で 40px 以上並走している（二重線に見える。同じ箱につながる線も対象）
  ERROR CLIP     ラベルの文字が枠に収まっていない
  WARN  CLIPFONT --font で渡したフォントに差し替えると、ラベルの文字が枠からはみ出す（--font を付けたときだけ）
  WARN  CROSS    始点も終点も異なる線同士が交差している（図ごとに件数と例を1行）
  WARN  DETOUR   線が、始点と終点の直線距離の2倍を超えて遠回りしている

線と箱を取り出せるのは、mermaid が箱を g.node、線を data-edge の path で描く図
（flowchart・stateDiagram・classDiagram など）。sequenceDiagram などは PARSE と CLIP だけを見る。

使い方:
  python check_mermaid.py <file.md|file.mmd> [...] [--font "<CSS font-family>"] [--png <dir>]
                          [--deps <dir>] [--node <node の実行ファイル>]

  --font  読者の環境のフォント（例 "Meiryo"）。描いた後にこのフォントへ差し替えて、文字が枠に収まるかを測り直す。
          mermaid は描いた環境のフォントで枠の大きさを決めるので、閲覧先のフォントが違うと見切れる。
          差し替えの効果は検査する PC にそのフォントが入っているときだけ出る。--png の画像も差し替え後になる
  --png   各図を <dir>/<通し番号>-<ファイル名>-<行番号>.png に撮る。機械検査で判断がつかないときだけ使う
  --deps  playwright と mermaid を npm install した場所（その下の node_modules を探す）。
          省略時は環境変数 MERMAID_CHECK_DEPS、次に npm のグローバル（npm root -g）を探す

終了コード: 0 = ERROR なし（WARN のみも 0） / 1 = ERROR あり
          2 = 引数の誤り・ファイルが読めない・node / playwright / mermaid / Chromium が無い
外部への通信: しない。mermaid は npm で入れた手元のファイルを読み込み、描画するページからの通信は
render_mermaid.cjs がすべて遮断する。遮断した通信があれば WARN で件数を出す。
依存: Python は標準ライブラリのみ。別に Node.js と npm の playwright・mermaid（v11）、Playwright の Chromium
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
RENDERER = os.path.join(HERE, "render_mermaid.cjs")
INSTALL_HINT = """\
導入（1回だけ）:
  npm install -g playwright mermaid@11
  npx playwright install chromium
グローバルに入れたくなければ、任意のフォルダに入れて --deps で渡す:
  npm install --prefix <dir> playwright mermaid@11
  npx --prefix <dir> playwright install chromium"""

INSET = 3.0         # 箱の縁から内側へこの距離より深く入ったら「内側を通った」とみなす
MIN_GRAZE = 8.0     # 箱の内側をこの長さ以上通ったら THROUGH。これ未満は角をかすめただけ（GRAZE）
END_SNAP = 10.0     # 線の端からこの距離以内の箱を、その線の始点・終点とみなす
SAME_GAP = 2.0      # 2本の線がこの距離以内なら同じところを通っている
MIN_RUN = 20.0      # SAMELINE・CLUSTER とみなす長さ
PARALLEL_GAP = 8.0  # これ以内の間隔で並ぶ2本の線は二重線に見える
PARALLEL_RUN = 40.0
NEAR_END = 25.0     # 共通の箱からこの距離以内は、線が集まって当然なので PARALLEL を問わない
DETOUR_RATIO = 2.0
DETOUR_MIN = 120.0  # 直線距離との差がこれ未満の遠回りは問わない
FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*mermaid\b")


def extract(path):
    """(行番号, ソース) の一覧。.md は ```mermaid の中身、それ以外はファイル全体"""
    with open(path, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    if not path.lower().endswith((".md", ".markdown")):
        return [(1, "\n".join(lines))]
    out, i = [], 0
    while i < len(lines):
        m = FENCE.match(lines[i])
        if not m:
            i += 1
            continue
        fence, start, body = m.group(2), i + 2, []
        i += 1
        while i < len(lines) and not lines[i].strip().startswith(fence):
            body.append(lines[i])
            i += 1
        out.append((start, "\n".join(body)))
        i += 1
    return out


# ---- 幾何 ----

def inside(p, b, inset=INSET):
    return b[0] + inset < p[0] < b[0] + b[2] - inset and b[1] + inset < p[1] < b[1] + b[3] - inset


def dist_to_box(p, b):
    dx = max(b[0] - p[0], 0, p[0] - (b[0] + b[2]))
    dy = max(b[1] - p[1], 0, p[1] - (b[1] + b[3]))
    return math.hypot(dx, dy)


def overlap(a, b, tol=2.0):
    return (min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]) > tol
            and min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]) > tol)


def contains(outer, inner, tol=1.0):
    return (outer[0] - tol <= inner[0] and outer[1] - tol <= inner[1]
            and inner[0] + inner[2] <= outer[0] + outer[2] + tol
            and inner[1] + inner[3] <= outer[1] + outer[3] + tol)


def seg_dist(p, a, b):
    ax, ay = b[0] - a[0], b[1] - a[1]
    L = ax * ax + ay * ay
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / L))
    return math.hypot(p[0] - a[0] - t * ax, p[1] - a[1] - t * ay)


def poly_dist(p, pts):
    return min(seg_dist(p, pts[k], pts[k + 1]) for k in range(len(pts) - 1))


def seg_cross(p1, p2, q1, q2):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return d1 * d2 < 0 and d3 * d4 < 0


def length(pts):
    return sum(math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]) for k in range(len(pts) - 1))


def longest_run(flags, pts):
    """flags が True の連続区間のうち、最も長いものの長さ"""
    best = cur = 0.0
    for k in range(1, len(pts)):
        if flags[k] and flags[k - 1]:
            cur += math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])
            best = max(best, cur)
        else:
            cur = 0.0
    return best


def short(text, n=20):
    text = text or "（無題）"
    return text if len(text) <= n else text[:n] + "…"


# ---- 判定 ----

def endpoint(p, nodes, clusters):
    """線の端点 p につながる箱。('n', i) か ('c', i)。見つからなければ None"""
    best, key = END_SNAP, None
    for i, n in enumerate(nodes):
        d = dist_to_box(p, n["box"])
        if d <= best:
            best, key = d, ("n", i)
    if key:
        return key
    for i, c in enumerate(clusters):
        b = c["box"]
        d = min(abs(p[0] - b[0]), abs(p[0] - b[0] - b[2]), abs(p[1] - b[1]), abs(p[1] - b[1] - b[3]))
        if d <= best and dist_to_box(p, b) <= END_SNAP:
            best, key = d, ("c", i)
    return key


def check(r):
    """1枚分の座標から (重大度, コード, 説明) の一覧を返す"""
    if r.get("parseError"):
        lines = [x.strip() for x in r["parseError"].strip().splitlines() if x.strip()]
        # 先頭の「Parse error on line N:」と、末尾の「Expecting ..., got 'X'」の got だけを残す（間はソースの抜粋）
        msg = lines[0] if lines else "描けない"
        got = re.search(r"got '[^']*'", lines[-1]) if len(lines) > 1 else None
        if got:
            msg += " " + got.group(0)
        elif len(lines) > 1:
            msg += " " + lines[-1][:120]
        return [("ERROR", "PARSE", msg[:200])]
    found = []
    nodes, clusters, edges, labels = r.get("nodes", []), r.get("clusters", []), r.get("edges", []), r.get("labels", [])

    def name(key):
        if key is None:
            return "?"
        return short(nodes[key[1]]["label"] if key[0] == "n" else clusters[key[1]]["label"], 12)

    ends = []
    for e in edges:
        pts = e["points"]
        ends.append((endpoint(pts[0], nodes, clusters), endpoint(pts[-1], nodes, clusters)))

    def ename(k):
        return f"{name(ends[k][0])}→{name(ends[k][1])}"

    def inner_box(key):
        return nodes[key[1]]["box"] if key[0] == "n" else clusters[key[1]]["box"]

    for k, e in enumerate(edges):
        pts, (s, t) = e["points"], ends[k]
        mine = {x for x in (s, t) if x}
        for i, n in enumerate(nodes):
            if ("n", i) in mine:
                continue
            flags = [inside(p, n["box"]) for p in pts]
            if longest_run(flags, pts) >= MIN_GRAZE:
                found.append(("ERROR", "THROUGH", f"線 {ename(k)} が箱「{short(n['label'])}」の中を通っている"))
            elif any(flags):
                found.append(("WARN", "GRAZE", f"線 {ename(k)} が箱「{short(n['label'])}」の角・縁をかすめている"))
        for i, c in enumerate(clusters):
            if ("c", i) in mine:
                continue
            if c.get("title") and any(inside(p, c["title"], 0) for p in pts):
                found.append(("ERROR", "TITLE", f"線 {ename(k)} がサブグラフ「{short(c['label'])}」の見出しの上を通っている"))
            if any(contains(c["box"], inner_box(x)) for x in mine):
                continue
            run = longest_run([inside(p, c["box"]) for p in pts], pts)
            if run >= MIN_RUN:
                found.append(("ERROR", "CLUSTER",
                              f"線 {ename(k)} が無関係のサブグラフ「{short(c['label'])}」を {run:.0f}px 横切っている"))

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = nodes[i]["box"], nodes[j]["box"]
            if overlap(a, b) and not contains(a, b) and not contains(b, a):
                found.append(("ERROR", "OVERLAP", f"箱「{short(nodes[i]['label'])}」と「{short(nodes[j]['label'])}」が重なっている"))
    for i, c in enumerate(clusters):
        for n in nodes:
            if overlap(c["box"], n["box"]) and not contains(c["box"], n["box"]):
                found.append(("ERROR", "OVERLAP", f"箱「{short(n['label'])}」がサブグラフ「{short(c['label'])}」の枠にかかっている"))
        for j in range(i + 1, len(clusters)):
            a, b = c["box"], clusters[j]["box"]
            if overlap(a, b) and not contains(a, b) and not contains(b, a):
                found.append(("ERROR", "OVERLAP", f"サブグラフ「{short(c['label'])}」と「{short(clusters[j]['label'])}」が重なっている"))

    for li, lab in enumerate(labels):
        b = lab["box"]
        cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
        own = next((k for k, e in enumerate(edges) if lab.get("edge") and e.get("id") == lab["edge"]), None)
        if own is None and edges:
            own = min(range(len(edges)), key=lambda k: poly_dist((cx, cy), edges[k]["points"]))
        for n in nodes:
            if overlap(b, n["box"]):
                found.append(("ERROR", "LABEL", f"線のラベル「{short(lab['label'])}」が箱「{short(n['label'])}」に重なっている"))
        for other in labels[li + 1:]:
            if overlap(b, other["box"]):
                found.append(("ERROR", "LABEL", f"線のラベル「{short(lab['label'])}」と「{short(other['label'])}」が重なっている"))
        for k, e in enumerate(edges):
            if k != own and any(inside(p, b, 1) for p in e["points"]):
                found.append(("ERROR", "LABEL", f"線のラベル「{short(lab['label'])}」の上を線 {ename(k)} が通っている"))

    for c in r.get("clips", []):
        need, have = c["need"], c["have"]
        if c["phase"] == "render":
            found.append(("ERROR", "CLIP", f"「{short(c['label'])}」が枠に収まっていない（文字 {need[0]}×{need[1]}px > 枠 {have[0]}×{have[1]}px）"))
        else:
            found.append(("WARN", "CLIPFONT", f"「{short(c['label'])}」が読者側のフォントだとはみ出す（文字幅 {need[0]}px > 枠 {have[0]}px）"))

    for a in range(len(edges)):
        for b in range(a + 1, len(edges)):
            shared = [inner_box(x) for x in {x for x in ends[a] if x} & {x for x in ends[b] if x}]
            pa, pb = edges[a]["points"], edges[b]["points"]
            near = [all(dist_to_box(p, sb) > NEAR_END for sb in shared) and poly_dist(p, pb) <= PARALLEL_GAP
                    for p in pa]
            run = longest_run(near, pa)
            if run >= PARALLEL_RUN and not (not shared and longest_run(
                    [poly_dist(p, pb) <= SAME_GAP for p in pa], pa) >= MIN_RUN):
                found.append(("WARN", "PARALLEL", f"線 {ename(a)} と {ename(b)} が {run:.0f}px 並走して二重線に見える"))

    crosses = []
    for a in range(len(edges)):
        for b in range(a + 1, len(edges)):
            shared = {x for x in ends[a] if x} & {x for x in ends[b] if x}
            if shared:
                continue
            pa, pb = edges[a]["points"], edges[b]["points"]
            near = [poly_dist(p, pb) <= SAME_GAP for p in pa]
            run = longest_run(near, pa)
            if run >= MIN_RUN:
                found.append(("ERROR", "SAMELINE", f"線 {ename(a)} と {ename(b)} が {run:.0f}px 重なって見分けられない"))
                continue
            if any(seg_cross(pa[i], pa[i + 1], pb[j], pb[j + 1])
                   for i in range(len(pa) - 1) for j in range(len(pb) - 1)):
                crosses.append(f"{ename(a)} × {ename(b)}")
    if crosses:
        more = f" ほか {len(crosses) - 3} 件" if len(crosses) > 3 else ""
        found.append(("WARN", "CROSS", f"線の交差 {len(crosses)} 箇所: " + "、".join(crosses[:3]) + more))

    for k, e in enumerate(edges):
        pts = e["points"]
        if ends[k][0] and ends[k][0] == ends[k][1]:
            continue
        L = length(pts)
        D = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
        if L > DETOUR_RATIO * D and L - D >= DETOUR_MIN:
            found.append(("WARN", "DETOUR", f"線 {ename(k)} が遠回りしている（経路 {L:.0f}px / 直線 {D:.0f}px）"))
    return found


# ---- 実行 ----

def node_path(deps):
    paths = []
    for d in (deps, os.environ.get("MERMAID_CHECK_DEPS")):
        if d:
            paths.append(os.path.join(os.path.abspath(d), "node_modules"))
    npm = shutil.which("npm")
    if npm:
        try:
            root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True, timeout=60).stdout.strip()
            if root:
                paths.append(root)
        except (OSError, subprocess.SubprocessError):
            pass
    if os.environ.get("NODE_PATH"):
        paths.append(os.environ["NODE_PATH"])
    return os.pathsep.join(paths)


def render(diagrams, font, png, deps, node):
    env = dict(os.environ, NODE_PATH=node_path(deps))
    cmd = [node, RENDERER] + (["--png", os.path.abspath(png)] if png else [])
    payload = json.dumps({"diagrams": diagrams, "font": font}, ensure_ascii=False)
    try:
        proc = subprocess.run(cmd, input=payload.encode("utf-8"), capture_output=True, env=env, timeout=600)
    except subprocess.TimeoutExpired:
        return {"error": "runtime", "message": "600 秒で描き終わらなかった"}
    out = proc.stdout.decode("utf-8", "replace")
    try:
        data = json.loads(out)
    except ValueError:
        data = {"error": "runtime", "message": (out + proc.stderr.decode("utf-8", "replace")).strip()}
    return data


def main():
    ap = argparse.ArgumentParser(description="mermaid 図のレイアウトの崩れを検査する")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--font", default="")
    ap.add_argument("--png")
    ap.add_argument("--deps")
    ap.add_argument("--node")
    a = ap.parse_args()

    node = a.node or shutil.which("node")
    if not node:
        print("ERROR: Node.js が見つからない。https://nodejs.org/ から入れるか --node で場所を渡す\n" + INSTALL_HINT)
        return 2

    diagrams, where = [], {}
    for path in a.files:
        try:
            blocks = extract(path)
        except (OSError, UnicodeDecodeError) as e:
            print(f"ERROR: {path} を読めない: {e}")
            return 2
        stem = os.path.splitext(os.path.basename(path))[0]
        for line, src in blocks:
            did = f"{len(diagrams) + 1:02d}-{stem}-{line}"
            diagrams.append({"id": did, "src": src})
            where[did] = (path, line)
    if not diagrams:
        print("mermaid: 図なし")
        return 0

    data = render(diagrams, a.font, a.png, a.deps, node)
    if data.get("error") == "deps":
        print("ERROR: 見つからない npm パッケージ: " + ", ".join(data["missing"]) + "\n" + INSTALL_HINT)
        return 2
    if data.get("error"):
        msg = data.get("message", "")
        if "Executable doesn't exist" in msg or "playwright install" in msg:
            print("ERROR: Playwright の Chromium が入っていない\n" + INSTALL_HINT)
        else:
            print("ERROR: 描画に失敗した: " + msg[:400])
        return 2

    if data.get("blocked"):
        print(f"WARN: 描画中の外部への通信 {data['blocked']} 件を遮断した（図の表示に影響していないか --png で確かめる）")
    errors = warns = bad = 0
    for r in data["results"]:
        path, line = where[r["id"]]
        found = check(r)
        if not found:
            continue
        bad += 1
        kind = r.get("type") or "mermaid"
        for sev, code, msg in found:
            if code == "PARSE":
                m = re.search(r"line (\d+)", msg)
                if m:
                    line = line + int(m.group(1)) - 1
            print(f"{path}:{line} {kind} {sev} {code} {msg}")
            errors += sev == "ERROR"
            warns += sev == "WARN"
    if not bad:
        print(f"mermaid: {len(diagrams)} 枚を検査、問題なし")
        return 0
    print(f"mermaid: {len(diagrams)} 枚中 {bad} 枚に ERROR {errors} 件 / WARN {warns} 件")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
