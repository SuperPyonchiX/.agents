# Next Design HTML エクスポートの読み取り

フェーズ0で、HTML エクスポートを `work/design-index.json` に意味づけするときに読む。

## 前提

Next Design の HTML エクスポートは、モデルの構成に応じて出力が変わる。**章立てもテーブルの列名も固定ではない**。したがって「決まった位置から決まった値を取る」パースはできない。

そこで役割を分ける。

| 担当 | やること |
|---|---|
| `scripts/extract_nextdesign_html.py` | 見出し階層・表・図まわりのテキストを、構造を保ったまま JSON に落とす。**意味づけはしない** |
| エージェント（この工程） | 中間 JSON を読み、下記の対応づけの手がかりに従って `work/design-index.json` を組み立てる |

## 中間 JSON の形

`extract_nextdesign_html.py` の出力はこの形になる。

```json
{
  "source": "design.html",
  "title": "詳細設計書",
  "sections": [
    {
      "level": 2,
      "heading": "MotorController",
      "path": ["詳細設計書", "制御", "MotorController"],
      "paragraphs": ["モータの回転数を制御するクラス。"],
      "tables": [
        {
          "caption": "操作",
          "headers": ["名前", "戻り値", "引数", "可視性", "説明"],
          "rows": [["SetSpeed", "bool", "int32_t speed", "public", "回転数を設定する"]]
        }
      ],
      "images": [{"alt": "クラス図", "src": "img/class01.png"}]
    }
  ]
}
```

`sections` は文書順に並ぶ。`path` に祖先の見出しが入るので、どのパッケージのどのクラスの話かはここで判別する。

## 対応づけの手がかり

列名は日英・表記揺れがある。次の候補で当てる。当たらない列があれば、**推測で埋めず未確定として扱う**。

| design-index の項目 | 表側の列名の候補 |
|---|---|
| クラス名 | 見出しそのもの、`名前` / `クラス名` / `Name` |
| 属性 | 表のキャプションが `属性` / `プロパティ` / `Attributes` / `Fields` |
| 操作 | 表のキャプションが `操作` / `メソッド` / `Operations` / `Methods` |
| 戻り値型 | `戻り値` / `戻り型` / `型` / `Return` / `Type` |
| 引数 | `引数` / `パラメータ` / `Parameters` / `Arguments` |
| 可視性 | `可視性` / `公開範囲` / `Visibility` / `Access` |
| 説明 | `説明` / `概要` / `備考` / `Description` |

### シーケンス図

シーケンス図は画像として出ることが多く、`images` からは呼び出し順を取れない。次の順に探す。

1. 図の直後・直前の表（`メッセージ一覧` `シーケンス` 等）— あればここから呼び出し順を取る
2. 本文の箇条書き — 「1. A が B の X() を呼ぶ」形式なら取れる
3. どちらも無い — **呼び出し順は未確定とし、ユーザーに提示して確認する**

シーケンスから取れるのは主に次の3つで、いずれもテスト観点の材料になるので落とさない。

- 呼び出しの順序（事前に呼ばれていなければならない関数がある＝事前条件）
- 依存先クラス（フェーズ4でモック化する対象）
- 分岐・ループ・代替フロー（異常系のテスト観点になる）

### 静的構造（関連・多重度）

関連の多重度は、依存の持ち方（値 / 参照 / ポインタ / コンテナ）とライフタイムの判断材料になる。`0..1` は「未設定状態が正当に存在する」の意味なので、その状態を叩くテスト観点を必ず起こす。

## design-index.json の組み立て

スキーマは `assets/templates/design-index.schema.json` にある。要点だけ。

- `functions[].id` は `<クラス名>::<関数名>` を基本とし、オーバーロードがある場合は `<クラス名>::<関数名>(<引数型のカンマ区切り>)` にする。**この ID が以降の全工程の突合キー**になるので、途中で変えない。
- 型が読み取れなかった項目は、勝手に `int` などで埋めず `"unknown"` を入れ、`open_questions` に積む。
- `open_questions` が空でない状態でフェーズ1に進まない。必ずユーザーに提示する。

最小の実例（クラス1件・関数1件）:

```json
{
  "source": "design.html",
  "generated_at": "2026-08-11T10:00:00+09:00",
  "classes": [
    {
      "name": "MotorController",
      "namespace": "control",
      "brief": "モータの回転数を制御するクラス。",
      "attributes": [
        { "name": "target_speed_", "type": "std::int32_t", "visibility": "private", "brief": "目標回転数 [rpm]。" }
      ],
      "functions": [
        {
          "id": "MotorController::SetSpeed",
          "name": "SetSpeed",
          "return_type": "bool",
          "parameters": [
            { "name": "speed", "type": "std::int32_t", "direction": "in", "range": "0..kMaxSpeed" }
          ],
          "visibility": "public",
          "is_const": false,
          "is_virtual": false,
          "brief": "目標回転数を設定する。",
          "preconditions": ["Initialize() が true を返していること"],
          "return_values": [
            { "value": "true", "meaning": "設定に成功した" },
            { "value": "false", "meaning": "speed が有効範囲外だった" }
          ]
        }
      ],
      "dependencies": [
        { "target": "ISpeedSensor", "multiplicity": "1", "mockable": true }
      ]
    }
  ],
  "sequences": [
    {
      "name": "起動シーケンス",
      "steps": [
        { "order": 1, "from": "App", "to": "MotorController", "call": "Initialize()", "note": "" },
        { "order": 2, "from": "MotorController", "to": "ISpeedSensor", "call": "Reset()", "note": "失敗したら false を返して終了" }
      ]
    }
  ],
  "open_questions": [
    { "where": "MotorController::Calibrate", "question": "引数の型が表から読み取れない" }
  ]
}
```

## ユーザーへの提示

フェーズ0の最後に、この形で提示して合意を取る。

```
取り込み結果:
  クラス 4件 / 関数 27件（public 18 / private 9）
  - MotorController : 8関数
  - SpeedSensor     : 5関数
  ...

確認が必要な点:
  - MotorController::Calibrate の引数の型が表から読み取れませんでした（"unknown"）
  - シーケンス図「起動シーケンス」の呼び出し順が画像のみで、テキストから取得できませんでした

この範囲で実装を進めてよいか確認してください。
```

## 想定外への対処

| 状況 | 対処 |
|---|---|
| 関数シグネチャが1つも取れない | エクスポート設定（出力詳細度）の確認をユーザーに求めて止まる |
| 表が無く本文の文章のみ | 文章から抽出を試み、結果を全件ユーザーに提示して確認を得る |
| 同名クラスが複数の階層にある | `path` で名前空間を判別し、`namespace` フィールドに入れて区別する |
| HTML が複数ファイルに分割されている | ファイルごとに `extract_nextdesign_html.py` を実行し、`work/raw-export-<n>.json` に分けて出力してから統合する |
