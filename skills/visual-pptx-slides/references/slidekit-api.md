# slidekit API

build_deck.py を書くとき（手順3）に読む。実装は `scripts/slidekit.py`。迷ったら `assets/examples/demo_all_patterns.py` の同じパターンの呼び出しを真似る。

## 目次

1. 約束ごと
2. Deck（デッキ全体）
3. 低レベル部品
4. 共通帯・補足
5. パターン関数
6. よくある失敗

## 1. 約束ごと

- 座標・寸法はインチ（float）。スライドは 13.333 × 7.5。
- 定数: `MX`（左右マージン 0.65）、`BODY = (0.65, 1.85, 12.03, 4.8)`（本文領域）、`SW` `SH`。
- `split_area(area, ratios, gap=0.35, direction="h"|"v")` で領域を比率分割する。
- 色は theme の色名で指定する: `bg panel ink sub muted rule white primary primary_mid primary_soft secondary secondary_soft tertiary tertiary_soft accent accent_soft`。
- 文字のマークアップ: `[[語]]` = 朱の太字、`{{語}}` = 藍の太字、`\n` = 改行。
- 文字を部分ごとに大きさを変えたいときは段落リストを渡す: `[[("30", {"size": 54, "bold": True}), (" 分", {"size": 20})]]`。
- 図形名の接頭辞（`TITLE` `SOURCE` `PAGE` `T:` `B:`）は `check_deck.py` が使うので変えない。

## 2. Deck

```python
deck = Deck(theme="default")      # "corporate" / JSON パスも可
s = deck.slide(title, kicker=None, chapter=None, chapter_color="primary",
               source=None, notes=None, page=True)   # 通常スライド
deck.cover(title, subtitle=None, series=None, pills=(), points=(), notes=None)
s = deck.blank()                  # ヘッダーを自動で置かない（自由配置）。TITLE は自分で置く
deck.save("out/deck.pptx")        # ページ番号「n / N」はここで振る
```

- `chapter` は章番号（文字列も可: `"+"`）。キッカーの左に丸で出る。
- `source` は出典。省略すると罫線ごと出ない（データのあるスライドでは省略しない）。
- `notes` は発表者ノート。話す内容・補足の数字はここへ逃がし、スライドの文字を減らす。
- `pills` は文字列か `(文字列, 色名)`。`points` は `(番号, 見出し, 補足, 色名)`。
- `blank()` はキッカー・タイトル・出典を置かないだけで、タイトルが不要になるわけではない。読者に見える結論文を `s.text(0.65, 0.9, 12.03, 0.85, "結論文", size=34, bold=True, name="TITLE")` のように自分で置く。置かないと `check_deck.py` が NO_TITLE（ERROR）を出す。見えないタイトルや空のタイトルで検査を通さない。

## 3. 低レベル部品（Slide のメソッド）

| メソッド | 用途 |
|---|---|
| `box(x, y, w, h, fill="panel", line=None, radius=0.12, text=None, size=None, color="ink", bold=False, align="center", valign="middle", lw=1.25, dash=False)` | 角丸の箱。中に文字 |
| `rect(...)` / `circle(cx, cy, d, ...)` | 四角・円（引数は box と同じ） |
| `text(x, y, w, h, text, size=None, color="ink", bold=False, align="left", valign="top")` | 枠なしの文字 |
| `pill(x, y, w, h, text, fill="primary", color="white", size=None, line=None)` | 両端の丸いラベル |
| `badge(cx, cy, d, text, fill="primary", ring=None)` | 丸数字（`ring="secondary"` で白抜き） |
| `line(x1, y1, x2, y2, color="sub", width=1.5, dash=False, head=None)` | 線。`head="end"/"both"` で矢じり |
| `block_arrow(x, y, w, h, color="accent", direction="right", text=None)` | 太矢印（1枚に1本） |
| `tag(x, y, text="概念図")` | 注記タグ（概念図 / 要公式確認 / 推定） |
| `polyline(points, color="primary", width=3, fill=None, closed=False)` | 折れ線・多角形 |
| `image(path, x, y, w, h, caption=None)` | 画像。無ければ破線の差し替え枠 |
| `notes(text)` | 発表者ノートを上書き |

## 4. 共通帯・補足

```python
s.action_band(text, label="今やる1手", y=6.0, h=0.62, color="tertiary")
s.legend([("primary", "藍 = モデル"), ("accent", "朱 = 変化")], x, y)
s.side_panel(x, y, w, h, "視聴者の反応", [("Discord 話題数", "2 位", ""), ("保存率", "5 位", "10月")])
```

## 5. パターン関数

すべて `area=(x, y, w, h)` を受け取り、省略時は `BODY`。

