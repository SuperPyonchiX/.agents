#!/usr/bin/env python3
"""スキルディレクトリの仕様適合と構造を機械的に検証する。

使い方:
    python scripts/validate_skill.py <スキルディレクトリ>

終了コード 0 で合格。不合格時は失敗項目を標準出力に列挙して 1 を返す。
WARN のみなら合格（0）だが、内容は表示する。

検査は2系統ある:

1. **仕様適合** — frontmatter の許可キー、name の kebab-case と長さ、
   description の山括弧禁止と長さ。Agent Skill の公式仕様に基づく。
2. **構造** — name とディレクトリ名の一致、metadata.web-description の有無と
   200 文字以内、description の 300 文字目安（超過は WARN）、リンク切れ、
   同梱ファイル（references/ templates/ examples/ assets/）の孤児、行数。
   references/review-checklist.md と AGENTS.md に基づく、この置き場固有の検査。

依存は標準ライブラリのみ。Claude Code 以外の環境（Codex 等）へこのスキルを
そのまま持ち出せるようにするためで、外部パッケージや特定のディレクトリ配置を
前提にしない。

なお Claude Code に skill-creator が入っている場合、その
scripts/quick_validate.py が上記 1 と同じ範囲を見る（あちらは PyYAML を要求
するので、こちらから委譲はしていない）。**仕様が変わったら両方に追随が要る**
ことは意識しておくこと。ルールの出典は各定数のコメントに書いてある。

このスクリプトが見るのは references/review-checklist.md のうち
**機械判定できる項目だけ**である。次のような主観的な項目は対象外で、
目視レビューに残る:

  - description に想定する依頼文言が具体的に列挙されているか
  - 指示が命令形で書かれているか
  - ループに成功条件・上限・諦め条件がそろっているか
  - 並列枝の担当範囲が重複していないか
  - 初めて見るエージェントが推測を挟まずに実行できるか

つまり「合格 = 良いスキル」ではない。合格は、チェックリストを人手で
当てる前に潰せる機械的な不備がゼロ、という意味でしかない。
"""

import re
import sys
from pathlib import Path

# Windows のコンソールは既定が cp932 のことがあり、日本語の指摘が文字化けする。
# 検証結果が読めないと修正できないので、出力を UTF-8 に固定する。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 参照ファイルにこの行数を超えたら目次を求める（file-splitting.md）
TOC_REQUIRED_LINES = 300
# SKILL.md 本文がこの行数に近づいたら分割を検討する（file-splitting.md）
SKILL_MD_MAX_LINES = 500
# description がこの文字数未満なら、発火の手がかりとして短すぎるとみなす
DESCRIPTION_MIN_CHARS = 60
# description がこの文字数を超えたら WARN。全スキル分が毎セッション読み込まれる
# 固定費になるため、300 文字を目安にする（AGENTS.md「SKILL.md の規約」）
DESCRIPTION_GUIDE_CHARS = 300
# claude.ai（WEB版）の description 上限。metadata.web-description はこの長さ以内で必須
# （tools/pack_skill.py と skill-portfolio-audit の audit_skills.py と同じ判定条件）
WEB_DESCRIPTION_MAX_CHARS = 200
# 孤児検査の対象ディレクトリ（再帰的に走査する）。SKILL.md からも references/ からも
# 参照されない同梱ファイルは、読ませる導線がないので置いていないのと変わらない。
ORPHAN_SCAN_DIRS = ("references", "templates", "examples", "assets")

# --- ここから Agent Skill の公式仕様に由来する定数 ---
# frontmatter に置いてよいキー。これ以外があるとスキルの読み込みが弾かれる。
ALLOWED_FRONTMATTER_KEYS = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
    "compatibility",
}
NAME_MAX_CHARS = 64
DESCRIPTION_MAX_CHARS = 1024
COMPATIBILITY_MAX_CHARS = 500
# name は kebab-case（英小文字・数字・ハイフン）のみ
NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")

# スキル内のファイルを指していると断定できるパスだけを拾う。
#
# 裸のファイル名（`state.json`、`progress.md` など）は意図的に対象外にしている。
# スキルの文書では、それが「このスキル内のファイルへの参照」なのか
# 「生成されるスキルが作る成果物の名前」なのかを表記から区別できず、
# 拾うと後者を大量に誤検出するため。誤検出だらけの検証は使われなくなる
# （references/loop-engineering.md の「評価は信頼できる形で」に反する）。
#
# 結果として、参照ファイル同士の同階層リンク（`loop-engineering.md` など）は
# 未検査のまま残る。これは既知の穴。ただし実際に起きた破損は
# すべて references/ 接頭辞つきのリンクであり、そこは完全に覆えている。
SKILL_SUBDIRS = r"(?:references|scripts|assets)"
LINK_PATTERNS = [
    re.compile(r"\[[^\]]*\]\(([^)]+)\)"),                  # markdown リンク
    re.compile(rf"`({SKILL_SUBDIRS}/[^`\n]+)`"),           # バッククォート内の skill 相対パス
]

