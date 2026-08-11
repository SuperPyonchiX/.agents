# レビュー記録

- 対象: <プロジェクト / クラス名>
- 設計インデックス: `work/design-index.json`

状態が `open` の指摘が1件でも残っている間は完了としない。
`accepted`（逸脱承認）にできるのは**ユーザーの了承を得たときだけ**。自分で承認しない。

## 指摘一覧

| ID | フェーズ | 対象 | 指摘 | 重大度 | 状態 | 対応/理由 |
|---|---|---|---|---|---|---|
| RV-001 | P1 | MotorController::Shutdown | @retval が false のみで、成功時の戻り値が未定義 | 高 | fixed | 設計を確認し @retval true を追記 |
| RV-002 | P1 | MotorController::Update | @pre がない。Initialize 前提かどうか読み取れない | 中 | fixed | @pre Initialize() が true を返していること、を追記 |
| RV-003 | P2 | MotorController::SetSpeed | 上限値ちょうど（kMaxSpeed）の観点がない | 中 | fixed | UT_MotorController_SetSpeed_002 を追加 |
| RV-004 | P3 | UT_MotorController_Update_007 | EXPECT_CALL が実装の呼び出し列の写しになっている | 中 | fixed | 設計が定めた順序のみに絞った |
| RV-005 | P5 | motor_controller.cpp:88 | マジックナンバー 3000 が直書き | 低 | accepted | ハードウェア固有の固定値。定数化すると意味が薄れるためユーザー了承のうえ据え置き |
| RV-000 | P1 | 全体 | 指摘なし | — | fixed | review-gates.md の「1. 関数設計レビュー」を全項目適用 |

## 集計

| フェーズ | 指摘 | fixed | accepted | open |
|---|---|---|---|---|
| P1 | 2 | 2 | 0 | 0 |
| P2 | 1 | 1 | 0 | 0 |
| P3 | 1 | 1 | 0 | 0 |
| P5 | 1 | 0 | 1 | 0 |
| P6 | 0 | 0 | 0 | 0 |

## 逸脱承認（accepted）の一覧

P6 の最終レビューで**全件を理由付きで提示する**。

| ID | 対象 | 承認した理由 | 承認者 |
|---|---|---|---|
| RV-005 | motor_controller.cpp:88 | ハードウェア固有の固定値のため | <ユーザー名 / 日付> |
