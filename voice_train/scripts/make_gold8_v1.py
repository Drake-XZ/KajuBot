r"""第八批：看完视频 / 歌 / 动图的感想，兄长大人挑的或自己写的 → K 层（佳树口吻）训练数据 + 考试题 + 同卡偏好对（2026-11-11）。

先把页面上的标注存到本地（Claude 用 ArtifactData list，collection "labels"，out_dir = data/review8_labels），再跑（AstrBot venv）：
  python -I make_gold8.py [--dry]

每条标注 {pick, text, skip}（pick = 以页面上第几句为底，-1 = 完全自己写；页面上三句的来历在 data/review8_key.json：w1 / w2 = 写手照感受卡写的两遍，ds = DeepSeek 照感受直接写的）：
  - 原样挑了写手的一句：卡片 = 那张感受卡（写手真正看到的），答案 = 那一句。
  - 挑了 DeepSeek 的、在某句上改过、或者自己写的：先问 DeepSeek 他的写法照感受卡算不算说得通（AGREE）——算就用感受卡；
    不算就按线上方式从他的写法重新抽卡（免得教写手不照卡写）。
  - 每 3 条留 1 条做考试题 → data/review8_eval.jsonl；其余写进 data/layered_v1/stage2.jsonl，src "curated"，id "gold-r8-…"（可反复跑）。
  - 偏好对 → data/review8_prefs.jsonl（和 prefs_v1/dpo.jsonl 同一个格式）：答案用的是感受卡时，chosen = 他的答案，
    rejected = 同一张卡上没被选中的写手那一句 / 两句（同卡对比：赢的不是靠少说要点）；DeepSeek 那句没被选中也记一对（rej_from "ds"）。
撤销：删掉 stage2.jsonl 里 id 以 gold-r8- 开头的行，删 review8_eval.jsonl 和 review8_prefs.jsonl。
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

DATA = os.path.join(bl.VT, "data")
ITEMS = os.path.join(DATA, "review8_items.json")
KEY = os.path.join(DATA, "review8_key.json")
LABELS = os.path.join(DATA, "review8_labels", "labels")
STAGE2 = os.path.join(DATA, "layered_v1", "stage2.jsonl")
EVAL = os.path.join(DATA, "review8_eval.jsonl")
PREFS = os.path.join(DATA, "review8_prefs.jsonl")


def lines(t):
    """页面上几条之间用 / 隔开（和线上分条发一样）→ 换行；去掉句号和空行。"""
    t = re.sub(r"\s*[/／]\s*", "\n", str(t or "").strip())
    t = t.replace("兄大人", "兄长大人").replace("兄长长大人", "兄长大人")
    t = re.sub(r"。+(?=.)", "\n", t).replace("。", "")
    return "\n".join(x.strip() for x in t.split("\n") if x.strip())


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
    key = json.load(open(KEY, encoding="utf-8"))
    lab = labels()
    todo = [(it, lab[it["id"]]) for it in items
            if it["id"] in lab and not lab[it["id"]].get("skip") and lines(lab[it["id"]].get("text"))]
    print(f"标注 {len(lab)} 条，能用 {len(todo)} 条（其余是\"这条不要\"或空的）")
    picks = {"w": 0, "ds": 0, "改过": 0, "自己写": 0}

    async def extract(it, text):
        c = card.parse(await bl.ask(card.EXTRACT, card.extract_prompt(it["ctx"], text, "私聊", "兄长大人")))
        return card.render(c, "私聊", "兄长大人") if c else ""

    async def agrees(ct, target):
        j = re.search(r"\{.*\}", await bl.ask(bl.AGREE, f"要点卡：\n{ct}\n\n回复：\n{target}", 0.0) or "", re.S)
        try:
            v = json.loads(j.group(0)) if j else {}
        except ValueError:
            v = {}
        return bool(v.get("ok")), str(v.get("why") or "判断失败")

    async def one(it, lb):
        target = lines(lb.get("text"))
        cands = [lines(c) for c in it["cands"]]
        who = key[it["id"]]  # 页面上第 i 句是谁写的
        same = cands.index(target) if target in cands else -1
        if same >= 0 and who[same].startswith("w"):
            picks["w"] += 1
            return {"it": it, "target": target, "card": it["card"], "from": "挑了写手的", "why": "", "cands": cands, "who": who, "same": same}
        kind = "ds" if same >= 0 else ("改过" if int(lb.get("pick", -1)) >= 0 else "自己写")
        picks[kind] += 1
        ok, why = await agrees(it["card"], target)
        name = {"ds": "挑了DeepSeek的", "改过": "在候选上改的", "自己写": "自己写的"}[kind]
        if ok:
            return {"it": it, "target": target, "card": it["card"], "from": name + "·感受卡说得通", "why": why,
                    "cands": cands, "who": who, "same": same}
        return {"it": it, "target": target, "card": await extract(it, target), "from": name + "·重新抽卡", "why": why,
                "cands": cands, "who": who, "same": same}

    rows = await asyncio.gather(*(one(it, lb) for it, lb in todo))
    bad = [r["it"]["id"] for r in rows if not r["card"]]
    rows = [r for r in rows if r["card"]]
    if bad:
        print(f"没抽出卡的跳过：{bad}")
    train, exam, prefs = [], [], []
    for i, r in enumerate(rows):
        it = r["it"]
        row = {"src": "curated", "id": "gold-" + it["id"], "ctx": it["ctx"], "card": r["card"], "target": r["target"],
               "to": "兄长大人", "kind": "私聊", "card_from": r["from"], "scene": "看完感想"}
        held = i % 3 == 2
        (exam if held else train).append(row)
        if r["card"] == it["card"] and not held:  # 同一张感受卡上的对比才成对（考试题不进偏好训练）
            for j, c in enumerate(r["cands"]):
                if j != r["same"] and c and c != r["target"]:
                    prefs.append({"id": f"gold-{it['id']}-{r['who'][j]}", "src": "r8", "ctx": it["ctx"], "card": r["card"],
                                  "chosen": r["target"], "rejected": c, "card_from": r["from"],
                                  "rej_from": "ds" if r["who"][j] == "ds" else "writer"})
    print("他怎么选的：", picks)
    for kind in sorted({r["from"] for r in rows}):
        print(f"  {kind} {sum(r['from'] == kind for r in rows)} 条")
    print(f"进 K 层训练 {len(train)} 条，留作考试题 {len(exam)} 条，偏好对 {len(prefs)} 对"
          f"（其中对写手 {sum(p['rej_from'] == 'writer' for p in prefs)}）\n{bl.cost()}")
    for r in rows:
        print(f"--- {r['it']['id']} [{r['from']}] {r['why']}\n  → {r['target']}")
    if a.dry:
        return
    kept = [r for r in bl.load(STAGE2) if not str(r.get("id", "")).startswith("gold-r8-")]
    with open(STAGE2, "w", encoding="utf-8") as f:
        for r in kept + train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for path, data in ((EVAL, exam), (PREFS, prefs)):
        with open(path, "w", encoding="utf-8") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"写好：{STAGE2}（共 {len(kept) + len(train)} 行）、{EVAL}、{PREFS}")


if __name__ == "__main__":
    asyncio.run(main())
