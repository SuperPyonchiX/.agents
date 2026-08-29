# 外部から取り込んだスキル

`skills/` にある**他者が著作権を持つスキル**の出典と扱いを記録する。
追加・更新・削除したら必ずここも直す。判断基準は AGENTS.md の「外部から取り込んだスキル（vendoring）」にある。

**このリポジトリは公開されている。** 再配布を許可されていないものはコミットしない。

## コミットしているもの

ライセンスが再配布を許可しており、`skills/<name>/LICENSE` に全文を同梱しているもの。

### show-me

| | |
|---|---|
| 出典 | https://github.com/humanlayer/skills/tree/main/plugins/show-me/skills/show-me |
| ライセンス | MIT（Copyright (c) 2026 HumanLayer）。全文は `skills/show-me/LICENSE` |
| 取得時のコミット | `6ab9013a10c28f5046f7f999549cd5328a0b30d7`（2026-08-13） |
| 取得日 | 2026-08-29 |
| 改変 | **あり**（下記） |

改変したのは frontmatter だけで、本文は上流のまま英語で保持している。

- `description` を日本語に差し替えた。上流は英語のみで、日本語の依頼では発火しないため。あわせて `markdown-explanation-doc` との棲み分けを1文追加
- `metadata.web-description` を追加（claude.ai の 200 文字制限用。このリポジトリ独自の仕組み）
- `license: MIT` を追加

## コミットしていないもの

ライセンスが無い、または再配布の許諾が確認できないもの。**`.gitignore` で除外し、手元にだけ置く。**
新しい環境では git clone だけでは入らないので、下の「再取得」に従って各自で入れ直す。

### obsidian

| | |
|---|---|
| 出典 | YouTube 動画の特典として配布されたもの https://www.youtube.com/watch?v=TU8DSyuMto4 |
| ライセンス | **付与されていない。** 既定の著作権が働き、再配布の許諾は無い |
| 扱い | `.gitignore` で `skills/obsidian/` を除外。**コミットしない** |
| 取得日 | 2026-08-29 時点で手元にあることを確認 |
| 改変 | あり（Windows 対応、プレースホルダ展開、`agents/` の移設） |

改変の内訳:

- `agents/vault-page-reviewer.md` を削除し、内容を `references/page-review.md` へ移した（Claude Code のサブエージェント機能への依存を外すため。AGENTS.md の移植性の規約）
- `{{VAULT_PATH}}` `{{VAULT_ID}}` `{{VAULT_NAME}}` を自環境の値へ展開
- CLI 本体・設定ファイル・トラブルシュートを Windows 向けに修正。`_SETUP.md` に OS 差の表を追加
- デイリーノートの位置を実測値（`01_日記/YYYY-MM-DD.md`）に修正
- `metadata.web-description` を追加

**vault 側のセットアップ（2026-08-29 実施済み）**: このスキルは vault 内の設定にも依存する。
新しい環境では `_SETUP.md` の Phase 6・7 をやり直すこと。

| 項目 | 状態 |
|---|---|
| `.obsidian/snippets/rich-vault.css` | `assets/rich-vault.css` からコピー済み |
| `.obsidian/appearance.json` の `enabledCssSnippets` | `["rich-vault"]` |
| コアプラグイン | `daily-notes` / `bases` / `file-recovery` いずれも有効 |

**`_SETUP.md` と `_CONFIG.md` は削除しない。** Phase 10 は setup 後の削除を指示しているが、
このスキルは git に含めていないため、消すと新しい環境で再構築する手がかりが無くなる。

**再取得**: 配布元の動画特典から入手し直す。取得後に上の改変を当て直し、vault 側のセットアップも行う。
**コミットしたくなったら**: 先に配布者へ再配布の可否を確認する。許諾が取れたら、その旨とライセンス表記を
`skills/obsidian/LICENSE` に置き、`.gitignore` から外して SKILL.md の frontmatter に `license:` を足す。

## ラッパースクリプト（リポジトリ外）

`obsidian` スキルは PATH 上のラッパーに依存する。これはリポジトリの管理対象外なので、環境ごとに作る。

| ファイル | 用途 |
|---|---|
| `~/.local/bin/obsidian.cmd` | PowerShell・cmd 用 |
| `~/.local/bin/obsidian` | Git Bash 用 |

作り方は `skills/obsidian/references/cli-commands.md` の「再セットアップ手順」にある。
