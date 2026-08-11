#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""レビュー指摘台帳に未クローズの指摘が残っていないかを検査する。

R4（報告と合意）のゲートとして実行する。

    python check_review_log.py work/review-log.md

終了コード:
    0  open の指摘なし（クローズ済み）
    1  open が残っている、または台帳の形式が不正
    2  引数の指定ミス

状態として認めるのは open / fixed / accepted / rejected の4つ。
open・未対応・対応中 は未クローズとして扱う。
表記揺れの吸収範囲と台帳の形式は references/scan-rules.md を参照。
依存は標準ライブラリのみ。
"""

import argparse
import re
import sys

# 列名の候補（表記揺れを吸収する）
COL_ID = {"id", "指摘id", "no", "no."}
COL_STATUS = {"状態", "ステータス", "status"}
COL_SEVERITY = {"重大度", "severity"}
COL_REASON = {"対応/理由", "対応・理由", "対応", "理由", "reason"}

OPEN_STATUSES = {"open", "未対応", "対応中"}
CLOSED_STATUSES = {"fixed", "accepted", "rejected", "修正済", "承認済", "不採用"}
NEEDS_REASON = {"accepted", "rejected", "承認済", "不採用"}
SEP_RE = re.compile(r":?-{2,}:?")

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
        print("指摘 %d 件（open %d / fixed %d / accepted %d / rejected %d）"
              % (total, counts["open"], counts["fixed"], counts["accepted"], counts["rejected"]))
        print("ERROR %d 件 / WARN %d 件" % (len(self.errors), len(self.warns)))
        if self.errors:
            print("不合格。open を残したまま完了として報告しないこと。")
        else:
            print("合格。未クローズの指摘はない。")
        return 1 if self.errors else 0


def normalize_status(raw):
    s = raw.strip().lower()
    if s in OPEN_STATUSES:
        return "open"
    if s in ("fixed", "修正済"):
        return "fixed"
    if s in ("accepted", "承認済"):
        return "accepted"
    if s in ("rejected", "不採用"):
        return "rejected"
    return None


def check(path, rep):
    """ID 列と状態列の両方を持つ表だけを見る。集計表や逸脱承認一覧は自然に除外される。"""
    counts = {"open": 0, "fixed": 0, "accepted": 0, "rejected": 0}
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as e:
        rep.error(path, "読み込めない (%s)" % e)
        return None, counts

    id_col = status_col = severity_col = reason_col = None
    seen_table = False
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if not s.startswith("|"):
            id_col = status_col = severity_col = reason_col = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(SEP_RE.fullmatch(c) for c in cells if c):
            continue
        lowered = [c.lower() for c in cells]

        if status_col is None:
            for idx, c in enumerate(lowered):
                if c in COL_ID and id_col is None:
                    id_col = idx
                elif c in COL_STATUS:
                    status_col = idx
                elif c in COL_SEVERITY:
                    severity_col = idx
                elif c in COL_REASON:
                    reason_col = idx
            if status_col is None or id_col is None:
                id_col = status_col = severity_col = reason_col = None
            else:
                seen_table = True
            continue

        if max(id_col, status_col) >= len(cells):
            continue
        rid = cells[id_col]
        raw_status = cells[status_col]
        if not rid or "<" in rid:
            continue  # テンプレートのプレースホルダ行

        status = normalize_status(raw_status)
        where = "%s:%d" % (path, n)
        if status is None:
            rep.error(where, "指摘 %s の状態が不正: '%s'（open / fixed / accepted / rejected のいずれか）"
                      % (rid, raw_status))
            continue

        counts[status] += 1
        if status == "open":
            rep.error(where, "指摘 %s が %s のまま残っている"
                             "（修正するか、ユーザーの了承を得て accepted にすること）" % (rid, raw_status))
            continue

        if status in ("accepted", "rejected") and reason_col is not None and reason_col < len(cells):
            if not cells[reason_col].strip() or cells[reason_col].strip() == "—":
                rep.error(where, "指摘 %s が %s だが、対応/理由が空。なぜ直さない / 違反でないのかを書くこと"
                          % (rid, status))

        if status == "accepted" and severity_col is not None and severity_col < len(cells):
            if cells[severity_col].strip() in ("高", "high"):
                rep.warn(where, "指摘 %s は重大度「高」で accepted。ユーザーの個別了承を得たか確認すること" % rid)

    if not seen_table:
        rep.error(path, "ID 列と状態列を持つ指摘一覧が読めない。"
                        "assets/templates/review-log.md の表形式を確認すること")
    elif sum(counts.values()) == 0:
        rep.error(path, "指摘が1件も登録されていない。"
                        "指摘0件だった場合も、当てた観点と結論を1行残すこと")
    return seen_table, counts


def main(argv):
    ap = argparse.ArgumentParser(description="レビュー指摘台帳の未クローズ検査")
    ap.add_argument("review_log", help="work/review-log.md")
    args = ap.parse_args(argv)

    rep = Report()
    _seen, counts = check(args.review_log, rep)
    return rep.dump(counts)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
