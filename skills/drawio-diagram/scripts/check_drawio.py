#!/usr/bin/env python3
"""draw.io ファイル（.drawio）の構造を検査する。

検査項目:
  ERROR  XML として読めない / mxfile・diagram・mxGraphModel が無い
  ERROR  mxCell の id 重複、parent・source・target が存在しない id を指す
  ERROR  vertex に mxGeometry が無い、幅・高さが 0 以下
  ERROR  同じ親の中で vertex 同士が重なっている（コンテナと中身の関係は除く）
  ERROR  スイムレーン・枠の見出し帯に中の箱がかぶっている
  ERROR  edge のラベルに labelBackgroundColor が無い（線とラベルが重なる）
  ERROR  --spec の要件にある箱・置き場所・線が図に無い
  ERROR  ページ名・ラベルが文字化けしている（「??」の連続や U+FFFD。UTF-8 以外で保存したときに起きる）
  WARN   vertex のラベルが空（コンテナ・テキストなしの装飾は除外できないので目安）

使い方:
  python check_drawio.py <file.drawio> [--spec <file.spec.json>]

spec.json の形（D0 で書く。id は .drawio の mxCell の id と一致させる）:
  {"groups": [{"id": "lane_dev", "label": "開発者", "kind": "lane"}, ...],
   "nodes": [{"id": "fix", "label": "コード修正", "in": "lane_dev"}, ...],
   "edges": [{"from": "triage", "to": "fix", "label": "修正"}, ...]}
  - groups[] も箱として照合する（id・label・in）。複数ページは {"pages": [...]} で、全ページ分をまとめて照合する
  - シーケンス図のページ（layout: "sequence"）は participants を箱、steps の中のメッセージを線として照合し、
    参加者が左から書いた順に並んでいるかも見る。活性区間につながる線はそのライフラインの線とみなす
  - layout_from_spec.py 用の配置・見た目のキー（at・near・pos・span・shape・kind・stack・style・class など）は無視する
  - nodes[].in    置き場所の枠・レーンの id（任意）。親をたどってその枠の中にあれば合格
  - nodes[].label ラベルに含まれるべき文字列（任意。改行・空白は無視して部分一致）
  - edges[].label 線のラベルに含まれるべき文字列（任意）
  - 同じ from→to の線は1本あれば合格。向きは区別する
  - 並び順の要件は "order": [{"axis": "y", "ids": ["lane_dev", "lane_rev", "lane_qa"]}] と書く。
    axis が y なら上から順、x なら左から順に、前の箱より完全に先（重ならず後ろ）に置かれていれば合格

終了コード: 0 = ERROR なし（WARN はあってよい） / 1 = ERROR あり / 2 = 引数の誤り・ファイルが読めない
依存: 標準ライブラリのみ
"""
import base64
import json
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zlib


def load_models(path):
    tree = ET.parse(path)
    root = tree.getroot()
    if root.tag != "mxfile":
        raise ValueError("ルート要素が mxfile ではない")
    diagrams = root.findall("diagram")
    if not diagrams:
        raise ValueError("diagram 要素が無い")
    models = []
    for d in diagrams:
        name = d.get("name", d.get("id", "?"))
        model = d.find("mxGraphModel")
        if model is None and (d.text or "").strip():
            # 圧縮形式: base64 → raw deflate → URL エンコード
            raw = zlib.decompress(base64.b64decode(d.text.strip()), -15)
            model = ET.fromstring(urllib.parse.unquote(raw.decode("utf-8")))
        if model is None:
            raise ValueError(f"diagram「{name}」に mxGraphModel が無い")
        models.append((name, model))
    return models


def rect(cell):
    g = cell.find("mxGeometry")
    if g is None:
        return None
    try:
        return (float(g.get("x", 0)), float(g.get("y", 0)),
                float(g.get("width", 0)), float(g.get("height", 0)))
    except ValueError:
        return None


def overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def garbled(text):
    return bool(text) and ("�" in text or "??" in text)


