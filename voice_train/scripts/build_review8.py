r"""第八批标注：看完视频 / 歌 / 动图之后的感想，兄长大人挑一个最像她的、或者自己写一句。

2026-11-11 起因：她看完东西的回复 AI 味重。查下来——以前带视频链接的 16 轮全都没过写手（回晚了就跳过），发的是 DeepSeek 原稿；
过了写手也不行：要点卡里四五条要点，写手逐条照着写，像念清单。写手没见过"看完感想"这种卡。
这一批给它这类数据：感受卡（情绪 + 一两条要点，来自全模态模型写的"看的时候心里的感觉"）→ 她该怎么说。

每条给三个候选（顺序打乱）：两个是本地写手照同一张感受卡写的（同一张卡的两种说法 → 偏好对），一个是 DeepSeek 照感受直接写的（现在线上的做法）。
兄长：点一个最像她的；都不像就在框里自己写；素材不好就"这条不要"。

    python -I build_review8.py feel     全模态把素材都看一遍 → data/review8_felt.json（素材在 bot_setup/tools/omni_compare/media，清单 samples_r8.json）
    python -I build_review8.py cand     感受卡 + 三个候选 → data/review8_items.json、data/review8_key.json
    python -I build_review8.py page     → review/review8.html
"""
import asyncio
import json
import os
import random
import re
import sqlite3
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
VT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = r"D:\JiashuBot\bot_setup"
OC = os.path.join(SETUP, "tools", "omni_compare")
CORE = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
sys.path.insert(0, SETUP)
os.environ["KAJU_DATA"] = r"D:\JiashuBot\kaju_data"
FELT = os.path.join(VT, "data", "review8_felt.json")
ITEMS = os.path.join(VT, "data", "review8_items.json")
KEY = os.path.join(VT, "data", "review8_key.json")
WRITER = "kaju-writer-l1a-r003"

from kaju_core.senses import omni  # noqa: E402
from kaju_core.voice import card  # noqa: E402

# 全模态写的感受（心情那边的说法）→ 要点卡上的情绪
EMO = {"兴奋": "开心", "安心": "平常", "平静": "平常", "害怕": "担心", "失落": "难过", "烦": "无奈", "后悔": "难过"}


def load(p, default):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def save(p, d):
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def samples():
    S = json.load(open(os.path.join(OC, "samples_r8.json"), encoding="utf-8"))
    shelf = json.load(open(r"D:\JiashuBot\kaju_data\self\memory_weight\state.json", encoding="utf-8"))["shelf"]
    shelf = list(shelf.values()) if isinstance(shelf, dict) else shelf
    out = []
    for s in S:
        it = shelf[s["shelf"]] if "shelf" in s else {}
        m = re.search(r"《(.+?)》", str(it.get("content") or ""))
        s["title"] = s.get("title") or (m.group(1) if m else "")
        s["said"] = str(it.get("said") or "")
        s["reply_then"] = str(it.get("reply") or "")
        audio = bool(s.get("audio_only"))
        s["path"] = (os.path.join(OC, "media", "small", s["id"] + ".mp3") if audio else
                     os.path.join(OC, "media", "small", s["id"] + ".mp4") if s["ext"] == ".gif" else
                     os.path.join(OC, "media", s["id"] + s["ext"]))
        s["media"] = "audio" if audio else "video"
        s["what"] = "歌" if audio else "动图" if s["ext"] == ".gif" else "视频"
        if os.path.exists(s["path"]):
            out.append(s)
    return out


# ------------------------------------------------------------ 看一遍
async def feel():
    felt = load(FELT, {})
    cfg = {"omni_effort": "low", "omni_timeout": 120}
    tmp = tempfile.mkdtemp()
    sem = asyncio.Semaphore(2)

    async def one(s):
        if s["id"] in felt:
            return
        async with sem:
            try:
                p = await omni.feel(s["path"], s["media"], cfg, tmp, "" if s["media"] == "audio" else s["title"])
            except Exception as e:  # noqa: BLE001
                print("FAIL", s["id"], type(e).__name__, str(e)[:120], flush=True)
                return
        felt[s["id"]] = p
        save(FELT, felt)
        print("ok", s["id"], p["emotion"], p["intensity"], p["secs"], "s", p["usage"], flush=True)

    await asyncio.gather(*(one(s) for s in samples()))
    print(len(felt), "条有感受")


# ------------------------------------------------------------ 感受卡 + 候选
def own_words(said: str) -> str:
    """他发视频时自己说的话（去掉链接和分享卡的标题）。"""
    keep = [ln for ln in said.split("\n") if "复制打开抖音" not in ln]  # 抖音分享口令那一整行都不是他说的话
    x = re.sub(r"https?://\S+", "", "\n".join(keep))
    x = re.sub(r"【[^】]*】", "", x)
    x = re.sub(r"【[^】]*$|^[^【]*】", "", x, flags=re.M)  # 标题里又套了括号、或者被截断的分享卡：剩下的半截也去掉
    return " ".join(x.split())


