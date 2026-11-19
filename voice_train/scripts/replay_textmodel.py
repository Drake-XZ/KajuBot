r"""纯文字对话换别家模型写草稿的盲选（2026-11-14 兄长：普通对话能不能用别的大模型；不要国内模型 → 试 Claude）。

同一批线上真实输入（kaju_style 的 draft_inputs：主模型那一轮收到的系统提示、历史、这一轮的话、附加提醒），两家各写一份草稿：
  A gemini：aigocode gemini-3.8-flash（线上主模型 gemini_flash38 同一家、同一格式）；没答上来就用当时线上那份草稿
  B claude：text_models.json 里 hardysapi 的 claude-sonnet-5-5（OpenAI 格式）
两边都不带工具（回放没法真去执行工具，两边一样）。两份草稿都走线上同一条路：Gemini 出卡（EXTRACT_V4 + 当时那张卡的心情行）
→ 线上写手（state.json 的 live_model）照卡写。盲选页只给聊天和对方这句，不露草稿（看文风就知道是谁）。

  drafts  两家写草稿 → data\textmodel_ab\drafts.json
  write   出卡 + 写手 → write.json（要 Ollama 里的线上写手）
  page    二选一盲选页 review\textmodel_ab.html（collection votes；对照 data\textmodel_ab\key.json）
用法：<bot venv>\python.exe -I -X utf8 scripts\replay_textmodel.py drafts|write|page|all
"""
import argparse
import asyncio
import glob
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import round_train as rt  # noqa: E402  sys.path / KAJU_DATA、write()、lines()

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
STYLE = r"D:\JiashuBot\kaju_data\self\kaju_style"
ACC = r"D:\JiashuBot\kaju_data\accounts"
D = os.path.join(rt.VT, "data", "textmodel_ab")


def jl(pattern):
    out = []
    for p in sorted(glob.glob(pattern)):
        out += [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]
    return out


def load():
    rec = {str(r["t"]): r for r in jl(os.path.join(STYLE, "rewrites", "*.jsonl"))}
    rows = []
    for d in jl(os.path.join(STYLE, "draft_inputs", "*.jsonl")):
        r = rec.get(str(d["t"]))
        if not r or d.get("images"):
            continue
        c = (r.get("card") or [{}])[-1] if isinstance(r.get("card"), list) else {}
        rows.append({"id": str(d["t"]), "kind": r.get("kind") or "私聊", "to": r.get("title") or "", "ctx": r.get("ctx") or [],
                     "said": r.get("said") or "", "live_draft": r.get("draft") or "", "live_final": r.get("final") or "",
                     "mood": next((x for x in str(c.get("card") or "").splitlines() if x.startswith("心情：")), ""),
                     "felt": "felt" in c, "input": d})
    return rows


def messages(d):
    """draft_inputs 一行 → OpenAI messages：系统提示 + 历史（工具那几轮去掉、同一边连着的合成一条）+ 这一轮（附加提醒接在后面）。"""
    msgs = [{"role": "system", "content": d.get("system_prompt") or ""}]
    for c in d.get("contexts") or []:
        role = c.get("role")
        text = str(c.get("text") or c.get("content") or "").strip()
        if role not in ("user", "assistant") or not text:
            continue
        if msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n" + text
        else:
            msgs.append({"role": role, "content": text})
    now = "\n".join([str(d.get("prompt") or "")] + [str(x) for x in d.get("extra") or []]).strip()
    if msgs[-1]["role"] == "user":
        msgs[-1]["content"] += "\n" + now
    else:
        msgs.append({"role": "user", "content": now})
    return msgs


def key_of(path, host):
    d = json.load(open(path, encoding="utf-8-sig"))
    return next(k for k in d["keys"] if host in k["base_url"])