# パスとして追いかけない外部参照
EXTERNAL = re.compile(r"^(https?:|mailto:|#)")


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
            print("不合格。上の ERROR を解消すること。")
        elif self.warns:
            print("合格（WARN あり）。WARN は判断のうえ対応する。")
        else:
            print("合格。ただし主観項目は references/review-checklist.md で別途確認すること。")
        return 1 if self.errors else 0


def parse_frontmatter(text):
    """--- で囲まれた frontmatter を素朴に行パースする。

    PyYAML に依存しないため、`key: value` の 1 行形式と、`metadata:` 直下の
    1 段ネスト（`  web-description: ...`）だけを解釈する。
    戻り値は (フィールド辞書, エラー文字列 or None)。`metadata` の値はネストした
    キーの辞書になる。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "frontmatter が見つからない（1 行目が `---` でない）"
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}, "frontmatter の終端 `---` が見つからない"

    fields = {}
    key = None
    subkey = None
    for line in lines[1:end]:
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        n = re.match(r"^\s+([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            key = m.group(1)
            subkey = None
            fields[key] = {} if key == "metadata" else m.group(2).strip()
        elif n and key == "metadata":
            subkey = n.group(1)
            fields[key][subkey] = n.group(2).strip()
        elif key and line.strip():
            # 折り返された値の続き
            if key == "metadata":
                if subkey:
                    fields[key][subkey] += " " + line.strip()
            else:
                fields[key] += " " + line.strip()
    return fields, None


def extract_paths(text):
    """本文からスキルルート相対のパス候補を抽出する。"""
    found = set()
    for pat in LINK_PATTERNS:
        for m in pat.finditer(text):
            found.add(m.group(1))

    out = set()
    for p in found:
        p = p.strip()
        if not p or EXTERNAL.match(p):
            continue
        # テンプレートのプレースホルダは実在しなくてよい
        if "<" in p or ">" in p or "*" in p:
            continue
        out.add(p)
    return out


def resolve(skill_dir, source_file, path):
    """パスをスキルルート基準・ファイル基準の順に解決する。

    参照ファイル同士は同階層で書かれ、スキルルート配下の references/ や
    assets/ はルート基準で書かれる。どちらかで実在すれば良しとする。
    """
    candidates = [skill_dir / path, source_file.parent / path]
    return any(c.exists() for c in candidates)


def check_frontmatter(skill_dir, skill_md_text, rep):
    fields, err = parse_frontmatter(skill_md_text)
    if err:
        rep.error("SKILL.md", err)
        return

    # --- 仕様適合 ---
    unexpected = set(fields) - ALLOWED_FRONTMATTER_KEYS
    if unexpected:
        rep.error(
            "SKILL.md",
            f"frontmatter に未知のキーがある: {', '.join(sorted(unexpected))}。"
            f"置いてよいのは {', '.join(sorted(ALLOWED_FRONTMATTER_KEYS))} のみ",
        )

    name = fields.get("name")
    if not name:
        rep.error("SKILL.md", "frontmatter に `name` がない")
    else:
        if not NAME_PATTERN.match(name):
            rep.error(
                "SKILL.md",
                f"`name: {name}` は kebab-case（英小文字・数字・ハイフン）にすること",
            )
        elif name.startswith("-") or name.endswith("-") or "--" in name:
            rep.error(
                "SKILL.md",
                f"`name: {name}` はハイフンで始まる/終わる、または連続ハイフンを含んでいる",
            )
        if len(name) > NAME_MAX_CHARS:
            rep.error(
                "SKILL.md",
                f"name が {len(name)} 文字。上限は {NAME_MAX_CHARS} 文字",
            )
        # --- 構造（このスキル固有の規約）---
        if name != skill_dir.name:
            rep.error(
                "SKILL.md",
                f"`name: {name}` がディレクトリ名 `{skill_dir.name}` と一致しない",
            )

    desc = fields.get("description")
    if not desc:
        rep.error("SKILL.md", "frontmatter に `description` がない")
    else:
        # テンプレートの穴埋めを忘れると、ここで確実に捕まる
        if "<" in desc or ">" in desc:
            rep.error(
                "SKILL.md",
                "description に山括弧（< >）を含めてはいけない。"
                "テンプレートのプレースホルダを埋め残していないか確認すること",
            )
        if len(desc) > DESCRIPTION_MAX_CHARS:
            rep.error(
                "SKILL.md",
                f"description が {len(desc)} 文字。上限は {DESCRIPTION_MAX_CHARS} 文字",
            )
        elif len(desc) < DESCRIPTION_MIN_CHARS:
            rep.warn(
                "SKILL.md",
                f"description が {len(desc)} 文字と短い。"
                "「何をするか」と「いつ使うか」の両方が書かれているか確認すること",
            )
        elif len(desc) > DESCRIPTION_GUIDE_CHARS:
            rep.warn(
                "SKILL.md",
                f"description が {len(desc)} 文字。目安は {DESCRIPTION_GUIDE_CHARS} 文字。"
                "毎セッション読み込まれる固定費になるので、定型句と不要な名指しを削ること",
            )

    # --- claude.ai 配布用の短縮 description（このリポジトリ固有の規約）---
    meta = fields.get("metadata")
    web = meta.get("web-description") if isinstance(meta, dict) else None
    if not web:
        rep.error(
            "SKILL.md",
            "frontmatter に `metadata.web-description` がない。"
            f"claude.ai 用に {WEB_DESCRIPTION_MAX_CHARS} 文字以内の短縮版を置くこと"
            "（無いと pack_skill.py が終了コード 1 で止まる）",
        )
    else:
        if len(web) > WEB_DESCRIPTION_MAX_CHARS:
            rep.error(
                "SKILL.md",
                f"metadata.web-description が {len(web)} 文字。"
                f"上限は {WEB_DESCRIPTION_MAX_CHARS} 文字",
            )
        if "<" in web or ">" in web:
            rep.error(
                "SKILL.md",
                "metadata.web-description に山括弧（< >）を含めてはいけない",
            )

    compat = fields.get("compatibility")
    if compat and len(compat) > COMPATIBILITY_MAX_CHARS:
        rep.error(
            "SKILL.md",
            f"compatibility が {len(compat)} 文字。上限は {COMPATIBILITY_MAX_CHARS} 文字",
        )


def check_links(skill_dir, md_files, rep):
    for f in md_files:
        text = f.read_text(encoding="utf-8")
        rel = f.relative_to(skill_dir).as_posix()
        for path in sorted(extract_paths(text)):
            if not resolve(skill_dir, f, path):
                rep.error(rel, f"参照先が存在しない: {path}")


def check_orphans(skill_dir, all_text, rep):
    for dir_name in ORPHAN_SCAN_DIRS:
        target = skill_dir / dir_name
        if not target.is_dir():
            continue
        for f in sorted(target.rglob("*")):
            if not f.is_file() or f.name.startswith("."):
                continue
            # 同名ファイルが別ディレクトリにある場合の取り違えを避けるため、
            # ファイル名ではなく skill ディレクトリからの相対パスで照合する。
            rel = f.relative_to(skill_dir).as_posix()
            if rel not in all_text:
                rep.warn(
                    rel,
                    "SKILL.md からも参照ファイルからも一度も参照されていない。"
                    "読むタイミングを SKILL.md に書くか、不要なら削除すること",
                )


def check_lengths(skill_dir, rep):
    skill_md = skill_dir / "SKILL.md"
    n = len(skill_md.read_text(encoding="utf-8").splitlines())
    if n > SKILL_MD_MAX_LINES:
        rep.warn(
            "SKILL.md",
            f"{n} 行。{SKILL_MD_MAX_LINES} 行を超えたので "
            "references/ への分割を検討すること",
        )

    for f in sorted((skill_dir / "references").glob("*.md")) if (skill_dir / "references").is_dir() else []:
        lines = f.read_text(encoding="utf-8").splitlines()
        if len(lines) > TOC_REQUIRED_LINES:
            # 冒頭 30 行に見出しリンクの並びがあれば目次とみなす
            head = "\n".join(lines[:30])
            if not re.search(r"^\s*[-*]\s*\[.+\]\(#", head, re.M):
                rep.warn(
                    f"references/{f.name}",
                    f"{len(lines)} 行あるが冒頭に目次がない",
                )


def check_scripts_documented(skill_dir, all_text, rep):
    script_dir = skill_dir / "scripts"
    if not script_dir.is_dir():
        return
    for f in sorted(script_dir.iterdir()):
        if not f.is_file() or f.name.startswith("_"):
            continue
        if f.name not in all_text:
            rep.warn(
                f"scripts/{f.name}",
                "SKILL.md にも参照ファイルにも使い方が書かれていない。"
                "呼び出し方と終了コードの意味を書くこと",
            )


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2

    skill_dir = Path(argv[1]).resolve()
    if not skill_dir.is_dir():
        print(f"ERROR  {skill_dir} はディレクトリではない")
        return 1

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        print(f"ERROR  {skill_dir.name}: SKILL.md が存在しない")
        return 1

    rep = Report()
    skill_md_text = skill_md.read_text(encoding="utf-8")

    md_files = [skill_md]
    ref_dir = skill_dir / "references"
    if ref_dir.is_dir():
        md_files += sorted(ref_dir.glob("*.md"))
    all_text = "\n".join(f.read_text(encoding="utf-8") for f in md_files)

    print(f"検証対象: {skill_dir}")
    print()

    check_frontmatter(skill_dir, skill_md_text, rep)
    check_links(skill_dir, md_files, rep)
    check_orphans(skill_dir, all_text, rep)
    check_lengths(skill_dir, rep)
    check_scripts_documented(skill_dir, all_text, rep)

    return rep.dump()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
