"""check_deck.py — 生成した .pptx を機械的に検査する（目視の前に必ず通す）。

使い方:
    python check_deck.py out/deck.pptx [--theme default] [--json check.json]

検査項目（ERROR は必ず直す / WARN は理由があれば残してよい）:
    ERROR  OFF_SLIDE    図形がスライドの外にはみ出している
    ERROR  OVERFLOW     文字が枠に収まらない（文字幅からの推定）
    ERROR  TABLE_GROW   表のセルの文字が行の高さに収まらない（PowerPoint では行が伸び、表が下へはみ出す）
    ERROR  TINY_FONT    9pt 未満の文字（段落から引き継いだ大きさも含む）
    ERROR  NO_TITLE     タイトル（図形名 TITLE）が無い
    WARN   TITLE_WRAP   タイトルが2行以上になる見込み（明示の改行を含む。1行の結論文にする）
    WARN   SMALL_FONT   本文に 11pt 未満の文字（出典・ページ番号・注記タグは除外）
    WARN   OVERLAP      枠なし文字同士が重なっている（文字が実際に占める範囲で判定。縦横の揃えを反映）
    WARN   ORPHAN       折り返しの最終行が1〜2文字だけになる見込み（「…なっ / た」のような泣き別れ）
    WARN   ACCENT_MANY  図中（タイトル以外）の朱が 3 箇所を超える（塗りと文字を数える。表は朱の列ごとに1。線は数えない）
    WARN   DENSE        1 スライドの文字数が 260 字を超える（表のセルを含む）
    WARN   OFF_PALETTE  theme に無い色が使われている
    WARN   UNCHECKED    検査できない図形（グループ・グラフ・埋め込みなど）がある。目視で確かめる

推定の前提: 全角 1.0em・半角 0.55em・行送り 1.2em×行間倍率。実際の描画とはずれる（ずれ幅はフォントの
有無・禁則処理で変わり、保証はない）。OVERFLOW が出なくても render.py の画像で最終確認すること。

終了コード:
    0 = ERROR なし
    1 = ERROR あり（スライドを直す）
    2 = 検査できない（python-pptx が無い・pptx が読めない・theme が見つからない／壊れている）。
        スライドの不良ではないので build_deck.py を直さず、原因を解消してから再実行する

--json の出力には検査した pptx の sha256 を入れる。納品時に out/deck.pptx の sha256 と一致することを確かめる。
"""
import argparse
import hashlib
import json
import math
import os
import sys

try:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
except ImportError as e:
    print(f"python-pptx が読み込めない（{e}）。`pip install python-pptx` で導入してから再実行する。",
          file=sys.stderr)
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
EMU_IN = 914400
DEFAULT_PT = 18  # python-pptx の既定テンプレートの本文サイズ（大きさ未指定の文字に使う）
SMALL_OK = ("SOURCE", "PAGE", "B:tag", "T:tick", "T:legend", "T:kicker")
REQUIRED_COLORS = ("bg", "panel", "ink", "sub", "muted", "rule", "white", "primary",
                   "primary_mid", "primary_soft", "secondary", "secondary_soft", "tertiary",
                   "tertiary_soft", "accent", "accent_soft")


class InputError(Exception):
    """検査の前提が崩れている（終了コード 2）。"""


def _in(v):
    return (v or 0) / EMU_IN


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _char_w(ch):
    o = ord(ch)
    if o > 0x2E7F or 0xFF01 <= o <= 0xFF5E:
        return 1.0
    if ch == " ":
        return 0.3
    if ch.isupper() or ch.isdigit():
        return 0.62
    return 0.55


def _run_pt(r, p):
    """実際に効く文字サイズ: run → 段落 → 既定の順に引き継ぐ。"""
    if r.font.size:
        return r.font.size.pt
    if p.font.size:
        return p.font.size.pt
    return DEFAULT_PT


