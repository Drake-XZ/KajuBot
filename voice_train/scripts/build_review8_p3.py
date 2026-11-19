r"""第八批标注的候选，换成新写手 8b-A + 第三版格式的短卡重写（2026-11-11 兄长定：走 8b-A；看完东西的卡要短）。

短卡怎么来（兄长 11-11 定的）：
  要说到的  只放一两处最强的感受——按全模态给的强弱取最强的两处（不让模型挑），DeepSeek 只负责压成短事实，不添东西、不重排。
  局面      谁分享了什么、佳树刚看完、看的时候心情怎样有多强、看完喜不喜欢。说多说少以后靠这一栏学。
  长短      兄长不要这一栏。但现在的 8b-A 训练时每张卡都有，所以出候选时临时按感受强弱填；
            进训练数据的卡（card_gold）不带这一栏。
三个候选：两个 8b-A 照同一张短卡写的（偏好对），一个沿用上一版 DeepSeek 直接写的（线上原来的做法）。

    python -I build_review8_p3.py card    感受 → 短卡 → data/review8_cards_p3.json（DeepSeek 压要点，30 次调用）
    python -I build_review8_p3.py cand    8b-A 照卡写 → data/review8_items.json、review8_key.json（旧的先改名 *_r003.json 留底）
    python -I build_review8_p3.py page    → review/review8.html
"""
import asyncio
import json
import os
import random
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_review8 as b8  # noqa: E402  (samples、own_words、load、save、page)

VT = b8.VT
CARDS = os.path.join(VT, "data", "review8_cards_p3.json")
WRITER = "kaju-writer-p3-8b-a"
SYS3 = json.load(open(os.path.join(VT, "train_pack", "kaju_train_pack", "data", "system.json"), encoding="utf-8"))["2"]
TOP = 2  # 取最强的几处感受
LENGTH = {1: "简短", 2: "正常", 3: "长"}  # 临时：现在的写手必须看到这一栏

SHORTEN = """你在给一个写手准备材料卡。下面是佳树（一个女孩）看完一段内容后记下的感受。把它压成卡上的两栏，只压缩，不添加任何感受里没有的东西，不改顺序。

局面：一两句话，写清——谁给佳树分享了什么（或者佳树自己刷到了什么）、这是个什么内容（十来个字）、佳树刚看完、看的时候心情怎样有多强、看完喜不喜欢这类东西。最后以"轮到佳树回。"结尾。第三人称，叫她"佳树"。
要说到的：只压"最强的感受"下面列出的那几处，一处一条，给几处就写几条；不要把整体心情或"看完之后"写成一条（那些已经在局面里）。每条 10 到 22 个字，写成"哪一下 + 佳树怎样"，用平常说话的词，读起来通顺，不要为了短把字省成电报（不写"愣后笑出""觉代码藏心跳"这种）。感受里的"我"是佳树，写成"佳树"；引号里别人说的话原样保留。

参考卡的样子（别的题）：
局面：兄长大人刚说下周课少不是回家、晚上能视频，并问佳树几点下课，轮到佳树回答。
要说到的：佳树不请假了；佳树九点才下补习班

只输出 JSON：{"局面": "...", "要说到的": ["...", "..."]}"""


def top_moments(p):
    ms = sorted(p.get("moments") or [], key=lambda m: -m["strength"])  # sorted 是稳定的：一样强的按出现先后
    return ms[:TOP]


