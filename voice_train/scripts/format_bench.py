r"""各家中转 × 两种请求格式 × 各个功能，速度和能不能用（2026-11-14 兄长：不同的输入格式你试过吗？原生或者 OpenAI 之类的）。

  Gemini 中转（gemini_keys.json）：原生 generateContent / OpenAI chat.completions
  Claude 中转（text_models.json）：OpenAI chat.completions / Claude 原生 messages
功能（各测 2 次）：
  text   短文字（苹果题，看答没答对）
  card   出卡：线上一张真实卡的提示词（EXTRACT_V4 + 那次的聊天和草稿）
  main   主模型：线上一轮真实输入（系统提示 + 历史 + 这一轮，五六万字）+ 这一轮能用的工具（只有名字，参数照一个 query 补的）
  image  看一张表情包（看认没认出是梗图）
  audio  听一段 mp3（Claude 不测）
  video  看一段 0.3MB mp4（Claude 不测）
结果 → data\format_bench\results.json、report.md。
用法：<bot venv>\python.exe -I -X utf8 scripts\format_bench.py
"""
import base64
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
sys.path.insert(0, r"D:\JiashuBot\bot_setup")
os.environ.setdefault("KAJU_DATA", r"D:\JiashuBot\kaju_data")
from kaju_core.voice import card  # noqa: E402

VT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(VT, "data", "format_bench")
ACC = r"D:\JiashuBot\kaju_data\accounts"
STYLE = r"D:\JiashuBot\kaju_data\self\kaju_style"
IMG = r"D:\JiashuBot\kaju_data\self\meme_manager\auto_collect_inbox\images\kaju_memes__196b1bca4c5eeafd7d0207349d5dcc1880e8c431b5c1e3e48e8a417d3ad9602c.jpg"
VID = r"D:\JiashuBot\bot_setup\tools\omni_compare\media\07_funny_dog.mp4"
MP3 = os.path.join(OUT, "dog.mp3")
Q = "小明有 3 个苹果，给了小红 1 个，又买了 5 个，然后吃掉一半。他现在有几个？只回答数字和一句理由。"
TIMEOUT = 120
RUNS = 2


def jl(pattern):
    out = []
    for p in sorted(glob.glob(pattern)):
        out += [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]
    return out


def real_inputs():
    """线上最近一轮真实主模型输入，和一张真实卡的出卡提示词。"""
    di = jl(os.path.join(STYLE, "draft_inputs", "*.jsonl"))[-1]
    msgs = [{"role": "system", "content": di.get("system_prompt") or ""}]
    for c in di.get("contexts") or []:
        role, text = c.get("role"), str(c.get("text") or c.get("content") or "").strip()
        if role not in ("user", "assistant") or not text:
            continue
        if msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n" + text
        else:
            msgs.append({"role": role, "content": text})
    now = "\n".join([str(di.get("prompt") or "")] + [str(x) for x in di.get("extra") or []]).strip()
    if msgs[-1]["role"] == "user":
        msgs[-1]["content"] += "\n" + now
    else:
        msgs.append({"role": "user", "content": now})
    tools = [{"name": n, "description": f"佳树的工具 {n}", "parameters": {"type": "object", "properties": {
        "query": {"type": "string", "description": "要做的事或要找的内容"}}, "required": []}} for n in di.get("tools") or []]
    rec = next(r for r in reversed(jl(os.path.join(STYLE, "rewrites", "*.jsonl"))) if r.get("draft") and r.get("ctx"))
    card_user = card.extract_prompt_v4(rec["ctx"], rec["draft"], rec.get("kind") or "私聊", rec.get("title") or "", False)
    return msgs, tools, card.EXTRACT_V4, card_user


def post(url, body, hdr):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", "User-Agent": "python-client", **hdr})
    t = time.time()
    try:
        return json.load(urllib.request.urlopen(req, timeout=TIMEOUT)), None, time.time() - t
    except urllib.error.HTTPError as ex:
        return None, f"HTTP {ex.code} {ex.read().decode('utf-8', 'replace')[:90]}", time.time() - t
    except Exception as ex:  # noqa: BLE001
        return None, f"{type(ex).__name__} {str(ex)[:60]}", time.time() - t


