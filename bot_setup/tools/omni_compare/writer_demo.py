r"""看完感想过一遍线上的写手是什么样：DeepSeek 原稿 → 抽要点卡（和线上同一个提示词）→ 本地写手照卡写。
另外数一数她以往"看完东西"的回复里那些套路出现得多不多。
    <venv>\Scripts\python.exe -I writer_demo.py
"""
import asyncio
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
os.environ["KAJU_DATA"] = r"D:\JiashuBot\kaju_data"
CORE = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"

from openai import AsyncOpenAI  # noqa: E402

from kaju_core.voice import card  # noqa: E402

PATTERNS = {
    "反而/反倒/却 转折收尾": re.compile(r"反而|反倒|倒是|却"),
    "那种…/像…一样 比喻": re.compile(r"那种|像是|像被|仿佛|好像.{2,12}一样"),
    "身体反应代替心情": re.compile(r"眼眶|鼻子.?酸|心里一[沉紧空]|胸口|喉咙|手心|嘴角"),
    "正好三行": None,
    "每行都以 呢/嘛/呀/哦 收尾": None,
    "开头先报告“看完了/看了”": re.compile(r"^.{0,12}(看完了|看到最后|看了|听完了|从头看)"),
    "点评口吻（节奏/剪辑/氛围/反差/杀伤力…）": re.compile(r"节奏|剪辑|氛围|反差|杀伤力|张力|质感|有点东西|太会了"),
}


def stats(replies: list[str]) -> dict:
    out = {}
    for name, rx in PATTERNS.items():
        if name == "正好三行":
            n = sum(1 for r in replies if len([x for x in r.split("\n") if x.strip()]) == 3)
        elif name.startswith("每行都以"):
            n = sum(1 for r in replies if (ls := [x.strip() for x in r.split("\n") if x.strip() and "&&" not in x])
                    and len(ls) >= 2 and all(re.search(r"[呢嘛呀哦啦]\W*$", x) for x in ls))
        else:
            n = sum(1 for r in replies if rx.search(r))
        out[name] = n
    return out


async def main():
    # 1. 以往"看完东西"的回复（记忆轻重里珍藏的 18 条：她当时真实发出去的）
    shelf = json.load(open(r"D:\JiashuBot\kaju_data\self\memory_weight\state.json", encoding="utf-8"))["shelf"]
    shelf = list(shelf.values()) if isinstance(shelf, dict) else shelf
    past = [str(it.get("reply") or "") for it in shelf if it.get("url") and it.get("reply")]
    print(f"以往看完视频的回复 {len(past)} 条：")
    for k, v in stats(past).items():
        print(f"  {k}: {v}/{len(past)}")
    lens = sorted(len(r) for r in past)
    print("  字数 中位数", lens[len(lens) // 2], "最长", lens[-1])
    # 写手记录：这些轮次过没过写手
    rows = []
    for f in sorted(glob.glob(r"D:\JiashuBot\kaju_data\self\kaju_style\rewrites\*.jsonl")):
        rows += [json.loads(x) for x in open(f, encoding="utf-8") if x.strip()]
    media = [r for r in rows if re.search(r"bilibili|b23\.tv|douyin", str(r.get("said") or ""))]
    print(f"\n写手记录里带视频链接的轮次 {len(media)} 条：", {o: sum(1 for r in media if r.get('outcome') == o) for o in
                                             sorted({r.get('outcome') for r in media})})

    # 2. 10 条带感受的原稿 → 抽卡 → 写手
    cfg = json.load(open(os.path.join(CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = src.get("key") or src.get("api_key")
    ds = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"])
    local = AsyncOpenAI(api_key="ollama", base_url="http://127.0.0.1:11435/v1", timeout=120)
    R = json.load(open(os.path.join(HERE, "results", "replies.json"), encoding="utf-8"))
    O = json.load(open(os.path.join(HERE, "results", "old.json"), encoding="utf-8"))
    res, drafts, written = {}, [], []
    for sid, r in R.items():
        draft = r["new"][0]
        said = (O[sid]["said"] or "佳树看看这个").split("\n")[-1][:60]
        ctx = [f"兄长大人：{said}"]
        ex = await ds.chat.completions.create(model="deepseek-flash", temperature=0.3, extra_body=card.EXTRACT_EXTRA_BODY, messages=[
            {"role": "system", "content": card.EXTRACT},
            {"role": "user", "content": card.extract_prompt(ctx, draft, "私聊", "兄长大人")}])
        c = card.parse(ex.choices[0].message.content or "")
        if not c:
            print(sid, "抽卡失败")
            continue
        card_text = card.render(c, "私聊", "兄长大人")
        w = await local.chat.completions.create(model="kaju-writer-l1a-r003", messages=[
            {"role": "system", "content": card.WRITE_SYSTEM[2]}, {"role": "user", "content": card.write_prompt(ctx, card_text)}])
        new = (w.choices[0].message.content or "").strip()
        res[sid] = {"draft": draft, "card": card_text, "writer": new}
        drafts.append(draft)
        written.append(new)
        print(f"\n== {sid}\n原稿：{draft}\n要点：{'；'.join(c.get('points') or [])}\n写手：{new}")
    json.dump(res, open(os.path.join(HERE, "results", "writer_demo.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n原稿套路：", stats(drafts))
    print("写手套路：", stats(written))

asyncio.run(main())
