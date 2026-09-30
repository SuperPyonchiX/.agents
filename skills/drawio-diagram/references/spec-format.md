# spec.json の書き方

D0 で spec.json を書くときに読む。`layout_from_spec.py` はこの形を読んで `.drawio` を作り、`check_drawio.py --spec` は同じ spec.json を要件として図と突き合わせる。

役割分担は次のとおり。

- **線の経路はスクリプトが決める**。箱と枠の見出し帯を避ける直交経路を探し、経由点まで固定する
- **箱の位置は図の種類で決め方を分ける**。構成図・概念図・状態遷移図・クラス図・ER図はモデルが `at`・`near` で書く（`layout: "free"`）。フロー図・スイムレーン図は流れの順に自動で並べる（`layout: "grid"`）。シーケンス図はスクリプトが並べる（`layout: "sequence"`）

## 全体の形

```json
{
  "name": "ページ名",
  "layout": "free",
  "styles": {"hw": "fillColor=#f8cecc;strokeColor=#b85450"},
  "groups": [ ... ],
  "nodes":  [ ... ],
  "edges":  [ ... ],
  "order":  [ ... ]
}
```

複数ページは `{"pages": [ {1ページ分}, ... ]}` と書く。**id はページをまたいでも重複させない**（`check_drawio.py --spec` は全ページをまとめて照合する）。

| キー | 意味 |
|---|---|
| `layout` | `free`（位置をモデルが書く）/ `grid`（自動配置）/ `sequence`（シーケンス図。下の節）。省略すると、どの要素にも `at`・`near` が無ければ `grid`、あれば枠ごとに判定 |
| `direction` | grid の流れの向き。`LR`（左→右、既定）/ `TB`（上→下） |
| `lanes` | `vertical` でレーンを左右に並べ、流れを上→下にする。省略するとレーンは上下に積み、流れは左→右 |
| `gap` | `[列間, 行間]`。grid のセルの間隔。省略すると線ラベルの長さから決まる |
| `styles` | スタイルに名前を付ける。要素側の `class` で参照する |

## 枠（groups）と箱（nodes）

```json
{"id": "srv", "label": "サーバー", "kind": "box", "at": [260, 0]}
{"id": "api", "label": "API", "in": "srv", "near": {"right_of": "web"}, "class": "hw"}
```

| キー | 対象 | 意味 |
|---|---|---|
| `id` | 両方 | 英数字。線の `from`・`to` から参照する |
| `label` | 両方 | 表示する文字。改行は `<br>` |
| `in` | 両方 | 入れる枠の id。省略すると図全体の直下 |
| `kind` | 枠 | `box`（囲み枠・層。既定）/ `lane`（スイムレーン。図全体の直下にだけ置ける） |
| `shape` | 箱 | 形。下の表 |
| `at` | 両方 | `[x, y]`。**親の中身の原点**（枠なら見出し帯と余白の内側の左上、図全体なら左上）からの座標 |
| `near` | 両方 | 同じ親の中の別の要素を基準にした相対位置。下の節 |
| `pos` | 両方 | grid の `[列, 行]`（0 始まり）。省略すると自動 |
| `span` | 枠 | grid で `[列数, 行数]` にまたがらせる |
| `stack` | 枠 | grid で中身を並べる向き。`row`（既定）/ `column` |
| `size` | 両方 | `[幅, 高さ]`。箱ではラベルの長さによる自動拡張を止める。枠では最小の大きさ |
| `style` | 両方 | draw.io のスタイル文字列。既定のスタイルへ key=value 単位で上書きする |
| `class` | 両方 | `styles` の名前。文字列か配列。`class` → `style` の順に重なる |

**同じ枠の直下では、`at`/`near` と `pos`（自動）を混ぜない**（終了コード 2）。枠ごとにはそろえなくてよく、grid の枠の中身だけを `at` で置くこともできる。レーンそのものには `at` を書かない（レーンの位置は並び順で決まる）。

### shape