def chat(k, model, msgs, timeout=120):
    body = {"model": model, "messages": msgs, "max_tokens": 2000}
    base = k["base_url"].rstrip("/").removesuffix("/v1")
    req = urllib.request.Request(base + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "python-client",
                                  "Authorization": "Bearer " + k["api_key"]})
    t = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.load(r)
    text = str(((j.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if not text:
        raise RuntimeError("没回字 " + json.dumps(j, ensure_ascii=False)[:120])
    return text, time.time() - t


async def make_drafts():
    rows = load()
    gem = key_of(os.path.join(ACC, "gemini_keys.json"), "aigocode")
    cla = key_of(os.path.join(ACC, "text_models.json"), "hardysapi.com")
    sem = asyncio.Semaphore(4)

    async def one(k, model, r, tries=2):
        async with sem:
            for i in range(tries):
                try:
                    return await asyncio.to_thread(chat, k, model, messages(r["input"]))
                except Exception as e:  # noqa: BLE001
                    print(f"  {model} 第 {i + 1} 次没写成 {r['id']} {type(e).__name__}: {str(e)[:80]}", flush=True)
            return "", 0.0

    ga = await asyncio.gather(*[one(gem, gem["model"], r) for r in rows])
    cb = await asyncio.gather(*[one(cla, cla["model"], r) for r in rows])
    for r, (a, ta), (b, tb) in zip(rows, ga, cb):
        r["draft_a"], r["secs_a"] = (a, ta) if a else (r["live_draft"], 0.0)
        r["a_from"] = "gemini-3.8-flash 重写" if a else "线上当时那份"
        r["draft_b"], r["secs_b"] = b, tb
        del r["input"]
    os.makedirs(D, exist_ok=True)
    json.dump(rows, open(os.path.join(D, "drafts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sa = [r["secs_a"] for r in rows if r["secs_a"]]
    sb = [r["secs_b"] for r in rows if r["secs_b"]]
    print(f"草稿：{len(rows)} 轮；Gemini 重写成 {len(sa)}（其余用线上那份），平均 {sum(sa) / max(1, len(sa)):.1f}s；"
          f"Claude 写成 {len(sb)}，平均 {sum(sb) / max(1, len(sb)):.1f}s", flush=True)


async def make_cards_and_write():
    import build_layered as bl
    bl.use_gemini()
    from kaju_core.senses import omni
    from kaju_core.voice import card
    rows = json.load(open(os.path.join(D, "drafts.json"), encoding="utf-8"))
    sem = asyncio.Semaphore(4)

    async def one(r, draft):
        if not draft:
            return ""
        async with sem:
            for attempt in range(3):
                try:
                    out, _ = await omni.text(card.EXTRACT_V4, card.extract_prompt_v4(r["ctx"], draft, r["kind"], r["to"], r["felt"]),
                                             timeout=60)
                    g = card.parse_v4(out)
                    if g:
                        return card.render_v4(r["kind"], r["to"], g, r["mood"])
                except Exception as e:  # noqa: BLE001
                    print("  出卡没成", r["id"], type(e).__name__, attempt + 1, flush=True)
            return ""

    ca = await asyncio.gather(*[one(r, r["draft_a"]) for r in rows])
    cb = await asyncio.gather(*[one(r, r["draft_b"]) for r in rows])
    model = rt.state()["live_model"]
    for i, (r, a, b) in enumerate(zip(rows, ca, cb)):
        r["card_a"], r["card_b"] = a, b
        r["out_a"] = rt.write(model, r["ctx"], a) if a else ""
        r["out_b"] = rt.write(model, r["ctx"], b) if b else ""
        print(f"  写了 {i + 1}/{len(rows)}", flush=True)
    json.dump(rows, open(os.path.join(D, "write.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def make_page():
    rows = json.load(open(os.path.join(D, "write.json"), encoding="utf-8"))
    rng = random.Random(20261114 + 77)
    ok = [r for r in rows if r.get("out_a") and r.get("out_b") and rt.lines(r["out_a"]) != rt.lines(r["out_b"])]
    page, key = [], {}
    for r in ok:
        order = ["gemini", "claude"]
        rng.shuffle(order)
        iid = f"tm-{len(page) + 1}"
        texts = {"gemini": r["out_a"], "claude": r["out_b"]}
        key[iid] = {"A": order[0], "B": order[1], "src": r["id"], "a_from": r["a_from"]}
        page.append({"id": iid, "n": len(page) + 1, "src": "group" if r["kind"] == "群聊" else "private", "to": r["to"] or "无",
                     "draft": r["said"] or "（没有）", "draft_label": "对方这句（草稿不显示，免得看出是哪家）",
                     "ctx": r["ctx"][-6:] or ["（没有前文）"],
                     "A": {"text": texts[order[0]], "blocked": ""}, "B": {"text": texts[order[1]], "blocked": ""}})
    json.dump(key, open(os.path.join(D, "key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(rt.VT, "review", "round_ab.template.html"), encoding="utf-8").read()
    html = os.path.join(rt.VT, "review", "textmodel_ab.html")
    open(html, "w", encoding="utf-8", newline="\n").write(
        tpl.replace("/*TITLE*/", "草稿换模型盲选").replace("__ITEMS__", json.dumps(page, ensure_ascii=False).replace("</", "<\\/")))
    print(f"盲选页 {html}：{len(page)} 对（两边都写出来且不一样的 {len(ok)}/{len(rows)}）", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["drafts", "write", "page", "all"])
    a = ap.parse_args()
    if a.cmd in ("drafts", "all"):
        asyncio.run(make_drafts())
    if a.cmd in ("write", "all"):
        asyncio.run(make_cards_and_write())
    if a.cmd in ("page", "all"):
        make_page()


if __name__ == "__main__":
    main()
