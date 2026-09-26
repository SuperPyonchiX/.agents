# バージョン別ドキュメント対応表

E0 で読む。Next Design の拡張機能ドキュメントは**バージョンごとに独立したサイト**として公開されており、URL 基点が違うだけでなく**仕様そのものが違う**。バージョンを確定せずに書いたマニフェストは、動かないだけでなく Next Design を起動不能にしうる。

## ドキュメント基点

| バージョン | `docBase` | 備考 |
|---|---|---|
| V5.x | `https://docs.nextdesign.app/extension/` | 現行版。バージョン指定なしの URL は常にここを指す |
| V4.x | `https://docs.nextdesign.app/extension/v4.x/` | |
| V3.x | `https://docs.nextdesign.app/extension/v3.x/` | **C# のみ。Python の記載が無い** |
| V2.x | `https://www.nextdesign.app/support/documents/2.0/extension/` | サイトの構造が別系統。ページ構成が下表と対応しない |
| V1.1 | `https://www.nextdesign.app/support/documents/1.1/extension/` | 同上 |

V5.x のページ構成を基準にすると、V4.x / V3.x は `docBase` に同じ相対パスを繋げばおおむね同じページに届く。V2.x 以前は構成が違うので、**サイト内を辿って該当ページを探す**。

## いつどのページを読むか

相対パスは `docBase` に繋いで使う。例: V3.x でマニフェスト構造を見るなら
`https://docs.nextdesign.app/extension/v3.x/docs/manifest/manifest-json`。

| 相対パス | 読むタイミング |
|---|---|
| `docs/overview/intro` | 拡張機能の全体像を確認したいとき |
| `docs/overview/extension-points` | E1。拡張ポイントの3分類 |
| `docs/manifest/extension` | E2。エクステンション定義のキー一覧 |
| `docs/manifest/manifest-json` | E2。マニフェスト全体の構造 |
| `docs/manifest/extension-points/ribbon` | E2。リボン制御の種類とプロパティ |
| `docs/manifest/extension-points/commands` | E2。コマンド定義 |
| `docs/manifest/extension-points/events` | E2。購読できるイベント名とイベントフィルタ |
| `docs/manifest/ribbon-ids` | E2。既存タブ・グループへ差し込むときの ID |
| `docs/manifest/schema` | E2。マニフェストのスキーマファイル |
| `docs/tutorials/hello-world` | 最小構成を確認したいとき |
| `api/intro` | E3。API の全体構成 |
| `docs/getting-started/dev-with-scripts/...` | E3・E4。スクリプト開発の手順とデバッグ（V4.x 以降。V3.x はパスが異なるので目次から辿る） |

**ネットワークが使えない場合**は `references/manifest-spec.md` と `references/csharp-script.md` の記載を使う。ただしそれらは V5.x のドキュメントを基準に書いてあるので、下の差異表に載っている項目は**ユーザーに確認する**。

## 確認済みのバージョン差異

現物のドキュメントで確認した差分だけを載せる。**ここに無い項目も違う可能性がある。**

| 項目 | V3.x | V4.x / V5.x |
|---|---|---|
| スクリプト言語 | **C# のみ**（`main.cs`） | C#（`main.cs`）と Python（`main.py`） |
| プロファイル指定キー | `baseprofile`（全て小文字） | `baseProfile` / `baseProfiles`（V5.x で確認） |
| `onActivate` / `onDeactivate` | **無い** | ある（Python 用） |
| `runtime` / `env` | ある | ある |

`validate_manifest.py` はこの表に基づいて `--nd-version` ごとに許可キーを切り替える。**V3.x なのに `--nd-version` を省略すると、既定の 5 が適用されて `baseProfiles` などが素通りする。**

## バージョンが確定しないとき

「たぶん最新」「わからない」は確定ではない。次を案内して待つ。

> Next Design の ヘルプ > バージョン情報 でバージョンを確認できます。

それでも分からない場合は**先に進まない**。推測で最新版を仮定して書いたマニフェストが、古いバージョンで Next Design を起動不能にするのが最悪のケースで、しかもエラーが出ないので原因に辿り着けない。

## 拡張機能の配置先

バージョンによらず共通。

| 配置先 | 適用範囲 |
|---|---|
| `%LOCALAPPDATA%\DENSO CREATE\Next Design\extensions\` | そのユーザーのみ |
| `C:\ProgramData\DENSO CREATE\Next Design\extensions\` | そのPCの全ユーザー |

この直下に拡張機能ごとのディレクトリを作り、`manifest.json` とスクリプトを置く。`AppData` と `ProgramData` は隠しフォルダである。
