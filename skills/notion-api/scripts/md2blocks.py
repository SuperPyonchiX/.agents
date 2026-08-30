"""Markdown を Notion API のブロック JSON 配列に変換する。

使い方:
    python md2blocks.py [--file INPUT.md] [--out OUTPUT.json]
    --file を省略すると標準入力から読む。--out を省略すると標準出力へ書く。

対応する記法:
    #/##/### 見出し、> 引用、--- 区切り線、-/* 箇条書き（字下げ2以上は直前項目の子）、
    1. 番号リスト、``` コードフェンス（言語指定つき）、**太字**、`インラインコード`。
    それ以外の連続行は1つの段落にまとめる。

制約の吸収:
    rich_text の1要素は2000字未満に自動分割する。

終了コード: 0=成功 / 2=引数・入力の不備
"""
import argparse
import json
import re
import sys

MAX_TEXT = 1990  # rich_text 1要素の上限 2000 に対する安全マージン

# Notion が受け付けるコードブロック言語（主要なもの）。外れたら plain text に落とす
KNOWN_LANGUAGES = {
    "bash", "c", "c#", "c++", "cpp", "csharp", "css", "diff", "go", "graphql", "html",
    "java", "javascript", "json", "kotlin", "markdown", "mermaid", "php", "plain text",
    "powershell", "python", "ruby", "rust", "shell", "sql", "swift", "typescript",
    "xml", "yaml",
}
LANGUAGE_ALIASES = {"js": "javascript", "ts": "typescript", "py": "python",
                    "sh": "shell", "ps1": "powershell", "cs": "c#", "text": "plain text",
                    "": "plain text"}

INLINE_RE = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")


def chunk(text):
    return [text[i:i + MAX_TEXT] for i in range(0, len(text), MAX_TEXT)] or [""]


def rich_text(text):
    """インライン記法を解釈して rich_text 配列を作る。"""
    out = []
    for part in INLINE_RE.split(text):
        if not part:
            continue
        annotations = None
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            content, annotations = part[2:-2], {"bold": True}
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            content, annotations = part[1:-1], {"code": True}
        else:
            content = part
        for piece in chunk(content):
            item = {"type": "text", "text": {"content": piece}}
            if annotations:
                item["annotations"] = dict(annotations)
            out.append(item)
    return out


def plain_rich_text(text):
    """インライン解釈をしない rich_text 配列（コードブロック用）。"""
    return [{"type": "text", "text": {"content": piece}} for piece in chunk(text)]


def make_block(block_type, text):
    return {"object": "block", "type": block_type, block_type: {"rich_text": rich_text(text)}}


def convert(lines):
    blocks = []
    paragraph = []  # 連続する平文行のバッファ
    code = None     # コードフェンス内なら [language, [lines...]]

    def flush_paragraph():
        if paragraph:
            blocks.append(make_block("paragraph", "\n".join(paragraph)))
            paragraph.clear()

    for raw in lines:
        line = raw.rstrip("\n")

        if code is not None:
            if line.strip().startswith("```"):
                blocks.append({"object": "block", "type": "code", "code": {
                    "rich_text": plain_rich_text("\n".join(code[1])),
                    "language": code[0]}})
                code = None
            else:
                code[1].append(line)
            continue

        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            lang = stripped[3:].strip().lower()
            lang = LANGUAGE_ALIASES.get(lang, lang)
            if lang not in KNOWN_LANGUAGES:
                lang = "plain text"
            code = [lang, []]
            continue
        if not stripped:
            flush_paragraph()
            continue
        if stripped == "---" or stripped == "***":
            flush_paragraph()
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            continue
        m = re.match(r"(#{1,3})\s+(.*)", stripped)
        if m and not line.startswith((" ", "\t")):
            flush_paragraph()
            blocks.append(make_block("heading_{}".format(len(m.group(1))), m.group(2)))
            continue
        if stripped.startswith("> "):
            flush_paragraph()
            blocks.append(make_block("quote", stripped[2:]))
            continue
        m = re.match(r"(\s*)[-*]\s+(.*)", line)
        if m:
            flush_paragraph()
            item = make_block("bulleted_list_item", m.group(2))
            if len(m.group(1)) >= 2 and blocks and blocks[-1]["type"] == "bulleted_list_item":
                blocks[-1]["bulleted_list_item"].setdefault("children", []).append(item)
            else:
                blocks.append(item)
            continue
        m = re.match(r"\s*\d+[.)]\s+(.*)", line)
        if m:
            flush_paragraph()
            blocks.append(make_block("numbered_list_item", m.group(1)))
            continue
        paragraph.append(stripped)

    if code is not None:  # 閉じられていないフェンスもコードとして出す
        blocks.append({"object": "block", "type": "code", "code": {
            "rich_text": plain_rich_text("\n".join(code[1])), "language": code[0]}})
    flush_paragraph()
    return blocks


def main():
    parser = argparse.ArgumentParser(description="Markdown → Notion blocks JSON")
    parser.add_argument("--file", help="入力 Markdown ファイル。省略時は標準入力")
    parser.add_argument("--out", help="出力 JSON ファイル。省略時は標準出力")
    args = parser.parse_args()

    if args.file:
        try:
            with open(args.file, encoding="utf-8-sig") as f:
                lines = f.readlines()
        except OSError as e:
            print("ファイルを読めません: {}".format(e), file=sys.stderr)
            sys.exit(2)
    else:
        lines = sys.stdin.readlines()

    blocks = convert(lines)
    text = json.dumps(blocks, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)


if __name__ == "__main__":
    main()