def _est_height(tf, inner_w):
    """必要高さ（インチ）・全段落の合計行数・泣き別れの候補・最も長い行の幅を返す。"""
    total, total_lines, widest = 0.0, 0, 0.0
    orphans = []
    for p in tf.paragraphs:
        size = None
        width = 0.0
        for r in p.runs:
            s = _run_pt(r, p)
            size = max(size or 0, s)
            bold = 1.04 if r.font.bold else 1.0
            width += sum(_char_w(c) for c in r.text) * s / 72 * bold
        if size is None:
            size = p.font.size.pt if p.font.size else DEFAULT_PT
        lines = max(1, math.ceil(width / max(inner_w, 0.05) - 1e-6))
        if lines > 1:
            rest = width - (lines - 1) * inner_w
            if rest < 2.2 * size / 72:
                orphans.append(p.text[-3:])
        ls = p.line_spacing if isinstance(p.line_spacing, float) else 1.0
        total += lines * size / 72 * 1.2 * ls
        total_lines += lines
        widest = max(widest, min(width, inner_w))
    return total, total_lines, orphans, widest


def _rgb_of(color):
    try:
        if color and color.type is not None:
            return str(color.rgb)
    except Exception:
        pass
    return None


def _colors_in(shape):
    out = []
    try:
        if shape.fill.type == 1:
            out.append(str(shape.fill.fore_color.rgb))
    except Exception:
        pass
    if shape.has_text_frame:
        for p in shape.text_frame.paragraphs:
            for r in p.runs:
                c = _rgb_of(r.font.color)
                if c:
                    out.append(c)
    return out


def load_theme(name):
    path = name if name.endswith(".json") else os.path.join(HERE, "..", "assets", "themes",
                                                           name + ".json")
    if not os.path.exists(path):
        raise InputError(f"theme が見つからない: {path}（--theme の綴りを確かめる）")
    try:
        with open(path, encoding="utf-8") as f:
            theme = json.load(f)
    except (OSError, ValueError) as e:
        raise InputError(f"theme が読めない: {path}（{e}）")
    missing = [k for k in REQUIRED_COLORS if k not in theme.get("colors", {})]
    if missing:
        raise InputError(f"theme の colors に必須の色名が無い: {', '.join(missing)}")
    return theme


def _text_extent(y, h, tf, need):
    """枠の中で文字が実際に占める上端・下端（縦の配置を反映）。"""
    mt, mb = _in(tf.margin_top), _in(tf.margin_bottom)
    inner = max(h - mt - mb, 0)
    used = min(inner, need)
    anchor = tf.vertical_anchor
    if anchor == MSO_ANCHOR.MIDDLE:
        top = y + mt + (inner - used) / 2
    elif anchor == MSO_ANCHOR.BOTTOM:
        top = y + h - mb - used
    else:
        top = y + mt
    return top, top + used


def _text_span(x, w, tf, widest):
    """枠の中で文字が実際に占める左端・右端（揃えを反映。段落ごとの揃えは先頭段落で代表させる）。"""
    ml, mr = _in(tf.margin_left), _in(tf.margin_right)
    inner = max(w - ml - mr, 0)
    used = min(inner, widest)
    align = tf.paragraphs[0].alignment if tf.paragraphs else None
    if align == PP_ALIGN.CENTER:
        left = x + ml + (inner - used) / 2
    elif align == PP_ALIGN.RIGHT:
        left = x + w - mr - used
    else:
        left = x + ml
    return left, left + used


