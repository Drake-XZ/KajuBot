"""精简提示词 A/B（2026-11-07）：现在的人设卡 + 说话规则 对 两三句身份 + 按话题想起的"关于自己"，谁写的草稿更像人。

    <bot venv>\\python.exe -I build_prompt_ab.py OUT.jsonl [--n 20]

- 现状组 cur：线上真实系统提示快照（kaju_basics browse.json 的 voice，11-06 04:58 兄长私聊）里的
  安全声明 + 人设卡 + 说话规则段（称呼规则 / 说话要有变化 / 说话节奏 / 佳树的句子 / 佳树的语气 / 深夜关心）。
- 精简组 min：同一段安全声明 + 两三句身份 + 用 bge-m3 从 64 条"关于自己"里按最近几句话检索的前 5 条。
- 两组都去掉快照里那一刻的动态内容（日记、心情、日程、备忘、珍藏、喜好、群和工具说明），只比"规则"这一个变量。
- 两组拿同样的聊天上下文，用 deepseek-flash（开思考，和线上主回复一样）写草稿；草稿再走同一条路：
  新规则抽卡 → kaju-writer-l1c 照卡写 → 线上同一份核对 → 没过就发草稿。
- 题目：kaju_life 日志里佳树当时真的回了的私聊（兄长）和群聊时刻，跳过 ab5 出过的。
"""
import argparse
import asyncio
import glob
import json
import math
import os
import random
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_layered_eval as ev  # noqa: E402  (live_rw / card / ds / local / guard)

ROOT = r"D:\JiashuBot"
PD = os.path.join(ev.CORE, "data", "plugin_data")
OWNER = "111111111"
STYLE_SECTIONS = ["称呼规则", "说话要有变化", "说话节奏", "佳树的句子", "佳树的语气", "深夜关心"]
MINIMAL = ("你是温水佳树，初三，学生会副会长。你在 QQ 上和兄长大人（你的哥哥）聊天，也在他和朋友们的群里聊天。\n"
           "不说自己是 AI、模型或助手。")


def current_system():
    snap = json.load(open(os.path.join(PD, "astrbot_plugin_kaju_basics", "browse.json"), encoding="utf-8"))["voice"]["system"]
    head, _, rest = snap.partition("# Persona Instructions")
    persona = rest.split("\n【", 1)[0].split("\n## Skills", 1)[0]  # 后面是技能列表和表情包选图说明，不算人设和说话规则
    parts = {m.group(1): m.group(0) for m in re.finditer(r"【([^】]+)】.*?(?=\n【|\Z)", snap, re.S)}
    style = []
    for name in STYLE_SECTIONS:
        hit = next((v for k, v in parts.items() if k.startswith(name)), None)
        if hit:
            style.append(hit.strip())
    return head.strip(), (head + "# Persona Instructions" + persona).strip() + "\n\n" + "\n\n".join(style)


def embed(texts):
    body = json.dumps({"model": "bge-m3", "input": texts}).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:11435/api/embed", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["embeddings"]


def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


def addr_of():
    addr = json.load(open(os.path.join(PD, "astrbot_plugin_address_book", "addresses.json"), encoding="utf-8"))
    names = json.load(open(os.path.join(PD, "astrbot_plugin_kaju_life", "names.json"), encoding="utf-8"))
    out = {}
    for uid, n in (names.get("people") or {}).items():
        a = (addr.get(uid) or {}).get("address") if isinstance(addr.get(uid), dict) else ""
        out[uid] = "兄长大人" if uid == OWNER else (a or n)
    return out


