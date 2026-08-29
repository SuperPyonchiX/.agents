#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スキル置き場を横断して健全性を検査する。

A1（機械検査）で実行する。1スキル単位の検証（validate_skill.py）では見られない
「スキル間の関係」と「配布時にしか判明しない不備」をまとめて洗う。

    python audit_skills.py <skills-dir> [-o work/audit-report.json]
                           [--validator <validate_skill.py のパス>]
                           [--readme <README.md のパス>]

検査するもの:
    1. web-description   欠落 / 200文字超過 / 山括弧の混入（pack_skill.py の判定条件と同じ）
    2. frontmatter       name とディレクトリ名の一致、description の長さと山括弧
    3. 個別検証の集約    --validator を渡すと各スキルに対して実行し、結果を1表にまとめる
    4. 発火競合          description のトリガー文言と特徴語が重なるスキルのペアを候補として出す
    5. 棲み分け宣言      競合候補が互いの description で名指しの振り分けをしているか
    6. README 突合       --readme を渡すと収録スキル表と実体、および表中の行数を突き合わせる

終了コード:
    0  ERROR なし（WARN のみの場合も 0）
    1  ERROR あり
    2  引数の指定ミス

競合候補の判定は機械の目安でしかない。採否は A2 でエージェントが判断する。
依存は標準ライブラリのみ。
"""

import argparse
import itertools
import json
import os
import re
import subprocess
import sys

WEB_DESC_LIMIT = 200      # claude.ai の description 上限
DESC_LIMIT = 1024         # Agent Skills 仕様の上限
NAME_LIMIT = 64
SKILL_BODY_LIMIT = 500

JACCARD_THRESHOLD = 0.18  # 特徴語の重なりで競合候補とみなす下限
TRIGGER_MIN_LEN = 6       # 部分一致で同一トリガーとみなす最短長
TRIGGER_MIN_NORM_LEN = 4  # これより短い鉤括弧内はトリガーとみなさない
WARN_SCORE = 2.5          # これ未満の候補は一覧に載せるだけで WARN にしない

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TRIGGER_RE = re.compile(r"[「『]([^」』]{2,40})[」』]")
TERM_RE = re.compile(r"[一-鿿]{2,}|[゠-ヿ]{3,}|[A-Za-z][A-Za-z0-9+#.\-]{2,}")
README_ROW_RE = re.compile(r"^\|\s*`([a-z0-9][a-z0-9-]*)`\s*\|(.*)$")
README_LINES_RE = re.compile(r"\|\s*(\d+)\s*行\s*\|")

# description の定型部分。これを特徴語から除かないと全スキルが互いに競合候補になる
STOPWORDS = frozenset([
    "スキル", "使う", "場合", "担当", "そちら", "こちら", "明示", "言及", "必ず",
    "依頼", "作業", "対象", "出力", "入力", "内容", "形式", "確認", "実行", "作成",
    "手順", "工程", "結果", "情報", "以下", "次の", "自分", "全体", "個別", "両方",
    "とき", "ため", "こと", "もの", "これ", "それ", "など", "また", "さらに",
    "ファイル", "ユーザー", "エージェント", "ドキュメント",
])

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
        self.errors.append({"where": where, "message": msg})

    def warn(self, where, msg):
        self.warns.append({"where": where, "message": msg})


# --------------------------------------------------------------------------
# frontmatter の読み取り
# --------------------------------------------------------------------------

def parse_frontmatter(text):
    """SKILL.md の frontmatter を読む。ネストは metadata の1段だけ扱えれば足りる。

    戻り値は (トップレベルの dict, metadata の dict)。frontmatter が無ければ (None, {})。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, {}
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, {}

    top, meta = {}, {}
    current_key = None
    in_metadata = False
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw[:1] in (" ", "\t")
        m = re.match(r"^(\s*)([A-Za-z0-9_-]+)\s*:\s*(.*)$", raw)
        if m:
            indent, key, value = m.group(1), m.group(2), m.group(3).strip()
            if indent:
                if in_metadata:
                    meta[key] = strip_quotes(value)
                    current_key = ("meta", key)
                continue
            in_metadata = (key == "metadata")
            top[key] = strip_quotes(value)
            current_key = ("top", key)
            continue
        if indented and current_key:  # 折り返し行
            scope, key = current_key
            target = meta if scope == "meta" else top
            target[key] = (target.get(key, "") + " " + raw.strip()).strip()
    return top, meta


