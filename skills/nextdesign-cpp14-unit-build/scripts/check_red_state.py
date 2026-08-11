#!/usr/bin/env python3
"""テスト実行ログを解析し、実装前の RED が正しく成立しているかを判定する。

使い方:
    python scripts/check_red_state.py --design work/test-design.md --log work/red-evidence.txt

終了コード:
    0  正しく RED（観点表の全テストが実行され、全件失敗している）
    1  RED として認められない
    2  引数誤り

P3 のゲートで使う。「テストを書いた」だけでは、そのテストが何も検証していないことに
気づけない。実装が空のまま**全件が確かに失敗する**ことを機械的に確かめる。

RED と認めない条件:

  - テストが1件も実行されていない（ビルド失敗、ターゲット未登録、フィルタの効きすぎ）
  - 観点表にあるテストIDがログに現れない（テストの書き漏れ、名前の不一致）
  - 成功またはスキップしたテストがある
    → 実装が空なのに通るテストは、期待値を空実装の既定値に合わせて書いた疑いがある

ctest のテキスト出力と gtest 自体の出力の両方を解析する。どちらの形式でも、
テストIDだけを見て突き合わせる（スイート名は無視する）。

依存は標準ライブラリのみ。
"""

import argparse
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ctest:  "1/4 Test #1: MotorControllerTest.UT_Foo_001 ...***Failed    0.01 sec"
CTEST_LINE = re.compile(
    r"^\s*\d+/\d+\s+Test\s+#\d+:\s+(?P<name>\S+)\s+\.*\s*(?P<status>\*{3}\S*[^\r\n]*|Passed[^\r\n]*)"
)
# gtest:  "[       OK ] MotorControllerTest.UT_Foo_001 (0 ms)"
#         "[  FAILED  ] MotorControllerTest.UT_Foo_001"
#         "[  SKIPPED ] MotorControllerTest.UT_Foo_001"
GTEST_LINE = re.compile(
    r"^\[\s*(?P<status>OK|FAILED|SKIPPED)\s*\]\s+(?P<name>[\w./]+)"
)

# 観点表の列名候補（check_traceability.py と同じ）
COL_TEST_ID = {"テストID", "テストid", "test id", "testid", "id"}
COL_TARGET = {"対象関数", "対象", "関数", "target"}


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
            print("RED として認められない。実装を書かずに、上の指摘を解消すること。")
        else:
            print("RED 成立。実装（P4 / GREEN）に進んでよい。")
        return 1 if self.errors else 0


def parse_design_ids(path):
    """観点表からテストIDの一覧を取り出す。"""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        print(f"ERROR  {path}: 読み込めない ({e})")
        return None

    ids = []
    id_col = None
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            id_col = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        lowered = [c.lower() for c in cells]
        if id_col is None:
            for idx, c in enumerate(lowered):
                if c in COL_TEST_ID:
                    id_col = idx
                    break
            # 見出し行に「対象関数」等が並んでいるだけの行は読み飛ばす
            if id_col is not None:
                continue
            continue
        if id_col >= len(cells):
            continue
        test_id = cells[id_col]
        if not test_id or "<" in test_id or test_id.lower() in COL_TEST_ID:
            continue
        if test_id in COL_TARGET:
            continue
        ids.append(test_id)
    return ids


def parse_log(path):
    """実行ログから {テストID: 状態} を取り出す。状態は failed / passed / skipped。"""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"ERROR  {path}: 読み込めない ({e})")
        return None

    result = {}
    for line in text.splitlines():
        m = GTEST_LINE.match(line.strip())
        if m:
            name = m.group("name").split(".")[-1]
            status = {"OK": "passed", "FAILED": "failed", "SKIPPED": "skipped"}[
                m.group("status")
            ]
            # 同じテストが複数回出る場合、失敗を優先して残す
            if result.get(name) != "failed":
                result[name] = status
            continue
        m = CTEST_LINE.match(line)
        if m:
            name = m.group("name").split(".")[-1]
            raw = m.group("status")
            if raw.startswith("Passed"):
                status = "passed"
            elif "Skipped" in raw or "Not Run" in raw:
                status = "skipped"
            else:
                status = "failed"
            if result.get(name) != "failed":
                result[name] = status
    return result


def main(argv):
    ap = argparse.ArgumentParser(add_help=True, description=__doc__)
    ap.add_argument("--design", required=True, help="work/test-design.md")
    ap.add_argument("--log", required=True, help="ctest / gtest の実行ログ")
    try:
        args = ap.parse_args(argv[1:])
    except SystemExit:
        return 2

    design_ids = parse_design_ids(args.design)
    results = parse_log(args.log)
    if design_ids is None or results is None:
        return 1

    rep = Report()

    if not design_ids:
        rep.error(args.design, "テストIDを持つ行が1つも読めない。列名『テストID』を確認すること")

    if not results:
        rep.error(
            args.log,
            "テストが1件も実行されていない。ビルド失敗・テストターゲット未登録・"
            "フィルタの効きすぎのいずれかを疑うこと。ビルドエラーは RED ではない",
        )
        return rep.dump()

    failed = [n for n, s in results.items() if s == "failed"]
    passed = [n for n, s in results.items() if s == "passed"]
    skipped = [n for n, s in results.items() if s == "skipped"]

    for tid in design_ids:
        if tid not in results:
            rep.error(tid, "観点表にあるが実行されていない。テストの書き漏れか名前の不一致")

    for name in sorted(passed):
        rep.error(
            name,
            "実装前なのに成功している。期待値を空実装の既定値に合わせて書いた疑いがある。"
            "観点表の期待結果に立ち返って書き直すこと（実装を書いて RED を作らない）",
        )
    for name in sorted(skipped):
        rep.error(name, "スキップされている。DISABLED_ / GTEST_SKIP() を外すこと")

    for name in sorted(results):
        if name not in design_ids:
            rep.warn(name, "観点表にないテストが実行されている。観点表に追記するか見直すこと")

    print(
        f"判定: 観点表 {len(design_ids)} 件 / 実行 {len(results)} 件 "
        f"（失敗 {len(failed)} / 成功 {len(passed)} / スキップ {len(skipped)}）"
    )
    print()
    return rep.dump()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
