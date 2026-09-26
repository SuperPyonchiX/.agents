# DLL 方式の開発環境とライセンス

DLL 方式の開発環境（Visual Studio なし）を案内するとき、およびユーザーがライセンスを気にしたときに読む。2026年9月に各ライセンスの原文を確認した内容。**ここに書いたのは条文を読んだうえでの判断で、組織の法務・ソフトウェア管理部門の判断に代わるものではない。** ユーザーにもそう伝える。

## 結論

Visual Studio のライセンスが無くても、次の組み合わせで商用の拡張開発ができる。どれも費用はかからない。

| 用途 | ツール | ライセンス | 商用開発 |
|---|---|---|---|
| ビルド | .NET SDK（dotnet CLI） | Windows 版は .NET Library License（ソースコードは MIT） | 可 |
| 参照パック | Microsoft.NETCore.App.Ref ほか（NuGet） | MIT | 可 |
| エディタ | VS Code | Microsoft Software License Terms | 可 |
| 補完・デバッグ | VS Code の「C#」拡張（`ms-dotnettools.csharp`） | 配布物は Microsoft C# Extension の条項（ソースは MIT） | 可 |
| 使わない | VS Code の「C# Dev Kit」（`ms-dotnettools.csdevkit`） | Community License | 商用で開発者6名以上は Visual Studio Professional 以上が必要 |

## 根拠

| 対象 | 原文 | 出典 |
|---|---|---|
| .NET 全般 | "There are no licensing costs, including for commercial use." | https://dotnet.microsoft.com/platform/free |
| .NET SDK（Windows） | "On Windows: .NET Library License" | https://github.com/dotnet/core/blob/main/license-information.md |
| 同 第1条 | "You may install and use any number of copies of the software to develop and test your applications."（SDK 同梱の LICENSE.txt は "to design, develop and test your programs."） | https://dotnet.microsoft.com/dotnet_library_license.htm |
| ビルドした DLL | "Binaries produced by .NET SDK compilers can be redistributed without additional restrictions" | license-information.md |
| 参照パック | nupkg の定義が MIT（WindowsDesktop は同梱 LICENSE が MIT License 本文） | 各 nupkg の nuspec |
| VS Code 第1条 | "You may use any number of copies of the software to develop and test your applications, including deployment within your internal corporate network." | https://code.visualstudio.com/license |
| C# 拡張 | "You may only use the C# Extension for Visual Studio Code with Visual Studio Code, Visual Studio or Xamarin Studio software to help you develop and test your applications." | https://github.com/dotnet/vscode-csharp/blob/main/RuntimeLicenses/license.txt |
| C# Dev Kit | "For commercial purposes, teams of up to 5 can also use the C# Dev Kit at no cost. For 6+ developers, those users will need a Visual Studio Professional (or higher) subscription." | https://code.visualstudio.com/docs/csharp/cs-dev-kit-faq |

注意点:

- .NET Library License の禁止事項は、リバースエンジニアリング、技術的制限の回避、SDK そのものを第三者へ共有・公開・貸与すること。SDK は各自が Microsoft から入手させる
- .NET SDK・VS Code とも、条項で利用状況の送信が定められている。SDK は `DOTNET_CLI_TELEMETRY_OPTOUT=1` で止められる
- Next Design 本体の使用許諾契約は確認していない。拡張から `NextDesign.Core.dll` 等を参照するのは公式マニュアルの DLL 開発手順が前提にしている使い方だが、契約の条文では裏を取っていない
- NuGet の `NextDesign.Core` / `NextDesign.Desktop` にはライセンス表記が無く、"DENSO CREATE INC. All rights reserved." のみ

## 上司・情シスへの説明

ユーザーが「どう説明すればいいか」と聞いたら、次を渡す。

- 口頭では「.NET SDK は Microsoft が無償で出している開発キットで、ライセンスは .NET Library License。プログラムの開発・テストのためなら何台に入れてもよく、商用利用も費用がかからないと公式に明記されている。Visual Studio とは別の製品で、Visual Studio のライセンスには依存しない」
- いちばん強いエビデンスは、インストールした SDK に同梱の `LICENSE.txt`（`C:\Program Files\dotnet\LICENSE.txt`、ユーザーフォルダに入れた場合は `%LOCALAPPDATA%\Microsoft\dotnet\LICENSE.txt`）。実際に同意したライセンスそのもので、Web の記載が変わっても影響しない。Web の出典は日付付きで PDF かスクリーンショットに残させる
- 「法的に100%問題ない」とは言わせない。「条文上は問題ないと判断した。根拠はこれ」と伝え、最終判断は組織のソフトウェア管理部門に承認をもらう形にする
