"""slidekit — python-pptx で「図解型」スライドを組むための部品集。

使い方（build_deck.py から import する）:

    import sys; sys.path.insert(0, "<スキルのディレクトリ>/scripts")
    from slidekit import Deck

    deck = Deck(theme="default")                 # assets/themes/<name>.json か JSON のパス
    s = deck.slide(chapter=1, kicker="章名",
                   title="結論文の中で[[変化点]]だけ朱にする",
                   source="出典: ...")
    s.before_after(before={...}, after={...})    # パターン関数（references/slidekit-api.md）
    s.action_band("次にやる1手を1文で")
    deck.save("out/deck.pptx")

約束ごと:
- 座標と寸法はすべてインチ（float）。スライドは 13.333 x 7.5 インチ（16:9）。
- 色は theme の色名（"primary", "accent_soft" など）か 6 桁の HEX。
- 文字列のマークアップ: [[語]] = 朱（accent）太字、{{語}} = 藍（primary）太字、\n = 改行。
- 図形名に接頭辞を付ける（TITLE / SOURCE / PAGE / T: / B:）。check_deck.py がこれを見る。

依存: python-pptx (>=0.6.21), lxml。無ければ導入方法を表示して終了コード 2 で止まる。
入力の不備（空の items、負の値、全部 0 の値、系列数の不一致）は ValueError で知らせる。
"""
import json
import math
import os
import re
import sys

try:
    from lxml import etree
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.dml import MSO_LINE_DASH_STYLE
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
    from pptx.oxml.ns import qn
    from pptx.util import Emu, Inches, Pt
except ImportError as e:  # build_deck.py から import されたときもここで止める
    print(f"python-pptx が読み込めない（{e}）。`pip install python-pptx` で導入してから再実行する。",
          file=sys.stderr)
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
THEME_DIR = os.path.normpath(os.path.join(HERE, "..", "assets", "themes"))

# ---- グリッド（インチ） -------------------------------------------------
SW, SH = 13.333, 7.5
MX = 0.65            # 左右マージン
BODY_TOP = 1.85      # 本文領域の上端
BODY_BOTTOM = 6.65   # 本文領域の下端
FOOT_RULE = 6.86     # 出典の上の罫線
BODY = (MX, BODY_TOP, SW - 2 * MX, BODY_BOTTOM - BODY_TOP)

_ALIGN = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}
_ANCHOR = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE, "bottom": MSO_ANCHOR.BOTTOM}
_MARK = re.compile(r"\[\[(.+?)\]\]|\{\{(.+?)\}\}")
_DASH = MSO_LINE_DASH_STYLE.DASH


