"""第三版训练数据：要点卡换成"局面 + 要说到的 + 长短"（减AI味完整方案-v2 第 2b 步，2026-11-10 兄长大人点头）。

参考 MaiBot 的 reply_reference（规划器只给局面和事实，不给要说的话）。训练目标不变，还是真人 / 原作 / 兄长认可的那句话；
变的是给写手的材料：DeepSeek **看着那句真话倒着写**——
  局面      只根据聊天写：聊到哪了、最后这句谁对谁说、为什么轮到她回。不写怎么回、什么语气。
  要说到的  那句话里、光看聊天自己想不出来的信息：事实、经历、打算、决定、对问题的是/否。一条一个短事实，不带说法。
            感受、评价、玩笑、关心、反问都不写——这些以后由写手自己定。
  长短      不调模型，按那句话的字数算（简短 / 正常 / 长）。
这样写手学到的是：信息照材料说、不编；怎么说、说不说感受，自己定。线上 DeepSeek 以后也只给这三样（不再写草稿）。
没有"背景"一栏：倒着写时分不出哪些背景没用上，训练里没有的东西线上也不给（MaiBot 的教训：线上多喂训练外的东西会变啰嗦）。

来源：data\\layered_v2 的 stage1（H：LCCC / 群聊 / 兄长私聊 / B站 / 贴吧）、stage2（K：原作 + 兄长的样本）、eval_*。
  stage1 同一句（上下文 + 回复都一样）只留一条；stage2 原来一句有几张卡的照旧留几条，温度 0.3 / 0.55 / 0.8 轮着用。
输出 data\\layered_v3\\：stage1.jsonl / stage2.jsonl / eval_*.jsonl（多一个 guide 字段和渲染好的 card 文本）、system.json、meta.json。
可以断了再跑：写好的指引存在 cache.jsonl。只用 deepseek-flash，关思考。
用法（AstrBot venv）：python -I build_guide_v3.py [--limit N] [--dry] [--wait-until HH:MM]
  --dry 只数要调多少次、估个价；--wait-until 等到本机这个时间再开始（空闲价 = 本机 03:30～11:30）
"""
import argparse
import asyncio
import datetime as dt
import glob
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_layered as bl  # noqa: E402

DATA = os.path.join(bl.VT, "data")
SRC = os.path.join(DATA, "layered_v2")
OUT = os.path.join(DATA, "layered_v3")
CACHE = os.path.join(OUT, "cache.jsonl")
TEMPS = (0.3, 0.55, 0.8)

HIND = """下面是一段聊天，和{me}接下来真的发出去的一句回复。
请倒着整理：在{me}开口之前，一个了解情况的人会递给{me}什么材料。以后会有人只看聊天和这份材料，自己把话说出来。
所以材料里要有{me}光看聊天想不出来的信息，但不能有{me}的说法。只输出 JSON：
{{"局面": "...", "要说到的": ["..."]}}

局面：一两句话，**只根据聊天写，不许用回复里才有的信息**。聊到哪了、最后这句是谁对谁说的、接的是前面哪句、为什么轮到{me}回。
  只描述到"轮到{me}回"为止：不写{me}接下来说了什么、问了什么、做了什么，不写{me}该怎么回、什么情绪、什么语气。
  最后一句里有"那个""他""你说的"这种指代，而且聊天里看得出指的是什么，顺手点明。

要说到的：回复里、光看聊天{me}自己想不出来的信息，一条一个短事实：
  - 外面的事实和知识（是什么、怎么做、名字、数字、时间、地点）。
  - {me}自己的事：经历过什么、做了什么、有什么、知道不知道、认不认识。
  - {me}的打算和决定：要去做什么、答应还是不答应、对一个是非问题答的是"是"还是"不是"。
  回复里有几条就写几条，一条都不能漏，也不能写回复里没有的。用自己的话概括成事实，不要照抄回复的句子，不带语气词和称呼。
  下面这些**不写**，写了就错：
  - 感受和评价（开心、担心、觉得好笑、觉得厉害、喜欢不喜欢这句话）。
  - 玩笑、吐槽、撒娇、夸人、安慰、关心、道谢、打招呼、附和（"确实""是的"）。
  - 反过来问对方的话。
  - 反问、疑问（回复整句是在问，就没有信息）。
  - 斗嘴、玩笑里的自夸自贬和夸张说法（那不是事实）。
  - 聊天里已经明说过、回复只是重复了一遍的内容。
  - 你对回复里名词的解释、你自己知道的知识、你的推测。每一条都必须是回复里明明白白说了的。
  回复只是在接话、表态、开玩笑，没有上面那三类信息：空数组 []。

例子（聊天最后一句 → 回复 → 要说到的）：
  "我正在加班" → "还在床上" → ["{me}还在床上"]　　　　　　　　（自己现在的状况，是信息；局面里不许提"在床上"）
  "好！" → "不好意思，换好了" → ["已经换好了"]　　　　　　　　　（做完了一件事，是信息）
  "你说我该不该蹭他饭" → "蹭吧蹭吧，人家都开口了，不吃反而见外" → ["觉得该蹭"]　（对"该不该"的回答是信息；理由是{me}的说法，不写）
  "居然没这个吗？" → "我还等了半天" → ["{me}等了半天"]
  "有天看少儿频道有播" → "少儿频道？？？" → []　　　　　　　　　（整句是反问）
  "就是太笨的对手呗" → "错，我是慷慨大方的对手" → []　　　　　　（斗嘴）
  "我这个周末要参加社团合宿" → "咦！？所以说，兄长大人终于交到朋友了吗？" → []　（对方说过的事不算，剩下的是反问）
  "那顿饭早吃过了" → "好的，那就放心了" → []　　　　　　　　　　（接话、感受）"""

