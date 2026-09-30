#!/usr/bin/env python3
"""書き出した SVG から、実際に描かれた線の経路を取り出して配置の崩れを検査する。

check_drawio.py は XML の構造しか見ない。線の経路は draw.io が描画時に決めるので、
「線が関係ない箱を突き抜ける」「別々の線が同じ線分に重なって見分けられない」は
書き出した SVG を見ないと分からない。目視で見落としやすいので、機械で拾う。

検査項目（すべて ERROR）:
  THROUGH  線が、自分の source / target でもその入れ物でもない箱の内側を通っている
  INSIDE   線が、自分の source / target の四角い箱の内側を通っている（矢印が箱の中で止まる、箱の中を横断する）
  TOUCH    線が、そういう箱の縁に沿って走るか、4px 以内まで寄っている（枠線と重なって見分けられない）
  OVERLAP  source も target も異なる2本の線が、同じ直線上で 20px 以上重なっている
  HEADER   線が、スイムレーン・枠の見出し帯（名前が書かれた帯）を横切っている
  BORDER   線が、枠の辺に沿って 20px 以上走っている（枠線と見分けられない）
  LABEL    線のラベル同士が重なっている、線のラベルが別の線の上に乗っている、
           線のラベルが無関係の箱に重なっている、または自分の線の端（矢印の先端・出口）にかかっている

使い方:
  python export_drawio.py <file.drawio> -f svg [--page N]   # 先に SVG を書き出す
  python check_layout.py <file.drawio> <file.svg> [--page N]

  --page  .drawio の何ページ目と突き合わせるか（1 始まり。SVG を書き出したページと同じにする）

終了コード: 0 = 問題なし / 1 = 崩れあり / 2 = 引数の誤り・読めない・座標を対応づけられない
依存: 標準ライブラリのみ
"""
import argparse
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, __file__.rsplit("check_layout.py", 1)[0] or ".")
from check_drawio import load_models  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SVG = "{http://www.w3.org/2000/svg}"
INSET = 3.0        # 箱の縁から内側へこの距離より深く入ったら「突き抜け」
TOUCH_MARGIN = 4.0  # 箱の縁の外側この距離までに線が来たら「接触」
MIN_OVERLAP = 20.0
ARROW = 8.0         # 線の端からこの距離までにラベルが来たら、矢印や出口にかかっているとみなす


def cells_of(model):
    root = model.find("root")
    out = {}
    for obj in root.findall("object") + root.findall("UserObject"):
        c = obj.find("mxCell")
        if c is not None:
            c.set("id", obj.get("id", ""))
            out[c.get("id")] = c
    for c in root.findall("mxCell"):
        out[c.get("id")] = c
    return out


def abs_rects(cells):
    rects = {}

    def get(cid, depth=0):
        if cid in rects:
            return rects[cid]
        c = cells.get(cid)
        if c is None or c.get("vertex") != "1" or depth > 50:
            return None
        g = c.find("mxGeometry")
        if g is None:
            return None
        x, y = float(g.get("x", 0)), float(g.get("y", 0))
        w, h = float(g.get("width", 0)), float(g.get("height", 0))
        parent = get(c.get("parent"), depth + 1)
        if parent:
            x, y = x + parent[0], y + parent[1]
        rects[cid] = (x, y, w, h)
        return rects[cid]

    for cid in cells:
        get(cid)
    return rects


def ancestors(cells, cid):
    seen = set()
    cur = cells.get(cid)
    while cur is not None and cur.get("parent") not in (None, "0", "1") and cur.get("parent") not in seen:
        seen.add(cur.get("parent"))
        cur = cells.get(cur.get("parent"))
    return seen


def path_points(d):
    toks = re.findall(r"[MLCQZmlcqz]|-?\d+(?:\.\d+)?", d)
    pts, i, cmd = [], 0, None
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t.upper()
            i += 1
            continue
        n = {"M": 2, "L": 2, "Q": 4, "C": 6}.get(cmd, 2)
        nums = [float(v) for v in toks[i:i + n]]
        if len(nums) < n:
            break
        pts.append((nums[-2], nums[-1]))  # 曲線は終点だけ使う（近似）
        i += n
    return pts


def svg_groups(svg_path):
    root = ET.parse(svg_path).getroot()
    groups = {}
    for g in root.iter(f"{SVG}g"):
        cid = g.get("data-cell-id")
        if cid and cid not in groups:
            groups[cid] = g
    return groups


