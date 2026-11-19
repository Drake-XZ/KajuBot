"""第六批标注：写手照卡写出来、真的发出去的线上回复，兄长大人判断像不像佳树（像就认可，不像就改成她会说的）。

2026-11-09 起因：第 4 轮 K 层（佳树口吻）重训到 190 / 322 步都追不上 r003——K 的数据（原作台词 + 兄长样本）
每轮几乎不变，r003 早学过了。要超过它只能加新的佳树数据，最好是聊天腔的：卡片、上下文和线上一模一样，
答案是兄长大人认可或改过的说法。标完用 make_gold6.py 写进 K 层数据，一部分留作每晚考试题。

来源：kaju_style 的线上记录（kaju_data/self/kaju_style/rewrites/*.jsonl），outcome = used（写手写的那句发出去了）。
去掉第五批（guard_eval）已经用过的。

用法：python -I build_review6.py → data/review6_items.json
"""
import glob
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
VT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REWRITES = r"D:\JiashuBot\kaju_data\self\kaju_style\rewrites"
OUT = os.path.join(VT, "data", "review6_items.json")


def parse(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return []
    return v or []


def main():
    # 第五批只把写手改了意思的那些（review5_targets.json 里有答案的）写成了训练数据 / 考题，其余没用
    done5 = {k for k in json.load(open(os.path.join(VT, "data", "review5_targets.json"), encoding="utf-8")) if not k.startswith("_")}
    used5 = {str(x.get("t")) for x in json.load(open(os.path.join(VT, "guard_eval", "items.json"), encoding="utf-8"))
             if str(x.get("id")) in done5}
    items, seen = [], set()
    for p in sorted(glob.glob(os.path.join(REWRITES, "*.jsonl"))):
        for line in open(p, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            w, c, ctx = parse(r.get("writer")), parse(r.get("card")), parse(r.get("ctx"))
            if r.get("outcome") != "used" or not w or not c or not c[0].get("card") or not w[0].get("user"):
                continue
            if str(r.get("t")) in used5:
                continue
            reply = re.sub(r"\s*&&[^&\n]*&&\s*", "", r.get("final") or "").strip()  # 表情包标签不是说法
            key = (tuple(ctx[-2:]), reply)
            if not reply or key in seen:
                continue
            seen.add(key)
            card_text = c[0]["card"]
            gist = next((ln.split("：", 1)[1] for ln in card_text.splitlines() if ln.startswith("要点：")), "")
            show = []
            for ln in ctx:
                who, _, x = ln.partition("：")
                show.append({"who": who if x else "", "x": x if x else ln})
            items.append({
                "id": f"r6-{r['t']}",
                "t": r["t"],
                "when": time.strftime("%m-%d %H:%M", time.localtime(r["t"])),
                "kind": r.get("kind", ""),
                "to": r.get("title", ""),
                "model": w[0].get("model", ""),
                "ctx": show,
                "train_ctx": ctx,
                "card": card_text,
                "gist": gist,
                "reply": reply.replace("\n", " / "),
                "user": w[0]["user"],
            })
    json.dump(items, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 标注页：只放显示要用的字段（卡片全文、写手输入留在 items.json 里给 make_gold6 用）
    show = [{k: it[k] for k in ("id", "when", "kind", "to", "ctx", "gist", "reply")} for it in items]
    tpl = open(os.path.join(VT, "review", "review6.template.html"), encoding="utf-8").read()
    page = tpl.replace("/*ITEMS*/", json.dumps(show, ensure_ascii=False).replace("</", "<\\/"))
    open(os.path.join(VT, "review", "review6.html"), "w", encoding="utf-8", newline="\n").write(page)
    by = {}
    for it in items:
        by[it["kind"]] = by.get(it["kind"], 0) + 1
    print(f"{len(items)} 条 → {OUT}", by)


if __name__ == "__main__":
    main()
