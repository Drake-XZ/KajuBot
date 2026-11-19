r"""第 7 轮训练包（2026-11-17）：r6 的包为底，有新卡的样本换上长聊天 + 新卡，系统提示换 v5（去掉“不说你”）。

  H：r6 h_data\stage1（新规划器卡 1996 + 旧 H 1996）——群聊 / 兄长私聊里出了新卡的换 ctx、card
  K：r6 k_data\stage2（原作、旧人工样本、金句）——出了新卡的换；stage1 = H 那份（阶段二复习用）
  对子：照 r6 的（心情对子、毛病对子），卡和聊天不动
  恋爱向的（目标 / 对子里有那类词）整包都不要（prepare_r7_cards.ROMANCE）
  系统提示：{"1": 照旧, "2": card.SYSTEM_V5}——线上 rewrite.writer_system = "v5" 和写手一起换
结果：data\rounds_v4\r7\h_data、k_data、info.json
用法（AstrBot 的 Python）：python -I -X utf8 scripts\prepare_r7_pack.py
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prepare_r7 as p7  # noqa: E402
import prepare_r7_cards as pc  # noqa: E402
import train_keys  # noqa: E402,F401  bot_setup 进 sys.path

sys.stdout.reconfigure(encoding="utf-8")
KEEP = ("src", "id", "group", "ctx", "target", "card")


def dump(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def swap(rows, part, new):
    out, n_new, n_drop = [], 0, 0
    for r in rows:
        if pc.ROMANCE.search(r.get("target") or ""):
            n_drop += 1
            continue
        d = new.get((f"{part}:{r['id']}", r["src"]))
        if d:  # 长聊天按现在的上限再截一遍（11-17 显存不够，16 行 / 1500 字 → 12 行 / 1000 字；线上同一个上限）
            from kaju_core.voice import longctx
            r = dict(r, ctx=longctx.trim(d["ctx"]), card=d["card"])
            n_new += 1
        out.append({k: r[k] for k in KEEP if k in r})
    return out, n_new, n_drop


def main():
    from kaju_core.voice import card
    new = {(d["key"], d["src"]): d for d in p7.jl(pc.OUT)}
    h, h_new, h_drop = swap(p7.jl(os.path.join(p7.R6, "h_data", "stage1.jsonl")), "H", new)
    k, k_new, k_drop = swap(p7.jl(os.path.join(p7.R6, "k_data", "stage2.jsonl")), "K", new)
    sysj = json.load(open(os.path.join(p7.R6, "k_data", "system.json"), encoding="utf-8"))
    sysj["2"] = card.SYSTEM_V5
    pairs = {}
    for name in ("dpo.jsonl", "heldout.jsonl", "kto.jsonl"):
        src = os.path.join(p7.R6, "k_data", "prefs", name)
        rows = p7.jl(src) if os.path.exists(src) else []
        pairs[name] = [p for p in rows if not pc.ROMANCE.search(json.dumps(p, ensure_ascii=False))]
    for d in ("h_data", "k_data"):
        base = os.path.join(p7.R7, d)
        if os.path.isdir(base):
            shutil.rmtree(base)
        os.makedirs(os.path.join(base, "prefs"))
        json.dump(sysj, open(os.path.join(base, "system.json"), "w", encoding="utf-8"), ensure_ascii=False)
        dump(os.path.join(base, "stage1.jsonl"), h)
    dump(os.path.join(p7.R7, "k_data", "stage2.jsonl"), k)
    for name, rows in pairs.items():
        dump(os.path.join(p7.R7, "k_data", "prefs", name), rows)
    long_h = sum(len(r["ctx"]) >= 10 for r in h)
    long_k = sum(len(r["ctx"]) >= 10 for r in k)
    info = {"H": {"共": len(h), "换了新卡和长聊天": h_new, "前文≥10行": long_h, "恋爱向不要": h_drop},
            "K": {"共": len(k), "换了新卡和长聊天": k_new, "前文≥10行": long_k, "恋爱向不要": k_drop,
                  "带心情行": sum("\n心情：" in r["card"] for r in k), "掺了无关背景": sum(1 for d in new.values() if d["part"] == "K" and d["mixed_bg"])},
            "对子": {n: len(r) for n, r in pairs.items()}, "系统提示": "v5（去掉不说你）"}
    json.dump(info, open(os.path.join(p7.R7, "info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
