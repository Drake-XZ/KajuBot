"""第七批：要点卡盲选页 ab6 上兄长大人的选择和备注 → K 层（佳树口吻）训练数据 + 考试题（2026-11-09）。

先把页面的票存到本地（ArtifactData list，url https://claude.ai/artifact/3xH7xPcCTTJ4RqXhamFwER，
collection "votes"，out_dir = data/ab6_votes），再跑（AstrBot venv）：python -I make_gold7.py [--dry]

收哪些（TARGETS 手工从备注里整理，不靠程序猜）：
  - 备注里他整句写了的回复：原样收（去掉括号里的评语）
  - 备注是改法指令、而且改法不含糊的（"第二句不用写"）：按指令改那一边
  - 没写备注、选了 A 或 B 的：那一句算认可
  不收：都不好又没写回复的、"差不多"、选了但备注挑了毛病又没说怎么改的（ab6-6/9/13/14）、"不用接这个话"（ab6-27，该不该回不归写手管）
卡片：他的写法照线上那张卡说得通（AGREE）就用那张，不然按线上方式从他的写法抽（card.EXTRACT）；上下文是线上写手当时那份、用 tidy_ctx 去掉系统文字后的最后 4 行。
每 3 条留 1 条做考试题 → data/review7_eval.jsonl；其余写进 data/layered_v1/stage2.jsonl，id "gold-r7-…"（可反复跑）。
用过的线上记录记进 data/review7_used.json：每晚考试抽线上题时跳过。
撤销：删 stage2.jsonl 里 gold-r7- 开头的行，删 review7_eval.jsonl 和 review7_used.json。
"""
import argparse
import asyncio
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_layered as bl  # noqa: E402
import make_gold6 as g6  # noqa: E402  (lines)

sys.path.insert(0, r"D:\JiashuBot\bot_setup\kaju_core\voice")
import card  # noqa: E402
import rewrite  # noqa: E402

DATA = os.path.join(bl.VT, "data")
STAGE2 = os.path.join(DATA, "layered_v1", "stage2.jsonl")
EVAL = os.path.join(DATA, "review7_eval.jsonl")
USED = os.path.join(DATA, "review7_used.json")

