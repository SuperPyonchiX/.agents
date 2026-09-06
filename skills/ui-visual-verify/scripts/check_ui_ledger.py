#!/usr/bin/env python3
"""UI 指摘台帳の完了判定。

使い方:
    python check_ui_ledger.py <ui-ledger.md>

終了コード:
    0  合格（open / fixed が無く、closed は after 画像あり、deferred は理由あり）
    1  ERROR あり（内容を標準出力に列挙）
    2  引数の指定ミス、またはファイルが読めない

依存: 標準ライブラリのみ。
"""
import os
import sys

STATES = {"open", "fixed", "closed", "deferred"}
# 台帳の列順（assets/templates/ui-ledger.md と一致させる）
COL_ID, COL_ISSUE, COL_TARGET, COL_BEFORE_M, COL_CHANGE, COL_AFTER_M, COL_BEFORE, COL_AFTER, COL_ROUND, COL_STATE, COL_NOTE = range(11)


def parse_rows(lines):
    rows = []
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 11 or not cells[COL_ID].startswith("UI-"):
            continue
        rows.append((n, cells))
    return rows


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    path = argv[1]
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        print(f"ERROR: 台帳を読めない: {e}")
        return 2

    base = os.path.dirname(os.path.abspath(path))
    rows = parse_rows(lines)
    errors = []
    counts = {s: 0 for s in STATES}

    if not rows:
        errors.append("台帳に UI-xxx の行が1件も無い")

    for n, c in rows:
        state = c[COL_STATE]
        if state not in STATES:
            errors.append(f"L{n} {c[COL_ID]}: 状態 '{state}' は不正（{'/'.join(sorted(STATES))}）")
            continue
        counts[state] += 1
        if state in ("open", "fixed"):
            errors.append(f"L{n} {c[COL_ID]}: {state} が残っている")
        if state == "closed":
            after = c[COL_AFTER]
            if not after:
                errors.append(f"L{n} {c[COL_ID]}: closed だが after 画像のパスが無い")
            elif not os.path.exists(os.path.join(base, after)) and not os.path.exists(after):
                errors.append(f"L{n} {c[COL_ID]}: after 画像が見つからない: {after}")
            if not c[COL_AFTER_M]:
                errors.append(f"L{n} {c[COL_ID]}: closed だが修正後の計測が空")
        if state == "deferred" and not c[COL_NOTE]:
            errors.append(f"L{n} {c[COL_ID]}: deferred だが備考（理由）が空")

    print("集計: " + ", ".join(f"{s}={counts[s]}" for s in ("open", "fixed", "closed", "deferred")))
    for e in errors:
        print("ERROR: " + e)
    if errors:
        return 1
    print("合格: 未クローズ残なし")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
