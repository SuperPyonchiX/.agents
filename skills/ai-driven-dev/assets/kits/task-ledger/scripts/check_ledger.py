#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ai-driven-dev の開発台帳（DEV_TASKS.md）に未クローズのタスクや証拠の欠けが無いかを検査する。

手順0（再開判定）と手順3（仕上げ）で実行する。

    python check_ledger.py DEV_TASKS.md [--repo リポジトリのパス] [--resume] [--no-commit]

--no-commit を付けると、完了タスクのコミット列が空か「なし」でも ERROR にしない。
変更ファイル列がある台帳では、完了タスクの変更ファイルが空なら ERROR にする。

--resume を付けると未着手・進行中を ERROR にしない（再開時・途中で終えるとき用）。

終了コード:
    0  全タスクがクローズ済み（完了 / 保留 / 中止）で、不備なし
    1  未着手・進行中が残っている、または証拠・コミットの欠けなどの不備がある
    2  引数の誤り、ファイルが読めない、タスク表が見つからない、git を起動できない、
       --repo が git リポジトリでない

依存は標準ライブラリのみ。
"""

import argparse
import re
import subprocess
import sys

COL_ID = {"id", "no", "no."}
COL_STATUS = {"状態", "ステータス", "status"}
COL_EVIDENCE = {"証拠", "evidence"}
COL_COMMIT = {"コミット", "commit"}
COL_FILES = {"変更ファイル", "files"}
COL_KIND = {"種類", "kind"}
COL_COMMAND = {"コマンド", "command"}

STATUS_ALIASES = {
    "未着手": "未着手", "todo": "未着手",
    "進行中": "進行中", "doing": "進行中", "wip": "進行中",
    "完了": "完了", "done": "完了",
    "保留": "保留", "hold": "保留",
    "中止": "中止", "dropped": "中止",
}
ORDER = ["未着手", "進行中", "完了", "保留", "中止"]
OPEN = {"未着手", "進行中"}
SEP_RE = re.compile(r":?-{2,}:?")
HASH_RE = re.compile(r"[0-9a-fA-F]{7,40}")
CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
FENCE_RE = re.compile(r"^(```|~~~)")
EMPTY = {"", "-", "—", "なし"}

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def is_placeholder(text):
    return "〔" in text


def split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip() for c in CELL_SPLIT_RE.split(s)]


def parse_hashes(cell):
    """セル全体がハッシュの並び（空白・カンマ区切り）のときだけハッシュを返す。"""
    parts = [x for x in re.split(r"[\s,、]+", cell.strip("`").strip()) if x]
    if parts and all(HASH_RE.fullmatch(x.strip("`")) for x in parts):
        return [x.strip("`") for x in parts]
    return []


def read_tables(lines):
    """Markdown の表を (見出し行番号, 見出し, [(行番号, セル)]) のリストで返す。"""
    tables = []
    current = None
    in_fence = False
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if FENCE_RE.match(s):
            in_fence = not in_fence
            current = None
            continue
        if in_fence or not s.startswith("|"):
            current = None
            continue
        cells = split_row(s)
        if all(SEP_RE.fullmatch(c) for c in cells if c) and any(cells):
            continue
        if current is None:
            current = (n, [c.lower() for c in cells], [])
            tables.append(current)
        else:
            current[2].append((n, cells))
    return tables


def find_col(header, names):
    for i, c in enumerate(header):
        if c in names:
            return i
    return None


def git(repo, *args):
    try:
        return subprocess.run(["git", "-C", repo] + list(args), capture_output=True)
    except OSError as e:
        raise RuntimeError("git を起動できない (%s)" % e)


def commit_exists(repo, sha):
    return git(repo, "cat-file", "-e", sha + "^{commit}").returncode == 0


def check(path, repo, resume=False, no_commit=False):
    errors, warns = [], []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except OSError as e:
        return None, ["読み込めない (%s)" % e], [], {}

    tables = read_tables(lines)
    task_table = None
    cmd_table = None
    for t in tables:
        h = t[1]
        if task_table is None and find_col(h, COL_ID) is not None and find_col(h, COL_STATUS) is not None:
            task_table = t
        elif cmd_table is None and find_col(h, COL_KIND) is not None and find_col(h, COL_COMMAND) is not None:
            cmd_table = t
    if task_table is None:
        return None, ["ID 列と状態列を持つタスク表が見つからない。"
                      "assets/templates/DEV_TASKS.md の形式を確認すること"], [], {}

    hn, header, rows = task_table
    c_id, c_st = find_col(header, COL_ID), find_col(header, COL_STATUS)
    c_ev, c_cm = find_col(header, COL_EVIDENCE), find_col(header, COL_COMMIT)
    c_fl = find_col(header, COL_FILES)
    if c_ev is None:
        errors.append("%s:%d: 証拠列がない" % (path, hn))
    if c_cm is None:
        errors.append("%s:%d: コミット列がない" % (path, hn))

    counts = dict((s, 0) for s in ORDER)
    seen = set()
    for n, cells in rows:
        where = "%s:%d" % (path, n)
        if len(cells) != len(header):
            errors.append("%s: 列数が見出しと一致しない（%d 列、見出しは %d 列）"
                          % (where, len(cells), len(header)))
            continue
        tid = cells[c_id]
        if not tid or is_placeholder(tid):
            continue
        if tid in seen:
            errors.append("%s: タスクIDが重複している: %s" % (where, tid))
        seen.add(tid)
        raw = cells[c_st]
        status = STATUS_ALIASES.get(raw.strip().lower())
        if status is None:
            errors.append("%s: %s の状態が不正: '%s'（%s のどれか）" % (where, tid, raw, " / ".join(ORDER)))
            continue
        counts[status] += 1
        evidence = cells[c_ev] if c_ev is not None else ""
        commit = cells[c_cm] if c_cm is not None else ""
        if status in OPEN:
            if resume:
                continue
            errors.append("%s: %s が %s のまま残っている" % (where, tid, status))
        elif status == "完了":
            if evidence in EMPTY or is_placeholder(evidence):
                errors.append("%s: %s は完了だが証拠が空。実行した検証の結果を書くこと" % (where, tid))
            if c_fl is not None and (cells[c_fl] in EMPTY or is_placeholder(cells[c_fl])):
                errors.append("%s: %s は完了だが変更ファイルが空。実際に変えたファイルを書くこと" % (where, tid))
            hashes = parse_hashes(commit)
            if not hashes and no_commit and commit in EMPTY:
                pass
            elif not hashes:
                errors.append("%s: %s は完了だがコミットが無い（短いハッシュを書くこと）: '%s'"
                              % (where, tid, commit))
            elif repo:
                for sha in hashes:
                    if not commit_exists(repo, sha):
                        errors.append("%s: %s のコミット %s がリポジトリに無い" % (where, tid, sha))
        else:
            if evidence in EMPTY or is_placeholder(evidence):
                errors.append("%s: %s は%sだが理由が空。証拠列にユーザーの了承と理由を書くこと"
                              % (where, tid, status))

    if sum(counts.values()) == 0:
        errors.append("%s: タスクが1件も登録されていない" % path)
    if counts["進行中"] > 1:
        warns.append("%s: 進行中が %d 件ある。同時に進めるのは1件まで" % (path, counts["進行中"]))

    if cmd_table is None:
        warns.append("%s: 検証コマンドの表が見つからない" % path)
    else:
        c_cmd = find_col(cmd_table[1], COL_COMMAND)
        filled = [c[c_cmd] for _, c in cmd_table[2]
                  if c_cmd < len(c) and c[c_cmd] not in EMPTY and not is_placeholder(c[c_cmd])]
        if not filled:
            warns.append("%s: 検証コマンドが1つも書かれていない" % path)
    return True, errors, warns, counts


def main(argv):
    ap = argparse.ArgumentParser(description="開発台帳の未クローズ・証拠欠けの検査")
    ap.add_argument("ledger", help="DEV_TASKS.md のパス")
    ap.add_argument("--repo", help="完了タスクのコミットが実在するかを確かめるリポジトリ")
    ap.add_argument("--resume", action="store_true", help="未着手・進行中を ERROR にしない")
    ap.add_argument("--no-commit", action="store_true", help="完了タスクにコミットを求めない（コミットしない方式）")
    args = ap.parse_args(argv)

    try:
        if args.repo and git(args.repo, "rev-parse", "--git-dir").returncode != 0:
            print("ERROR  --repo が git リポジトリではない: %s" % args.repo)
            return 2
        ok, errors, warns, counts = check(args.ledger, args.repo, args.resume, args.no_commit)
    except RuntimeError as e:
        print("ERROR  %s" % e)
        return 2
    if ok is None:
        for e in errors:
            print("ERROR  %s" % e)
        return 2

    for e in errors:
        print("ERROR  %s" % e)
    for w in warns:
        print("WARN   %s" % w)
    print()
    print("タスク %d 件（%s）" % (sum(counts.values()),
                               " / ".join("%s %d" % (s, counts[s]) for s in ORDER)))
    print("ERROR %d 件 / WARN %d 件" % (len(errors), len(warns)))
    if errors:
        print("不合格。未クローズや証拠の欠けを残したまま完了として報告しないこと。")
        return 1
    if args.resume and (counts["未着手"] or counts["進行中"]):
        print("合格（再開用の検査）。完了タスクの記録に不備はない。残り %d 件。"
              % (counts["未着手"] + counts["進行中"]))
        return 0
    print("合格。全タスクがクローズ済み。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
