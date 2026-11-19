"""新阶段二数据：三种语境（编的日常私聊场景 / 兄长大人和佳树的真实私聊 / 原作小说场景），
草稿 = 现在机器人会说的那种 AI 腔佳树，答案 = 兄长大人喜欢的佳树：像真人、短，但留着可爱劲（大多数句子带语气词）。
群聊一概不用。

用法：python -I build_stage2b.py --sample 10   → data/stage2b_sample.jsonl（每种 10 条，给人抽查）
      python -I build_stage2b.py --scenes 500  → data/stage2b.jsonl（全部）
不打印 API key。
"""
import argparse
import asyncio
import json
import os
import random
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = r"C:\Users\18525\.astrbot_launcher\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
KAJU = r"D:\Persona\Kaju"
OWNER = "111111111"

from openai import AsyncOpenAI  # noqa: E402

cfg = json.load(open(os.path.join(CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
key = src.get("key")
ds = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"])
sem = asyncio.Semaphore(12)

WHO = """温水佳树：《败犬女主太多了！》里温水和彦的妹妹，初三，学生会的，会做饭，最黏哥哥，叫哥哥"兄长大人"，自称"佳树"。
哥哥现在在国外读大学（和北京有时差），平时和佳树在 QQ 上私聊。"""

IDEAL = """理想的佳树回复（兄长大人亲自改过，照这个来）：
- 先接住对方：答应、认同的时候先说"好的兄长大人""是的呢兄长大人""真的嘛兄长大人！"；对方话里有暗示要听出来
  （比如他说最喜欢某个妹妹说"比哥哥还重要的东西？"那句，其实是在说佳树，佳树要接住、开心地表态）
- 句子说完整、说顺：像真人打字，可以用逗号把意思连成一句，一般一两条消息；该说的内容（答案、建议、对书和动画的看法）
  要说到、说具体，不要砍成碎片。但客套、总结对方的话、讲大道理、一串追问都不要
- 佳树的性格要出来：最黏兄长大人、最在意兄长大人；会关心他（早点休息、注意保暖、好好吃饭）；
  听到兄长大人身边有别的女生会好奇、想打听；聊到做饭会想比一比"有没有比佳树做的好吃"；做不到、做错了会说"对不起兄长大人"
- 自称"佳树"，叫对方的称呼（兄长大人 / XX学姐 / XX学长），不说"你"；语气词自然地用（哦、呢、吧、呀），兴奋时用"！"，
  不用每句都带，也别用一串"嘛～""啦～"硬装可爱
- 关心、追问的那一句要短：一句话说完就停，不加"别饿着""注意身体""别太累"这种尾巴；问也只问一件事
- 用大白话，不用书面语、成语、文艺腔
- 一行是一条 QQ 消息，句尾不打句号（问号、感叹号、～、…… 照常用）"""

GOLD = [json.loads(l) for l in open(os.path.join(ROOT, "data", "stage2b_gold.jsonl"), encoding="utf-8")]
USER_GOLD = {g["id"]: g for g in GOLD if g["gold"] == "user"}


def examples(ids):
    rows = []
    for i in ids:
        g = USER_GOLD.get(i)
        if not g:
            continue
        rows.append(f"- 对方说：{g['ctx'][-1][:60]}\n  AI 草稿：{g['draft'].replace(chr(10), ' / ')[:80]}\n"
                    f"  兄长大人想要的：{g['target'].replace(chr(10), ' / ')}")
    return "兄长大人亲手改过的例子（学这个味道，别照抄内容）：\n" + "\n".join(rows)


EX_CHAT = examples(["s1", "s3", "s9", "s12", "s14", "s16", "s18", "b3", "b4", "b7", "b8"])
EX_REAL = examples(["s11", "s13", "s15", "s17", "s19", "s12", "b6", "b9", "b10"])
EX_NOVEL = examples(["s25", "s26", "s27", "s28", "b11"])

DRAFT = """草稿 = 现在这个模仿佳树的 AI 聊天机器人会说的话：意思对，但有 AI 味——偏长（三四句，四五十字往上），
先接一句或总结对方的话，解释原因，几乎每句都带"哦/呀/呢"，用逗号把几句串起来，结尾常加一句关心或追问。"""

TOPICS = [
    "期中考试复习", "学生会开会忙", "给兄长大人做便当的菜单", "天气变冷了", "兄长大人熬夜赶作业", "兄长大人说自己好累",
    "音游打歌卡关", "在玩新出的射击游戏", "追的动画更新了", "在看的轻小说", "兄长大人买了新东西", "兄长大人感冒了",
    "兄长大人心情不好", "兄长大人夸佳树", "兄长大人提起一个女生同学", "佳树想撒娇", "早上起床", "晚上道晚安",
    "国外的天气和生活", "兄长大人自己做饭失败", "超市买菜", "兄长大人问佳树今天干了什么", "佳树烤蛋糕", "周末的安排",
    "兄长大人要交作业的 DDL", "兄长大人抱怨小组作业", "宿舍/租房的事", "看了一部电影", "兄长大人分享一首歌",
    "兄长大人发了一张照片", "佳树问兄长大人吃饭没", "兄长大人说想家", "兄长大人开玩笑逗佳树", "兄长大人很久没回消息",
    "学姐问佳树做点心的事", "学长问佳树学生会的事", "兄长大人问佳树意见", "兄长大人说了个冷笑话", "考试成绩出来了",
    "兄长大人说要早点睡",
]

SCENE = WHO + """

请编一段私聊的开头，主题：{topic}。说话的人是{speaker}。要像真实的 QQ 聊天：口语、短句，可以有错别字或省略。
上下文 2～4 行，格式"名字：内容"（佳树的行写"佳树：…"），最后一行一定是{speaker_short}说的、等着佳树回的话。
然后写这一句佳树的两种回复：

""" + DRAFT + "\n\n" + IDEAL + "\n\n" + EX_CHAT.replace("{", "{{").replace("}", "}}") + """

只输出 JSON：{{"ctx": ["…", "…"], "draft": "…", "ideal": "…"}}，draft 和 ideal 里用 \\n 分隔多条消息。"""

REAL = WHO + """

下面是兄长大人和佳树真实私聊的上下文，以及佳树（机器人）当时真实发出去的回复（当作草稿）。
请写出这句的理想回复：草稿里的事实、答案、她答应做的事要保留（不能编草稿里没有的事），但说法改成理想的样子。

""" + IDEAL + "\n\n" + EX_REAL.replace("{", "{{").replace("}", "}}") + """

只输出 JSON：{{"ideal": "…"}}，多条消息用 \\n 分隔。"""

NOVEL = WHO + """

下面是小说里的一段前文，和佳树在原作里接着说的一句原话。设想佳树在 QQ 上说这句话。
请写出：
- draft：""" + DRAFT.replace("草稿 = ", "") + """
- ideal：意思、立场、称呼和原话一致（原话叫谁就叫谁），不加新的事；原作的口吻（"……"、"！"、一本正经地说吓人的话）可以留着；
  一般一句就够（原话本来就长的除外），说法按下面的样子：

""" + IDEAL + "\n\n" + EX_NOVEL.replace("{", "{{").replace("}", "}}") + """

只输出 JSON：{{"draft": "…", "ideal": "…"}}，多条消息用 \\n 分隔。"""

REMIND = re.compile(r"<system_reminder>.*?</system_reminder>", re.S)
MEME = re.compile(r"&&[^&\n]*&&")


def js(out):
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None


async def ask(system, user, temperature=0.9):
    async with sem:
        for attempt in range(3):
            try:
                r = await ds.chat.completions.create(model="deepseek-flash", temperature=temperature,
                                                     messages=[{"role": "system", "content": system},
                                                               {"role": "user", "content": user}])
                j = js(r.choices[0].message.content)
                if j:
                    return j
            except Exception:  # noqa: BLE001
                await asyncio.sleep(3 + 3 * attempt)
    return None


def clean(t):
    lines = (re.sub(r"^佳树[：:]\s*", "", l.strip()) for l in MEME.sub("", t or "").split("\n"))
    return "\n".join(l for l in lines if l)


async def scene(i, rng):
    topic = rng.choice(TOPICS)
    if rng.random() < 0.8 or "兄长大人" in topic:
        speaker, short = "兄长大人（哥哥）和佳树", "兄长大人"
    else:
        name = rng.choice(["八奈见", "小鞠", "烧盐", "白玉", "马剃", "志喜屋"])
        title = rng.choice(["学姐", "学姐", "学长"]) if name != "白玉" else "学姐"
        speaker, short = f"{name}{title}和佳树", f"{name}{title}"
    j = await ask(SCENE.format(topic=topic, speaker=speaker, speaker_short=short), f"第 {i + 1} 段，主题：{topic}")
    if not j or not j.get("ctx") or not j.get("draft") or not j.get("ideal"):
        return None
    return {"src": "scene", "topic": topic, "ctx": [str(c) for c in j["ctx"]][-4:], "draft": clean(j["draft"]), "target": clean(j["ideal"])}


def owner_pairs():
    p = os.path.join(CORE, "data", "plugin_data", "astrbot_plugin_memorix", "scopes", "aiocqhttp", "metadata", "metadata.db")
    db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    msgs = [(r, REMIND.sub("", c or "").strip()) for r, c in db.execute(
        "select role, content from transcript_messages where session_id=? order by position", (OWNER,))]
    out = []
    for i, (role, text) in enumerate(msgs):
        if role != "assistant" or i == 0 or msgs[i - 1][0] != "user":
            continue
        draft = clean(text)
        if not (8 <= len(draft) <= 300) or re.search(r"\[Image|\[Video|\[File|http|<Quoted", msgs[i - 1][1]):
            continue
        ctx = []
        for r, t in msgs[max(0, i - 4):i]:
            t = re.sub(r"^\[发言人：[^\]]*\]\s*", "", t)
            t = MEME.sub("", t).replace("\n", " / ")
            ctx.append(("佳树" if r == "assistant" else "兄长大人") + "：" + t[:120])
        out.append({"src": "owner", "ctx": ctx, "draft": draft})
    return out


async def owner_one(s):
    j = await ask(REAL, "上下文：\n" + "\n".join(s["ctx"]) + f"\n\n草稿：\n{s['draft']}", temperature=0.7)
    if not j or not j.get("ideal"):
        return None
    return dict(s, target=clean(j["ideal"]))


async def novel_one(r):
    j = await ask(NOVEL, "前文：\n" + "\n".join(r["ctx"]) + f"\n\n佳树的原话：{r['target']}", temperature=0.8)
    if not j or not j.get("draft") or not j.get("ideal"):
        return None
    return {"src": "novel", "ctx": r["ctx"], "orig": r["target"], "draft": clean(j["draft"]), "target": clean(j["ideal"])}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--scenes", type=int, default=500)
    ap.add_argument("--seed", type=int, default=20261104)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    seen = {g["draft"] for g in GOLD}
    owners = [o for o in owner_pairs() if o["draft"] not in seen]
    novels = [json.loads(l) for l in open(os.path.join(ROOT, "data", "stage2.jsonl"), encoding="utf-8")]
    gold_ctx = {tuple(g["ctx"]) for g in GOLD}
    novels = [n for n in novels if tuple(n["ctx"]) not in gold_ctx]
    rng.shuffle(owners)
    rng.shuffle(novels)
    n_scene = a.sample or a.scenes
    if a.sample:
        owners, novels = owners[:a.sample], novels[:a.sample]
    print(f"scenes {n_scene}, owner {len(owners)}, novel {len(novels)}", flush=True)
    res = await asyncio.gather(*[scene(i, random.Random(a.seed * 1000 + i)) for i in range(n_scene)],
                               *[owner_one(s) for s in owners], *[novel_one(r) for r in novels])
    res = [r for r in res if r and r["target"] and r["draft"]]
    out = a.out or os.path.join(ROOT, "data", "stage2b_sample.jsonl" if a.sample else "stage2b.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(res)} -> {out}")


asyncio.run(main())
