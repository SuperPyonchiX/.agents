#!/usr/bin/env python3
"""spec.json から .drawio を生成する。箱の位置は spec.json に従い、線の経路はこのスクリプトが決める。

モデルに線の経路（折れ点の座標）を決めさせると、箱の突き抜けや線の重なりが起きやすい。
このスクリプトは、箱と枠の見出し帯を避ける直交経路を探し、経由点まで固定して書き出す。
箱の位置は spec.json の at（座標）・near（相対位置）に従い、書かれていなければグリッドで自動に並べる。

使い方:
  python layout_from_spec.py <file.spec.json> -o <file.drawio>

spec.json の最小の形:
  {"name": "ページ名", "layout": "free",
   "nodes": [{"id": "a", "label": "A", "at": [0, 0]},
             {"id": "b", "label": "B", "near": {"right_of": "a"}}],
   "edges": [{"from": "a", "to": "b", "label": "要求"}]}
  キーの一覧（groups・shape・style・class・pos・order・from_side・via など）は
  ../references/spec-format.md にある。

終了コード: 0 = 生成した / 1 = 経路が見つからない線がある（生成はする。該当線は直線で引く） /
          2 = 引数の誤り・spec.json が読めない・参照先の無い id・at/near の誤り
依存: 標準ライブラリのみ
"""
import argparse
import heapq
import json
import sys
from xml.sax.saxutils import escape, quoteattr

sys.path.insert(0, __file__.rsplit("layout_from_spec.py", 1)[0] or ".")
from layout_sequence import sequence_xml  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SIZES = {
    "process": (140, 60), "decision": (140, 80), "start": (110, 50), "end": (110, 50),
    "document": (140, 70), "database": (110, 80), "external": (140, 60), "actor": (40, 70),
    "note": (140, 60), "text": (160, 30),
    "state": (140, 60), "initial": (30, 30), "final": (30, 30), "choice": (40, 40),
    "class": (160, 60), "entity": (160, 60),
}
STYLES = {
    "process": "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;",
    "decision": "rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;",
    "start": "ellipse;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;",
    "end": "ellipse;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;",
    "document": "shape=document;whiteSpace=wrap;html=1;boundedLbl=1;fillColor=#dae8fc;strokeColor=#6c8ebf;",
    "database": "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;size=12;fillColor=#dae8fc;strokeColor=#6c8ebf;",
    "external": "rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=#f5f5f5;strokeColor=#666666;",
    "actor": "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;",
    "note": "shape=note;whiteSpace=wrap;html=1;size=14;fillColor=#fff2cc;strokeColor=#d6b656;",
    "text": "text;html=1;align=center;verticalAlign=middle;",
    "state": "rounded=1;arcSize=40;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;",
    "initial": "ellipse;html=1;fillColor=#000000;strokeColor=#000000;",
    "final": "ellipse;shape=endState;html=1;fillColor=#000000;strokeColor=#000000;",
    "choice": "rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;",
    "class": ("swimlane;fontStyle=1;align=center;verticalAlign=top;childLayout=stackLayout;horizontal=1;"
              "startSize=26;horizontalStack=0;resizeParent=1;resizeParentMax=0;resizeLast=0;collapsible=0;"
              "marginBottom=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;"),
    "entity": ("swimlane;fontStyle=1;align=center;verticalAlign=top;childLayout=stackLayout;horizontal=1;"
               "startSize=26;horizontalStack=0;resizeParent=1;resizeParentMax=0;resizeLast=0;collapsible=0;"
               "marginBottom=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;"),
}
ROUND = ("decision", "start", "end", "database", "actor", "initial", "final", "choice")
FIXED = ("actor", "text", "initial", "final", "choice")   # ラベルの長さで幅を広げない形
LIST = ("class", "entity")   # 見出しの下に行を積む箱（クラス図・ER図）
ROW_H, SEP_H = 26, 8
ROW_STYLE = ("text;strokeColor=none;fillColor=none;align=left;verticalAlign=top;spacingLeft=4;spacingRight=4;"
             "overflow=hidden;rotatable=0;points=[[0,0.5],[1,0.5]];portConstraint=eastwest;whiteSpace=wrap;html=1;")
SEP_STYLE = ("line;strokeWidth=1;fillColor=none;align=left;verticalAlign=middle;spacingTop=-1;spacingLeft=3;"
             "spacingRight=3;rotatable=0;labelPosition=right;points=[];portConstraint=eastwest;strokeColor=inherit;")
# 線の種類（クラス図）。compose / aggregate は from が全体（ひし形の側）
EDGE_KINDS = {
    "inherit": "endArrow=block;endFill=0;endSize=12;",
    "realize": "endArrow=block;endFill=0;endSize=12;dashed=1;",
    "compose": "startArrow=diamondThin;startFill=1;startSize=14;endArrow=none;",
    "aggregate": "startArrow=diamondThin;startFill=0;startSize=14;endArrow=none;",
    "assoc": "endArrow=none;",
    "depend": "endArrow=open;endFill=0;dashed=1;",
}
# ER図の多重度（カラスの足）。card: [from 側, to 側]
CARD = {"1": "ERmandOne", "0..1": "ERzeroToOne", "1..*": "ERoneToMany", "0..*": "ERzeroToMany", "*": "ERmany"}


def text_width(text):
    """全角は 14px、半角は 8px として概算する"""
    return sum(14 if ord(ch) > 0x2E7F else 8 for ch in text)
COL_GAP, ROW_GAP = 100, 70
LANE_HEAD, BOX_HEAD, PAD = 40, 30, 30
HEAD_GAP = 20       # 見出し帯と中身の間に足す余白（見出し帯のすぐ下を線が通れるように）
MARGIN = 14          # 経路が箱から離れる距離
STUB = 12            # 出入口からまっすぐ出す長さ
BEND, OVERLAP_COST, NEAR_COST = 120.0, 5000.0, 60.0
CROSS_COST = 250.0   # 他の線との交差1か所あたり。交差が合流に見えるのを避けるため、多少の遠回りを選ばせる
NEAR = ("right_of", "left_of", "below", "above")
NEAR_GAP = 80        # near の既定の間隔（線とラベルが通れる幅）


class SpecError(Exception):
    pass


# ---------------------------------------------------------------- 配置

