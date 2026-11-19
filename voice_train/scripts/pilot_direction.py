"""离线小试「规划器只给方向」（2026-11-10，方案第四节第 2 步的第一小步；参考 MaiBot 的 reply 工具）。

现在线上：DeepSeek 先写一整份草稿 → 抽成要点卡 → 本地写手照卡写。卡上每一条都是 DeepSeek 草稿里的话。
这里试的：DeepSeek 不写正文，只写
  要用到的事实  回这句话非有不可的信息（对方问的事的答案、聊天里谁做了什么）。信息提取靠这一栏留住。
  方向          这一句要做什么（回答 / 接梗 / 安慰 / 追问 / 认错…）、冲着哪句话，一句话。
  长短          简短 / 正常 / 长
具体说哪几句、加不加关心的话、打什么比方，都不写——留给写手。
拿最近 N 条线上记录各写一份，和当时的草稿、卡并排，给兄长大人看内容上是不是少了 AI 味。

离线试的局限：线上 DeepSeek 写草稿时看得到佳树的记忆、知识本、心情，这里只给了那几行聊天，
所以"佳树自己的事"（吃没吃过什么）这里写不出来，真上线时这一栏会由记忆填上。
输出 data\\pilot_direction.json + data\\daily\\reports\\pilot-direction.md。约 N 次 DeepSeek 调用（30 条高峰价约 0.03 元）。
用法（AstrBot venv）：python -I pilot_direction.py [--n 30]
"""
import asyncio
import json
import os
import re
import sys

ARGS = sys.argv[1:]
sys.argv = sys.argv[:1]
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replay_live_cards as rp  # noqa: E402

bl = rp.bl

PLAN = """你在帮温水佳树（自称"佳树"，高中女生，管对方叫"兄长大人"或"某某学长/学姐"）准备回一句聊天消息。
你不替她写回复。真正开口的是她自己：她会看着这段聊天和你给的材料，用自己的话说。
你给的是材料，不是台词。只输出 JSON：
{"局面": "...", "要答的": ["..."], "背景": ["..."], "长短": "简短|正常|长"}

局面：一两句话，只描述现在的情况——聊到哪了、这句话是谁对谁说的、接的是前面哪句、为什么轮到她回。
  不写她该怎么回、该表达什么情绪、用什么语气。

要答的：先判断最后这句话是不是在向她要信息。
  - 是在问一件外面的事（是什么、怎么办、怎么做到、有没有现成的、推荐什么、为什么会这样），或者在说"你刚才没讲到某某"：
    这一栏**不能空**。你把答案想好，挑最要紧的写，最多 3 条，每条一个短事实，名字、数字、做法写具体。
    她自己不懂这些，你不写她就答不上。
  - 是在问她自己（她的经历、喜好、认不认识、做没做过、愿不愿意、怎么想）：只写一条"问她自己：<问的是什么>"，不要替她编答案。
  - 没有在问她（闲聊、玩笑、发牢骚、说自己的心情、夸她、道谢、应一声）：空数组 []。
    对方只是说"很烦""成功了"这种，不算在问她。

背景：默认 []。只有下面两种情况才写，最多 2 条：
  - 最后这句话里有个指代，不点明她会弄错（"那个""他""你说的办法"指的是哪件事、谁）。
  - 回这句话要用到五行以前聊过的一件具体的事。
  她是谁、对方是谁、最后几行里一眼看得到的内容、"某某是群里的人"这种，都不要写。

长短：对方说得短、是闲聊就"简短"；要解释事情才"长"。

哪一栏都不要写的：
- 回复正文，或者可以直接照着念的句子。
- 语气、语气词、比方、例子、情绪（"轻快一点""撒个娇""表示开心"）。
- 顺手的关心和客套（早点睡、别太累、注意身体、下次一起）——除非对方这句话就是在说这件事。
- 对聊天的点评和总结。"""


def opt(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


async def plan(r):
    u = f"场合：{r['kind']}\n要回的人：{r['title'] or '无'}\n\n聊天（最后一行是要回的话）：\n" + "\n".join(r["ctx"][-10:] or ["（没有前文）"])
    for _ in range(2):
        m = re.search(r"\{.*\}", await bl.ask(PLAN, u, 0.3) or "", re.S)
        try:
            v = json.loads(m.group(0)) if m else None
        except ValueError:
            v = None
        if v and v.get("局面"):
            v["要答的"] = [str(x) for x in (v.get("要答的") or v.get("要答") or []) if str(x).strip()][:3]
            v["背景"] = [str(x) for x in (v.get("背景") or []) if str(x).strip()][:2]
            return v
    return None


async def main():
    n = int(opt("--n", "30"))
    recs = rp.records()
    seen, picked = set(), []
    for r in reversed(recs):  # 最近的在前；同一段聊天只留一条
        k = bl.ctx_key(r["ctx"])
        if k not in seen and r["ctx"]:
            seen.add(k)
            picked.append(r)
        if len(picked) >= n:
            break
    picked.reverse()
    res = await asyncio.gather(*(plan(r) for r in picked))
    out = [{**r, "plan": v} for r, v in zip(picked, res) if v]
    json.dump(out, open(os.path.join(bl.VT, "data", "pilot_direction.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    cell = lambda t: str(t or "").replace("|", "｜").replace("\n", "<br>")  # noqa: E731
    L = ["# 小试：DeepSeek 只给方向，不写正文", "",
         f"最近 {len(out)} 条线上记录。左边是当时线上的做法（DeepSeek 写草稿 → 抽成卡），右边是新做法第三版（照 MaiBot 的 reply_reference：DeepSeek 只写“局面 + 要答的 + 背景 + 长短”，不写句子、不写语气）。“要答的”她必须说到，最多 3 条；“背景”可以不说。",
         "要看的是：右边有没有把回这句话需要的信息留住，同时把 DeepSeek 自己加的那些话（顺手的关心、比方、总结）去掉。",
         "离线试的局限：这里 DeepSeek 只看得到这几行聊天，看不到佳树的记忆，所以她自己的事会写“要看她自己记不记得”；真上线时由记忆填。", ""]
    for i, r in enumerate(out, 1):
        p = r["plan"]
        pts = re.search(r"^要点：(.*)$", r["old_card"], re.M)
        L += [f"## {i}. {r['kind']} · 回给 {r['title'] or '无'}", "",
              "聊天：", "", *[f"> {cell(x)}" for x in r["ctx"][-6:]], "",
              "| 现在：DeepSeek 的草稿 | 现在：卡上的要点 | 新：只给局面和事实 |", "|---|---|---|",
              f"| {cell(r['draft'])} | {cell((pts.group(1) if pts else '').replace('；', chr(10)))} | "
              f"**局面** {cell(p.get('局面'))}<br>**要答的** {cell('；'.join(p['要答的']) or '无')}<br>"
              f"**背景** {cell('；'.join(p['背景']) or '无')}<br>**长短** {cell(p.get('长短'))} |", ""]
    rp_ = os.path.join(bl.VT, "data", "daily", "reports", "pilot-direction.md")
    open(rp_, "w", encoding="utf-8").write("\n".join(L))
    print(f"{len(out)} 条 → {rp_}\n{bl.cost()}")


if __name__ == "__main__":
    asyncio.run(main())
