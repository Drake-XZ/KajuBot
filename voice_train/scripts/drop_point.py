r"""删一个要点的反例（2026-11-12，奖惩方案的"惩罚 3·漏点"）：专防上次 DPO 靠丢要点变短赢。

拿训练里的好答案（人工样本 + 第八批 + 一部分原作台词，卡上至少 2 条要点），让 Gemini 把其中一条要点对应的话删掉、
别的字一个不动 → 成对：chosen = 原答案，rejected = 删掉一条的，同一张卡。
检查：rejected 必须比原来短、和原来大部分一样（相似度 ≥ 0.6），不能和原来相同；不合格的扔掉。

    python -I drop_point.py [novel 条数，默认 200]   → data\prefs_v2\droppoint.jsonl（按 id 续跑）
"""
import difflib
import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mine_fresh as mf  # noqa: E402  (Gemini 调用、key)
import mine_prefs as mp  # noqa: E402  (卡片行、要点)

OUT = os.path.join(mp.OUT, "droppoint.jsonl")

DROP = """下面是一张要点卡和照卡写出的回复。把回复里讲"要删的那条要点"的话删掉，其余的字一个都不要改、不要补、不要换说法。
删完要还是通顺的话（只允许顺手去掉因此多出来的连接词或标点）。回复里的换行照原样保留。
只回 JSON：{"text": "删完的回复"}"""


def pool(n_novel):
    rows = mp.rows()
    nov = []
    for line in open(os.path.join(mp.PACK, "stage2.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r.get("src") == "novel":
            nov.append({"id": r["id"], "ctx": r["ctx"], "card": mp.strip_length(r["card"]), "target": r["target"]})
    rnd = random.Random(2026111203)
    nov = [r for r in nov if len(mp.points(r["card"])) >= 2]
    rows = [r for r in rows if len(mp.points(r["card"])) >= 2] + rnd.sample(nov, min(n_novel, len(nov)))
    for r in rows:
        pts = re.search(r"要说到的：(.*)", r["card"]).group(1).split("；")
        r["drop"] = random.Random(r["id"]).choice(pts).strip()
    return rows


def main():
    n_novel = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    rows = pool(n_novel)
    done = {json.loads(x)["src_id"] for x in open(OUT, encoding="utf-8")} if os.path.exists(OUT) else set()
    todo = [r for r in rows if r["id"] not in done]
    print(f"卡上 ≥2 条要点的好答案 {len(rows)} 条，还要做 {len(todo)} 条", flush=True)
    k = mf.train_keys.gemini()
    tok = {"in": 0, "out": 0, "ok": 0, "bad": 0}

    def one(r):
        user = f"要点卡：\n{r['card']}\n\n要删的那条要点：{r['drop']}\n\n回复：\n{r['target']}"
        try:
            text, u = mf.gemini(k, DROP, user)
            tok["in"] += u.get("prompt_tokens", 0)
            tok["out"] += u.get("completion_tokens", 0)
            t = str(json.loads(text[text.find("{"):text.rfind("}") + 1]).get("text") or "").strip()
        except Exception as e:  # noqa: BLE001
            print("FAIL", r["id"], type(e).__name__, str(e)[:100], flush=True)
            return None
        a, b = r["target"].replace("\n", ""), t.replace("\n", "")
        if not b or b == a or len(b) >= len(a) or difflib.SequenceMatcher(None, a, b).ratio() < 0.6:
            tok["bad"] += 1
            return None
        tok["ok"] += 1
        return {"id": r["id"] + "-drop", "src_id": r["id"], "src": "droppoint", "ctx": r["ctx"], "card": r["card"],
                "chosen": r["target"], "rejected": t, "rej_from": "drop-point", "dropped": r["drop"]}

    with ThreadPoolExecutor(4) as ex, open(OUT, "a", encoding="utf-8") as fo:
        for x in ex.map(one, todo):
            if x:
                fo.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(f"合格 {tok['ok']}，扔掉 {tok['bad']}；输入 {tok['in']} 输出 {tok['out']} tokens → {OUT}")


if __name__ == "__main__":
    main()