| 値 | 形 | 用途 |
|---|---|---|
| `process` | 角丸の四角（既定） | 処理・ブロック・部品 |
| `decision` | ひし形 | 分岐 |
| `start` / `end` | 楕円 | 開始・終了 |
| `document` | 波形の下辺 | 帳票・ファイル |
| `database` | 円柱 | DB・記憶域 |
| `external` | 破線の四角 | 外部システム |
| `actor` | 人型 | 利用者 |
| `note` | 付箋 | 補足 |
| `text` | 枠なしの文字 | 注記 |
| `state` | 丸みの強い四角 | 状態遷移図の状態 |
| `initial` / `final` | 黒丸 / 二重丸 | 状態遷移図の開始・終了。`label` は省いてよい |
| `choice` | 小さなひし形 | 状態遷移図の分岐点 |
| `class` | 見出し＋属性＋操作の区画 | クラス図。`fields`・`methods` に行を書く |
| `entity` | 見出し＋属性の区画 | ER図。`fields` に行を書く（`PK 顧客ID` など） |

`class` と `entity` の大きさは行数と最長の行から決まる（`size` の幅があればそれを使う）。

```json
{"id": "temp", "label": "TempSensor", "shape": "class",
 "fields": ["- raw_: uint16_t"], "methods": ["+ read(): int32_t"]}
```

中の行は `<箱の id>__f<番号>`（属性）・`__sep`（区切り線）・`__m<番号>`（操作）の id で出力され、draw.io 上で1行ずつ直せる。

これ以外の図形は `style` に `shape=...` を書く（`shape=cloud`、`shape=hexagon;perimeter=hexagonPerimeter2` など）。`shape=` を差し替えた箱には、線の接続点が図形の輪郭に投影されるよう自動で設定する。ただし雲形のように輪郭が外接矩形より内側に凹む図形では、矢印の先端と輪郭の間に隙間が残る（draw.io の図形側の性質）。

### near（相対位置）

```json
"near": {"right_of": "web", "gap": 80, "align": "center"}
```

- 方向は `right_of` / `left_of` / `below` / `above` のどれか1つ
- 基準は **同じ親の直下の要素**に限る。基準の位置が決まってから置くので、連鎖してよい（循環は終了コード 2）
- `gap` は基準との間隔（既定 80）。**線ラベルがある線を通すなら、ラベルの文字数 × 13 + 50 以上**あける。狭いと check_layout.py が LABEL を出す
- `align` は交差する向きのそろえ方。`start`（左端・上端）/ `center`（既定）/ `end`

### 位置を決めるときの目安

- 流れの向きを1つに決め、流れの順に左から右（または上から下）へ置く
- 線でつながる箱は隣に置く。つながらない箱を間にはさまない
- 箱の間は 80 以上あける。線ラベルがあるなら上の `gap` の目安に従う
- 座標は 10 の倍数にする。draw.io のグリッドに乗り、後から人が動かしやすい
- 線でつなぐ箱は、線の向きに中心をそろえる。幅の違う箱（開始・終了の楕円、分岐のひし形）を `at` の左端でそろえると中心がずれ、線に小さな段差が出る（check_layout.py の JOG）。縦に流すなら `near` の `below` でつなげば中心がそろう
- 迷ったら `near` を使う。`at` は、図全体の直下で基準にする要素と、`near` で言えない位置だけに使う

## 線（edges）

```json
{"from": "api", "to": "ext", "label": "決済", "from_side": "bottom", "dashed": true}
```

| キー | 意味 |
|---|---|
| `from` / `to` | 箱か枠の id。同じ id なら自己遷移（箱の角を回る輪） |
| `label` | 線のラベル |
| `dashed` | `true` で破線 |
| `both` | `true` で両端に矢印 |
| `kind` | クラス図の関係。`inherit`（汎化）/ `realize`（実現）/ `compose`（コンポジション）/ `aggregate`（集約）/ `assoc`（関連）/ `depend`（依存）。`compose`・`aggregate` は `from` が全体の側（ひし形が付く） |
| `card` | ER図の多重度 `[from 側, to 側]`。値は `1` / `0..1` / `1..*` / `0..*` / `*`。カラスの足の記号で描く |
| `from_side` / `to_side` | 出口・入口の辺。`top` / `bottom` / `left` / `right`。省略すると経路探索が選ぶ |
| `via` | `[[x, y], ...]`。経由させる点（図全体の左上からの座標）。探索は点ごとに区切って行う |
| `style` / `class` | 箱と同じ。線の色・太さ（`strokeColor=#b85450;strokeWidth=2`）など |
| `id` | 省略すると `e_<from>_<to>` |