def _check_table(shp, idx, add, palette, accent):
    """表のセルを検査する。戻り値は (文字数, 朱の数, theme 外の色)。朱は列単位で数える（推奨列の強調は1か所）。"""
    tbl = shp.table
    chars, accent_cols, off = 0, set(), set()
    for ri, row in enumerate(tbl.rows):
        rh = _in(row.height)
        for ci, cell in enumerate(row.cells):
            if cell.is_spanned:
                continue
            cw = sum(_in(tbl.columns[c].width) for c in range(ci, ci + max(cell.span_width, 1)))
            tf = cell.text_frame
            text = tf.text.strip()
            try:
                if cell.fill.type == 1:
                    c = str(cell.fill.fore_color.rgb)
                    if palette and c not in palette:
                        off.add(c)
            except Exception:
                pass
            if not text:
                continue
            chars += len(text.replace("\n", ""))
            for p in tf.paragraphs:
                for r in p.runs:
                    if not r.text.strip():
                        continue
                    pt = _run_pt(r, p)
                    if pt < 9:
                        add("ERROR", "TINY_FONT", idx, f"{shp.name} 行{ri + 1}列{ci + 1}: {pt}pt"
                            f"「{r.text[:12]}」")
                    elif pt < 11:
                        add("WARN", "SMALL_FONT", idx, f"{shp.name} 行{ri + 1}列{ci + 1}: {pt}pt"
                            f"「{r.text[:12]}」")
                    c = _rgb_of(r.font.color)
                    if c:
                        if c == accent:
                            accent_cols.add(ci)
                        if palette and c not in palette:
                            off.add(c)
            inner_w = cw - _in(cell.margin_left) - _in(cell.margin_right)
            span_h = sum(_in(tbl.rows[k].height) for k in range(ri, ri + max(cell.span_height, 1)))
            inner_h = span_h - _in(cell.margin_top) - _in(cell.margin_bottom)
            need, lines, _, _ = _est_height(tf, inner_w)
            if need > inner_h * 1.04 + 0.02:
                add("ERROR", "TABLE_GROW", idx, f"{shp.name} 行{ri + 1}列{ci + 1}「{text[:16]}」"
                    f"必要高さ {need:.2f}in > 行 {inner_h:.2f}in（{lines}行の見込み。"
                    "行が伸びて表が下へはみ出す。文を短くするか表を分ける）")
            if rh <= 0:
                add("WARN", "UNCHECKED", idx, f"{shp.name} 行{ri + 1}: 行の高さが 0")
    return chars, len(accent_cols), off


