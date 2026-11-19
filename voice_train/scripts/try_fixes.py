r"""三项不用训练的修法，先在考题上试（2026-11-12，兄长：“先试三项”）。写手 kaju-writer-p4-8b-k，线上不动。

  nopoint  “无”卡补上要接住什么：考试里 9 道“要说到的：无”的题，Gemini 照聊天重出“要说到的”（不看参考答案），
           局面 / 心情行不变；不该回的让它说不回。写手照新卡各写 3 遍。
  rp       重复惩罚：8 道看完感想 + 12 道要点最多的题，repeat_penalty 1.0 / 1.1 / 1.15 各写 4 遍（同一组种子），
           数打转的句子、字数，DeepSeek 数漏点。先验证这个参数在 Ollama 里真起作用。
  felt     感受写进事实：8 道看完感想的卡，Gemini 把“事实（感受词）”改写成一条平铺的话，写手照新卡各写 3 遍，
           数回复里括号和单独念出来的感受词。
--hand：nopoint / felt 不调 Gemini，改用 data\try_fixes\hand_cards.json（11-12 中转平台账号用尽时 Claude 手写的卡），结果存 <名字>_hand.json。
结果都存 data\try_fixes\<名字>.json；盲选页另外造（build_ab11.py）。
用法（AstrBot 的 Python）：python -I -X utf8 scripts\try_fixes.py nopoint|rp|felt
"""
import asyncio
import json
import os
import re
import statistics
import sys
import time
import urllib.request

sys.argv = sys.argv[:1] + sys.argv[1:]
CMD = sys.argv[1] if len(sys.argv) > 1 else ""
HAND = "--hand" in sys.argv  # 不调 Gemini，用 data\try_fixes\hand_cards.json 里 Claude 手写的卡（只测写手那一半）
sys.argv = sys.argv[:1]  # daily_learn 读 argv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exam_p3 as ep  # noqa: E402  (SYS3、items、cover、mood_line)
import mine_fresh as mf  # noqa: E402  (persona、gemini)
import train_keys  # noqa: E402

bl, dl = ep.bl, ep.dl
MODEL = "kaju-writer-p4-8b-k"
OUT = os.path.join(bl.VT, "data", "try_fixes")
EXAM = os.path.join(bl.VT, "data", f"exam_p3_{MODEL}.json")

PLAN_NOPOINT = """你替佳树想好这一回要说什么，写成卡上“要说到的”那几条，交给另一个只会照卡说话的写手。
只回 JSON：{"回": true, "要说到的": ["…", "…"]}
- 要说到的：1 到 4 条，每条一件、6 到 20 个字。第一条写佳树要接住对方这一句的什么——
  对方在夸、在问、在抱怨、在逗、在戳她，佳树怎么回应，写成“佳树觉得……”“佳树问……”“佳树夸……”“佳树答应……”这样的短事实。
  不要替她写成句子，不写语气词和口癖。不编聊天里和她身上没有的事。
- 卡里提到她自己写“佳树”，不写“我”；称呼按聊天里的名字写。
- 这一句不需要她再接（话已经说完了、再说就多余），就回 {"回": false, "要说到的": []}。"""

FELT = """下面是佳树看完一个视频或一首歌后记下的几条，每条是“事实（当时的感受）”。
把每条改写成一条平铺的短话：事实和感受写在一起，不用括号，比如“仙人掌亮灯扭着学说话（魔性好笑）”→“仙人掌亮灯扭着学说话，又魔性又好笑”。
不加新内容，不删内容，不写成佳树说话的口气。只回 JSON：{"要说到的": ["…", "…"]}，条数和原来一样。"""


