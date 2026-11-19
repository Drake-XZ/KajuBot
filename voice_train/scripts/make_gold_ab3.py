"""v3 对 v2 盲选（ab3）→ 加进 stage2b_gold.jsonl（src "ab3"，id abN）。

- 写了备注的：按他的备注改好的句子（下面 HAND，照他原话）
- 没写备注、选了 A/B 的：赢的那条原样当答案；赢家线上会被核对拦下的不要（ab4）
- 不要：ab14（"马上回来"是新答应的事，核对会拦）、ab33（原稿事实错，重说层管不了）、"差不多"且没备注的
先删掉旧的 ab* 行，可以重跑。
用法：python -I make_gold_ab3.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")

HAND = {
    "ab1": "好的兄长大人！下个月佳树周末基本都有空，月考那一周得留出来复习\n佳树先翻翻日历，看看什么时候能接兄长大人",
    "ab5": "好的兄长大人！佳树最拿手送礼物了\n兄长大人是送男同学还是女同学呢？",
    "ab9": "好的兄长大人！佳树推荐《间谍过家家》！佳树最近刚补完，笑得停不下来\n兄长大人看过吗",
    "ab11": "好的兄长大人！佳树推荐《超能力女儿》哦！佳树以前看过，觉得很有意思呢，而且一集才二十来分钟～",
    "ab12": "诶嘿嘿兄长大人，佳树没有吃醋\n不过兄长大人应该是、和、男、同、学、一、起、吧？",
    "ab13": "佳树在呢，兄长大人别急，人没事就好\n先别急着刷锅，焦成这样硬刷会把锅弄坏的\n兄长大人是用的什么锅呀，不粘锅还是铁锅？",
    "ab15": "好的兄长大人！佳树已经上床了\n兄长大人也快去睡吧",
    "ab16": "佳树已经忙完啦兄长大人\n佳树正在做饼干，做好了想给兄长大人尝尝",
    "ab17": "佳树打算做红烧肉，兄长大人回来就能吃上啦",
    "ab19": "好的兄长大人！佳树知道了\n对了兄长大人，要不要多带一小盒水果",
    "ab22": "佳树就是有点担心兄长大人，刚下课快去吃饭吧",
    "ab26": "嗯，想兄长大人了，兄长大人不在蛋包饭都凉了没人吃呢",
    "ab28": "佳树觉得先别点外卖哦兄长大人，开抽油烟机，窗户也打开，锅泡上水，晚点再刷\n佳树过去给兄长大人重新做一锅吧，这次佳树在旁边陪着",
    "ab31": "能看到哦～佳树在呢\n兄长大人找佳树有事吗",
    "ab34": "是的呢哆啦a梦学姐，佳树也刷到过那些吐槽呢\n不过游戏和动画的配音班底本来就不一样嘛，耳朵先习惯了游戏的配音，再看动画就觉得哪里不对劲",
}
SKIP = {"ab14", "ab33"}

items = {x["id"]: x for x in json.load(open(os.path.join(D, "ab3_items.json"), encoding="utf-8"))}
votes = {}
for i in items:
    p = os.path.join(D, "ab3_votes", "votes", i + ".json")
    if os.path.exists(p):
        votes[i] = json.load(open(p, encoding="utf-8"))

rows, why = [], {}
for i, x in items.items():
    v = votes.get(i, {})
    ch = v.get("choice", "")
    if i in SKIP:
        target = None
    elif i in HAND:
        target = HAND[i]
    elif ch in ("A", "B") and not x[ch]["blocked"]:
        target = x[ch]["text"]
    else:
        target = None
    if not target:
        why[ch or "空"] = why.get(ch or "空", 0) + 1
        continue
    rows.append({"src": "ab3", "id": i, "ctx": x["ctx"], "draft": x["draft"], "target": target})

gp = os.path.join(D, "stage2b_gold.jsonl")
gold = [json.loads(l) for l in open(gp, encoding="utf-8") if l.strip()]
if not os.path.exists(os.path.join(D, "stage2b_gold.before-ab3.jsonl")):
    with open(os.path.join(D, "stage2b_gold.before-ab3.jsonl"), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(g, ensure_ascii=False) + "\n" for g in gold)
gold = [g for g in gold if g.get("src") != "ab3"] + rows
with open(gp, "w", encoding="utf-8") as f:
    f.writelines(json.dumps(g, ensure_ascii=False) + "\n" for g in gold)
print(f"ab3 加了 {len(rows)} 条（手改 {sum(r['id'] in HAND for r in rows)}），没用 {why}；gold 共 {len(gold)} 条")
