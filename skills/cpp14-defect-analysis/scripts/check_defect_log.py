#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仮説台帳に未クローズの仮説が残っていないかを検査する。

D6（水平展開と報告）のゲートとして実行する。

    python check_defect_log.py work/hypotheses.md [--unresolved]

--unresolved は根本原因を特定できずに終える場合に付ける。confirmed 0 件を
ERROR ではなく WARN に落とす。未解決であることを報告に明記した場合にだけ使う。

終了コード:
    0  未クローズなし（合格）
    1  ERROR あり、または台帳の形式が不正
    2  引数の指定ミス

状態として認めるのは open / running / confirmed / rejected / deferred の5つ。
open と running は未クローズとして扱う。
台帳の形式は assets/templates/hypotheses.md を参照。
依存は標準ライブラリのみ。
"""

import argparse
import re
import sys

# 列名の候補（表記揺れを吸収する）
COL_ID = {"id", "仮説id", "no", "no."}
COL_STATUS = {"状態", "ステータス", "status"}
COL_METHOD = {"検証方法", "検証手段", "method"}
COL_RESULT = {"検証結果", "結果", "result"}
COL_ORDER = {"順", "検証順", "order"}

OPEN_STATUSES = {"open", "未検証"}
RUNNING_STATUSES = {"running", "検証中"}
EMPTY_CELLS = {"", "—", "-", "ー", "n/a", "na", "tbd", "未記入"}

SEP_RE = re.compile(r":?-{2,}:?")
UPPER_LIMIT = 8  # D3 の検証上限（confirmed + rejected）

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


class Report(object):
    def __init__(self):
        self.errors = []
        self.warns = []

    def error(self, where, msg):
        self.errors.append((where, msg))

    def warn(self, where, msg):
        self.warns.append((where, msg))

    def dump(self, counts):
        for where, msg in self.errors:
            print("ERROR  %s: %s" % (where, msg))
        for where, msg in self.warns:
            print("WARN   %s: %s" % (where, msg))
        print()
        total = sum(counts.values())
        print("仮説 %d 件（open %d / running %d / confirmed %d / rejected %d / deferred %d）"
              % (total, counts["open"], counts["running"], counts["confirmed"],
                 counts["rejected"], counts["deferred"]))
        print("検証実施 %d 件 / 上限 %d 件"
              % (counts["confirmed"] + counts["rejected"], UPPER_LIMIT))
        print("ERROR %d 件 / WARN %d 件" % (len(self.errors), len(self.warns)))
        if self.errors:
            print("不合格。未クローズの仮説を残したまま完了として報告しないこと。")
        else:
            print("合格。未クローズの仮説はない。")
        return 1 if self.errors else 0


def normalize_status(raw):
    s = raw.strip().lower()
    if s in OPEN_STATUSES:
        return "open"
    if s in RUNNING_STATUSES:
        return "running"
    if s in ("confirmed", "確定", "採用"):
        return "confirmed"
    if s in ("rejected", "棄却", "不採用"):
        return "rejected"
    if s in ("deferred", "見送り", "未実施"):
        return "deferred"
    return None


def is_empty(cell):
    return cell.strip().lower() in EMPTY_CELLS


def check(path, rep):
    """ID 列と状態列の両方を持つ表だけを見る。集計表や履歴は自然に除外される。"""
    counts = {"open": 0, "running": 0, "confirmed": 0, "rejected": 0, "deferred": 0}
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as e:
        rep.error(path, "読み込めない (%s)" % e)
        return False, counts

    cols = {}
    seen_table = False
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if not s.startswith("|"):
            cols = {}
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(SEP_RE.fullmatch(c) for c in cells if c):
            continue
        lowered = [c.lower() for c in cells]

        if "status" not in cols:
            found = {}
            for idx, c in enumerate(lowered):
                if c in COL_ID and "id" not in found:
                    found["id"] = idx
                elif c in COL_STATUS:
                    found["status"] = idx
                elif c in COL_METHOD:
                    found["method"] = idx
                elif c in COL_RESULT:
                    found["result"] = idx
                elif c in COL_ORDER:
                    found["order"] = idx
            if "status" in found and "id" in found:
                cols = found
                seen_table = True
            continue

        if max(cols["id"], cols["status"]) >= len(cells):
            continue
        hid = cells[cols["id"]]
        raw_status = cells[cols["status"]]
        if not hid or "<" in hid:
            continue  # テンプレートのプレースホルダ行

        status = normalize_status(raw_status)
        where = "%s:%d" % (path, n)
        if status is None:
            rep.error(where, "仮説 %s の状態が不正: '%s'"
                             "（open / running / confirmed / rejected / deferred のいずれか）"
                      % (hid, raw_status))
            continue

        counts[status] += 1

        if status == "open":
            rep.error(where, "仮説 %s が未検証のまま残っている"
                             "（検証するか、別仮説が確定したため見送るなら deferred に理由付きで落とすこと）"
                      % hid)
            continue
        if status == "running":
            rep.error(where, "仮説 %s が検証中のまま残っている"
                             "（中断された可能性がある。open に戻して検証し直すこと）" % hid)
            continue

        # 検証結果は confirmed / rejected / deferred のすべてで必須
        if "result" in cols and cols["result"] < len(cells):
            if is_empty(cells[cols["result"]]):
                if status == "deferred":
                    rep.error(where, "仮説 %s が deferred だが検証結果が空。"
                                     "なぜ検証しなくてよいと判断したかを書くこと" % hid)
                else:
                    rep.error(where, "仮説 %s が %s だが検証結果が空。観測した事実を書くこと"
                              % (hid, status))

        # 検証方法は実際に検証したもの（confirmed / rejected）で必須
        if status in ("confirmed", "rejected") and "method" in cols and cols["method"] < len(cells):
            if is_empty(cells[cols["method"]]):
                rep.error(where, "仮説 %s が %s だが検証方法が空。"
                                 "何をどこで観測して判断したかを書くこと" % (hid, status))

        if status in ("confirmed", "rejected") and "order" in cols and cols["order"] < len(cells):
            if is_empty(cells[cols["order"]]):
                rep.warn(where, "仮説 %s に検証順が付いていない。"
                                "確度とコストで並べ替えたか確認すること" % hid)

    return seen_table, counts


def judge(seen_table, counts, unresolved, rep, path):
    if not seen_table:
        rep.error(path, "ID 列と状態列を持つ仮説一覧が読めない。"
                        "assets/templates/hypotheses.md の表形式を確認すること")
        return
    total = sum(counts.values())
    if total == 0:
        rep.error(path, "仮説が1件も登録されていない")
        return
    if total < 3:
        rep.warn(path, "仮説が %d 件しかない。1〜2件で進めると、その仮説に合う証拠だけを集めることになる。"
                       "references/defect-patterns.md の各パターンを当てて追加したか確認すること" % total)

    verified = counts["confirmed"] + counts["rejected"]
    if verified > UPPER_LIMIT:
        rep.warn(path, "検証実施が %d 件で上限 %d 件を超えている。"
                       "収束していない可能性がある。方針を変えるかユーザーに相談すること"
                 % (verified, UPPER_LIMIT))

    if counts["confirmed"] == 0:
        msg = ("根本原因が確定していない（confirmed 0 件）。"
               "未解決として報告するなら、試した仮説と観測できた事実と次に試すべきことを"
               "報告に明記すること")
        if unresolved:
            rep.warn(path, msg + "（--unresolved 指定のため WARN に落とした）")
        else:
            rep.error(path, msg + "。未解決で終える場合は --unresolved を付けて実行すること")
    elif counts["confirmed"] > 1:
        rep.warn(path, "confirmed が %d 件ある。複合要因なら妥当だが、"
                       "それぞれが現象のどの部分を説明するのかを報告に書くこと" % counts["confirmed"])


def main(argv):
    ap = argparse.ArgumentParser(description="仮説台帳の未クローズ検査")
    ap.add_argument("hypotheses_log", help="work/hypotheses.md")
    ap.add_argument("--unresolved", action="store_true",
                    help="根本原因を特定できずに終える場合に付ける。confirmed 0 件を WARN に落とす")
    args = ap.parse_args(argv)

    rep = Report()
    seen_table, counts = check(args.hypotheses_log, rep)
    judge(seen_table, counts, args.unresolved, rep, args.hypotheses_log)
    return rep.dump(counts)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
