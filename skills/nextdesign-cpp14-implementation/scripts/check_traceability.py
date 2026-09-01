#!/usr/bin/env python3
"""設計 ⇔ ヘッダ宣言を突き合わせ、実装漏れとレビューの未クローズを列挙する。

使い方:
    python scripts/check_traceability.py --index work/design-index.json \
        --sources include/ [--review-log work/review-log.md]

終了コード:
    0  欠落なし
    1  欠落あり
    2  引数誤り

検査する対応関係:

    design-index.json の functions[].id
      -> ヘッダに同名の宣言があるか
    review-log.md の各指摘                     (--review-log を渡したときのみ)
      -> 状態が open のまま残っていないか

P3 のゲートで使う。依存は標準ライブラリのみ。
"""

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SOURCE_SUFFIXES = {".h", ".hpp", ".hh", ".hxx"}

# レビュー記録の列名の候補（表記揺れを吸収する）
COL_REVIEW_ID = {"id", "指摘id", "no", "no."}
COL_REVIEW_STATUS = {"状態", "ステータス", "status"}
OPEN_STATUSES = {"open", "未対応", "対応中"}


class Report:
    def __init__(self):
        self.errors = []
        self.warns = []

    def error(self, where, msg):
        self.errors.append((where, msg))

    def warn(self, where, msg):
        self.warns.append((where, msg))

    def dump(self):
        for where, msg in self.errors:
            print(f"ERROR  {where}: {msg}")
        for where, msg in self.warns:
            print(f"WARN   {where}: {msg}")
        print()
        print(f"ERROR {len(self.errors)} 件 / WARN {len(self.warns)} 件")
        if self.errors:
            print("不合格。欠落を該当フェーズに戻って埋めること。")
        else:
            print("合格。設計とヘッダ宣言の対応に欠落はない。")
        return 1 if self.errors else 0


def load_index(path, rep):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR  {path}: 読み込めない ({e})")
        return None
    funcs = []
    for cls in data.get("classes", []):
        cname = cls.get("name", "?")
        for fn in cls.get("functions", []):
            fid = fn.get("id") or f"{cname}::{fn.get('name', '?')}"
            funcs.append(
                {
                    "id": fid,
                    "class": cname,
                    "name": fn.get("name", ""),
                    "visibility": fn.get("visibility", "public"),
                }
            )
    if not funcs:
        rep.error(str(path), "classes[].functions が空。P0 の取り込みをやり直すこと")
    return funcs


def check_review_log(path, rep):
    """レビュー記録に open のまま残っている指摘がないかを検査する。

    ID 列と状態列の両方を持つ表だけを見る。集計表や逸脱承認一覧は自然に除外される。
    """
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        print(f"ERROR  {path}: 読み込めない ({e})")
        return None

    counts = {"open": 0, "closed": 0}
    id_col = status_col = None
    seen_table = False
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if not s.startswith("|"):
            id_col = status_col = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        lowered = [c.lower() for c in cells]
        if status_col is None:
            for idx, c in enumerate(lowered):
                if c in COL_REVIEW_ID and id_col is None:
                    id_col = idx
                elif c in COL_REVIEW_STATUS:
                    status_col = idx
            if status_col is None or id_col is None:
                id_col = status_col = None
            else:
                seen_table = True
            continue
        if max(id_col, status_col) >= len(cells):
            continue
        rid = cells[id_col]
        status = cells[status_col].lower()
        if not rid or "<" in rid:
            continue
        if status in OPEN_STATUSES:
            counts["open"] += 1
            rep.error(
                f"{path}:{n}",
                f"レビュー指摘 {rid} が {cells[status_col]} のまま残っている"
                "（修正するか、ユーザーの了承を得て accepted にすること）",
            )
        else:
            counts["closed"] += 1

    if not seen_table:
        rep.error(path, "ID 列と状態列を持つ指摘一覧が読めない。テンプレートの表形式を確認すること")
    return counts


def collect_declarations(src_dir):
    d = Path(src_dir)
    if not d.is_dir():
        return None
    text = []
    for f in sorted(d.rglob("*")):
        if f.is_file() and f.suffix in SOURCE_SUFFIXES:
            text.append(f.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(text)


def main(argv):
    ap = argparse.ArgumentParser(add_help=True, description=__doc__)
    ap.add_argument("--index", required=True, help="work/design-index.json")
    ap.add_argument("--sources", required=True, help="ヘッダのディレクトリ")
    ap.add_argument("--review-log", default=None, help="work/review-log.md（省略可）")
    try:
        args = ap.parse_args(argv[1:])
    except SystemExit:
        return 2

    rep = Report()
    funcs = load_index(args.index, rep)
    if funcs is None:
        return 1

    decls = collect_declarations(args.sources)
    if decls is None:
        print(f"ERROR  {args.sources}: ディレクトリが存在しない")
        return 1
    if not decls.strip():
        print(f"ERROR  {args.sources}: ヘッダファイルが1つも見つからない")
        return 1

    # 設計の関数 -> 宣言
    for fn in funcs:
        if not re.search(r"\b" + re.escape(fn["name"]) + r"\s*\(", decls):
            rep.error(fn["id"], "設計にあるがヘッダに宣言が見つからない（P1 に戻る）")

    # レビュー指摘のクローズ状況
    review_counts = None
    if args.review_log:
        review_counts = check_review_log(args.review_log, rep)
        if review_counts is None:
            return 1

    n_public = sum(1 for f in funcs if f["visibility"] == "public")
    summary = f"突合: 設計関数 {len(funcs)} 件（public {n_public} 件）"
    if review_counts is not None:
        summary += (
            f" / レビュー指摘 {review_counts['open'] + review_counts['closed']} 件"
            f"（open {review_counts['open']}）"
        )
    print(summary)
    print()
    return rep.dump()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