def check_model(page, model):
    errors, warns = [], []
    if garbled(page):
        errors.append(f"ページ名「{page}」が文字化けしている。ファイルを UTF-8 で保存し直す")
    root = model.find("root")
    if root is None:
        return [f"[{page}] root 要素が無い"], warns
    cells = root.findall("mxCell") + [
        c for obj in root.findall("object") + root.findall("UserObject")
        for c in obj.findall("mxCell")
    ]
    ids = {}
    for obj in root.findall("object") + root.findall("UserObject"):
        cell = obj.find("mxCell")
        if cell is not None and obj.get("id"):
            cell.set("id", obj.get("id"))
            cell.set("value", obj.get("label", ""))
    for c in cells:
        cid = c.get("id")
        if cid is None:
            errors.append(f"[{page}] id の無い mxCell がある")
            continue
        if cid in ids:
            errors.append(f"[{page}] id「{cid}」が重複している")
        ids[cid] = c
    for cid, c in ids.items():
        for attr in ("parent", "source", "target"):
            ref = c.get(attr)
            if ref is not None and ref not in ids:
                errors.append(f"[{page}] {cid} の {attr}=\"{ref}\" が存在しない")
    for cid, c in ids.items():
        if garbled(c.get("value")):
            errors.append(f"[{page}] {cid} のラベル「{c.get('value')[:20]}」が文字化けしている。UTF-8 で保存し直す")
    vertices = {cid: c for cid, c in ids.items() if c.get("vertex") == "1"}
    parents = {c.get("parent") for c in ids.values()}
    for cid, c in vertices.items():
        r = rect(c)
        if r is None:
            errors.append(f"[{page}] vertex「{cid}」に mxGeometry が無い")
        elif r[2] <= 0 or r[3] <= 0:
            errors.append(f"[{page}] vertex「{cid}」の幅か高さが 0 以下")
        style = c.get("style", "")
        if not (c.get("value") or "").strip() and cid not in parents \
                and "text" not in style and "line" not in style                 and "noLabel=1" not in style:
            warns.append(f"[{page}] vertex「{cid}」のラベルが空")
    for cid, c in ids.items():
        if c.get("edge") == "1" and (c.get("value") or "").strip() \
                and "labelBackgroundColor" not in c.get("style", ""):
            errors.append(f"[{page}] edge「{cid}」のラベルに labelBackgroundColor が無い（線と重なる）")
    by_parent = {}
    for cid, c in vertices.items():
        by_parent.setdefault(c.get("parent"), []).append(cid)
    decor = ("seqDecor=1", "orthogonalPerimeter")   # シーケンス図の枠・ガード・活性区間は重なってよい
    for siblings in by_parent.values():
        siblings = [v for v in siblings if not any(d in vertices[v].get("style", "") for d in decor)]
        for i, a in enumerate(siblings):
            for b in siblings[i + 1:]:
                ra, rb = rect(vertices[a]), rect(vertices[b])
                if ra and rb and overlaps(ra, rb):
                    errors.append(f"[{page}] vertex「{a}」と「{b}」が重なっている")
    for cid, c in vertices.items():
        parent = ids.get(c.get("parent"))
        r = rect(c)
        if parent is None or parent.get("vertex") != "1" or r is None:
            continue
        pstyle = style_map(parent.get("style", ""))
        if "swimlane" not in pstyle:
            continue
        band = float(pstyle.get("startSize", 23))
        horizontal = pstyle.get("horizontal", "1") != "0"
        if (r[1] < band) if horizontal else (r[0] < band):
            errors.append(f"[{page}] vertex「{cid}」が枠「{parent.get('id')}」の見出し帯"
                          f"（{'上端' if horizontal else '左端'}から {band:g}px）にかぶっている")
    return errors, warns


def style_map(style):
    out = {}
    for part in style.split(";"):
        if not part:
            continue
        k, _, v = part.partition("=")
        out[k] = v if _ else ""
    return out


def norm(text):
    return re.sub(r"<[^>]+>|&[a-z]+;|\s", "", text or "")


def flatten_spec(spec):
    pages = spec["pages"] if "pages" in spec else [spec]
    out = {"nodes": [], "edges": [], "order": []}
    for pg in pages:
        out["nodes"] += [dict(g, _group=True) for g in pg.get("groups", [])] + list(pg.get("nodes", []))
        out["edges"] += list(pg.get("edges", []))
        out["order"] += list(pg.get("order", []))
        if pg.get("layout") == "sequence":   # 参加者は箱、メッセージは線、参加者の並びは左からの順
            parts = pg.get("participants", [])
            out["nodes"] += parts
            out["edges"] += list(iter_messages(pg.get("steps", [])))
            if len(parts) > 1:
                out["order"].append({"axis": "x", "ids": [p["id"] for p in parts]})
    return out