# ------------------------------------------------------------------ 三种格式各怎么发
def native(k, msgs, tools=None, parts=None, think="low"):
    sys_ = next((m["content"] for m in msgs if m["role"] == "system"), "")
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in msgs if m["role"] != "system"]
    if parts:
        contents[-1]["parts"] = parts + contents[-1]["parts"]
    body = {"contents": contents}
    if sys_:
        body["systemInstruction"] = {"parts": [{"text": sys_}]}
    if tools:
        body["tools"] = [{"functionDeclarations": tools}]
    if think:
        body["generationConfig"] = {"thinkingConfig": {"thinkingLevel": think}}
    base = k["base_url"].rstrip("/").removesuffix("/v1beta").removesuffix("/v1")
    j, err, dt = post(f"{base}/v1beta/models/{k['model']}:generateContent", body, {"x-goog-api-key": k["api_key"]})
    if err:
        return False, dt, err
    try:
        ps = j["candidates"][0]["content"]["parts"]
    except Exception:  # noqa: BLE001
        return False, dt, "没回字 " + json.dumps(j, ensure_ascii=False)[:90]
    fc = [p["functionCall"]["name"] for p in ps if p.get("functionCall")]
    txt = "".join(p.get("text", "") for p in ps if not p.get("thought")).strip()
    return bool(fc or txt), dt, (f"调工具 {fc[0]}" if fc else txt[:80]) or "空"


def openai(k, msgs, tools=None, parts=None, think="low"):
    m2 = [dict(m) for m in msgs]
    if parts:
        m2[-1]["content"] = parts + [{"type": "text", "text": m2[-1]["content"]}]
    body = {"model": k["model"], "messages": m2, "max_tokens": 2000}
    if tools:
        body["tools"] = [{"type": "function", "function": t} for t in tools]
    if think and not k.get("claude"):
        body["reasoning_effort"] = think
    base = k["base_url"].rstrip("/").removesuffix("/v1beta").removesuffix("/v1")
    j, err, dt = post(f"{base}/v1/chat/completions", body, {"Authorization": "Bearer " + k["api_key"]})
    if err:
        return False, dt, err
    try:
        m = j["choices"][0]["message"]
    except Exception:  # noqa: BLE001
        return False, dt, "没回字 " + json.dumps(j, ensure_ascii=False)[:90]
    if m.get("tool_calls"):
        return True, dt, "调工具 " + m["tool_calls"][0]["function"]["name"]
    txt = str(m.get("content") or "").strip()
    return bool(txt), dt, txt[:80] or "空"


def anthropic(k, msgs, tools=None, parts=None, think="low"):
    sys_ = next((m["content"] for m in msgs if m["role"] == "system"), "")
    m2 = [{"role": m["role"], "content": m["content"]} for m in msgs if m["role"] != "system"]
    if parts:
        m2[-1]["content"] = parts + [{"type": "text", "text": m2[-1]["content"]}]
    body = {"model": k["model"], "max_tokens": 2000, "messages": m2}
    if sys_:
        body["system"] = sys_
    if tools:
        body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
    base = k["base_url"].rstrip("/").removesuffix("/v1")
    j, err, dt = post(f"{base}/v1/messages", body, {"x-api-key": k["api_key"], "anthropic-version": "2023-06-01"})
    if err:
        return False, dt, err
    blocks = j.get("content") or []
    tu = [b["name"] for b in blocks if b.get("type") == "tool_use"]
    txt = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    return bool(tu or txt), dt, (f"调工具 {tu[0]}" if tu else txt[:80]) or "空"


def media_parts(fmt, kind):
    if kind == "image":
        b = base64.b64encode(open(IMG, "rb").read()).decode()
        return {"native": [{"inline_data": {"mime_type": "image/jpeg", "data": b}}],
                "openai": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b}}],
                "anthropic": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}}]}[fmt]
    if kind == "audio":
        b = base64.b64encode(open(MP3, "rb").read()).decode()
        return {"native": [{"inline_data": {"mime_type": "audio/mp3", "data": b}}],
                "openai": [{"type": "input_audio", "input_audio": {"data": b, "format": "mp3"}}]}[fmt]
    b = base64.b64encode(open(VID, "rb").read()).decode()
    return {"native": [{"inline_data": {"mime_type": "video/mp4", "data": b}}],
            "openai": [{"type": "video_url", "video_url": {"url": "data:video/mp4;base64," + b}}]}[fmt]


