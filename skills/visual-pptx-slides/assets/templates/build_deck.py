"""〔デッキ名〕を生成する。outline.md の「### n.」とスライドのブロックを 1 対 1 で対応させる。

    python build_deck.py            # → out/deck.pptx

修正するときは、指摘のあったスライドのブロックだけを編集する。
"""
import os
import sys

SKILL_DIR = os.environ.get("SLIDE_SKILL_DIR", "〔スキルのディレクトリの絶対パス〕")
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
from slidekit import BODY, Deck, split_area  # noqa: E402,F401

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "deck.pptx")
deck = Deck(theme="default")
SRC = "出典: 〔〕"

# --- 1. 表紙 -------------------------------------------------------------
deck.cover(series="〔シリーズ名〕", title="〔…[[変化点]]…〕", subtitle="〔副題〕",
           pills=[("〔期間〕", "primary"), ("〔N つの変化〕", "tertiary")],
           points=[(1, "〔見出し〕", "〔代表日〕", "primary")])

# --- 2. 〔キッカー〕 --------------------------------------------------------
s = deck.slide(chapter=1, kicker="〔章名〕", title="〔結論文の[[変化点]]〕", source=SRC)
s.before_after(before={"title": "これまで: 〔〕", "items": ["〔〕"], "caption": "〔〕"},
               after={"title": "これから: 〔〕", "items": ["〔〕"], "caption": "〔〕"},
               area=(BODY[0], BODY[1], BODY[2], 3.9))
s.action_band("〔次の行動を1文で〕")

deck.save(OUT)
print(OUT)