class Layout:
    def __init__(self, page):
        self.page = page
        self.direction = page.get("direction", "LR").upper()
        self.vlanes = page.get("lanes") == "vertical"
        if any(g.get("kind") == "lane" for g in page.get("groups", [])):
            # 横長のレーンは上下に積むので流れは左→右、縦長のレーンは左右に並べるので上→下に固定する
            self.direction = "TB" if self.vlanes else "LR"
        self.groups = {g["id"]: dict(g) for g in page.get("groups", [])}
        self.nodes = {n["id"]: dict(n) for n in page.get("nodes", [])}
        self.edges = [dict(e) for e in page.get("edges", [])]
        ids = list(self.groups) + list(self.nodes)
        if len(ids) != len(set(ids)):
            raise SpecError("groups と nodes の id が重複している")
        for item in list(self.groups.values()) + list(self.nodes.values()):
            if item.get("in") and item["in"] not in self.groups:
                raise SpecError(f"「{item['id']}」の in=\"{item['in']}\" が groups に無い")
        for n in self.nodes.values():
            if n.get("shape", "process") not in SIZES:
                raise SpecError(f"「{n['id']}」の shape=\"{n.get('shape')}\" は使えない。使える値: {', '.join(SIZES)}")
        for g in self.groups.values():
            if g.get("kind", "box") not in ("lane", "box"):
                raise SpecError(f"枠「{g['id']}」の kind=\"{g.get('kind')}\" は使えない。lane か box")
        for e in self.edges:
            for k in ("from", "to"):
                if e.get(k) not in self.nodes and e.get(k) not in self.groups:
                    raise SpecError(f"線の {k}=\"{e.get(k)}\" が nodes / groups に無い")
            for k in ("from_side", "to_side"):
                if e.get(k) and e[k] not in ("top", "bottom", "left", "right"):
                    raise SpecError(f"線「{e['from']} → {e['to']}」の {k}=\"{e[k]}\" は使えない。top / bottom / left / right")
        self.lanes = [g for g in self.groups.values() if g.get("kind") == "lane"]
        for g in self.lanes:
            if g.get("in"):
                raise SpecError(f"レーン「{g['id']}」は図全体の直下に置く（in を書かない）")
        self.children = {None: []}
        for gid in self.groups:
            self.children[gid] = []
        for item in list(self.groups.values()) + list(self.nodes.values()):
            self.children[item.get("in")].append(item["id"])
        order_ids = [i for o in page.get("order", []) for i in o.get("ids", [])]
        self.lanes.sort(key=lambda g: order_ids.index(g["id"]) if g["id"] in order_ids else len(order_ids))
        self.check_free(page.get("layout"))
        self.size = {}
        self.rel = {}      # 親の左上からの相対座標
        self.abs = {}

    def item(self, iid):
        return self.groups.get(iid) or self.nodes.get(iid)

    # --- 自由配置（at / near）
    def is_free(self, iid):
        it = self.item(iid)
        return "at" in it or "near" in it

    def check_free(self, layout):
        if layout not in (None, "free", "grid"):
            raise SpecError(f"layout=\"{layout}\" は使えない。free / grid / sequence")
        for parent, kids in self.children.items():
            kids = [k for k in kids if self.item(k).get("kind") != "lane"]
            free = [k for k in kids if self.is_free(k)]
            if layout == "free" and len(free) != len(kids):
                miss = [k for k in kids if k not in free]
                raise SpecError(f"layout=free では全要素に at か near を書く（無い: {', '.join(miss)}）")
            if free and len(free) != len(kids):
                where = f"枠「{parent}」" if parent else "図全体の直下"
                raise SpecError(f"{where}で at/near と pos（自動）が混ざっている。同じ枠の中ではどちらかにそろえる")
            for k in free:
                it = self.item(k)
                if "at" in it and "near" in it:
                    raise SpecError(f"「{k}」に at と near の両方がある。どちらか一方にする")
                if "near" in it:
                    rel = [d for d in NEAR if d in it["near"]]
                    if len(rel) != 1:
                        raise SpecError(f"「{k}」の near には {' / '.join(NEAR)} のどれか1つを書く")
                    base = it["near"][rel[0]]
                    if base not in kids:
                        raise SpecError(f"「{k}」の near の基準「{base}」は同じ枠の直下にある要素にする")

    def free_local(self, kids):
        """at / near の要素の、親の中身の原点からの位置を決める。戻り値は {id: (x, y)}。負の座標は 0 に寄せる"""
        pos = {}
        pending = list(kids)
        while pending:
            progressed = False
            for k in list(pending):
                it = self.item(k)
                w, h = self.size[k]
                if "at" in it:
                    pos[k] = (float(it["at"][0]), float(it["at"][1]))
                else:
                    rel = next(d for d in NEAR if d in it["near"])
                    base = it["near"][rel]
                    if base not in pos:
                        continue
                    bx, by = pos[base]
                    bw, bh = self.size[base]
                    gap = float(it["near"].get("gap", NEAR_GAP))
                    align = it["near"].get("align", "center")
                    frac = {"start": 0.0, "center": 0.5, "end": 1.0}.get(align)
                    if frac is None:
                        raise SpecError(f"「{k}」の near.align=\"{align}\" は使えない。start / center / end")
                    if rel in ("right_of", "left_of"):
                        x = bx + bw + gap if rel == "right_of" else bx - gap - w
                        y = by + (bh - h) * frac
                    else:
                        y = by + bh + gap if rel == "below" else by - gap - h
                        x = bx + (bw - w) * frac
                    pos[k] = (x, y)
                pending.remove(k)
                progressed = True
            if not progressed:
                raise SpecError(f"near の基準が循環している: {', '.join(pending)}")
        if pos:
            mx = min(x for x, _ in pos.values())
            my = min(y for _, y in pos.values())
            dx, dy = -min(mx, 0), -min(my, 0)
            pos = {k: (x + dx, y + dy) for k, (x, y) in pos.items()}
        return pos

    def free_extent(self, local):
        w = max((x + self.size[k][0] for k, (x, _) in local.items()), default=160)
        h = max((y + self.size[k][1] for k, (_, y) in local.items()), default=40)
        return w, h

    # --- 自動の pos
    def ranks(self):
        order = list(self.nodes) + list(self.groups)
        adj = {n: [] for n in order}
        for e in self.edges:
            if e["from"] in adj and e["to"] in adj:
                adj[e["from"]].append(e["to"])
        state, back = {}, set()

        def dfs(u):
            state[u] = 1
            for v in adj[u]:
                if state.get(v) == 1:
                    back.add((u, v))
                elif v not in state:
                    dfs(v)
            state[u] = 2

        sys.setrecursionlimit(10000)
        for n in order:
            if n not in state:
                dfs(n)
        rank = {n: 0 for n in order}
        for _ in range(len(order)):
            changed = False
            for u in order:
                for v in adj[u]:
                    if (u, v) not in back and rank[v] < rank[u] + 1:
                        rank[v] = rank[u] + 1
                        changed = True
            if not changed:
                break
        self.back = back
        return rank

    def apply_order(self):
        """order に書かれた兄弟（同じ枠の直下で pos の無いもの）は、その順に並べる"""
        for o in self.page.get("order", []):
            ids = [i for i in o.get("ids", []) if self.item(i) is not None]
            if len(ids) < 2 or len({self.item(i).get("in") for i in ids}) != 1:
                continue
            if any("pos" in self.item(i) for i in ids) or any(self.item(i).get("kind") == "lane" for i in ids):
                continue
            for n, i in enumerate(ids):
                self.item(i)["pos"] = [0, n] if o.get("axis", "y") == "y" else [n, 0]

    def auto_pos(self):
        self.apply_order()
        self.auto_ids = {k for k in list(self.groups) + list(self.nodes)
                         if "pos" not in self.item(k) and not self.is_free(k)}
        rank = self.ranks()
        lr = self.direction != "TB"
        if self.lanes:
            used = {}
            main_ax = 0 if lr else 1
            for lane in self.lanes:
                for cid in self.children[lane["id"]]:
                    it = self.item(cid)
                    if "pos" in it:
                        used.setdefault((lane["id"], it["pos"][main_ax]), set()).add(it["pos"][1 - main_ax])
            for lane in self.lanes:
                for cid in self.children[lane["id"]]:
                    it = self.item(cid)
                    if "pos" not in it and not self.is_free(cid):
                        col = rank.get(cid, 0)
                        rows = used.setdefault((lane["id"], col), set())
                        row = 0
                        while row in rows:
                            row += 1
                        rows.add(row)
                        it["pos"] = [col, row] if lr else [row, col]
            axis = 0 if lr else 1
            kids = [self.item(c) for l in self.lanes for c in self.children[l["id"]] if not self.is_free(c)]
            dense = {v: i for i, v in enumerate(sorted({k["pos"][axis] for k in kids}))}
            for k in kids:
                k["pos"][axis] = dense[k["pos"][axis]]
        for parent, kids in self.children.items():
            if parent is not None and self.groups[parent].get("kind") == "lane":
                continue
            if parent is None and self.lanes:
                continue
            free = [k for k in kids if "pos" not in self.item(k) and not self.is_free(k)]
            if not free:
                continue
            stack = "column" if parent is None and not lr else \
                (self.groups[parent].get("stack", "row") if parent else ("row" if lr else "column"))
            has_edges = any(e["from"] in free and e["to"] in free for e in self.edges)
            taken = {tuple(self.item(k)["pos"]) for k in kids if "pos" in self.item(k)}
            count = {}
            dense = {v: i for i, v in enumerate(sorted({rank.get(k, 0) for k in free}))}
            for k in free:
                main = dense[rank.get(k, 0)] if has_edges else None
                if main is None:
                    main = 0
                    while ((main, 0) if stack == "row" else (0, main)) in taken:
                        main += 1
                    pos = (main, 0) if stack == "row" else (0, main)
                else:
                    sub = count.get(main, 0)
                    pos = (main, sub) if stack == "row" else (sub, main)
                    while pos in taken:
                        sub += 1
                        pos = (main, sub) if stack == "row" else (sub, main)
                    count[main] = sub + 1
                taken.add(pos)
                self.item(k)["pos"] = list(pos)

    # --- 大きさと座標
    def grid(self, kids, col_w=None, row_h=None):
        """kids を pos で並べ、(列幅, 行高, 内容幅, 内容高) を返す。span を考慮する"""
        cw, rh = {}, {}
        spans = []
        for k in kids:
            c, r = self.item(k)["pos"]
            sc, sr = self.item(k).get("span", [1, 1])
            w, h = self.size[k]
            if sc == 1:
                cw[c] = max(cw.get(c, 0), w)
            if sr == 1:
                rh[r] = max(rh.get(r, 0), h)
            spans.append((k, c, r, sc, sr, w, h))
        if col_w:
            for c, w in col_w.items():
                cw[c] = max(cw.get(c, 0), w)
        if row_h:
            for r, h in row_h.items():
                rh[r] = max(rh.get(r, 0), h)
        for k, c, r, sc, sr, w, h in spans:
            for i in range(c, c + sc):
                cw.setdefault(i, 0)
            for j in range(r, r + sr):
                rh.setdefault(j, 0)
            if sc > 1:
                have = sum(cw[i] for i in range(c, c + sc)) + COL_GAP * (sc - 1)
                if have < w:
                    cw[c + sc - 1] += w - have
            if sr > 1:
                have = sum(rh[j] for j in range(r, r + sr)) + ROW_GAP * (sr - 1)
                if have < h:
                    rh[r + sr - 1] += h - have
        ncol = max(cw) + 1 if cw else 0
        nrow = max(rh) + 1 if rh else 0
        for i in range(ncol):
            cw.setdefault(i, 0)
        for j in range(nrow):
            rh.setdefault(j, 0)
        width = sum(cw.values()) + COL_GAP * max(0, ncol - 1)
        height = sum(rh.values()) + ROW_GAP * max(0, nrow - 1)
        return cw, rh, width, height

    def place(self, kids, cw, rh, ox, oy):
        xs, ys = {}, {}
        x = ox
        for i in sorted(cw):
            xs[i] = x
            x += cw[i] + COL_GAP
        y = oy
        for j in sorted(rh):
            ys[j] = y
            y += rh[j] + ROW_GAP
        for k in kids:
            c, r = self.item(k)["pos"]
            sc, sr = self.item(k).get("span", [1, 1])
            w, h = self.size[k]
            cell_w = sum(cw[i] for i in range(c, c + sc)) + COL_GAP * (sc - 1)
            cell_h = sum(rh[j] for j in range(r, r + sr)) + ROW_GAP * (sr - 1)
            if k in self.groups:   # 枠はセルいっぱいに広げず、左上に置く
                self.rel[k] = (xs[c], ys[r])
            else:
                self.rel[k] = (xs[c] + (cell_w - w) / 2, ys[r] + (cell_h - h) / 2)

    def list_size(self, n, w):
        """クラス・エンティティの大きさ。見出し＋属性の行＋（操作があれば）区切り線と操作の行"""
        fields, methods = n.get("fields", []), n.get("methods", [])
        lines = [n.get("label", "")] + fields + methods
        if "size" not in n:
            w = max(w, min(max(text_width(t) for t in lines) + 24, 400))
        h = ROW_H + ROW_H * len(fields) + (SEP_H + ROW_H * len(methods) if methods else 0)
        return w, max(h, ROW_H + SEP_H)

    def measure(self, gid):
        for k in self.children[gid]:
            if k in self.groups:
                self.measure(k)
            else:
                shape = self.nodes[k].get("shape", "process")
                w, h = self.nodes[k].get("size", SIZES.get(shape, SIZES["process"]))
                fixed = "size" in self.nodes[k]
                text = self.nodes[k].get("label", "").split("<br>")
                longest = max(len(s) for s in text) if text else 0
                need = 14 * longest + (60 if shape == "decision" else 24)
                if shape in LIST:
                    w, h = self.list_size(self.nodes[k], w)
                elif shape not in FIXED and need > w and not fixed:
                    w = min(need, 320)
                    if shape == "decision":
                        h = max(h, int(w * 0.5))
                self.size[k] = (w, h)
        if gid is None:
            return
        kids = self.children[gid]
        if kids and self.is_free(kids[0]):
            local = self.free_local(kids)
            w, h = self.free_extent(local)
            self.groups[gid]["_free"] = local
        else:
            cw, rh, w, h = self.grid(kids) if kids else ({}, {}, 160, 40)
            self.stretch(kids, cw, rh)
            self.groups[gid]["_grid"] = (cw, rh)
        mw, mh = self.groups[gid].get("size", (0, 0))
        self.size[gid] = (max(w + PAD * 2, mw), max(h + BOX_HEAD + HEAD_GAP + PAD * 2, mh))

    def stretch(self, kids, cw, rh):
        """同じ列の枠は列幅に、同じ行の枠は行高にそろえ、中身を中央に寄せる"""
        for k in kids:
            if k not in self.groups or self.item(k).get("kind") == "lane":
                continue
            c, r = self.item(k)["pos"]
            sc, sr = self.item(k).get("span", [1, 1])
            w, h = self.size[k]
            nw = sum(cw[i] for i in range(c, c + sc)) + COL_GAP * (sc - 1)
            nh = sum(rh[j] for j in range(r, r + sr)) + ROW_GAP * (sr - 1)
            nw, nh = max(w, nw), max(h, nh)
            self.groups[k]["_offset"] = ((nw - w) / 2, (nh - h) / 2)
            self.size[k] = (nw, nh)

    def layout(self):
        self.auto_pos()
        self.place_all()
        if self.reorder():
            self.size, self.rel, self.abs = {}, {}, {}
            for g in self.groups.values():
                g.pop("_offset", None)
                g.pop("_grid", None)
                g.pop("_free", None)
            self.place_all()

    def reorder(self):
        """自動で並べた兄弟を、つながる相手の位置（重心）の順に並べ替える。変えたら True"""
        changed = False
        nbr = {}
        for e in self.edges:
            nbr.setdefault(e["from"], []).append(e["to"])
            nbr.setdefault(e["to"], []).append(e["from"])

        def desc(iid):
            out = [iid]
            for k in self.children.get(iid, []):
                out += desc(k)
            return out

        for parent, kids in self.children.items():
            auto = [k for k in kids if k in self.auto_ids]
            if len(auto) < 2 or (parent is None and self.lanes) or                     (parent and self.groups[parent].get("kind") == "lane"):
                continue
            rows = {}
            for k in auto:
                rows.setdefault(tuple(self.item(k)["pos"][1:] if True else ()), [])
            axis = 0 if len({self.item(k)["pos"][1] for k in auto}) == 1 else                 (1 if len({self.item(k)["pos"][0] for k in auto}) == 1 else None)
            if axis is None:
                continue
            inner = set(sum((desc(k) for k in auto), []))
            keyed = []
            for idx, k in enumerate(auto):
                pts = []
                for d in desc(k):
                    for o in nbr.get(d, []):
                        if o not in inner and o in self.abs:
                            x, y = self.abs[o]
                            w, h = self.size[o]
                            pts.append(x + w / 2 if axis == 0 else y + h / 2)
                keyed.append((sum(pts) / len(pts) if pts else None, idx, k))
            if all(v is None for v, _, _ in keyed):
                continue
            slots = sorted(self.item(k)["pos"][axis] for k in auto)
            known = sorted((v, i, k) for v, i, k in keyed if v is not None)
            order = [k for _, _, k in known]
            for v, i, k in keyed:   # 相手の無い箱は元の位置の近くに差し込む
                if v is None:
                    order.insert(min(i, len(order)), k)
            if order != auto:
                changed = True
                for k, s in zip(order, slots):
                    self.item(k)["pos"][axis] = s
        return changed

    def place_free(self, kids, ox, oy):
        local = self.free_local(kids)
        for k, (x, y) in local.items():
            self.rel[k] = (ox + x, oy + y)
        return self.free_extent(local)

    def place_block(self, kids, ox, oy, stretch=False):
        """枠の外（図全体の直下）の要素を置く。at/near ならその位置、そうでなければグリッド"""
        if not kids:
            return
        if self.is_free(kids[0]):
            self.place_free(kids, ox, oy)
            return
        cw, rh, _, _ = self.grid(kids)
        if stretch:
            self.stretch(kids, cw, rh)
        self.place(kids, cw, rh, ox, oy)

    def place_all(self):
        self.measure(None)
        if self.lanes:
            lane_kids = {l["id"]: self.children[l["id"]] for l in self.lanes}
            main = 1 if self.vlanes else 0   # レーンをまたいでそろえる軸（横長なら列、縦長なら行）
            shared = {}
            for kids in lane_kids.values():
                for k in kids:
                    if self.is_free(k):
                        continue
                    c = self.item(k)["pos"][main]
                    shared[c] = max(shared.get(c, 0), self.size[k][main])
            grids = {}
            for lid, kids in lane_kids.items():
                if kids and self.is_free(kids[0]):
                    local = self.free_local(kids)
                    grids[lid] = ("free", local) + self.free_extent(local)
                else:
                    cw, rh, w, h = self.grid(kids, None if self.vlanes else shared, shared if self.vlanes else None)
                    grids[lid] = ("grid", (cw, rh), w, h)
            if self.vlanes:
                ox, oy = PAD, LANE_HEAD + HEAD_GAP + PAD
                height = max(max(g[3] for g in grids.values()), 60) + LANE_HEAD + HEAD_GAP + PAD * 2
                pos = 0
                for lane in self.lanes:
                    kind, data, w, _ = grids[lane["id"]]
                    lane_w = max(w, 120) + PAD * 2
                    self.size[lane["id"]] = (lane_w, height)
                    self.rel[lane["id"]] = (pos, 0)
                    pos += lane_w
                end = (0, height + ROW_GAP)
            else:
                ox, oy = LANE_HEAD + PAD + HEAD_GAP, PAD
                width = max(g[2] for g in grids.values()) + LANE_HEAD + PAD * 2 + HEAD_GAP
                pos = 0
                for lane in self.lanes:
                    _, _, _, h = grids[lane["id"]]
                    lane_h = max(h, 60) + PAD * 2
                    self.size[lane["id"]] = (width, lane_h)
                    self.rel[lane["id"]] = (0, pos)
                    pos += lane_h
                end = (0, pos + ROW_GAP)
            for lane in self.lanes:
                kind, data, _, _ = grids[lane["id"]]
                kids = lane_kids[lane["id"]]
                if kind == "free":
                    for k, (x, y) in data.items():
                        self.rel[k] = (ox + x, oy + y)
                else:
                    self.place(kids, data[0], data[1], ox, oy)
            others = [k for k in self.children[None] if k not in lane_kids]
            self.place_block(others, end[0], end[1])
        else:
            self.place_block(self.children[None], 0, 0, stretch=True)
        for gid, g in self.groups.items():
            if g.get("kind") == "lane":
                continue
            if "_grid" in g:
                cw, rh = g["_grid"]
                ox, oy = g.get("_offset", (0, 0))
                self.place(self.children[gid], cw, rh, PAD + ox, BOX_HEAD + HEAD_GAP + PAD + oy)
            elif "_free" in g:
                for k, (x, y) in g["_free"].items():
                    self.rel[k] = (PAD + x, BOX_HEAD + HEAD_GAP + PAD + y)

        def absolute(iid):
            if iid in self.abs:
                return self.abs[iid]
            x, y = self.rel[iid]
            parent = self.item(iid).get("in")
            if parent:
                px, py = absolute(parent)
                x, y = x + px, y + py
            self.abs[iid] = (x, y)
            return self.abs[iid]

        for iid in self.rel:
            absolute(iid)

    def rect(self, iid):
        x, y = self.abs[iid]
        w, h = self.size[iid]
        return (x, y, w, h)


