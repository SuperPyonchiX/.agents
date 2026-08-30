"""Notion REST API の共通処理。notion_page.py / notion_query.py から import される。

単体では実行しない。トークンは環境変数 NOTION_TOKEN から読む。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

API_BASE = "https://api.notion.com"
NOTION_VERSION = "2025-09-03"

TOKEN_GUIDE = """NOTION_TOKEN が設定されていません。次の手順で設定してください。
1. https://www.notion.so/profile/integrations でインテグレーションを作成し、トークンを発行する
2. Notion 側で対象ページ / データベースの「接続」にそのインテグレーションを追加する
3. 環境変数 NOTION_TOKEN に設定する（PowerShell の例）
   [Environment]::SetEnvironmentVariable('NOTION_TOKEN', 'ntn_xxxx', 'User')
   設定後はシェルを開き直す"""


def get_token():
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        print(TOKEN_GUIDE, file=sys.stderr)
        sys.exit(2)
    return token


def request(method, path, payload=None):
    """API を1回呼び、レスポンス JSON を返す。429 は Retry-After に従い最大2回リトライ。

    失敗時はエラー内容を stderr に出して終了コード1で止まる。
    """
    token = get_token()
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": "Bearer " + token,
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    for attempt in range(3):
        req = urllib.request.Request(API_BASE + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 429 and attempt < 2:
                time.sleep(float(e.headers.get("Retry-After", "2")))
                continue
            print("API error {}: {}".format(e.code, body), file=sys.stderr)
            sys.exit(1)
        except urllib.error.URLError as e:
            print("接続エラー: {}".format(e.reason), file=sys.stderr)
            sys.exit(1)


def load_json_arg(value, expect_type):
    """引数が JSON リテラルならパースし、そうでなければファイルパスとして読む。"""
    text = value
    stripped = value.lstrip()
    if not (stripped.startswith("{") or stripped.startswith("[")):
        try:
            with open(value, encoding="utf-8-sig") as f:
                text = f.read()
        except OSError as e:
            print("ファイルを読めません: {}".format(e), file=sys.stderr)
            sys.exit(2)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        print("JSON のパースに失敗: {}".format(e), file=sys.stderr)
        sys.exit(2)
    if not isinstance(obj, expect_type):
        print("JSON の型が不正です（期待: {}）".format(expect_type.__name__), file=sys.stderr)
        sys.exit(2)
    return obj
