#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""トリアージ結果に未判定と根拠欠落が残っていないかを検査する。

T5（完了判定）のゲートとして実行する。

    python check_triage.py work/clusters.json

終了コード:
    0  合格。未判定と根拠欠落がない
    1  未判定または根拠欠落がある
    2  引数の指定ミス、ファイルが無い

判定値と必須項目の意味は references/triage-criteria.md を参照。
依存は標準ライブラリのみ。
"""

import argparse
import json
import os
import sys

VERDICTS = ("fix", "deviate", "false_positive", "deferred")
FP_CODES = ("FP-PATH", "FP-RANGE", "FP-ALIAS", "FP-EXT", "FP-MACRO", "FP-CFG", "FP-STD")
DV_CODES = ("DV-HW", "DV-PERF", "DV-EXT", "DV-COMPAT", "DV-LANG", "DV-STD")
EMPTY = ("", "—", "-", "なし", "n/a", "na", "tbd", "未定")
MIN_RATIONALE = 10  # 根拠として最低限の文字数。「問題ない」で閉じさせない

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


def is_blank(value):
    return not value or str(value).strip().lower() in EMPTY


def check_verdict(rep, where, verdict, code, rationale, alternative):
    """1件分の判定を検査する。クラスタ単位でもメンバー単位でも同じ規則を当てる。"""
    if is_blank(verdict):
        rep.error(where, "未判定。verdict が空")
        return None
    v = str(verdict).strip()
    if v not in VERDICTS:
        rep.error(where, "verdict が不正: '%s'（%s のいずれか）" % (v, " / ".join(VERDICTS)))
        return None

    if is_blank(rationale):
        rep.error(where, "%s だが rationale が空。判断の根拠を書くこと" % v)
    elif len(str(rationale).strip()) < MIN_RATIONALE:
        rep.warn(where, "%s の rationale が短い: '%s'。"
                        "後から他人が読んで判断を追える粒度にすること" % (v, rationale))

    c = ("" if is_blank(code) else str(code).strip().upper())
    if v == "false_positive":
        if not c:
            rep.error(where, "false_positive だが FP コードが無い。"
                             "解析限界を特定できないなら deferred にすること")
        elif c not in FP_CODES:
            rep.error(where, "FP コードが不正: '%s'（%s のいずれか）" % (c, " / ".join(FP_CODES)))
    elif v == "deviate":
        if not c:
            rep.error(where, "deviate だが DV コードが無い")
        elif c not in DV_CODES:
            rep.error(where, "DV コードが不正: '%s'（%s のいずれか）" % (c, " / ".join(DV_CODES)))
        if is_blank(alternative):
            rep.error(where, "deviate だが代替措置 (alternative) が空。"
                             "代替措置のない逸脱はリスクを放置しているのと同じ")
    elif c:
        rep.warn(where, "%s に分類コード '%s' が付いている。fix / deferred では使わない" % (v, c))

    return v


def check(path, rep):
    counts = dict((v, 0) for v in VERDICTS)
    deferred = []

    if not os.path.isfile(path):
        print("ERROR  見つからない: %s" % path, file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print("ERROR  読めない: %s (%s)" % (path, e), file=sys.stderr)
        sys.exit(2)

    clusters = data.get("clusters") or []
    if not clusters:
        rep.error(path, "クラスタが0件。T2 の出力を確認すること")
        return counts, deferred, 0

    total_members = 0
    for c in clusters:
        cid = c.get("cluster_id") or c.get("fingerprint") or "?"
        where = "%s [%s]" % (cid, c.get("rule_id") or "-")
        members = c.get("members") or []
        total_members += len(members)

        if c.get("status") != "done":
            rep.error(where, "status が '%s' のまま。T3 で判定してから完了にすること"
                      % (c.get("status") or "未設定"))

        if c.get("uniformity") == "unknown":
            rep.error(where, "uniformity が unknown のまま。"
                             "T3 で uniform か individual かを決めること")

        if c.get("uniformity") == "individual":
            # メンバーごとに判定が要る。
            if not members:
                rep.error(where, "individual だがメンバーが無い")
            for m in members:
                mwhere = "%s / 行%s" % (where, m.get("row"))
                v = check_verdict(rep, mwhere, m.get("verdict"), m.get("code"),
                                  m.get("rationale"), m.get("alternative"))
                if v:
                    counts[v] += 1
                    if v == "deferred":
                        deferred.append((mwhere, m.get("rationale") or ""))
        else:
            v = check_verdict(rep, where, c.get("verdict"), c.get("code"),
                              c.get("rationale"), c.get("alternative"))
            if v:
                n = max(len(members), 1)
                counts[v] += n
                if v == "deferred":
                    deferred.append(("%s（%d 件）" % (where, n), c.get("rationale") or ""))

    return counts, deferred, total_members


def main(argv):
    ap = argparse.ArgumentParser(description="トリアージ結果の未判定・根拠欠落の検査")
    ap.add_argument("clusters", help="work/clusters.json")
    args = ap.parse_args(argv)

    rep = Report()
    counts, deferred, total = check(args.clusters, rep)

    for where, msg in rep.errors:
        print("ERROR  %s: %s" % (where, msg))
    for where, msg in rep.warns:
        print("WARN   %s: %s" % (where, msg))

    print()
    judged = sum(counts.values())
    print("指摘 %d 件中 %d 件に判定あり" % (total, judged))
    print("  fix %d / deviate %d / false_positive %d / deferred %d"
          % (counts["fix"], counts["deviate"], counts["false_positive"], counts["deferred"]))

    if deferred:
        print()
        print("deferred（T5 の報告で全件を個別に列挙すること）:")
        for where, reason in deferred:
            print("  - %s: %s" % (where, reason or "（理由が空。何が足りないかを書くこと）"))

    print()
    print("ERROR %d 件 / WARN %d 件" % (len(rep.errors), len(rep.warns)))
    if rep.errors:
        print("不合格。未判定を残したまま完了として報告しないこと。")
        return 1
    print("合格。未判定と根拠欠落はない。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
