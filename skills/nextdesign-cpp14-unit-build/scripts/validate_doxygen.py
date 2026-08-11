#!/usr/bin/env python3
"""ヘッダの関数宣言と Doxygen コメントの整合を機械的に検査する。

使い方:
    python scripts/validate_doxygen.py <ヘッダファイル or ディレクトリ> [...] [--quiet]

終了コード:
    0  合格（ERROR 0 件。WARN のみなら 0）
    1  ERROR あり
    2  引数誤り

検査するのは次の3点だけ。P1 のゲートで使う。

  - 全関数宣言に Doxygen コメントと @brief があること
  - 引数の数だけ @param があり、名前が一致していること
  - 戻り値型が void 以外なら @return または @retval があること

@pre / @post / @note は**検査しない**（有無を機械判定しても中身の妥当性は測れない）。
これらは references/function-design.md に従って人の目で確認する。

C++ の完全なパーサではない。テンプレートの特殊化、関数ポインタを返す宣言、
マクロで組み立てた宣言は正しく読めないことがある。読めなかった行は
--quiet を外すと SKIP として表示されるので、そこは目視で確認すること。

依存は標準ライブラリのみ。
"""

import argparse
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADER_SUFFIXES = {".h", ".hpp", ".hh", ".hxx"}

# 宣言の先頭から取り除く修飾子
LEADING_KEYWORDS = {
    "virtual", "static", "inline", "explicit", "constexpr",
    "friend", "extern", "mutable", "typedef",
}
# 関数ではないと断定できる開始トークン
NOT_A_FUNCTION = {"class", "struct", "union", "enum", "namespace", "using", "return"}

IDENT = re.compile(r"[A-Za-z_]\w*")
DOC_START = re.compile(r"/\*[*!]")
PARAM_TAG = re.compile(r"[@\\]param(?:\s*\[[^\]]*\])?\s+([A-Za-z_]\w*)")
PARAM_TAG_NO_DIR = re.compile(r"[@\\]param\s+[A-Za-z_]")
BRIEF_TAG = re.compile(r"[@\\]brief\b")
RETURN_TAG = re.compile(r"[@\\](?:return|returns|retval)\b")


class Report:
    def __init__(self):
        self.errors = []
        self.warns = []
        self.skips = []

    def error(self, where, msg):
        self.errors.append((where, msg))

    def warn(self, where, msg):
        self.warns.append((where, msg))

    def skip(self, where, msg):
        self.skips.append((where, msg))

    def dump(self, quiet):
        for where, msg in self.errors:
            print(f"ERROR  {where}: {msg}")
        for where, msg in self.warns:
            print(f"WARN   {where}: {msg}")
        if not quiet:
            for where, msg in self.skips:
                print(f"SKIP   {where}: {msg}")
        print()
        print(f"ERROR {len(self.errors)} 件 / WARN {len(self.warns)} 件 / SKIP {len(self.skips)} 件")
        if self.errors:
            print("不合格。ERROR を解消するまで P2 に進まないこと。")
        else:
            print("合格。@pre / @post の妥当性は references/function-design.md で目視確認すること。")
        return 1 if self.errors else 0


def split_top_level(text, sep=","):
    """深さ0の区切り文字で分割する。<> () {} [] をネストとして数える。"""
    out, depth, cur = [], 0, []
    openers, closers = "<([{", ">)]}"
    for ch in text:
        if ch in openers:
            depth += 1
        elif ch in closers:
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [s.strip() for s in out]


def find_paren_span(text):
    """最初の深さ0の '(' と対応する ')' の位置を返す。見つからなければ None。"""
    start = text.find("(")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return (start, i)
    return None


def param_name(decl):
    """引数宣言から引数名を取り出す。取れなければ None。"""
    d = split_top_level(decl, "=")[0].strip()      # 既定値を落とす
    d = re.sub(r"\[[^\]]*\]\s*$", "", d).strip()   # 配列の [] を落とす
    if not d or d == "void":
        return None
    if "(" in d:  # 関数ポインタ引数などは読み切れない
        m = list(IDENT.finditer(d))
        return m[-1].group(0) if m else None
    names = IDENT.findall(d)
    if not names:
        return None
    last = names[-1]
    # 型名しか書かれていない（無名引数）ケースを弾く
    if last in {"const", "volatile", "unsigned", "signed", "int", "char", "long",
                "short", "float", "double", "bool", "void", "auto"}:
        return None
    if len(names) == 1 and not re.search(r"[\*&]\s*" + re.escape(last) + r"\s*$", d):
        # 例: "std::int32_t" のように型のみ → 名前なし
        if "::" in d or d == last:
            return None
    return last


def collect_statement(lines, i):
    """i 行目から宣言1個分を集める。(本文, 次の行番号) を返す。"""
    buf = []
    depth = 0
    while i < len(lines):
        line = lines[i]
        # 次の Doxygen コメントに達したら、そこで打ち切る（宣言をまたいで飲み込まない）
        if buf and DOC_START.match(line.strip()):
            return " ".join(buf), i
        code = re.sub(r"//.*$", "", line)
        buf.append(code)
        for ch in code:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        joined = " ".join(buf)
        if depth <= 0 and re.search(r"[;{}]", code):
            return joined, i + 1
        i += 1
        if len(buf) > 40:  # 暴走防止
            return " ".join(buf), i
    return " ".join(buf), i