def main():
    os.makedirs(OUT, exist_ok=True)
    from kaju_core.senses import omni
    if not os.path.exists(MP3):
        omni.to_mp3(VID, MP3)
    msgs, tools, card_sys, card_user = real_inputs()
    print(f"主模型输入 {sum(len(m['content']) for m in msgs)} 字、{len(tools)} 个工具；出卡提示 {len(card_sys) + len(card_user)} 字", flush=True)
    gk = json.load(open(os.path.join(ACC, "gemini_keys.json"), encoding="utf-8"))["keys"]
    tk = json.load(open(os.path.join(ACC, "text_models.json"), encoding="utf-8-sig"))["keys"]
    provs = [dict(k, model=k.get("model") or "gemini-3.8-flash", claude=False) for k in gk if k.get("enabled", True) is not False]
    provs += [dict(k, claude=True) for k in tk if k.get("enabled", True) is not False]
    FN = {"native": native, "openai": openai, "anthropic": anthropic}
    tasks = {
        "text": lambda f, k: f(k, [{"role": "user", "content": Q}]),
        "card": lambda f, k: f(k, [{"role": "system", "content": card_sys}, {"role": "user", "content": card_user}]),
        "main": lambda f, k: f(k, msgs, tools=tools, think="" if k["claude"] else "low"),
        "image": lambda f, k: f(k, [{"role": "user", "content": "这张图里是什么？一句话。"}], parts=media_parts(f.__name__, "image")),
        "audio": lambda f, k: f(k, [{"role": "user", "content": "这段音频里能听到什么？一两句话。没听到就直说。"}], parts=media_parts(f.__name__, "audio")),
        "video": lambda f, k: f(k, [{"role": "user", "content": "这段视频里发生了什么？画面和声音各一句。"}], parts=media_parts(f.__name__, "video")),
    }

    def jobs_for(k):
        fmts = ["openai", "anthropic"] if k["claude"] else ["native", "openai"]
        names = ["text", "card", "main", "image"] + ([] if k["claude"] else ["audio", "video"])
        return [(k, f, t) for f in fmts for t in names]

    def run_line(line):
        rows = []
        for k, fmt, task in line:
            for i in range(RUNS):
                try:
                    ok, dt, said = tasks[task](FN[fmt], k)
                except Exception as e:  # noqa: BLE001
                    ok, dt, said = False, 0.0, f"{type(e).__name__} {e}"[:90]
                rows.append({"who": k.get("name") or k["base_url"], "host": k["base_url"].split("//")[-1], "model": k["model"],
                             "fmt": fmt, "task": task, "run": i + 1, "ok": ok, "secs": round(dt, 1), "said": said})
                print(f"  {rows[-1]['host']:<20} {fmt:<9} {task:<5} #{i + 1} {'OK ' if ok else 'FAIL'} {dt:5.1f}s {said[:50]!r}", flush=True)
        return rows

    lines = []
    for k in provs:  # 每家每种格式一条线（同一家同一格式按顺序发，免得自己把自己挤爆）
        js = jobs_for(k)
        for f in sorted({j[1] for j in js}):
            lines.append([j for j in js if j[1] == f])
    with ThreadPoolExecutor(len(lines)) as ex:
        rows = [r for part in ex.map(run_line, lines) for r in part]
    json.dump(rows, open(os.path.join(OUT, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md = ["# 各家 × 格式 × 功能（2026-11-14）", "", "格子里：成几次 / 2，成了的平均秒数；后面是第一次成了的回答开头。", ""]
    order = ["text", "card", "main", "image", "audio", "video"]
    md += ["| 中转 | 模型 | 格式 | " + " | ".join(order) + " |", "|---|---|---|" + "---|" * len(order)]
    keyset = []
    for r in rows:
        kk = (r["host"], r["model"], r["fmt"])
        if kk not in keyset:
            keyset.append(kk)
    for host, model, fmt in keyset:
        cells = []
        for t in order:
            rs = [r for r in rows if (r["host"], r["model"], r["fmt"], r["task"]) == (host, model, fmt, t)]
            if not rs:
                cells.append("—")
                continue
            good = [r for r in rs if r["ok"]]
            cells.append(f"{len(good)}/{len(rs)} {sum(r['secs'] for r in good) / len(good):.1f}s" if good else f"0/{len(rs)}")
        md.append(f"| {host} | {model} | {fmt} | " + " | ".join(cells) + " |")
    md += ["", "## 回答开头（每格第一次成了的那次）", ""]
    for host, model, fmt in keyset:
        for t in order:
            r = next((r for r in rows if (r["host"], r["model"], r["fmt"], r["task"]) == (host, model, fmt, t) and r["ok"]), None)
            bad = next((r for r in rows if (r["host"], r["model"], r["fmt"], r["task"]) == (host, model, fmt, t) and not r["ok"]), None)
            if r or bad:
                md.append(f"- {host} {fmt} {t}：" + (f"{r['said'][:70]!r}" if r else f"失败 {bad['said'][:70]}"))
    open(os.path.join(OUT, "report.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("完成：" + os.path.join(OUT, "report.md"), flush=True)


if __name__ == "__main__":
    main()
