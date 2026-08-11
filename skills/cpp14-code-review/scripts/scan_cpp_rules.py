#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""組込み C++14（AUTOSAR C++14 / CERT C++）の規約違反候補を静的に抽出する。

出力するのは「指摘」ではなく「候補」である。確度 high / medium / policy を付けて
返すので、medium と policy は R2（目視レビュー）で1件ずつ採否を判定すること。

    python scan_cpp_rules.py --scope work/review-scope.json -o work/scan-report.json
    python scan_cpp_rules.py src/ include/ -o work/scan-report.json

終了コード:
    0  実行成功（検出件数の多寡によらず 0。検出はゲートではない）
    1  実行エラー（対象が存在しない、scope が読めない、出力先に書けない）
    2  引数の指定ミス

ルールIDと誤検知パターンは references/scan-rules.md を参照。
依存は標準ライブラリのみ。
"""

import argparse
import bisect
import json
import os
import re
import sys
from datetime import datetime

CPP_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx", ".h++", ".inl", ".ipp")
HEADER_SUFFIXES = (".h", ".hh", ".hpp", ".hxx", ".h++", ".inl", ".ipp")

# 関数定義の走査で名前として拾ってはいけない予約語
CONTROL_KEYWORDS = {
    "if", "else", "for", "while", "switch", "catch", "return", "sizeof",
    "case", "do", "throw", "new", "delete", "typeid", "alignof", "decltype",
    "static_cast", "dynamic_cast", "const_cast", "reinterpret_cast",
    "and", "or", "not", "template", "typename", "noexcept", "explicit",
}

BUILTIN_TYPES = {
    "void", "bool", "char", "wchar_t", "char16_t", "char32_t", "short", "int",
    "long", "float", "double", "signed", "unsigned", "size_t",
}

DEFAULT_MAX_FUNCTION_LINES = 60

# Windows の既定コードページでは日本語の要約が化けるため、可能なら UTF-8 に切り替える
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


class Finding(object):
    def __init__(self, rule, confidence, path, line, code, message):
        self.rule = rule
        self.confidence = confidence
        self.path = path
        self.line = line
        self.code = code
        self.message = message
        self.source = "scanner"

    def to_dict(self, seq, in_diff):
        return {
            "seq": seq,
            "rule": self.rule,
            "confidence": self.confidence,
            "file": self.path.replace(os.sep, "/"),
            "line": self.line,
            "in_diff": in_diff,
            "code": self.code.rstrip()[:200],
            "message": self.message,
            "source": self.source,
        }


# --------------------------------------------------------------------------
# 前処理: コメントと文字列・文字リテラルを空白に潰す（行・桁の構造は保つ）
# --------------------------------------------------------------------------

def strip_code(text):
    """コメントと文字列リテラルを空白に置換した文字列を返す。改行は保持する。"""
    out = []
    i = 0
    n = len(text)
    state = "code"  # code / line_comment / block_comment / string / char / raw
    raw_delim = ""
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                state = "line_comment"
                out.append("  ")
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block_comment"
                out.append("  ")
                i += 2
                continue
            if ch == "R" and nxt == '"':
                # 生文字列リテラル R"delim( ... )delim"
                j = text.find("(", i + 2)
                if j != -1:
                    raw_delim = text[i + 2:j]
                    state = "raw"
                    out.append(" " * (j - i + 1))
                    i = j + 1
                    continue
            if ch == '"':
                state = "string"
                out.append(" ")
                i += 1
                continue
            if ch == "'":
                state = "char"
                out.append(" ")
                i += 1
                continue
            out.append(ch)
            i += 1
            continue

        if state == "line_comment":
            if ch == "\n":
                state = "code"
                out.append("\n")
            else:
                out.append(" ")
            i += 1
            continue

        if state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "code"
                out.append("  ")
                i += 2
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue

        if state == "raw":
            closing = ")" + raw_delim + '"'
            if text.startswith(closing, i):
                state = "code"
                out.append(" " * len(closing))
                i += len(closing)
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue

        # string / char
        if ch == "\\":
            out.append("  ")
            i += 2
            continue
        if (state == "string" and ch == '"') or (state == "char" and ch == "'"):
            state = "code"
            out.append(" ")
            i += 1
            continue
        out.append("\n" if ch == "\n" else " ")
        i += 1
    return "".join(out)


class Source(object):
    """1ファイル分の原文と、コメント・リテラルを除去した文の両方を保持する。"""

    def __init__(self, path, text):
        self.path = path
        self.text = text
        self.clean = strip_code(text)
        self.lines = text.splitlines()
        self.clean_lines = self.clean.splitlines()
        # オフセット -> 行番号 の逆引き用
        self._starts = [0]
        for line in self.clean.split("\n")[:-1]:
            self._starts.append(self._starts[-1] + len(line) + 1)
        self.is_header = path.lower().endswith(HEADER_SUFFIXES)

    def line_of(self, offset):
        return bisect.bisect_right(self._starts, offset)

    def raw_line(self, lineno):
        if 1 <= lineno <= len(self.lines):
            return self.lines[lineno - 1]
        return ""

    def clean_line(self, lineno):
        if 1 <= lineno <= len(self.clean_lines):
            return self.clean_lines[lineno - 1]
        return ""


def match_forward(text, start, open_ch, close_ch):
    """text[start] が open_ch のとき、対応する close_ch の位置を返す。見つからなければ -1。"""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


def split_top_level(text, sep=","):
    """括弧の入れ子を考慮して分割する。"""
    parts = []
    depth = 0
    cur = []
    for ch in text:
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts]


# --------------------------------------------------------------------------
# 構造の抽出（クラス / 関数 / switch）
# --------------------------------------------------------------------------

RE_CLASS = re.compile(r"\b(class|struct)\s+(?:[A-Z_][A-Z0-9_]*\s+)?([A-Za-z_]\w*)\s*(final\s*)?(:[^{;]*)?\{")
RE_CALL = re.compile(r"([A-Za-z_~][A-Za-z0-9_]*)\s*\(")
RE_SWITCH = re.compile(r"\bswitch\s*\(")
RE_QUALIFIER = re.compile(r"\s*(const|volatile|noexcept|override|final|mutable|&&|&|throw\s*\(\s*\)|->[^{;]*)")


def find_classes(src):
    """[(name, has_base, body_start, body_end, header_lineno)] を返す。"""
    result = []
    for m in RE_CLASS.finditer(src.clean):
        brace = m.end() - 1
        end = match_forward(src.clean, brace, "{", "}")
        if end == -1:
            continue
        result.append((m.group(2), bool(m.group(4)), brace + 1, end, src.line_of(m.start())))
    return result


def find_functions(src):
    """[(name, params, body_start, body_end, decl_lineno)] を返す。"""
    result = []
    text = src.clean
    for m in RE_CALL.finditer(text):
        name = m.group(1)
        if name in CONTROL_KEYWORDS:
            continue
        popen = m.end() - 1
        pclose = match_forward(text, popen, "(", ")")
        if pclose == -1:
            continue
        i = pclose + 1
        # 修飾子と初期化子リストを読み飛ばして、本体の { にたどり着けるか見る
        while i < len(text):
            q = RE_QUALIFIER.match(text, i)
            if q and q.end() > i:
                i = q.end()
                continue
            break
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
        if i < len(text) and text[i] == ":" and text[i:i + 2] != "::":
            # メンバ初期化子リスト。同じ深さの { まで進む
            depth = 0
            j = i
            while j < len(text):
                if text[j] in "([":
                    depth += 1
                elif text[j] in ")]":
                    depth -= 1
                elif text[j] == "{" and depth == 0:
                    break
                elif text[j] == ";" and depth == 0:
                    j = -1
                    break
                j += 1
            i = j
        if i == -1 or i >= len(text) or text[i] != "{":
            continue
        end = match_forward(text, i, "{", "}")
        if end == -1:
            continue
        result.append((name, text[popen + 1:pclose], i + 1, end, src.line_of(m.start())))
    return result


def find_switches(src):
    """[(body_start, body_end, switch_lineno)] を返す。"""
    result = []
    text = src.clean
    for m in RE_SWITCH.finditer(text):
        popen = m.end() - 1
        pclose = match_forward(text, popen, "(", ")")
        if pclose == -1:
            continue
        i = pclose + 1
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
        if i >= len(text) or text[i] != "{":
            continue
        end = match_forward(text, i, "{", "}")
        if end == -1:
            continue
        result.append((i + 1, end, src.line_of(m.start())))
    return result


def scan_labels_at_depth1(src, body_start, body_end):
    """switch 本体の直下にある case / default ラベルの (種別, オフセット) を返す。"""
    text = src.clean
    labels = []
    depth = 0
    i = body_start
    while i < body_end:
        ch = text[i]
        if ch in "{([":
            depth += 1
        elif ch in "})]":
            depth -= 1
        elif depth == 0 and (text.startswith("case", i) or text.startswith("default", i)):
            before = text[i - 1] if i > 0 else " "
            kind = "case" if text.startswith("case", i) else "default"
            after = text[i + len(kind)] if i + len(kind) < len(text) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                labels.append((kind, i))
                i += len(kind)
                continue
        i += 1
    return labels


# --------------------------------------------------------------------------
# ルール本体
# --------------------------------------------------------------------------

RE_C_CAST = re.compile(
    r"(?<![A-Za-z0-9_)\]])\(\s*((?:const\s+|volatile\s+|unsigned\s+|signed\s+|struct\s+|enum\s+)*"
    r"[A-Za-z_]\w*(?:\s*::\s*\w+)*)\s*((?:\*|&)*)\s*\)\s*(?=[A-Za-z_(\-+~!&*])"
)
RE_NULL = re.compile(r"\bNULL\b")
RE_USING_NS = re.compile(r"\busing\s+namespace\b")
RE_C_ALLOC = re.compile(r"(?<![.\w>])\b(malloc|calloc|realloc|free)\s*\(")
RE_ENV_API = re.compile(r"(?<![.\w>])\b(system|getenv|exit|abort|atexit)\s*\(")
RE_FUNC_MACRO = re.compile(r"^\s*#\s*define\s+\w+\(")
RE_VARARG = re.compile(r"[(,]\s*\.\.\.\s*\)")
RE_CATCH_ALL = re.compile(r"\bcatch\s*\(\s*\.\.\.\s*\)")
RE_GOTO = re.compile(r"\bgoto\b")
RE_TODO = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")
RE_PLAIN_INT = re.compile(r"\b(?:unsigned\s+|signed\s+)?\b(int|long|short|char)\b(?!\s*\*\s*\w+\s*=\s*\")")
RE_LONE_UNSIGNED = re.compile(r"\bunsigned\b(?!\s*(int|long|short|char))")
RE_FLOAT_CMP = re.compile(r"(?:(?<![\w.])\d+\.\d*[fF]?|(?<![\w.])\.\d+[fF]?|\b\d+[eE][+-]?\d+[fF]?)\s*[=!]=|"
                          r"[=!]=\s*(?:(?<![\w.])\d+\.\d*[fF]?|(?<![\w.])\.\d+[fF]?|\b\d+[eE][+-]?\d+[fF]?)")
RE_MAGIC = re.compile(r"(?<![\w.\"'])(0[xX][0-9a-fA-F]+|\d+\.\d+|\d+)(?![\w.])")
RE_CONST_DEF = re.compile(r"\b(const|constexpr|enum|#\s*define|static\s+const)\b")
RE_THROW_TRY = re.compile(r"\b(throw|try|catch)\b")
RE_NEW = re.compile(r"\bnew\b(?!\s*\))")
RE_DELETE = re.compile(r"(?<![=]\s)\bdelete\b")
RE_RTTI = re.compile(r"\b(dynamic_cast|typeid)\b")
RE_CTRL_HEAD = re.compile(r"(?<![\w.])\b(if|for|while)\s*\(")
RE_TERMINATOR = re.compile(r"\b(break|return|throw|continue|goto)\b")
RE_FALLTHROUGH_NOTE = re.compile(r"fall\s*-?\s*thro?ugh|意図的に落と|フォールスルー", re.IGNORECASE)

NON_TYPE_LEADS = {"return", "if", "while", "for", "switch", "case", "sizeof", "else",
                  "do", "and", "or", "not", "new", "delete", "throw", "catch", "using",
                  "typedef", "namespace", "public", "private", "protected", "operator"}


def _looks_like_type(token, ptr):
    """C スタイルキャストの中身が型に見えるか。誤検知を抑えるための絞り込み。"""
    head = token.split()[0] if token.split() else ""
    if head in NON_TYPE_LEADS:
        return False
    if ptr:
        return True
    words = token.replace("::", " ").split()
    last = words[-1] if words else ""
    if last in BUILTIN_TYPES or head in ("const", "volatile", "unsigned", "signed", "struct", "enum"):
        return True
    if last.endswith("_t") or "::" in token:
        return True
    if last[:1].isupper():
        return True
    return False


def rule_line_regexes(src, findings):
    """行単位で判定できるルール。"""
    for lineno, cline in enumerate(src.clean_lines, start=1):
        raw = src.raw_line(lineno)
        stripped = cline.strip()

        for m in RE_C_CAST.finditer(cline):
            token, ptr = m.group(1).strip(), m.group(2).strip()
            if token == "void" and not ptr:
                continue  # 未使用引数の抑止。組込みでは正当
            if not _looks_like_type(token, ptr):
                continue
            findings.append(Finding("CAST-001", "high", src.path, lineno, raw, "C スタイルキャスト"))

        if RE_NULL.search(cline):
            findings.append(Finding("BAN-001", "high", src.path, lineno, raw, "NULL の使用。nullptr を使う"))

        if src.is_header and RE_USING_NS.search(cline):
            findings.append(Finding("BAN-002", "high", src.path, lineno, raw, "ヘッダ内の using namespace"))

        m = RE_C_ALLOC.search(cline)
        if m:
            findings.append(Finding("BAN-003", "high", src.path, lineno, raw,
                                    "C のメモリ API: %s" % m.group(1)))

        m = RE_ENV_API.search(cline)
        if m:
            findings.append(Finding("BAN-004", "high", src.path, lineno, raw,
                                    "環境依存 API: %s" % m.group(1)))

        if RE_FUNC_MACRO.match(cline):
            findings.append(Finding("BAN-005", "high", src.path, lineno, raw,
                                    "関数形式マクロ。constexpr / inline 関数にする"))

        if RE_VARARG.search(cline) and not RE_CATCH_ALL.search(cline):
            findings.append(Finding("BAN-006", "high", src.path, lineno, raw, "可変長引数"))

        if RE_GOTO.search(cline):
            findings.append(Finding("CTRL-001", "high", src.path, lineno, raw, "goto"))

        # TODO 類はコメント内にあるので原文を見る
        m = RE_TODO.search(raw)
        if m:
            findings.append(Finding("MNT-001", "high", src.path, lineno, raw,
                                    "未完了の印が残っている: %s" % m.group(1)))

        if stripped.startswith("#"):
            continue

        if RE_PLAIN_INT.search(cline) or RE_LONE_UNSIGNED.search(cline):
            if "main(" not in cline and "argv" not in cline:
                findings.append(Finding("TYPE-001", "medium", src.path, lineno, raw,
                                        "可変幅の整数型。<cstdint> の固定幅型を検討する"))

        if RE_FLOAT_CMP.search(cline):
            findings.append(Finding("TYPE-002", "medium", src.path, lineno, raw,
                                    "浮動小数点の等値比較"))

        if not RE_CONST_DEF.search(cline) and "#include" not in cline:
            for m in RE_MAGIC.finditer(cline):
                lit = m.group(1)
                if lit in ("0", "1", "2", "0x0", "0X0", "0x1", "0X1"):
                    continue
                findings.append(Finding("MNT-002", "medium", src.path, lineno, raw,
                                        "マジックナンバー: %s" % lit))
                break


def rule_braces(src, findings):
    """CTRL-003: if / for / while の本体でブレースを省略している。"""
    text = src.clean
    for m in RE_CTRL_HEAD.finditer(text):
        lineno = src.line_of(m.start())
        if src.clean_line(lineno).strip().startswith("#"):
            continue
        # do { ... } while (...); の while は対象外
        if m.group(1) == "while":
            head = text[:m.start()].rstrip()
            if head.endswith("}"):
                continue
        popen = m.end() - 1
        pclose = match_forward(text, popen, "(", ")")
        if pclose == -1:
            continue
        i = pclose + 1
        while i < len(text) and text[i] in " \t\r":
            i += 1
        if i < len(text) and text[i] == "{":
            continue
        if i < len(text) and text[i] == "\n":
            # 次の空でない行が { で始まるか
            j = i
            while j < len(text) and text[j] in " \t\r\n":
                j += 1
            if j < len(text) and text[j] == "{":
                continue
        findings.append(Finding("CTRL-003", "high", src.path, lineno, src.raw_line(lineno),
                                "%s の本体がブレースで囲まれていない" % m.group(1)))


def rule_switch(src, findings):
    """CTRL-002: default 欠落 / CTRL-004: フォールスルー。"""
    text = src.clean
    for body_start, body_end, lineno in find_switches(src):
        labels = scan_labels_at_depth1(src, body_start, body_end)
        if not any(k == "default" for k, _ in labels):
            findings.append(Finding("CTRL-002", "high", src.path, lineno, src.raw_line(lineno),
                                    "switch に default がない"))
        for idx in range(1, len(labels)):
            prev_off = labels[idx - 1][1]
            cur_off = labels[idx][1]
            segment = text[prev_off:cur_off]
            body = segment.split(":", 1)[1] if ":" in segment else ""
            if not body.strip():
                continue  # case を並べているだけ。フォールスルーではない
            if RE_TERMINATOR.search(body):
                continue
            cur_line = src.line_of(cur_off)
            note_window = "\n".join(src.lines[max(0, cur_line - 3):cur_line])
            if RE_FALLTHROUGH_NOTE.search(note_window):
                continue
            findings.append(Finding("CTRL-004", "medium", src.path, cur_line, src.raw_line(cur_line),
                                    "case のフォールスルー。意図するならコメントで明示する"))


def rule_classes(src, findings):
    """CLS-001..004。"""
    text = src.clean
    for name, has_base, body_start, body_end, lineno in find_classes(src):
        body = text[body_start:body_end]
        dtor = re.search(r"(virtual\s+)?~\s*%s\s*\(" % re.escape(name), body)

        # CLS-002: virtual を持つのにデストラクタが非 virtual（基底クラスを持つ場合は判定しない）
        if not has_base and re.search(r"\bvirtual\b", body):
            if dtor is None:
                findings.append(Finding("CLS-002", "medium", src.path, lineno, src.raw_line(lineno),
                                        "class %s は virtual を持つがデストラクタが宣言されていない" % name))
            elif not dtor.group(1):
                dline = src.line_of(body_start + dtor.start())
                findings.append(Finding("CLS-002", "medium", src.path, dline, src.raw_line(dline),
                                        "class %s のデストラクタが非 virtual" % name))

        # CLS-003: Rule of Five / Zero
        esc = re.escape(name)
        members = {
            "dtor": dtor is not None,
            "copy_ctor": re.search(r"%s\s*\(\s*const\s+%s\s*&" % (esc, esc), body) is not None,
            "move_ctor": re.search(r"%s\s*\(\s*%s\s*&&" % (esc, esc), body) is not None,
            "copy_assign": re.search(r"operator\s*=\s*\(\s*const\s+%s\s*&" % esc, body) is not None,
            "move_assign": re.search(r"operator\s*=\s*\(\s*%s\s*&&" % esc, body) is not None,
        }
        declared = sum(1 for v in members.values() if v)
        if 0 < declared < 5:
            missing = [k for k, v in members.items() if not v]
            findings.append(Finding("CLS-003", "medium", src.path, lineno, src.raw_line(lineno),
                                    "class %s が Rule of Five を満たしていない（未宣言: %s）"
                                    % (name, ", ".join(missing))))

        # CLS-001: 単一引数コンストラクタの explicit 欠落
        for m in re.finditer(r"([A-Za-z_~]\w*)\s*\(", body):
            if m.group(1) != name:
                continue
            popen = body_start + m.end() - 1
            pclose = match_forward(text, popen, "(", ")")
            if pclose == -1:
                continue
            params = [p for p in split_top_level(text[popen + 1:pclose]) if p and p != "void"]
            if len(params) != 1:
                continue
            p = params[0]
            if re.search(r"%s\s*(const\s*)?(&&|&)" % esc, p) or re.search(r"const\s+%s\s*&" % esc, p):
                continue  # コピー / ムーブコンストラクタ
            head = body[:m.start()]
            tail = head.rsplit(";", 1)[-1].rsplit("{", 1)[-1].rsplit("}", 1)[-1].rsplit(":", 1)[-1]
            if "explicit" in tail:
                continue
            cline = src.line_of(body_start + m.start())
            findings.append(Finding("CLS-001", "medium", src.path, cline, src.raw_line(cline),
                                    "単一引数コンストラクタに explicit がない"))

        # CLS-004: 派生クラスの virtual 再宣言に override / final がない
        if has_base:
            for m in re.finditer(r"\bvirtual\b[^;{]*[;{]", body):
                decl = m.group(0)
                if "override" in decl or "final" in decl or "~" in decl:
                    continue
                cline = src.line_of(body_start + m.start())
                findings.append(Finding("CLS-004", "medium", src.path, cline, src.raw_line(cline),
                                        "派生クラスの virtual 宣言に override / final がない"))


def rule_functions(src, findings, max_lines):
    """FUNC-001: 直接再帰 / MNT-003: 関数が長い。"""
    text = src.clean
    for name, _params, body_start, body_end, lineno in find_functions(src):
        body = text[body_start:body_end]
        if re.search(r"(?<![\w.>:])%s\s*\(" % re.escape(name), body):
            findings.append(Finding("FUNC-001", "medium", src.path, lineno, src.raw_line(lineno),
                                    "直接再帰。スタック使用量が静的に見積もれるか確認する"))
        length = src.line_of(body_end) - src.line_of(body_start) + 1
        if length > max_lines:
            findings.append(Finding("MNT-003", "medium", src.path, lineno, src.raw_line(lineno),
                                    "関数 %s が %d 行（閾値 %d）" % (name, length, max_lines)))


def rule_policy(src, findings, policy):
    """POL-001..003。方針が forbidden のときのみ違反として扱う。"""
    for lineno, cline in enumerate(src.clean_lines, start=1):
        raw = src.raw_line(lineno)
        if cline.strip().startswith("#"):
            continue

        exc = policy.get("exceptions", "unknown")
        if exc != "allowed" and RE_THROW_TRY.search(cline):
            conf = "policy" if exc == "unknown" else "high"
            findings.append(Finding("POL-001", conf, src.path, lineno, raw, "例外の使用"))

        dyn = policy.get("dynamic_memory", "unknown")
        if dyn != "allowed":
            hit = RE_NEW.search(cline) or RE_DELETE.search(cline)
            if hit and "= delete" not in cline and "=delete" not in cline:
                conf = "high" if dyn == "forbidden" else ("medium" if dyn == "init_only" else "policy")
                msg = "動的メモリ確保" if dyn != "init_only" else "動的メモリ確保。初期化時のみか確認する"
                findings.append(Finding("POL-002", conf, src.path, lineno, raw, msg))

        rtti = policy.get("virtual_rtti", "unknown")
        if rtti != "allowed" and RE_RTTI.search(cline):
            conf = "policy" if rtti == "unknown" else "high"
            findings.append(Finding("POL-003", conf, src.path, lineno, raw, "RTTI の使用"))


def scan_file(path, policy, max_lines):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        raise RuntimeError("読み込めない: %s (%s)" % (path, e))
    src = Source(path, text)
    findings = []
    rule_line_regexes(src, findings)
    rule_braces(src, findings)
    rule_switch(src, findings)
    rule_classes(src, findings)
    rule_functions(src, findings, max_lines)
    rule_policy(src, findings, policy)
    return findings


# --------------------------------------------------------------------------
# 外部ツールのログ取り込み
# --------------------------------------------------------------------------

RE_TIDY = re.compile(r"^(?P<file>[^:\s][^:]*):(?P<line>\d+):(?:\d+:)?\s*"
                     r"(?P<sev>error|warning|note|info|remark):\s*(?P<msg>.*?)\s*(?:\[(?P<check>[^\]]+)\])?$",
                     re.IGNORECASE)


def load_tool_log(path):
    findings = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = RE_TIDY.match(line.rstrip("\n"))
            if not m:
                continue
            sev = m.group("sev").lower()
            if sev == "note":
                continue
            conf = "high" if sev == "error" else "medium"
            fd = Finding(m.group("check") or "external", conf, m.group("file"),
                         int(m.group("line")), m.group("msg"), m.group("msg"))
            fd.source = os.path.basename(path)
            findings.append(fd)
    return findings


# --------------------------------------------------------------------------
# 対象の収集
# --------------------------------------------------------------------------

def collect_targets(paths):
    out = []
    for p in paths:
        if os.path.isfile(p):
            out.append(p)
        elif os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in (".git", "build", "out", "node_modules")]
                for name in sorted(files):
                    if name.lower().endswith(CPP_SUFFIXES):
                        out.append(os.path.join(root, name))
        else:
            raise RuntimeError("対象が存在しない: %s" % p)
    return out


def load_scope(path):
    with open(path, "r", encoding="utf-8") as f:
        scope = json.load(f)
    files = []
    changed = {}
    for entry in scope.get("files", []):
        if isinstance(entry, str):
            files.append(entry)
        else:
            fp = entry.get("path")
            if not fp:
                continue
            files.append(fp)
            ranges = entry.get("changed_lines") or []
            changed[fp.replace(os.sep, "/")] = [tuple(r) for r in ranges if len(r) == 2]
    return scope, files, changed


def is_in_diff(mode, changed, path, line):
    if mode != "diff":
        return None
    ranges = changed.get(path.replace(os.sep, "/"))
    if not ranges:
        return False
    return any(lo <= line <= hi for lo, hi in ranges)


def main(argv):
    ap = argparse.ArgumentParser(
        description="組込み C++14 の規約違反候補を抽出する（指摘ではなく候補）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="対象のファイルまたはディレクトリ")
    ap.add_argument("--scope", default=None, help="work/review-scope.json")
    ap.add_argument("--tidy-log", action="append", default=[],
                    help="clang-tidy / PC-lint 形式のログ（複数指定可）")
    ap.add_argument("--max-function-lines", type=int, default=DEFAULT_MAX_FUNCTION_LINES,
                    help="MNT-003 の閾値（既定 %d）" % DEFAULT_MAX_FUNCTION_LINES)
    ap.add_argument("-o", "--output", default=None, help="JSON の出力先")
    args = ap.parse_args(argv)

    if not args.paths and not args.scope:
        ap.print_usage(sys.stderr)
        sys.stderr.write("エラー: 対象のパスか --scope のどちらかを指定する\n")
        return 2

    mode = "path"
    diff_base = None
    policy = {}
    changed = {}
    targets = []

    try:
        if args.scope:
            scope, files, changed = load_scope(args.scope)
            mode = scope.get("mode", "path")
            diff_base = scope.get("diff_base")
            policy = scope.get("policy", {}) or {}
            targets.extend(collect_targets(files))
        if args.paths:
            targets.extend(collect_targets(args.paths))
    except (OSError, ValueError, RuntimeError) as e:
        sys.stderr.write("エラー: %s\n" % e)
        return 1

    targets = sorted(set(os.path.normpath(t) for t in targets))
    targets = [t for t in targets if t.lower().endswith(CPP_SUFFIXES)]
    if not targets:
        sys.stderr.write("エラー: C/C++ の対象ファイルが1件もない\n")
        return 1

    findings = []
    try:
        for path in targets:
            findings.extend(scan_file(path, policy, args.max_function_lines))
        for log in args.tidy_log:
            findings.extend(load_tool_log(log))
    except (OSError, RuntimeError) as e:
        sys.stderr.write("エラー: %s\n" % e)
        return 1

    findings.sort(key=lambda f: (f.path, f.line, f.rule))
    records = []
    for i, fd in enumerate(findings, start=1):
        records.append(fd.to_dict(i, is_in_diff(mode, changed, fd.path, fd.line)))

    summary = {"high": 0, "medium": 0, "policy": 0, "external": 0}
    by_rule = {}
    for r in records:
        summary[r["confidence"]] = summary.get(r["confidence"], 0) + 1
        if r["source"] != "scanner":
            summary["external"] += 1
        by_rule[r["rule"]] = by_rule.get(r["rule"], 0) + 1

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": mode,
        "diff_base": diff_base,
        "policy": policy,
        "files_scanned": len(targets),
        "summary": summary,
        "findings": records,
    }

    if args.output:
        try:
            outdir = os.path.dirname(os.path.abspath(args.output))
            if outdir and not os.path.isdir(outdir):
                os.makedirs(outdir)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except OSError as e:
            sys.stderr.write("エラー: 出力先に書けない: %s\n" % e)
            return 1

    print("走査ファイル: %d 件 / mode=%s" % (len(targets), mode))
    print("候補: high %d / medium %d / policy %d（うち外部ツール由来 %d）"
          % (summary["high"], summary["medium"], summary["policy"], summary["external"]))
    if mode == "diff":
        in_diff = sum(1 for r in records if r["in_diff"])
        print("差分行内 %d 件 / 差分外 %d 件" % (in_diff, len(records) - in_diff))
    for rule, count in sorted(by_rule.items(), key=lambda kv: (-kv[1], kv[0])):
        print("  %-12s %d" % (rule, count))
    if args.output:
        print("詳細: %s" % args.output)
    print("※ これらは候補である。medium / policy は R2 で1件ずつ採否を判定すること。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
