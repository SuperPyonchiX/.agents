# DLL 方式の開発手順

E0 で DLL 方式に決まったら、E3 の前に読む。Visual Studio を使わず、.NET SDK（dotnet CLI）と VS Code で開発する前提で書いてある。

**ここに書いた値（TargetFramework、NuGet の版）は V3.x で実機確認したもの。** V4.x 以降では `docBase` + `docs/getting-started/dev-with-vs/create-vs-project` を読んで値を確かめ、雛形を書き換えてから使う。V3.x の値を他の版へ流用しない。

## スクリプトとの違い

公式マニュアル（`docBase` + `docs/overview/script-and-dlls`）の比較表の要点。

| 項目 | スクリプト | DLL |
|---|---|---|
| 処理性能 | 高 | 高（同じ） |
| 初回呼び出し時のコンパイル待ち | あり | なし |
| ユーザー操作をトリガとするイベント、条件付き書式、動的制約、独自 UI | 不可 | 可 |
| 補完・デバッガ | 不可 | 可（VS Code の「C#」拡張でも可） |
| 利用者によるソースの確認・改変 | 可 | 不可 |
| スクリプトエディタでの即時実行 | 可 | 不可 |
| 必要な環境 | なし | .NET SDK |

ハンドラのコード（署名・API の呼び方）は両方式で共通。違うのは、エントリが `IExtension` を実装したクラスになること、ファイルを分けられること、ビルドが要ることの3つ。

## 方式を尋ねるときの判断材料

E0 で新規作成の方式を尋ねるとき、要件に照らして次の表から推奨を1つ示す。

| DLL を推奨する条件（1つでも当てはまれば） | スクリプトを推奨する条件 |
|---|---|
| DLL でしかできない機能を使う（上の表） | 利用者にソースを見せたい・直させたい |
| コードが大きくなる見込みがある（数千行規模） | 小さく試したい |
| 補完やデバッガを使いたい | .NET SDK を導入できない |

**DLL 専用の機能が要件にあるなら、スクリプトを選ばせない。** その旨を伝えて DLL に決める。

## 開発環境（Visual Studio なし）

初回だけ行う。環境構築を案内するときは `references/dll-license.md` の要点（商用利用で費用がかからないこと、Visual Studio のライセンスに依存しないこと）を必ず添える。

1. .NET SDK を入れる。LTS の最新（2026年9月時点では .NET 10、サポートは2028年11月14日まで）を選ぶ。新しい SDK でも古い TargetFramework 向けにビルドできる
   - 管理者権限あり: `winget install Microsoft.DotNet.SDK.10` か、`https://dotnet.microsoft.com/download` のインストーラー
   - 管理者権限なし: 公式スクリプト `https://dot.net/v1/dotnet-install.ps1` を `-Channel 10.0 -InstallDir "$env:LOCALAPPDATA\Microsoft\dotnet"` で実行し、ユーザー環境変数 PATH に追加する
   - 利用状況の送信を止めたい場合は、ユーザー環境変数 `DOTNET_CLI_TELEMETRY_OPTOUT=1`
   - 新しいターミナルで `dotnet --list-sdks` に表示されれば完了
2. VS Code に「C#」拡張（`ms-dotnettools.csharp`）を入れる。**「C# Dev Kit」は入れない**（理由は `references/dll-license.md`）
3. C# 拡張が「spawn UNKNOWN」の通知を出したら、ユーザー設定（JSON）に次を足し、自動ダウンロードの代わりに入れた SDK を使わせる。path は SDK の場所に合わせる

   ```json
   "dotnetAcquisitionExtension.existingDotnetPath": [
     { "extensionId": "ms-dotnettools.csharp", "path": "C:\\Program Files\\dotnet\\dotnet.exe" }
   ]
   ```

## プロジェクトの構成

```
<拡張機能名>/
    <拡張機能名>.csproj   ← assets/templates/dll/Extension.csproj.template
    manifest.json         ← main は "<拡張機能名>.dll"
    <拡張機能名>.cs       ← assets/templates/dll/Extension.cs.template（エントリクラス）
    その他の .cs          ← 自由に分けてよい
    resources/            ← 画像。csproj で出力へコピーする
```

- **ソースのディレクトリと配置先を分ける。** 配置先（extensions フォルダ）に置くのは publish の出力だけ
- `IExtension` を実装したクラスはプロジェクト全体で1つだけ。`Activate` / `Deactivate` は処理が無くても空で実装する
- `execFunc` とイベントハンドラは、エントリクラスの **public メソッド**にする
- `using` は各 `.cs` に書くか、csproj の `<Using Include="..." />`（global using）にまとめる。`validate_manifest.py` はどちらも見る
- 名前空間とエントリクラスを同名にしない（型名の解決があいまいになる）

## スクリプトから DLL へ移す

