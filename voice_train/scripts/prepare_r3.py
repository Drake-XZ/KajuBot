r"""第 3 轮（2026-11-14，交接-佳树-向MaiBot做法看齐 第五节“下一步”）：第二阶段“背景”卡的数据拼成 round_train 吃的样子。

  gold.jsonl    兄长金句 37 条，卡用带背景的 card_v5（data\stage2bg\gold.jsonl）
  pairs.jsonl   同一张 v5 卡让线上写手写 2 遍当“不要的”（同卡才成对）
  kto.jsonl     第 2 轮他原样选中的 7 条当好（v4 卡）；**不放“都不好”整句反例**（第 2 轮拆开验证的教训）
  extra_stage2.jsonl  原作台词里背景不空的 v5 卡（复习用；原来的 v4 卡照旧在训练包里，两种都要会）
不放群聊 / 兄长私聊：K 层的复习一律按“佳树说的话”学，群友的话放进来会教她学群友说话（那些只适合 H 层）。
用法（AstrBot 的 Python，Ollama 要开着）：python -I -X utf8 scripts\prepare_r3.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import round_train as rt  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
BG = os.path.join(rt.VT, "data", "stage2bg")
OUT = rt.rdir(3)


def main():
    os.makedirs(OUT, exist_ok=True)
    model = rt.state()["live_model"]
    gold, pairs = [], []
    for r in rt.jl(os.path.join(BG, "gold.jsonl")):
        rid = "r3-" + r["id"]
        base = {"id": rid, "src": "live", "group": rid, "ctx": r["ctx"], "card": r["card_v5"]}
        gold.append({**base, "target": r["target"]})
        for _ in range(2):
            out = rt.write(model, r["ctx"], r["card_v5"])
            if out and rt.lines(out) != rt.lines(r["target"]):
                pairs.append({**base, "chosen": r["target"], "rejected": rt.lines(out), "w": 2.0})
        print(f"  {len(gold)}/37 {rid}", flush=True)
    kto = [k for k in rt.jl(os.path.join(rt.rdir(2), "kto.jsonl")) if k.get("label") == "good"]
    extra = [{"id": r["id"] + "-bg", "src": "novel", "group": r.get("group") or r["id"], "ctx": r["ctx"], "card": r["card_v5"], "target": r["target"]}
             for r in rt.jl(os.path.join(BG, "novel.jsonl")) if r.get("bg")]
    rt.wjl(os.path.join(OUT, "gold.jsonl"), gold)
    rt.wjl(os.path.join(OUT, "pairs.jsonl"), pairs)
    rt.wjl(os.path.join(OUT, "kto.jsonl"), kto)
    rt.wjl(os.path.join(OUT, "extra_stage2.jsonl"), extra)
    print(f"金句 {len(gold)}、成对 {len(pairs)}、单条好 {len(kto)}、带背景的原作复习 {len(extra)} → {OUT}", flush=True)


if __name__ == "__main__":
    main()