def analyze(path, rep):
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    class_names = set(re.findall(r"\b(?:class|struct)\s+([A-Za-z_]\w*)", text))

    i = 0
    pending_doc = None
    pending_doc_line = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        if not stripped:
            i += 1
            continue
        if stripped.startswith("#"):
            i += 1
            continue
        if stripped.startswith("//"):
            i += 1
            continue
        # アクセス指定子・ラベルは宣言ではない。直前の Doxygen を捨てないよう読み飛ばす
        if re.fullmatch(r"(public|protected|private)\s*:.*", stripped):
            i += 1
            continue

        if DOC_START.search(stripped) or stripped.startswith("/*"):
            is_doc = bool(DOC_START.match(stripped))
            start = i
            block = []
            while i < len(lines):
                block.append(lines[i])
                if "*/" in lines[i]:
                    break
                i += 1
            i += 1
            if is_doc:
                pending_doc = "\n".join(block)
                pending_doc_line = start + 1
            else:
                pending_doc = None
            continue

        stmt, next_i = collect_statement(lines, i)
        line_no = i + 1
        i = next_i
        check_declaration(path, line_no, stmt, pending_doc, pending_doc_line,
                          class_names, rep)
        pending_doc = None


def check_declaration(path, line_no, stmt, doc, doc_line, class_names, rep):
    where = f"{path}:{line_no}"
    s = " ".join(stmt.split())

    if s.startswith("template"):
        rep.skip(where, "テンプレート宣言は読み飛ばした。目視で確認すること")
        return
    head = s.split("(")[0]
    first = IDENT.search(head)
    if first and first.group(0) in NOT_A_FUNCTION:
        return
    if "(" not in s:
        return
    if re.search(r"=\s*(delete|default)\s*;", s):
        return
    if re.search(r"\boperator\b", s):
        rep.skip(where, "演算子オーバーロードは読み飛ばした。目視で確認すること")
        return

    span = find_paren_span(s)
    if span is None:
        return
    before = s[:span[0]].strip()
    inside = s[span[0] + 1:span[1]]

    # マクロ呼び出し・変数の初期化を弾く
    tokens = [t for t in IDENT.findall(before) if t not in LEADING_KEYWORDS]
    if not tokens:
        return
    name = tokens[-1]
    is_dtor = "~" in before
    return_tokens = tokens[:-1]
    is_ctor = (not return_tokens) and (name in class_names)

    if not return_tokens and not is_ctor and not is_dtor:
        return  # 戻り値型が無く、コンストラクタでもない → 関数宣言ではない

    params = [p for p in (param_name(p) for p in split_top_level(inside)) if p]
    n_declared = len([p for p in split_top_level(inside) if p and p != "void"])

    label = f"{name}()"

    if doc is None:
        rep.error(where, f"{label} に Doxygen コメントがない")
        return

    dwhere = f"{path}:{doc_line}"
    if not BRIEF_TAG.search(doc):
        rep.error(dwhere, f"{label} の Doxygen に @brief がない")

    documented = set(PARAM_TAG.findall(doc))
    for p in params:
        if p not in documented:
            rep.error(dwhere, f"{label} の引数 {p} に対応する @param がない")
    for d in documented - set(params):
        rep.warn(dwhere, f"{label} の @param {d} は宣言に存在しない引数")
    if n_declared > len(params):
        rep.warn(where, f"{label} に名前のない引数がある。名前を付けて @param を書くこと")
    if PARAM_TAG_NO_DIR.search(doc):
        rep.warn(dwhere, f"{label} の @param に方向指定（[in] / [out] / [in,out]）がない")

    if not is_ctor and not is_dtor:
        # 表示用に元の字面から戻り値型を切り出す（"std::int32_t" を保つため）
        cut = before.rfind(name)
        ret = before[:cut].strip() if cut > 0 else " ".join(return_tokens)
        for kw in LEADING_KEYWORDS:
            ret = re.sub(r"\b" + kw + r"\b", "", ret)
        ret = " ".join(ret.split())
        is_void = ret == "void" and "*" not in before
        if not is_void and not RETURN_TAG.search(doc):
            rep.error(dwhere, f"{label} は戻り値型 {ret} だが @return / @retval がない")


def gather(paths, rep):
    files = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for f in sorted(path.rglob("*")):
                if f.is_file() and f.suffix in HEADER_SUFFIXES:
                    files.append(f)
        elif path.is_file():
            files.append(path)
        else:
            rep.error(str(path), "ファイルもディレクトリも存在しない")
    return files


def main(argv):
    ap = argparse.ArgumentParser(add_help=True, description=__doc__)
    ap.add_argument("paths", nargs="+", help="ヘッダファイル、またはヘッダを含むディレクトリ")
    ap.add_argument("--quiet", action="store_true", help="SKIP を表示しない")
    try:
        args = ap.parse_args(argv[1:])
    except SystemExit:
        return 2

    rep = Report()
    files = gather(args.paths, rep)
    if not files and not rep.errors:
        print("ERROR  検査対象のヘッダが1つも見つからない")
        return 1

    print(f"検査対象: {len(files)} ファイル")
    print()
    for f in files:
        analyze(f, rep)
    return rep.dump(args.quiet)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
