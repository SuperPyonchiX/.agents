# 単体テスト設計書

- 対象設計: <Next Design 詳細設計書名 / HTML パス>
- 設計インデックス: `work/design-index.json`
- 作成日: <YYYY-MM-DD>

## 対象範囲

| クラス | 対象関数数（public） | 備考 |
|---|---|---|
| <ClassName> | <n> | |

## テスト環境

| 項目 | 内容 |
|---|---|
| フレームワーク | GoogleTest / gmock |
| ビルド | CMake（C++14, `-Wall -Wextra -Werror`） |
| 実行 | ctest |
| カバレッジ | <取得する場合はツール名 / しない場合は「取得しない（理由）」> |

## テスト観点一覧

すべての列を埋める。検討したうえで不要と判断した区分は空欄にせず「該当なし（理由）」と書く。

| テストID | 対象関数 | 区分 | 観点 | 事前条件 | 入力 | 期待結果 | 根拠 |
|---|---|---|---|---|---|---|---|
| UT_<Class>_<Func>_001 | <Class>::<Func> | 正常 | 有効値を設定できる | Initialize() が true | speed=100 | 戻り値 true、GetTargetSpeed() が 100 | @retval true |
| UT_<Class>_<Func>_002 | <Class>::<Func> | 境界 | 上限値を受け付ける | Initialize() が true | speed=kMaxSpeed | 戻り値 true、GetTargetSpeed() が kMaxSpeed | 引数の有効範囲 |
| UT_<Class>_<Func>_003 | <Class>::<Func> | 境界 | 上限超過を拒否する | Initialize() が true | speed=kMaxSpeed+1 | 戻り値 false、GetTargetSpeed() が変化しない | @retval false |
| UT_<Class>_<Func>_004 | <Class>::<Func> | 異常 | 未初期化での呼び出しを拒否する | なし（Initialize 未実行） | speed=100 | 戻り値 false | @pre |
| UT_<Class>_<Func>_005 | <Class>::<Func> | 相互作用 | 依存先を1回だけ呼ぶ | Initialize() が true | speed=100 | ISensor::Read() が1回、IDriver::Apply(100) がその後に1回 | シーケンス図「<図名>」 |

## 網羅状況

| 対象関数 | 正常 | 境界 | 異常 | 相互作用 |
|---|---|---|---|---|
| <Class>::<Func> | 1 | 2 | 1 | 1 |
| <Class>::<Func2> | 1 | 該当なし（引数なし） | 該当なし（失敗経路なし） | 該当なし |

## 未確定事項

期待結果が設計から決まらなかったもの。フェーズ4に進む前にユーザーの確認を得る。

| 対象関数 | 決まらない点 | 確認したいこと |
|---|---|---|
| <Class>::<Func> | 事前条件違反時の振る舞いが設計に無い | false を返すのか、アサートで停止するのか |
