# manifest.json の仕様

E1・E2 で読む。記載は V5.x のドキュメントを基準にしている。**バージョン差異のある項目は `references/doc-map.md` の差異表を必ず確認する。**

- [全体構造](#全体構造)
- [エクステンション定義のキー](#エクステンション定義のキー)
- [拡張ポイント: ribbon](#拡張ポイント-ribbon)
- [拡張ポイント: commands](#拡張ポイント-commands)
- [拡張ポイント: events](#拡張ポイント-events)
- [ID の命名規約](#id-の命名規約)
- [多言語対応](#多言語対応)

## 全体構造

拡張機能ディレクトリの直下に、`manifest.json` という名前で**ちょうど1つ**置く。UTF-8 で保存する。

```
myExtension/
  manifest.json
  main.cs
  locale.ja.json     （多言語対応する場合）
  locale.en.json     （同上）
  resources/
    button.png
```

```json
{
  "name": "MyExtension",
  "version": "1.0.0",
  "publisher": "組織名",
  "main": "main.cs",
  "lifecycle": "project",
  "extensionPoints": {
    "ribbon": { "tabs": [] },
    "commands": [],
    "events": {}
  }
}
```

`extensionPoints` の3つのキーは、使うものだけ書けばよい。

## エクステンション定義のキー

| キー | 必須 | 値 | 意味 |
|---|---|---|---|
| `name` | ○ | 文字列 | 全エクステンションで一意な名前。ID の接頭辞にも使う |
| `main` | ○ | ファイル名 | エントリポイント。スクリプト方式では `main.cs`。**1つしか指定できない** |
| `lifecycle` | ○ | `application` / `project` | 有効な期間 |
| `displayName` | | 文字列 | 表示名 |
| `description` | | 文字列 | 説明 |
| `icon` | | パス | アイコン画像 |
| `version` | | セマンティックバージョン | 拡張機能自体のバージョン |
| `publisher` | | 文字列 | 提供者 |
| `license` | | 文字列 | ライセンス表記 |
| `homepage` | | URL | 参照先 |
| `categories` | | 文字列の配列 | 分類 |
| `env` | | オブジェクト | 動作環境の要件 |
| `runtime` | | オブジェクト | ランタイム設定 |
| `baseprofile` / `baseProfile` | | プロファイル名 | 対象プロファイル。`project` ライフサイクルのみ。**綴りがバージョンで異なる** |
| `extensionPoints` | | オブジェクト | 拡張ポイント定義 |

`lifecycle` の選び方:

| 値 | 有効な期間 | 使いどころ |
|---|---|---|
| `application` | Next Design の起動から終了まで | プロジェクトに依存しない機能。常にリボンに出す |
| `project` | プロジェクトを開いている間 | プロジェクトのモデルを扱う機能 |

**`application` は事故のコストが高い。** マニフェストの誤りや `using` 不足が、Next Design 自体の起動失敗に直結する。迷ったら `project` を選ぶ。

## 拡張ポイント: ribbon

階層は `tabs` → `groups` → `controls` の3段。

```json
"ribbon": {
  "tabs": [
    {
      "id": "MyExtension.MainTab",
      "label": "My Extension",
      "orderBefore": "System.View",
      "groups": [
        {
          "id": "MyExtension.CheckGroup",
          "label": "検査",
          "controls": [
            {
              "id": "MyExtension.RunCheckButton",
              "type": "Button",
              "label": "検査する",
              "description": "モデルの整合性を検査します",
              "imageLarge": "resources/check32.png",
              "command": "MyExtension.Command.RunCheck"
            }
          ]
        }
      ]
    }
  ]
}
```

制御の種類（`type`）:

| type | 用途 |
|---|---|
| `Button` | コマンドを実行する。アイコンを付けられる |
| `CheckBox` | オン/オフを持つ。`isChecked` で状態を束ねる |
| `Separator` | 区切り線 |
| `ButtonGroup` | ボタンを横に並べる入れ物 |
| `StackPanel` | 縦に積む入れ物。**最大3つまで** |
| `Menu` | ドロップダウンメニューの入れ物 |
| `SplitButton` | ボタンとドロップダウンの組み合わせ |

共通のプロパティ:

| キー | 意味 |
|---|---|
| `id` | **リボン全体で一意**。必須 |
| `label` | 表示文字列。`%リソース名%` でロケールファイルを参照できる |
| `visible` | `"true"` / `"false"`。既定は表示 |
| `orderBefore` / `orderAfter` | 兄弟要素の ID を指定して位置を決める |
| `command` | Button などが実行するコマンドの ID |
| `imageSmall` / `imageLarge` | PNG のパス。それぞれ 16x16 / 32x32 が目安 |
| `isEnabled` | 有効/無効を束ねるプロパティ |
| `description` | ツールチップ |

位置指定を省略した場合、タブはヘルプタブの手前、それ以外は兄弟要素の末尾に付く。

**既存の要素 ID を書くと、新規作成ではなく既存要素へのマージになる。** Next Design 本体のタブにグループを足したいときは意図的にこれを使うが、そうでなければ必ず `<name>.` を接頭辞にして衝突を避ける。本体の ID は `docs/manifest/ribbon-ids` にある。

## 拡張ポイント: commands

```json
"commands": [
  { "id": "MyExtension.Command.RunCheck", "execFunc": "RunCheck" }
]
```

| キー | 意味 |
|---|---|
| `id` | コマンドの識別子。リボンの `command` から参照される |
| `execFunc` | `main.cs` 側の関数名。**完全一致させる** |

UI が要らないコマンド（他から呼ばれるだけ）は `commands` だけ定義すればよい。

## 拡張ポイント: events

Next Design 内部の操作に反応する。

```json
"events": {
  "project": [
    { "onBeforeSave": "ProjectOnBeforeSave" }
  ],
  "models": [
    { "class": "Function", "onAfterNew": "FunctionOnAfterNew" }
  ]
}
```

購読できるイベント（領域ごと）:

| 領域 | イベント名 |
|---|---|
| `application` | `onAfterStart`, `onBeforeQuit` |
| `commands` | `onBeforeExecute`, `onAfterExecute` |
| `project` | `onAfterNew`, `onBeforeOpen`, `onAfterOpen`, `onBeforeSave`, `onAfterSave`, `onBeforeClose`, `onAfterClose`, `onBeforeReload`, `onAfterReload`, `onAfterModelUnitLoad` |
| `models` | `onBeforeNew`, `onAfterNew`, `onFieldChanged`, `onBeforeDelete`, `onBeforeChangeOwner`, `onAfterChangeOwner`, `onBeforeChangeOrder`, `onAfterChangeOrder`, `onBeforeNewRelation`, `onAfterNewRelation`, `onValidate`, `onError`, `onSelectionChanged`, `onModelEdited`, `onUndoRedo` |
| `editors` / `pages` / `navigators` / `information` | `onShow`, `onHide`, `onSelectionChanged` など |

**イベント名は必ず該当バージョンの `docs/manifest/extension-points/events` で存在を確認する。** 綴り違いは黙って無視されるだけで、エラーにならない。

イベントフィルタ（拾う範囲を絞る）:

| 領域 | フィルタキー | 値 |
|---|---|---|
| `models` | `class` | クラス名、完全修飾名、`*`。カンマ区切りで複数可 |
| `commands` | `commandId` | 対象コマンドの ID |
| `editors` | `viewDefinition` | ビュー定義名 |
| `navigators` | `navigator` | `Model` / `ProductLine` / `Scm` / `Project` / `Profile` / `*` |
| `information` | `information` | `Error` / `SearchResult` / `Output` / `*` |

**フィルタを `*` にすると、モデルを1つ触るたびにハンドラが呼ばれる。** 応答性が落ちるので、対象クラスが決まっているなら必ず指定する。

## ID の命名規約

守るのは3つ。`validate_manifest.py` が全部を機械判定する。

1. リボン要素の `id` は**リボン全体で一意**。必ず `<name>.` を接頭辞にする
2. `controls[].command` は `commands[].id` のいずれかと**完全一致**
3. `commands[].execFunc` とイベントハンドラ名は、`main.cs` の関数名と**完全一致**

推奨する形:

```
<name>.MainTab                 タブ
<name>.<用途>Group             グループ
<name>.<用途>Button            制御
<name>.Command.<動詞>          コマンド
```

## 多言語対応

`label` に `%リソース名%` と書き、拡張機能ディレクトリ直下に `locale.ja.json` / `locale.en.json` を置く。ロケールファイルが無いのに `%...%` を使うと、その記法がそのまま画面に出る。`validate_manifest.py` はこの組み合わせを WARN として報告する。