def iter_messages(steps):
    for s in steps:
        if "fragment" in s:
            ops = s.get("operands") or [{"steps": s.get("steps", [])}]
            for op in ops:
                yield from iter_messages(op.get("steps", []))
        else:
            yield s


def check_spec(models, spec):
    spec = flatten_spec(spec)
    errors = []
    cells = {}
    for _, model in models:
        root = model.find("root")
        for obj in root.findall("object") + root.findall("UserObject"):
            c = obj.find("mxCell")
            if c is not None:
                c.set("id", obj.get("id", ""))
                c.set("value", obj.get("label", ""))
                cells[c.get("id")] = c
        for c in root.findall("mxCell"):
            cells[c.get("id")] = c

    def inside(cid, box):
        seen = set()
        cur = cells.get(cid)
        while cur is not None and cur.get("parent") not in seen:
            if cur.get("parent") == box:
                return True
            seen.add(cur.get("parent"))
            cur = cells.get(cur.get("parent"))
        return False

    for n in spec.get("nodes", []):
        c = cells.get(n["id"])
        if c is None or c.get("vertex") != "1":
            errors.append(f"要件の箱「{n['id']}」（{n.get('label', '')}）が図に無い")
            continue
        if n.get("label") and norm(n["label"]) not in norm(c.get("value")):
            errors.append(f"箱「{n['id']}」のラベルに「{n['label']}」が含まれていない（今: {norm(c.get('value'))}）")
        if n.get("in") and not inside(n["id"], n["in"]):
            errors.append(f"箱「{n['id']}」が枠「{n['in']}」の中に無い（今の親: {c.get('parent')}）")
    def absrect(cid, depth=0):
        c = cells.get(cid)
        r = rect(c) if c is not None else None
        if r is None or depth > 50:
            return None
        pr = absrect(c.get("parent"), depth + 1) if c.get("parent") not in (None, "0", "1") else None
        return (r[0] + pr[0], r[1] + pr[1], r[2], r[3]) if pr else r

    for o in spec.get("order", []):
        axis = o.get("axis", "y")
        ids_ = o["ids"]
        for a_id, b_id in zip(ids_, ids_[1:]):
            ra, rb = absrect(a_id), absrect(b_id)
            if ra is None or rb is None:
                errors.append(f"並び順の要件の箱「{a_id if ra is None else b_id}」が図に無い")
                continue
            ok = rb[1] >= ra[1] + ra[3] - 1 if axis == "y" else rb[0] >= ra[0] + ra[2] - 1
            if not ok:
                where = "下" if axis == "y" else "右"
                errors.append(f"「{b_id}」が「{a_id}」より{where}に置かれていない（要件: {'上から' if axis == 'y' else '左から'} {' → '.join(ids_)}）")
    def owner(cid):
        """シーケンス図の活性区間はライフラインの一部として扱う"""
        c = cells.get(cid)
        if c is not None and "targetShapes=umlLifeline" in (c.get("style") or ""):
            return c.get("parent")
        return cid

    edges = [c for c in cells.values() if c.get("edge") == "1"]
    for e in spec.get("edges", []):
        hits = [c for c in edges if owner(c.get("source")) == e["from"] and owner(c.get("target")) == e["to"]]
        if not hits:
            errors.append(f"要件の線「{e['from']} → {e['to']}」が図に無い")
        elif e.get("label") and not any(norm(e["label"]) in norm(c.get("value")) for c in hits):
            errors.append(f"線「{e['from']} → {e['to']}」のラベルに「{e['label']}」が含まれていない")
    return errors


for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv):
    args = argv[1:]
    spec_path = None
    if len(args) == 3 and args[1] == "--spec":
        spec_path = args[2]
    elif len(args) != 1:
        print(__doc__)
        return 2
    try:
        models = load_models(args[0])
        spec = json.load(open(spec_path, encoding="utf-8")) if spec_path else None
    except (OSError, ET.ParseError, ValueError, zlib.error) as e:
        print(f"ERROR  読めない: {e}")
        return 2
    errors, warns = [], []
    for page, model in models:
        e, w = check_model(page, model)
        errors += e
        warns += w
    if spec is not None:
        try:
            errors += check_spec(models, spec)
        except (KeyError, TypeError, AttributeError) as e:
            print(f"ERROR  spec.json の形が違う: {e}")
            return 2
    for m in errors:
        print(f"ERROR  {m}")
    for m in warns:
        print(f"WARN   {m}")
    print(f"ページ {len(models)} / ERROR {len(errors)} 件 / WARN {len(warns)} 件")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