```python
s.before_after(before={"title": "これまで: …", "items": [...], "caption": "…"},
               after={"title": "これから: …", "items": [...], "caption": "…"},
               color="secondary", arrow=True)            # → {"before": 内側領域, "after": 内側領域}
s.card_columns([{"title", "sub", "color", "chips": [...], "note", "footer"}, ...])
s.timeline_events([{"pos": 0.3, "date": "10/7", "label": "…", "color": "tertiary",
                    "side": "up", "highlight": False}, ...], start="10/1", end="10/31")
s.gantt(axis=[(0, "9/22"), (1, "10/31")],
        rows=[{"label", "sub", "color", "bars": [(0.2, 1.0, "9/29 発表", "solid"|"soft"|"fade")]}],
        now=1.0, now_label="10月末、4つが並んだ")
s.swimlane(axis=[(0, "9/22"), ...],
           lanes=[{"label": "モデル", "color": "primary",
                   "events": [(0.0, "Opus 5.5", "up", "accent"), (0.2, "Sonnet", "down", True)]}])
s.matrix(cols=[...], rows=[{"label", "sub", "cells": {0: "出力100万", 1: "動画入力"}}],
         group={"cols": (0, 1), "note": "共通点 = [[長時間]]の作業"}, right_note="各社バラバラ")
s.bar_ranking([("Gemini 4 実使用", 400), ("格付け", 206, "primary"), ...],
              baseline=100, baseline_label="中央値 = 100", highlight=0, highlight_text="中央値の4倍")
s.column_compare(groups=[("入力", [5, 4]), ("出力", [25, 20])],
                 series=[("Opus 5", "tertiary_soft"), ("Opus 5.5", "tertiary")],
                 callout="2割安く", unit="$")
s.pyramid([("Opus", "判断・長時間", "primary"), ("Sonnet", "日常の主力", "primary_mid"),
           ("Haiku", "大量処理", "primary_soft")], side_notes=["↑ 上ほど深く考える"])
s.hub_spoke(center={"title": "Claude 5.5 世代", "items": ["Opus", "Sonnet", "Haiku"], "badge": "一強"},
            satellites=[{"title": "Gemini 4", "sub": "長い出力・動画", "highlight": False}, ...],
            ring={"pills": ["Dots", "Grok Bot", "Muse", "Duet"], "label_top": "外側 = AI秘書",
                  "label_bottom": "24時間動き続ける"})
s.flow_steps([{"title": "① 生成", "items": [...], "color": "primary"}, ...],
             arrow_color="accent", arrow_labels=["5分", "待ち2日"])
s.layer_stack([{"label": "Application", "items": [...], "color": "primary", "highlight": False}, ...],
              side=("注記の見出し", "注記の本文"))
s.numbered_list([(1, "見出し", "補足", "primary"), ...], highlight=4, highlight_label="人の判断")
s.concept_curve(rising="AI が作る量", flat="人が読める量", gap="読み切れない\n= ボトルネック")
s.area_compare([("Opus 5 = 1", 1.0, "$5 / $25"), ("V4.1 Flash", 1/60, "約 1/60")],
               unit_note="面積 = 費用（100万トークンあたり）")
s.kpi_tiles([("30", "分", "1関数あたりの工数", "accent", "以前は 2 時間")])
s.table(header=[...], rows=[[...], ...], col_widths=[2, 3, 3], highlight_col=2, size=16)
s.agenda(items=[(1, "Claude\nの一強", "primary"), ...],
         timebar=[("掴み", 1.5, "panel"), ("1", 3.5, "primary"), ...],
         legend=[("primary", "藍 = モデル"), ...])
```

`pos` はすべて 0.0（左端）〜 1.0（右端）の相対位置。日付から計算するときは `(日付 - 開始) / (終了 - 開始)`。

数値を受け取るパターン（`bar_ranking` `column_compare` `area_compare`）と `layer_stack` は、入力が空・負の値・全部 0・系列数の不一致のとき `ValueError` を出す。`area_compare` の値 0 は面積 0 として四角を描かず、0 より大きく小さすぎる値は最小サイズで描いて補足に「拡大表示」と付ける。

## 6. よくある失敗

| 症状 | 原因と直し方 |
|---|---|
| OVERFLOW が出る | 文字が長い。まず言葉を短くする。次に箱を広げる。最後にサイズを 1〜2pt 下げる（本文 13pt 未満にはしない） |
| TITLE_WRAP | タイトルを言い換えて全角 24 字以内に。2 行タイトルは不可（`
` での明示の改行も 2 行に数える） |
| TABLE_GROW | 表のセルの文が行に収まらず、PowerPoint で行が伸びて表が下へはみ出す。セルの文を短くするか、表を 2 枚に分ける |
| ValueError | パターン関数への入力の不備。メッセージのとおり値を直す |
| check_deck.py が終了コード 2 | 検査不能。theme 名の綴りか python-pptx の導入を確かめる。スライドは直さない |
| ORPHAN | 「…なっ / た」のような泣き別れ。語尾を削るか（「標準になった」→「標準化」）、枠を広げる |
| OVERLAP | 枠なし文字同士の衝突。`area` を分け直すか、吹き出しの `side` を入れ替える |
| 文字が四角で化ける・太さが違う | 描画環境にテーマのフォントが無い。`render.py` は代替フォントで描くので数%ずれる。実機確認が必要な場合はユーザーに伝える |
| 色が想定と違う | HEX 直書きをしていないか。theme の色名を使う |
