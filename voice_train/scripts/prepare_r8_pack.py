r"""第 8 轮的训练包和考题（2026-11-17，人格进写手；AGENT.md 第十节）。先跑 prepare_r8.py label（K 每条的标签）。

  gold   兄长三次盲选的备注 → 金数据（只要他写出来的话，“不需要回复 / 按之前的标注走 / 第二句不要”这类说明不要）：
           replay7 / replay6：卡 = 大脑当时出的标签卡（replay7\plans.jsonl，两次是同样那 52 轮，同一轮都有备注就用 replay7 的）
           r7k 盲选：卡 = 那道考题的 v8 卡，“要说到的”换成从他这句出的标签（要调模型，十几条）；长聊天错位的那 6 道题不要
         → r8\gold.jsonl
  exam   考题 v9 = v8 的题，“要说到的”换成从参考回复出的标签；长聊天错位的 6 道换回短前文 → data\stage2bg\exam_v9.json（要调模型，约 40 条）
  pack   r8\k_data：stage2 = r7k 的 K（要说到的换成标签；长聊天和记录对不上的换回 r6 的短前文；恋爱话题词表加宽后去掉）
           + 金数据（来源记 curated，训练时重复 3 遍）；约 5% 的卡多一条答案没说的标签、约 15%（有“反应”且不止一条的）去掉“反应”那条
           （反应是人格最多的地方，让写手自己补）；stage1（复习）照 r7k、同样去恋爱话题；prefs、system.json 照 r7k
         → r8\k_data、r8\info.json
用法（AstrBot 的 Python）：python -I -X utf8 scripts\prepare_r8_pack.py gold|exam|pack
"""
import argparse
import asyncio
import json
import os
import random
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, r"D:\JiashuBot\bot_setup")
import prepare_r8 as p8  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.join(VT, "data", "rounds_v4")
R6, R7K, R8 = os.path.join(ROOT, "r6"), os.path.join(ROOT, "r7k"), os.path.join(ROOT, "r8")
EXAM8 = os.path.join(VT, "data", "stage2bg", "exam_v8.json")
EXAM9 = os.path.join(VT, "data", "stage2bg", "exam_v9.json")
# 恋爱话题（r7k 的 ROMANCE_WIDE 漏了“实质上就是夫妻”“初恋对象是佳树”“谈情说爱”）：佳树是初三学生，这类不进训练
ROMANCE = re.compile(r"恋爱|交往|告白|表白|喜欢的人|情侣|吃醋|约会|夫妻|配偶|初恋|谈情|结婚|求婚|新娘|老婆|老公|嫁|恋人|男朋友|女朋友|"
                     r"亲亲|接吻|亲吻|kiss|心上人|暗恋|追求|一见钟情|拍拖|对象是谁|当恋人|月色")
NOTE_ONLY = re.compile(r"不需要|不用回|没必要|按照之前|按之前|标注走|照抄|句式重复|不要也行|第二句|自己编的|不用硬接")
# 第 7 轮核查出来长聊天错位的考题（被回的那句没进前文 / 答案在前文里 / 说话人换了）
BAD_EXAM = {"gold-r4-2026-11-02-1330-13", "gold-r4-2026-11-07-1833-32", "gold-r5-2026-11-09-103",
            "gold-r6-1794213560.9", "gold-r7-ab6-12", "gold-r7-ab6-29"}


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def wjl(p, rows):
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def romance(r):
    return bool(ROMANCE.search(r["target"] + r["card"] + (r["ctx"][-1] if r.get("ctx") else "")))


def with_labels(card, labels):
    return re.sub(r"^要说到的：.*$", ("要说到的：" + ("；".join(labels) or "无")).replace("\\", "\\\\"), card, count=1, flags=re.M)


def is_reply(note):
    n = (note or "").strip()
    return len(n) >= 4 and not NOTE_ONLY.search(n)


