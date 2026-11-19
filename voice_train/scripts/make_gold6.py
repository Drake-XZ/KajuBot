"""第六批：写手发出去的线上回复，兄长大人认可或改写 → K 层（佳树口吻）训练数据 + 考试题（2026-11-09）。

先把页面上的标注存到本地（Claude 用 ArtifactData list，url https://claude.ai/artifact/F2PeyHrCfBUuyM357YS8Yx，
collection "labels"，out_dir = data/review6_labels），再跑（AstrBot venv）：
  python -I make_gold6.py [--dry]

每条标注 {text, skip, ok}：
  - ok（认可原句）：卡片 = 线上当时那张（写手真正看到的），答案 = 原句。上下文也是线上那份。
  - 改写：先问 DeepSeek 他的写法照线上那张卡算不算说得通（AGREE）——算就用那张卡（只改了说法，正是要学的口吻）；
    不算（他改了要说的事）就按线上方式从他的写法重新抽卡，免得教写手不照卡写。
  - 每 3 条留 1 条做考试题 → data/review6_eval.jsonl（daily_learn 的考试会读）；
    其余写进 data/layered_v1/stage2.jsonl，src "curated"，id "gold-r6-…"（先删掉上次的 gold-r6 行，可以反复跑）。
  - 标过的（含"这条不要"）记进 data/review6_used.json：每晚考试抽线上题时跳过它们，训练题不会混进考题。
撤销：删掉 stage2.jsonl 里 id 以 gold-r6- 开头的行，删 review6_eval.jsonl 和 review6_used.json。
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
import build_layered as bl  # noqa: E402  (DeepSeek 客户端、load、AGREE)

sys.path.insert(0, r"D:\JiashuBot\bot_setup\kaju_core\voice")
import card  # noqa: E402  (和线上同一份抽卡提示词和格式)
import rewrite  # noqa: E402  (tidy_ctx：和线上一样去掉上下文里的系统文字和空行)

# 不用的：草稿串到了别的对话，卡片和上下文说的不是一回事（拿它训练会教写手答非所问）
EXCLUDE = {"r6-1794025921.3": "兄长问视频讲什么/犯罪标签，草稿却是另一个小丑视频"}

DATA = os.path.join(bl.VT, "data")
ITEMS = os.path.join(DATA, "review6_items.json")
LABELS = os.path.join(DATA, "review6_labels", "labels")
STAGE2 = os.path.join(DATA, "layered_v1", "stage2.jsonl")
EVAL = os.path.join(DATA, "review6_eval.jsonl")
USED = os.path.join(DATA, "review6_used.json")


def lines(t):
    """页面上几条之间用 / 隔开（和线上分条发一样）→ 换行；去掉句号和空行。"""
    t = re.sub(r"\s*[/／]\s*", "\n", str(t or "").strip())
    t = t.replace("兄大人", "兄长大人").replace("兄长长大人", "兄长大人")
    t = re.sub(r"。+(?=.)", "\n", t).replace("。", "")
    return "\n".join(l.strip() for l in t.split("\n") if l.strip())


def labels():
    out = {}
    for p in glob.glob(os.path.join(LABELS, "*.json")):
        d = json.load(open(p, encoding="utf-8"))
        out[os.path.splitext(os.path.basename(p))[0]] = d.get("data", d) if isinstance(d, dict) else {}
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    items = json.load(open(ITEMS, encoding="utf-8"))
    lab = labels()
    for it in items:
        it["train_ctx"] = rewrite.tidy_ctx(it["train_ctx"])[-4:] or ["（没有前文）"]
    todo = [(it, lab[it["id"]]) for it in items
            if it["id"] in lab and not lab[it["id"]].get("skip") and lines(lab[it["id"]].get("text"))
            and it["id"] not in EXCLUDE]
    for k, why in EXCLUDE.items():
        print(f"不用 {k}：{why}")
    print(f"标注 {len(lab)} 条，能用 {len(todo)} 条（其余是\"这条不要\"或空的）")

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

    async def one(it, lb):
        target = lines(lb.get("text"))
        if lb.get("ok") or target == lines(it["reply"]):
            return {"it": it, "target": target, "card": it["card"], "from": "认可原句", "why": ""}
        ok, why = await agrees(it["card"], target)
        if ok:
            return {"it": it, "target": target, "card": it["card"], "from": "改了说法", "why": why}
        return {"it": it, "target": target, "card": await extract(it, target), "from": "改了意思", "why": why}

    rows = await asyncio.gather(*(one(it, lb) for it, lb in todo))
    bad = [r["it"]["id"] for r in rows if not r["card"]]
    rows = [r for r in rows if r["card"]]
    if bad:
        print(f"没抽出卡的跳过：{bad}")
    train, exam = [], []
    for i, r in enumerate(rows):
        row = {"src": "curated", "id": "gold-" + r["it"]["id"], "ctx": r["it"]["train_ctx"], "card": r["card"],
               "target": r["target"], "to": r["it"]["to"], "kind": r["it"]["kind"], "card_from": r["from"]}
        (exam if i % 3 == 2 else train).append(row)
    for kind in ("认可原句", "改了说法", "改了意思"):
        print(f"  {kind} {sum(r['from'] == kind for r in rows)} 条")
    print(f"进 K 层训练 {len(train)} 条，留作考试题 {len(exam)} 条\n{bl.cost()}")
    for r in rows:
        if r["from"] != "认可原句":
            print(f"--- {r['it']['id']} [{r['from']}] {r['why']}\n  原句：{r['it']['reply']}\n  → {r['target']}")
    if a.dry:
        return
    kept = [r for r in bl.load(STAGE2) if not str(r.get("id", "")).startswith("gold-r6-")]
    with open(STAGE2, "w", encoding="utf-8") as f:
        for r in kept + train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(EVAL, "w", encoding="utf-8") as f:
        for r in exam:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    json.dump(sorted(str(it["t"]) for it in items if it["id"] in lab), open(USED, "w", encoding="utf-8"))
    print(f"写好：{STAGE2}（共 {len(kept) + len(train)} 行）、{EVAL}、{USED}")


if __name__ == "__main__":
    asyncio.run(main())