def moments(rng, n, exclude):
    titles = addr_of()
    out = []
    for p in sorted(glob.glob(os.path.join(PD, "astrbot_plugin_kaju_life", "log", "*.jsonl"))):
        rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
        by = {}
        for r in rows:
            by.setdefault(r["c"], []).append(r)
        for chat, rs in by.items():
            if not (chat == "p" + OWNER or chat.startswith("g")):
                continue
            for i, r in enumerate(rs):
                if r.get("u") != "self" or i == 0 or rs[i - 1].get("u") == "self" or len(rs[i - 1].get("x", "")) < 2:
                    continue
                ctx = []
                for c in rs[max(0, i - 6):i]:
                    who = "佳树" if c.get("u") == "self" else titles.get(str(c.get("u")), c.get("n") or "群友")
                    ctx.append(f"{who}：{re.sub(r'&&[^&]*&&', '', c.get('x', '')).strip()}")
                if "|".join(ctx[-2:]) in exclude:
                    continue
                to = titles.get(str(rs[i - 1].get("u")), rs[i - 1].get("n") or "群友")
                out.append({"id": f"pa-{os.path.basename(p)[:-6]}-{i}-{chat[:1]}", "kind": "私聊" if chat.startswith("p") else "群聊",
                            "to": to, "ctx": ctx, "real": r.get("x", "")})
    priv = [o for o in out if o["kind"] == "私聊"]
    grp = [o for o in out if o["kind"] == "群聊"]
    rng.shuffle(priv)
    rng.shuffle(grp)
    return priv[: n - n // 3] + grp[: n // 3]


async def draft(system, item):
    user = ("聊天记录（最后一句是刚收到的）：\n" + "\n".join(item["ctx"]) +
            f"\n\n现在轮到你在{'和兄长大人的私聊' if item['kind'] == '私聊' else '群'}里回话。直接写你要发的消息。")
    r = await ev.ds.chat.completions.create(model="deepseek-flash", messages=[
        {"role": "system", "content": system}, {"role": "user", "content": user}])
    return ev.live_rw.clean_output(r.choices[0].message.content or "")


async def through_writer(item, d):
    ctx, title, kind = item["ctx"], item["to"], item["kind"]
    said = ctx[-1].split("：", 1)[-1]
    c = ev.card.parse(await ev.ds_chat(ev.card.EXTRACT, ev.card.extract_prompt(ctx, d, kind, title), 0.3))
    card_text = ev.card.render(c, kind, title) if c else ""
    if not card_text:
        return {"text": d, "draft": d, "card": "", "fell_back": "没抽出卡"}
    raw = ev.card.fix_formal(ev.live_rw.clean_output(ev.local("kaju-writer-l1c", ev.card.WRITE_SYSTEM[2],
                                                               ev.card.write_prompt(ctx, card_text))), d, title)
    res = await ev.finish(raw, d, said, title, ctx, ok=ev.card.sane(raw, d))
    return {**res, "draft": d, "card": card_text}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=20)
    a = ap.parse_args()
    _, cur_sys = current_system()
    head, _ = current_system()
    facts = [f["fact"] for f in json.load(open(os.path.join(ROOT, "voice_train", "data", "layered_v1", "self_facts_final.json"),
                                               encoding="utf-8"))]
    fvec = embed(facts)
    used = {"|".join(x["ctx"][-2:]) for x in json.load(open(os.path.join(ROOT, "voice_train", "data", "ab5_items.json"), encoding="utf-8"))}
    items = moments(random.Random(23), a.n, used)
    print(f"现状组系统提示 {len(cur_sys)} 字；精简组身份 {len(MINIMAL)} 字 + 5 条事实；题 {len(items)} 道")
    rows = []
    for i, it in enumerate(items, 1):
        q = embed(["\n".join(it["ctx"][-3:])])[0]
        top = sorted(range(len(facts)), key=lambda k: -cos(q, fvec[k]))[:5]
        min_sys = head + "\n\n" + MINIMAL + "\n\n【你记得的关于自己】\n" + "\n".join("- " + facts[k] for k in top)
        d_cur, d_min = await asyncio.gather(draft(cur_sys, it), draft(min_sys, it))
        cur, mn = await asyncio.gather(through_writer(it, d_cur), through_writer(it, d_min))
        rows.append({**it, "facts": [facts[k] for k in top], "cands": {"cur": cur, "min": mn}})
        print(f"{i}/{len(items)} {it['kind']} 退回草稿 cur={bool(cur['fell_back'])} min={bool(mn['fell_back'])}")
    with open(a.out, "x", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"共 {len(rows)} 题 → {a.out}")


if __name__ == "__main__":
    asyncio.run(main())
