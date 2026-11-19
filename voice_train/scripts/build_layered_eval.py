"""分层 writer 第一轮盲选题：线上 v3.1 重说层 对 新写手 A / B / C，四选一。

    <bot venv>\\python.exe -I build_layered_eval.py OUT.jsonl [--n 24]

题目：data\\ab5_items.json 里真实的"上下文 + DeepSeek 草稿"（这轮训练已剔除和它们重叠的条目）。
每个系统都照线上的完整流程走到"真正发出去的那句"：
  v31  kaju-rewriter 看草稿重说（rewrite.SYSTEM + build_prompt）→ 不像回复 / 叫错人 → 发草稿 → 核对没过 → 发草稿
  l1a / l1b / l1c  DeepSeek 从草稿抽要点卡（card.EXTRACT，关思考）→ 写手照卡写（card.WRITE_SYSTEM[2]）→ 不像回复 → 发草稿 → 核对没过 → 发草稿
核对用线上同一份 rewrite.GUARD（deepseek-flash 关思考，和线上 deepseek_nothink 一样）。采样参数和线上一样。
v31 和核对用运行实例里的 kaju_style（1.10.0，就是线上在跑的）；抽卡、写手提示用项目里的 card.py（1.11.0，card 模式）。
"""
import argparse
import asyncio
import importlib.util
import json
import os
import random
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
ROOT = r"D:\JiashuBot"
CORE = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
LIVE_STYLE = os.path.join(CORE, "data", "kaju_lib", "kaju_core", "voice")  # 线上部署的 rewrite.py
PROJ_STYLE = os.path.join(ROOT, "bot_setup", "kaju_core", "voice")


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


live_rw = load_mod("live_rewrite", os.path.join(LIVE_STYLE, "rewrite.py"))
card = load_mod("proj_card", os.path.join(PROJ_STYLE, "card.py"))

from openai import AsyncOpenAI  # noqa: E402

_cfg = json.load(open(os.path.join(CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
_src = next(s for s in _cfg["provider_sources"] if s["id"] == "deepseek_source")
_key = _src.get("key")
ds = AsyncOpenAI(api_key=_key[0] if isinstance(_key, list) else _key, base_url=_src["api_base"], timeout=60)
NOTHINK = {"thinking": {"type": "disabled"}}
WRITERS = {"l1a": "kaju-writer-l1a", "l1b": "kaju-writer-l1b", "l1c": "kaju-writer-l1c"}


async def ds_chat(system, user, temperature=0.3):
    r = await ds.chat.completions.create(model="deepseek-flash", temperature=temperature, extra_body=NOTHINK,
                                         messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return r.choices[0].message.content or ""


def local(model, system, user):
    body = json.dumps({"model": model, "temperature": 0.7, "top_p": 0.9, "max_tokens": 220,
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:11435/v1/chat/completions", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["choices"][0]["message"]["content"]


async def guard(said, draft, new, title, ctx):
    out = await ds_chat(live_rw.GUARD, live_rw.guard_prompt(said, draft, new, title, ctx), 0.0)
    bad, why = live_rw.guard_bad(out)[:2]
    if not bad and live_rw.added_opener(new, draft) and not live_rw.guard_opener_ok(out):
        new = live_rw.strip_opener(new)
    return bad, why, new


async def run_item(x):
    ctx, draft, title = x["ctx"], x["draft"], x.get("to") or "兄长大人"
    kind = "私聊" if title == "兄长大人" else "群聊"
    said = ctx[-1].split("：", 1)[-1] if ctx else ""
    res = {}
    # v3.1：看草稿重说
    raw = live_rw.clean_output(local("kaju-rewriter", live_rw.SYSTEM, live_rw.build_prompt(ctx, draft)))
    res["v31"] = await finish(raw, draft, said, title, ctx, ok=live_rw.sane(raw, draft) and not live_rw.wrong_title(raw, draft, title))
    # 新写手：同一张卡（从草稿抽，和线上 card 模式一样）
    c = card.parse(await ds_chat(card.EXTRACT, card.extract_prompt(ctx, draft, kind, title), 0.3))
    card_text = card.render(c, kind, title) if c else ""
    for k, model in WRITERS.items():
        if not card_text:
            res[k] = {"text": draft, "raw": "", "fell_back": "没抽出卡"}
            continue
        raw = card.fix_formal(live_rw.clean_output(local(model, card.WRITE_SYSTEM[2], card.write_prompt(ctx, card_text))), draft, title)
        res[k] = await finish(raw, draft, said, title, ctx, ok=card.sane(raw, draft))
    return {"id": f"ly-{x['id']}", "kind": kind, "to": title, "ctx": ctx, "draft": draft, "card": card_text, "cands": res}


async def finish(raw, draft, said, title, ctx, ok):
    if not ok or not raw.strip() or raw.strip() == draft.strip():
        return {"text": draft, "raw": raw, "fell_back": "不像回复/一样"}
    try:
        bad, why, new = await guard(said, draft, raw, title, ctx)
    except Exception as e:  # noqa: BLE001
        return {"text": draft, "raw": raw, "fell_back": f"核对失败 {type(e).__name__}"}
    if bad:
        return {"text": draft, "raw": raw, "fell_back": f"核对没过：{why}"}
    return {"text": new, "raw": raw, "fell_back": ""}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--writers", default="l1a,l1b,l1c", help="比哪些新写手，逗号分隔")
    ap.add_argument("--exclude", default="", help="这些出题结果（jsonl）里用过的题不再出")
    ap.add_argument("--chat-only", action="store_true", help="不要说说题（上下文最后一句是「佳树自己发一条说说」的）")
    a = ap.parse_args()
    for k in list(WRITERS):
        if k not in a.writers.split(","):
            WRITERS.pop(k)
    used = set()
    if a.exclude:
        used = {json.loads(l)["id"] for l in open(a.exclude, encoding="utf-8") if l.strip()}
    items = json.load(open(os.path.join(ROOT, "voice_train", "data", "ab5_items.json"), encoding="utf-8"))
    items = [x for x in items if f"ly-{x['id']}" not in used
             and not (a.chat_only and x["ctx"] and "说说" in x["ctx"][-1])]
    print(f"可出的题 {len(items)} 道")
    rng = random.Random(11)
    by = {}
    for x in items:
        by.setdefault(x.get("src", "?"), []).append(x)
    picked = []
    while len(picked) < min(a.n, len(items)):  # 各来源轮流挑，场景/私聊/群聊都有
        for src in sorted(by):
            if by[src] and len(picked) < a.n:
                picked.append(by[src].pop(rng.randrange(len(by[src]))))
    rows = []
    for i, x in enumerate(picked, 1):
        rows.append(await run_item(x))
        fb = {k: bool(v["fell_back"]) for k, v in rows[-1]["cands"].items()}
        print(f"{i}/{len(picked)} {x.get('src')} 退回草稿：{fb}")
    with open(a.out, "x", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    from collections import Counter
    for k in ["v31", *WRITERS]:
        c = Counter(bool(r["cands"][k]["fell_back"]) for r in rows)
        print(f"{k}: 用上自己写的 {c[False]}，退回草稿 {c[True]}")
    print(f"共 {len(rows)} 题 → {a.out}")


if __name__ == "__main__":
    asyncio.run(main())
