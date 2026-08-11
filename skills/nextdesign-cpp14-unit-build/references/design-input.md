# 詳細設計インプットの読み取り

P0 で、渡された詳細設計を `work/design-index.json` に正規化するときに読む。

- [入力形式の判別と経路](#入力形式の判別と経路)
- [複数形式が混在する場合](#複数形式が混在する場合)
- [経路A: HTML エクスポート](#経路a-html-エクスポート)
- [経路B: CSV / Excel](#経路b-csv--excel)
- [経路C: PlantUML](#経路c-plantuml)
- [経路D: Markdown / テキスト](#経路d-markdown--テキスト)
- [経路E: 画像](#経路e-画像)
- [全経路共通: 対応づけの手がかり](#全経路共通-対応づけの手がかり)
- [design-index.json の組み立て](#design-indexjson-の組み立て)

## 入力形式の判別と経路

**出力はどの経路でも `work/design-index.json` の1つに揃える。** 後続フェーズは入力形式を一切意識しない。ここが唯一の吸収層である。

| 形式 | 判別 | 経路 | 精度 |
|---|---|---|---|
| HTML エクスポート | `.html` / `.htm` | A. `scripts/extract_nextdesign_html.py` で中間JSON化してから意味づけ | 高 |
| CSV | `.csv` | B. 直読して列名で対応づけ | 高 |
| Excel | `.xlsx` / `.xls` | B. **CSV 保存を依頼する**（直読しない） | — |
| PlantUML | `.puml` / `.pu` / `@startuml` を含む | C. 直読して構文から抽出 | **最高** |
| Markdown / テキスト | `.md` / `.txt` / 会話への貼り付け | D. 直読 | 中 |
| 画像 | `.png` / `.jpg` / スクリーンショット | E. 読み取り後、**全件ユーザー確認必須** | 低 |

判別できない場合、**推測して進めずユーザーに形式を尋ねる**。

### どの経路でも守ること

- 読み取れなかった項目は、勝手に既定値（`int` など）で埋めず `"unknown"` を入れ、`open_questions` に積む
- `open_questions` が空でない状態で P1 に進まない
- 取り込み結果は必ず一覧にしてユーザーに提示し、スコープの合意を得る

## 複数形式が混在する場合

実務では「クラス図は画像、関数一覧は Excel、シーケンスは PlantUML」のように混ざる。すべて取り込んで統合する。

**矛盾したときの優先順位**（上が勝つ）:

1. PlantUML / 明示的な表（CSV・HTML の表）— 構造化されており解釈の余地が最も小さい
2. 本文テキストの記述
3. 画像からの読み取り

優先順位で機械的に決めてよいのは**表記の揺れ**まで。**意味が食い違う場合（型が違う、引数の数が違う、戻り値が違う）は自動で解決せず、両方を併記して `open_questions` に積み、ユーザーに判断を仰ぐ。**

## 経路A: HTML エクスポート

Next Design の HTML エクスポートは、モデルの構成に応じて出力が変わる。**章立てもテーブルの列名も固定ではない**。したがって「決まった位置から決まった値を取る」パースはできない。

そこで役割を分ける。

| 担当 | やること |
|---|---|
| `scripts/extract_nextdesign_html.py` | 見出し階層・表・図まわりのテキストを、構造を保ったまま JSON に落とす。**意味づけはしない** |
| エージェント（この工程） | 中間 JSON を読み、下記の対応づけの手がかりに従って `work/design-index.json` を組み立てる |

複数ファイルに分割されている場合は、ファイルごとに実行して `work/raw-export-<n>.json` に分けて出力してから統合する。

### 中間 JSON の形

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

## 経路B: CSV / Excel

**Excel (.xlsx) は直読しない。** 読むには外部パッケージが要り、移植性の規約に反する。次のようにユーザーへ依頼する。

> 設計を CSV で保存し直して渡してください（Excel で「名前を付けて保存」→ CSV UTF-8）。
> シートが複数ある場合は、クラス一覧・操作一覧・シーケンス一覧をそれぞれ別ファイルにしてください。

CSV は直読して、下の「対応づけの手がかり」の列名候補で対応づける。注意点。

- 1行目が見出し行とは限らない。タイトル行・空行が上にあることがある。**見出しらしい行を探してから読む**
- セル内改行や区切り文字を含む値はダブルクォートで囲まれている。素朴な `split(",")` はしない
- 1つのクラスの関数が複数行にわたる場合、クラス名列が空欄の行は直前の値の継続とみなす（マージセルの名残）。この解釈をしたことはユーザーへの提示に含める

## 経路C: PlantUML

**最も精度の高い経路。** 他形式と併用できる場合はこれを優先する。テキストなので取りこぼしがほぼ無い。

クラス図から取る:

```plantuml
class MotorController {
    - target_speed_ : int32_t
    + Initialize() : bool
    + SetSpeed(speed : int32_t) : bool
    - Clamp(value : int32_t) : int32_t
}
MotorController --> "1" ISpeedSensor
```

| 記法 | 対応 |
|---|---|
| `+` / `#` / `-` | `visibility` = public / protected / private |
| `名前(引数 : 型) : 戻り値型` | `functions[]` のシグネチャ |
| `{static}` / `{abstract}` | 静的関数 / 純粋仮想。`{abstract}` と `interface` 内の操作は `is_pure_virtual: true` にする |
| `-->` `--` `*--` `o--` と `"1"` `"0..1"` `"0..*"` | `dependencies[]` と `multiplicity` |
| `<|--` | `base_classes` |

シーケンス図から取る:

```plantuml
App -> MotorController : Initialize()
MotorController -> ISpeedSensor : Reset()
alt 失敗
  MotorController --> App : false
end
```

- `A -> B : call()` の並び順が `sequences[].steps[].order`
- `alt` / `opt` / `loop` の条件は `note` に残す。**ここが異常系のテスト観点になる**ので落とさない
- `activate` / `deactivate` は無視してよい

## 経路D: Markdown / テキスト

表があれば「対応づけの手がかり」の列名候補で当てる。文章のみの場合は次の形を探す。

- 「〜クラスは、〜する」→ クラスの `brief`
- 「引数 speed（0〜10000）」→ 引数名と `range`。**範囲の記述は境界値テストの材料なので必ず拾う**
- 「〜の場合は false を返す」→ `return_values[]`
- 「〜を呼ぶ前に Initialize() を実行しておくこと」→ `preconditions[]`

文章からの抽出は解釈が入る。**抽出結果は全件をユーザーに提示して確認を得る。**

## 経路E: 画像

図を読み取って `design-index.json` に落とす。**この経路は誤読が起きる前提で扱う。**

1. 画像を読める環境かを確認する。読めない場合は**そこで止まり**、PlantUML かテキストでの提供をユーザーに依頼する。無理に進めない。
2. 読み取った内容を、クラスごとに**全件表にしてユーザーに提示し、承認を得る**。ここは「確認を得たこと」を完了条件にする。
3. 判読できない文字（潰れた小さい文字、重なった線）は推測せず `"unknown"` にする。
4. 図に描かれていない情報（引数の有効範囲、エラー時の戻り値）は画像からは取れない。**取れないことを明示して**ユーザーに補足を求める。

## 全経路共通: 対応づけの手がかり

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

PlantUML 以外の経路では、シーケンス図は画像として出ることが多く、呼び出し順を機械的に取れない。次の順に探す。

1. 図の直後・直前の表（`メッセージ一覧` `シーケンス` 等）— あればここから呼び出し順を取る
2. 本文の箇条書き — 「1. A が B の X() を呼ぶ」形式なら取れる
3. 画像のみ — 経路E に従って読み取り、**全件ユーザーに提示して確認を得る**
4. どちらも無い — **呼び出し順は未確定とし、ユーザーに提示して確認する**

シーケンスから取れるのは主に次の3つで、いずれもテスト観点の材料になるので落とさない。

- 呼び出しの順序（事前に呼ばれていなければならない関数がある＝事前条件）
- 依存先クラス（P3 でモック化する対象。`dependencies[].mockable` に反映する）
- 分岐・ループ・代替フロー（異常系のテスト観点になる）

### 静的構造（関連・多重度）

関連の多重度は、依存の持ち方（値 / 参照 / ポインタ / コンテナ）とライフタイムの判断材料になる。`0..1` は「未設定状態が正当に存在する」の意味なので、その状態を叩くテスト観点を必ず起こす。

## design-index.json の組み立て

スキーマは `assets/templates/design-index.schema.json` にある。要点だけ。

- `functions[].id` は `<クラス名>::<関数名>` を基本とし、オーバーロードがある場合は `<クラス名>::<関数名>(<引数型のカンマ区切り>)` にする。**この ID が以降の全工程の突合キー**になるので、途中で変えない。
- 型が読み取れなかった項目は、勝手に `int` などで埋めず `"unknown"` を入れ、`open_questions` に積む。
- `open_questions` が空でない状態で P1 に進まない。必ずユーザーに提示する。
- `source` には、取り込んだ入力を全部書く（複数形式を統合した場合はカンマ区切りで列挙する）。

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

P0 の最後に、この形で提示して合意を取る。取り込み元の形式と、その形式ゆえの信頼度を明示すること。

```
取り込み結果（入力: design.html + sequence.puml + class_diagram.png）:
  クラス 4件 / 関数 27件（public 18 / private 9）
  - MotorController : 8関数（HTML の表から取得）
  - SpeedSensor     : 5関数（HTML の表から取得）
  - PowerManager    : 6関数（画像から読み取り。要確認）
  ...

カバレッジ目標: C0 100% / C1 100%（計測は gcovr を使用）

確認が必要な点:
  - MotorController::Calibrate の引数の型が読み取れませんでした（"unknown"）
  - PowerManager は画像からの読み取りのため、全関数のシグネチャをご確認ください
  - Shutdown() の戻り値が HTML の表では void、画像では bool と食い違っています

この範囲で実装を進めてよいか確認してください。
```

## 想定外への対処

| 状況 | 対処 |
|---|---|
| 入力形式が判別できない | 推測せずユーザーに尋ねる |
| 関数シグネチャが1つも取れない | より詳細な形式での再出力をユーザーに依頼して止まる |
| 表が無く本文の文章のみ | 経路D で抽出を試み、結果を全件ユーザーに提示して確認を得る |
| 画像を読める環境でない | 止まって、PlantUML かテキストでの提供を依頼する |
| 同名クラスが複数の階層にある | 見出し階層やパッケージ名で判別し、`namespace` フィールドに入れて区別する |
| 形式間で内容が食い違う | 自動で解決せず、両方を併記して `open_questions` に積みユーザーに判断を仰ぐ |
| 設計が途中までしかない | 取れた範囲だけをスコープとして提示し、合意を得てから進む。欠けている部分を推測で補わない |