# ---------------------------------------------------------------- 経路

SIDES = {"right": (1, 0.5), "left": (0, 0.5), "top": (0.5, 0), "bottom": (0.5, 1)}
OUT = {"right": (1, 0), "left": (-1, 0), "top": (0, -1), "bottom": (0, 1)}


def inside(px, py, r, strict=True):
    x, y, w, h = r
    if strict:
        return x < px < x + w and y < py < y + h
    return x <= px <= x + w and y <= py <= y + h


class Router:
    def __init__(self, lay):
        self.lay = lay
        self.obstacles = []
        for nid in lay.nodes:
            x, y, w, h = lay.rect(nid)
            self.obstacles.append((nid, (x - MARGIN, y - MARGIN, w + MARGIN * 2, h + MARGIN * 2)))
        for gid, g in lay.groups.items():
            x, y, w, h = lay.rect(gid)
            if not lay.children[gid]:   # 中身の無い枠は箱と同じく避ける
                self.obstacles.append((gid, (x - MARGIN, y - MARGIN, w + MARGIN * 2, h + MARGIN * 2)))
                continue
            if g.get("kind") == "lane" and lay.vlanes:
                band = (x, y - 2, w, LANE_HEAD + 2 + MARGIN)
            elif g.get("kind") == "lane":
                band = (x - 2, y, LANE_HEAD + 2 + MARGIN, h)
            else:
                band = (x, y - 2, w, BOX_HEAD + 2 + MARGIN)
            self.obstacles.append((gid + "#head", band))
        self.routed = []   # (from, to, [points])
        self.borders = []  # 枠の辺。線を沿わせない（枠線と見分けられなくなる）
        for gid in lay.groups:
            x, y, w, h = lay.rect(gid)
            self.borders += [("h", y, x, x + w), ("h", y + h, x, x + w), ("v", x, y, y + h), ("v", x + w, y, y + h)]
        xs, ys = set(), set()
        for _, (x, y, w, h) in self.obstacles:
            xs.update((x, x + w))
            ys.update((y, y + h))
        allx = [r[0] for _, r in self.obstacles] + [r[0] + r[2] for _, r in self.obstacles]
        ally = [r[1] for _, r in self.obstacles] + [r[1] + r[3] for _, r in self.obstacles]
        self.frame = (min(allx) - 60, min(ally) - 60, max(allx) + 60, max(ally) + 60)
        for gid in lay.groups:   # 枠の辺の少し外側と内側にも経路の候補線を置く
            x, y, w, h = lay.rect(gid)
            xs.update((x - MARGIN * 1.5, x + MARGIN * 1.5, x + w - MARGIN * 1.5, x + w + MARGIN * 1.5))
            ys.update((y - MARGIN * 1.5, y + h - MARGIN * 1.5, y + h + MARGIN * 1.5))
        xs.update((self.frame[0], self.frame[2]))
        ys.update((self.frame[1], self.frame[3]))
        self.base_xs, self.base_ys = xs, ys

    def port(self, nid, side, frac=0.5):
        x, y, w, h = self.lay.rect(nid)
        if side in ("left", "right"):
            px = x + (w if side == "right" else 0)
            py = y + h * frac
            fx, fy = (1 if side == "right" else 0), frac
        else:
            px = x + w * frac
            py = y + (h if side == "bottom" else 0)
            fx, fy = frac, (1 if side == "bottom" else 0)
        dx, dy = OUT[side]
        return (px, py), (px + dx * (STUB + MARGIN), py + dy * (STUB + MARGIN)), (fx, fy)

    def blocked(self, ax, ay, bx, by, ignore):
        mx, my = (ax + bx) / 2, (ay + by) / 2
        for oid, r in self.obstacles:
            if oid in ignore:
                continue
            if inside(mx, my, r) or inside(ax, ay, r) or inside(bx, by, r):
                return True
        return False

    def seg_cost(self, a, b, src, dst):
        cost = 0.0
        for kind, c, lo, hi in self.borders:
            if kind == "h" and abs(a[1] - b[1]) < 0.01 and abs(a[1] - c) < 10:
                if min(max(a[0], b[0]), hi) - max(min(a[0], b[0]), lo) > 1:
                    cost += OVERLAP_COST / 2
            elif kind == "v" and abs(a[0] - b[0]) < 0.01 and abs(a[0] - c) < 10:
                if min(max(a[1], b[1]), hi) - max(min(a[1], b[1]), lo) > 1:
                    cost += OVERLAP_COST / 2
        for f, t, pts in self.routed:
            if f == src or t == dst:
                continue
            for p, q in zip(pts, pts[1:]):
                if a[1] == b[1] == p[1] == q[1]:
                    lo, hi = max(min(a[0], b[0]), min(p[0], q[0])), min(max(a[0], b[0]), max(p[0], q[0]))
                    if hi - lo > 1:
                        cost += OVERLAP_COST
                elif a[0] == b[0] == p[0] == q[0]:
                    lo, hi = max(min(a[1], b[1]), min(p[1], q[1])), min(max(a[1], b[1]), max(p[1], q[1]))
                    if hi - lo > 1:
                        cost += OVERLAP_COST
                elif (a[1] == b[1] and p[1] == q[1] and abs(a[1] - p[1]) < 8) or \
                        (a[0] == b[0] and p[0] == q[0] and abs(a[0] - p[0]) < 8):
                    cost += NEAR_COST
                elif crosses(a, b, p, q):
                    cost += CROSS_COST
        return cost

    def search(self, s, t, src, dst, ignore):
        xs = sorted(self.base_xs | {s[0], t[0]} | self.mids(self.base_xs | {s[0], t[0]}))
        ys = sorted(self.base_ys | {s[1], t[1]} | self.mids(self.base_ys | {s[1], t[1]}))
        xi = {x: i for i, x in enumerate(xs)}
        yi = {y: i for i, y in enumerate(ys)}
        if s[0] not in xi or s[1] not in yi or t[0] not in xi or t[1] not in yi:
            return None, float("inf")
        start = (xi[s[0]], yi[s[1]])
        goal = (xi[t[0]], yi[t[1]])
        pq = [(0.0, start, None)]
        best = {(start, None): 0.0}
        prev = {}
        while pq:
            c, (i, j), d = heapq.heappop(pq)
            if (i, j) == goal:
                pts = [(xs[i], ys[j])]
                key = ((i, j), d)
                while key in prev:
                    key = prev[key]
                    pts.append((xs[key[0][0]], ys[key[0][1]]))
                return simplify(pts[::-1]), c
            if c > best.get(((i, j), d), float("inf")):
                continue
            for nd, (di, dj) in enumerate(((1, 0), (-1, 0), (0, 1), (0, -1))):
                ni, nj = i + di, j + dj
                if not (0 <= ni < len(xs) and 0 <= nj < len(ys)):
                    continue
                a, b = (xs[i], ys[j]), (xs[ni], ys[nj])
                if self.blocked(a[0], a[1], b[0], b[1], ignore):
                    continue
                cost = c + abs(a[0] - b[0]) + abs(a[1] - b[1])
                if d is not None and d != nd:
                    cost += BEND
                cost += self.seg_cost(a, b, src, dst)
                key = ((ni, nj), nd)
                if cost < best.get(key, float("inf")):
                    best[key] = cost
                    prev[key] = ((i, j), d)
                    heapq.heappush(pq, (cost, (ni, nj), nd))
        return None, float("inf")

    def used_sides(self, nid):
        """引き終えた線のうち、この箱に付いている端がどの辺にあるか"""
        x, y, w, h = self.lay.rect(nid)
        out = set()
        for f, t, pts in self.routed:
            for end, p in ((f, pts[0]), (t, pts[-1])):
                if end != nid or f == t:
                    continue
                for side, hit in (("left", abs(p[0] - x) < 1), ("right", abs(p[0] - x - w) < 1),
                                  ("top", abs(p[1] - y) < 1), ("bottom", abs(p[1] - y - h) < 1)):
                    if hit:
                        out.add(side)
        return out

    def search_via(self, s, t, via, src, dst, ignore):
        """経由点を順に通る経路。経由点ごとに区切って探索し、つなぐ"""
        stops = [s] + [(float(x), float(y)) for x, y in via] + [t]
        pts, total = [], 0.0
        for a, b in zip(stops, stops[1:]):
            leg, cost = self.search(a, b, src, dst, ignore)
            if leg is None:
                return None, float("inf")
            pts += leg if not pts else leg[1:]
            total += cost
        return simplify(pts), total

    @staticmethod
    def mids(vals):
        v = sorted(vals)
        return {(a + b) / 2 for a, b in zip(v, v[1:]) if b - a > 2 * MARGIN}

    def candidates(self, e):
        if e["from"] == e["to"]:   # 自己遷移は箱の角を回る
            base = [("right", "top"), ("top", "left"), ("bottom", "right"), ("left", "bottom")]
        else:
            base = self.auto_candidates(e)
        fs, ts = e.get("from_side"), e.get("to_side")
        if not fs and not ts:
            return base
        picked = [c for c in base if (not fs or c[0] == fs) and (not ts or c[1] == ts)]
        return picked or [(a, b) for a in ([fs] if fs else SIDES) for b in ([ts] if ts else SIDES)]

    def auto_candidates(self, e):
        (sx, sy, sw, sh), (tx, ty, tw, th) = self.lay.rect(e["from"]), self.lay.rect(e["to"])
        dx = (tx + tw / 2) - (sx + sw / 2)
        dy = (ty + th / 2) - (sy + sh / 2)
        lr = self.lay.direction != "TB"
        back = (e["from"], e["to"]) in getattr(self.lay, "back", set())
        if back:
            return [("top", "top"), ("bottom", "bottom"), ("right", "top"), ("left", "left")] if lr else \
                   [("left", "left"), ("right", "right"), ("bottom", "left"), ("top", "top")]
        horiz = [("right", "left") if dx >= 0 else ("left", "right")]
        vert = [("bottom", "top") if dy >= 0 else ("top", "bottom")]
        mixed = [("right" if dx >= 0 else "left", "top" if dy >= 0 else "bottom"),
                 ("bottom" if dy >= 0 else "top", "left" if dx >= 0 else "right")]
        first = horiz + vert if abs(dx) >= abs(dy) else vert + horiz
        return first + mixed

    def route_one(self, e, sides=None, fracs=(0.5, 0.5)):
        src, dst = e["from"], e["to"]
        ignore = set()   # 両端の箱も避ける（出入口の直線部分は余白より長いので、探索の始点・終点は箱の外）
        best = (None, float("inf"), None)
        for ss, ts in ([sides] if sides else self.candidates(e)):
            sp, sstub, sf = self.port(src, ss, fracs[0])
            tp, tstub, tf = self.port(dst, ts, fracs[1])
            pts, cost = self.search_via(sstub, tstub, e.get("via", []), src, dst, ignore)
            if pts is None:
                continue
            if src == dst:   # 自己遷移は、他の線が付いていない辺を使う
                used = self.used_sides(src)
                cost += OVERLAP_COST * ((ss in used) + (ts in used))
            if cost < best[1]:
                best = ([sp] + pts + [tp], cost, (ss, ts, sf, tf))
        return best

    def route_all(self):
        order = sorted(self.lay.edges, key=lambda e: (e["from"], e["to"]) in getattr(self.lay, "back", set()))
        chosen = {}
        for e in order:
            pts, cost, info = self.route_one(e)
            if pts is None:
                chosen[id(e)] = None
                continue
            chosen[id(e)] = info
            self.routed.append((e["from"], e["to"], simplify(pts)))
        # 同じ辺に複数の線が付く四角い箱は、出入口をずらして引き直す
        uses = {}
        for e in order:
            info = chosen[id(e)]
            if not info:
                continue
            ss, ts = info[0], info[1]
            uses.setdefault((e["from"], ss), []).append((e, 0))
            uses.setdefault((e["to"], ts), []).append((e, 1))
        frac = {}
        for (nid, side), lst in uses.items():
            if len(lst) < 2 or self.lay.nodes.get(nid, {}).get("shape", "process") in ROUND or nid in self.lay.groups:
                continue
            loop = any(e["from"] == e["to"] for e, _ in lst)
            if len({end for _, end in lst}) == 1 and not loop:   # 全部入る線か全部出る線なら、1点にまとめて幹にする
                continue
            others = []
            for e, end in lst:
                other = e["to"] if end == 0 else e["from"]
                ox, oy, ow, oh = self.lay.rect(other)
                key = oy + oh / 2 if side in ("left", "right") else ox + ow / 2
                others.append((key, id(e), end))
            others.sort()
            for k, (_, eid, end) in enumerate(others):
                frac[(eid, end)] = (k + 1) / (len(others) + 1)
        self.routed = []
        result = {}
        failed = []
        for e in order:
            info = chosen[id(e)]
            if not info:
                failed.append(e)
                result[id(e)] = None
                continue
            fr = (frac.get((id(e), 0), 0.5), frac.get((id(e), 1), 0.5))
            pts, cost, info2 = self.route_one(e, (info[0], info[1]), fr)
            if pts is None:
                pts, cost, info2 = self.route_one(e)
            if pts is None:
                failed.append(e)
                result[id(e)] = None
                continue
            pts = simplify(pts)
            self.routed.append((e["from"], e["to"], pts))
            result[id(e)] = (pts, info2)
        return result, failed