線どうしが交差する箇所は、後に描く線が弧で跳び越す（交差と合流を見分けるため）。経路探索は交差の少ない経路を選ぶ。

経路（折れ点）そのものは書かない。直したいときは、まず箱の位置、次に `from_side`・`to_side`、最後に `via` の順で指定する。

## 並び順（order）

```json
"order": [{"axis": "y", "ids": ["app", "rte", "bsw"]}]
```

- `axis` が `y` なら上から、`x` なら左からこの順に並んでいることを check_drawio.py が照合する
- grid で、同じ枠の直下の pos の無い兄弟ならこの順に並べる。レーンを並べたときはレーンの順にもなる
- free では照合だけ行う。並べるのはモデルが書く `at`・`near`

## シーケンス図（layout: "sequence"）

シーケンス図のページは `groups`・`nodes`・`edges` を使わず、`participants` と `steps` で書く。位置はすべてスクリプトが決める（参加者は左から書いた順、メッセージは上から書いた順）。

```json
{
  "name": "注文処理", "layout": "sequence",
  "participants": [
    {"id": "user", "label": "利用者", "shape": "actor"},
    {"id": "web", "label": "Webアプリ"},
    {"id": "db", "label": "在庫DB", "shape": "database"}
  ],
  "steps": [
    {"from": "user", "to": "web", "label": "注文する"},
    {"from": "web", "to": "db", "label": "在庫確認", "id": "q"},
    {"from": "db", "to": "web", "type": "reply", "label": "在庫数"},
    {"fragment": "alt", "operands": [
      {"guard": "在庫あり", "steps": [{"from": "web", "to": "user", "type": "reply", "label": "注文完了"}]},
      {"guard": "在庫なし", "steps": [{"from": "web", "to": "user", "type": "reply", "label": "在庫切れ"}]}
    ]},
    {"fragment": "loop", "guard": "通知ごと", "steps": [
      {"from": "db", "to": "web", "type": "async", "label": "在庫変動通知"}
    ]}
  ]
}
```

### participants

| キー | 意味 |
|---|---|
| `id` / `label` | 参加者の id と見出し |
| `shape` | `process`（四角。既定）/ `actor`（人型）/ `database`（紫の四角）/ `entity`（UML のエンティティ記号）/ `external`（破線の四角） |
| `style` / `class` | 見出しの見た目。箱と同じ |

### steps（メッセージ）

| キー | 意味 |
|---|---|
| `from` / `to` | 参加者の id。同じ id なら自己メッセージ（右に折り返す線） |
| `label` | メッセージの文言 |
| `type` | `sync`（同期。既定。塗りの矢印）/ `async`（非同期。開いた矢印）/ `reply`（応答。破線）/ `create`（生成。相手の見出しをその高さから始める）/ `destroy`（破棄。相手のライフラインをそこで終えて × を付ける） |
| `id` | 省略すると `m<番号>`。`replyTo` で参照するときに書く |
| `replyTo` | 応答が返す呼び出しの `id`。省略すると、相手から自分への未応答の同期呼び出しのうち最も新しいものに対応づける |
| `activate` | `false` で、この同期呼び出しの活性区間を描かない |
| `style` / `class` | 線の見た目 |

活性区間（ライフライン上の細い箱）は、同期呼び出しを受けてから、それへの応答を返すまで描く。**応答の無い同期呼び出しには活性区間を描かない。** 描きたいなら応答を書く。応答が対応する呼び出しを見つけられないときは WARN が出るので、`replyTo` で指定する。内側の呼び出しの応答を省いて外側の応答だけを書くと、対応を誤ることがある。その場合も `replyTo` を書く。

### steps（複合フラグメント）

