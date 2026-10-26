"""local/ の規約資料からルール番号の索引を作り、番号から資料の場所を引く。

使い方:
    python rule_index.py build [--local <local ディレクトリ>]
    python rule_index.py find <ルール番号> [<ルール番号> ...] [--local <local ディレクトリ>]

build:
    local/ 配下の PDF・.txt・.md を走査し、AUTOSAR（A5-1-1 / M0-1-9 の形）と CERT C++（EXP34-CPP の形）の
    ルール番号が出てくる場所を local/index.tsv に書く。PDF はページ番号、テキストは行番号で記録する。
    番号の直後に (required / advisory / document) が続く箇所を「定義」とみなし、分類も記録する。
    索引は資料からの派生物なので local/ の外へ書かない（git 管理外のまま）。
find:
    index.tsv から番号を引き、定義の箇所を先に、言及の箇所を後に並べて表示する。
    表示するのは場所だけで条文は出さない。条文は表示された場所を開いて読む。

--local を省くと、このスクリプトの1つ上のディレクトリにある local/ を使う。

終了コード:
    0  成功（find は全番号が見つかった）
    1  find で見つからない番号があった / build で資料が1件も無い
    2  引数の不備、local/ が無い、index.tsv が無い（先に build）、PDF があるのに pypdf が無い
依存: PDF を読むときだけ pypdf（pip install pypdf）。テキスト資料だけなら標準ライブラリのみ。
"""
import argparse
import csv
import re
import sys
from pathlib import Path

RULE_RE = re.compile(r"\b(?:Rule\s+)?([AM]\d{1,2}-\d{1,2}-\d{1,2}|[A-Z]{3}\d{2}-CPP)\b")
CLASS_RE = re.compile(r"\s*\(\s*(required|advisory|document)", re.I)
TEXT_SUFFIXES = {".txt", ".md"}
INDEX_NAME = "index.tsv"


def standard_of(rule):
    return "CERT C++" if rule.endswith("-CPP") else "AUTOSAR C++14"


def pages_of(path):
    """(場所, 本文) を順に返す。PDF はページ、テキストは行。"""
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            print("PDF を読むには pypdf が要ります: pip install pypdf", file=sys.stderr)
            sys.exit(2)
        for no, page in enumerate(PdfReader(str(path)).pages, 1):
            yield "p.%d" % no, page.extract_text() or ""
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        for no, line in enumerate(text.splitlines(), 1):
            yield "l.%d" % no, line


def classify(text, end):
    m = CLASS_RE.match(text, end)
    return m.group(1).lower() if m else ""


def build(local):
    rows = []
    sources = [p for p in sorted(local.rglob("*"))
               if p.is_file() and p.name != INDEX_NAME and (p.suffix.lower() == ".pdf" or p.suffix.lower() in TEXT_SUFFIXES)]
    for src in sources:
        for where, text in pages_of(src):
            seen = set()
            for m in RULE_RE.finditer(text):
                rule, cls = m.group(1), classify(text, m.end())
                key = (rule, cls)
                if key in seen:
                    continue
                seen.add(key)
                rows.append((rule, standard_of(rule), "定義" if cls else "言及", cls,
                             src.relative_to(local).as_posix(), where))
    if not sources:
        print("資料がありません: %s（autosar/ cert/ inhouse/ に PDF か .txt/.md を置く）" % local)
        return 1
    out = local / INDEX_NAME
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["rule", "standard", "kind", "class", "file", "where"])
        w.writerows(rows)
    rules = {r[0] for r in rows}
    defined = {r[0] for r in rows if r[2] == "定義"}
    print("資料 %d 件 / 番号 %d 種（定義が見つかったもの %d）→ %s" % (len(sources), len(rules), len(defined), out))
    return 0


def find(local, wanted):
    index = local / INDEX_NAME
    if not index.is_file():
        print("索引がありません。先に build を実行してください: %s" % index, file=sys.stderr)
        return 2
    with open(index, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    missing = 0
    for rule in wanted:
        rule = rule.strip().upper()
        hits = sorted((r for r in rows if r["rule"].upper() == rule), key=lambda r: r["kind"] != "定義")
        if not hits:
            print("NOTFOUND  %s（版の違いか、資料に無い番号）" % rule)
            missing += 1
            continue
        for r in hits:
            print("%s  %s  %s%s  local/%s %s" % (rule, r["standard"], r["kind"],
                                               "(%s)" % r["class"] if r["class"] else "", r["file"], r["where"]))
    return 1 if missing else 0


def main():
    parser = argparse.ArgumentParser(description="規約資料のルール番号索引")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--local")
    f = sub.add_parser("find")
    f.add_argument("rules", nargs="+")
    f.add_argument("--local")
    args = parser.parse_args()
    local = Path(args.local) if args.local else Path(__file__).resolve().parents[1] / "local"
    if not local.is_dir():
        print("local/ がありません: %s" % local, file=sys.stderr)
        sys.exit(2)
    sys.exit(build(local) if args.cmd == "build" else find(local, args.rules))


if __name__ == "__main__":
    main()
