r"""K 层原作 2668 条转成规划器卡 + 心情看回话重估（2026-11-17，voice_train\H和K重训方案-20261117.md 第 2 步）。

每条两次调用（走 model_router.json tasks.card 的动态挑选，和线上规划器同一条链；usage_meter 记用量估钱）：
  1. KPLAN：补“要接住的”、把“要说到的”重写成只留她那句真说了的事、第三人称短事实、不用她的原话（防照抄，治“串卡 / 佳树连用”），
     方向（只记不进卡），背景 0～2 条（前文里她用到的事 + 0～1 件没用的）。
  2. 心情：原作那段原文（label_novel_mood.locate，往前 2400 字）+ 她那句，列“说这句时”的心情（她那句流露的情绪算 min_ago=0 的一件事），
     kaju_heart 同一套公式算数、mood_line 拼（和 H 一样“看回话”；原来 K 是“只看开口之前”，心情几乎都一样）。
卡 = 原卡的场合 / 对象 / 局面 + “。要接住的：…” / 新要说到的 / 背景（清掉和卡重复的、泄答案的）/ 心情行（make_train_pack.picked(id) 挑约七成，和原来同一批）。
答案不动（原作原句）。

    python -I -X utf8 scripts\prepare_k_plan.py run [--limit 40]   → data\stage_k_plan\novel.jsonl（续跑）、novel.md（例子）、usage-*.json
"""
import argparse
import asyncio
import json
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prepare_h_plan as hp  # noqa: E402  clean_bg / card_with / 两字片段
import round_train as rt  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
OUT = os.path.join(rt.VT, "data", "stage_k_plan")
STAGE2 = os.path.join(rt.PACK, "data", "stage2.jsonl")

KPLAN = """下面是轻小说里的一段对话（佳树是温水佳树，初三女生，叫哥哥“兄长大人”）、交给佳树的材料（局面、要说到的），和佳树真正说出口的那句话。
请按规划器的写法补四栏。只输出 JSON：{"要接住的": "...", "要说到的": ["..."], "方向": "...", "背景": ["..."]}

要接住的：最后那句（或最后几句）里需要佳树接住的是哪件事——问了什么、要她做什么、在说什么事、发生了什么。一句话，主语是说话 / 做事的人。
  只写“是什么事”，不写“回应…”“表达…”，不写她该怎么回，不写她要说的内容。
要说到的：把材料里“要说到的”重写一遍。只留佳树那句**真说了的事**；每条一件事、一句短话（二十字以内），写成第三人称的事实
  （“兄长和对方出去的日子是平安夜”“爸妈今天都晚回来”），**换掉佳树那句里的说法**：除了人名、物名、数字这些换不了的，
  别照抄她的词句和语气词；能合成一条的合成一条，最多 3 条；不写态度、感受、撒娇、提问、玩笑；材料里是“无”或者都没真说到，就 []。
方向：佳树这句话的反应，一个短语（十个字以内）：态度或者回应动作（“撒娇抱怨”“乖乖答应”“吃醋地追问”“开心地报告”）。不写句子。
背景：交给佳树的、可以用也可以不用的事，0～2 条，每条一句短话，只从对话和原文前文来：
  1. 佳树那句里用到了、但局面和要说到的里都没有的前文的事，写进来（让每件事有来路）；
  2. 再挑 0～1 件前文里和最后那句有关、但她没用到的事（教写手背景可以不说）。挑不出就不挑。
  不写：对人对事的定性和评价、她该怎么说话的提醒、她的心情和想法、你自己的知识和推算、局面和要说到的里已经有的。没有就 []。"""

KMOOD = """下面是轻小说里的一段原文，最后一行是温水佳树（初三女生，主角温水和彦的妹妹，叫他“兄长大人”）说的话。
我要知道：**佳树说最后这句的时候**，她心里是什么状态。前面发生的事要算，最后这句话本身流露出来的情绪也要算
（把它当成 min_ago 为 0 的一件事：最后这句听着开心、委屈、吃醋、生气、得意、撒娇、难过……就照它写，强度照语气的轻重）。

请列出：
1. hour：这时大概是几点（0~23 的整数，按场景推，比如早饭 7、放学后 17、晚饭后 20、深夜 23；看不出就按最可能的写）。
2. events：发生在佳树身上、让她有感受的事，按发生先后排，最多 6 件，最后一件是最后这句话流露的情绪；没有就空列表。每件：
   - emo：她的感受，只能从这些里选一个：{emos}
   - i：强度 1~3（1 一点点，2 明显，3 很强烈）。多数日常小事是 1。
   - src："person" 是人对她说了 / 做了什么（或她和人说话时的感受）；"content" 是她看的、读的、吃的、玩的东西本身让她有感受
   - from_brother：这件事是不是兄长大人（温水和彦）对她做的 / 说的（true / false）
   - toward_her：这件事是不是冲着她来的（别人之间的事、她旁观的为 false）
   - cause：起因，20 字以内，用第三人称写事实
   - min_ago：离最后那句话大概几分钟前（整数；最后这句本身是 0）
3. carried：原文里明确写到、在这段之前就压在她心里、到现在还没放下的事。一般没有，就空列表。每件：
   - emo：只能从这些里选：{thread_emos}
   - c：现在还有多重，0.5~3
   - hours_ago：大概是几小时前开始的
   - from_brother：true / false
   - cause：20 字以内

只输出一个 JSON 对象，不要别的字：{{"hour": 17, "events": [...], "carried": [...]}}

原文（最后一行是佳树说的话）：
{text}
"""