def load_theme(theme):
    path = theme if str(theme).endswith(".json") else os.path.join(THEME_DIR, f"{theme}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _check_values(values, what, allow_zero=True):
    """数値リストの入口検査。空・非有限・負の値・全部 0 を ValueError にする。"""
    vals = list(values)
    if not vals:
        raise ValueError(f"{what}: 値が 1 つも無い")
    for v in vals:
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{what}: 数値でない・有限でない値 {v!r}")
        if v < 0:
            raise ValueError(f"{what}: 負の値 {v!r} は描けない（0 始まりの棒・面積のため）")
        if v == 0 and not allow_zero:
            raise ValueError(f"{what}: 0 は描けない")
    if max(vals) == 0:
        raise ValueError(f"{what}: 値がすべて 0 で、大きさを比べられない")
    return vals


def split_area(area, ratios, gap=0.35, direction="h"):
    """領域を比率で分割する。direction="h" で横並び、"v" で縦積み。戻り値は (x,y,w,h) のリスト。"""
    x, y, w, h = area
    total = sum(ratios)
    span = (w if direction == "h" else h) - gap * (len(ratios) - 1)
    out, cur = [], (x if direction == "h" else y)
    for r in ratios:
        size = span * r / total
        out.append((cur, y, size, h) if direction == "h" else (x, cur, w, size))
        cur += size + gap
    return out


class Deck:
    def __init__(self, theme="default"):
        self.theme = load_theme(theme)
        self.C = self.theme["colors"]
        self.S = self.theme["sizes"]
        self.font = self.theme["font"]
        self.prs = Presentation()
        self.prs.slide_width = Inches(SW)
        self.prs.slide_height = Inches(SH)
        self._layout = self.prs.slide_layouts[6]  # 白紙
        self.slides = []

    # ---- 共通 -----------------------------------------------------------
    def rgb(self, v):
        return RGBColor.from_string(self.C.get(v, v).lstrip("#").upper())

    def font_run(self, run, size, color, bold):
        f = run.font
        f.size = Pt(size)
        f.bold = bold
        f.color.rgb = self.rgb(color)
        rpr = run._r.get_or_add_rPr()
        rpr.set("lang", "ja-JP")  # 日本語の禁則処理を効かせる
        for tag in ("a:latin", "a:ea", "a:cs"):
            el = rpr.find(qn(tag))
            if el is None:
                el = etree.SubElement(rpr, qn(tag))
            el.set("typeface", self.font)

    def _new(self):
        sl = self.prs.slides.add_slide(self._layout)
        sl.background.fill.solid()
        sl.background.fill.fore_color.rgb = self.rgb("bg")
        return sl

    # ---- スライド生成 ----------------------------------------------------
    def slide(self, title, kicker=None, chapter=None, chapter_color="primary",
              source=None, notes=None, page=True):
        """通常スライド。タイトル・キッカー・出典・ページ番号を配置して Slide を返す。"""
        s = Slide(self, self._new())
        s.page = page
        s._header(title, kicker, chapter, chapter_color)
        s._footer(source)
        if notes:
            s.notes(notes)
        self.slides.append(s)
        return s

    def blank(self, page=True):
        """ヘッダー（キッカー・タイトル・出典）を自動で置かないスライド。自由配置したいときに使う。
        タイトルは不要になるわけではない。読者に見える結論文を
        s.text(..., name="TITLE") で自分で置く（置かないと check_deck.py が NO_TITLE を出す）。"""
        s = Slide(self, self._new())
        s.page = page
        self.slides.append(s)
        return s

    def cover(self, title, subtitle=None, series=None, pills=(), points=(), notes=None):
        """表紙。points = [(番号, 見出し, 補足, 色名), ...] を下段に並べる（全体の地図）。"""
        s = Slide(self, self._new())
        s.page = True
        if series:
            s.text(MX, 0.75, 8, 0.4, series, size=self.S["kicker"] + 2, color="sub", bold=True,
                   name="T:series")
        s.text(MX, 1.2, SW - 2 * MX, 1.1, title, size=self.S["cover_title"], bold=True,
               name="TITLE", line_spacing=1.05)
        y = 2.35
        if subtitle:
            s.text(MX, y, SW - 2 * MX, 0.75, subtitle, size=self.S["cover_title"] - 14,
                   color="primary", bold=True, name="T:subtitle")
            y += 0.95
        x = MX
        for i, p in enumerate(pills):
            text, color = (p if isinstance(p, tuple) else (p, "primary"))
            w = 0.3 + 0.19 * _width_units(text) * (16 / 12)
            s.pill(x, y, w, 0.55, text, fill="panel" if i == 0 else f"{color}_soft",
                   color="ink", line=color, size=16)
            x += w + 0.25
        if points:
            area = (MX, 4.5, SW - 2 * MX, 1.9)
            s.line(MX, 4.35, SW - MX, 4.35, color="rule", width=1)
            cols = split_area(area, [1] * len(points), gap=0.3)
            for (num, head, sub, color), (cx, cy, cw, ch) in zip(points, cols):
                s.badge(cx + 0.3, cy + 0.42, 0.6, str(num), fill=color, size=22)
                fit = (cw - 0.85) * 72 / max(_width_units(head) * 1.05, 1)  # 1行に収まる pt
                s.text(cx + 0.7, cy + 0.02, cw - 0.7, 0.8, head, size=max(14, min(16, int(fit))),
                       bold=True,
                       valign="middle", name=f"T:pt{num}")
                if sub:
                    s.text(cx + 0.7, cy + 0.85, cw - 0.7, 0.7, sub, size=self.S["small"],
                           color="sub", name=f"T:pt{num}sub")
        if notes:
            s.notes(notes)
        self.slides.append(s)
        return s

    def save(self, path):
        n = len(self.slides)
        for i, s in enumerate(self.slides, 1):
            if s.page:
                s.text(SW - MX - 1.4, 0.32, 1.4, 0.3, f"{i} / {n}", size=self.S["caption"],
                       color="muted", align="right", name="PAGE")
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        self.prs.save(path)
        return path


def _width_units(text):
    """全角=1、半角=0.55 として文字幅を概算する（レイアウト用の目安）。"""
    u = 0.0
    for ch in str(text):
        u += 1.0 if ord(ch) > 0x2E7F else 0.55
    return u


class Slide:
    def __init__(self, deck, sl):
        self.d = deck
        self.sl = sl
        self.shapes = sl.shapes
        self.page = True
        self._n = 0

    # ================================================================
    # 低レベル部品
    # ================================================================
    def _name(self, prefix, name):
        self._n += 1
        return name or f"{prefix}{self._n}"

    def _fill(self, shp, fill):
        if fill is None:
            shp.fill.background()
        else:
            shp.fill.solid()
            shp.fill.fore_color.rgb = self.d.rgb(fill)

    def _line(self, shp, line, lw, dash):
        if line is None:
            shp.line.fill.background()
        else:
            shp.line.color.rgb = self.d.rgb(line)
            shp.line.width = Pt(lw)
            if dash:
                shp.line.dash_style = _DASH

    def _write(self, tf, text, size, color, bold, align, valign, line_spacing=1.12,
               margin=(0.06, 0.03)):
        """text は str（マークアップ可）か、段落のリスト [[(文字, {size,color,bold}), ...], ...]。"""
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.NONE
        tf.margin_left = tf.margin_right = Inches(margin[0])
        tf.margin_top = tf.margin_bottom = Inches(margin[1])
        tf.vertical_anchor = _ANCHOR[valign]
        if isinstance(text, (list, tuple)) and text and isinstance(text[0], (list, tuple)):
            paras = text
        else:
            paras = []
            for ln in str(text).split("\n"):
                segs, pos = [], 0
                for m in _MARK.finditer(ln):
                    if m.start() > pos:
                        segs.append((ln[pos:m.start()], {}))
                    if m.group(1) is not None:
                        segs.append((m.group(1), {"color": "accent", "bold": True}))
                    else:
                        segs.append((m.group(2), {"color": "primary", "bold": True}))
                    pos = m.end()
                if pos < len(ln) or not segs:
                    segs.append((ln[pos:], {}))
                paras.append(segs)
        for i, segs in enumerate(paras):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = _ALIGN[align]
            p.line_spacing = line_spacing
            p.font.size = Pt(size)
            for seg, opt in segs:
                r = p.add_run()
                r.text = seg
                self.d.font_run(r, opt.get("size", size), opt.get("color", color),
                                opt.get("bold", bold))

    def shape(self, kind, x, y, w, h, fill=None, line=None, lw=1.25, dash=False, radius=None,
              text=None, size=None, color="ink", bold=False, align="center", valign="middle",
              name=None, line_spacing=1.12):
        shp = self.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
        _strip_style(shp)
        self._fill(shp, fill)
        self._line(shp, line, lw, dash)
        if radius is not None and kind == MSO_SHAPE.ROUNDED_RECTANGLE:
            shp.adjustments[0] = min(0.5, radius / max(min(w, h), 0.01))
        if text is not None and text != "":
            self._write(shp.text_frame, text, size or self.d.S["body"], color, bold, align,
                        valign, line_spacing)
        shp.name = self._name("B:", name)
        return shp

    def box(self, x, y, w, h, fill="panel", line=None, radius=0.12, **kw):
        """角丸の箱。text= を渡すと中に文字を書く。"""
        return self.shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, fill=fill, line=line,
                          radius=radius, **kw)

    def rect(self, x, y, w, h, fill="panel", line=None, **kw):
        return self.shape(MSO_SHAPE.RECTANGLE, x, y, w, h, fill=fill, line=line, **kw)

    def circle(self, cx, cy, d, fill="primary", line=None, **kw):
        return self.shape(MSO_SHAPE.OVAL, cx - d / 2, cy - d / 2, d, d, fill=fill, line=line, **kw)

    def text(self, x, y, w, h, text, size=None, color="ink", bold=False, align="left",
             valign="top", name=None, line_spacing=1.12):
        """枠なしの文字。check_deck.py のはみ出し判定の対象（名前が T: で始まる）。"""
        tb = self.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        self._write(tb.text_frame, text, size or self.d.S["body"], color, bold, align, valign,
                    line_spacing)
        self._n += 1
        if name in ("TITLE", "SOURCE", "PAGE"):
            tb.name = name
        else:
            base = (name or str(self._n))
            tb.name = base if base.startswith("T:") else "T:" + base
        return tb

    def pill(self, x, y, w, h, text, fill="primary", color="white", size=None, bold=True,
             line=None, lw=1.5, name=None):
        """両端が丸いラベル。章名・凡例・ボタン風の見出しに使う。"""
        return self.box(x, y, w, h, fill=fill, line=line, lw=lw, radius=h / 2, text=text,
                        size=size or self.d.S["small"], color=color, bold=bold, name=name)

    def badge(self, cx, cy, d, text, fill="primary", color="white", size=None, ring=None):
        """丸数字。章番号・手順番号に使う。ring= で白地に色の輪にする。"""
        if ring:
            return self.circle(cx, cy, d, fill="white", line=ring, lw=3, text=text,
                               size=size or d * 30, color=ring, bold=True)
        return self.circle(cx, cy, d, fill=fill, text=text, size=size or d * 30, color=color,
                           bold=True)

    def line(self, x1, y1, x2, y2, color="sub", width=1.5, dash=False, head=None, name=None):
        """直線。head="end" で終点に矢じり、"both" で両端。"""
        cx = self.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1),
                                       Inches(x2), Inches(y2))
        _strip_style(cx)
        cx.line.color.rgb = self.d.rgb(color)
        cx.line.width = Pt(width)
        if dash:
            cx.line.dash_style = _DASH
        if head:
            ln = cx.line._get_or_add_ln()
            if head == "both":
                he = etree.SubElement(ln, qn("a:headEnd"))
                he.set("type", "triangle")
            te = etree.SubElement(ln, qn("a:tailEnd"))
            te.set("type", "triangle")
            te.set("w", "med")
            te.set("len", "med")
        cx.name = self._name("L:", name)
        return cx

    def block_arrow(self, x, y, w, h, color="accent", direction="right", text=None, size=None):
        """太い矢印。Before→After の転換点など、1スライド1本まで。"""
        kind = {"right": MSO_SHAPE.RIGHT_ARROW, "down": MSO_SHAPE.DOWN_ARROW,
                "left": MSO_SHAPE.LEFT_ARROW, "up": MSO_SHAPE.UP_ARROW}[direction]
        return self.shape(kind, x, y, w, h, fill=color, text=text, size=size or 12,
                          color="white", bold=True)

    def tag(self, x, y, text="概念図", w=None):
        """小さな注記タグ（概念図 / 要公式確認 / 推定 など）。"""
        w = w or 0.35 + 0.16 * _width_units(text)
        return self.box(x, y, w, 0.32, fill="panel", line="rule", lw=1, radius=0.06, text=text,
                        size=self.d.S["caption"], color="sub", name=f"B:tag:{text}")

    def polyline(self, points, color="primary", width=3, fill=None, closed=False):
        """折れ線・曲線・多角形（points はインチ座標のリスト）。fill= で塗り多角形。"""
        pts = [(int(Inches(px)), int(Inches(py))) for px, py in points]
        b = self.shapes.build_freeform(pts[0][0], pts[0][1], scale=1.0)
        b.add_line_segments(pts[1:], close=closed)
        shp = b.convert_to_shape()
        _strip_style(shp)
        self._fill(shp, fill)
        self._line(shp, color, width, False)
        shp.name = self._name("F:", None)
        return shp

    def image(self, path, x, y, w, h, caption=None):
        """画像を置く。ファイルが無ければ破線の差し替え枠を置く（勝手に画像を探さない）。"""
        if path and os.path.exists(path):
            pic = self.shapes.add_picture(path, Inches(x), Inches(y), Inches(w), Inches(h))
        else:
            pic = self.box(x, y, w, h, fill="panel", line="muted", dash=True, radius=0.08,
                           text=caption or "画像差し替え", size=self.d.S["caption"], color="muted")
        return pic

    def notes(self, text):
        self.sl.notes_slide.notes_text_frame.text = text

    # ================================================================
    # ヘッダー・フッター・共通帯
    # ================================================================
    def _header(self, title, kicker, chapter, chapter_color):
        x = MX
        if chapter is not None:
            self.badge(MX + 0.2, 0.62, 0.4, str(chapter), fill=chapter_color, size=14)
            x = MX + 0.52
        if kicker:
            self.text(x, 0.45, 8, 0.36, kicker, size=self.d.S["kicker"], color="sub", bold=True,
                      valign="middle", name="T:kicker")
        self.text(MX, 0.9, SW - 2 * MX, 0.85, title, size=self.d.S["title"], bold=True,
                  valign="middle", name="TITLE", line_spacing=1.0)

    def _footer(self, source):
        if not source:
            return
        self.line(MX, FOOT_RULE, SW - MX, FOOT_RULE, color="rule", width=0.75, name="L:foot")
        self.text(MX, FOOT_RULE + 0.04, SW - 2 * MX - 1.0, 0.36, source, size=self.d.S["source"],
                  color="sub", valign="middle", name="SOURCE")

    def action_band(self, text, label="今やる1手", y=6.0, h=0.62, color="tertiary"):
        """スライド下部の行動帯。章の最後のスライドに置き、次の行動を1文で示す。"""
        self.box(MX, y, SW - 2 * MX, h, fill=f"{color}_soft", radius=0.12, name="B:band")
        lw = 0.45 + 0.2 * _width_units(label)
        self.pill(MX + 0.25, y + 0.1, lw, h - 0.2, label, fill=color, color="ink", size=15)
        self.text(MX + 0.45 + lw, y, SW - 2 * MX - lw - 0.6, h, text, size=19, bold=True,
                  valign="middle", name="T:band")

    def legend(self, items, x, y, size=None, gap=0.35):
        """色の凡例。items = [(色名, ラベル), ...] を横一列に並べる。"""
        size = size or self.d.S["small"]
        for color, label in items:
            self.box(x, y + 0.04, 0.26, 0.26, fill=color, radius=0.05, name=f"B:legend:{label}")
            w = 0.15 + _width_units(label) * size / 72 * 1.05
            self.text(x + 0.32, y - 0.02, w, 0.38, label, size=size, color="ink", bold=True,
                      valign="middle", name=f"T:legend:{label}")
            x += 0.32 + w + gap
        return x

    def side_panel(self, x, y, w, h, title, rows, color="tertiary"):
        """右サイドの補足パネル。rows = [(見出し, 大きい値, 補足), ...]（反応・数値など）。"""
        self.text(x, y, w, 0.4, title, size=self.d.S["small"] + 1, bold=True, name="T:sidetitle")
        n = len(rows)
        rh = (h - 0.5 - 0.15 * (n - 1)) / n
        cy = y + 0.5
        for head, value, sub in rows:
            cx = x
            self.box(cx, cy, w, rh, fill="panel", radius=0.1)
            self.rect(cx, cy + 0.12, 0.07, rh - 0.24, fill=color)
            self.text(cx + 0.2, cy + 0.08, w - 0.3, 0.32, head, size=self.d.S["caption"] + 1,
                      color="sub", name="T:side-h")
            self.text(cx + 0.2, cy + 0.38, w - 0.3, rh - 0.45,
                      [[(str(value), {"size": 30, "bold": True}),
                        ("  " + sub if sub else "", {"size": self.d.S["small"], "bold": True})]],
                      valign="top", name="T:side-v")
            cy += rh + 0.15

    # ================================================================
    # パターン（references/layout-patterns.md と 1:1 対応）
    # ================================================================
    @staticmethod
    def _area(area):
        return area or BODY

    def before_after(self, before, after, area=None, color="secondary", arrow=True):
        """P-BA: これまで → これから。before/after = {title, items, caption}。
        items を省略すると枠だけ描くので、戻り値の内側領域に自由に描ける。"""
        x, y, w, h = self._area(area)
        aw = 0.8 if arrow else 0.3
        pw = (w - aw - 0.3) / 2
        inner = {}
        for key, spec, px in (("before", before, x), ("after", after, x + pw + aw + 0.3)):
            soft = key == "after"
            self.box(px, y, pw, h, fill=f"{color}_soft" if soft else "panel",
                     line=None if soft else "rule", lw=1, radius=0.15)
            self.text(px + 0.3, y + 0.2, pw - 0.6, 0.5, spec.get("title", ""), size=20, bold=True,
                      name=f"T:{key}-title")
            iy, ih = y + 0.85, h - 0.85 - 0.25
            if spec.get("caption"):
                self.text(px + 0.3, y + h - 0.7, pw - 0.6, 0.45, spec["caption"], size=17,
                          bold=True, color=color if soft else "primary", align="center",
                          name=f"T:{key}-cap")
                ih -= 0.55
            inner[key] = (px + 0.3, iy, pw - 0.6, ih)
            items = spec.get("items") or []
            if items:
                rh = min(0.7, (ih - 0.15 * (len(items) - 1)) / len(items))
                for i, it in enumerate(items):
                    self.box(px + 0.3, iy + i * (rh + 0.15), pw - 0.6, rh,
                             fill="panel" if soft else "bg", line=color if soft else None,
                             lw=1, radius=0.1, text=it, size=17, align="left", bold=soft,
                             color=color if soft else "ink")
        if arrow:
            self.block_arrow(x + pw + 0.15, y + h / 2 - 0.35, aw, 0.7)
        return inner

    def card_columns(self, cards, area=None, footer_color="tertiary"):
        """P-CARD: 2〜4列の比較カード。card = {title, sub, color, chips, note, footer}。"""
        x, y, w, h = self._area(area)
        has_footer = any(c.get("footer") for c in cards)
        ch = h - (0.95 if has_footer else 0)
        cols = split_area((x, y, w, ch), [1] * len(cards), gap=0.35)
        for c, (cx, cy, cw, _) in zip(cards, cols):
            col = c.get("color", "secondary")
            self.box(cx, cy, cw, ch, fill="panel", line=col, lw=2, radius=0.15)
            hh = 1.15 if c.get("sub") else 0.8
            self.box(cx, cy, cw, hh, fill=col, radius=0.15)
            self.rect(cx, cy + hh - 0.2, cw, 0.2, fill=col)
            self.text(cx + 0.25, cy + 0.1, cw - 0.5, 0.6, c["title"], size=26, bold=True,
                      color="white", valign="middle", name="T:card-title")
            if c.get("sub"):
                self.text(cx + 0.25, cy + 0.65, cw - 0.5, 0.42, c["sub"], size=16, bold=True,
                          color="white", valign="middle", name="T:card-sub")
            iy = cy + hh + 0.25
            for chip in c.get("chips", []):
                self.box(cx + 0.25, iy, cw - 0.5, 0.58, fill=f"{col}_soft", radius=0.08,
                         text=chip, size=16, bold=True, color=col, align="left")
                iy += 0.7
            if c.get("note"):
                self.text(cx + 0.25, iy + 0.05, cw - 0.5, cy + ch - iy - 0.15, c["note"],
                          size=self.d.S["small"], color="sub", name="T:card-note")
            if c.get("footer"):
                self.line(cx + cw / 2, cy + ch, cx + cw / 2, cy + ch + 0.3, color=footer_color,
                          width=2)
                self.box(cx, cy + ch + 0.3, cw, 0.65, fill=footer_color, radius=0.1,
                         text=c["footer"], size=18, bold=True, color="ink")

    def timeline_events(self, events, start=None, end=None, area=None):
        """P-TL: 1本の時間軸に出来事を吹き出しで上下に並べる。
        event = {pos: 0..1, date, label, color, side: "up"|"down", highlight: bool}"""
        x, y, w, h = self._area(area)
        ly = y + h / 2
        self.line(x, ly, x + w, ly, color="ink", width=2)
        if start:
            self.text(x - 0.1, ly + 0.08, 1.2, 0.35, start, size=self.d.S["small"], color="sub",
                      name="T:tl-start")
        if end:
            self.text(x + w - 1.1, ly + 0.08, 1.2, 0.35, end, size=self.d.S["small"], color="sub",
                      align="right", name="T:tl-end")
        bh = 1.05
        sides = {"up": [], "down": []}
        for e in events:
            sides[e.get("side", "up")].append(e)
        n_side = max(len(v) for v in sides.values()) or 1
        bw = min(2.6, (w - 0.15 * (n_side - 1)) / n_side)
        place = {}
        for side, evs in sides.items():  # 同じ側の吹き出しが重ならないよう左から詰め、右端で押し戻す
            evs = sorted(evs, key=lambda e: e["pos"])
            xs, prev = [], x - 1
            for e in evs:
                bx = max(x + w * e["pos"] - bw / 2, x, prev + 0.15)
                xs.append(bx)
                prev = bx + bw
            over = xs[-1] + bw - (x + w) if xs else 0
            for k in range(len(xs) - 1, -1, -1):
                if over <= 0:
                    break
                xs[k] -= over
                if k and xs[k] < xs[k - 1] + bw + 0.15:
                    over = xs[k - 1] + bw + 0.15 - xs[k]
                else:
                    over = 0
            for e, bx in zip(evs, xs):
                place[id(e)] = bx
        for e in events:
            col = "accent" if e.get("highlight") else e.get("color", "primary")
            px = x + w * e["pos"]
            up = e.get("side", "up") == "up"
            by = y + 0.05 if up else y + h - bh - 0.05
            bx = place[id(e)]
            self.line(px, ly, min(max(px, bx + 0.2), bx + bw - 0.2), by + bh if up else by,
                      color=col, width=1.5)
            self.circle(px, ly, 0.22, fill=col)
            self.box(bx, by, bw, bh, fill="accent_soft" if e.get("highlight") else f"{col}_soft"
                     if f"{col}_soft" in self.d.C else "panel",
                     line="accent" if e.get("highlight") else None, lw=1.5, radius=0.08)
            self.rect(bx, by + 0.1, 0.07, bh - 0.2, fill=col)
            self.text(bx + 0.18, by + 0.06, bw - 0.25, 0.4, e["date"], size=16, bold=True,
                      color=col, name="T:tl-date")
            self.text(bx + 0.18, by + 0.44, bw - 0.25, bh - 0.5, e["label"], size=14, bold=True,
                      name="T:tl-label")

    def gantt(self, axis, rows, area=None, now=None, now_label=None, label_w=2.9):
        """P-GANTT: 行ごとに期間バー。axis = [(pos, ラベル)], row = {label, sub, bars:[(s,e,文字,style)]}。
        style: "solid" | "soft" | "fade"（左端がフェード=それ以前から）。"""
        x, y, w, h = self._area(area)
        tx, tw = x + label_w, w - label_w
        self.line(tx, y + 0.42, tx + tw, y + 0.42, color="ink", width=1.25)
        for pos, lab in axis:
            px = tx + tw * pos
            self.line(px, y + 0.36, px, y + 0.48, color="ink", width=1.25)
            self.text(px - 0.6, y, 1.2, 0.34, lab, size=self.d.S["small"] + 1, bold=True,
                      color="accent" if now is not None and abs(pos - now) < 1e-6 else "ink",
                      align="center", name="T:gantt-axis")
        n = len(rows)
        top = y + 0.6
        rh = (h - 0.6 - (0.45 if now_label else 0) - 0.12 * (n - 1)) / n
        for i, r in enumerate(rows):
            ry = top + i * (rh + 0.12)
            self.box(x, ry, w, rh, fill="panel", radius=0.08)
            self.text(x + 0.2, ry + 0.08, label_w - 0.3, rh * 0.55, r["label"], size=21, bold=True,
                      valign="middle", name="T:gantt-label")
            if r.get("sub"):
                self.text(x + 0.2, ry + rh * 0.55, label_w - 0.3, rh * 0.4, r["sub"],
                          size=self.d.S["small"], color="sub", name="T:gantt-sub")
            for s, e, txt, style in r.get("bars", []):
                bx, bw = tx + tw * s, tw * (e - s)
                bh = min(0.5, rh * 0.42)
                by = ry + (rh - bh) / 2
                col = r.get("color", "secondary")
                if style == "soft":
                    self.box(bx, by, bw, bh, fill=f"{col}_soft", line=col, lw=1, radius=0.06,
                             text=txt, size=14, bold=True, color="ink", align="left")
                else:
                    if style == "fade":
                        steps = 6
                        fw = min(bw * 0.3, 1.4)
                        for k in range(steps):
                            self.rect(bx + fw * k / steps, by, fw / steps + 0.01, bh,
                                      fill=_mix(self.d.C[col], self.d.C["panel"], 1 - (k + 1) / steps),
                                      name=f"B:fade{self._n}")
                        bx, bw = bx + fw, bw - fw
                    self.box(bx, by, bw, bh, fill=col, radius=0.06, text=txt, size=16, bold=True,
                             color="white", align="left" if style != "fade" else "right")
        if now is not None:
            px = tx + tw * now
            self.line(px, y + 0.42, px, top + n * (rh + 0.12) - 0.1, color="accent", width=2.5)
            if now_label:
                self.text(px - 4.0, y + h - 0.42, 4.0, 0.4, now_label, size=17, bold=True,
                          color="accent", align="right", name="T:gantt-now")

    def swimlane(self, axis, lanes, area=None, label_w=1.75):
        """P-LANE: 複数レーンの時系列（モデル / 製品 / 価格 など層ごとの動き）。
        axis = [(pos, ラベル)], lane = {label, color, events:[(pos, 文字, "up"|"down", 強調)]}
        強調: False=白抜き点 / True=塗り点 / "accent"=朱（そのスライドの主役の出来事だけ）"""
        x, y, w, h = self._area(area)
        tx, tw = x + label_w + 0.2, w - label_w - 0.4
        for pos, lab in axis:
            self.text(tx + tw * pos - 0.6, y, 1.2, 0.32, lab, size=self.d.S["small"] + 1,
                      bold=True, color="primary", align="center", name="T:lane-axis")
        n = len(lanes)
        top = y + 0.4
        lh = (h - 0.4 - 0.1 * (n - 1)) / n
        for i, ln in enumerate(lanes):
            col = ln.get("color", "primary")
            ly = top + i * (lh + 0.1)
            self.box(x, ly, w, lh, fill=f"{col}_soft", radius=0.1)
            self.pill(x + 0.15, ly + lh / 2 - 0.25, label_w - 0.1, 0.5, ln["label"], fill=col,
                      size=15)
            cy = ly + lh / 2
            self.line(tx, cy, tx + tw, cy, color=col, width=1.25)
            for ev in ln.get("events", []):
                pos, txt = ev[0], ev[1]
                side = ev[2] if len(ev) > 2 else "up"
                strong = ev[3] if len(ev) > 3 else False
                px = tx + tw * pos
                dot = "accent" if strong == "accent" else col
                if strong:
                    self.circle(px, cy, 0.2, fill=dot)
                else:
                    self.circle(px, cy, 0.2, fill="white", line=col, lw=2)
                ty = ly + 0.04 if side == "up" else cy + 0.12
                self.text(px - 0.05, ty, 2.6, lh / 2 - 0.14, txt, size=13, bold=True,
                          color="accent" if strong == "accent" else "ink",
                          valign="bottom" if side == "up" else "top", name="T:lane-ev")

    def matrix(self, cols, rows, area=None, label_w=3.3, group=None, right_note=None):
        """P-MATRIX: 行=対象、列=観点。row = {label, sub, cells:{列番号: 文字}}。
        group = {cols:(開始,終了), note} で列のまとまりを朱の枠で囲み、共通点を下に書く。"""
        x, y, w, h = self._area(area)
        note_h = 0.65 if (group or right_note) else 0
        gx, gw = x + label_w, w - label_w
        cw = gw / len(cols)
        self.text(x, y + 0.05, label_w, 0.5, "対象 ＼ 観点", size=self.d.S["small"], color="sub",
                  bold=True, valign="middle", name="T:mx-corner")
        for j, c in enumerate(cols):
            self.box(gx + j * cw + 0.06, y, cw - 0.12, 0.6, fill="primary", radius=0.08, text=c,
                     size=16, bold=True, color="white")
        n = len(rows)
        top = y + 0.72
        rh = (h - 0.72 - note_h - 0.1) / n
        for i, r in enumerate(rows):
            ry = top + i * rh
            if i:
                self.line(x, ry, x + w, ry, color="rule", width=0.75)
            self.text(x, ry + 0.04, label_w - 0.2, rh * 0.58, r["label"], size=19, bold=True,
                      valign="middle", name="T:mx-label")
            if r.get("sub"):
                self.text(x, ry + rh * 0.58, label_w - 0.2, rh * 0.38, r["sub"],
                          size=self.d.S["caption"] + 1, color="sub", name="T:mx-sub")
            for j in range(len(cols)):
                cx = gx + j * cw
                val = r.get("cells", {}).get(j)
                if val:
                    self.box(cx + 0.06, ry + 0.08, cw - 0.12, rh - 0.16, fill="primary",
                             radius=0.08, text=val, size=15, bold=True, color="white")
                else:
                    self.circle(cx + cw / 2, ry + rh / 2, 0.1, fill="rule")
        bottom = top + n * rh
        if group:
            a, b = group["cols"]
            fx = gx + a * cw - 0.02
            fw = (b - a + 1) * cw + 0.04
            self.box(fx, y - 0.1, fw, bottom - y + 0.15, fill=None, line="accent", lw=2.5,
                     radius=0.12)
            self.box(x, bottom + 0.17, fx + fw - x, note_h - 0.12, fill="panel", line="ink", lw=1.5,
                     radius=0.1, text=group["note"], size=18, bold=True)
            self.line(fx + fw / 2, bottom + 0.05, fx + fw / 2, bottom + 0.17, color="accent",
                      width=2.5, head="end")
        if right_note:
            sx = gx + (group["cols"][1] + 1) * cw if group else gx
            self.text(sx, bottom + 0.17, x + w - sx, note_h - 0.12, right_note, size=17,
                      bold=True, color="primary", align="center", valign="middle",
                      name="T:mx-right")

    def bar_ranking(self, items, area=None, baseline=None, baseline_label=None, highlight=0,
                    highlight_text=None, label_w=3.4, fmt="{:g}", max_value=None):
        """P-RANK: 横棒ランキング。items = [(ラベル, 値, 色名)]（色名は省略可）。
        baseline で中央値などの基準線を引く。highlight 番目を朱にする。"""
        x, y, w, h = self._area(area)
        n = len(items)
        vals = _check_values([it[1] for it in items], "bar_ranking の値")
        vmax = max_value or max(vals) * 1.12
        bx, bw = x + label_w + 0.15, w - label_w - 1.0
        rh = (h - (0.45 if baseline_label else 0.1)) / n
        for i, it in enumerate(items):
            lab, val = it[0], it[1]
            col = it[2] if len(it) > 2 else "primary"
            ry = y + i * rh
            hi = i == highlight
            self.text(x, ry, label_w, rh, lab, size=17, bold=True, color="accent" if hi else "ink",
                      align="right", valign="middle", name="T:rank-label")
            ln = bw * val / vmax
            fill = "accent" if hi else col
            soft = col.endswith("_soft")
            self.rect(bx, ry + rh * 0.18, ln, rh * 0.64, fill=fill, line="primary" if soft else None,
                      lw=1.25, text=highlight_text if hi and highlight_text else None, size=15,
                      bold=True, color="white")
            self.text(bx + ln + 0.08, ry, 0.9, rh, fmt.format(val), size=18, bold=True,
                      color="accent" if hi else "ink", valign="middle", name="T:rank-val")
        if baseline is not None:
            px = bx + bw * baseline / vmax
            self.line(px, y, px, y + n * rh, color="sub", width=1.25, dash=True)
            if baseline_label:
                self.text(px - 1.2, y + n * rh + 0.02, 2.4, 0.38, baseline_label,
                          size=self.d.S["caption"] + 1, color="sub", align="center",
                          name="T:rank-base")

    def column_compare(self, groups, series, area=None, callout=None, fmt="{:g}", unit=""):
        """P-COL: 縦棒の前後比較。groups = [(群ラベル, [値, 値, ...])]、series = [(凡例, 色名)]。
        callout = "2割安く" のような結論ラベル（朱）。"""
        x, y, w, h = self._area(area)
        if not groups:
            raise ValueError("column_compare: groups が空")
        for lab, vals in groups:
            if len(vals) != len(series):
                raise ValueError(f"column_compare: 群「{lab}」の値の数 {len(vals)} が "
                                 f"series の数 {len(series)} と違う")
        vmax = max(_check_values([v for _, vals in groups for v in vals],
                                 "column_compare の値")) * 1.18
        base = y + h - 0.95
        ph = base - (y + 0.55)
        gw = w / len(groups)
        ns = len(series)
        bw = min(0.95, gw * 0.7 / ns)
        for g, (lab, vals) in enumerate(groups):
            gx = x + g * gw + (gw - bw * ns - 0.12 * (ns - 1)) / 2
            for k, v in enumerate(vals):
                bh = ph * v / vmax
                col = series[k][1]
                self.rect(gx + k * (bw + 0.12), base - bh, bw, bh, fill=col,
                          line="tertiary" if col.endswith("_soft") else None, lw=1.25)
                self.text(gx + k * (bw + 0.12) - 0.05, base - bh - 0.45, bw + 0.1, 0.42,
                          f"{unit}{fmt.format(v)}", size=20, bold=True, align="center",
                          valign="bottom", name="T:col-val")
            self.text(x + g * gw, base + 0.08, gw, 0.4, lab, size=17, bold=True, align="center",
                      name="T:col-group")
        self.line(x + 0.1, base, x + w - 0.1, base, color="ink", width=1.5)
        self.legend([(c, l) for l, c in series], x + 0.2, y + h - 0.38)
        if callout:
            self.pill(x + 0.2, y, 0.5 + 0.24 * _width_units(callout), 0.52, callout, fill="accent",
                      size=18)

    def pyramid(self, tiers, area=None, side_notes=None, width_ratio=0.72):
        """P-PYR: 階層・使い分け。tiers は上から [(見出し, 補足, 色名)]。上ほど少数・重い。"""
        x, y, w, h = self._area(area)
        pw = w * width_ratio
        px = x + (w - pw) / 2 if not side_notes else x
        n = len(tiers)
        gap = 0.08
        th = (h - gap * (n - 1)) / n
        top_w = pw * 0.28
        for i, (head, sub, col) in enumerate(tiers):
            ty = y + i * (th + gap)
            wt = top_w + (pw - top_w) * (i / n)
            wb = top_w + (pw - top_w) * ((i + 1) / n)
            shp = self.shape(MSO_SHAPE.TRAPEZOID, px + (pw - wb) / 2, ty, wb, th, fill=col,
                             text=f"{head}\n{sub}" if sub else head, size=22, bold=True,
                             color="white" if not col.endswith("_soft") else "primary")
            shp.adjustments[0] = min(0.5 * wb / th, ((wb - wt) / 2) / min(wb, th))
            if sub:
                p2 = shp.text_frame.paragraphs[1]
                for r in p2.runs:
                    r.font.size = Pt(15)
        if side_notes:
            sx = px + pw + 0.3
            self.text(sx, y, x + w - sx, h, "\n".join(side_notes), size=16, bold=True,
                      color="primary", name="T:pyr-side")

    def hub_spoke(self, center, satellites, area=None, ring=None):
        """P-HUB: 勢力図・全体像。中心 = {title, items, badge}、satellites = [{title, sub, highlight}]
        （最大6。左上→右上→左中→右中→左下→右下の順）。ring = {pills:[...4], label_top, label_bottom}"""
        x, y, w, h = self._area(area)
        cx, cy = x + w / 2, y + h / 2
        d = min(h * 0.6, 2.8)
        self.shape(MSO_SHAPE.OVAL, cx - w * 0.33, cy - h * 0.36, w * 0.66, h * 0.72,
                   fill="primary_soft")
        if ring:
            self.box(x + 0.1, y + 0.05, w - 0.2, h - 0.1, fill=None, line="secondary", lw=2,
                     dash=True, radius=h / 2.2)
        bw, bh = min(3.6, (w - d) / 2 - 0.55), 0.95
        rows = [cy - h * 0.31, cy, cy + h * 0.31]
        slots = []
        for r, ry in enumerate(rows):
            inner = d * (0.36 if r != 1 else 0.5) + 0.45
            slots.append((cx - inner - bw, ry - bh / 2))
            slots.append((cx + inner, ry - bh / 2))
        for sat, (sx, sy) in zip(satellites, slots):
            ex = sx + bw if sx < cx else sx
            self.line(cx, cy, ex, sy + bh / 2, color="muted", width=1)
        self.circle(cx, cy, d + 0.24, fill="bg", line="rule", lw=1)
        self.circle(cx, cy, d, fill="primary")
        if center.get("badge"):
            self.pill(cx - 0.6, cy - d / 2 - 0.22, 1.2, 0.48, center["badge"], fill="accent",
                      size=17)
        self.text(cx - d / 2, cy - d * 0.34, d, 0.45, center["title"], size=18, bold=True,
                  color="white", align="center", name="T:hub-title")
        items = center.get("items", [])
        ih = min(0.42, (d * 0.55) / max(len(items), 1) - 0.06)
        for k, it in enumerate(items):
            iy = cy - d * 0.14 + k * (ih + 0.08)
            self.pill(cx - d * 0.33, iy, d * 0.66, ih, it,
                      fill="white" if k == 0 else "primary_soft", color="primary", size=15)
        for sat, (sx, sy) in zip(satellites, slots):
            hi = sat.get("highlight")
            self.box(sx, sy, bw, bh, fill="tertiary_soft" if hi else "panel",
                     line="tertiary" if hi else "primary", lw=1.5, radius=0.1)
            self.rect(sx, sy + 0.1, 0.08, bh - 0.2, fill="tertiary" if hi else "primary")
            self.text(sx + 0.2, sy + 0.06, bw - 0.3, 0.45, sat["title"], size=18, bold=True,
                      color="primary", valign="middle", name="T:hub-sat")
            if sat.get("sub"):
                self.text(sx + 0.2, sy + 0.5, bw - 0.3, 0.38, sat["sub"], size=self.d.S["small"],
                          name="T:hub-sub")
        if ring:
            pills = ring.get("pills", [])
            pw = 2.0
            pos = [(cx - pw - 0.15, y - 0.17), (cx + 0.15, y - 0.17),
                   (cx - pw - 0.15, y + h - 0.33), (cx + 0.15, y + h - 0.33)]
            for p, (ppx, ppy) in zip(pills, pos):
                self.pill(ppx, ppy, pw, 0.5, p, fill="secondary", size=16)
            if ring.get("label_top"):
                self.text(x + w - 2.6, y - 0.12, 2.6, 0.4, ring["label_top"], size=15, bold=True,
                          color="secondary", align="right", name="T:ring-top")
            if ring.get("label_bottom"):
                self.text(x, y + h - 0.28, 2.8, 0.4, ring["label_bottom"], size=15, bold=True,
                          color="secondary", name="T:ring-bottom")

    def flow_steps(self, steps, area=None, arrow_color="accent", arrow_labels=None):
        """P-FLOW: 処理・手順の流れ。step = {title, items|body, color}。2〜5段。技術資料の基本形。"""
        x, y, w, h = self._area(area)
        n = len(steps)
        aw = 0.65
        cols = split_area((x, y, w, h), [1] * n, gap=aw + 0.2)
        for i, (st, (cx, cy, cw, ch)) in enumerate(zip(steps, cols)):
            col = st.get("color", "primary")
            self.box(cx, cy, cw, ch, fill="panel", line=col, lw=1.75, radius=0.12)
            self.box(cx, cy, cw, 0.75, fill=col, radius=0.12)
            self.rect(cx, cy + 0.55, cw, 0.2, fill=col)
            self.text(cx + 0.15, cy, cw - 0.3, 0.75, st["title"], size=19, bold=True,
                      color="white", align="center", valign="middle", name="T:flow-title")
            iy = cy + 0.95
            if st.get("items"):
                for it in st["items"]:
                    self.box(cx + 0.2, iy, cw - 0.4, 0.55, fill=f"{col}_soft"
                             if f"{col}_soft" in self.d.C else "bg", radius=0.08, text=it,
                             size=15, bold=True, color="ink", align="left")
                    iy += 0.67
            if st.get("body"):
                self.text(cx + 0.2, iy, cw - 0.4, cy + ch - iy - 0.15, st["body"], size=15,
                          name="T:flow-body")
            if i < n - 1:
                ax = cx + cw + 0.1
                self.block_arrow(ax, cy + ch / 2 - 0.3, aw, 0.6, color=arrow_color)
                if arrow_labels and i < len(arrow_labels) and arrow_labels[i]:
                    self.text(ax - 0.4, cy + ch / 2 + 0.35, aw + 0.8, 0.6, arrow_labels[i],
                              size=self.d.S["caption"] + 1, bold=True, color=arrow_color,
                              align="center", name="T:flow-alabel")

    def layer_stack(self, layers, area=None, label_w=2.4, side=None):
        """P-LAYER: レイヤー構成図（アーキテクチャ・ソフトウェアスタック）。
        layer = {label, items:[...], color, highlight}。上から順に描く。side = (見出し, 文字) で右に注記。"""
        x, y, w, h = self._area(area)
        if side:
            w -= 3.0
        if not layers:
            raise ValueError("layer_stack: layers が空")
        n = len(layers)
        lh = (h - 0.12 * (n - 1)) / n
        for i, L in enumerate(layers):
            col = L.get("color", "primary")
            ly = y + i * (lh + 0.12)
            hi = L.get("highlight")
            self.box(x, ly, w, lh, fill=f"{col}_soft" if f"{col}_soft" in self.d.C else "panel",
                     line="accent" if hi else None, lw=2.5, radius=0.1)
            self.box(x, ly, label_w, lh, fill=col, radius=0.1, text=L["label"], size=18,
                     bold=True, color="white")
            items = L.get("items", [])
            if items:
                cols = split_area((x + label_w + 0.2, ly + 0.14, w - label_w - 0.35, lh - 0.28),
                                  [1] * len(items), gap=0.15)
                for it, (ix, iy, iw, ih) in zip(items, cols):
                    self.box(ix, iy, iw, ih, fill="panel", line=col, lw=1, radius=0.08, text=it,
                             size=15, bold=True)
        if side:
            sx = x + w + 0.3
            self.box(sx, y, 2.7, h, fill="panel", line="rule", lw=1, radius=0.12)
            self.text(sx + 0.2, y + 0.15, 2.3, 0.45, side[0], size=17, bold=True, color="primary",
                      name="T:layer-side-h")
            self.text(sx + 0.2, y + 0.65, 2.3, h - 0.8, side[1], size=14, name="T:layer-side")

    def numbered_list(self, items, area=None, highlight=None, highlight_label=None):
        """P-LIST: 番号付きの要点（まとめ・提案の柱）。items = [(番号, 見出し, 補足, 色名)]。"""
        x, y, w, h = self._area(area)
        n = len(items)
        rh = (h - 0.1 * (n - 1)) / n
        sq = min(0.85, rh - 0.12)
        for i, (num, head, sub, col) in enumerate(items):
            ry = y + i * (rh + 0.1)
            if highlight == i:
                self.box(x - 0.1, ry - 0.04, w + 0.2, rh + 0.08, fill="panel", line="tertiary",
                         lw=2, radius=0.12)
                if highlight_label:
                    self.pill(x + w - 1.9, ry + rh / 2 - 0.27, 1.8, 0.54, highlight_label,
                              fill="ink", size=16)
            self.box(x, ry + (rh - sq) / 2, sq, sq, fill=col, radius=0.14, text=str(num), size=26,
                     bold=True, color="white" if not col.endswith("_soft") else "primary")
            self.text(x + sq + 0.25, ry, w - sq - 2.3, rh * 0.55, head, size=20, bold=True,
                      valign="bottom", name="T:list-head")
            if sub:
                self.text(x + sq + 0.25, ry + rh * 0.55, w - sq - 2.3, rh * 0.45, sub,
                          size=self.d.S["small"] + 1, color="sub", name="T:list-sub")

    def concept_curve(self, area=None, rising="AI が作る量", flat="人が読める量",
                      gap="読み切れない\n= ボトルネック", x_label="時間", y_label="量"):
        """P-CURVE: 指数的に伸びる量と横ばいの量の交差（概念図）。数値の裏付けがないときに使う。"""
        x, y, w, h = self._area(area)
        ox, oy = x + 0.5, y + h - 0.45
        self.line(ox, oy, x + w, oy, color="ink", width=2, head="end")
        self.line(ox, oy, ox, y, color="ink", width=2, head="end")
        self.text(x + w - 1.0, oy + 0.05, 1.0, 0.35, x_label, size=14, bold=True, align="right",
                  name="T:curve-x")
        self.text(x - 0.1, y, 0.55, 0.4, y_label, size=14, bold=True, name="T:curve-y")
        self.tag(ox + 0.25, y + 0.05)
        fy = oy - (oy - y) * 0.3
        x0, x1 = ox + 0.2, x + w - 0.4
        pts = []
        for k in range(41):
            t = k / 40
            pts.append((x0 + (x1 - x0) * t, oy - 0.15 - (oy - y - 0.4) * (math.exp(4 * t) - 1) /
                        (math.exp(4) - 1)))
        cross = next((p for p in pts if p[1] <= fy), pts[-1])
        shade = [p for p in pts if p[0] >= cross[0]]
        self.polyline(shade + [(shade[-1][0], fy), (cross[0], fy)], color=None, width=0,
                      fill="accent_soft", closed=True)
        self.line(x0, fy, x1, fy, color="tertiary", width=4)
        self.polyline(pts, color="primary", width=4)
        self.line(x1 - 0.1, pts[-1][1] + 0.1, x1 - 0.1, fy - 0.05, color="accent", width=2,
                  head="both")
        self.text(x1 - 3.8, y + 0.0, 3.0, 0.45, rising, size=19, bold=True, color="primary",
                  align="right", name="T:curve-rise")
        self.text(x0 + 0.1, fy - 0.5, 3.0, 0.45, flat, size=19, bold=True, name="T:curve-flat")
        self.text(x0 + 0.1, fy + 0.08, 2.0, 0.35, "ほぼ横ばい", size=13, color="sub",
                  name="T:curve-flat2")
        self.text(cross[0] - 2.5, fy - 1.2, 2.4, 0.9, gap, size=17, bold=True,
                  color="accent", align="right", valign="bottom", name="T:curve-gap")

    def area_compare(self, items, area=None, unit_note=None):
        """P-AREA: 面積=量の比較（例: 費用）。items = [(ラベル, 値, 補足)]。先頭が基準（破線枠）。"""
        x, y, w, h = self._area(area)
        side = min(h - 0.55, w * 0.4)
        if not items:
            raise ValueError("area_compare: items が空")
        _check_values([it[1] for it in items], "area_compare の値")
        base = items[0][1]
        if base <= 0:
            raise ValueError("area_compare: 先頭（基準）の値は 0 より大きくする")
        self.text(x, y, max(side, 4.0), 0.45, f"{items[0][0]}　{items[0][2] or ''}", size=18,
                  bold=True, name="T:area-base")
        y += 0.55
        oy = y + side
        self.box(x, y, side, side, fill=None, line="tertiary", lw=2, dash=True, radius=0.04)
        lx = x + side + 0.5
        smalls = []
        cur_x = x + 0.15
        for lab, val, sub in items[1:]:
            s_ = side * math.sqrt(val / base)
            if s_ > side * 0.5:
                self.box(x, oy - s_, s_, s_, fill="tertiary_soft", line="tertiary", lw=1.5,
                         radius=0.03)
                self.text(x + 0.3, oy - s_ + 0.2, s_ - 0.4, 0.8, f"{lab}\n{sub or ''}", size=18,
                          bold=True, name="T:area-big")
            else:
                # 0 は面積 0 として描かない（最小サイズで描くと「面積 = 量」と矛盾する）。
                # 0 より大きく小さすぎて見えないものは 0.18 で描き、補足に「拡大表示」と書く。
                if val > 0 and s_ < 0.18:
                    s_, sub = 0.18, f"{sub or ''}（拡大表示）".strip()
                smalls.append((lab, sub, cur_x, s_))
                cur_x += max(s_, 0.05) + 0.2
        # 引き出し線: 左の四角ほど高い位置で右へ折る（線同士が交差しない）
        for k, (lab, sub, sx, s_) in enumerate(smalls):
            max_s = max(m[3] for m in smalls)
            level = oy - 0.12 - max_s - 0.4 - (len(smalls) - 1 - k) * 0.9
            if s_ > 0:
                self.rect(sx, oy - 0.12 - s_, s_, s_, fill="tertiary")
            self.line(sx + s_ / 2, oy - 0.12 - s_, sx + s_ / 2, level, color="ink", width=1)
            self.line(sx + s_ / 2, level, lx - 0.08, level, color="ink", width=1)
            self.text(lx, level - 0.42, x + w - lx, 0.84, f"{lab}\n{sub or ''}", size=16,
                      bold=True, valign="middle", name="T:area-small")
        if unit_note:
            self.text(lx, y - 0.05, x + w - lx, 0.35, unit_note, size=self.d.S["caption"] + 1,
                      color="sub", name="T:area-note")

    def kpi_tiles(self, tiles, area=None):
        """P-KPI: 大きな数字のタイル。tile = (値, 単位, 説明, 色名, 比較の注記)。報告スライドの冒頭向け。"""
        x, y, w, h = self._area(area)
        cols = split_area((x, y, w, h), [1] * len(tiles), gap=0.35)
        for t, (cx, cy, cw, ch) in zip(tiles, cols):
            val, unit, label, col = t[:4]
            cmp_ = t[4] if len(t) > 4 else None
            self.box(cx, cy, cw, ch, fill="panel", radius=0.14)
            self.rect(cx, cy, cw, 0.12, fill=col)
            self.text(cx + 0.3, cy + 0.35, cw - 0.6, 0.45, label, size=17, bold=True,
                      color="sub", name="T:kpi-label")
            self.text(cx + 0.3, cy + 0.85, cw - 0.6, 1.3,
                      [[(str(val), {"size": 54, "bold": True, "color": col}),
                        (" " + unit, {"size": 20, "bold": True})]],
                      valign="middle", name="T:kpi-val")
            if cmp_:
                self.text(cx + 0.3, cy + 2.2, cw - 0.6, ch - 2.4, cmp_, size=15, color="ink",
                          name="T:kpi-cmp")

    def table(self, header, rows, area=None, col_widths=None, highlight_col=None, size=14):
        """P-TABLE: 表（設計比較・仕様一覧）。PowerPoint の表として出すので後で編集できる。
        highlight_col 列を朱の太字にする（推奨案など）。行は 8 行程度まで。"""
        x, y, w, h = self._area(area)
        nr, nc = len(rows) + 1, len(header)
        rh = min(0.6, h / nr)
        gf = self.shapes.add_table(nr, nc, Inches(x), Inches(y), Inches(w), Inches(rh * nr))
        tbl = gf.table
        sid = tbl._tbl.tblPr.find(qn("a:tableStyleId"))
        if sid is None:
            sid = etree.SubElement(tbl._tbl.tblPr, qn("a:tableStyleId"))
        sid.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"  # No Style, No Grid
        widths = col_widths or [w / nc] * nc
        for j, cw in enumerate(widths):
            tbl.columns[j].width = Inches(cw * w / sum(widths))
        for i in range(nr):
            tbl.rows[i].height = Inches(rh)
            for j in range(nc):
                cell = tbl.cell(i, j)
                val = header[j] if i == 0 else rows[i - 1][j]
                cell.fill.solid()
                if i == 0:
                    cell.fill.fore_color.rgb = self.d.rgb("primary")
                else:
                    cell.fill.fore_color.rgb = self.d.rgb("panel" if i % 2 else "primary_soft")
                cell.margin_left = cell.margin_right = Inches(0.1)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                tf = cell.text_frame
                tf.word_wrap = True
                p = tf.paragraphs[0]
                p.alignment = PP_ALIGN.LEFT if j == 0 else PP_ALIGN.CENTER
                r = p.add_run()
                r.text = str(val)
                hi = highlight_col == j and i > 0
                self.d.font_run(r, size, "white" if i == 0 else ("accent" if hi else "ink"),
                                i == 0 or j == 0 or hi)
        gf.name = self._name("G:table", None)
        return gf

    def agenda(self, items, area=None, timebar=None, legend=None):
        """P-AGENDA: 章立て + 時間配分 + 色の凡例。items = [(番号, ラベル, 色名)]、
        timebar = [(ラベル, 分, 色名)]、legend = [(色名, 意味)]。"""
        x, y, w, h = self._area(area)
        n = len(items)
        cols = split_area((x, y, w, 2.3), [1] * n, gap=0.22)
        for (num, lab, col), (cx, cy, cw, _) in zip(items, cols):
            sq = min(cw, 1.35)
            sx = cx + (cw - sq) / 2
            soft = col.endswith("_soft")
            self.box(sx, cy, sq, sq, fill=col, line="primary" if soft else None, lw=1.5,
                     radius=0.22, text=str(num), size=40, bold=True,
                     color="primary" if soft else "white")
            self.text(cx - 0.05, cy + sq + 0.1, cw + 0.1, 0.85, lab, size=15, bold=True,
                      align="center", name="T:agenda-label")
        ty = y + 2.55
        if timebar:
            total = sum(m for _, m, _ in timebar)
            self.text(x, ty, 2.5, 0.35, f"{total:g} 分の配分", size=self.d.S["small"],
                      color="sub", bold=True, name="T:agenda-tb")
            bx, by, bh = x, ty + 0.4, 0.6
            acc = 0
            self.text(bx - 0.3, by + bh + 0.05, 0.8, 0.32, "0:00", size=self.d.S["caption"],
                      color="sub", align="center", name="T:tick")
            for lab, m, col in timebar:
                sw_ = w * m / total
                soft = col.endswith("_soft") or col in ("panel", "bg")
                self.rect(bx, by, sw_, bh, fill=col, line="rule", lw=0.75, text=lab, size=15,
                          bold=True, color="primary" if soft else "white")
                bx += sw_
                acc += m
                self.text(bx - 0.4, by + bh + 0.05, 0.8, 0.32, _mmss(acc),
                          size=self.d.S["caption"], color="sub", align="center", name="T:tick")
            ty = by + bh + 0.6
        if legend:
            self.legend(legend, x, max(ty, y + h - 0.45))


def _strip_style(shp):
    """テーマ由来の既定スタイル（影・枠色・文字色）を外す。色は必ず明示指定する前提。"""
    st = shp._element.find(qn("p:style"))
    if st is not None:
        shp._element.remove(st)
    shp.shadow.inherit = False


def _mmss(minutes):
    s = int(round(minutes * 60))
    return f"{s // 60}:{s % 60:02d}"


def _mix(hex_a, hex_b, t):
    """hex_a と hex_b を t (0..1, 1 で hex_b) で混ぜた HEX を返す。"""
    a = [int(hex_a[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(hex_b[i:i + 2], 16) for i in (0, 2, 4)]
    return "".join(f"{round(a[k] + (b[k] - a[k]) * t):02X}" for k in range(3))