async def cards():
    from openai import AsyncOpenAI

    felt, out = b8.load(b8.FELT, {}), b8.load(CARDS, {})
    cfg = json.load(open(os.path.join(b8.CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src = next(x for x in cfg["provider_sources"] if x["id"] == "deepseek_source")
    k = src.get("key") or src.get("api_key")
    ds = AsyncOpenAI(api_key=k[0] if isinstance(k, list) else k, base_url=src["api_base"])
    strong = {1: "淡淡的", 2: "比较明显", 3: "很强"}
    for s in b8.samples():
        if s["id"] in out or s["id"] not in felt:
            continue
        p = felt[s["id"]]
        said = b8.own_words(s["said"])
        how = "佳树自己刷B站刷到的，兄长大人问她刚才刷到什么" if s["src"] == "browse" else (
            f"兄长大人分享给佳树的{s['what']}" + (f"，他说：{said}" if said else "，他什么都没说"))
        ms = top_moments(p)
        user = "\n".join([
            f"来历：{how}", f"是什么：{p.get('facts', '')}",
            f"整体心情：{p['emotion']}，{strong.get(p['intensity'], '比较明显')}", f"看完之后：{p.get('after', '')}",
            "最强的感受（就压这几处）：", *([f"- {m['what']}——{m['feel']}" for m in ms] or [f"- {p.get('after', '')}"])])
        r = await ds.chat.completions.create(model="deepseek-flash", temperature=0.2, messages=[
            {"role": "system", "content": SHORTEN}, {"role": "user", "content": user}])
        m = re.search(r"\{.*\}", r.choices[0].message.content or "", re.S)
        try:
            g = json.loads(m.group(0))
            pts = [str(x).strip("。 ") for x in g["要说到的"]][:max(1, len(ms))]
            scene = str(g["局面"]).strip()
        except Exception:  # noqa: BLE001
            print("FAIL", s["id"], (r.choices[0].message.content or "")[:100], flush=True)
            continue
        out[s["id"]] = {"局面": scene, "要说到的": pts, "intensity": p["intensity"], "emotion": p["emotion"],
                        "picked": [f"{m['t']} {m['what']}：{m['feel']}（强度 {m['strength']}）" for m in ms]}
        b8.save(CARDS, out)
        print(s["id"], "|", scene, "|", "；".join(pts), flush=True)
    print(len(out), "张短卡 →", CARDS)


def render(c, with_length=True):
    lines = ["场合：私聊", "对象：兄长大人", "局面：" + c["局面"], "要说到的：" + ("；".join(c["要说到的"]) or "无")]
    if with_length:
        lines.append("长短：" + LENGTH.get(c["intensity"], "正常"))
    return "\n".join(lines)


def write(ctx, card_text, temp):
    body = {"model": WRITER, "temperature": temp, "top_p": 0.9, "max_tokens": 220, "reasoning_effort": "none", "messages": [
        {"role": "system", "content": SYS3},
        {"role": "user", "content": "聊天：\n" + ("\n".join(ctx) or "（没有前文）") + "\n\n材料：\n" + card_text}]}
    req = urllib.request.Request("http://127.0.0.1:11435/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer local"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return (json.load(r)["choices"][0]["message"]["content"] or "").strip()


def cand():
    cards_, felt = b8.load(CARDS, {}), b8.load(b8.FELT, {})
    old_items = {it["id"]: it for it in b8.load(b8.ITEMS.replace(".json", "_r003.json"), None) or b8.load(b8.ITEMS, [])}
    old_key = b8.load(b8.KEY.replace(".json", "_r003.json"), None) or b8.load(b8.KEY, {})
    for p in (b8.ITEMS, b8.KEY):  # 旧格式 r003 写的那版留底，只留第一次的
        bak = p.replace(".json", "_r003.json")
        if os.path.exists(p) and not os.path.exists(bak):
            os.replace(p, bak)
    rnd = random.Random(2026111102)
    items, key = [], {}
    for s in b8.samples():
        sid = "r8-" + s["id"]
        if s["id"] not in cards_ or sid not in old_items:
            continue
        c, p, old = cards_[s["id"]], felt[s["id"]], old_items[sid]
        ctx = old["ctx"]
        card_text = render(c)
        w1 = write(ctx, card_text, 0.7)
        w2 = w1
        for t in (0.9, 1.0, 1.1):
            w2 = write(ctx, card_text, t)
            if w2 != w1:
                break
        d = old["cands"][old_key[sid].index("ds")]  # DeepSeek 直接写的那句沿用
        opts = [("w1", w1), ("w2", w2), ("ds", d)]
        rnd.shuffle(opts)
        key[sid] = [o[0] for o in opts]
        ms = top_moments(p)
        items.append({
            "id": sid, "src": s["src"], "what": s["what"], "title": s["title"], "ctx": ctx, "card": card_text, "card_gold": render(c, False),
            "user": "聊天：\n" + "\n".join(ctx) + "\n\n材料：\n" + card_text, "format": "p3", "writer": WRITER,
            "felt": {"emotion": p["emotion"], "intensity": p["intensity"],
                     "moment": "　".join(f"{m['t']} {m['what']}：{m['feel']}" for m in ms),
                     "after": p.get("after", ""), "facts": p.get("facts", "")},
            "cands": [o[1].replace("\n", " / ") for o in opts], "reply_then": old.get("reply_then", ""),
        })
        b8.save(b8.ITEMS, items)
        b8.save(b8.KEY, key)
        print(sid, [len(o[1]) for o in opts], "|", w1.replace("\n", " / "), flush=True)
    print(len(items), "条 →", b8.ITEMS)


if __name__ == "__main__":
    step = sys.argv[1]
    if step == "card":
        asyncio.run(cards())
    elif step == "cand":
        cand()
    else:
        b8.page()
