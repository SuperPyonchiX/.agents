# spec.json の書き方

D0 で spec.json を書くときに読む。`layout_from_spec.py` はこの形を読んで `.drawio` を作り、`check_drawio.py --spec` は同じ spec.json を要件として図と突き合わせる。

役割分担は次のとおり。

- **箱の位置はモデルが決める**（`at`・`near`）
- **線の経路はスクリプトが決める**。箱と枠の見出し帯を避ける直交経路を探し、経由点まで固定する
- 位置にこだわりがない図や、要素が多い流れの図は、グリッドの自動配置（`layout: "grid"`）に任せてよい

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
| `layout` | `free`（位置をモデルが書く）/ `grid`（自動配置）。省略すると、どの要素にも `at`・`near` が無ければ `grid`、あれば枠ごとに判定 |
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
| `from_side` / `to_side` | 出口・入口の辺。`top` / `bottom` / `left` / `right`。省略すると経路探索が選ぶ |
| `via` | `[[x, y], ...]`。経由させる点（図全体の左上からの座標）。探索は点ごとに区切って行う |
| `style` / `class` | 箱と同じ。線の色・太さ（`strokeColor=#b85450;strokeWidth=2`）など |
| `id` | 省略すると `e_<from>_<to>` |

経路（折れ点）そのものは書かない。直したいときは、まず箱の位置、次に `from_side`・`to_side`、最後に `via` の順で指定する。

## 並び順（order）

```json
"order": [{"axis": "y", "ids": ["app", "rte", "bsw"]}]
```

- `axis` が `y` なら上から、`x` なら左からこの順に並んでいることを check_drawio.py が照合する
- grid で、同じ枠の直下の pos の無い兄弟ならこの順に並べる。レーンを並べたときはレーンの順にもなる
- free では照合だけ行う。並べるのはモデルが書く `at`・`near`

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
