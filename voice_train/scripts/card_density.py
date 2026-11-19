import json, random, re, glob, statistics as S, sys
def pts(card):
    l = next((x for x in card.splitlines() if x.startswith("要说到的：")), "要说到的：")
    v = l.split("：", 1)[1].strip()
    return [] if v in ("", "无") else [p for p in v.split("；") if p.strip()]
def norm(t): return re.sub(r"[\s，。！？、,.!?~～…/“”\"'：:（）()]", "", t or "")
def bigr(t): t = norm(t); return {t[i:i+2] for i in range(len(t)-1)}
def copy(out, card):
    P = "".join(pts(card)); b = bigr(out)
    return len(b & bigr(P)) / len(b) if b else 0
def stats(name, rows):
    n = [len(pts(r["card"])) for r in rows]; L = [len(norm(r["out"])) for r in rows]
    c = [copy(r["out"], r["card"]) for r in rows if pts(r["card"])]
    hist = {k: round(sum(1 for x in n if x == k) / len(n), 2) for k in range(0, 6)}
    print(f"{name:14} n={len(rows):5}  点数分布(0..5)={hist}  ≥3点={sum(x>=3 for x in n)/len(n):.2f}  回复字数中位={S.median(L):.0f}  照抄率中位={S.median(c):.2f}  照抄≥0.6={sum(x>=0.6 for x in c)/max(1,len(c)):.2f}")
random.seed(1)
D = "train_pack/kaju_train_pack/data/"
s1 = [json.loads(l) for l in open(D + "stage1.jsonl", encoding="utf-8")]
s1 = random.sample(s1, 3000)
s2 = [json.loads(l) for l in open(D + "stage2.jsonl", encoding="utf-8")]
for r in s1 + s2: r["out"] = r["target"]
stats("训练 H(群聊)", s1)
stats("训练 K(全部)", s2)
stats("训练 K 原作", [r for r in s2 if r.get("src") == "novel"])
stats("训练 K 兄长", [r for r in s2 if r.get("src") != "novel"])
live = []
for p in sorted(glob.glob(r"D:\JiashuBot\kaju_data\self\kaju_style\rewrites\2026-11-1[23].jsonl")):
    for l in open(p, encoding="utf-8"):
        d = json.loads(l)
        if (d.get("config") or {}).get("card_model") != "kaju-writer-p4-8b-k" or d.get("outcome") != "used": continue
        c = (d.get("card") or [{}])[-1].get("card", "")
        if "局面：" in c: live.append({"card": c, "out": d.get("final") or ""})
stats("线上 p4-8b-k", live)
