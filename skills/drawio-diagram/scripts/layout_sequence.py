#!/usr/bin/env python3
"""シーケンス図のページ（layout: "sequence"）を .drawio の XML に変換する。layout_from_spec.py から呼ぶ。

ライフラインは draw.io の umlLifeline、活性区間はその子セル、メッセージは接続先を持つ線、
複合フラグメント（alt / loop / opt など）は umlFrame で出す。人が draw.io でライフラインを
横に動かしても、メッセージは接続先に追従する。

spec の形は ../references/spec-format.md の「シーケンス図」にある。単体では実行しない。
依存: 標準ライブラリのみ
"""
from xml.sax.saxutils import quoteattr

HEAD_H = 40          # 参加者の見出しの高さ
ROW = 40             # メッセージ1本の縦の間隔
SELF_ROW = 60        # 自己メッセージの縦の間隔
FRAG_HEAD = 35       # フラグメントの見出し帯
OPERAND_GAP = 30     # alt の区切り線から次のメッセージまで
FRAG_TAIL = 20
ACT_W = 10           # 活性区間の幅
FRAME_PAD = 15       # フラグメントの枠と参加者の見出しの間
SELF_W = 30          # 自己メッセージの横の張り出し
ACTOR_W = 30         # 人型の参加者のセル幅（ラベルはセルからはみ出して下に出る）

PART_STYLE = ("shape=umlLifeline;perimeter=lifelinePerimeter;whiteSpace=wrap;html=1;container=1;dropTarget=0;"
              "collapsible=0;recursiveResize=0;outlineConnect=0;portConstraint=eastwest;size=40;")
PART_SHAPES = {
    "process": "fillColor=#dae8fc;strokeColor=#6c8ebf;",
    # database は円柱にしない（ライフラインの size を円柱の蓋の高さとして読んでしまい、形が崩れる）。色で区別する
    # 人型は幅が狭いので、ラベルを人型の下に出す（ライフラインの線と重なるので白地を敷く）
    "actor": "participant=umlActor;verticalAlign=top;spacingTop=42;labelBackgroundColor=#ffffff;whiteSpace=nowrap;",
    "database": "fillColor=#e1d5e7;strokeColor=#9673a6;",
    "entity": "participant=umlEntity;verticalAlign=top;spacingTop=42;labelBackgroundColor=#ffffff;whiteSpace=nowrap;",
    "external": "dashed=1;fillColor=#f5f5f5;strokeColor=#666666;",
}
ACT_STYLE = ("html=1;points=[];perimeter=orthogonalPerimeter;outlineConnect=0;targetShapes=umlLifeline;"
             "portConstraint=eastwest;noLabel=1;fillColor=#ffffff;")
MSG_BASE = "edgeStyle=none;html=1;rounded=0;labelBackgroundColor=#ffffff;verticalAlign=bottom;"
MSG_TYPES = {
    "sync": "endArrow=block;endFill=1;",
    "async": "endArrow=open;endFill=0;",
    "reply": "endArrow=open;endFill=0;dashed=1;",
    "create": "endArrow=open;endFill=0;dashed=1;",
    "destroy": "endArrow=block;endFill=1;",
}
FRAME_STYLE = "shape=umlFrame;whiteSpace=wrap;html=1;pointerEvents=0;fillColor=none;width=60;height=20;seqDecor=1;"
GUARD_STYLE = "text;html=1;align=left;verticalAlign=middle;fontStyle=2;labelBackgroundColor=#ffffff;seqDecor=1;"
DESTROY_STYLE = "shape=umlDestroy;html=1;strokeWidth=2;noLabel=1;seqDecor=1;"
SEP_STYLE = "line;strokeWidth=1;dashed=1;html=1;fillColor=none;seqDecor=1;"
OPERATORS = ("alt", "opt", "loop", "par", "break", "critical", "ref")


class SeqError(ValueError):
    pass


def text_width(text):
    return sum(14 if ord(ch) > 0x2E7F else 8 for ch in text)


def fmt(v):
    return str(int(round(v)))