def crosses(a, b, p, q):
    """直交する2本の線分が、どちらの端点でもない所で交わるか"""
    if a[1] == b[1] and p[0] == q[0]:
        h, v = (a, b), (p, q)
    elif a[0] == b[0] and p[1] == q[1]:
        h, v = (p, q), (a, b)
    else:
        return False
    x, y = v[0][0], h[0][1]
    return (min(h[0][0], h[1][0]) < x < max(h[0][0], h[1][0]) and
            min(v[0][1], v[1][1]) < y < max(v[0][1], v[1][1]))


def simplify(pts):
    out = []
    for p in pts:
        if out and abs(out[-1][0] - p[0]) < 0.01 and abs(out[-1][1] - p[1]) < 0.01:
            continue
        out.append(p)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        if (abs(a[0] - b[0]) < 0.01 and abs(b[0] - c[0]) < 0.01) or (abs(a[1] - b[1]) < 0.01 and abs(b[1] - c[1]) < 0.01):
            out.pop(i)
        else:
            i += 1
    return out


def seg_hits_box(a, b, box):
    x, y, w, h = box
    if abs(a[1] - b[1]) < 0.01:
        return y < a[1] < y + h and min(a[0], b[0]) < x + w and max(a[0], b[0]) > x
    return x < a[0] < x + w and min(a[1], b[1]) < y + h and max(a[1], b[1]) > y


