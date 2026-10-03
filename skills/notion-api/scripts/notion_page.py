"""Notion のページを作成・アーカイブする。

使い方:
    python notion_page.py create --data-source-id <ds-id> --properties <JSON|ファイル> \
        [--blocks <JSON|ファイル>] [--icon <絵文字>] [--progress <進捗JSON>]
    python notion_page.py append --page-id <page-id> --blocks <不足分JSON> \
        --expected-count <読み戻した直下ブロック数> [--progress <進捗JSON>]
    python notion_page.py set-icon --page-id <page-id> --icon <絵文字>
    python notion_page.py archive --page-id <page-id>

- --properties / --blocks は JSON リテラルでもファイルパスでもよい（{ や [ で始まれば JSON と解釈）
- create の --icon は省略できるが、省略するとアイコンなしのページになる。一覧での見分けが
  つかなくなるので、内容に合う絵文字を必ず渡すこと。付け忘れたページは set-icon で後から直せる
- blocks が100個を超える場合は自動で分割追送する（APIの1リクエスト100ブロック制限を吸収）
- create は本文の先頭に目次ブロック（table_of_contents）を必ず入れる。blocks の先頭が既に目次なら重ねない
- archive はゴミ箱送り（復元可能）。完全削除は実装していない
- トークンは環境変数 NOTION_TOKEN。プロパティ値の形は references/api-guide.md を参照

終了コード: 0=成功（作成したページの id と url を JSON で標準出力へ）
            1=set-icon/archive・append事前読取のAPIエラー / 2=引数・トークン不備
            3=create/append送信中のAPIエラー・部分成功・結果不明・進捗保存失敗
"""
import argparse
import json
import sys
from pathlib import Path

from notion_http import load_json_arg, request

# 作成するページの先頭に必ず置く目次。見出しから Notion が自動で組み立てる
TOC_BLOCK = {"object": "block", "type": "table_of_contents", "table_of_contents": {"color": "default"}}


def save_progress(args, state):
    """stdoutは最終JSON1件。途中結果はstderrと任意のJSONファイルに残す。"""
    text = json.dumps(state, ensure_ascii=False)
    print(text, file=sys.stderr, flush=True)
    if getattr(args, "progress", None):
        path = Path(args.progress)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text + "\n", encoding="utf-8")
        tmp.replace(path)


def validate_blocks(blocks):
    if any(not isinstance(b, dict) or not isinstance(b.get("type"), str) for b in blocks):
        print("blocks はtypeを持つオブジェクトの配列にしてください", file=sys.stderr)
        raise SystemExit(2)


def send_batches(args, state, blocks, start=0):
    """結果不明のバッチはconfirmed_blocksへ加算しない。再送は自動化しない。"""
    try:
        for i in range(start, len(blocks), 100):
            state["status"] = "sending"
            state["pending_blocks"] = min(100, len(blocks) - i)
            save_progress(args, state)
            request("PATCH", "/v1/blocks/{}/children".format(state["id"]),
                    {"children": blocks[i:i + 100]})
            state["confirmed_blocks"] += state["pending_blocks"]
            state["pending_blocks"] = 0
            save_progress(args, state)
    except (Exception, SystemExit) as exc:
        print("追送または進捗保存に失敗: " + str(exc), file=sys.stderr)
        state["status"] = "partial"
        state["recovery"] = "本文を読み戻し、追加済み範囲を確認する。createや直前のバッチをそのまま再実行しない"
        try:
            save_progress(args, state)
        except OSError:
            pass  # stderrとstdoutにIDを残す。ファイル保存失敗で結果を隠さない。
        print(json.dumps(state, ensure_ascii=False), flush=True)
        raise SystemExit(3) from exc
    state["status"] = "complete"
    try:
        save_progress(args, state)
    except OSError as exc:
        print("進捗ファイルの保存に失敗: " + str(exc), file=sys.stderr)
        print(json.dumps(state, ensure_ascii=False), flush=True)
        raise SystemExit(3) from exc
    print(json.dumps(state, ensure_ascii=False), flush=True)


