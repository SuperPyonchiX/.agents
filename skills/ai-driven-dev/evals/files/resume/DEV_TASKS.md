# 開発台帳

## 作業環境

- ブランチ: main
- 開始コミット: 1111111

## 目的

csvcount に空行を読み飛ばすオプションを足す。

## 範囲外

- なし

## 受け入れ条件

- [ ] `--skip-blank` を付けると空行を数えない

## 検証コマンド

| 種類 | コマンド |
|---|---|
| テスト | `python -m unittest discover -s tests` |
| lint・型検査 | なし |
| ビルド | なし |
| 起動確認 | `python csvcount.py README.md` が終了コード 0 |

## タスク

状態は 未着手 / 進行中 / 完了 / 保留 / 中止 のどれか。進行中は同時に1件まで。

| ID | タスク | 完了条件 | 状態 | 証拠 | コミット |
|---|---|---|---|---|---|
| T1 | count_rows に空行除外の引数を足す | `test_skip_blank` が通る | 完了 | RED: AssertionError / GREEN: 2 passed | 0000000 |
| T2 | CLI に --skip-blank を足す | `test_cli_skip_blank` が通る | 未着手 | | |

## 経緯

- 2026-11-27 台帳を作成