def strip_mood(card):
    return "\n".join(x for x in card.split("\n") if not x.startswith("心情："))


def rows_all():
    rows = [json.loads(line) for line in open(STAGE2, encoding="utf-8")]
    nov = [r for r in rows if r.get("src") == "novel"]
    random.Random(20261117).shuffle(nov)
    return nov


async def one(r, txts, sem, st):
    import label_novel_mood as L
    from kaju_core.senses import omni
    card0 = strip_mood(r["card"])
    u = f"对话：\n{chr(10).join(r['ctx'][-8:])}\n\n交给佳树的材料：\n{card0}\n\n佳树说出口的话：\n{r['target']}"
    _, passage = L.locate(txts, r["ctx"])
    text = (passage or "\n".join(r["ctx"])) + "\n佳树：「" + r["target"].replace("\n", " ") + "」"
    mprompt = KMOOD.format(emos=L.EMOS, thread_emos=L.THREAD_EMOS, text=text)
    res = dict(r, card_old=r["card"], passage_found=bool(passage))
    async with sem:
        for attempt in range(3):
            try:
                out, _ = await omni.text(KPLAN, u, timeout=40)
                m = re.search(r"\{.*\}", out or "", re.S)
                v = json.loads(m.group(0)) if m else None
                if isinstance(v, dict) and str(v.get("要接住的") or "").strip():
                    was_none = bool(re.search(r"^要说到的：\s*无\s*$", card0, re.M))  # 原来是“无”的照旧“无”
                    res.update(catch=str(v["要接住的"]).strip(), direction=str(v.get("方向") or "").strip(),
                               must=[] if was_none else [str(x).strip() for x in (v.get("要说到的") or []) if str(x).strip()][:4],
                               bg=[str(x).strip() for x in (v.get("背景") or []) if str(x).strip()][:2])
                    break
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(5 * (attempt + 1))
        else:
            st["卡没出好"] += 1
            return None
        for attempt in range(3):
            try:
                out, _ = await omni.text("", mprompt, timeout=40)
                lab = L.parse(out or "")
                if lab is not None:
                    res.update(mood_label=lab, mood_snap=L.simulate(lab), mood_v=2)
                    break
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(5 * (attempt + 1))
        else:
            st["心情没出好"] += 1
    st["好"] += 1
    return res


def finish(r):
    import make_train_pack as mp
    from kaju_core.heart.mood_line import mood_line
    r["card"] = strip_mood(r["card_old"])
    r["bg_clean"] = hp.clean_bg(r)
    card = hp.card_with(r["card"], r.get("catch", ""), r["bg_clean"], r.get("must"))
    if r.get("mood_snap") and mp.picked(r["id"]):  # 和原来造包时同一批带心情行
        card += "\n" + mood_line(r["mood_snap"])
    r["card_final"] = card
    return r


def report(rows, path_md):
    L = ["# K 层原作转规划器卡（小试）", ""]
    for r in rows[:15]:
        L += [f"### {r['id']}", "```", *r["ctx"][-3:], "```", "原来的卡：", "```", r["card_old"], "```", "新卡：", "```", r["card_final"], "```",
              f"方向（只记）：{r.get('direction', '')}", f"佳树那句：{r['target']}", ""]
    open(path_md, "w", encoding="utf-8").write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pin", default="", help="只用这一家中转的 Gemini（比如 bb-api），不落到别家")
    a = ap.parse_args()
    import usage_meter
    import label_novel_mood as L
    if a.pin:
        import relay_pin
        relay_pin.pin(a.pin)
    usage_meter.patch()
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "novel.jsonl")
    done = {json.loads(x)["id"] for x in open(path, encoding="utf-8")} if os.path.exists(path) else set()
    allrows = rows_all()
    todo = [r for r in allrows if r["id"] not in done]
    batch = todo[:a.limit] if a.limit else todo
    print(f"原作 {len(allrows)} 条，已做 {len(done)}，这次 {len(batch)}", flush=True)
    txts = L.load_txts()
    st = {"好": 0, "卡没出好": 0, "心情没出好": 0}
    sem = asyncio.Semaphore(6)

    async def go():
        return await asyncio.gather(*(one(r, txts, sem, st) for r in batch))
    rows = [finish(r) for r in asyncio.run(go()) if r]
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    report(rows, os.path.join(OUT, "novel.md"))
    scale = len(allrows) / max(1, len(batch))
    u = usage_meter.report(os.path.join(OUT, f"usage-{time.strftime('%H%M')}.json"), scale)
    print(f"{st}；找到原文的 {sum(r['passage_found'] for r in rows)}/{len(rows)}", flush=True)
    print(f"这批估 {u['rmb']} 元，按比例全量（×{scale:.1f}）约 {u['rmb_full']} 元；各家：", flush=True)
    for who, x in u["by"].items():
        print(f"  {who}：{x['calls']} 次，进 {x['in_chars']} 字、出 {x['out_chars']} 字，价格倍数 {x['price']}，约 {x['rmb']} 元", flush=True)


if __name__ == "__main__":
    main()
