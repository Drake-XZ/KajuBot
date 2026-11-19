"""抽卡规则改了以后（2026-11-07：去描写、去含糊指代），在上一轮盲选的题上对照：旧卡 / 新卡 / C 照新卡写的。只打印。

    <bot venv>\\python.exe -I retest_cards.py [--all]
不带 --all 只看兄长大人标了 AI 味或写了备注的题。
"""
import asyncio
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_layered_eval as ev  # noqa: E402  (用项目里的 card.py，已是新规则)

VT = r"D:\JiashuBot\voice_train"


def pts(card_text):
    return next((l for l in card_text.split("\n") if l.startswith("要点")), "（没有卡）")


async def main():
    rows = [json.loads(l) for l in open(os.path.join(VT, "data", "layered_v1_eval.jsonl"), encoding="utf-8")]
    votes = json.load(open(os.path.join(VT, "review", "layered_v1", "votes.json"), encoding="utf-8"))
    pick = [r for r in rows if "--all" in sys.argv or votes[r["id"]]["note"]
            or any("AI味" in f for f in votes[r["id"]]["flags"].values())]
    for r in pick:
        ctx, draft, title, kind = r["ctx"], r["draft"], r["to"], r["kind"]
        c = ev.card.parse(await ev.ds_chat(ev.card.EXTRACT, ev.card.extract_prompt(ctx, draft, kind, title), 0.3))
        new_card = ev.card.render(c, kind, title) if c else ""
        out = ev.live_rw.clean_output(ev.local("kaju-writer-l1c", ev.card.WRITE_SYSTEM[2],
                                                ev.card.write_prompt(ctx, new_card))) if new_card else ""
        note = votes[r["id"]]["note"]
        print(f"\n## {r['id']}  {('备注：' + note) if note else ''}")
        print("  草稿  ", draft.replace("\n", " / ")[:110])
        print("  旧卡  ", pts(r["card"])[:110])
        print("  新卡  ", pts(new_card)[:110])
        print("  C旧   ", r["cands"]["l1c"]["text"].replace("\n", " / ")[:110])
        print("  C新卡 ", out.replace("\n", " / ")[:110])


asyncio.run(main())