def label_pos(pts, text, others, rects, borders):
    """ラベルの置き場所を選ぶ。戻り値は (線全体の中での相対位置 -1〜1, 横へのずらし量 dx, dy)。
    線分上の3か所と、その両脇を候補にし、他の線・箱・枠の境界に重ならないものを選ぶ"""
    lens = [abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(pts, pts[1:])]
    total = sum(lens) or 1
    lw, lh = 13 * len(text) + 10, 20
    best = None
    own = list(zip(pts, pts[1:]))
    for k, (a, b) in enumerate(own):
        horiz = abs(a[1] - b[1]) < 0.01
        for frac in (0.5, 0.3, 0.7):
            px, py = a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac
            sides = [(0, 0)] + ([(0, -(lh / 2 + 4)), (0, lh / 2 + 4)] if horiz else
                                [(-(lw / 2 + 6), 0), (lw / 2 + 6, 0)])
            for dx, dy in sides:
                box = (px + dx - lw / 2, py + dy - lh / 2, lw, lh)
                hits = sum(seg_hits_box(p, q, box) for seg in others for p, q in zip(seg, seg[1:]))
                hits += sum(1 for r in rects if not (box[0] + lw <= r[0] or r[0] + r[2] <= box[0] or
                                                     box[1] + lh <= r[1] or r[1] + r[3] <= box[1]))
                hits += sum(seg_hits_box(p, q, box) for p, q in borders)
                if dx or dy:   # 脇に置くなら、自分の他の線分とも重ねない
                    hits += sum(seg_hits_box(p, q, box) for j, (p, q) in enumerate(own) if j != k)
                short = lens[k] < (lw if horiz else lh) + 2 * STUB + 12   # ラベルが矢印や出入口にかかる
                score = (hits, short, 0 if not (dx or dy) else 1, abs(frac - 0.5), -lens[k] - 40 * k)
                if best is None or score < best[0]:
                    at = sum(lens[:k]) + lens[k] * frac
                    best = (score, round(2 * at / total - 1, 3), dx, dy)
    return best[1], best[2], best[3]


