# シーケンス図の spec.json の書き方

D0 でシーケンス図を書くときに、spec-format.md の代わりに読む。シーケンス図以外のページを同じファイルに混ぜるときは spec-format.md も読む。

複数ページは `{"pages": [ {1ページ分}, ... ]}` と書き、**id はページをまたいでも重複させない**（`check_drawio.py --spec` は全ページをまとめて照合する）。ページの `styles` に名前を付けたスタイルを置くと、参加者やメッセージの `class` で参照できる。`style` は draw.io のスタイル文字列で、既定のスタイルへ key=value 単位で上書きする。

## 全体の形

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