def strip_quotes(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


# --------------------------------------------------------------------------
# 1スキルの読み取りと単体検査
# --------------------------------------------------------------------------

def load_skill(skills_dir, name, rep):
    path = os.path.join(skills_dir, name, "SKILL.md")
    where = os.path.join(name, "SKILL.md")
    if not os.path.isfile(path):
        rep.error(name, "SKILL.md がない。スキルとして読み込まれない")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        rep.error(where, "読み込めない (%s)" % e)
        return None

    top, meta = parse_frontmatter(text)
    if top is None:
        rep.error(where, "frontmatter が読めない。--- で囲まれているか確認すること")
        return None

    body_lines = len(text.splitlines())
    skill = {
        "name": name,
        "declared_name": top.get("name", ""),
        "description": top.get("description", ""),
        "web_description": meta.get("web-description", ""),
        "lines": body_lines,
        "path": where,
    }

    if skill["declared_name"] != name:
        rep.error(where, "name '%s' がディレクトリ名 '%s' と一致しない。"
                         "読み込まれず、エラーも出ない" % (skill["declared_name"], name))
    if not NAME_RE.match(name) or len(name) > NAME_LIMIT:
        rep.error(name, "ディレクトリ名が kebab-case でないか %d 文字を超えている" % NAME_LIMIT)

    desc = skill["description"]
    if not desc:
        rep.error(where, "description がない。発火判断の材料がなくなる")
    else:
        if len(desc) > DESC_LIMIT:
            rep.error(where, "description が %d 文字。上限 %d 文字" % (len(desc), DESC_LIMIT))
        if "<" in desc or ">" in desc:
            rep.error(where, "description に山括弧が含まれる。仕様で弾かれる")

    web = skill["web_description"]
    if not web:
        rep.error(where, "metadata.web-description がない。"
                         "pack_skill.py が終了コード1で止まり、claude.ai へ配布できない")
    else:
        if len(web) > WEB_DESC_LIMIT:
            rep.error(where, "metadata.web-description が %d 文字。上限 %d 文字"
                      % (len(web), WEB_DESC_LIMIT))
        if "<" in web or ">" in web:
            rep.error(where, "metadata.web-description に山括弧が含まれる")

    if body_lines > SKILL_BODY_LIMIT:
        rep.warn(where, "SKILL.md が %d 行。%d 行を超えたら references/ に分割すること"
                 % (body_lines, SKILL_BODY_LIMIT))

    return skill


# --------------------------------------------------------------------------
# 発火競合の抽出
# --------------------------------------------------------------------------

def normalize_trigger(phrase):
    return re.sub(r"[。、\s]", "", phrase).lower()


def extract_signals(description):
    triggers = set()
    for m in TRIGGER_RE.finditer(description):
        norm = normalize_trigger(m.group(1))
        # 「スキル」のような定型句は全 description に出るので、トリガーとして数えない
        if len(norm) >= TRIGGER_MIN_NORM_LEN and norm not in STOPWORDS:
            triggers.add(norm)
    body = TRIGGER_RE.sub(" ", description)  # トリガー文言を除いた残りから特徴語を取る
    terms = set()
    for m in TERM_RE.finditer(body):
        t = m.group(0)
        if t in STOPWORDS:
            continue
        terms.add(t.lower())
    return triggers, terms


def trigger_overlap(a, b):
    shared = []
    for x in a:
        for y in b:
            if x == y:
                shared.append(x)
            elif len(x) >= TRIGGER_MIN_LEN and len(y) >= TRIGGER_MIN_LEN and (x in y or y in x):
                shared.append(x if len(x) <= len(y) else y)
    return sorted(set(shared))


def find_conflicts(skills, rep):
    signals = {}
    for s in skills:
        signals[s["name"]] = extract_signals(s["description"])

    candidates = []
    for a, b in itertools.combinations(skills, 2):
        ta, ma = signals[a["name"]]
        tb, mb = signals[b["name"]]
        shared_triggers = trigger_overlap(ta, tb)
        shared_terms = sorted(ma & mb)
        union = len(ma | mb)
        jaccard = (len(ma & mb) / union) if union else 0.0
        if not shared_triggers and jaccard < JACCARD_THRESHOLD:
            continue

        a_names_b = b["name"] in a["description"]
        b_names_a = a["name"] in b["description"]
        cand = {
            "pair": [a["name"], b["name"]],
            "shared_triggers": shared_triggers,
            "shared_terms": shared_terms[:15],
            "jaccard": round(jaccard, 3),
            "declares_boundary": {a["name"]: a_names_b, b["name"]: b_names_a},
            "score": round(2.0 * len(shared_triggers) + 10.0 * jaccard, 2),
        }
        candidates.append(cand)

        if cand["score"] >= WARN_SCORE and not (a_names_b or b_names_a):
            reason = ("同一のトリガー文言 %s を持つ" % shared_triggers) if shared_triggers \
                else ("description の特徴語が %.0f%% 重なる" % (jaccard * 100))
            rep.warn("%s / %s" % (a["name"], b["name"]),
                     "%s が、どちらの description にも相手の名前が出てこない。"
                     "棲み分けを名指しで書くか、対象範囲を狭めること" % reason)

    candidates.sort(key=lambda c: -c["score"])
    return candidates


# --------------------------------------------------------------------------
# 個別検証の集約
# --------------------------------------------------------------------------

def run_validator(validator, skills_dir, names):
    results = {}
    for name in names:
        target = os.path.join(skills_dir, name)
        try:
            proc = subprocess.run([sys.executable, validator, target],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            results[name] = {"exit_code": None, "error": str(e)}
            continue
        out = (proc.stdout or "") + (proc.stderr or "")
        results[name] = {
            "exit_code": proc.returncode,
            "errors": len(re.findall(r"^ERROR\b", out, re.M)),
            "warns": len(re.findall(r"^WARN\b", out, re.M)),
            "output": out.strip().splitlines()[-6:],
        }
    return results


# --------------------------------------------------------------------------
# README 突合
# --------------------------------------------------------------------------

def check_readme(readme_path, skills, rep):
    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as e:
        rep.error(readme_path, "読み込めない (%s)" % e)
        return None

    listed = {}
    for raw in lines:
        m = README_ROW_RE.match(raw.strip())
        if not m:
            continue
        name = m.group(1)
        lm = README_LINES_RE.search("|" + m.group(2))
        listed[name] = int(lm.group(1)) if lm else None

    actual = {s["name"]: s["lines"] for s in skills}
    missing_in_readme = sorted(set(actual) - set(listed))
    missing_in_repo = sorted(set(listed) - set(actual))
    line_mismatch = []
    for name, n in listed.items():
        if n is None or name not in actual:
            continue
        if actual[name] != n:
            line_mismatch.append({"skill": name, "readme": n, "actual": actual[name]})

    for name in missing_in_readme:
        rep.warn(readme_path, "収録スキル表に `%s` の行がない。実体はあるのに一覧から漏れている" % name)
    for name in missing_in_repo:
        rep.error(readme_path, "収録スキル表の `%s` に対応するディレクトリがない" % name)
    for m in line_mismatch:
        rep.warn(readme_path, "`%s` の行数が表では %d 行、実体は %d 行"
                 % (m["skill"], m["readme"], m["actual"]))

    return {
        "listed": len(listed),
        "missing_in_readme": missing_in_readme,
        "missing_in_repo": missing_in_repo,
        "line_mismatch": line_mismatch,
    }


# --------------------------------------------------------------------------

def dump(report, rep):
    for e in rep.errors:
        print("ERROR  %s: %s" % (e["where"], e["message"]))
    for w in rep.warns:
        print("WARN   %s: %s" % (w["where"], w["message"]))
    print()

    print("スキル %d 件" % len(report["skills"]))
    missing_web = [s["name"] for s in report["skills"] if not s["web_description"]]
    if missing_web:
        print("  web-description 欠落: %s" % ", ".join(missing_web))
    if report["conflicts"]:
        print("競合候補 %d 組（A2 で1組ずつ判断すること）" % len(report["conflicts"]))
        for c in report["conflicts"][:10]:
            declared = [k for k, v in c["declares_boundary"].items() if v]
            print("  %-24s %-24s score=%.2f trig=%d 棲み分け宣言=%s"
                  % (c["pair"][0], c["pair"][1], c["score"], len(c["shared_triggers"]),
                     ",".join(declared) if declared else "なし"))
    else:
        print("競合候補 0 組")
    print("ERROR %d 件 / WARN %d 件" % (len(rep.errors), len(rep.warns)))
    if rep.errors:
        print("不合格。ERROR を残したままコミットしないこと。")
    else:
        print("合格。ただし競合候補の採否は A2 で判断すること。")


def main(argv):
    ap = argparse.ArgumentParser(description="スキル置き場の横断検査")
    ap.add_argument("skills_dir", help="skills/ のパス")
    ap.add_argument("-o", "--output", help="検査結果の JSON 出力先")
    ap.add_argument("--validator", help="validate_skill.py のパス。渡すと各スキルに対して実行する")
    ap.add_argument("--readme", help="README.md のパス。渡すと収録スキル表と突き合わせる")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.skills_dir):
        print("ERROR  %s: ディレクトリがない" % args.skills_dir)
        return 2
    if args.validator and not os.path.isfile(args.validator):
        print("ERROR  %s: validate_skill.py が見つからない" % args.validator)
        return 2

    names = sorted(d for d in os.listdir(args.skills_dir)
                   if os.path.isdir(os.path.join(args.skills_dir, d)) and not d.startswith("."))
    if not names:
        print("ERROR  %s: スキルが1件もない" % args.skills_dir)
        return 2

    rep = Report()
    skills = [s for s in (load_skill(args.skills_dir, n, rep) for n in names) if s]

    report = {
        "skills_dir": os.path.abspath(args.skills_dir),
        "skills": skills,
        "conflicts": find_conflicts(skills, rep),
        "validation": run_validator(args.validator, args.skills_dir,
                                    [s["name"] for s in skills]) if args.validator else None,
        "readme": check_readme(args.readme, skills, rep) if args.readme else None,
    }
    if report["validation"]:
        for name, r in report["validation"].items():
            if r.get("exit_code") not in (0, None):
                rep.error(name, "validate_skill.py が終了コード %s（ERROR %s 件）"
                          % (r["exit_code"], r.get("errors", "?")))
            elif r.get("exit_code") is None:
                rep.warn(name, "validate_skill.py を実行できなかった (%s)" % r.get("error"))

    report["errors"] = rep.errors
    report["warns"] = rep.warns
    dump(report, rep)

    if args.output:
        outdir = os.path.dirname(os.path.abspath(args.output))
        if outdir and not os.path.isdir(outdir):
            os.makedirs(outdir)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print("→ %s" % args.output)

    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