async def label_many(items):
    """[(key, card, ctx, target)] → {key: labels}（照 prepare_r8.LABEL 出）。"""
    import train_keys  # noqa: F401
    import usage_meter
    usage_meter.patch()
    from kaju_core.senses import omni
    sem = asyncio.Semaphore(4)
    out = {}

    async def one(key, card, ctx, target):
        async with sem:
            for _ in range(2):
                try:
                    o, _n = await omni.text(p8.LABEL, p8.user_of({"card": card, "ctx": ctx, "target": target}), timeout=40)
                    labels = p8.parse(o)
                    if labels:
                        out[key] = labels
                        return
                except Exception as e:  # noqa: BLE001
                    print("  没出好", key, type(e).__name__, str(e)[:80], flush=True)
    await asyncio.gather(*[one(*x) for x in items])
    u = usage_meter.report(os.path.join(R8, f"usage-{time.strftime('%H%M%S')}.json"))
    print("估钱", json.dumps({k: u.get(k) for k in ("rmb", "rmb_full")}, ensure_ascii=False), flush=True)
    return out


def cmd_gold():
    from kaju_core.voice import brain
    os.makedirs(R8, exist_ok=True)
    plans = {d["id"]: d["plan"] for d in jl(os.path.join(ROOT, "replay7", "plans.jsonl")) if d.get("plan")}
    items = {i["id"]: i for i in json.load(open(os.path.join(ROOT, "replay6", "items.json"), encoding="utf-8"))}
    gold, seen, skipped = [], set(), []
    for tag in ("replay7", "replay6"):
        for o in json.load(open(os.path.join(ROOT, tag, "ab_result.json"), encoding="utf-8"))["rows"]:
            if not o.get("note"):
                continue
            note = o["note"].strip()
            if not is_reply(note) or (o["src"], note) in seen or o["src"] not in plans:  # 同一轮两次写了不一样的话：两条都要
                skipped.append((tag, o["id"], note[:30]))
                continue
            it = items[o["src"]]
            seen.add((o["src"], note))
            gold.append({"src": "curated", "id": f"gold-r8-{tag}-{o['id']}", "group": f"gold-r8-{o['src']}", "ctx": it["long"],
                         "target": o["note"].strip(), "card": brain.card_of(it["kind"], it["title"], plans[o["src"]], it["mood"])})
    exam = {it["id"]: it for it in json.load(open(os.path.join(VT, "data", "exam_p3_kaju-writer-p6-8b-r7k_v8.json"), encoding="utf-8"))}
    todo = []
    for o in json.load(open(os.path.join(R7K, "ab_result.json"), encoding="utf-8"))["rows"]:
        if not o.get("note"):
            continue
        if not is_reply(o["note"]) or o["exam"] in BAD_EXAM or o["exam"] not in exam:
            skipped.append(("r7k", o["id"], o["note"][:30]))
            continue
        it = exam[o["exam"]]
        todo.append((o["id"], it["new_card"], it.get("ctx_new") or it["ctx"], o["note"].strip(), it))
    labels = asyncio.run(label_many([(k, c, x, t) for k, c, x, t, _ in todo]))
    for k, c, x, t, it in todo:
        if k in labels:
            gold.append({"src": "curated", "id": f"gold-r8-r7k-{k}", "group": f"gold-r8-{it['id']}", "ctx": x, "target": t,
                         "card": with_labels(c, labels[k])})
    gold = [g for g in gold if not romance(g)]
    wjl(os.path.join(R8, "gold.jsonl"), gold)
    print(f"金数据 {len(gold)} 条（replay7 {sum('replay7' in g['id'] for g in gold)}、replay6 {sum('replay6' in g['id'] for g in gold)}、"
          f"r7k {sum('-r7k-' in g['id'] for g in gold)}）；没要的 {len(skipped)}：", flush=True)
    for s in skipped:
        print("   ", s)


