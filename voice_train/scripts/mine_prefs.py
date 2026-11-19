r"""挖偏好训练的反例（2026-11-12，兄长："你可以根据我的偏好给她训练增加惩罚或奖励" → "现在挖"）。

在人工样本的卡上让 8b-A（本机 Ollama，关思考）各写 2 句，用几样检测打分，挑出最差的那句当 rejected，
chosen 仍是原来的人工答案（原作台词 / 兄长认可或改写过的）。检测只用来挑训练用的反例，线上不改她一个字。

检测（都是从兄长第八批的改法来的，见决定记录"第八批标完了"）：
  念卡   卡里"要说到的"原句在回复里照搬了几成（最长公共子串 / 要点长度，取平均）
  我/哥  自称"我"、叫"哥 / 哥哥"，比人工答案多出来的次数
  套话   "今天累不累"这类他每次都删的尾巴
  打转   同一段四个字重复 4 次以上（以前出过"洗脑洗脑…"400 字）
卡片：训练包 stage2 的人工样本（去掉"长短"那一行，和这次重训一致）+ data\gold8\train.jsonl；去重。考试题不碰。

    python -I mine_prefs.py pilot 6    → 小试，打印出来看
    python -I mine_prefs.py run        → data\prefs_v2\mined_raw.jsonl（按 id 续跑）+ mined.jsonl（挑出来的对）
    python -I mine_prefs.py pick       → 只按已有的样本重新挑对（改了门槛时用）
"""
import json
import os
import random
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
VT = r"D:\JiashuBot\voice_train"
PACK = os.path.join(VT, "train_pack", "kaju_train_pack", "data")
SYS3 = json.load(open(os.path.join(PACK, "system.json"), encoding="utf-8"))["2"]
OUT = os.path.join(VT, "data", "prefs_v2")
RAW = os.path.join(OUT, "mined_raw.jsonl")
PAIRS = os.path.join(OUT, "mined.jsonl")
MODEL = "kaju-writer-p3-8b-a"
URL = "http://127.0.0.1:11435/v1/chat/completions"
N = 2
TEMP = 0.9
MIN_SCORE = 1.0  # 低于这个就算写得还行，不当反例
TAILS = ("累不累", "辛苦了吗", "今天过得怎么样")


def strip_length(card):
    return "\n".join(x for x in card.split("\n") if not x.startswith("长短："))


def rows():
    seen, out = set(), []
    paths = [os.path.join(PACK, "stage2.jsonl"), os.path.join(VT, "data", "gold8", "train.jsonl")]
    for p in paths:
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            if r.get("src") != "curated" or "要说到的：" not in r.get("card", ""):
                continue
            card = strip_length(r["card"])
            k = (tuple(r["ctx"]), card, r["target"])
            if k in seen:
                continue
            seen.add(k)
            out.append({"id": re.sub(r"-\d+$", "", r["id"]) if "gold-r8-" in r["id"] else r["id"],
                        "ctx": r["ctx"], "card": card, "target": r["target"]})
    ids = {}
    for r in out:  # id 唯一
        ids[r["id"]] = ids.get(r["id"], 0) + 1
        if ids[r["id"]] > 1:
            r["id"] += f"~{ids[r['id']]}"
    return out


