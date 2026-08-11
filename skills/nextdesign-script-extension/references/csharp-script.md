# C# スクリプトの実装

E3 で読む。スクリプト方式は環境構築が不要な代わりに、**デバッガが使えず、コンパイルエラーが実行時まで表面化しない**。書き方の制約はそこから来ている。

- [エントリポイントの制約](#エントリポイントの制約)
- [ハンドラの署名](#ハンドラの署名)
- [グローバルオブジェクト](#グローバルオブジェクト)
- [using 文](#using-文)
- [ログと例外処理](#ログと例外処理)
- [頻出の落とし穴](#頻出の落とし穴)

## エントリポイントの制約

- `manifest.json` の `main` に指定できるファイルは**1つだけ**。全ハンドラをそのファイルに実装する。**ファイル分割はできない**
- スクリプトはクラス宣言を書かない。**トップレベルにメソッドを並べる**形になる
- スクリプトが読み込まれてコンパイルされるのは、**そのハンドラが最初に呼ばれたとき**。Next Design 起動時ではない
- スクリプトの変更は**再起動するまで反映されない**

```csharp
using NextDesign.Core;
using NextDesign.Desktop;

// コマンドハンドラ
public void RunCheck(ICommandContext context, ICommandParams parameters)
{
    // 処理
}

// 補助メソッドも同じファイルに並べる
private int CountErrors(IProject project)
{
    return 0;
}
```

## ハンドラの署名

`manifest.json` で参照した関数は、この署名で実装する。**引数の型と順序を変えない。**

| 種別 | 署名 |
|---|---|
| コマンド | `public void 関数名(ICommandContext context, ICommandParams parameters)` |
| イベント | `public void 関数名(IEventContext context, IEventParams eventParams)` |

関数名は `manifest.json` の `execFunc`（またはイベントのハンドラ名）と**完全一致**させる。綴りが違うと、ボタンを押しても**何も起きない**。エラーも出ない。`validate_manifest.py` はこの不一致を ERROR として検出する。

## グローバルオブジェクト

スクリプト内では次のオブジェクトを宣言なしで使える。

| 名前 | 型 | 用途 |
|---|---|---|
| `App` | `IApplication` | アプリケーション全体への入口 |
| `Context` | `IContext` | 実行コンテキスト |
| `Errors` | `IErrors` | エラー情報の登録と参照 |
| `Output` | `IOutput` | 出力ウィンドウへのログ |
| `Search` | `ISearchManager` | 検索 |
| `Window` | `IWorkspaceWindow` | ウィンドウ |
| `Workspace` | `IWorkspace` | ワークスペース |
| `CurrentProject` | `IProject` | 現在のプロジェクト |
| `CurrentModel` | `IModel` | 選択中のモデル |
| `EditorPage` | `IEditorPage` | エディタページ |
| `ViewDefinitions` | `IViewDefinitions` | ビュー定義 |
| `UI` | `ICommonUI` | ダイアログなどの基本 UI |

ハンドラの第1引数 `context` からも同じものに辿れる（`context.App` など）。**どちらか一方に統一して書く。** 混在させると、後で読む人がスコープを誤解する。

```csharp
public void RunCheck(ICommandContext context, ICommandParams parameters)
{
    var project = App.Workspace.CurrentProject;
    if (project == null)
    {
        App.Window.UI.ShowInformationDialog("プロジェクトを開いてください", "検査");
        return;
    }
    Output.WriteLine("MyExtension", string.Format("対象: {0}", project.Name));
}
```

**`CurrentProject` が `null` になる場合を必ず想定する。** `application` ライフサイクルではプロジェクトを開いていない状態でボタンを押せてしまう。

## using 文

C# スクリプトは `using` を自動で補わない。使った型に対する `using` を自分で書く。

```csharp
using NextDesign.Core;
using NextDesign.Desktop;
using NextDesign.Extension;
using System;
using System.Collections.Generic;
using System.Linq;
```

**`using` 不足は `application` ライフサイクルで Next Design 自体を起動不能にする。** 公式ドキュメントに明記された挙動で、しかもエラーメッセージが出ない。実装を終えたら、使った型を一通り見直して `using` の棚卸しをすること。

`System.IO` や `System.Text` など、標準ライブラリを使うときも同様に書く。

## ログと例外処理

デバッガが使えないので、**ログが唯一の手がかり**になる。

```csharp
public void RunCheck(ICommandContext context, ICommandParams parameters)
{
    try
    {
        Output.WriteLine("MyExtension", "検査を開始します");
        // 処理
        Output.WriteLine("MyExtension", "検査が完了しました");
    }
    catch (Exception e)
    {
        Output.WriteLine("MyExtension", string.Format("エラー: {0}", e.Message));
        App.Window.UI.ShowInformationDialog(e.Message, "検査でエラーが発生しました");
    }
}
```

守ること:

- 失敗しうる処理（ファイル I/O、外部プロセス起動、モデルの探索、型変換）は try/catch で受ける
- **例外を握りつぶさない。** `catch` して何も出さないと、無反応にしか見えず原因に辿り着けない
- `Output.WriteLine` の第1引数はカテゴリ。**拡張機能名で固定する**と、出力ウィンドウで自分のログを絞り込める
- 進行が長い処理は、開始と終了の両方をログに出す。どこで止まったか分かる

## 頻出の落とし穴

| 症状 | 原因 |
|---|---|
| Next Design が起動しない | `using` 不足、または `manifest.json` の構文エラー・キー誤り。`application` ライフサイクルで起きやすい |
| リボンに何も出ない | マニフェストの `extensionPoints.ribbon` の誤り。ID の重複、`orderBefore` の参照先が存在しない |
| ボタンを押しても無反応 | `execFunc` と関数名の不一致。または `catch` して何も出していない |
| ボタンを押すと初めてエラーが出る | 正常。スクリプトは**初回呼び出し時にコンパイルされる** |
| 直したのに変わらない | Next Design を再起動していない。**編集は再起動するまで反映されない** |
| イベントが呼ばれない | イベント名の綴り違い（黙って無視される）、またはフィルタの `class` が対象と合っていない |
| 動作が重くなった | イベントフィルタが `*` になっている。対象クラスを絞る |
| `CurrentProject` で例外 | プロジェクトが開かれていない。`null` チェックを入れる |

**ドキュメントで存在を確認できない API を推測で書かない。** `docBase` 配下の API リファレンス（`api/intro` から辿る）で確認できないメンバーは、ユーザーに問う。存在しないメンバーを書いても、コンパイルエラーが出るのはハンドラを最初に押したときで、原因の切り分けに時間を取られる。
