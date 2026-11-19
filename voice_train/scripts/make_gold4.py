"""第四轮标注 → 训练数据 + 考试题。

先把页面上的标注存到本地（Claude 用 ArtifactData list，collection "labels"，out_dir = data/review4_labels），再跑：
  python -I make_gold4.py [--dry]

做的事：
  1. 每条写了的（没点"这条不要"、不是空的）：卡片按线上方式从她当时的回复抽（DeepSeek 关思考，和线上同一份 EXTRACT），
     所以卡片里还带着她的复述；答案是兄长大人写的说法 —— 写手学到"卡上是复述，说出来直接给反应"。
  2. 每 3 条留 1 条做考试题 → data/review4_eval.jsonl（daily_learn 的考试会读）；
     其余追加进 data/layered_v1/stage2.jsonl（K 层：原作台词 + 兄长大人的样本），src "curated"，id "gold-r4-…"。
     先删掉上次跑出来的 gold-r4 行，所以可以反复跑。
不打印 API key。
"""
import argparse
import asyncio
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_layered as bl  # noqa: E402  (DeepSeek 客户端、load/append)

sys.path.insert(0, r"D:\JiashuBot\bot_setup\kaju_core\voice")
import card  # noqa: E402  (和线上同一份抽卡提示词和格式)

DATA = os.path.join(bl.VT, "data")
ITEMS = os.path.join(DATA, "review4_items.json")
LABELS = os.path.join(DATA, "review4_labels", "labels")
STAGE2 = os.path.join(DATA, "layered_v1", "stage2.jsonl")
EVAL = os.path.join(DATA, "review4_eval.jsonl")


def tidy(t):
    """他打的字 → 训练目标：去掉（发个表情包）这类备注，句号处换成新一条，修几个常见手误。"""
    t = re.sub(r"[（(][^）)]*[）)]", "", t or "")
    t = t.replace("兄大人", "兄长大人").replace("兄长长大人", "兄长大人")
    # 这一批里看到的手误（2026-11-08）
    t = t.replace("学长得夸奖", "学长的夸奖").replace("头上盯着", "头上顶着").replace("把错另一个", "错把另一个")
    t = re.sub(r"。+(?=.)", "\n", t).replace("。", "")
    return "\n".join(l.strip() for l in t.split("\n") if l.strip())


def labels():
    out = {}
    for p in glob.glob(os.path.join(LABELS, "*.json")):
        d = json.load(open(p, encoding="utf-8"))
        body = d.get("data", d) if isinstance(d, dict) else {}
        out[os.path.splitext(os.path.basename(p))[0]] = body
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    items = json.load(open(ITEMS, encoding="utf-8"))
    lab = labels()
    todo = [(it, tidy(lab[it["id"]].get("text", ""))) for it in items
            if it["id"] in lab and not lab[it["id"]].get("skip") and tidy(lab[it["id"]].get("text", ""))]
    print(f"标注 {len(lab)} 条，能用 {len(todo)} 条（其余是\"这条不要\"或空的）")
    if not todo:
        return

    async def extract(it, text):
        c = card.parse(await bl.ask(card.EXTRACT, card.extract_prompt(it["train_ctx"], text, it["kind"], it["to"])))
        return card.render(c, it["kind"], it["to"]) if c else ""

    async def agrees(ct, target):
        j = re.search(r"\{.*\}", await bl.ask(bl.AGREE, f"要点卡：\n{ct}\n\n回复：\n{target}", 0.0) or "", re.S)
        try:
            v = json.loads(j.group(0)) if j else {}
        except ValueError:
            v = {}
        return bool(v.get("ok")), str(v.get("why") or "判断失败")

    async def one(it, target):
        # 先按线上方式从她当时的回复抽卡：他的写法照这张卡也说得通 → 用它（卡上带着复述，答案不复述，正是要学的）；
        # 他把要说的事改了（"佳树也想刷抖音，但要等兄长大人同意"）→ 卡和答案对不上，会教写手不照卡写，改从他的写法抽卡
        ct = await extract(it, it["reply"])
        ok, why = await agrees(ct, target) if ct else (False, "没抽出卡")
        if ok:
            return {"it": it, "target": target, "card": ct, "from": "她的回复", "why": why}
        ct2 = await extract(it, target)
        return {"it": it, "target": target, "card": ct2, "from": "他的写法", "why": why}

    rows = await asyncio.gather(*(one(it, t) for it, t in todo))
    bad = [r["it"]["id"] for r in rows if not r["card"]]
    rows = [r for r in rows if r["card"]]
    if bad:
        print(f"没抽出卡的跳过：{bad}")
    train, exam = [], []
    for i, r in enumerate(rows):
        row = {"src": "curated", "id": "gold-" + r["it"]["id"], "ctx": r["it"]["train_ctx"], "card": r["card"],
               "target": r["target"], "to": r["it"]["to"], "kind": r["it"]["kind"], "card_from": r["from"]}
        (exam if i % 3 == 2 else train).append(row)
    n_her = sum(r["from"] == "她的回复" for r in rows)
    print(f"卡片从她的回复抽 {n_her} 条（教\"别复述\"），从他的写法抽 {len(rows) - n_her} 条（他改了要说的事）")
    print(f"进 K 层训练 {len(train)} 条，留作考试题 {len(exam)} 条\n{bl.cost()}")
    for r in rows:
        print(f"--- {r['it']['id']} [{r['from']}] {r['why']}\n{r['card']}\n→ {r['target']}")
    if a.dry:
        return
    kept = [r for r in bl.load(STAGE2) if not str(r.get("id", "")).startswith("gold-r4-")]
    with open(STAGE2, "w", encoding="utf-8") as f:
        for r in kept + train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(EVAL, "w", encoding="utf-8") as f:
        for r in exam:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"写好：{STAGE2}（共 {len(kept) + len(train)} 行）、{EVAL}")


if __name__ == "__main__":
    asyncio.run(main())