WRITE_SYSTEM_V3 = {
    1: ("你是写手：看着聊天和局面，写出真人在聊天里会发的回复。“要说到的”里的事都要说到、不能说错；除此之外不编造已经发生的事、"
        "做过的事或别人说过的话。怎么接话、说不说自己的感受、怎么说，都由你定。长短、用词、语气像真人随手打的字。只输出回复。"),
    2: ("你是写手：看着聊天和局面，写出温水佳树（《败犬女主太多了！》里温水和彦的妹妹）会说的话。“要说到的”里的事都要说到、不能说错；"
        "除此之外不编造已经发生的事、做过的事或别人说过的话。怎么接话、说不说自己的感受、怎么说，都由你定。"
        "自称佳树，按场合自然使用对象的称呼，不说\"你\"；像她平时说话，也像真人随手打的字。只输出回复。"),
}


def field(card_text, name):
    m = re.search(rf"^{name}：(.*)$", card_text or "", re.M)
    v = m.group(1).strip() if m else ""
    return "" if v == "无" else v


def length_of(target):
    """长短按真话的字数算（不调模型）：12 字以内简短，45 字以内正常，再长算长。"""
    n = len(re.sub(r"\s", "", target or ""))
    return "简短" if n <= 12 else "正常" if n <= 45 else "长"


def render(kind, to, guide, length):
    """给写手看的材料（训练和线上同一个样子；放在 card 字段里，train_writer 的提示照旧拼）。"""
    return "\n".join([f"场合：{kind}", f"对象：{to or '无'}", f"局面：{guide['局面']}",
                      "要说到的：" + ("；".join(guide["要说到的"]) or "无"), f"长短：{length}"])


def parse(out):
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    if not isinstance(v, dict) or not str(v.get("局面") or "").strip():
        return None
    pts = v.get("要说到的")
    if pts is None:
        pts = v.get("要说到") or []
    if isinstance(pts, str):
        pts = [] if pts.strip() in ("", "无") else [pts]
    pts = [re.sub(r"\s+", " ", str(x)).strip().rstrip("。") for x in pts if str(x).strip() and str(x).strip() != "无"]
    return {"局面": re.sub(r"\s+", " ", str(v["局面"])).strip(), "要说到的": pts}


class Cache:
    def __init__(self):
        os.makedirs(OUT, exist_ok=True)
        self.d = {r["key"]: r for r in bl.load(CACHE)}
        self.f = open(CACHE, "a", encoding="utf-8")

    def put(self, row):
        self.d[row["key"]] = row
        self.f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.f.flush()


def job_of(row, temp, me):
    kind = field(row.get("card", ""), "场合") or row.get("kind") or "群聊"
    to = field(row.get("card", ""), "对象") or row.get("to") or ""
    return {"key": f"h3|{me}|{temp}|{kind}|{to}|{bl.ctx_key(row.get('ctx') or [])}|{(row.get('target') or '').strip()}",
            "kind": kind, "to": to, "ctx": row.get("ctx") or [], "target": row.get("target") or "", "temp": temp, "me": me}


async def run_job(j, cache):
    if j["key"] in cache.d:
        return cache.d[j["key"]]
    user = (f"场合：{j['kind']}\n{j['me']}在回的人：{j['to'] or '无'}\n\n聊天：\n" + "\n".join(j["ctx"] or ["（没有前文）"]) +
            f"\n\n{j['me']}发出去的回复：\n{j['target']}")
    g = None
    for t in (j["temp"], 0.5):
        g = parse(await bl.ask(HIND.format(me=j["me"]), user, t))
        if g:
            break
    out = {"key": j["key"], "guide": g}
    cache.put(out)
    return out