def felt_card(s: dict, p: dict) -> tuple[list[str], str, dict]:
    """→ (上下文, 要点卡, 卡的内容)。要点最多两条：感觉最强的那一下 + 看完留下的。"""
    said = own_words(s["said"])
    if s["src"] == "browse":
        ctx = ["兄长大人：佳树刚才刷到什么了呀"]
        reply_to = "刚才刷到什么"
    else:
        ctx = [f"兄长大人：[分享了{"一首歌" if s["what"] == "歌" else "一个" + s["what"]}] {said}".rstrip()]
        reply_to = said[:20] or f"分享的{s['what']}"
    ms = p.get("moments") or []
    best = max(ms, key=lambda m: m["strength"]) if ms else None
    me = lambda x: re.sub(r"我", "佳树", x)  # noqa: E731
    points = []
    if best:
        points.append(me(f"{best['what']}，{best['feel']}"))
    if p.get("after"):
        points.append(me(p["after"]))
    emo = EMO.get(p["emotion"], p["emotion"])
    if emo == "开心" and "搞笑" in (p.get("genre") or ""):
        emo = "好笑"
    c = {"reply_to": reply_to, "emotion": card._words([emo], card.EMOTIONS) or ["平常"], "attitude": ["分享"],
         "points": points[:2], "ask": "", "to": "兄长大人"}
    return ctx, card.render(c, "私聊", "兄长大人"), c


async def cand():
    from openai import AsyncOpenAI

    felt, items, key = load(FELT, {}), load(ITEMS, []), load(KEY, {})
    done = {it["id"] for it in items}
    cfg = json.load(open(os.path.join(CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src = next(x for x in cfg["provider_sources"] if x["id"] == "deepseek_source")
    k = src.get("key") or src.get("api_key")
    ds = AsyncOpenAI(api_key=k[0] if isinstance(k, list) else k, base_url=src["api_base"])
    local = AsyncOpenAI(api_key="ollama", base_url="http://127.0.0.1:11435/v1", timeout=120)
    db = sqlite3.connect("file:" + os.path.join(CORE, "data", "data_v4.db") + "?mode=ro", uri=True)
    persona = db.execute("select system_prompt from personas where persona_id='default'").fetchone()[0]
    rnd = random.Random(20261111)

    async def write(ctx, card_text, temp):
        r = await local.chat.completions.create(model=WRITER, temperature=temp, messages=[
            {"role": "system", "content": card.WRITE_SYSTEM[2]}, {"role": "user", "content": card.write_prompt(ctx, card_text)}])
        return card.fix_formal((r.choices[0].message.content or "").strip(), "", "兄长大人")

    for s in samples():
        sid = "r8-" + s["id"]
        if sid in done or s["id"] not in felt:
            continue
        p = felt[s["id"]]
        ctx, card_text, c = felt_card(s, p)
        w1 = await write(ctx, card_text, 0.7)
        w2 = w1
        for t in (0.9, 1.0, 1.1):
            w2 = await write(ctx, card_text, t)
            if w2 != w1:
                break
        said = ctx[0].split("：", 1)[1]
        material = omni.render(p, "一段", s["media"], 2)
        user = (f"{said}\n<system_reminder>\n[你刚看完的{s['what']}] {material}\n"
                "回他的时候说你自己看完的感受，像平时聊天那样，不要把内容讲一遍。\n</system_reminder>")
        r = await ds.chat.completions.create(model="deepseek-flash", messages=[
            {"role": "system", "content": persona}, {"role": "user", "content": user}])
        d = (r.choices[0].message.content or "").strip()
        opts = [("w1", w1), ("w2", w2), ("ds", d)]
        rnd.shuffle(opts)
        key[sid] = [o[0] for o in opts]
        best = max(p["moments"], key=lambda m: m["strength"]) if p.get("moments") else None
        items.append({
            "id": sid, "src": s["src"], "what": s["what"], "title": s["title"], "ctx": ctx, "card": card_text,
            "user": card.write_prompt(ctx, card_text), "felt": {
                "emotion": p["emotion"], "intensity": p["intensity"], "moment": (f"{best['t']} {best['what']}：{best['feel']}" if best else ""),
                "after": p.get("after", ""), "facts": p.get("facts", "")},
            "cands": [o[1].replace("\n", " / ") for o in opts], "reply_then": s["reply_then"].replace("\n", " / "),
        })
        save(ITEMS, items)
        save(KEY, key)
        print(sid, "ok", [len(o[1]) for o in opts], flush=True)
    print(len(items), "条 →", ITEMS)


def page():
    items = load(ITEMS, [])
    show = [{k: it[k] for k in ("id", "what", "title", "ctx", "felt", "cands")} for it in items]
    tpl = open(os.path.join(VT, "review", "review8.template.html"), encoding="utf-8").read()
    out = tpl.replace("/*ITEMS*/", json.dumps(show, ensure_ascii=False).replace("</", "<\\/"))
    open(os.path.join(VT, "review", "review8.html"), "w", encoding="utf-8", newline="\n").write(out)
    print(len(show), "条 → review/review8.html")


if __name__ == "__main__":
    step = sys.argv[1]
    if step == "page":
        page()
    else:
        asyncio.run({"feel": feel, "cand": cand}[step]())