def write(ctx, card, seed):
    body = {"model": MODEL, "temperature": TEMP, "top_p": 0.9, "max_tokens": 400, "seed": seed,
            "reasoning_effort": "none", "messages": [
                {"role": "system", "content": SYS3},
                {"role": "user", "content": "聊天：\n" + ("\n".join(ctx) or "（没有前文）") + "\n\n材料：\n" + card}]}
    req = urllib.request.Request(URL, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer local"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return (json.load(r)["choices"][0]["message"]["content"] or "").strip()


def lcs(a, b):
    """最长公共子串长度。"""
    best, prev = 0, [0] * (len(b) + 1)
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def points(card):
    m = re.search(r"要说到的：(.*)", card)
    if not m or m.group(1).strip() in ("", "无"):
        return []
    return [re.sub(r"（[^）]*）$", "", p).strip() for p in m.group(1).split("；") if len(p.strip()) >= 4]


def first_person(t):
    t = re.sub(r"[“「『\"][^”」』\"]*[”」』\"]", "", t)  # 引号里的话不算
    return len(re.findall(r"我(?!们的|们)", t)) + len(re.findall(r"我们", t))


def ge(t):
    return len(re.findall(r"哥", t))


def loops(t):
    t = t.replace("\n", "")
    grams = {}
    for i in range(len(t) - 3):
        g = t[i:i + 4]
        if "兄长" in g or "佳树" in g or "大人" in g:  # 称呼本来就会说好几遍，不算打转
            continue
        grams[g] = grams.get(g, 0) + 1
    return max(grams.values(), default=0)


def judge(card, target, text):
    pts = points(card)
    copy = sum(lcs(p, text) / len(p) for p in pts) / len(pts) if pts else 0.0
    copy_t = sum(lcs(p, target) / len(p) for p in pts) / len(pts) if pts else 0.0
    f = {"copy": round(copy, 2), "copy_gold": round(copy_t, 2),
         "wo": max(0, first_person(text) - first_person(target)),
         "ge": max(0, ge(text) - ge(target)),
         "tail": sum(x in text and x not in target for x in TAILS),
         "loop": loops(text)}
    s = 0.0
    if copy >= 0.5 and copy - copy_t >= 0.2:  # 比人工答案明显更照念
        s += 2 * (copy - copy_t) / 0.3
    s += 1.0 * min(f["wo"], 3) + 1.0 * min(f["ge"], 2) + 1.5 * f["tail"]
    if f["loop"] >= 4:
        s += 3
    f["score"] = round(s, 2)
    return f


def load_raw():
    if not os.path.exists(RAW):
        return {}
    out = {}
    for line in open(RAW, encoding="utf-8"):
        r = json.loads(line)
        out[r["id"]] = r
    return out


def pick():
    raw = load_raw()
    pairs, why = [], {"copy": 0, "wo": 0, "ge": 0, "tail": 0, "loop": 0}
    for r in raw.values():
        best = max(r["samples"], key=lambda s: s["f"]["score"], default=None)
        if not best or best["f"]["score"] < MIN_SCORE or best["text"] == r["target"]:
            continue
        f = best["f"]
        for k in why:
            if (k == "copy" and f["copy"] - f["copy_gold"] >= 0.2 and f["copy"] >= 0.5) or \
               (k == "loop" and f["loop"] >= 4) or (k not in ("copy", "loop") and f[k]):
                why[k] += 1
        pairs.append({"id": r["id"] + "-mined", "src": "mined", "ctx": r["ctx"], "card": r["card"],
                      "chosen": r["target"], "rejected": best["text"], "rej_from": "writer-8b-a", "flags": f})
    with open(PAIRS, "w", encoding="utf-8") as fo:
        for p in pairs:
            fo.write(json.dumps(p, ensure_ascii=False) + "\n")
    L = lambda s: len(s.replace("\n", ""))  # noqa: E731
    print(f"样本 {len(raw)} 张卡，挑出 {len(pairs)} 对（分数 ≥ {MIN_SCORE}）；各项命中：{why}")
    if pairs:
        print(f"chosen 平均 {sum(L(p['chosen']) for p in pairs) / len(pairs):.0f} 字，"
              f"rejected 平均 {sum(L(p['rejected']) for p in pairs) / len(pairs):.0f} 字 → {PAIRS}")


def sample(r):
    out = []
    for j in range(N):
        t = time.time()
        text = write(r["ctx"], r["card"], 1000 + j)
        out.append({"text": text, "f": judge(r["card"], r["target"], text), "secs": round(time.time() - t, 1)})
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    os.makedirs(OUT, exist_ok=True)
    if cmd == "pick":
        return pick()
    todo = rows()
    if cmd == "pilot":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
        for r in random.Random(7).sample(todo, n):
            print("=====", r["id"], "\n卡:", r["card"].split("要说到的：")[-1], "\n人工:", r["target"].replace("\n", " / "))
            for s in sample(r):
                print(f"  [{s['secs']}s] {s['f']}\n   {s['text'].replace(chr(10), ' / ')}")
        return
    raw = load_raw()
    todo = [r for r in todo if r["id"] not in raw]
    print(f"卡 {len(rows())} 张，还要写 {len(todo)} 张 × {N} 句", flush=True)
    t0 = time.time()
    with open(RAW, "a", encoding="utf-8") as fo:
        for i, r in enumerate(todo, 1):
            try:
                ss = sample(r)
            except Exception as e:  # noqa: BLE001
                print("FAIL", r["id"], type(e).__name__, str(e)[:120], flush=True)
                continue
            fo.write(json.dumps(dict(r, samples=ss), ensure_ascii=False) + "\n")
            fo.flush()
            if i % 25 == 0:
                el = time.time() - t0
                print(f"{i}/{len(todo)}  已用 {el / 60:.0f} 分钟，还要约 {el / i * (len(todo) - i) / 60:.0f} 分钟", flush=True)
    pick()


if __name__ == "__main__":
    main()
