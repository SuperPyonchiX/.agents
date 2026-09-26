---
name: repo-agent-bootstrap
description: 新規・既存リポジトリへ Claude / Codex 共通の指示・スキル配布・検証を導入する。「リポジトリを作って」「プロジェクトを新規作成して」「共通ハーネスを導入して」「Claude と Codex の運用を揃えて」で使う。通常のコード修正は対象外。指示内容の全面診断・監査は agents-md-advisor。
metadata:
  web-description: 新規・既存リポジトリへ Claude / Codex 共通の指示・スキル配布・検証を導入する。「リポジトリを作って」「共通ハーネスを導入して」「両エージェントの運用を揃えて」で使う。
---

# 共通ハーネスの導入

Windows PowerShell 5.1 または PowerShell 7 を使う。手順は **対象確認 → 調査・統合 → 導入 → 検証**。
このスキルはユーザー共通で保持し、導入先へは日常運用に必要なファイルだけ配布する。

## 1. 対象を確定する

依頼の対象ルートを絶対パスで確定する。新規作成の依頼ならプロジェクト作成作業の中で対象ディレクトリを用意する。
単なるコード修正で未導入に気づいても、自動で追加しない。
プロジェクト作成の技術選定、Git リモート作成、モデル・権限設定、自動ジョブのエンジン切替はこのスキルの担当外。

## 2. 調査して既存内容を統合する

- 対象に適用される指示、Git 差分、AGENTS.md、CLAUDE.md、両スキル置き場、Tools の同名ファイル、ビルド・テスト・CIを読む。
- 個人設定や認証情報をプロジェクト指示へコピーしない。ユーザー個人用スキル全体も配布しない。
- リポジトリ内の対象パスにリンクがあれば、実体への移行方針を確認する。リンクを辿って書き換えない。
- CLAUDE.md の共通指示は AGENTS.md へ移す。Claude 固有の指示は `.claude/project-notes.md` に保存し、CLAUDE.md に `@.claude/project-notes.md` を残す。移動に伴う相対参照も修正する。
- AGENTS.md がなく、CLAUDE.md が共通指示だけなら、導入スクリプトによる全文の移動を使う。
- 両方に独自指示がある場合は意味を読んで統合する。既存の内容を保持し、矛盾がある箇所だけ原文と推奨案を示して判断を求める。全面監査は依頼された場合に agents-md-advisor を使う。
- 同名スキルの異内容ファイルは差分を読み、統合結果を決める前に同期しない。両版の意図が両立しなければ判断を求める。同一内容・片側だけのファイルは導入スクリプトで統合できる。
- 既存の同名ツールが別実装なら、置換による機能差を示して確認する。強制上書きしない。
- このリポジトリに実在するビルド・テストコマンドだけを AGENTS.md へ記載する。未選定ならコマンドを捏造しない。MQL5 固有規約や自動 push／PR 方針を流用しない。

## 3. 導入する

導入前に [Install-AgentHarness.ps1](scripts/Install-AgentHarness.ps1) を `-Check` で実行する。
これは変更予定の表示と衝突検出であり、導入済み状態の検証ではない。

```powershell
& <スキルの場所>/scripts/Install-AgentHarness.ps1 -RepoRoot D:/work/project -Check
& <スキルの場所>/scripts/Install-AgentHarness.ps1 -RepoRoot D:/work/project
```

通常実行は不足分の作成と共通運用節の追記を行い、最後にハーネス検査を実行する。
衝突は書き込み前に止める。I/O 障害による途中失敗は巻き戻さず、変更一覧を確認して再実行する。
既存の独自指示や変更済みツールは雛形で再初期化しない。同一バージョンの再実行は差分ゼロにする。
導入先に存在する共通運用節を更新する場合は、節を読んで必要な差分だけ編集する。

導入時に使う資産:

| 資産 | 配布先・用途 |
|---|---|
| [AGENTS.section.md](assets/AGENTS.section.md) | AGENTS.md に追記する日常運用 |
| [CLAUDE.md](assets/CLAUDE.md) | Claude の入口 |
| [AgentHarness.Common.ps1](assets/Tools/AgentHarness.Common.ps1) | Tools 配下のパス・リンク検証共通処理 |
| [Sync-AgentSkills.ps1](assets/Tools/Sync-AgentSkills.ps1) | 正本から配布物を生成。-Check は変更せず不一致で失敗 |
| [Test-AgentHarness.ps1](assets/Tools/Test-AgentHarness.ps1) | 入口・スキル構造・同期状態の検査 |

スキルの正本は `.agents/skills/`、生成物は `.claude/skills/`。両方を Git 管理する。
ゼロスキルでも正常とし、空の置き場は .gitkeep で残す。サンプルスキルは作らない。
生成物だけにファイルが残り正本が空なら同期は失敗し、自動削除しない。
正本がある通常の同期では、正本にない配布ファイルを削除するため、初回は必ず統合後に配布物扱いへ移す。

## 4. 検証する

```powershell
powershell -NoProfile -File Tools/Test-AgentHarness.ps1
# PowerShell 7 では powershell を pwsh に置換する。
```

各スクリプトは成功時 0、不整合・衝突・I/O 障害時はパスと理由を含む例外で非 0。
Sync と Test の RepoRoot は省略時に Tools の親。Install は対象の絶対パスが必須。
Sync の RelativePath は正本にある1ファイルだけを同期するための任意引数。

- 既存のテスト入口や CI があれば検査を組み込む。既存の PowerShell 実行基盤がない CI では pwsh を利用できるジョブを用意する。CI がなければコマンドの文書化で完了とする。
- Git 管理対象が ignore されていないか確認する。強制 add で回避せず、対象を限定した ignore 設定の調整を行う。
- 導入を再実行し、独自指示とファイル内容・更新日時に不要な差分がないことを確認する。
- 検証失敗は該当箇所だけ修正し、最大3周まで再検査する。同じ失敗が続いたら原因を見直す。解消しなければ残件を明示して止める。
- 可能なら両エージェントの新規セッションで入口とプロジェクトスキルの認識を確認する。未実施の実機検証を成功扱いしない。

完了は、ハーネス検査合格・再実行で不要な差分なし・対象ファイルが Git 管理可能であること。
変更対象、実行した検証、両エージェントで確認できた範囲を報告する。

## このスキルを変更したとき

[回帰テスト](scripts/test_bootstrap.py) を実行する。Python 3 の標準ライブラリのみを使い、一時ディレクトリで検証する。

```powershell
python <スキルの場所>/scripts/test_bootstrap.py --shell powershell
python <スキルの場所>/scripts/test_bootstrap.py --shell pwsh
```

終了コード 0 が合格、テスト失敗は 1。選択した PowerShell がなければ実行できないことを報告する。
両ランタイムの検査と workflow-skill-architect の validate_skill.py、skill-creator の quick_validate.py を通す。
