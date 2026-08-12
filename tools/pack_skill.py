#!/usr/bin/env python3
"""スキルディレクトリを claude.ai（WEB版）へアップロードできる zip に固める。

claude.ai は zip のルート直下に `<skill-name>/` が来ることを要求する。
また description の上限が 200 文字と、Agent Skills 仕様（1024 文字）より厳しい。
本リポジトリの description は CLI 系での発火精度を優先して長く書いてあるため、
zip に入れる SKILL.md だけ frontmatter の `metadata.web-description` に差し替える。
実体（skills/ 配下）は一切書き換えない。

使い方:
    python tools/pack_skill.py --all
    python tools/pack_skill.py skills/<name> [skills/<name> ...]
    python tools/pack_skill.py --all -o build

終了コード:
    0  成功
    1  検証エラー（web-description が無い / 200 文字超過 など）
    2  引数の指定ミス

依存は標準ライブラリのみ。特定のディレクトリ配置を前提にしない。
"""

import argparse
import re
import sys
import zipfile
from pathlib import Path

# claude.ai 側の description 上限。仕様の 1024 文字ではなくこちらに合わせる。
WEB_DESCRIPTION_MAX_CHARS = 200

# zip に含めない。実行環境の残骸であってスキルの一部ではない。
EXCLUDE_NAMES = {"__pycache__", ".DS_Store", ".git"}
EXCLUDE_SUFFIXES = {".pyc"}

TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")
NESTED_KEY = re.compile(r"^\s+([A-Za-z_][\w-]*):\s*(.*)$")


class SkillError(Exception):
    """パッケージを中止すべき不備。"""


