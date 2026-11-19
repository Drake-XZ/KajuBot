r"""说人话量尺（2026-11-13《说人话和要点卡-整合方案》第 0 步）。

对一批回复出两类数：
  1. 程序算的：卡上“要说到的”几点、回复字数、照抄率（回复里的两字片段有多少在卡的“要说到的”里出现过）。
  2. Gemini 判的（只判对错，不判好不好听、像不像她）：
       成话   每一句是不是正常中文（两句硬拼、缺字、词序乱、主宾错乱都算不成话）
       接得上 和聊天最后几句接得上、前后几句之间通顺、没有突然冒出不相干的事
       念卡   像在念说明：第三人称描述自己该做的事（“佳树让兄长大人…”）、把动作语气说成字面（“佳树撒娇了”“佳树哼”）

用法（AstrBot 的 Python，在 voice_train 下）：
  python -I -X utf8 scripts\speech_check.py live [--model kaju-writer-p4-8b-k]   线上记录（发出去的 + 被核对拦下的最后一遍）
  python -I -X utf8 scripts\speech_check.py exam --model kaju-writer-p4-8b-k     考试输出（data\exam_p3_<model>.json，每题第 1 遍）
报告写到 data\speech\<名字>.json / .md。别的脚本 import 它用 judge_many() / metrics()。
"""
import argparse
import asyncio
import glob
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
VT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(VT, "data", "speech")
REWRITES = r"D:\JiashuBot\kaju_data\self\kaju_style\rewrites"

JUDGE = """下面是一段聊天，和佳树接着说的话（分几行就是分几条发）。你是挑剔的中文母语者。只判断三件事，不评价好不好听、像不像她、说得够不够多：
1. 成话：每一句读起来是不是一个中国人随手打出来的顺的话。只要有一句你得改语序、补字、拆开才顺，就算不成话。常见的：
   - 两件事硬塞进一句：“佳树看每一帧认真看过了”（应是“每一帧佳树都认真看过了”）；
   - 短语生硬地拼接：“兄长大人取笑佳树，佳树哼”（像几个词条接在一起，不像说话）；
   - 缺字、词序乱、主语宾语弄反、同一句里把对方的话原样搬过来再接自己的话。
   严一点：说得通但别扭的，也算不成话。
2. 接得上：和聊天最后几句接得上——回应的是对方刚说的；几句之间前后通顺，没有前言不搭后语，没有突然冒出和聊天不相干的事。
3. 念卡：像在念一张说明——用第三人称交代自己做什么（“佳树让兄长大人卡住时歇一会儿”这种说明句），或者把动作、语气说成字面（“佳树撒娇了”“佳树哼”“佳树表示同意”）。自称“佳树”本身是她的习惯，不算。
只输出 JSON：{"成话": true或false, "接得上": true或false, "念卡": true或false, "毛病": "有毛病时一句话指出是哪句、什么毛病；没有就写空字符串"}"""


def points(card: str) -> list[str]:
    line = next((x for x in (card or "").splitlines() if x.startswith("要说到的：")), "要说到的：")
    v = line.split("：", 1)[1].strip()
    return [] if v in ("", "无") else [p for p in v.split("；") if p.strip()]


def _norm(t: str) -> str:
    return re.sub(r"[\s，。！？、,.!?~～…/“”\"'：:（）()\[\]【】&]", "", t or "")


