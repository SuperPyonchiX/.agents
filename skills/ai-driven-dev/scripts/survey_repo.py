#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""対象リポジトリの現状を機械的に集める（ai-driven-dev の手順2: 現状診断）。

    python survey_repo.py <対象ディレクトリ> [--json]

言語の内訳（.agents/skills などのスキル置き場は除く）、ビルド・パッケージ定義、テストの有無、CI、lint の設定、エージェント向け文書
（AGENTS.md など）、既存のスキル、git の状態を集め、Markdown（既定）か JSON で標準出力に出す。
ファイルの中身は package.json の scripts と pyproject.toml の [tool.*] の見出し以外は読まない。

終了コード:
    0  集計できた
    2  引数の誤り（ディレクトリでない）

依存は標準ライブラリのみ。
"""

import argparse
import collections
import json
import os
import re
import subprocess
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "out", "target", ".venv", "venv",
             "__pycache__", ".tox", ".mypy_cache", ".pytest_cache", ".next", "bin", "obj", ".idea", ".vs"}
LANG = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java",
    ".kt": "Kotlin", ".cs": "C#", ".c": "C", ".h": "C/C++ ヘッダ", ".cpp": "C++", ".cc": "C++",
    ".hpp": "C++", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".m": "Objective-C",
    ".mq5": "MQL5", ".mqh": "MQL5", ".sh": "Shell", ".ps1": "PowerShell", ".sql": "SQL",
    ".html": "HTML", ".css": "CSS", ".vue": "Vue", ".svelte": "Svelte", ".md": "Markdown",
}
MANIFESTS = ["package.json", "pyproject.toml", "requirements.txt", "setup.py", "Pipfile", "Cargo.toml",
             "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "CMakeLists.txt", "Makefile",
             "Gemfile", "composer.json", "Package.swift", "deno.json"]
LINT_FILES = [".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.cjs", "eslint.config.js",
              "eslint.config.mjs", ".prettierrc", "ruff.toml", ".ruff.toml", ".flake8", "mypy.ini",
              "tsconfig.json", ".clang-tidy", ".clang-format", ".editorconfig", ".golangci.yml",
              "rustfmt.toml", ".rubocop.yml", ".pre-commit-config.yaml"]
AGENT_DOCS = ["AGENTS.md", "CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md", ".cursorrules",
              "HANDOFF.md", "DEV_PLAN.md"]
CI_PATHS = [".github/workflows", ".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile", ".circleci",
            "bitbucket-pipelines.yml"]
TEST_FILE_RE = re.compile(r"(^test_.*\.py$|.*_test\.py$|.*_test\.go$|.*\.(test|spec)\.[jt]sx?$|"
                          r".*Tests?\.(java|kt|cs)$|.*_spec\.rb$|.*_test\.(cpp|cc|c)$|^test_.*\.(cpp|cc|c)$)")
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "testing"}
# スキル置き場は「既存のスキル」で別に数える。開発対象の言語・テストの集計を汚さないよう歩かない
SKILL_BASES = (".agents/skills", ".claude/skills", ".github/skills")


def git(root, *args):
    try:
        r = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def survey(root):
    langs = collections.Counter()
    test_files = []
    test_dirs = set()
    files = 0
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        dirnames[:] = [d for d in dirnames
                       if (d not in SKIP_DIRS and not d.startswith(".") or d in (".github", ".agents", ".claude"))
                       and os.path.normpath(os.path.join(rel_dir, d)).replace(os.sep, "/") not in SKILL_BASES]
        if os.path.basename(dirpath).lower() in TEST_DIRS:
            test_dirs.add(rel_dir.replace(os.sep, "/"))
        for name in filenames:
            files += 1
            ext = os.path.splitext(name)[1].lower()
            if ext in LANG:
                langs[LANG[ext]] += 1
            if TEST_FILE_RE.match(name):
                test_files.append(os.path.normpath(os.path.join(rel_dir, name)).replace(os.sep, "/"))

    def exists(p):
        return os.path.exists(os.path.join(root, p))

    manifests = [m for m in MANIFESTS if exists(m)]
    for name in os.listdir(root):
        if name.endswith((".sln", ".csproj", ".vcxproj")):
            manifests.append(name)

    scripts = {}
    if exists("package.json"):
        try:
            with open(os.path.join(root, "package.json"), encoding="utf-8") as f:
                scripts = dict((k, v) for k, v in (json.load(f).get("scripts") or {}).items()
                               if k in ("test", "lint", "build", "typecheck", "start", "dev", "format"))
        except (OSError, ValueError):
            scripts = {"(読めない)": "package.json の形式を確認すること"}
    py_tools = []
    if exists("pyproject.toml"):
        try:
            with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as f:
                py_tools = sorted(set(re.findall(r"^\[tool\.([A-Za-z0-9_-]+)", f.read(), re.M)))
        except OSError:
            pass

    ci = []
    for p in CI_PATHS:
        full = os.path.join(root, p)
        if os.path.isdir(full):
            ci += [p + "/" + n for n in sorted(os.listdir(full))]
        elif os.path.exists(full):
            ci.append(p)

    skills = []
    for base in SKILL_BASES:
        full = os.path.join(root, base)
        if os.path.isdir(full):
            skills += [base + "/" + n for n in sorted(os.listdir(full))
                       if os.path.isfile(os.path.join(full, n, "SKILL.md"))]

    g = None
    if git(root, "rev-parse", "--git-dir") is not None:
        status = git(root, "status", "--short") or ""
        g = {
            "branch": git(root, "branch", "--show-current"),
            "head": git(root, "rev-parse", "--short", "HEAD"),
            "commits": git(root, "rev-list", "--count", "HEAD"),
            "last_commit": git(root, "log", "-1", "--format=%ci %s"),
            "uncommitted": len([l for l in status.splitlines() if l.strip()]),
            "remotes": (git(root, "remote") or "").split(),
        }

    return {
        "root": os.path.abspath(root),
        "files": files,
        "languages": langs.most_common(8),
        "manifests": manifests,
        "package_scripts": scripts,
        "pyproject_tools": py_tools,
        "tests": {"files": len(test_files), "examples": test_files[:5], "dirs": sorted(test_dirs)[:5]},
        "ci": ci,
        "lint_config": [p for p in LINT_FILES if exists(p)],
        "agent_docs": [p for p in AGENT_DOCS if exists(p)],
        "skills": skills,
        "readme": [n for n in ("README.md", "README.rst", "README.txt", "README") if exists(n)],
        "git": g,
    }


def to_markdown(r):
    def join(xs):
        return "、".join(xs) if xs else "なし"
    lines = ["# 現状診断: %s" % r["root"], "", "| 項目 | 結果 |", "|---|---|"]
    lines.append("| ファイル数 | %d |" % r["files"])
    lines.append("| 言語（ファイル数） | %s |" % join(["%s %d" % (k, v) for k, v in r["languages"]]))
    lines.append("| ビルド・パッケージ定義 | %s |" % join(r["manifests"]))
    if r["package_scripts"]:
        lines.append("| package.json の scripts | %s |" % join(
            ["%s: `%s`" % (k, v.replace("|", "\\|")) for k, v in r["package_scripts"].items()]))
    if r["pyproject_tools"]:
        lines.append("| pyproject.toml の [tool.*] | %s |" % join(r["pyproject_tools"]))
    t = r["tests"]
    lines.append("| テスト | %s |" % ("%d 件（例: %s）" % (t["files"], join(t["examples"])) if t["files"]
                                    else "テストファイルが見つからない"))
    lines.append("| テストのディレクトリ | %s |" % join(t["dirs"]))
    lines.append("| CI | %s |" % join(r["ci"]))
    lines.append("| lint・整形の設定 | %s |" % join(r["lint_config"]))
    lines.append("| エージェント向け文書 | %s |" % join(r["agent_docs"]))
    sk = r["skills"]
    lines.append("| 既存のスキル | %s |" % ("%d 本（%s%s）" % (len(sk), join(sk[:8]), " ほか" if len(sk) > 8 else "")
                                       if sk else "なし"))
    lines.append("| README | %s |" % join(r["readme"]))
    g = r["git"]
    if g:
        lines.append("| git | ブランチ %s / HEAD %s / コミット %s 件 / 未コミット %d 件 / remote %s |"
                     % (g["branch"] or "(detached)", g["head"] or "なし", g["commits"] or "0", g["uncommitted"], join(g["remotes"])))
        lines.append("| 最終コミット | %s |" % (g["last_commit"] or "なし"))
    else:
        lines.append("| git | git リポジトリではない |")
    return "\n".join(lines)


def main(argv):
    ap = argparse.ArgumentParser(description="対象リポジトリの現状診断")
    ap.add_argument("root", help="対象ディレクトリ")
    ap.add_argument("--json", action="store_true", help="JSON で出力する")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.root):
        print("ERROR  ディレクトリではない: %s" % args.root)
        return 2
    r = survey(args.root)
    print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else to_markdown(r))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