def write(card_text, ctx, rp=1.0, seed=None, num_predict=1024):
    """原生接口（think 关掉），可以带 repeat_penalty / seed。num_predict 只是防卡死的兜底，不压她的长短。"""
    opts = {"temperature": 0.7, "top_p": 0.9, "repeat_penalty": rp, "num_predict": num_predict}
    if seed is not None:
        opts["seed"] = seed
    body = {"model": MODEL, "stream": False, "think": False, "options": opts, "messages": [
        {"role": "system", "content": ep.SYS3},
        {"role": "user", "content": "聊天：\n" + ("\n".join(ctx) or "（没有前文）") + "\n\n材料：\n" + card_text}]}
    req = urllib.request.Request(dl.OLLAMA_URL + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return dl.live_rw.clean_output(json.load(r)["message"]["content"]).strip()
        except Exception:  # noqa: BLE001
            time.sleep(3)
    return ""


def loops(text, n=6, times=3):
    """同一段（n 字以上）出现 times 次以上，或者同一行出现两次，就算打转。只用来判坏、扔掉重写，不改字。"""
    t = re.sub(r"\s", "", text)
    lines = [x.strip() for x in text.split("\n") if len(x.strip()) >= n]
    if len(lines) != len(set(lines)):
        return True
    for i in range(0, max(0, len(t) - n)):
        if t.count(t[i:i + n]) >= times:
            return True
    return False


def replace_points(card, pts):
    return re.sub(r"(?m)^要说到的：.*$", lambda _: "要说到的：" + ("；".join(pts) or "无"), card)


def gem_json(k, system, user):
    for _ in range(3):
        try:
            text, u = mf.gemini(k, system, user)
            return json.loads(text[text.find("{"):text.rfind("}") + 1]), u
        except Exception as e:  # noqa: BLE001
            print("  重试", type(e).__name__, str(e)[:120], flush=True)
            time.sleep(3)
    return None, {}


def exam_rows():
    return json.load(open(EXAM, encoding="utf-8"))


def save(name, obj):
    os.makedirs(OUT, exist_ok=True)
    json.dump(obj, open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("存好", os.path.join(OUT, name + ".json"), flush=True)


def hand(part):
    return json.load(open(os.path.join(OUT, "hand_cards.json"), encoding="utf-8"))[part]


def nopoint():
    k = None if HAND else train_keys.gemini()
    sysmsg = "" if HAND else mf.persona() + "\n\n" + PLAN_NOPOINT
    rows = [r for r in exam_rows() if r["must"] in ("无", "", "（无）")]
    out = []
    for r in rows:
        user = f"场合：{r['kind']}\n对象：{r['title'] or '无'}\n\n聊天：\n" + "\n".join(r["ctx"])
        j, _ = (hand("nopoint").get(r["id"]), {}) if HAND else gem_json(k, sysmsg, user)
        if not j:
            print("没出卡", r["id"]); continue
        reply = j.get("回", True) is not False
        pts = [str(x).strip("。；; ") for x in j.get("要说到的") or [] if str(x).strip()][:4]
        card = replace_points(r["new_card"], pts)
        wrote = [write(card, r["ctx"]) for _ in range(3)] if reply and pts else []
        print(f"{r['id']}  回={reply}  {'；'.join(pts)}\n   原来：{r['new'][0]}\n   现在：{wrote[0] if wrote else '（不回）'}", flush=True)
        out.append({"id": r["id"], "kind": r["kind"], "title": r["title"], "ctx": r["ctx"], "ref": r["ref"],
                    "old_card": r["new_card"], "new_card": card, "reply": reply, "points": pts,
                    "before": r["new"], "after": wrote, "old_writer": r["old"]})
    save("nopoint" + ("_hand" if HAND else ""), out)


async def rp():
    rows = exam_rows()
    felt = [r for r in rows if r["old_card"] is None]
    many = sorted([r for r in rows if r["old_card"] is not None and r["must"] not in ("无", "")],
                  key=lambda r: -r["must"].count("；"))[:12]
    its = felt + many
    # 参数到底起不起作用：同一个种子，1.0 和 1.5 写出来一样就是没起作用
    a = write(its[0]["new_card"], its[0]["ctx"], 1.0, seed=7)
    b = write(its[0]["new_card"], its[0]["ctx"], 1.5, seed=7)
    a2 = write(its[0]["new_card"], its[0]["ctx"], 1.0, seed=7)
    print("同种子 1.0 两次一样：", a == a2, "｜ 1.0 和 1.5 一样：", a == b, flush=True)
    res = {"同种子可复现": a == a2, "repeat_penalty起作用": a != b, "by": {}}
    for pen in (1.0, 1.1, 1.15):
        rec = []
        for r in its:
            for s in range(4):
                t = write(r["new_card"], r["ctx"], pen, seed=100 + s)
                rec.append({"id": r["id"], "felt": r["old_card"] is None, "seed": 100 + s, "text": t, "loop": loops(t), "len": len(t)})
        covs = await asyncio.gather(*[ep.cover({"must": next(x for x in its if x["id"] == q["id"])["must"]}, q["text"]) for q in rec])
        for q, c in zip(rec, covs):
            q["漏"], q["错"] = c["漏"], c["错"]
        st = {"句数": len(rec), "打转": sum(q["loop"] for q in rec), "字数中位": statistics.median(q["len"] for q in rec),
              "看完感想字数中位": statistics.median(q["len"] for q in rec if q["felt"]),
              "有漏的句": sum(q["漏"] > 0 for q in rec), "漏点合计": sum(q["漏"] for q in rec), "说错": sum(q["错"] > 0 for q in rec)}
        print(f"repeat_penalty {pen}：{st}", flush=True)
        res["by"][str(pen)] = {"stats": st, "rows": rec}
    save("rp", res)


FEEL_WORD = re.compile(r"[（(][^）)]{1,8}[）)]")


def felt():
    k = None if HAND else train_keys.gemini()
    rows = [r for r in exam_rows() if r["old_card"] is None]
    out = []
    for r in rows:
        pts = [p.strip() for p in re.split(r"[；;]", r["must"]) if p.strip()]
        j, _ = ({"要说到的": hand("felt").get(r["id"])}, {}) if HAND else gem_json(k, FELT, "\n".join(pts))
        new = [str(x).strip("。；; ") for x in (j or {}).get("要说到的") or [] if str(x).strip()]
        if len(new) != len(pts):
            print("条数对不上，跳过", r["id"], pts, new); continue
        card = replace_points(r["new_card"], new)
        wrote = [write(card, r["ctx"]) for _ in range(3)]
        feels = [re.findall(r"[（(]([^）)]{1,8})[）)]", p) for p in pts]
        words = [w for f in feels for w in f]

        def readout(t):  # 括号原样出现，或感受词单独成句（前后是标点）
            return bool(FEEL_WORD.search(t)) or any(re.search(r"[，。！、…\s]" + re.escape(w) + r"[，。！…\s]|" + re.escape(w) + r"$", t) for w in words)
        print(f"{r['id']}\n   改后：{'；'.join(new)}\n   原来：{r['new'][0][:120]}\n   现在：{wrote[0][:120]}", flush=True)
        out.append({"id": r["id"], "ctx": r["ctx"], "ref": r["ref"], "old_card": r["new_card"], "new_card": card,
                    "before": r["new"], "after": wrote,
                    "念感受词_原来": sum(readout(t) for t in r["new"]), "念感受词_现在": sum(readout(t) for t in wrote),
                    "打转_原来": sum(loops(t) for t in r["new"]), "打转_现在": sum(loops(t) for t in wrote)})
    print("念感受词 原来", sum(o["念感受词_原来"] for o in out), "/", 3 * len(out), "→ 现在", sum(o["念感受词_现在"] for o in out), "/", 3 * len(out))
    save("felt" + ("_hand" if HAND else ""), out)


if __name__ == "__main__":
    {"nopoint": nopoint, "rp": lambda: asyncio.run(rp()), "felt": felt}[CMD]()