# ---------------------------------------------------------------- 書き出し

def fmt(v):
    return str(int(round(v)))


def merge_style(base, *extra):
    """draw.io のスタイル文字列を key=value 単位で後勝ちにマージする。値の無い語（rhombus など）は形の指定として先頭に置く"""
    words, kv = [], {}
    for st in (base,) + extra:
        for part in (st or "").split(";"):
            part = part.strip()
            if not part:
                continue
            k, eq, v = part.partition("=")
            if eq:
                kv[k] = v
            elif k not in words:
                words.append(k)
    if "shape" in kv:   # shape= を上書きしたら、既定の形の語（rhombus・ellipse など）は落とす
        words = [w for w in words if w in ("html", "text")]
    return "".join(f"{w};" for w in words) + "".join(f"{k}={v};" for k, v in kv.items())


def user_style(page, it):
    """要素の class（ページの styles を参照）と style を順に重ねた文字列"""
    classes = page.get("styles", {})
    names = it.get("class", [])
    names = [names] if isinstance(names, str) else names
    for n in names:
        if n not in classes:
            raise SpecError(f"「{it.get('id', it.get('from', '?'))}」の class=\"{n}\" がページの styles に無い")
    return ";".join([classes[n] for n in names] + [it.get("style", "")])


def page_xml(page, idx):
    global COL_GAP, ROW_GAP
    if page.get("layout") == "sequence":
        body, warns = sequence_xml(page, idx)
        for w in warns:
            print(f"WARN   [{page.get('name', idx)}] {w}")
        return body, []
    longest = max([len(e.get("label", "")) for e in page.get("edges", [])] + [0])
    COL_GAP = min(240, max(100, 13 * longest + 70))
    ROW_GAP = 70 if longest <= 4 else 90
    if "gap" in page:
        COL_GAP, ROW_GAP = (float(v) for v in page["gap"])
    lay = Layout(page)
    lay.layout()
    router = Router(lay)
    routes, failed = router.route_all()
    out = []
    name = page.get("name", f"ページ{idx}")
    out.append(f'  <diagram id="page{idx}" name={quoteattr(name)}>')
    out.append('    <mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" page="1" '
               'pageWidth="1169" pageHeight="827"><root>')
    out.append('      <mxCell id="0"/><mxCell id="1" parent="0"/>')
    emitted = set()
    borders = []
    for gid in lay.groups:
        x, y, w, h = lay.rect(gid)
        borders += [((x, y), (x + w, y)), ((x, y + h), (x + w, y + h)),
                    ((x, y), (x, y + h)), ((x + w, y), (x + w, y + h))]

    def emit(iid):
        if iid in emitted:
            return
        it = lay.item(iid)
        if it.get("in"):
            emit(it["in"])
        emitted.add(iid)
        x, y = lay.rel[iid]
        w, h = lay.size[iid]
        parent = it.get("in") or "1"
        if iid in lay.groups:
            if it.get("kind") == "lane":
                style = (f"swimlane;horizontal={1 if lay.vlanes else 0};startSize={LANE_HEAD};html=1;"
                         "fillColor=#f5f5f5;swimlaneFillColor=#ffffff;")
            else:
                style = f"swimlane;startSize={BOX_HEAD};html=1;rounded=1;horizontal=1;"
        else:
            style = STYLES.get(it.get("shape", "process"), STYLES["process"])
            if not it.get("label") and it.get("shape") in FIXED:
                style += "noLabel=1;"
        style = merge_style(style, user_style(page, it))
        out.append(f'      <mxCell id={quoteattr(iid)} value={quoteattr(it.get("label", ""))} '
                   f'style={quoteattr(style)} vertex="1" parent={quoteattr(parent)}>'
                   f'<mxGeometry x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" as="geometry"/></mxCell>')
        if it.get("shape") in LIST and iid in lay.nodes:
            emit_rows(iid, it, w)

    def emit_rows(iid, it, w):
        """クラス・エンティティの中の行。id は <箱の id>__f<番号>（属性）/ __sep / __m<番号>（操作）"""
        y = ROW_H
        rows = [(f"{iid}__f{i}", t, ROW_STYLE, ROW_H) for i, t in enumerate(it.get("fields", []))]
        if it.get("methods"):
            rows.append((f"{iid}__sep", "", SEP_STYLE, SEP_H))
            rows += [(f"{iid}__m{i}", t, ROW_STYLE, ROW_H) for i, t in enumerate(it["methods"])]
        for rid, text, st, h in rows:
            out.append(f'      <mxCell id={quoteattr(rid)} value={quoteattr(text)} style={quoteattr(st)} '
                       f'vertex="1" parent={quoteattr(iid)}>'
                       f'<mxGeometry y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" as="geometry"/></mxCell>')
            y += h

    for gid in [l["id"] for l in lay.lanes] + list(lay.groups) + list(lay.nodes):
        emit(gid)
    for n, e in enumerate(lay.edges):
        eid = e.get("id") or f"e_{e['from']}_{e['to']}" + (f"_{n}" if any(
            x is not e and x["from"] == e["from"] and x["to"] == e["to"] for x in lay.edges) else "")
        # 交差する箇所は後に描く線が弧で跳び越す（交差と合流を見分けられるように）
        style = "edgeStyle=none;rounded=0;html=1;endArrow=classic;labelBackgroundColor=#ffffff;jumpStyle=arc;jumpSize=10;"
        if e.get("dashed"):
            style += "dashed=1;"
        if e.get("both"):
            style += "startArrow=classic;"
        if e.get("kind"):
            if e["kind"] not in EDGE_KINDS:
                raise SpecError(f"線「{e['from']} → {e['to']}」の kind=\"{e['kind']}\" は使えない。使える値: {', '.join(EDGE_KINDS)}")
            style = merge_style(style, EDGE_KINDS[e["kind"]])
        if e.get("card"):
            ends = e["card"]
            if len(ends) != 2 or any(c not in CARD for c in ends):
                raise SpecError(f"線「{e['from']} → {e['to']}」の card は [from 側, to 側] で、値は {' / '.join(CARD)}")
            style = merge_style(style, f"startArrow={CARD[ends[0]]};startFill=0;startSize=10;"
                                       f"endArrow={CARD[ends[1]]};endFill=0;endSize=10;")
        r = routes.get(id(e))
        style = merge_style(style, user_style(page, e))
        geo = '<mxGeometry relative="1" as="geometry"/>'
        if r:
            pts, (ss, ts, sf, tf) = r
            # style で shape= を差し替えた箱は外接矩形と輪郭がずれるので、接続点を輪郭へ投影させる
            per = ["shape=" in user_style(page, lay.item(e[k])) for k in ("from", "to")]
            style += (f"exitX={sf[0]:.3g};exitY={sf[1]:.3g};exitDx=0;exitDy=0;exitPerimeter={int(per[0])};"
                      f"entryX={tf[0]:.3g};entryY={tf[1]:.3g};entryDx=0;entryDy=0;entryPerimeter={int(per[1])};")
            inner = "".join(f'<mxPoint x="{fmt(x)}" y="{fmt(y)}"/>' for x, y in pts[1:-1])
            lx, ldx, ldy = 0, 0, 0
            if e.get("label"):
                others = [q for f2, t2, q in router.routed if q is not pts]
                rects = [lay.rect(n) for n in lay.nodes]
                lx, ldx, ldy = label_pos(pts, e["label"], others, rects, borders)
            offset = f'<mxPoint x="{fmt(ldx)}" y="{fmt(ldy)}" as="offset"/>' if (ldx or ldy) else ""
            geo = (f'<mxGeometry x="{lx}" relative="1" as="geometry">'
                   + (f'<Array as="points">{inner}</Array>' if inner else "") + offset + '</mxGeometry>')
        out.append(f'      <mxCell id={quoteattr(eid)} value={quoteattr(e.get("label", ""))} '
                   f'style={quoteattr(style)} edge="1" parent="1" source={quoteattr(e["from"])} '
                   f'target={quoteattr(e["to"])}>{geo}</mxCell>')
    out.append('    </root></mxGraphModel>')
    out.append('  </diagram>')
    return out, [(name, e) for e in failed]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("spec")
    p.add_argument("-o", "--output", required=False)
    try:
        a = p.parse_args()
    except SystemExit:
        return 2
    try:
        spec = json.load(open(a.spec, encoding="utf-8"))
        pages = spec["pages"] if "pages" in spec else [spec]
        lines, failed = ["<mxfile>"], []
        for i, page in enumerate(pages, 1):
            body, f = page_xml(page, i)
            lines += body
            failed += f
        lines.append("</mxfile>")
    except (OSError, ValueError, KeyError, TypeError, SpecError) as e:
        print(f"ERROR  spec.json を処理できない: {e}")
        return 2
    out = a.output or a.spec.replace(".spec.json", "") + ".drawio"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    for name, e in failed:
        print(f"WARN   [{name}] 線「{e['from']} → {e['to']}」の経路が見つからない。箱の pos を離すか、枠の外に出す")
    print(f"OK     {out}（{len(pages)} ページ、経路なし {len(failed)} 本）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
