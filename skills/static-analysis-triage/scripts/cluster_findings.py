#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指摘をフィンガープリントで束ね、判定DBの過去の判定を再適用する。

T2（クラスタリング）と T5（判定DBの保存）で使う。

    python cluster_findings.py --findings work/findings.json --scope work/triage-scope.json \
        -o work/clusters.json
    python cluster_findings.py --clusters work/clusters.json --scope work/triage-scope.json \
        --save-decisions

終了コード:
    0  正常
    1  入力が不正（指摘0件 / 判定DBが壊れている / 判定の入っていないクラスタを保存しようとした）
    2  引数の指定ミス、ファイルが無い

フィンガープリントの設計と uniformity の判断基準は references/clustering.md を参照。
依存は標準ライブラリのみ。
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

# uniformity の推定。references/clustering.md の表と対応させること。
INDIVIDUAL_KEYWORDS = (
    "null", "ヌル", "dereference", "参照外し",
    "bound", "境界", "overflow", "オーバーフロー", "underflow",
    "uninitial", "未初期化", "initialized",
    "leak", "リーク", "free", "解放", "resource", "リソース",
    "alias", "別名", "race", "競合", "concurren", "並行", "thread",
    "interrupt", "割込", "割り込み", "atomic",
    "divide", "division", "除算", "zero", "ゼロ除",
    "unreachable", "到達不能", "dead code", "デッドコード",
    "range", "値域", "taint", "use after", "double free", "deadlock",
    "buffer", "バッファ", "index", "添字",
)
UNIFORM_KEYWORDS = (
    "cast", "キャスト", "conversion", "変換",
    "brace", "波括弧", "ブレース", "goto",
    "magic", "マジックナンバー", "literal",
    "naming", "命名", "identifier name",
    "include", "インクルード", "header guard", "インクルードガード",
    "switch", "default", "enum", "列挙",
    "const", "constexpr", "explicit",
    "signed", "unsigned", "符号",
    "comment", "コメント", "indent", "字下げ",
    "declaration", "宣言", "typedef", "using",
)

# コード断片の正規化で残す識別子。型と修飾子が問題の種類を決めるので、これだけ残して
# 変数名・関数名は ID に潰す。残さないと value_0 と value_1 が別クラスタになる。
KEEP_IDENTIFIERS = frozenset("""
alignas alignof asm auto bool break case catch char char16_t char32_t class const
constexpr const_cast continue decltype default delete do double dynamic_cast else
enum explicit export extern false float for friend goto if inline int long mutable
namespace new noexcept nullptr operator private protected public register
reinterpret_cast return short signed sizeof static static_assert static_cast struct
switch template this thread_local throw true try typedef typeid typename union
unsigned using virtual void volatile wchar_t while
int8_t int16_t int32_t int64_t uint8_t uint16_t uint32_t uint64_t
int_least8_t int_least16_t int_least32_t int_least64_t
uint_least8_t uint_least16_t uint_least32_t uint_least64_t
int_fast8_t int_fast16_t int_fast32_t int_fast64_t
uint_fast8_t uint_fast16_t uint_fast32_t uint_fast64_t
size_t ssize_t ptrdiff_t intptr_t uintptr_t intmax_t uintmax_t
std NULL nullptr_t
""".split())