def split_frontmatter(text):
    """SKILL.md を (frontmatter 行, 本文) に分ける。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError("frontmatter が見つからない（1 行目が `---` でない）")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise SkillError("frontmatter の終端 `---` が見つからない")
    return lines[1:end], lines[end + 1:]


def split_blocks(fm_lines):
    """frontmatter をトップレベルキーごとのブロックに割る。

    戻り値は [(key, [そのキーに属する行...]), ...]。
    折り返された値やネストしたブロックは、そのキーの行に含めたまま持つ。
    """
    blocks = []
    for line in fm_lines:
        m = TOP_KEY.match(line)
        if m:
            blocks.append((m.group(1), [line]))
        elif blocks:
            blocks[-1][1].append(line)
        elif line.strip():
            raise SkillError(f"frontmatter の先頭が `key: value` 形式でない: {line!r}")
    return blocks


def extract_web_description(metadata_lines):
    """metadata ブロックから web-description の値を取り出す。

    戻り値は (値 or None, web-description 行を除いた metadata ブロック)。
    """
    value = None
    kept = []
    collecting = False
    for line in metadata_lines:
        m = NESTED_KEY.match(line)
        if m and m.group(1) == "web-description":
            value = m.group(2).strip()
            collecting = True
            continue
        if collecting:
            # 折り返された値の続き（次のキーでもなく、空行でもない行）
            if not m and line.strip():
                value += " " + line.strip()
                continue
            collecting = False
        kept.append(line)
    return value, kept


def build_web_skill_md(text):
    """zip に入れる SKILL.md の中身を組み立てる。"""
    fm_lines, body = split_frontmatter(text)
    blocks = split_blocks(fm_lines)
    keys = [k for k, _ in blocks]

    if "description" not in keys:
        raise SkillError("frontmatter に `description` がない")
    if "metadata" not in keys:
        raise SkillError(
            "frontmatter に `metadata.web-description` がない。"
            f"claude.ai 用に {WEB_DESCRIPTION_MAX_CHARS} 文字以内の description を書くこと"
        )

    web_desc = None
    out_blocks = []
    for key, lines in blocks:
        if key == "metadata":
            web_desc, kept = extract_web_description(lines)
            # web-description しか無かった metadata は丸ごと落とす
            if any(NESTED_KEY.match(l) for l in kept):
                out_blocks.append((key, kept))
            continue
        out_blocks.append((key, lines))

    if web_desc is None:
        raise SkillError(
            "frontmatter に `metadata.web-description` がない。"
            f"claude.ai 用に {WEB_DESCRIPTION_MAX_CHARS} 文字以内の description を書くこと"
        )
    if len(web_desc) > WEB_DESCRIPTION_MAX_CHARS:
        raise SkillError(
            f"metadata.web-description が {len(web_desc)} 文字。"
            f"上限は {WEB_DESCRIPTION_MAX_CHARS} 文字"
        )
    if "<" in web_desc or ">" in web_desc:
        raise SkillError("metadata.web-description に山括弧（< >）を含めてはいけない")

    rebuilt = []
    for key, lines in out_blocks:
        if key == "description":
            rebuilt.append(f"description: {web_desc}")
        else:
            rebuilt.extend(lines)

    return "\n".join(["---"] + rebuilt + ["---"] + body) + "\n"


def collect_files(skill_dir):
    """zip に含めるファイルを列挙する。"""
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(skill_dir)
        if any(part in EXCLUDE_NAMES for part in rel.parts):
            continue
        if path.suffix in EXCLUDE_SUFFIXES:
            continue
        yield path, rel


def pack(skill_dir, out_dir):
    """スキル1件を zip 化する。戻り値は出力先パス。"""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise SkillError("SKILL.md がない")

    name = skill_dir.name
    web_md = build_web_skill_md(skill_md.read_text(encoding="utf-8"))

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.zip"
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # claude.ai はルート直下の <skill-name>/ を見る。ネストさせない。
        zf.writestr(f"{name}/SKILL.md", web_md)
        for path, rel in collect_files(skill_dir):
            if rel.as_posix() == "SKILL.md":
                continue
            zf.write(path, f"{name}/{rel.as_posix()}")
    return out_path


def find_skills_root(start):
    """--all 用に skills/ ディレクトリを探す。

    カレントからの相対でも、このスクリプトの位置からでも見つかるようにする。
    """
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent):
        candidate = base / "skills"
        if candidate.is_dir():
            return candidate
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="スキルを claude.ai 用の zip に固める",
        epilog="終了コード: 0 成功 / 1 検証エラー / 2 引数エラー",
    )
    parser.add_argument("skill_dirs", nargs="*", type=Path, help="スキルディレクトリ")
    parser.add_argument("--all", action="store_true", help="skills/ 配下をすべて対象にする")
    parser.add_argument("-o", "--out-dir", type=Path, default=Path("dist"), help="出力先（既定: dist）")
    args = parser.parse_args(argv)

    if args.all and args.skill_dirs:
        parser.error("--all とスキルディレクトリは同時に指定できない")
    if not args.all and not args.skill_dirs:
        parser.error("スキルディレクトリか --all を指定すること")

    if args.all:
        root = find_skills_root(Path.cwd())
        if root is None:
            print("ERROR  skills/ ディレクトリが見つからない", file=sys.stderr)
            return 2
        targets = sorted(d for d in root.iterdir() if (d / "SKILL.md").is_file())
        if not targets:
            print("ERROR  skills/ 配下にスキルが1件もない", file=sys.stderr)
            return 2
    else:
        targets = args.skill_dirs

    failed = 0
    for skill_dir in targets:
        if not skill_dir.is_dir():
            print(f"ERROR  {skill_dir}: ディレクトリが存在しない")
            failed += 1
            continue
        try:
            out_path = pack(skill_dir, args.out_dir)
        except SkillError as e:
            print(f"ERROR  {skill_dir.name}: {e}")
            failed += 1
        else:
            print(f"OK     {skill_dir.name} -> {out_path}")

    print()
    print(f"成功 {len(targets) - failed} 件 / 失敗 {failed} 件")
    if failed:
        print("不合格。上の ERROR を解消すること。")
        return 1
    print(f"{args.out_dir} の zip を claude.ai の Customize > Skills からアップロードする。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