def find_offset(groups, rects):
    votes = {}
    for cid, (x, y, w, h) in rects.items():
        g = groups.get(cid)
        if g is None:
            continue
        for r in g.iter(f"{SVG}rect"):
            try:
                if abs(float(r.get("width")) - w) < 0.6 and abs(float(r.get("height")) - h) < 0.6:
                    key = (round(float(r.get("x")) - x), round(float(r.get("y")) - y))
                    votes[key] = votes.get(key, 0) + 1
                    break
            except (TypeError, ValueError):
                continue
    return max(votes, key=votes.get) if votes else None


def clip(p, q, rect, inset=INSET):
    """線分 pq が矩形の内側（inset だけ縮めたもの。負なら広げたもの）を通るか（Liang–Barsky）"""
    x, y, w, h = rect
    xmin, ymin, xmax, ymax = x + inset, y + inset, x + w - inset, y + h - inset
    if xmin >= xmax or ymin >= ymax:
        return False
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, p[0] - xmin), (dx, xmax - p[0]), (-dy, p[1] - ymin), (dy, ymax - p[1])):
        if pp == 0:
            if qq < 0:
                return False
        else:
            t = qq / pp
            if pp < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return t1 - t0 > 1e-6


def label_box(group):
    """ラベルの外接矩形。draw.io の SVG はラベル文字の代替画像を <switch> の中に置く"""
    for sw in group.iter(f"{SVG}switch"):
        for img in sw.iter(f"{SVG}image"):
            try:
                return (float(img.get("x")), float(img.get("y")),
                        float(img.get("width")), float(img.get("height")))
            except (TypeError, ValueError):
                return None
    return None


def box_overlap(a, b, shrink=1.0):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return (ax + shrink < bx + bw - shrink and bx + shrink < ax + aw - shrink and
            ay + shrink < by + bh - shrink and by + shrink < ay + ah - shrink)


