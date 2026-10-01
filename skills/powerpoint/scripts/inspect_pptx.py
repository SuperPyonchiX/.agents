#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PowerPoint（.pptx / .potx）の構造・文字・配置を出し、はみ出しと重なりを検査する。

    python inspect_pptx.py <pptx> [--layouts] [--slides 1-3,5] [--check]

出力（Markdown）:
    - 冒頭: スライドの大きさ（mm と縦横比）、スライド枚数
    - --layouts: テンプレートのレイアウト一覧と、各レイアウトのプレースホルダ（idx・種類・位置）
    - スライドごと: レイアウト名、図形（名前・種類・プレースホルダ idx・位置と大きさ mm・文字）、ノート
    --check: スライドの外にはみ出した図形と、文字を持つ図形どうしの重なりを「検査」節に列挙する

終了コード:
    0  出力した（--check では問題なし）
    1  開けない、または --check で問題が見つかった
    2  引数の指定ミス、入力が存在しない、.ppt、または python-pptx が無い

依存: python-pptx（pip install python-pptx）
"""

import argparse
import sys
from pathlib import Path

EMU_PER_MM = 36000
TOLERANCE_MM = 1.0   # これ以下のはみ出し・重なりは無視する


def mm(v):
    return (v or 0) / EMU_PER_MM


def parse_pages(spec, total):
    if not spec:
        return list(range(total))
    pages = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        start, end = int(a), int(b or a)
        pages.extend(p - 1 for p in range(start, end + 1) if 1 <= p <= total)
    return pages


def shape_text(shape, limit=60):
    if not shape.has_text_frame:
        return ""
    text = " / ".join(p.text for p in shape.text_frame.paragraphs if p.text.strip())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def shape_kind(shape):
    if shape.is_placeholder:
        return "ph[%d] %s" % (shape.placeholder_format.idx,
                              str(shape.placeholder_format.type).split(".")[-1].split(" ")[0])
    if shape.has_chart if hasattr(shape, "has_chart") else False:
        return "グラフ"
    if shape.has_table if hasattr(shape, "has_table") else False:
        return "表"
    return str(shape.shape_type).split(".")[-1].split(" ")[0] if shape.shape_type else "図形"


def box(shape):
    if shape.left is None or shape.width is None:
        return None
    return (mm(shape.left), mm(shape.top), mm(shape.left + shape.width), mm(shape.top + shape.height))


def check_slide(shapes, width, height):
    problems = []
    texts = []
    for s in shapes:
        b = box(s)
        if b is None:
            continue
        x1, y1, x2, y2 = b
        if x1 < -TOLERANCE_MM or y1 < -TOLERANCE_MM or x2 > width + TOLERANCE_MM or y2 > height + TOLERANCE_MM:
            problems.append("「%s」がスライドの外にはみ出している（%.0f,%.0f〜%.0f,%.0f mm）" % (s.name, x1, y1, x2, y2))
        if shape_text(s):
            texts.append((s, b))
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            (sa, a), (sb, b) = texts[i], texts[j]
            w = min(a[2], b[2]) - max(a[0], b[0])
            h = min(a[3], b[3]) - max(a[1], b[1])
            if w > TOLERANCE_MM and h > TOLERANCE_MM:
                problems.append("「%s」と「%s」が重なっている（%.0f×%.0f mm）" % (sa.name, sb.name, w, h))
    return problems


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="pptx の構造と配置を出す")
    ap.add_argument("pptx")
    ap.add_argument("--layouts", action="store_true", help="レイアウト一覧も出す")
    ap.add_argument("--slides", help="例: 1-3,5（1始まり）")
    ap.add_argument("--check", action="store_true", help="はみ出しと重なりを検査する")
    args = ap.parse_args()

    try:
        from pptx import Presentation
    except ImportError:
        print("python-pptx が必要: pip install python-pptx", file=sys.stderr)
        return 2
    path = Path(args.pptx)
    if not path.is_file():
        print("入力が存在しない: %s" % path, file=sys.stderr)
        return 2
    if path.suffix.lower() == ".ppt":
        print(".ppt は読めない。PowerPoint か LibreOffice で .pptx に変換してから扱う", file=sys.stderr)
        return 2
    try:
        prs = Presentation(str(path))
    except Exception as e:  # 壊れた zip・形式違いで python-pptx が投げる例外はまちまち
        print("開けない: %s (%s)" % (path, e), file=sys.stderr)
        return 1

    width, height = mm(prs.slide_width), mm(prs.slide_height)
    ratio = width / height if height else 0
    label = "16:9" if abs(ratio - 16 / 9) < 0.02 else "4:3" if abs(ratio - 4 / 3) < 0.02 else "%.2f:1" % ratio
    lines = ["# %s" % path.name, "",
             "- スライドの大きさ: %.0f × %.0f mm（%s）" % (width, height, label),
             "- スライド枚数: %d" % len(prs.slides), ""]

    if args.layouts:
        lines.append("## レイアウト")
        for m, master in enumerate(prs.slide_masters, 1):
            for layout in master.slide_layouts:
                lines.append("- マスター%d「%s」" % (m, layout.name))
                for ph in layout.placeholders:
                    b = box(ph)
                    pos = "%.0f,%.0f %.0f×%.0f mm" % (b[0], b[1], b[2] - b[0], b[3] - b[1]) if b else "位置なし"
                    lines.append("  - %s 「%s」 %s" % (shape_kind(ph), ph.name, pos))
        lines.append("")

    all_problems = []
    for i in parse_pages(args.slides, len(prs.slides)):
        slide = prs.slides[i]
        lines.append("## スライド %d（%s）" % (i + 1, slide.slide_layout.name))
        for s in slide.shapes:
            b = box(s)
            pos = "%.0f,%.0f %.0f×%.0f" % (b[0], b[1], b[2] - b[0], b[3] - b[1]) if b else "-"
            text = shape_text(s)
            lines.append("- %s 「%s」 %s mm%s" % (shape_kind(s), s.name, pos, ("： " + text) if text else ""))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip() if slide.notes_slide.notes_text_frame else ""
            if notes:
                lines.append("- ノート： " + notes.replace("\n", " / ")[:120])
        if args.check:
            for p in check_slide(slide.shapes, width, height):
                all_problems.append("スライド %d: %s" % (i + 1, p))
        lines.append("")

    if args.check:
        lines.append("## 検査")
        lines += ["- " + p for p in all_problems] or ["- 問題なし（はみ出し・重なりのみ。文字が枠に収まっているかは画像で確かめる）"]
    print("\n".join(lines))
    return 1 if args.check and all_problems else 0


if __name__ == "__main__":
    sys.exit(main())