```json
{"fragment": "alt", "operands": [{"guard": "条件1", "steps": [ ... ]}, {"guard": "else", "steps": [ ... ]}]}
{"fragment": "loop", "guard": "最大3回", "steps": [ ... ]}
```

- `fragment` は `alt` / `opt` / `loop` / `par` / `break` / `critical` / `ref`
- 分岐が2つ以上なら `operands`、1つなら `guard` と `steps` を直接書く。入れ子にしてよい
- 枠の横幅は中のメッセージに出てくる参加者から決まる。メッセージの無い参加者も囲みたいなら `covers: ["id", ...]` を足す
- `alt` の分岐ごとに、応答の済んだ呼び出しがそろわないと WARN が出る（片方の分岐だけ応答して、もう片方は応答しないなど）

### draw.io 上の形

参加者は draw.io 標準のライフライン図形、活性区間はその子、メッセージは両端がライフラインか活性区間に接続された線、フラグメントは独立した枠で出す。人が draw.io で参加者を横に動かすとメッセージが追従する。メッセージを足すときは、draw.io の UML 図形集のメッセージ線をライフラインへつなぐ。

## 例

自由配置（利用者・サーバー枠・外部決済）:

```json
{
  "name": "システム構成", "layout": "free",
  "groups": [{"id": "srv", "label": "サーバー", "at": [260, 0]}],
  "nodes": [
    {"id": "u", "label": "利用者", "shape": "actor", "at": [0, 40]},
    {"id": "web", "label": "Webアプリ", "in": "srv", "at": [0, 0]},
    {"id": "api", "label": "API", "in": "srv", "near": {"right_of": "web"}},
    {"id": "db", "label": "DB", "shape": "database", "in": "srv", "near": {"below": "api", "gap": 60}},
    {"id": "ext", "label": "外部決済", "shape": "external", "near": {"below": "srv", "gap": 60}}
  ],
  "edges": [
    {"from": "u", "to": "web", "label": "操作"},
    {"from": "web", "to": "api"},
    {"from": "api", "to": "db"},
    {"from": "api", "to": "ext", "label": "決済", "from_side": "bottom"}
  ]
}
```

状態遷移図（自己遷移は from と to を同じにする）:

```json
{
  "name": "状態遷移", "layout": "free",
  "nodes": [
    {"id": "init", "shape": "initial", "at": [0, 45]},
    {"id": "idle", "label": "待機", "shape": "state", "near": {"right_of": "init"}},
    {"id": "run", "label": "運転", "shape": "state", "near": {"right_of": "idle", "gap": 160}}
  ],
  "edges": [
    {"from": "init", "to": "idle"},
    {"from": "idle", "to": "run", "label": "開始"},
    {"from": "run", "to": "idle", "label": "停止"},
    {"from": "run", "to": "run", "label": "周期処理"}
  ]
}
```

ER図:

```json
{
  "name": "ER図", "layout": "free",
  "nodes": [
    {"id": "cust", "label": "顧客", "shape": "entity", "fields": ["PK 顧客ID", "氏名"], "at": [0, 0]},
    {"id": "ord", "label": "注文", "shape": "entity", "fields": ["PK 注文ID", "FK 顧客ID"], "near": {"right_of": "cust", "gap": 140}}
  ],
  "edges": [{"from": "cust", "to": "ord", "card": ["1", "0..*"]}]
}
```

スイムレーン（grid。位置は流れの順に自動）:

```json
{
  "name": "レビュー", "layout": "grid",
  "groups": [{"id": "l_dev", "label": "開発者", "kind": "lane"}, {"id": "l_rev", "label": "レビュアー", "kind": "lane"}],
  "nodes": [
    {"id": "fix", "label": "コード修正", "in": "l_dev"},
    {"id": "rv", "label": "レビュー", "in": "l_rev"},
    {"id": "ok", "label": "承認?", "shape": "decision", "in": "l_rev"}
  ],
  "edges": [
    {"from": "fix", "to": "rv"}, {"from": "rv", "to": "ok"},
    {"from": "ok", "to": "fix", "label": "差し戻し", "dashed": true}
  ],
  "order": [{"axis": "y", "ids": ["l_dev", "l_rev"]}]
}
```