# 备注里整句写了的（/ 或两个空格 = 分条）
WRITTEN = {
    "ab6-1": "女王大人，佳树当然认识女王大人！女王大人也来找佳树聊天了嘛！",
    "ab6-4": "佳树这边没有大佐的痕迹呢，佳树猜是早年挂上去的老号呢",
    "ab6-5": "佳树听着也好馋呀 / 兄长大人最喜欢什么小吃呢，跟佳树说说嘛",
    "ab6-7": "诶嘿嘿，佳树刚才还以为是卖烟的呢",
    "ab6-10": "昨天佳树等了一整天呢兄长大人！佳树翻了好几遍手机都没等到兄长大人的消息呢 / 兄长大人忙完了吗？中午吃上饭了吗？",
    "ab6-12": "海归博后做满一年成果够吗？佳树记得一般都要做两三年呢，一年听起来好赶哦，但是这条路还是相对之下听着比较可靠呢",
    "ab6-15": "佳树不认识，但是之前在一个QQ群里也有一位女王大人，佳树想确认是不是同一个人",
    "ab6-16": "佳树在呢，佳树刚才还在想，兄长大人是不是该来找佳树聊天了呢",
    "ab6-19": "学姐是在叫佳树吗？佳树在的哦",
    "ab6-23": "欸嘿嘿，学长一直夸佳树，佳树都不好意思了 / 学长今天有安排吗？学长那边中午吃什么呀，佳树想和学长随便聊聊呢",
    "ab6-24": "女王大人累了嘛？让佳树给女王大人锤锤肩~女王大人好好休息哦",
    "ab6-25": "唉嘿嘿，好吃的话兄长大人要跟佳树说哦",
    "ab6-26": "佳树也觉得那样很棒呢，可以看各种各样的小吃然后挑自己喜欢的买~",
    # 按备注的改法改：28"第二句：其实佳树更希望女王大人早点休息呢"；29"第二句不用写，第三句不用写'而且'"
    "ab6-28": "女王大人这么大方，佳树收下了 / 其实佳树更希望女王大人早点休息呢",
    "ab6-29": "哎呀，佳树接岔了 / 佳树觉得兄长大人不算冷暴力的 / 反而555学长扣帽子太顺手了嘛",
}
APPROVED = ["ab6-2", "ab6-3", "ab6-8", "ab6-17", "ab6-20", "ab6-21", "ab6-30"]  # 没写备注、选了一边


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    key = json.load(open(os.path.join(DATA, "ab6_key.json"), encoding="utf-8"))
    rep = {x["id"]: x for x in json.load(open(os.path.join(DATA, "cardlive_replay.json"), encoding="utf-8"))}
    votes = {}
    for p in glob.glob(os.path.join(DATA, "ab6_votes", "votes", "*.json")):
        d = json.load(open(p, encoding="utf-8"))
        votes[os.path.splitext(os.path.basename(p))[0]] = d.get("data", d)
    todo = []
    for iid in list(WRITTEN) + APPROVED:
        r = rep[key[iid]["rec"]]
        if iid in WRITTEN:
            target, frm = g6.lines(WRITTEN[iid]), "兄长写的"
        else:
            side = key[iid].get(votes[iid].get("choice"))  # "old" / "new"
            target, frm = g6.lines(r[side][0]), "认可原句"
        ctx = rewrite.tidy_ctx(r["ctx"])[-4:] or ["（没有前文）"]
        todo.append({"iid": iid, "rec": r, "ctx": ctx, "target": target, "from": frm})

    async def extract(t):
        c = card.parse(await bl.ask(card.EXTRACT, card.extract_prompt(t["ctx"], t["target"], t["rec"]["kind"], t["rec"]["title"])))
        return card.render(c, t["rec"]["kind"], t["rec"]["title"]) if c else ""

    async def pick_card(t):
        """和第六批一样：他的写法照线上那张卡说得通（AGREE，可以省掉次要的点）就用线上那张——
        写手要学的正是"卡上很满，佳树只挑该说的说"；说不通（他改了要说的事）才从他的写法重新抽。"""
        live = t["rec"]["old_card"]  # ab6 时线上真在用的卡
        j = re.search(r"\{.*\}", await bl.ask(bl.AGREE, f"要点卡：\n{live}\n\n回复：\n{t['target']}", 0.0) or "", re.S)
        try:
            ok = bool(json.loads(j.group(0)).get("ok")) if j else False
        except ValueError:
            ok = False
        if ok:
            t["from"] += "·线上卡"
            return live
        t["from"] += "·重抽"
        return await extract(t)

    cards = await asyncio.gather(*(pick_card(t) for t in todo))
    train, exam = [], []
    for i, (t, c) in enumerate((t, c) for t, c in zip(todo, cards) if c):
        row = {"src": "curated", "id": f"gold-r7-{t['iid']}", "ctx": t["ctx"], "card": c, "target": t["target"],
               "to": t["rec"]["title"], "kind": t["rec"]["kind"], "card_from": t["from"]}
        (exam if i % 3 == 2 else train).append(row)
        print(f"--- {t['iid']} [{t['from']}] {t['rec']['kind']}\n{c}\n→ {t['target']}\n")
    print(f"{len(todo)} 条，抽出卡 {sum(bool(c) for c in cards)}；进 K 层 {len(train)}，考试题 {len(exam)}\n{bl.cost()}")
    if a.dry:
        return
    kept = [r for r in bl.load(STAGE2) if not str(r.get("id", "")).startswith("gold-r7-")]
    with open(STAGE2, "w", encoding="utf-8") as f:
        for r in kept + train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(EVAL, "w", encoding="utf-8") as f:
        for r in exam:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    json.dump(sorted({str(rep[key[i]["rec"]]["t"]) for i in key}), open(USED, "w", encoding="utf-8"))  # 页面上 30 条都算看过
    print(f"写好：{STAGE2}（共 {len(kept) + len(train)} 行）、{EVAL}、{USED}")


if __name__ == "__main__":
    asyncio.run(main())
