"""Notion のページを作成・アーカイブする。

使い方:
    python notion_page.py create --data-source-id <ds-id> --properties <JSON|ファイル> \
        [--blocks <JSON|ファイル>] [--icon <絵文字>]
    python notion_page.py archive --page-id <page-id>

- --properties / --blocks は JSON リテラルでもファイルパスでもよい（{ や [ で始まれば JSON と解釈）
- blocks が100個を超える場合は自動で分割追送する（APIの1リクエスト100ブロック制限を吸収）
- archive はゴミ箱送り（復元可能）。完全削除は実装していない
- トークンは環境変数 NOTION_TOKEN。プロパティ値の形は references/api-guide.md を参照

終了コード: 0=成功（作成したページの id と url を JSON で標準出力へ）
            1=API エラー / 2=引数・トークン不備
"""
import argparse
import json
import sys

from notion_http import load_json_arg, request


def cmd_create(args):
    properties = load_json_arg(args.properties, dict)
    blocks = load_json_arg(args.blocks, list) if args.blocks else []
    payload = {
        "parent": {"type": "data_source_id", "data_source_id": args.data_source_id},
        "properties": properties,
    }
    if args.icon:
        payload["icon"] = {"type": "emoji", "emoji": args.icon}
    if blocks:
        payload["children"] = blocks[:100]
    page = request("POST", "/v1/pages", payload)
    for i in range(100, len(blocks), 100):
        request("PATCH", "/v1/blocks/{}/children".format(page["id"]),
                {"children": blocks[i:i + 100]})
    print(json.dumps({"id": page["id"], "url": page.get("url")}, ensure_ascii=False))


def cmd_archive(args):
    page = request("PATCH", "/v1/pages/{}".format(args.page_id), {"archived": True})
    print(json.dumps({"id": page["id"], "archived": page.get("archived")}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Notion ページの作成・アーカイブ")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="データソースにページを1件作成する")
    p_create.add_argument("--data-source-id", required=True)
    p_create.add_argument("--properties", required=True,
                          help="プロパティの JSON（リテラルまたはファイルパス）")
    p_create.add_argument("--blocks", help="本文ブロック配列の JSON（md2blocks.py の出力）")
    p_create.add_argument("--icon", help="ページアイコンにする絵文字1つ")
    p_create.set_defaults(func=cmd_create)

    p_archive = sub.add_parser("archive", help="ページをアーカイブする（復元可能）")
    p_archive.add_argument("--page-id", required=True)
    p_archive.set_defaults(func=cmd_archive)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