def collinear_overlap(a, b):
    (a1, a2), (b1, b2) = a, b
    if abs(a1[1] - a2[1]) < 0.5 and abs(b1[1] - b2[1]) < 0.5 and abs(a1[1] - b1[1]) < 0.5:
        lo = max(min(a1[0], a2[0]), min(b1[0], b2[0]))
        hi = min(max(a1[0], a2[0]), max(b1[0], b2[0]))
        return hi - lo
    if abs(a1[0] - a2[0]) < 0.5 and abs(b1[0] - b2[0]) < 0.5 and abs(a1[0] - b1[0]) < 0.5:
        lo = max(min(a1[1], a2[1]), min(b1[1], b2[1]))
        hi = min(max(a1[1], a2[1]), max(b1[1], b2[1]))
        return hi - lo
    return 0.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("drawio")
    p.add_argument("svg")
    p.add_argument("--page", type=int, default=1)
    try:
        a = p.parse_args()
        models = load_models(a.drawio)
        page, model = models[a.page - 1]
        groups = svg_groups(a.svg)
    except SystemExit:
        return 2
    except (OSError, ET.ParseError, ValueError, IndexError) as e:
        print(f"ERROR  読めない: {e}")
        return 2

    cells = cells_of(model)
    rects = abs_rects(cells)
    off = find_offset(groups, rects)
    if off is None:
        print("ERROR  SVG と .drawio の座標を対応づけられない（ページ違い、または矩形の箱が1つも無い）")
        return 2
    rects = {k: (x + off[0], y + off[1], w, h) for k, (x, y, w, h) in rects.items()}
    containers = {c.get("parent") for c in cells.values()}

    edges = {}
    for cid, c in cells.items():
        if c.get("edge") != "1" or cid not in groups:
            continue
        path = next((e for e in groups[cid].iter(f"{SVG}path") if e.get("fill") == "none"), None)
        if path is None:
            continue
        pts = path_points(path.get("d", ""))
        edges[cid] = (c, [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)])

    round_shapes = ("rhombus", "ellipse", "cylinder", "umlActor", "triangle", "hexagon", "cloud", "doubleEllipse")
    problems = []
    for cid, (c, segs) in edges.items():
        for end in (c.get("source"), c.get("target")):
            st = (cells.get(end).get("style") or "") if cells.get(end) is not None else ""
            if end in rects and end not in containers and not any(s in st for s in round_shapes):
                if any(clip(s, t, rects[end]) for s, t in segs):
                    problems.append(f"INSIDE   線「{cid}」が接続先の箱「{end}」の内側を通っている")
        ends = {c.get("source"), c.get("target")}
        skip = set(ends)
        for e in ends:
            if e:
                skip |= ancestors(cells, e)
        for vid, r in rects.items():
            if vid in skip or vid in containers:
                continue
            label = (cells[vid].get("value") or vid).replace("<br>", " ")[:20]
            if any(clip(s, t, r) for s, t in segs):
                problems.append(f"THROUGH  線「{cid}」が箱「{vid}」（{label}）を突き抜けている")
            elif any(clip(s, t, r, -TOUCH_MARGIN) for s, t in segs):
                problems.append(f"TOUCH    線「{cid}」が箱「{vid}」（{label}）の縁に沿っているか触れている")

    ids = list(edges)
    for i, e1 in enumerate(ids):
        c1, s1 = edges[e1]
        for e2 in ids[i + 1:]:
            c2, s2 = edges[e2]
            if c1.get("source") == c2.get("source") or c1.get("target") == c2.get("target"):
                continue  # 同じ箱からの分岐・同じ箱への合流は重なってよい
            if any(collinear_overlap(x, y) >= MIN_OVERLAP for x in s1 for y in s2):
                problems.append(f"OVERLAP  線「{e1}」と「{e2}」が同じ線分上に重なっている")

    for vid in containers:
        c = cells.get(vid)
        if c is None or vid not in rects or "swimlane" not in (c.get("style") or ""):
            continue
        st = dict(kv.partition("=")[::2] for kv in c.get("style", "").split(";") if kv)
        band = float(st.get("startSize") or 23)
        x, y, w, h = rects[vid]
        hb = (x, y, band, h) if st.get("horizontal") == "0" else (x, y, w, band)
        for cid, (_, segs) in edges.items():
            if any(clip(s, t, hb, 1.0) for s, t in segs):
                problems.append(f"HEADER   線「{cid}」が枠「{vid}」の見出し帯を横切っている")

    for vid in containers:
        if vid not in rects:
            continue
        x, y, w, h = rects[vid]
        sides = [((x, y), (x + w, y)), ((x, y + h), (x + w, y + h)), ((x, y), (x, y + h)), ((x + w, y), (x + w, y + h))]
        for cid, (_, segs) in edges.items():
            hit = False
            for s, t2 in segs:
                for p1, p2 in sides:
                    horiz = abs(p1[1] - p2[1]) < 0.5
                    if horiz and abs(s[1] - t2[1]) < 0.5 and abs(s[1] - p1[1]) < 6:
                        lo, hi = max(min(s[0], t2[0]), p1[0]), min(max(s[0], t2[0]), p2[0])
                        hit |= hi - lo >= 20
                    elif not horiz and abs(s[0] - t2[0]) < 0.5 and abs(s[0] - p1[0]) < 6:
                        lo, hi = max(min(s[1], t2[1]), p1[1]), min(max(s[1], t2[1]), p2[1])
                        hit |= hi - lo >= 20
            if hit:
                problems.append(f"BORDER   線「{cid}」が枠「{vid}」の辺に沿って走っている")

    labels = {cid: label_box(groups[cid]) for cid in edges}
    labels = {k: v for k, v in labels.items() if v}
    lids = list(labels)
    for i, e1 in enumerate(lids):
        for e2 in lids[i + 1:]:
            if box_overlap(labels[e1], labels[e2]):
                problems.append(f"LABEL    線「{e1}」と「{e2}」のラベルが重なっている")
    for cid, lb in labels.items():
        for other, (_, segs) in edges.items():
            if other != cid and any(clip(s, t, lb, 1.0) for s, t in segs):
                problems.append(f"LABEL    線「{cid}」のラベルが線「{other}」の上に乗っている")
        own = edges[cid][1]
        if own:
            ex, ey, ew, eh = lb[0] - ARROW, lb[1] - ARROW, lb[2] + 2 * ARROW, lb[3] + 2 * ARROW
            if any(ex <= px <= ex + ew and ey <= py <= ey + eh for px, py in (own[0][0], own[-1][1])):
                problems.append(f"LABEL    線「{cid}」のラベルが線の端（矢印・出口）にかかっている。両端の箱の間を広げる")
        c = edges[cid][0]
        skip = {c.get("source"), c.get("target")}
        for e in list(skip):
            if e:
                skip |= ancestors(cells, e)
        for vid, r in rects.items():
            if vid not in skip and vid not in containers and box_overlap(lb, r):
                problems.append(f"LABEL    線「{cid}」のラベルが箱「{vid}」に重なっている")

    for m in problems:
        print(f"ERROR  [{page}] {m}")
    print(f"ページ「{page}」/ 線 {len(edges)} 本 / 崩れ {len(problems)} 件")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
