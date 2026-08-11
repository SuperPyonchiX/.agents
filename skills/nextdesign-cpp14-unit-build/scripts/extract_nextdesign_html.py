#!/usr/bin/env python3
"""Next Design の HTML エクスポートを、構造を保った中間 JSON に落とす。

使い方:
    python scripts/extract_nextdesign_html.py <html> -o <出力json>

終了コード:
    0  成功
    1  読み込みまたはパース失敗
    2  引数誤り

意味づけ（どの表が「操作」でどの列が「戻り値型」か）は**このスクリプトの担当ではない**。
Next Design のエクスポートは章立ても列名も固定ではないため、決め打ちのパースは
必ず壊れる。ここでは見出し階層・表・段落・図の alt を機械的に取り出すだけにして、
意味づけはエージェント側（references/nextdesign-input.md）に任せる。

出力の形:

    {
      "source": "design.html",
      "title": "詳細設計書",
      "sections": [
        {
          "level": 2,
          "heading": "MotorController",
          "path": ["詳細設計書", "制御", "MotorController"],
          "paragraphs": ["..."],
          "tables": [{"caption": "操作", "headers": [...], "rows": [[...]]}],
          "images": [{"alt": "クラス図", "src": "img/class01.png"}]
        }
      ]
    }

依存は標準ライブラリのみ。
"""

import argparse
import json
import sys
from html.parser import HTMLParser

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TEXT = {"p", "li", "dd", "dt", "pre"}
SKIP_CONTENT = {"script", "style"}


def _clean(text):
    """空白を潰して1行にする。表のセルは改行を含みうるため。"""
    return " ".join(text.split())


class NextDesignHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.sections = []
        self._section = self._new_section(0, "")
        self._stack = []          # (level, heading) の祖先スタック
        self._buf = []            # 現在収集中のテキスト
        self._mode = None         # "heading" / "text" / "cell" / "caption" / "title"
        self._skip_depth = 0
        # 表の状態
        self._table_depth = 0
        self._table = None
        self._row = None
        self._row_is_header = False

    # --- 内部ヘルパ ---

    @staticmethod
    def _new_section(level, heading):
        return {
            "level": level,
            "heading": heading,
            "path": [],
            "paragraphs": [],
            "tables": [],
            "images": [],
        }

    def _flush_section(self):
        s = self._section
        has_content = s["paragraphs"] or s["tables"] or s["images"]
        if s["heading"] or has_content:
            self.sections.append(s)

    def _take_buf(self):
        text = _clean("".join(self._buf))
        self._buf = []
        return text

    def _push_path(self, level, heading):
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        path = [h for (_, h) in self._stack] + [heading]
        self._stack.append((level, heading))
        return path

    # --- HTMLParser のフック ---

    def handle_starttag(self, tag, attrs):
        if self._skip_depth:
            if tag in SKIP_CONTENT:
                self._skip_depth += 1
            return
        if tag in SKIP_CONTENT:
            self._skip_depth = 1
            return

        attrd = dict(attrs)

        if tag == "title":
            self._mode = "title"
            self._buf = []
        elif tag in HEADINGS:
            self._flush_section()
            self._section = self._new_section(int(tag[1]), "")
            self._mode = "heading"
            self._buf = []
        elif tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._table = {"caption": "", "headers": [], "rows": []}
        elif tag == "caption" and self._table_depth == 1:
            self._mode = "caption"
            self._buf = []
        elif tag == "tr" and self._table_depth == 1:
            self._row = []
            self._row_is_header = False
        elif tag in ("td", "th") and self._table_depth == 1:
            if tag == "th":
                self._row_is_header = True
            self._mode = "cell"
            self._buf = []
        elif tag == "img":
            self._section["images"].append(
                {"alt": _clean(attrd.get("alt", "")), "src": attrd.get("src", "")}
            )
        elif tag in BLOCK_TEXT and self._table_depth == 0:
            self._mode = "text"
            self._buf = []
        elif tag == "br" and self._mode:
            self._buf.append(" ")

    def handle_endtag(self, tag):
        if self._skip_depth:
            if tag in SKIP_CONTENT:
                self._skip_depth -= 1
            return

        if tag == "title" and self._mode == "title":
            self.title = self._take_buf()
            self._mode = None
        elif tag in HEADINGS and self._mode == "heading":
            heading = self._take_buf()
            self._section["heading"] = heading
            self._section["path"] = self._push_path(self._section["level"], heading)
            self._mode = None
        elif tag == "caption" and self._table_depth == 1:
            if self._table is not None:
                self._table["caption"] = self._take_buf()
            self._mode = None
        elif tag in ("td", "th") and self._table_depth == 1:
            if self._row is not None:
                self._row.append(self._take_buf())
            self._mode = None
        elif tag == "tr" and self._table_depth == 1:
            if self._table is not None and self._row:
                if self._row_is_header and not self._table["headers"]:
                    self._table["headers"] = self._row
                else:
                    self._table["rows"].append(self._row)
            self._row = None
        elif tag == "table":
            if self._table_depth == 1 and self._table is not None:
                # <th> が無いエクスポートでは 1 行目を見出し行とみなす
                if not self._table["headers"] and self._table["rows"]:
                    self._table["headers"] = self._table["rows"].pop(0)
                self._section["tables"].append(self._table)
                self._table = None
            self._table_depth = max(0, self._table_depth - 1)
        elif tag in BLOCK_TEXT and self._mode == "text":
            text = self._take_buf()
            if text:
                self._section["paragraphs"].append(text)
            self._mode = None

    def handle_data(self, data):
        if self._skip_depth or not self._mode:
            return
        self._buf.append(data)

    def close(self):
        super().close()
        self._flush_section()


def main(argv):
    ap = argparse.ArgumentParser(add_help=True, description=__doc__)
    ap.add_argument("html", help="Next Design の HTML エクスポート")
    ap.add_argument("-o", "--output", required=True, help="出力する中間 JSON のパス")
    ap.add_argument(
        "--encoding",
        default=None,
        help="入力の文字コード。省略時は utf-8 -> cp932 の順に試す",
    )
    try:
        args = ap.parse_args(argv[1:])
    except SystemExit:
        return 2

    encodings = [args.encoding] if args.encoding else ["utf-8", "utf-8-sig", "cp932"]
    text = None
    last_err = None
    for enc in encodings:
        try:
            with open(args.html, "r", encoding=enc) as f:
                text = f.read()
            break
        except UnicodeDecodeError as e:
            last_err = e
        except OSError as e:
            print(f"ERROR  入力を読み込めない: {e}")
            return 1
    if text is None:
        print(f"ERROR  文字コードを判別できない: {last_err}")
        return 1

    parser = NextDesignHTMLParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception as e:  # HTMLParser は壊れた入力でも例外を投げうる
        print(f"ERROR  HTML のパースに失敗: {e}")
        return 1

    result = {
        "source": args.html,
        "title": parser.title,
        "sections": parser.sections,
    }
    try:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"ERROR  出力を書き込めない: {e}")
        return 1

    n_tables = sum(len(s["tables"]) for s in parser.sections)
    n_images = sum(len(s["images"]) for s in parser.sections)
    print(f"抽出: 見出し {len(parser.sections)} / 表 {n_tables} / 図 {n_images}")
    print(f"出力: {args.output}")
    if n_tables == 0:
        print(
            "WARN   表が1つも取れていない。エクスポートの出力詳細度を確認するか、"
            "本文の段落から読み取ること"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