def check(path, theme):
    try:
        prs = Presentation(path)
    except Exception as e:
        raise InputError(f"pptx が読めない: {path}（{e}）")
    sw, sh = _in(prs.slide_width), _in(prs.slide_height)
    palette = {v.upper() for v in theme["colors"].values()}
    accent = theme["colors"]["accent"].upper()
    issues = []

    def add(level, code, idx, msg):
        issues.append({"level": level, "code": code, "slide": idx, "msg": msg})

    for idx, slide in enumerate(prs.slides, 1):
        names = [s.name for s in slide.shapes]
        if "TITLE" not in names:
            add("ERROR", "NO_TITLE", idx, "タイトル（名前 TITLE の図形）が無い。blank() のスライドは "
                "s.text(..., name=\"TITLE\") で見えるタイトルを置く")
        chars = 0
        accent_n = 0
        textboxes = []
        off = set()
        for shp in slide.shapes:
            x, y, w, h = _in(shp.left), _in(shp.top), _in(shp.width), _in(shp.height)
            if x < -0.02 or y < -0.02 or x + w > sw + 0.02 or y + h > sh + 0.02:
                add("ERROR", "OFF_SLIDE", idx, f"{shp.name} がスライド外 (x={x:.2f}, y={y:.2f}, "
                    f"w={w:.2f}, h={h:.2f})")
            if getattr(shp, "has_table", False) and shp.has_table:
                c, a, o = _check_table(shp, idx, add, palette, accent)
                chars += c
                accent_n += a
                off |= o
                continue
            if shp.shape_type is not None and int(shp.shape_type) in (6, 3, 7, 10):
                # 6 = グループ, 3 = グラフ, 7 = 埋め込み OLE, 10 = リンク OLE
                add("WARN", "UNCHECKED", idx, f"{shp.name}: 中身を検査できない図形。画像で目視する")
                continue
            cols = _colors_in(shp)
            if shp.name != "TITLE" and ":legend" not in shp.name:
                accent_n += sum(1 for c in cols if c == accent)
            if not shp.name.startswith("B:fade"):
                off |= {c for c in cols if c not in palette}
            if not shp.has_text_frame:
                continue
            tf = shp.text_frame
            text = tf.text.strip()
            if not text:
                continue
            chars += len(text.replace("\n", ""))
            for p in tf.paragraphs:
                for r in p.runs:
                    if r.text.strip():
                        pt = _run_pt(r, p)
                        if pt < 9:
                            add("ERROR", "TINY_FONT", idx, f"{shp.name}: {pt}pt「{r.text[:12]}」")
                        elif pt < 11 and not shp.name.startswith(SMALL_OK):
                            add("WARN", "SMALL_FONT", idx, f"{shp.name}: {pt}pt「{r.text[:12]}」")
            shrink = 1.0
            try:
                if shp.auto_shape_type in (MSO_SHAPE.OVAL, MSO_SHAPE.TRAPEZOID):
                    shrink = 0.72  # 楕円・台形は文字領域が狭い
            except Exception:
                pass
            inner_w = w * shrink - _in(tf.margin_left) - _in(tf.margin_right)
            inner_h = h - _in(tf.margin_top) - _in(tf.margin_bottom)
            need, lines, orphans, widest = _est_height(tf, inner_w)
            for o in orphans:
                add("WARN", "ORPHAN", idx, f"{shp.name}: 最終行が1〜2文字だけになる見込み「…{o}」"
                    "（語を短くするか枠を広げる）")
            if need > inner_h * 1.04 + 0.02:
                add("ERROR", "OVERFLOW", idx, f"{shp.name}「{text[:16]}」必要高さ {need:.2f}in > 枠 "
                    f"{inner_h:.2f}in（{lines}行の見込み）")
            if shp.name == "TITLE" and lines > 1:
                add("WARN", "TITLE_WRAP", idx, f"タイトルが {lines} 行の見込み（明示の改行を含む）"
                    f"「{text[:20]}」")
            if shp.name.startswith("T:"):
                top, bottom = _text_extent(y, h, tf, need)
                left, right = _text_span(x, w, tf, widest)
                textboxes.append((shp.name, left, top, right, bottom))
        for i in range(len(textboxes)):
            for j in range(i + 1, len(textboxes)):
                a, b = textboxes[i], textboxes[j]
                ow = min(a[3], b[3]) - max(a[1], b[1])
                oh = min(a[4], b[4]) - max(a[2], b[2])
                if ow > 0.15 and oh > 0.1:
                    add("WARN", "OVERLAP", idx, f"{a[0]} と {b[0]} が重なっている")
        if accent_n > 3:
            add("WARN", "ACCENT_MANY", idx, f"図中の朱が {accent_n} 箇所（タイトル以外は変化点1つに絞る）")
        if chars > 260:
            add("WARN", "DENSE", idx, f"文字数 {chars}（図を主役にし、文は短いラベルにする）")
        if off:
            add("WARN", "OFF_PALETTE", idx, f"theme に無い色: {', '.join(sorted(off))}")
    return issues


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pptx")
    ap.add_argument("--theme", default="default", help="theme 名か JSON のパス")
    ap.add_argument("--json", help="結果を JSON で書き出すパス")
    a = ap.parse_args()
    try:
        if not os.path.exists(a.pptx):
            raise InputError(f"pptx が無い: {a.pptx}")
        theme = load_theme(a.theme)
        issues = check(a.pptx, theme)
    except InputError as e:
        print(f"[検査不能] {e}", file=sys.stderr)
        if a.json:
            with open(a.json, "w", encoding="utf-8") as f:
                json.dump({"status": "unchecked", "reason": str(e)}, f, ensure_ascii=False, indent=2)
        return 2
    err = [i for i in issues if i["level"] == "ERROR"]
    for i in issues:
        print(f"[{i['level']}] slide {i['slide']:>2} {i['code']}: {i['msg']}")
    print(f"--- ERROR {len(err)} / WARN {len(issues) - len(err)}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"status": "error" if err else "ok", "pptx": os.path.abspath(a.pptx),
                       "sha256": sha256(a.pptx), "theme": a.theme, "errors": len(err),
                       "issues": issues}, f, ensure_ascii=False, indent=2)
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