def cmd_create(args):
    properties = load_json_arg(args.properties, dict)
    blocks = load_json_arg(args.blocks, list) if args.blocks else []
    validate_blocks(blocks)
    if not blocks or blocks[0].get("type") != "table_of_contents":
        blocks = [TOC_BLOCK] + blocks
    payload = {
        "parent": {"type": "data_source_id", "data_source_id": args.data_source_id},
        "properties": properties,
    }
    if args.icon:
        payload["icon"] = {"type": "emoji", "emoji": args.icon}
    if blocks:
        payload["children"] = blocks[:100]
    state = {"status": "creating", "id": None, "url": None,
             "confirmed_blocks": 0, "pending_blocks": min(100, len(blocks))}
    try:
        save_progress(args, state)
    except OSError as exc:
        print("進捗ファイルを作れません: " + str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    try:
        page = request("POST", "/v1/pages", payload)
        if not isinstance(page, dict) or not page.get("id"):
            raise ValueError("作成応答にページIDがありません")
    except (Exception, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code == 2:
            raise  # トークン未設定など、リクエスト前の入力エラー
        print("作成結果を確認できません: " + str(exc), file=sys.stderr)
        state["status"] = "unknown"
        state["recovery"] = "作成結果が未確認。DBを一意キーで照合してから再試行を判断する"
        try:
            save_progress(args, state)
        except OSError:
            pass
        print(json.dumps(state, ensure_ascii=False), flush=True)
        raise SystemExit(3) from exc
    state.update(id=page["id"], url=page.get("url"),
                 confirmed_blocks=min(100, len(blocks)), pending_blocks=0)
    send_batches(args, state, blocks, start=100)


def cmd_append(args):
    blocks = load_json_arg(args.blocks, list)
    validate_blocks(blocks)
    if not blocks or args.expected_count < 0:
        print("不足分のblocksと0以上のexpected-countが必要です", file=sys.stderr)
        raise SystemExit(2)
    # 呼び出し元による内容照合後に、少なくとも件数が変わっていないことを再確認する。
    count, cursor = 0, None
    while True:
        path = "/v1/blocks/{}/children?page_size=100".format(args.page_id)
        if cursor:
            path += "&start_cursor=" + cursor
        res = request("GET", path)
        count += len(res["results"])
        if not res.get("has_more"):
            break
        cursor = res["next_cursor"]
    if count != args.expected_count:
        print("本文の件数が変わっています。読み戻して再照合してください", file=sys.stderr)
        raise SystemExit(2)
    state = {"status": "appending", "id": args.page_id, "url": None,
             "confirmed_blocks": count, "pending_blocks": 0}
    send_batches(args, state, blocks)


def cmd_set_icon(args):
    page = request("PATCH", "/v1/pages/{}".format(args.page_id),
                   {"icon": {"type": "emoji", "emoji": args.icon}})
    icon = page.get("icon") or {}
    print(json.dumps({"id": page["id"], "icon": icon.get("emoji")}, ensure_ascii=False))


def cmd_archive(args):
    page = request("PATCH", "/v1/pages/{}".format(args.page_id), {"archived": True})
    print(json.dumps({"id": page["id"], "archived": page.get("archived")}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Notion ページの作成・アイコン設定・アーカイブ")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="データソースにページを1件作成する")
    p_create.add_argument("--data-source-id", required=True)
    p_create.add_argument("--properties", required=True,
                          help="プロパティの JSON（リテラルまたはファイルパス）")
    p_create.add_argument("--blocks", help="本文ブロック配列の JSON（md2blocks.py の出力）")
    p_create.add_argument("--icon", help="ページアイコンにする絵文字1つ（内容に合うものを必ず指定する）")
    p_create.add_argument("--progress", help="途中結果のJSON保存先。親フォルダを先に作る")
    p_create.set_defaults(func=cmd_create)

    p_append = sub.add_parser("append", help="読み戻しで照合した不足分だけを追送する")
    p_append.add_argument("--page-id", required=True)
    p_append.add_argument("--blocks", required=True)
    p_append.add_argument("--expected-count", type=int, required=True,
                          help="直前に内容を照合したページ直下のブロック件数")
    p_append.add_argument("--progress", help="途中結果のJSON保存先")
    p_append.set_defaults(func=cmd_append)

    p_icon = sub.add_parser("set-icon", help="既存ページのアイコンを設定・変更する")
    p_icon.add_argument("--page-id", required=True)
    p_icon.add_argument("--icon", required=True, help="ページアイコンにする絵文字1つ")
    p_icon.set_defaults(func=cmd_set_icon)

    p_archive = sub.add_parser("archive", help="ページをアーカイブする（復元可能）")
    p_archive.add_argument("--page-id", required=True)
    p_archive.set_defaults(func=cmd_archive)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