既存のスクリプト拡張を DLL にするときの手順。スクリプトのトップレベルに書いたハンドラは、C# スクリプトの中では暗黙のクラスのメンバーなので、それを明示的なクラスに置き換えるのが中心になる。

1. トップレベルのメソッド（ハンドラと、ハンドラから呼ぶ private メソッド）を `public partial class <拡張機能名>Extension { ... }` で包む。複数のファイルや箇所に分かれていても partial でまとめられる。トップレベルのクラスはそのまま残す（入れ子にすると、他のクラスから名前で参照できなくなる）
2. エントリの `.cs` に `public partial class <拡張機能名>Extension : IExtension` と空の `Activate` / `Deactivate` を置く
3. スクリプトでは先頭の `using` が全体に効いていた。ファイルを分けるなら、csproj の `<Using Include="..." />`（global using）にまとめるのが手早い
4. csproj では `EnableDefaultCompileItems` を false にし、`<Compile Include>` を記載順に並べる。既定の取り込みのままだと、tests/ の `.cs` まで混ざる。ほかの拡張と共有するソースは、正本のパスをそのまま `Include` する（コピーしない）
5. スクリプトのグローバル（`App` / `UI` / `Output` / `CurrentProject` など）を使っていたら、`context.App` 経由に書き換える
6. `manifest.json` の `main` を `<拡張機能名>.dll` にする。同梱するフォルダ（スキル、テンプレートなど）は csproj で出力へコピーする。実行時の拡張フォルダは `context.ExtensionInfo.ExtensionPath` で取れ、DLL 方式でも配置先を指す
7. 配置先に残ったスクリプト版の `main.cs` は、退避してから外す

## ビルド

プロジェクトディレクトリの親で実行する。

```powershell
dotnet publish <拡張機能名> -c Release -o <出力先>
```

- 既定は NuGet の `NextDesign.Core` / `NextDesign.Desktop` を参照する。V3.x では NuGet の最新が 3.1.3 で、これでビルドした DLL が V3.1.9 で動くことを確認済み
- `-p:NextDesignDir="<Next Design のインストール先>"` を付けると、インストール先の DLL を直接参照する。NuGet の版より新しい API を使うとき、nuget.org に接続できないときに使う
- 初回は TargetFramework 向けの参照パックを nuget.org から取得する。接続できない環境では、接続できる PC でビルドしたときにできる `%USERPROFILE%\.nuget\packages\` の `microsoft.netcore.app.ref` / `microsoft.windowsdesktop.app.ref` / `microsoft.aspnetcore.app.ref` の nupkg（V3.x なら 6.0.36）を持ち込み、`-p:RestoreSources="<置いたフォルダ>"` と `-p:NextDesignDir` を付けてビルドする

## 検証と配置

1. 配置する前に publish の出力を検査する

   ```
   python scripts/validate_manifest.py <プロジェクトディレクトリ> --nd-version <メジャー番号> --publish-dir <出力先>
   ```

2. Next Design を終了してから、出力の中身だけを `%LOCALAPPDATA%\DENSO CREATE\Next Design\extensions\<拡張機能名>\` へコピーする。**DLL は Next Design 実行中は差し替えられず、起動時にしか読み込まれない**
3. `NextDesign.Core.dll` / `NextDesign.Desktop.dll` を配置先に置かない（本体と競合する）。雛形の csproj は出力から外している

## デバッグ（未確認）

VS Code の「C#」拡張で、起動中の Next Design にアタッチできるはず。`.vscode/launch.json` に `"type": "coreclr", "request": "attach", "processId": "${command:pickProcess}"` の構成を置き、`NextDesign.exe` を選ぶ。実機では未確認なので、ユーザーに案内するときはそう伝える。

## よくある失敗

| 症状 | 原因 | 対処 |
|---|---|---|
| `MSB1009: プロジェクト ファイルが存在しません` | `dotnet publish <名前>` を、その名前のフォルダが無い場所（配置先など）で実行した | プロジェクトディレクトリの親で実行する |
| C# 拡張が「spawn UNKNOWN」「.NET SDK が見つかりません」 | 拡張が自動ダウンロードしたランタイムを起動できない（原因は環境依存で未特定） | 上の `existingDotnetPath` を設定する。直らなければ Windows セキュリティの保護の履歴を確認する |
| 直接参照のビルドで `MSB3277`（WindowsBase の版競合） | WPF のフレームワーク参照が無い | csproj に `FrameworkReference Include="Microsoft.WindowsDesktop.App.WPF"`（雛形には入っている） |
| リボンが出ない | 配置先に DLL が無い（ソースだけ置いた、出力の下位フォルダに置いた） | `--publish-dir` で出力を検査し、出力の中身を配置先の直下へコピーする |
| 差し替えが反映されない | Next Design 実行中にコピーした | 終了してからコピーし、起動し直す |
