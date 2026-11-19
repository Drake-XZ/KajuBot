r"""第 7 轮考题 v8（2026-11-17）：40 道考题换成“长聊天 + 规划器 v6 样子的卡”，像线上 B 那条路。

- 长聊天：考题的前文去聊天记录（prepare_r7.find_in_logs）/ 原作原文（novel_long）里找，往前取；找不到照旧短的。
- 卡：要说到的照 v7 卡（v7 是从草稿 / 参考摘的短事实——线上 B 也是规划器从草稿里拿事实）；
  局面、要接住的**不看答案**重写（写手看得到聊天，不复述）；背景只留长聊天里看不到的。心情行照 v7。
- 恋爱向的题（参考里有那类词）不考。
结果：data\stage2bg\exam_v8.json（{id: {"ctx_v8": [...], "card_v8": "..."}}）；exam_p3.py / rejudge_exam.py 用 --cards v8。
用法（AstrBot 的 Python）：python -I -X utf8 scripts\prepare_r7_exam.py
"""
import asyncio
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prepare_r7 as p7  # noqa: E402
import prepare_r7_cards as pc  # noqa: E402  cover、line_of、items、ROMANCE
import test_r7_cards as tc  # noqa: E402  addr_maker
import train_keys  # noqa: E402,F401

sys.stdout.reconfigure(encoding="utf-8")
V7 = os.path.join(p7.VT, "data", "stage2bg", "exam_v7.json")
V8 = os.path.join(p7.VT, "data", "stage2bg", "exam_v8.json")

PLAN = """下面是一段聊天（之后要照指导说话的写手也看得到这些），最后一句是对方刚对佳树说的话。你替规划器写“回复指导”的两栏，**不写佳树要说的话**。
只输出 JSON：{"局面": "...", "要接住的": "..."}
局面：一两句话：最后这句是谁对谁说的、接的是哪件事、为什么轮到佳树回。写手看得到聊天，**不要复述聊天里的话**，不要概括前面聊了什么。每句写出主语，别让人看反。
要接住的：最后那句（或最后几句）里需要佳树接住的是哪件事——问了什么、要她做什么、在说什么事。一句话，主语是说话的那个人。只写“是什么事”，不写怎么回。"""


def main():
    import exam_p3 as ex
    from kaju_core.senses import omni
    v7 = json.load(open(V7, encoding="utf-8"))
    base = {it["id"]: it for it in ex.items()}
    chats = p7.by_chat(p7.logs())
    addr_of = tc.addr_maker()
    txts = p7.load_txts()
    out = json.load(open(V8, encoding="utf-8")) if os.path.exists(V8) else {}  # 上次出好的留着，这次没出好不删
    st = {"长聊天": 0, "短": 0, "不考": 0, "没出好": 0}

    async def one(qid, v):
        it = base.get(qid)
        if not it:
            return
        if pc.ROMANCE.search(it["ref"] or ""):
            st["不考"] += 1
            return
        ctx = it["ctx"]
        if "场合：说说" in v["card_v7"]:  # 写说说：前文是素材、没有要回的人，照 v7 不动
            out[qid] = {"ctx_v8": ctx, "card_v8": v["card_v7"], "card_v7": v["card_v7"]}
            st["短"] += 1
            return
        long = None
        if it["kind"] == "当面":
            long = p7.novel_long(txts, ctx)
        else:
            hit = p7.find_in_logs(ctx, chats)
            if hit:
                long = p7.chat_long(chats[hit[0]], hit[1], addr_of)
        use = long if long and len(long) >= len(ctx) else ctx
        st["长聊天" if use is not ctx else "短"] += 1
        old = v["card_v7"]
        for attempt in range(3):
            try:
                res, _ = await omni.text(PLAN, "聊天：\n" + "\n".join(use), timeout=40)
                m = re.search(r"\{.*\}", res or "", re.S)
                p = json.loads(m.group(0)) if m else None
                if isinstance(p, dict) and str(p.get("局面") or "").strip():
                    break
            except Exception:  # noqa: BLE001
                p = None
            await asyncio.sleep(5 * (attempt + 1))
        else:
            st["没出好"] += 1
            return
        jm = str(p["局面"]).strip().rstrip("。")
        if str(p.get("要接住的") or "").strip():
            jm += "。要接住的：" + str(p["要接住的"]).strip().rstrip("。")
        text = "\n".join(use)
        bg = [b for b in pc.items(pc.line_of(old, "背景")) if pc.cover(b, text) < 0.5][:2]
        lines = [x for x in old.splitlines() if x.startswith(("场合：", "对象："))]
        lines += [f"局面：{jm}", "要说到的：" + (pc.line_of(old, "要说到的") or "无")]
        if bg:
            lines.append("背景：" + "；".join(bg))
        mood = next((x for x in old.splitlines() if x.startswith("心情：")), "")
        if mood:
            lines.append(mood)
        out[qid] = {"ctx_v8": use, "card_v8": "\n".join(lines), "card_v7": old}

    async def all_():
        sem = asyncio.Semaphore(6)

        async def lim(q, v):
            async with sem:
                await one(q, v)
        await asyncio.gather(*(lim(q, v) for q, v in v7.items()))

    asyncio.run(all_())
    json.dump(out, open(V8, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(st, "→", V8, f"（{len(out)} 题）")


if __name__ == "__main__":
    main()