IDENT_RE = re.compile(r"[A-Za-z_]\w*")
NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
HEX_RE = re.compile(r"\b0[xX][0-9a-fA-F]+\b")
QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`")
STR_RE = re.compile(r"\"(?:\\.|[^\"\\])*\"")
CHR_RE = re.compile(r"'(?:\\.|[^'\\])*'")
WS_RE = re.compile(r"\s+")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def die(code, msg):
    print("ERROR  %s" % msg, file=sys.stderr)
    sys.exit(code)


def load_json(path, code=2):
    if not os.path.isfile(path):
        die(code, "見つからない: %s" % path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        die(code, "読めない: %s (%s)" % (path, e))


def save_json(path, payload):
    out_dir = os.path.dirname(os.path.abspath(path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def now():
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def normalize_message(text):
    """メッセージを正規化する。引用された識別子と数値を潰す。"""
    s = QUOTED_RE.sub("ID", text or "")
    s = HEX_RE.sub("N", s)
    s = NUM_RE.sub("N", s)
    return WS_RE.sub(" ", s).strip().lower()


def normalize_code(text):
    """コード断片を正規化する。リテラル・数値・変数名を潰し、型と修飾子だけ残す。"""
    s = STR_RE.sub("S", text or "")
    s = CHR_RE.sub("C", s)
    s = HEX_RE.sub("N", s)
    s = NUM_RE.sub("N", s)
    s = IDENT_RE.sub(lambda m: m.group(0) if m.group(0) in KEEP_IDENTIFIERS else "ID", s)
    return WS_RE.sub(" ", s).strip()


def fingerprint_of(rec):
    material = "|".join((
        (rec.get("rule_id") or "").strip(),
        normalize_message(rec.get("message")),
        normalize_code(rec.get("code")),
    ))
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]


def guess_uniformity(rec):
    """ルールIDとメッセージのキーワードから uniformity を推定する。

    推定でしかないので、T3 で人が上書きしてよい。迷ったら individual に倒す。
    """
    hay = ("%s %s" % (rec.get("rule_id") or "", rec.get("message") or "")).lower()
    if any(k in hay for k in INDIVIDUAL_KEYWORDS):
        return "individual"
    if any(k in hay for k in UNIFORM_KEYWORDS):
        return "uniform"
    return "unknown"


def is_external(path, prefixes):
    p = (path or "").replace("\\", "/").lstrip("./")
    return any(p.startswith(x.replace("\\", "/").lstrip("./")) for x in prefixes if x)


def load_decisions(path):
    if not path or not os.path.isfile(path):
        return {}, 0
    data = load_json(path, code=1)
    if not isinstance(data, dict) or not isinstance(data.get("decisions"), dict):
        die(1, "判定DBが壊れている（decisions オブジェクトが無い）: %s" % path)
    return data["decisions"], len(data["decisions"])


def build(findings_path, scope, out_path):
    data = load_json(findings_path)
    findings = data.get("findings") or []
    if not findings:
        die(1, "指摘が0件。T1 の出力を確認すること")

    externals = scope.get("external_paths") or []
    tools = scope.get("tools") or []
    default_tool = tools[0]["name"] if len(tools) == 1 and "name" in tools[0] else ""

    groups = {}
    for rec in findings:
        fp = fingerprint_of(rec)
        ext = is_external(rec.get("file"), externals)
        # 外部提供コードと自社コードは判定が割れる（DV-EXT か fix か）ので別クラスタにする。
        cluster_id = fp + ("@external" if ext else "")
        g = groups.setdefault(cluster_id, {
            "cluster_id": cluster_id,
            "fingerprint": fp,
            "external": ext,
            "rule_id": (rec.get("rule_id") or "").strip(),
            "tool": (rec.get("tool") or default_tool).strip(),
            "uniformity": guess_uniformity(rec),
            "uniformity_source": "heuristic",
            "representative": {
                "file": rec.get("file", ""),
                "line": rec.get("line", ""),
                "function": rec.get("function", ""),
                "message": rec.get("message", ""),
                "code": rec.get("code", ""),
            },
            "members": [],
        })
        g["members"].append({
            "row": rec.get("row"),
            "id": rec.get("id", ""),
            "file": rec.get("file", ""),
            "line": rec.get("line", ""),
        })

    decisions, db_size = load_decisions(scope.get("decisions_db"))

    clusters = []
    auto_applied = 0
    hinted = 0
    for g in groups.values():
        g["member_count"] = len(g["members"])
        g["status"] = "pending"
        g["verdict"] = None
        g["code"] = None
        g["rationale"] = None
        g["alternative"] = None
        g["auto_applied"] = False
        g["previous_decision"] = None

        prev = decisions.get(g["cluster_id"])
        if prev:
            if g["uniformity"] == "individual":
                # 文脈依存の判定を字面で引き継ぐのは危険。参考情報に留める。
                g["previous_decision"] = prev
                hinted += 1
            else:
                g["verdict"] = prev.get("verdict")
                g["code"] = prev.get("code")
                g["rationale"] = prev.get("rationale")
                g["alternative"] = prev.get("alternative")
                g["auto_applied"] = True
                g["status"] = "done"
                auto_applied += 1
        clusters.append(g)

    clusters.sort(key=lambda c: (-c["member_count"], c["cluster_id"]))

    payload = {
        "version": 1,
        "generated_at": now(),
        "source": findings_path,
        "decisions_db": scope.get("decisions_db"),
        "clusters": clusters,
    }
    save_json(out_path, payload)

    total = len(findings)
    n_cluster = len(clusters)
    ratio = (total / n_cluster) if n_cluster else 0
    counts = {"uniform": 0, "individual": 0, "unknown": 0}
    for c in clusters:
        counts[c["uniformity"]] += 1

    print("指摘 %d 件 → クラスタ %d 個（圧縮率 %.1f 倍）" % (total, n_cluster, ratio))
    print("uniformity: uniform %d / individual %d / unknown %d"
          % (counts["uniform"], counts["individual"], counts["unknown"]))
    print("判定DB: %s（登録 %d 件）"
          % (scope.get("decisions_db") or "未設定", db_size))
    print("自動再適用: %d クラスタ / 参考表示のみ（individual）: %d クラスタ" % (auto_applied, hinted))
    print("未判定: %d クラスタ" % sum(1 for c in clusters if c["status"] == "pending"))
    print("出力: %s" % out_path)

    if auto_applied:
        print()
        print("T2 の抜き取り確認を行うこと。auto_applied のクラスタから3件（3件未満なら全件）を選び、")
        print("コードを読んで判定が今回のコードにも妥当か確認する。1件でも妥当でなければ、")
        print("そのルールIDの自動再適用をすべて解除して T3 で判定し直すこと。")
    if n_cluster > total * 0.8:
        print()
        print("WARN   クラスタ数が指摘件数の8割を超えている。ほとんど束ねられていない。")
        print("       form-spec.json に code 列や function 列を足せないか T0 に戻って確認すること。")
    return 0


def save_decisions(clusters_path, scope):
    db_path = scope.get("decisions_db")
    if not db_path:
        die(2, "triage-scope.json に decisions_db が無い")

    data = load_json(clusters_path)
    clusters = data.get("clusters") or []
    if not clusters:
        die(1, "クラスタが0件: %s" % clusters_path)

    unjudged = [c["cluster_id"] for c in clusters
                if c.get("uniformity") != "individual" and not c.get("verdict")]
    if unjudged:
        die(1, "判定の入っていないクラスタが %d 件ある。先に T3 を終えること（例: %s）"
            % (len(unjudged), ", ".join(unjudged[:3])))

    existing, _ = load_decisions(db_path)
    saved = skipped_deferred = skipped_individual = 0
    for c in clusters:
        if c.get("uniformity") == "individual":
            # メンバーごとに判定が違うため、クラスタ単位では保存できない。
            skipped_individual += 1
            continue
        if c.get("verdict") == "deferred":
            # 判断していないものを引き継ぐと、判断済みに見えてしまう。
            skipped_deferred += 1
            continue
        existing[c["cluster_id"]] = {
            "verdict": c.get("verdict"),
            "code": c.get("code"),
            "rationale": c.get("rationale"),
            "alternative": c.get("alternative"),
            "rule_id": c.get("rule_id"),
            "tool": c.get("tool"),
            "external": c.get("external", False),
            "decided_at": now(),
            "project": scope.get("project", ""),
            "standard": scope.get("standard", ""),
        }
        saved += 1

    save_json(db_path, {"version": 1, "updated_at": now(), "decisions": existing})
    print("判定DB: %s" % db_path)
    print("保存: %d 件 / 登録総数: %d 件" % (saved, len(existing)))
    print("除外: deferred %d 件（判断していないため保存しない）/ individual %d 件（メンバー単位の判定のため）"
          % (skipped_deferred, skipped_individual))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description="指摘のクラスタリングと判定DBの再適用・保存")
    ap.add_argument("--scope", required=True, metavar="JSON", help="work/triage-scope.json")
    ap.add_argument("--findings", metavar="JSON", help="work/findings.json（クラスタリング時）")
    ap.add_argument("--clusters", metavar="JSON", help="work/clusters.json（保存時）")
    ap.add_argument("-o", "--out", metavar="JSON", default="work/clusters.json",
                    help="出力先（既定: work/clusters.json）")
    ap.add_argument("--save-decisions", action="store_true",
                    help="判定結果を判定DBに保存する（--clusters と併用）")
    args = ap.parse_args(argv)

    scope = load_json(args.scope)

    if args.save_decisions:
        if not args.clusters:
            ap.error("--save-decisions には --clusters が要る")
        return save_decisions(args.clusters, scope)
    if not args.findings:
        ap.error("--findings か --save-decisions のどちらかを指定すること")
    return build(args.findings, scope, args.out)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
