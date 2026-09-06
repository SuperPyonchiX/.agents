"""Notion のデータソースを読む（スキーマ取得・クエリ・ページ本文の読み戻し）。

使い方:
    python notion_query.py schema --data-source-id <ds-id>
        → プロパティ定義（select / multi_select は選択肢一覧つき）を JSON で出力
    python notion_query.py query --data-source-id <ds-id> [--filter <JSON|ファイル>] [--compact]
        → 全件をページネーションを回して取得し、結果配列を JSON で出力。
          --compact は id・url・アイコン・プロパティの値だけに間引く（一覧確認用）
    python notion_query.py blocks --page-id <page-id>
        → ページ直下のブロック配列を JSON で出力（投稿後の読み戻し検証用）

- トークンは環境変数 NOTION_TOKEN。フィルタの書式は references/api-guide.md を参照
- すべて読み取り専用。書き込みは notion_page.py が担当

終了コード: 0=成功 / 1=API エラー / 2=引数・トークン不備
"""
import argparse
import json
import sys

from notion_http import load_json_arg, request


def cmd_schema(args):
    ds = request("GET", "/v1/data_sources/{}".format(args.data_source_id))
    print(json.dumps(ds.get("properties", {}), ensure_ascii=False, indent=1))


def compact_value(prop):
    t = prop.get("type")
    v = prop.get(t)
    if t == "title" or t == "rich_text":
        return "".join(x.get("plain_text", "") for x in (v or []))
    if t == "select":
        return v.get("name") if v else None
    if t == "multi_select":
        return [x.get("name") for x in (v or [])]
    if t == "date":
        return v.get("start") if v else None
    if t in ("url", "checkbox", "number", "email", "phone_number", "created_time",
             "last_edited_time"):
        return v
    return v


def cmd_query(args):
    payload = {"page_size": 100}
    if args.filter:
        payload["filter"] = load_json_arg(args.filter, dict)
    results = []
    while True:
        res = request("POST", "/v1/data_sources/{}/query".format(args.data_source_id), payload)
        results.extend(res.get("results", []))
        if not res.get("has_more"):
            break
        payload["start_cursor"] = res["next_cursor"]
    if args.compact:
        results = [{"id": p["id"], "url": p.get("url"),
                    "icon": (p.get("icon") or {}).get("emoji"),
                    "properties": {k: compact_value(v)
                                   for k, v in p.get("properties", {}).items()}}
                   for p in results]
    print(json.dumps(results, ensure_ascii=False, indent=1))


def cmd_blocks(args):
    results = []
    cursor = ""
    while True:
        path = "/v1/blocks/{}/children?page_size=100".format(args.page_id)
        if cursor:
            path += "&start_cursor=" + cursor
        res = request("GET", path)
        results.extend(res.get("results", []))
        if not res.get("has_more"):
            break
        cursor = res["next_cursor"]
    print(json.dumps(results, ensure_ascii=False, indent=1))


def main():
    parser = argparse.ArgumentParser(description="Notion データソースの読み取り")
    sub = parser.add_subparsers(dest="command", required=True)

    p_schema = sub.add_parser("schema", help="プロパティ定義と選択肢一覧を取得する")
    p_schema.add_argument("--data-source-id", required=True)
    p_schema.set_defaults(func=cmd_schema)

    p_query = sub.add_parser("query", help="データソースを全件クエリする")
    p_query.add_argument("--data-source-id", required=True)
    p_query.add_argument("--filter", help="フィルタの JSON（リテラルまたはファイルパス）")
    p_query.add_argument("--compact", action="store_true", help="id・url・値だけに間引く")
    p_query.set_defaults(func=cmd_query)

    p_blocks = sub.add_parser("blocks", help="ページ直下のブロックを読み戻す")
    p_blocks.add_argument("--page-id", required=True)
    p_blocks.set_defaults(func=cmd_blocks)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