def operands(frag):
    if "operands" in frag:
        return frag["operands"]
    return [{"guard": frag.get("guard", ""), "steps": frag.get("steps", [])}]


class Sequence:
    def __init__(self, page):
        self.page = page
        self.parts = page.get("participants", [])
        if not self.parts:
            raise SeqError("participants が空")
        self.pid = {p["id"]: i for i, p in enumerate(self.parts)}
        if len(self.pid) != len(self.parts):
            raise SeqError("participants の id が重複している")
        self.steps = page.get("steps", [])
        self.warns = []
        self.msgs = []        # (message dict, y, 自己か)
        self.acts = []        # 活性区間 {"part", "start", "end", "depth", "call", "id"}
        self.frames = []      # (frag, x の対象の参加者集合, y_top, y_bottom, 区切り [(y, guard)], 入れ子の深さ)
        self.created = {}     # 参加者 → 見出しの y（create で途中から始まる）
        self.destroyed = {}   # 参加者 → ライフラインの終わりの y
        for p in self.parts:
            if p.get("shape", "process") not in PART_SHAPES:
                raise SeqError(f"参加者「{p['id']}」の shape=\"{p.get('shape')}\" は使えない。使える値: {', '.join(PART_SHAPES)}")
        self.validate(self.steps)

    def validate(self, steps):
        for s in steps:
            if "fragment" in s:
                if s["fragment"] not in OPERATORS:
                    raise SeqError(f"fragment=\"{s['fragment']}\" は使えない。使える値: {', '.join(OPERATORS)}")
                for p in s.get("covers", []):
                    if p not in self.pid:
                        raise SeqError(f"fragment の covers にある「{p}」が participants に無い")
                for op in operands(s):
                    self.validate(op.get("steps", []))
                continue
            for k in ("from", "to"):
                if s.get(k) not in self.pid:
                    raise SeqError(f"メッセージの {k}=\"{s.get(k)}\" が participants に無い")
            if s.get("type", "sync") not in MSG_TYPES:
                raise SeqError(f"メッセージ「{s['from']} → {s['to']}」の type=\"{s.get('type')}\" は使えない。"
                               f"使える値: {', '.join(MSG_TYPES)}")

    # ---------------------------------------------------------------- 縦方向（時系列）
    def walk(self, steps, y, stacks, depth):
        """steps を上から順に置き、次の y と、出口の活性スタックを返す"""
        for s in steps:
            if "fragment" in s:
                y, stacks = self.walk_fragment(s, y, stacks, depth)
            else:
                y = self.place_message(s, y, stacks)
        return y, stacks

    def walk_fragment(self, frag, y, stacks, depth):
        top = y
        y += FRAG_HEAD
        seps, exits, covered = [], [], set()
        ops = operands(frag)
        first_msg = len(self.msgs)
        inner_start = len(self.frames)
        for n, op in enumerate(ops):
            if n > 0:   # 区切り線を前の分岐の直後に引き、次のメッセージとの間をあける
                seps.append((y + 5, op.get("guard", "")))
                y += 5 + OPERAND_GAP - ROW / 2
            entry = {k: list(v) for k, v in stacks.items()}   # 各分岐は同じ入口の状態から評価する
            y, out = self.walk(op.get("steps", []), y, entry, depth + 1)
            exits.append(out)
        open_sets = [frozenset(a["id"] for v in out.values() for a in v) for out in exits]
        if len(set(open_sets)) > 1:
            self.warns.append(f"{frag['fragment']}「{ops[0].get('guard', '')}」の分岐ごとに、応答の済んだ呼び出しが違う。"
                              "応答の有無を分岐間でそろえるか、replyTo で対応を明示する")
        merged = {}
        for out in exits:   # どれかの分岐で開いたままの活性区間は、合流後も開いているとみなす
            for k, v in out.items():
                cur = merged.setdefault(k, [])
                for a in v:
                    if a not in cur:
                        cur.append(a)
        for k in merged:
            merged[k].sort(key=lambda a: a["depth"])
        for m, _, _ in self.msgs[first_msg:]:
            covered |= {m["from"], m["to"]}
        for f in self.frames[inner_start:]:
            covered |= f[1]
        covered |= set(frag.get("covers", []))
        if not covered:
            covered = set(self.pid)
        nest = 1 + max((f[5] for f in self.frames[inner_start:]), default=0)
        y += FRAG_TAIL
        self.frames.append((frag, covered, top, y - FRAG_TAIL / 2, seps, nest, ops[0].get("guard", "")))
        return y, merged

    def place_message(self, m, y, stacks):
        y += ROW / 2
        a, b, kind = m["from"], m["to"], m.get("type", "sync")
        me = {"msg": m, "y": y, "self": a == b, "src": None, "dst": None}
        me["src"] = stacks.get(a, [None])[-1] if stacks.get(a) else None
        if a == b:
            me["dst"] = me["src"]
            self.msgs.append((m, y, me))
            return y + SELF_ROW - ROW / 2
        if kind == "create":
            self.created[b] = y - HEAD_H / 2
        if kind == "reply":
            act = self.find_call(m, stacks)
            if act is None:
                self.warns.append(f"応答「{a} → {b}」（{m.get('label', '')}）に対応する呼び出しが見つからない。"
                                  "replyTo で呼び出しの id を指定する")
            else:
                me["src"] = act
                act["end"] = max(act["end"] or 0, y)
                st = stacks[a]
                del st[st.index(act):]   # 内側で応答の無かった呼び出しも一緒に閉じる
        if kind == "sync" and m.get("activate", True) is not False:
            depth = len(stacks.get(b, []))
            act = {"part": b, "start": y, "end": None, "depth": depth, "call": m, "id": f"act{len(self.acts)}"}
            self.acts.append(act)
            stacks.setdefault(b, []).append(act)
            me["dst"] = act
        else:
            me["dst"] = stacks.get(b, [None])[-1] if stacks.get(b) and kind not in ("create", "destroy") else None
        if kind == "destroy":
            self.destroyed[b] = y
        self.msgs.append((m, y, me))
        if kind == "create":   # 生成した参加者の見出しの下端まで次の要素を下げる
            return y + ROW / 2 + HEAD_H / 2
        return y + ROW / 2

    def find_call(self, m, stacks):
        st = stacks.get(m["from"], [])
        if m.get("replyTo"):
            return next((a for a in reversed(st) if a["call"].get("id") == m["replyTo"]), None)
        return next((a for a in reversed(st) if a["call"]["from"] == m["to"]), None)

    # ---------------------------------------------------------------- 横方向
    def columns(self):
        widths = [max(100, text_width(p.get("label", "")) + 30) for p in self.parts]
        self.cell_w = [HEAD_H if p.get("shape") == "entity" else ACTOR_W if p.get("shape") == "actor" else w
                       for p, w in zip(self.parts, widths)]
        n = len(self.parts)
        gaps = [(widths[i] + widths[i + 1]) / 2 + 40 for i in range(n - 1)]
        right_extra = [0] * n
        for m, _, me in self.msgs:
            i, j = sorted((self.pid[m["from"]], self.pid[m["to"]]))
            lw = text_width(m.get("label", "")) + 50
            if i == j:
                right_extra[i] = max(right_extra[i], SELF_W + lw)
                continue
            have = sum(gaps[i:j])
            if have < lw:
                for k in range(i, j):
                    gaps[k] += (lw - have) / (j - i)
        for i in range(n - 1):   # 自己メッセージのラベルが右の参加者にかからないように
            gaps[i] = max(gaps[i], right_extra[i] + widths[i + 1] / 2 + 10)
        max_nest = max((f[5] for f in self.frames), default=0)
        left = max_nest * (FRAME_PAD + 10) + widths[0] / 2 + 10
        cx = [left]
        for g in gaps:
            cx.append(cx[-1] + g)
        return widths, cx

    # ---------------------------------------------------------------- 書き出し
    def xml(self, idx):
        stacks = {}
        # 人型の参加者はラベルが人型の下に出るので、最初のメッセージを下げる
        first = HEAD_H + (45 if any(p.get("shape") in ("actor", "entity") for p in self.parts) else 20)
        y_end, _ = self.walk(self.steps, first, stacks, 0)
        for a in self.acts:
            if a["end"] is None:   # 応答の無い同期呼び出しには活性区間を描かない
                continue
            a["end"] = max(a["end"], a["start"] + 20)
        live = [a for a in self.acts if a["end"] is not None]
        for _, _, me in self.msgs:
            for k in ("src", "dst"):
                if me[k] is not None and me[k]["end"] is None:
                    me[k] = None
        widths, cx = self.columns()
        total = y_end + ROW / 2
        out = []
        name = self.page.get("name", f"ページ{idx}")
        out.append(f'  <diagram id="page{idx}" name={quoteattr(name)}>')
        out.append('    <mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" page="1" '
                   'pageWidth="1169" pageHeight="827"><root>')
        out.append('      <mxCell id="0"/><mxCell id="1" parent="0"/>')
        top_of = {}
        for i, p in enumerate(self.parts):
            y0 = self.created.get(p["id"], 0)
            y1 = self.destroyed.get(p["id"], total)
            top_of[p["id"]] = y0
            style = PART_STYLE + PART_SHAPES.get(p.get("shape", "process"), PART_SHAPES["process"])
            style = merge(style, user_style(self.page, p))
            out.append(f'      <mxCell id={quoteattr(p["id"])} value={quoteattr(p.get("label", ""))} '
                       f'style={quoteattr(style)} vertex="1" parent="1">'
                       f'<mxGeometry x="{fmt(cx[i] - self.cell_w[i] / 2)}" y="{fmt(y0)}" width="{fmt(self.cell_w[i])}" '
                       f'height="{fmt(y1 - y0)}" as="geometry"/></mxCell>')
        for a in live:
            i = self.pid[a["part"]]
            x = self.cell_w[i] / 2 - ACT_W / 2 + a["depth"] * (ACT_W * 0.6)
            out.append(f'      <mxCell id={quoteattr(a["part"] + "__" + a["id"])} value="" style={quoteattr(ACT_STYLE)} '
                       f'vertex="1" parent={quoteattr(a["part"])}>'
                       f'<mxGeometry x="{fmt(x)}" y="{fmt(a["start"] - top_of[a["part"]])}" width="{ACT_W}" '
                       f'height="{fmt(a["end"] - a["start"])}" as="geometry"/></mxCell>')
        self.emit_frames(out, widths, cx)
        for p, y in self.destroyed.items():   # 破棄したライフラインの終端に × を付ける
            i = self.pid[p]
            out.append(f'      <mxCell id={quoteattr(p + "__destroy")} value="" style={quoteattr(DESTROY_STYLE)} '
                       f'vertex="1" parent="1"><mxGeometry x="{fmt(cx[i] - 10)}" y="{fmt(y - 10)}" width="20" '
                       f'height="20" as="geometry"/></mxCell>')
        for n, (m, y, me) in enumerate(self.msgs):
            out.append(self.emit_message(n, m, y, me, cx, top_of))
        out.append('    </root></mxGraphModel>')
        out.append('  </diagram>')
        return out, self.warns

    def port(self, which, part, act, y, toward_right, top_of):
        """メッセージの端の接続先 id と、接続位置のスタイル。活性区間があればその側面、無ければライフラインの中心線"""
        if act is None:
            # ライフラインは高さが後から変わりうるので、上端からの距離（Dy）で位置を固定する
            return part, (f"{which}X=0.5;{which}Y=0;{which}Dx=0;{which}Dy={fmt(y - top_of[part])};"
                          f"{which}Perimeter=0;")
        fy = (y - act["start"]) / (act["end"] - act["start"])
        return f'{part}__{act["id"]}', (f"{which}X={1 if toward_right else 0};{which}Y={fy:.4g};"
                                         f"{which}Dx=0;{which}Dy=0;{which}Perimeter=0;")

    def emit_message(self, n, m, y, me, cx, top_of):
        a, b = m["from"], m["to"]
        kind = m.get("type", "sync")
        style = MSG_BASE + MSG_TYPES[kind]
        right = self.pid[b] >= self.pid[a]
        pts = ""
        if me["self"]:
            y2 = y + SELF_ROW - ROW
            src, st1 = self.port("exit", a, me["src"], y, True, top_of)
            dst, st2 = self.port("entry", a, me["src"], y2, True, top_of)
            base_x = cx[self.pid[a]] + (ACT_W / 2 + me["src"]["depth"] * ACT_W * 0.6 if me["src"] else 0)
            pts = (f'<Array as="points"><mxPoint x="{fmt(base_x + SELF_W)}" y="{fmt(y)}"/>'
                   f'<mxPoint x="{fmt(base_x + SELF_W)}" y="{fmt(y2)}"/></Array>')
            style += st1 + st2 + "align=left;verticalAlign=middle;spacingLeft=4;"
        else:
            src, st1 = self.port("exit", a, me["src"], y, right, top_of)
            if kind == "create":   # 生成されるライフラインは、見出しの横の中央で受ける
                dst, st2 = b, f"entryX={0 if right else 1};entryY=0;entryDx=0;entryDy={HEAD_H // 2};entryPerimeter=0;"
            else:
                dst, st2 = self.port("entry", b, me["dst"], y, not right, top_of)
            style += st1 + st2
        style = merge(style, user_style(self.page, m))
        eid = m.get("id") or f"m{n + 1}"
        return (f'      <mxCell id={quoteattr(eid)} value={quoteattr(m.get("label", ""))} style={quoteattr(style)} '
                f'edge="1" parent="1" source={quoteattr(src)} target={quoteattr(dst)}>'
                f'<mxGeometry relative="1" as="geometry">{pts}</mxGeometry></mxCell>')

    def emit_frames(self, out, widths, cx):
        for n, (frag, covered, top, bottom, seps, nest, guard) in enumerate(self.frames):
            idx = sorted(self.pid[p] for p in covered)
            pad = FRAME_PAD + (nest - 1) * 10
            x0 = cx[idx[0]] - widths[idx[0]] / 2 - pad
            x1 = cx[idx[-1]] + widths[idx[-1]] / 2 + pad
            fid = frag.get("id") or f"frag{n + 1}"
            out.append(f'      <mxCell id={quoteattr(fid)} value={quoteattr(frag["fragment"])} style={quoteattr(FRAME_STYLE)} '
                       f'vertex="1" parent="1"><mxGeometry x="{fmt(x0)}" y="{fmt(top)}" width="{fmt(x1 - x0)}" '
                       f'height="{fmt(bottom - top)}" as="geometry"/></mxCell>')
            if guard:
                out.append(self.text(f"{fid}__g0", f"[{guard}]", x0 + 66, top, x1 - x0 - 70))
            for k, (sy, g) in enumerate(seps, 1):
                out.append(f'      <mxCell id={quoteattr(f"{fid}__sep{k}")} value="" style={quoteattr(SEP_STYLE)} '
                           f'vertex="1" parent="1"><mxGeometry x="{fmt(x0)}" y="{fmt(sy - 5)}" width="{fmt(x1 - x0)}" '
                           f'height="10" as="geometry"/></mxCell>')
                if g:
                    out.append(self.text(f"{fid}__g{k}", f"[{g}]", x0 + 6, sy + 3, x1 - x0 - 10))

    @staticmethod
    def text(cid, value, x, y, w):
        return (f'      <mxCell id={quoteattr(cid)} value={quoteattr(value)} style={quoteattr(GUARD_STYLE)} '
                f'vertex="1" parent="1"><mxGeometry x="{fmt(x)}" y="{fmt(y)}" width="{fmt(max(w, 40))}" '
                f'height="20" as="geometry"/></mxCell>')


def merge(base, extra):
    from layout_from_spec import merge_style
    return merge_style(base, extra)


def user_style(page, it):
    from layout_from_spec import user_style as us
    return us(page, it)


def sequence_xml(page, idx):
    """1ページ分の XML の行と、WARN の一覧を返す"""
    return Sequence(page).xml(idx)
