# レビュー記録

- 対象: <プロジェクト / クラス名>
- 設計インデックス: `work/design-index.json`

状態が `open` の指摘が1件でも残っている間は完了としない。
`accepted`（逸脱承認）にできるのは**ユーザーの了承を得たときだけ**。自分で承認しない。

## 指摘一覧

| ID | フェーズ | 対象 | 指摘 | 重大度 | 状態 | 対応/理由 |
|---|---|---|---|---|---|---|
| RV-001 | P1 | MotorController::Shutdown | @retval が false のみで、成功時の戻り値が未定義 | 高 | fixed | 設計を確認し @retval true と成立条件を追記 |
| RV-002 | P1 | MotorController::Update | @sideeffect がない。内部状態を変えるのか読み取れない | 中 | fixed | @sideeffect current_speed_ を更新する、を追記 |
| RV-003 | P2 | MotorController::SetSpeed | @retval false の成立条件「範囲外」に対応する分岐が実装にない | 高 | fixed | 範囲検査を追加した |
| RV-004 | P2 | motor_controller.cpp:88 | マジックナンバー 3000 が直書き | 低 | accepted | ハードウェア固有の固定値。定数化すると意味が薄れるためユーザー了承のうえ据え置き |
| RV-000 | P1 | 全体 | 指摘なし | — | fixed | review-gates.md の「1. 関数設計レビュー」を全項目適用 |

## 集計

| フェーズ | 指摘 | fixed | accepted | open |
|---|---|---|---|---|
| P1 | 2 | 2 | 0 | 0 |
| P2 | 2 | 1 | 1 | 0 |
| P3 | 0 | 0 | 0 | 0 |

## 逸脱承認（accepted）の一覧

P3 の最終レビューで**全件を理由付きで提示する**。

| ID | 対象 | 承認した理由 | 承認者 |
|---|---|---|---|
| RV-004 | motor_controller.cpp:88 | ハードウェア固有の固定値のため | <ユーザー名 / 日付> |