def plan_part(name, rows):
    """[(row, job)]。stage1 同一句只留一条；别的部分同一句的第 N 条用第 N 个温度。"""
    me = "我" if name.startswith("stage1") else "佳树"
    out, seen = [], {}
    for r in rows:
        if not (r.get("target") or "").strip():
            continue
        k = (bl.ctx_key(r.get("ctx") or []), r["target"].strip())
        n = seen.get(k, 0)
        seen[k] = n + 1
        if name.startswith("stage1") and n:
            continue
        out.append((r, job_of(r, TEMPS[min(n, len(TEMPS) - 1)], me)))
    return out


def wait_until(hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    now = dt.datetime.now()
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if at <= now:
        at += dt.timedelta(days=1)
    print(f"{now:%H:%M} 等到 {at:%m-%d %H:%M} 再开始（空闲价时段）", flush=True)
    time.sleep((at - now).total_seconds())


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="每部分只做前 N 条（试跑）")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--conc", type=int, default=24)
    ap.add_argument("--wait-until", default="")
    ap.add_argument("--pool", action="store_true", help="语料池（data\daily\pool.jsonl）里还没进 stage1 的真人样本 → stage1_pool.jsonl")
    a = ap.parse_args()
    bl.SEM = asyncio.Semaphore(a.conc)
    if a.pool:
        have = {(bl.ctx_key(r.get("ctx") or []), (r.get("target") or "").strip()) for r in bl.load(os.path.join(OUT, "stage1.jsonl"))}
        rows = [r for r in bl.load(os.path.join(DATA, "daily", "pool.jsonl"))
                if (bl.ctx_key(r.get("ctx") or []), (r.get("target") or "").strip()) not in have]
        parts = {"stage1_pool": rows}
    else:
        parts = {os.path.basename(p)[:-6]: bl.load(p) for p in sorted(glob.glob(os.path.join(SRC, "*.jsonl")))
                 if os.path.basename(p) != "cache.jsonl"}
    if a.limit:
        step = {k: max(1, len(v) // a.limit) for k, v in parts.items()}
        parts = {k: v[::step[k]][:a.limit] for k, v in parts.items()}  # 隔着取，各种来源都试到
    plan = {name: plan_part(name, rows) for name, rows in parts.items()}
    cache = Cache()
    uniq = {j["key"]: j for jobs in plan.values() for _, j in jobs}
    todo = [j for k, j in uniq.items() if k not in cache.d]
    print(f"共 {sum(len(v) for v in plan.values())} 条（" + "，".join(f"{k} {len(v)}" for k, v in plan.items()) +
          f"）；不同的指引 {len(uniq)} 份，已写 {len(uniq) - len(todo)}，要写 {len(todo)}", flush=True)
    print(f"约 {len(todo)} 次 DeepSeek 调用；按第二版重抽卡的价（36195 次 15.81 元，空闲价）约 {len(todo) / 36195 * 15.81:.1f} 元，高峰 ×2", flush=True)
    if a.dry:
        return
    if a.wait_until:
        wait_until(a.wait_until)
    t0, done = time.time(), [0]

    async def tracked(j):
        r = await run_job(j, cache)
        done[0] += 1
        if done[0] % 1000 == 0:
            el = time.time() - t0
            print(f"  {time.strftime('%H:%M:%S')} {done[0]}/{len(todo)}，已用 {el / 60:.0f} 分钟，"
                  f"预计还要 {el / done[0] * (len(todo) - done[0]) / 60:.0f} 分钟；{bl.cost()}", flush=True)
        return r
    for i in range(0, len(todo), 4000):
        await asyncio.gather(*(tracked(j) for j in todo[i:i + 4000]))

    meta = {"built": time.strftime("%Y-%m-%d %H:%M"), "parts": {}}
    for name, jobs in plan.items():
        out, stats = [], {"rows": len(jobs), "kept": 0, "no_guide": 0, "要说到的为空": 0, "长短": {"简短": 0, "正常": 0, "长": 0}}
        for r, j in jobs:
            g = (cache.d.get(j["key"]) or {}).get("guide")
            if not g:
                stats["no_guide"] += 1
                continue
            ln = length_of(r["target"])
            row = {k: v for k, v in r.items() if k not in ("card", "card_v1", "card_how")}
            row.update(guide=g, length=ln, card=render(j["kind"], j["to"], g, ln), card_v2=r.get("card", ""))
            out.append(row)
            stats["要说到的为空"] += not g["要说到的"]
            stats["长短"][ln] += 1
        stats["kept"] = len(out)
        meta["parts"][name] = stats
        with open(os.path.join(OUT, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for row in out:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{name}: {stats}", flush=True)
    if not a.pool:
        json.dump({str(k): v for k, v in WRITE_SYSTEM_V3.items()}, open(os.path.join(OUT, "system.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    meta["cost"] = bl.cost()
    json.dump(meta, open(os.path.join(OUT, "meta_pool.json" if a.pool else "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"写好 {OUT}\n{bl.cost()}")


if __name__ == "__main__":
    asyncio.run(main())