def cmd_exam():
    v8 = json.load(open(EXAM8, encoding="utf-8"))
    exam = {it["id"]: it for it in json.load(open(os.path.join(VT, "data", "exam_p3_kaju-writer-p6-8b-r7k_v8.json"), encoding="utf-8"))}
    todo = [(k, v["card_v8"], v.get("ctx_v8") or [], exam[k]["ref"]) for k, v in v8.items() if k in exam]
    labels = asyncio.run(label_many(todo))
    out = {}
    for k, v in v8.items():
        if k not in labels:
            continue
        ctx = v.get("ctx_v8") or []
        if k in BAD_EXAM:  # 长聊天错位：换回原来的短前文
            ctx = exam[k]["ctx"]
        out[k] = dict(v, card_v9=with_labels(v["card_v8"], labels[k]), ctx_v9=ctx)
    json.dump(out, open(EXAM9, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"考题 v9 {len(out)} 道（v8 {len(v8)}；换回短前文 {len(BAD_EXAM & set(out))}）", flush=True)


def aligned(short, long):
    """长前文最后一行是不是原来短前文最后一行（被回的那句）；说话人也要一样。"""
    if not long or not short or long == short:
        return True
    norm = lambda s: re.sub(r"[\s/，。！？、~～…·.!?,]", "", s or "")  # noqa: E731
    body = lambda line: (re.sub(r"^\d\d:\d\d ", "", line).split("：", 1) + [""])[:2] if "：" in line else ["", line]  # noqa: E731
    sw, st = body(short[-1])
    lw, lt = body(long[-1])
    return bool(norm(st)[:20]) and norm(st)[:20] in norm(lt) and (sw == lw or not sw)


def cmd_pack():
    rng = random.Random(888)
    labels = {(d["id"], d["src"]): d["labels"] for d in jl(p8.OUT) if d.get("labels")}
    old = {(r["id"], r["src"]): r for r in jl(os.path.join(R6, "k_data", "stage2.jsonl"))}
    src = os.path.join(R7K, "k_data")
    dst = os.path.join(R8, "k_data")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    s2 = jl(os.path.join(src, "stage2.jsonl"))
    pool = [x for v in labels.values() for x in v]
    stat = {"K 原来": len(s2), "没标签（照旧句子卡）": 0, "恋爱话题去掉": 0, "长前文换回短的": 0, "多一条": 0, "去掉反应": 0}
    out = []
    for r in s2:
        key = (r["id"], r["src"])
        r = dict(r)
        if key in old and not aligned(old[key].get("ctx") or [], r.get("ctx") or []):
            r["ctx"] = old[key]["ctx"]
            stat["长前文换回短的"] += 1
        ls = list(labels.get(key) or [])
        if not ls:
            stat["没标签（照旧句子卡）"] += 1
        else:
            reacts = [x for x in ls if x.startswith("反应")]
            if len(ls) >= 2 and reacts and rng.random() < 0.15:
                ls.remove(reacts[0])
                stat["去掉反应"] += 1
            elif rng.random() < 0.05:
                ls.append(rng.choice(pool))
                stat["多一条"] += 1
            r["card"] = with_labels(r["card"], ls)
        if romance(r):
            stat["恋爱话题去掉"] += 1
            continue
        out.append(r)
    gold = jl(os.path.join(R8, "gold.jsonl"))
    out += gold
    wjl(os.path.join(dst, "stage2.jsonl"), out)
    s1 = jl(os.path.join(src, "stage1.jsonl"))
    s1n = [r for r in s1 if not romance(r)]
    wjl(os.path.join(dst, "stage1.jsonl"), s1n)
    stat.update({"金数据": len(gold), "K 现在": len(out), "复习": len(s1n), "复习恋爱去掉": len(s1) - len(s1n),
                 "来源": {s: sum(r["src"] == s for r in out) for s in ("novel", "curated", "curated_old")}})
    json.dump(stat, open(os.path.join(R8, "info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(stat, ensure_ascii=False), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gold", "exam", "pack"])
    a = ap.parse_args()
    {"gold": cmd_gold, "exam": cmd_exam, "pack": cmd_pack}[a.cmd]()


if __name__ == "__main__":
    main()
