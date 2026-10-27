# はじめに

作業ブランチを最新の main に追従させる。作業はコマンド4回である。

# 手順

## ステップ1：リモートの変更を取り込む

```bash
git fetch origin
```

完了条件: エラーが出ずにプロンプトに戻る。

## ステップ2：main の上に積み直す

```bash
git rebase origin/develop
```

完了条件: `Successfully rebased` と表示される。

## ステップ3：作業ブランチを送る

```bash
git push --force-with-lease
```

完了条件: `git status` が `up to date` を示す。