def _bigrams(t: str) -> set:
    t = _norm(t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def jiashu_run(text: str) -> int:
    """连着几个分句都拿“佳树”开头（11-16 兄长：反复“佳树…佳树…佳树…”）。原作和他写的句子里没有到 3 的。"""
    cs = [c.strip() for c in re.split(r"[，,。！!？?~～…\n/、；;：:]+", text or "") if c.strip()]
    run = best = 0
    for c in cs:
        run = run + 1 if c.startswith("佳树") else 0
        best = max(best, run)
    return best


def metrics(reply: str, card: str) -> dict:
    p = points(card)
    b = _bigrams(reply)
    cp = len(b & _bigrams("".join(p))) / len(b) if b and p else 0.0
    return {"点数": len(p), "字数": len(_norm(reply)), "照抄率": round(cp, 3), "佳树连用": jiashu_run(reply)}


def _parse(out: str) -> dict | None:
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    if not isinstance(v, dict) or not all(k in v for k in ("成话", "接得上", "念卡")):
        return None
    return {"成话": bool(v["成话"]), "接得上": bool(v["接得上"]), "念卡": bool(v["念卡"]), "毛病": str(v.get("毛病") or "")}


async def judge_one(ctx: list[str], reply: str) -> dict | None:
    import build_layered as bl
    user = "聊天：\n" + ("\n".join(ctx[-8:]) if ctx else "（没有前文）") + "\n\n佳树接着说：\n" + reply.strip()
    for _ in range(2):
        v = _parse(await bl.ask(JUDGE, user, 0.0))
        if v:
            return v
    return None


async def judge_many(items: list[dict]) -> list[dict | None]:
    """items: [{ctx, reply}] → 每条的判定（判不出来是 None）。"""
    import build_layered as bl
    if bl.JUDGE.get("by") != "gemini":
        bl.use_gemini()
    return await asyncio.gather(*[judge_one(it["ctx"], it["reply"]) for it in items])


def summarize(rows: list[dict]) -> dict:
    """rows: 每条带 metrics 字段和 judge（可为 None）。"""
    n = len(rows)
    js = [r["judge"] for r in rows if r.get("judge")]
    pts = [r["点数"] for r in rows]
    s = {"条数": n, "判了": len(js),
         "卡 3 点以上": round(sum(p >= 3 for p in pts) / max(1, n), 2),
         "字数中位": statistics.median([r["字数"] for r in rows]) if rows else 0,
         "照抄率中位": round(statistics.median([r["照抄率"] for r in rows if r["点数"]] or [0]), 2),
         "照抄率≥0.6": round(sum(r["照抄率"] >= 0.6 for r in rows if r["点数"]) / max(1, sum(1 for r in rows if r["点数"])), 2),
         "佳树连用≥3": round(sum(r.get("佳树连用", 0) >= 3 for r in rows) / max(1, n), 2)}
    for k in ("成话", "接得上"):
        s[k + "率"] = round(sum(j[k] for j in js) / max(1, len(js)), 2)
    s["念卡率"] = round(sum(j["念卡"] for j in js) / max(1, len(js)), 2)
    return s


def live_items(model: str) -> list[dict]:
    out = []
    for p in sorted(glob.glob(os.path.join(REWRITES, "*.jsonl"))):
        for line in open(p, encoding="utf-8"):
            if not line.strip():
                continue
            d = json.loads(line)
            if (d.get("config") or {}).get("card_model") != model:
                continue
            card = (d.get("card") or [{}])[-1].get("card", "") or ""
            w = [x for x in d.get("writer") or [] if x.get("out")]
            reply = d.get("final") if d.get("outcome") == "used" else (w[-1]["out"] if w else "")
            if "局面：" not in card or not reply:
                continue
            out.append({"id": str(d["t"]), "kind": d.get("kind"), "ctx": d.get("ctx") or [], "card": card,
                        "reply": reply, "outcome": d.get("outcome")})
    return out


def exam_items(model: str) -> list[dict]:
    its = json.load(open(os.path.join(VT, "data", f"exam_p3_{model}.json"), encoding="utf-8"))
    return [{"id": it["id"], "kind": it.get("kind"), "ctx": it.get("ctx") or [], "card": it.get("new_card") or "",
             "reply": (it.get("new") or [""])[0]} for it in its if (it.get("new") or [""])[0]]


def report(name: str, rows: list[dict]) -> dict:
    os.makedirs(OUT, exist_ok=True)
    s = summarize(rows)
    json.dump({"summary": s, "rows": rows}, open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    bad = [r for r in rows if r.get("judge") and (not r["judge"]["成话"] or not r["judge"]["接得上"] or r["judge"]["念卡"])]
    md = [f"# 说人话量尺：{name}", "", "| 项 | 值 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in s.items()]
    md += ["", f"## 有毛病的（{len(bad)} 条）", ""]
    for r in bad:
        j = r["judge"]
        tags = "、".join(t for t, on in (("不成话", not j["成话"]), ("接不上", not j["接得上"]), ("念卡", j["念卡"])) if on)
        md.append(f"- [{tags}] {r['reply'].replace(chr(10), ' / ')[:120]} —— {j['毛病']}")
    open(os.path.join(OUT, name + ".md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    return s


async def run(kind: str, model: str):
    items = live_items(model) if kind == "live" else exam_items(model)
    js = await judge_many(items)
    rows = [{**it, **metrics(it["reply"], it["card"]), "judge": j} for it, j in zip(items, js)]
    s = report(f"{kind}-{model}", rows)
    print(json.dumps(s, ensure_ascii=False), "→", os.path.join(OUT, f"{kind}-{model}.md"), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["live", "exam"])
    ap.add_argument("--model", default="kaju-writer-p4-8b-k")
    a = ap.parse_args()
    asyncio.run(run(a.kind, a.model))


if __name__ == "__main__":
    main()
