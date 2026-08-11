#!/usr/bin/env python3
"""設計 ⇔ 宣言 ⇔ テスト観点 ⇔ テストコードの4者を突き合わせ、欠落を列挙する。

使い方:
    python scripts/check_traceability.py --index work/design-index.json \
        --design work/test-design.md --tests test/ [--sources include/] \
        [--review-log work/review-log.md]

終了コード:
    0  欠落なし
    1  欠落あり
    2  引数誤り

検査する対応関係:

    design-index.json の functions[].id
      -> ヘッダに同名の宣言があるか            (--sources を渡したときのみ)
      -> test-design.md に対象関数として1行以上あるか   (public のみ)
    test-design.md の各行のテストID
      -> テストコードに TEST / TEST_F として存在するか
    テストコードのテストID
      -> test-design.md に対応行があるか        (無ければ WARN)
    review-log.md の各指摘                     (--review-log を渡したときのみ)
      -> 状態が open のまま残っていないか

P6 のゲートで使う。依存は標準ライブラリのみ。
"""

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEST_MACRO = re.compile(
    r"\bTEST(?:_F|_P)?\s*\(\s*([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)\s*\)"
)
TEST_SUFFIXES = {".cpp", ".cc", ".cxx"}
SOURCE_SUFFIXES = {".h", ".hpp", ".hh", ".hxx"}

# 観点表の列名の候補（表記揺れを吸収する）
COL_TEST_ID = {"テストID", "テストid", "test id", "testid", "id"}
COL_TARGET = {"対象関数", "対象", "関数", "target"}
# レビュー記録の列名の候補
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
            print("合格。設計・観点表・テストコードの対応に欠落はない。")
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
                    # 純粋仮想関数は実装を持たない（P3 でモックとして実装する）ので、
                    # 観点表との突合からは除外する。宣言の突合はそのまま行う。
                    "pure_virtual": bool(fn.get("is_pure_virtual", False)),
                }
            )
    if not funcs:
        rep.error(str(path), "classes[].functions が空。P0 の取り込みをやり直すこと")
    return funcs


def parse_design_table(path, rep):
    """観点表から (テストID, 対象関数) の一覧を取り出す。"""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        print(f"ERROR  {path}: 読み込めない ({e})")
        return None

    rows = []
    id_col = target_col = None
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if not s.startswith("|"):
            id_col = target_col = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        lowered = [c.lower() for c in cells]
        if id_col is None:
            for idx, c in enumerate(lowered):
                if c in COL_TEST_ID:
                    id_col = idx
                elif c in COL_TARGET:
                    target_col = idx
            if id_col is not None:
                continue  # 見出し行だった
            continue
        if target_col is None or max(id_col, target_col) >= len(cells):
            continue
        test_id = cells[id_col]
        target = cells[target_col]
        if not test_id or "<" in test_id:
            continue  # テンプレートのプレースホルダ行
        rows.append({"test_id": test_id, "target": target, "line": n})

    if not rows:
        rep.error(str(path), "テストIDを持つ行が1つも読めない。列名『テストID』『対象関数』を確認すること")
    return rows


def collect_tests(test_dir, rep):
    d = Path(test_dir)
    if not d.is_dir():
        print(f"ERROR  {test_dir}: ディレクトリが存在しない")
        return None
    found = {}
    for f in sorted(d.rglob("*")):
        if f.is_file() and f.suffix in TEST_SUFFIXES:
            text = f.read_text(encoding="utf-8", errors="replace")
            for suite, name in TEST_MACRO.findall(text):
                found.setdefault(name, []).append(f"{f}::{suite}")
    if not found:
        rep.error(str(test_dir), "TEST / TEST_F が1つも見つからない")
    return found


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
    ap.add_argument("--design", required=True, help="work/test-design.md")
    ap.add_argument("--tests", required=True, help="テストコードのディレクトリ")
    ap.add_argument("--sources", default=None, help="ヘッダのディレクトリ（省略可）")
    ap.add_argument("--review-log", default=None, help="work/review-log.md（省略可）")
    try:
        args = ap.parse_args(argv[1:])
    except SystemExit:
        return 2

    rep = Report()
    funcs = load_index(args.index, rep)
    rows = parse_design_table(args.design, rep)
    tests = collect_tests(args.tests, rep)
    if funcs is None or rows is None or tests is None:
        return 1

    decls = collect_declarations(args.sources) if args.sources else None
    if args.sources and decls is None:
        print(f"ERROR  {args.sources}: ディレクトリが存在しない")
        return 1

    # 1. 設計の関数 -> 宣言
    if decls is not None:
        for fn in funcs:
            if not re.search(r"\b" + re.escape(fn["name"]) + r"\s*\(", decls):
                rep.error(fn["id"], "設計にあるがヘッダに宣言が見つからない（P1 に戻る）")

    # 2. 設計の public 関数 -> 観点表
    targets = {r["target"] for r in rows}
    target_names = {t.split("::")[-1].split("(")[0] for t in targets}
    n_pure = 0
    for fn in funcs:
        if fn["visibility"] != "public":
            continue
        if fn["pure_virtual"]:
            n_pure += 1
            continue
        if fn["id"] not in targets and fn["name"] not in target_names:
            rep.error(fn["id"], "public 関数だが観点表に1行もない（P2 に戻る）")

    # 3. 観点表 -> テストコード
    known_ids = {fn["id"] for fn in funcs}
    known_names = {fn["name"] for fn in funcs}
    for r in rows:
        if r["test_id"] not in tests:
            rep.error(
                f"{args.design}:{r['line']}",
                f"観点 {r['test_id']} に対応する TEST / TEST_F がない（P3 に戻る）",
            )
        t = r["target"]
        if t and t not in known_ids and t.split("::")[-1].split("(")[0] not in known_names:
            rep.error(
                f"{args.design}:{r['line']}",
                f"対象関数 {t} が design-index.json に存在しない（設計にない関数をテストしている）",
            )

    # 4. テストコード -> 観点表
    design_ids = {r["test_id"] for r in rows}
    for name, places in tests.items():
        if name not in design_ids:
            rep.warn(places[0], f"テスト {name} が観点表にない。観点表に追記するか、テストを見直すこと")

    # 5. レビュー指摘のクローズ状況
    review_counts = None
    if args.review_log:
        review_counts = check_review_log(args.review_log, rep)
        if review_counts is None:
            return 1

    n_public = sum(1 for f in funcs if f["visibility"] == "public")
    summary = (
        f"突合: 設計関数 {len(funcs)} 件（public {n_public} 件"
        + (f"、うち純粋仮想 {n_pure} 件は観点表の対象外" if n_pure else "")
        + f"） / 観点 {len(rows)} 件 / テスト {len(tests)} 件"
    )
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
