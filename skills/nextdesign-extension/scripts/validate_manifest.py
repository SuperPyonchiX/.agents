#!/usr/bin/env python3
"""Next Design スクリプト拡張機能の manifest.json を機械的に検証する。

使い方:
    python scripts/validate_manifest.py <拡張機能ディレクトリ> [--nd-version 3|4|5]

終了コード:
    0  合格（WARN のみなら合格。内容は表示する）
    1  ERROR あり
    2  引数誤り、またはディレクトリが存在しない

--nd-version は Next Design のメジャーバージョン。省略すると 5 とみなす。
**V3.x を検証するときに省略してはいけない。** V3.x に存在しないキー
（baseProfiles / onActivate / onDeactivate）が素通りする。

このスクリプトが潰しているのは、Next Design が起動不能になる原因と、
「ボタンを押しても何も起きない」の原因である。どちらもアプリ側は
エラーを出さないので、配置前にここで捕まえるしかない。

見ないもの（目視・実機確認に残る）:
  - C# の構文とコンパイル可否（Next Design 上でしか分からない）
  - API メンバーの実在（バージョン別のリファレンスを読むこと）
  - イベント名がそのバージョンに実在するか（綴り違いは黙って無視される）
  - 拡張機能が要件を満たしているか

依存は標準ライブラリのみ。引数で受け取ったパスだけで動き、
特定のディレクトリ配置を前提にしない。
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Windows のコンソールは既定が cp932 のことがあり、日本語の指摘が文字化けする。
# 検証結果が読めないと修正できないので、出力を UTF-8 に固定する。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REQUIRED_KEYS = ("name", "main", "lifecycle")
VALID_LIFECYCLES = ("application", "project")

# 全バージョン共通のトップレベルキー
COMMON_KEYS = {
    "name",
    "displayName",
    "description",
    "icon",
    "version",
    "publisher",
    "license",
    "homepage",
    "categories",
    "env",
    "runtime",
    "main",
    "lifecycle",
    "extensionPoints",
}
# バージョンごとに追加されるキー（references/doc-map.md の差異表と対応）
VERSION_KEYS = {
    3: {"baseprofile"},
    4: {"baseprofile", "baseProfile", "baseProfiles", "onActivate", "onDeactivate"},
    5: {"baseprofile", "baseProfile", "baseProfiles", "onActivate", "onDeactivate"},
}

VALID_CONTROL_TYPES = {
    "Button",
    "CheckBox",
    "Separator",
    "ButtonGroup",
    "StackPanel",
    "Menu",
    "SplitButton",
}

# イベント定義の領域名。この配下のキーのうち on で始まるものをハンドラ名とみなす
EVENT_AREAS = (
    "application",
    "commands",
    "project",
    "models",
    "editors",
    "pages",
    "navigators",
    "information",
)


class Report:
    def __init__(self):
        self.errors = []
        self.warns = []

    def error(self, where, msg):
        self.errors.append((where, msg))

    def warn(self, where, msg):
        self.warns.append((where, msg))

    def dump(self):
        for where, msg in self.errors:
            print("ERROR  {}: {}".format(where, msg))
        for where, msg in self.warns:
            print("WARN   {}: {}".format(where, msg))
        print("ERROR {} 件 / WARN {} 件".format(len(self.errors), len(self.warns)))


def load_manifest(path, rep):
    """manifest.json を読む。読めなければ None を返す。"""
    if not path.is_file():
        rep.error("manifest.json", "見つからない。拡張機能ディレクトリ直下に必要")
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        rep.error("manifest.json", "UTF-8 で読めない。UTF-8 で保存し直すこと")
        return None
    # BOM 付き UTF-8 は json が受け付けないので落とす
    raw = raw.lstrip("﻿")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        rep.error(
            "manifest.json",
            "JSON として不正 (行 {} 列 {}): {}".format(e.lineno, e.colno, e.msg),
        )
        return None
    if not isinstance(data, dict):
        rep.error("manifest.json", "最上位がオブジェクトでない")
        return None
    return data


def check_definition(data, ext_dir, nd_version, rep):
    """エクステンション定義（トップレベルのキー）を検査する。"""
    for key in REQUIRED_KEYS:
        if key not in data:
            rep.error("manifest.json", "必須キー '{}' が無い".format(key))

    allowed = COMMON_KEYS | VERSION_KEYS.get(nd_version, VERSION_KEYS[5])
    for key in data:
        if key not in allowed:
            rep.error(
                "manifest.json",
                "V{}.x で認識されないキー '{}'".format(nd_version, key),
            )

    lifecycle = data.get("lifecycle")
    if lifecycle is not None and lifecycle not in VALID_LIFECYCLES:
        rep.error(
            "manifest.json",
            "lifecycle は {} のいずれか。'{}' は不正".format(
                " / ".join(VALID_LIFECYCLES), lifecycle
            ),
        )

    main = data.get("main")
    if isinstance(main, str):
        if not main.endswith(".cs"):
            rep.error(
                "manifest.json",
                "main が '{}'。このスキルは C# スクリプト (.cs) のみを扱う".format(main),
            )
        if not (ext_dir / main).is_file():
            rep.error("manifest.json", "main が指す '{}' が存在しない".format(main))
    elif main is not None:
        rep.error("manifest.json", "main は文字列でなければならない")

    for key in ("version", "publisher", "displayName"):
        if not data.get(key):
            rep.warn("manifest.json", "'{}' が未設定".format(key))


def walk_controls(controls, path, ids, commands_used, images, types, rep):
    """リボンの controls を再帰的に辿る。入れ子の制御があるため。"""
    if not isinstance(controls, list):
        rep.error(path, "controls は配列でなければならない")
        return
    for i, ctrl in enumerate(controls):
        here = "{}[{}]".format(path, i)
        if not isinstance(ctrl, dict):
            rep.error(here, "制御はオブジェクトでなければならない")
            continue
        cid = ctrl.get("id")
        if not cid:
            rep.error(here, "id が無い。リボン要素の id は必須")
        else:
            ids.append((cid, here))
        ctype = ctrl.get("type")
        if ctype:
            types.append((ctype, here))
        if ctrl.get("command"):
            commands_used.append((ctrl["command"], here))
        for key in ("imageSmall", "imageLarge", "icon"):
            if ctrl.get(key):
                images.append((ctrl[key], "{}.{}".format(here, key)))
        # StackPanel / Menu / ButtonGroup / SplitButton は子を持つ
        if "controls" in ctrl:
            walk_controls(
                ctrl["controls"],
                "{}.controls".format(here),
                ids,
                commands_used,
                images,
                types,
                rep,
            )


def check_ribbon(ribbon, ids, commands_used, images, types, rep):
    if not isinstance(ribbon, dict):
        rep.error("extensionPoints.ribbon", "オブジェクトでなければならない")
        return
    tabs = ribbon.get("tabs", [])
    if not isinstance(tabs, list):
        rep.error("extensionPoints.ribbon.tabs", "配列でなければならない")
        return
    for ti, tab in enumerate(tabs):
        tpath = "ribbon.tabs[{}]".format(ti)
        if not isinstance(tab, dict):
            rep.error(tpath, "タブはオブジェクトでなければならない")
            continue
        if not tab.get("id"):
            rep.error(tpath, "id が無い")
        else:
            ids.append((tab["id"], tpath))
        groups = tab.get("groups", [])
        if not isinstance(groups, list):
            rep.error("{}.groups".format(tpath), "配列でなければならない")
            continue
        for gi, group in enumerate(groups):
            gpath = "{}.groups[{}]".format(tpath, gi)
            if not isinstance(group, dict):
                rep.error(gpath, "グループはオブジェクトでなければならない")
                continue
            if not group.get("id"):
                rep.error(gpath, "id が無い")
            else:
                ids.append((group["id"], gpath))
            walk_controls(
                group.get("controls", []),
                "{}.controls".format(gpath),
                ids,
                commands_used,
                images,
                types,
                rep,
            )


def collect_event_handlers(events, rep):
    """events 配下から (ハンドラ名, 位置) を集める。"""
    found = []
    if not isinstance(events, dict):
        rep.error("extensionPoints.events", "オブジェクトでなければならない")
        return found
    for area, entries in events.items():
        if area not in EVENT_AREAS:
            rep.warn(
                "extensionPoints.events",
                "'{}' は既知のイベント領域名でない。綴りを確認すること".format(area),
            )
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            rep.error("extensionPoints.events.{}".format(area), "配列でなければならない")
            continue
        for i, entry in enumerate(entries):
            here = "events.{}[{}]".format(area, i)
            if not isinstance(entry, dict):
                rep.error(here, "オブジェクトでなければならない")
                continue
            handlers = [k for k in entry if k.startswith("on")]
            if not handlers:
                rep.error(here, "on で始まるイベント名のキーが1つも無い")
            for key in handlers:
                value = entry[key]
                if not isinstance(value, str) or not value:
                    rep.error(
                        "{}.{}".format(here, key), "ハンドラ名は空でない文字列であること"
                    )
                else:
                    found.append((value, "{}.{}".format(here, key)))
    return found


def check_extension_points(data, ext_dir, rep):
    """拡張ポイントを検査し、main.cs に必要な関数名の一覧を返す。"""
    required_funcs = []
    points = data.get("extensionPoints")
    if points is None:
        rep.warn("manifest.json", "extensionPoints が無い。拡張ポイントを持たない")
        return required_funcs
    if not isinstance(points, dict):
        rep.error("extensionPoints", "オブジェクトでなければならない")
        return required_funcs

    ids = []
    commands_used = []
    images = []
    types = []

    if "ribbon" in points:
        check_ribbon(points["ribbon"], ids, commands_used, images, types, rep)

    # コマンド定義
    command_ids = set()
    commands = points.get("commands", [])
    if commands and not isinstance(commands, list):
        rep.error("extensionPoints.commands", "配列でなければならない")
        commands = []
    for i, cmd in enumerate(commands):
        here = "commands[{}]".format(i)
        if not isinstance(cmd, dict):
            rep.error(here, "コマンドはオブジェクトでなければならない")
            continue
        cid = cmd.get("id")
        if not cid:
            rep.error(here, "id が無い")
        else:
            if cid in command_ids:
                rep.error(here, "コマンド id '{}' が重複している".format(cid))
            command_ids.add(cid)
        func = cmd.get("execFunc")
        if not func:
            rep.error(here, "execFunc が無い")
        else:
            required_funcs.append((func, here))

    # リボンからのコマンド参照切れ
    for used, where in commands_used:
        if used not in command_ids:
            rep.error(
                where,
                "command '{}' に対応する commands[].id が無い".format(used),
            )

    # 参照されないコマンドは異常ではない（他から呼ぶ場合がある）ので WARN
    referenced = {c for c, _ in commands_used}
    for cid in sorted(command_ids - referenced):
        rep.warn(
            "extensionPoints.commands",
            "'{}' はリボンから参照されていない。UI から実行できない".format(cid),
        )

    # ID の重複と接頭辞
    seen = {}
    ext_name = data.get("name")
    for rid, where in ids:
        if rid in seen:
            rep.error(where, "id '{}' が {} と重複している".format(rid, seen[rid]))
        else:
            seen[rid] = where
        if ext_name and not rid.startswith("{}.".format(ext_name)):
            rep.warn(
                where,
                "id '{}' が '{}.' で始まっていない。既存要素と衝突する恐れがある".format(
                    rid, ext_name
                ),
            )

    # 制御の種類
    for ctype, where in types:
        if ctype not in VALID_CONTROL_TYPES:
            rep.error(
                where,
                "type '{}' は既知の制御でない。使えるのは {}".format(
                    ctype, " / ".join(sorted(VALID_CONTROL_TYPES))
                ),
            )

    # 画像の実在
    for img, where in images:
        if not (ext_dir / img).is_file():
            rep.error(where, "画像 '{}' が存在しない".format(img))

    # イベント
    if "events" in points:
        required_funcs.extend(collect_event_handlers(points["events"], rep))

    return required_funcs


def check_script(data, ext_dir, required_funcs, rep):
    """main.cs にハンドラが実装されているかを照合する。"""
    main = data.get("main")
    if not isinstance(main, str):
        return
    script = ext_dir / main
    if not script.is_file():
        return
    try:
        source = script.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        rep.error(main, "UTF-8 で読めない。UTF-8 で保存し直すこと")
        return

    # 行コメントとブロックコメントを落とす。コメントアウトされた雛形を
    # 実装済みと誤認しないため。
    stripped = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    stripped = re.sub(r"//[^\n]*", "", stripped)

    for func, where in required_funcs:
        pattern = r"\bvoid\s+{}\s*\(".format(re.escape(func))
        if not re.search(pattern, stripped):
            rep.error(
                where,
                "'{}' が {} に実装されていない（コメントアウトも未実装とみなす）".format(
                    func, main
                ),
            )

    if "using NextDesign" not in stripped:
        rep.warn(
            main,
            "NextDesign 名前空間の using が無い。using 不足は "
            "application ライフサイクルで Next Design を起動不能にする",
        )


def check_locale(data, ext_dir, rep):
    """label に %...% を使いながらロケールファイルが無い状態を拾う。"""
    text = json.dumps(data, ensure_ascii=False)
    if not re.search(r'"%[^"%]+%"', text):
        return
    if not list(ext_dir.glob("locale.*.json")):
        rep.warn(
            "manifest.json",
            "label に %リソース名% を使っているが locale.*.json が無い。"
            "記法がそのまま画面に出る",
        )


def main():
    parser = argparse.ArgumentParser(
        description="Next Design スクリプト拡張機能の manifest.json を検証する",
        add_help=True,
    )
    parser.add_argument("extension_dir", help="拡張機能ディレクトリ")
    parser.add_argument(
        "--nd-version",
        type=int,
        choices=(3, 4, 5),
        default=5,
        help="Next Design のメジャーバージョン（省略時 5）",
    )
    try:
        args = parser.parse_args()
    except SystemExit:
        return 2

    ext_dir = Path(args.extension_dir)
    if not ext_dir.is_dir():
        print("ERROR  引数: ディレクトリが存在しない: {}".format(ext_dir))
        return 2

    rep = Report()
    data = load_manifest(ext_dir / "manifest.json", rep)
    if data is None:
        rep.dump()
        return 1

    check_definition(data, ext_dir, args.nd_version, rep)
    required_funcs = check_extension_points(data, ext_dir, rep)
    check_script(data, ext_dir, required_funcs, rep)
    check_locale(data, ext_dir, rep)

    rep.dump()
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
