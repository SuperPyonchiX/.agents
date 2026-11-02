"""全パターンの見本デッキ（数値はすべて架空のサンプル値）。

    python assets/examples/demo_all_patterns.py [出力パス] [theme]

slidekit の使い方の実例として読む。新しいデッキを作るときは assets/templates/build_deck.py から始める。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scripts"))
from slidekit import BODY, Deck  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "out/demo.pptx"
theme = sys.argv[2] if len(sys.argv) > 2 else "default"
deck = Deck(theme=theme)
SRC = "出典: サンプル（数値はすべて架空）"

# 1. 表紙 ---------------------------------------------------------------
deck.cover(
    series="開発生産性レポート ・ 四半期まとめ",
    title="3か月でテストは何が[[変わったか]]",
    subtitle="2026年 第3四半期版",
    pills=[("7/1 〜 9/30 の 92 日", "primary"), ("4 つの変化 + 番外", "tertiary")],
    points=[(1, "生成が標準化", "7/8 全チームへ展開", "primary"),
            (2, "レビュー渋滞", "8/5 待ち行列が最大", "secondary"),
            (3, "検証を自動化", "8/20 判定スクリプト", "secondary"),
            (4, "費用が下がった", "9/10 モデル切り替え", "tertiary")])

# 2. アジェンダ ------------------------------------------------------------
s = deck.slide(kicker="今日の流れ", title="4つの変化 + 番外を、この順で話します", source=SRC)
s.agenda(items=[(1, "生成が\n標準になった", "primary"), (2, "レビューが\n詰まった", "secondary"),
                (3, "検証を\n自動化", "secondary_soft"), (4, "費用が\n下がった", "tertiary"),
                ("+", "番外\n来期の論点", "tertiary_soft")],
         timebar=[("掴み", 1.5, "panel"), ("1", 4, "primary"), ("2", 4, "secondary"),
                  ("3", 4, "secondary_soft"), ("4", 3, "tertiary"), ("締め", 2, "panel")],
         legend=[("primary", "藍 = 仕組み・ツール"), ("secondary", "碧 = 工程・運用"),
                 ("tertiary", "山吹 = コスト・人の側"), ("accent", "朱 = ここが変わった")])

# 3. 勢力図（ハブ） ----------------------------------------------------------
s = deck.slide(kicker="結論から", title="9月末、テスト工程の全体像はこうなった", source=SRC)
s.hub_spoke(center={"title": "テスト生成ハーネス", "items": ["生成", "判定", "記録"],
                    "badge": "中核"},
            satellites=[{"title": "要求仕様", "sub": "入力・トレース元"},
                        {"title": "静的解析", "sub": "ルール違反を先に除外"},
                        {"title": "CI", "sub": "夜間に全件実行"},
                        {"title": "レビュー", "sub": "人が判断する唯一の工程"},
                        {"title": "費用管理", "sub": "モデル別の単価", "highlight": True},
                        {"title": "ナレッジ", "sub": "失敗例を蓄積"}],
            ring={"pills": ["設計者", "検証者", "PL", "品質保証"], "label_top": "外側 = 関係者",
                  "label_bottom": "毎晩回り続ける"})

# 4. スイムレーン -----------------------------------------------------------
s = deck.slide(kicker="7/1 〜 9/30 の 92 日", title="3か月で、3つの層が[[同時に]]動いた", source=SRC)
s.swimlane(axis=[(0, "7/1"), (0.33, "8/1"), (0.67, "9/1"), (1, "9/30")],
           lanes=[{"label": "ツール", "color": "primary",
                   "events": [(0.05, "生成スキル v1", "up", "accent"), (0.4, "判定スクリプト", "up", True),
                              (0.75, "v2（境界値）", "down", True)]},
                  {"label": "運用", "color": "secondary",
                   "events": [(0.1, "全チーム展開", "up", True), (0.38, "レビュー待ち最大", "down"),
                              (0.6, "当番制を導入", "up", True)]},
                  {"label": "費用", "color": "tertiary",
                   "events": [(0.2, "月次上限を設定", "up"), (0.78, "モデル切替", "down", True)]}])

# 5. Before → After ------------------------------------------------------
s = deck.slide(chapter=1, kicker="生成が標準になった",
               title="テストは「書く」ものから[[「選ぶ」]]ものへ", source=SRC)
s.before_after(before={"title": "これまで: 人が書く", "items": ["仕様を読む", "ケースを考える",
                                                       "コードを書く", "レビューを受ける"],
                       "caption": "1関数あたり 2時間"},
               after={"title": "これから: AI が出し、人が選ぶ", "items": ["仕様を渡す", "候補を確認する",
                                                                "採否を決める"],
                      "caption": "1関数あたり 30分"})

# 6. 比較カード -------------------------------------------------------------
s = deck.slide(chapter=1, kicker="生成が標準になった",
               title="生成方式は[[3タイプ]] — 目的で1つ選ぶ", source=SRC)
s.card_columns([
    {"title": "仕様起点", "sub": "要求から網羅", "color": "secondary",
     "chips": ["要求IDと紐づく", "抜けが見える"], "note": "設計書が整っている案件向け",
     "footer": "新規開発で使いたい"},
    {"title": "コード起点", "sub": "実装から逆算", "color": "secondary",
     "chips": ["既存資産に強い", "分岐を全部通る"], "note": "レガシー改修向け",
     "footer": "既存コードに足したい"},
    {"title": "差分起点", "sub": "変更点だけ", "color": "secondary",
     "chips": ["速い・安い", "回帰に強い"], "note": "保守フェーズ向け",
     "footer": "毎日の修正で回したい"}])

# 7. フロー -----------------------------------------------------------------
s = deck.slide(chapter=2, kicker="レビューが詰まった",
               title="詰まりは[[判定]]の工程に集中していた", source=SRC)
s.flow_steps([{"title": "① 生成", "items": ["仕様を分解", "ケース案を出す"], "color": "primary"},
              {"title": "② 判定", "items": ["期待値を確認", "重複を除く"], "color": "accent"},
              {"title": "③ レビュー", "items": ["採否を決める", "理由を残す"], "color": "secondary"},
              {"title": "④ 記録", "items": ["項目書へ反映", "トレース更新"], "color": "primary"}],
             area=(BODY[0], BODY[1], BODY[2], 3.9), arrow_color="sub",
             arrow_labels=["5分", "待ち 2日", "15分"])
s.action_band("判定をスクリプトに寄せ、人はレビューだけに集中する")

# 8. レイヤー -----------------------------------------------------------------
s = deck.slide(chapter=3, kicker="検証を自動化",
               title="判定は3層に分け、[[下の層から]]機械化した", source=SRC)
s.layer_stack([{"label": "人の判断", "items": ["仕様の解釈", "採否"], "color": "tertiary"},
               {"label": "ルール判定", "items": ["命名規約", "境界値の有無", "重複検出"],
                "color": "secondary", "highlight": True},
               {"label": "構文・実行", "items": ["コンパイル", "実行", "カバレッジ計測"],
                "color": "primary"}],
              side=("8月に機械化", "下の2層をスクリプトにし、人の確認は最上層だけにした。\n\n"
                                 "判定スクリプトは CI で毎晩実行する。"))

# 9. マトリクス ---------------------------------------------------------------
s = deck.slide(chapter=3, kicker="検証を自動化",
               title="各チームは「[[境界値]]」と得意分野で勝負してきた",
               source=SRC + " ・ 概念図（定性。数値・順位ではない）")
s.matrix(cols=["境界値", "異常系", "性能", "保守性"],
         rows=[{"label": "制御チーム", "sub": "7/8 → 8/20", "cells": {0: "全関数で必須", 1: "故障注入"}},
               {"label": "通信チーム", "sub": "8/1", "cells": {0: "プロトコル境界", 3: "テンプレ化"}},
               {"label": "診断チーム", "sub": "8/12", "cells": {0: "DTC 全件"}},
               {"label": "基盤チーム", "sub": "9/1", "cells": {2: "実行時間計測"}}],
         group={"cols": (0, 1), "note": "共通点 = [[境界値]]と異常系を先に固めること"},
         right_note="ここはチームごと = 得意分野")

# 10. ランキング --------------------------------------------------------------
s = deck.slide(chapter=4, kicker="費用が下がった",
               title="「[[実際に使った]]」チームが一番伸びた", source=SRC + " ・ 指数: 全チーム中央値 = 100")
s.bar_ranking([("制御チーム", 400), ("通信チーム", 206), ("診断チーム", 194),
               ("基盤チーム", 188, "primary_soft"), ("UI チーム", 176, "secondary"),
               ("ツールチーム", 136)],
              area=(BODY[0], BODY[1], 8.2, BODY[3]), baseline=100, baseline_label="中央値 = 100",
              highlight_text="中央値の 4 倍", label_w=2.2)
s.box(9.3, 1.95, 3.4, 2.0, fill="panel", line="rule", lw=1,
      text="考察\n全部に広げず、\n得意分野ごとに使う", size=18, bold=True, align="left")

# 11. 縦棒比較 + サイドパネル -------------------------------------------------------
s = deck.slide(chapter=4, kicker="費用が下がった",
               title="モデル切替で、[[しかも安くなった]]", source=SRC)
s.column_compare(groups=[("入力", [5, 4]), ("出力", [25, 20])],
                 series=[("旧モデル", "tertiary_soft"), ("新モデル", "tertiary")],
                 area=(BODY[0], BODY[1], 7.5, BODY[3]), callout="2割安く", unit="$")
s.side_panel(8.8, BODY[1], 3.9, BODY[3], "チームの反応",
             [("満足度アンケート", "4.3", "/ 5"), ("継続利用率", "92", "%"), ("要望件数", "18", "件")])

# 12. ピラミッド --------------------------------------------------------------
s = deck.slide(chapter=4, kicker="費用が下がった",
               title="「最強はどれ？」から[[「どう使い分ける？」]]へ", source=SRC)
s.pyramid([("上位モデル", "設計判断・長時間", "primary"), ("中位モデル", "日常の主力", "primary_mid"),
           ("軽量モデル", "大量処理・定型", "primary_soft")],
          area=(BODY[0], BODY[1], BODY[2], 3.9),
          side_notes=["↑ 上ほど深く考える", "↓ 下ほど回数が多い"])
s.action_band("普段の生成を軽量モデルへ切り替え、上位は判断だけに使う")

# 13. ガント ------------------------------------------------------------------
s = deck.slide(kicker="番外", title="7月からの3か月で、[[4つの施策]]が出揃った", source=SRC)
s.gantt(axis=[(0, "7/1"), (0.25, "7/23"), (0.55, "8/20"), (0.85, "9/16"), (1, "9/30")],
        rows=[{"label": "生成スキル", "sub": "ツール", "bars": [(0.06, 1, "7/8 全チーム展開", "solid")]},
              {"label": "当番制", "sub": "運用", "bars": [(0, 1, "以前から試行、8月に正式化", "fade")]},
              {"label": "判定スクリプト", "sub": "ツール", "bars": [(0.55, 1, "8/20 導入", "solid")]},
              {"label": "モデル切替", "sub": "費用", "bars": [(0.85, 1, "9/16", "solid")]}],
        now=1, now_label="9月末、4つが並んだ")

# 14. イベントタイムライン ------------------------------------------------------------
s = deck.slide(kicker="番外", title="9月、ハーネスまわりの道具が次々に出た", source=SRC)
s.timeline_events([
    {"pos": 0.05, "date": "9/2", "label": "評価スキル", "color": "secondary", "side": "up"},
    {"pos": 0.15, "date": "9/4", "label": "レビュー支援", "color": "primary", "side": "down"},
    {"pos": 0.3, "date": "9/9", "label": "計画の1枚化", "color": "tertiary", "side": "up"},
    {"pos": 0.42, "date": "9/12", "label": "費用ダッシュボード", "color": "tertiary", "side": "down"},
    {"pos": 0.55, "date": "9/16", "label": "プロジェクト機能", "color": "primary", "side": "up"},
    {"pos": 0.66, "date": "9/19", "label": "並列セッション", "color": "secondary", "side": "down"},
    {"pos": 0.88, "date": "9/27", "label": "サブ工程を1本に統合", "side": "up", "highlight": True}],
    start="9/1", end="9/30", area=(BODY[0], BODY[1], BODY[2], 3.5))
s.legend([("primary", "機能"), ("secondary", "回す・並べる"), ("tertiary", "人の側・お金"),
          ("accent", "方針の転換")], BODY[0], 5.6)

# 15. KPI タイル ---------------------------------------------------------------
s = deck.slide(kicker="数字で見る", title="工数は[[4分の1]]に、カバレッジは上がった", source=SRC)
s.kpi_tiles([("30", "分", "1関数あたりの工数", "accent", "以前は 2 時間（4分の1）"),
             ("92", "%", "分岐カバレッジ", "primary", "前四半期 78% から +14pt"),
             ("2.1", "日", "レビュー待ち（平均）", "tertiary", "8月のピーク 4.5 日から短縮")],
            area=(BODY[0], BODY[1], BODY[2], 3.4))

# 16. 表 ----------------------------------------------------------------------
s = deck.slide(kicker="設計判断", title="判定方式は[[案B]]を推奨する", source=SRC)
s.table(["観点", "案A: 全件人手", "案B: ルール判定 + 人", "案C: 全自動"],
        [["工数", "大", "中", "小"], ["見逃しリスク", "低", "低", "中"],
         ["説明責任", "◎", "◎", "△"], ["導入コスト", "なし", "2人月", "4人月"]],
        area=(BODY[0], BODY[1], BODY[2], 3.2), col_widths=[2, 3, 3, 3], highlight_col=2, size=18)
s.action_band("案B で 10 月から試行。3 か月後に見逃し率で再評価する", label="決めてほしいこと",
              y=5.4, color="tertiary")

# 17. 概念カーブ + 右カード -----------------------------------------------------------
s = deck.slide(chapter="+", kicker="来期の論点", title="AI が作る量が、[[人が読める量]]を追い越した",
               source=SRC, chapter_color="tertiary")
s.concept_curve(area=(BODY[0], BODY[1], 7.6, BODY[3]))
s.box(8.75, 2.2, 3.95, 1.9, fill="panel", line="secondary", lw=1.5,
      text="{{9/9 計画の1枚化}}\n目的・手順・決めることを\n1枚の図で合意", size=16, align="left")
s.box(8.75, 4.35, 3.95, 1.9, fill="primary_soft",
      text="{{9/27 統合}}\nサブ工程をやめ、\n1本のループ + 評価へ", size=16, align="left")

# 18. 面積比較 ---------------------------------------------------------------
s = deck.slide(chapter=4, kicker="費用が下がった", title="旧モデルの[[1/60]]の費用で回せる構成ができた",
               source=SRC)
s.area_compare([("旧モデル = 1", 1.0, "$5 / $25"), ("新モデル = 0.8", 0.8, "2割減"),
                ("軽量モデル", 1 / 60, "約 1/60"), ("社内ホスト", 1 / 40, "約 1/40")],
               area=(BODY[0], BODY[1], 8.0, BODY[3]), unit_note="面積 = 費用（100万トークンあたり）")

# 19. まとめ ------------------------------------------------------------------
s = deck.slide(kicker="まとめ 4つの変化 + 番外", title="AI は速く・安く・常駐へ。人は[[「判断」]]に回る",
               source=SRC)
s.numbered_list([(1, "生成が標準になった", "書くより選ぶへ", "primary"),
                 (2, "レビューが詰まった", "判定の工程がボトルネック", "secondary"),
                 (3, "検証を自動化", "下の層から機械化", "secondary_soft"),
                 (4, "費用が下がった", "評価も常に回せる値段に", "tertiary"),
                 ("+", "来期の論点", "1枚の図で合わせ、人は判断する", "tertiary_soft")],
                highlight=4, highlight_label="人の判断")

deck.save(out)
print(out)
