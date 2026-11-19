r"""一个新 key 的全面测试（2026-11-15 兄长：不同的模型、思考强度、输入格式、输入文件类型都试一下）。

    <bot venv>\python.exe -I -X utf8 scripts\key_bench.py <gemini_keys.json 第几条 | newN = new_keys.json 第 N 条> [模型 …] [--fmt=native,openai,anthropic] [--list]
不写模型就用 new_keys.json 里写的 models，再没有就问它的模型列表。每个模型 × 三种格式（Gemini 原生 / OpenAI / Claude 原生，11-19 加）：
  text ×2（苹果题，3.5 才对）· 思考档 ×1 each（原生 thinkingLevel 不设/low/high；OpenAI reasoning_effort none/low/high）
  card ×2（上下文最长的一张真实卡）· main ×2（线上一轮真实输入 + 工具）
  image：jpg ×2、png、webp、gif（动图原样发）· audio：mp3 ×2、wav · video：mp4 ×2、gif 转成的 mp4
结果 → data\key_bench\<host>\results.json、report.md。
"""
import base64
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import format_bench as fb  # noqa: E402  post / native / openai / real_inputs / 文件路径

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
# 11-18 整理后 omni_compare\media 收进了备份包；这两个样例解到 data\key_bench\_media（11-19）
MEDIA = os.path.join(fb.VT, "data", "key_bench", "_media")
GIF = os.path.join(MEDIA, "10_gif_bow.gif")
fb.VID = os.path.join(MEDIA, "07_funny_dog.mp4")


def files(out):
    """准备各种类型的测试文件 → {名字: (mime, base64)}。"""
    from PIL import Image

    from kaju_core.senses import omni
    os.makedirs(out, exist_ok=True)
    f = {}
    jpg = open(fb.IMG, "rb").read()
    f["jpg"] = ("image/jpeg", jpg)
    im = Image.open(io.BytesIO(jpg)).convert("RGB")
    for fmt, mime in (("PNG", "image/png"), ("WEBP", "image/webp")):
        buf = io.BytesIO()
        im.save(buf, fmt)
        f[fmt.lower()] = (mime, buf.getvalue())
    f["gif"] = ("image/gif", open(GIF, "rb").read())
    mp3 = os.path.join(out, "dog.mp3")
    if not os.path.exists(mp3):
        omni.to_mp3(fb.VID, mp3)
    f["mp3"] = ("audio/mp3", open(mp3, "rb").read())
    wav = os.path.join(out, "dog.wav")
    if not os.path.exists(wav):
        import av
        with av.open(fb.VID) as src, av.open(wav, "w", format="wav") as dst:
            a = next(s for s in src.streams if s.type == "audio")
            o = dst.add_stream("pcm_s16le", rate=16000, layout="mono")
            rs = av.AudioResampler(format="s16", layout="mono", rate=16000)
            for frame in src.decode(a):
                for fr in rs.resample(frame):
                    for p in o.encode(fr):
                        dst.mux(p)
            for p in o.encode(None):
                dst.mux(p)
    f["wav"] = ("audio/wav", open(wav, "rb").read())
    f["mp4"] = ("video/mp4", open(fb.VID, "rb").read())
    g4 = os.path.join(out, "bow.mp4")
    if not os.path.exists(g4):
        omni.gif_to_mp4(GIF, g4)
    f["gif.mp4"] = ("video/mp4", open(g4, "rb").read())
    return {k: (m, base64.b64encode(b).decode(), len(b)) for k, (m, b) in f.items()}


def parts(fmt, mime, b64):
    if fmt == "native":
        return [{"inline_data": {"mime_type": mime, "data": b64}}]
    if fmt == "anthropic":
        if mime.startswith("image/"):
            return [{"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}]
        return [{"type": "document", "source": {"type": "base64", "media_type": mime, "data": b64}}]
    if mime.startswith("image/"):
        return [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]
    if mime.startswith("audio/"):
        return [{"type": "input_audio", "input_audio": {"data": b64, "format": mime.split("/")[1]}}]
    return [{"type": "video_url", "video_url": {"url": f"data:{mime};base64,{b64}"}}]


def biggest_card():
    from kaju_core.voice import card
    rows = [r for r in fb.jl(os.path.join(fb.STYLE, "rewrites", "*.jsonl")) if r.get("draft") and r.get("ctx")]
    rec = max(rows, key=lambda r: len("\n".join(r["ctx"])) + len(r["draft"]))
    return card.EXTRACT_V4, card.extract_prompt_v4(rec["ctx"], rec["draft"], rec.get("kind") or "私聊", rec.get("title") or "", False)


ASK = {"image": "这张图里是什么？一句话。", "audio": "这段音频里能听到什么？一两句话。没听到声音就直说。",
       "video": "这段视频里发生了什么？画面和声音各一句。没收到视频就直说。"}


def anthropic_think(k, msgs, tools=None, parts=None, think=""):
    """Claude 原生格式带思考：fb.anthropic 不设思考；这里 budget = 预算 1024，adaptive = 自适应（hardysapi 只认这个）。"""
    if not think or think == "none":
        return fb.anthropic(k, msgs, tools=tools, parts=parts)
    sys_ = next((m["content"] for m in msgs if m["role"] == "system"), "")
    m2 = [{"role": m["role"], "content": m["content"]} for m in msgs if m["role"] != "system"]
    if parts:
        m2[-1]["content"] = parts + [{"type": "text", "text": m2[-1]["content"]}]
    body = {"model": k["model"], "max_tokens": 4000, "messages": m2,
            "thinking": {"type": "enabled", "budget_tokens": 1024} if think == "budget" else {"type": "adaptive"}}
    if sys_:
        body["system"] = sys_
    if tools:
        body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
    base = k["base_url"].rstrip("/").removesuffix("/v1")
    j, err, dt = fb.post(f"{base}/v1/messages", body, {"x-api-key": k["api_key"], "anthropic-version": "2023-06-01"})
    if err:
        return False, dt, err
    blocks = j.get("content") or []
    tu = [b["name"] for b in blocks if b.get("type") == "tool_use"]
    txt = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    thought = any(b.get("type") == "thinking" for b in blocks)
    return bool(tu or txt), dt, ("[有思考] " if thought else "") + ((f"调工具 {tu[0]}" if tu else txt[:80]) or "空")


THINK = {"native": ("", "low", "high"), "openai": ("none", "low", "high"), "anthropic": ("none", "budget", "adaptive")}
LOW = {"native": "low", "openai": "low", "anthropic": ""}


def load_key(arg: str) -> dict:
    """“3” = gemini_keys.json 第 3 条；“new3” = new_keys.json 第 3 条（11-19 兄长新填的）。"""
    if arg.startswith("new"):
        keys = json.load(open(os.path.join(fb.ACC, "new_keys.json"), encoding="utf-8-sig"))["keys"]
        return keys[int(arg[3:] or 1) - 1]
    keys = json.load(open(os.path.join(fb.ACC, "gemini_keys.json"), encoding="utf-8-sig"))["keys"]
    return keys[int(arg) - 1]


def list_models(k0: dict) -> list[str]:
    import urllib.request
    base = k0["base_url"].rstrip("/").removesuffix("/v1beta").removesuffix("/v1")
    for path, hdr in (("/v1/models", {"Authorization": "Bearer " + k0["api_key"]}),
                      ("/v1/models", {"x-api-key": k0["api_key"], "anthropic-version": "2023-06-01"}),
                      ("/v1beta/models", {"x-goog-api-key": k0["api_key"]})):
        try:
            r = urllib.request.urlopen(urllib.request.Request(base + path, headers={**hdr, "User-Agent": "python-client"}), timeout=30)
            j = json.loads(r.read())
            if j.get("data"):
                return sorted(m["id"] for m in j["data"])
            if j.get("models"):
                return sorted(m["name"].removeprefix("models/") for m in j["models"])
        except Exception as e:  # noqa: BLE001
            print(f"  模型列表 {path} 没拿到：{type(e).__name__} {str(e)[:80]}", flush=True)
    return []


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fmts = next((a[len("--fmt="):].split(",") for a in sys.argv[1:] if a.startswith("--fmt=")), None)
    k0 = load_key(args[0])
    host = k0["base_url"].split("//")[-1].split("/")[0]
    out = os.path.join(fb.VT, "data", "key_bench", host + time.strftime("-%m%d"))
    models = args[1:] or list(k0.get("models") or [])
    if "--list" in sys.argv:
        print(f"{host}：", list_models(k0))
        return
    if not models:
        models = list_models(k0)
    if not models:
        sys.exit(f"{host}：没拿到模型列表，在 new_keys.json 的 models 里写上模型名再跑")
    F = files(out)
    msgs, tools, _, _ = fb.real_inputs()
    csys, cuser = biggest_card()
    print(f"{host}：{len(models)} 个模型 {models}；出卡提示 {len(csys) + len(cuser)} 字；主模型 {sum(len(m['content']) for m in msgs)} 字 + {len(tools)} 工具；"
          + "，".join(f"{n} {v[2] // 1024}KB" for n, v in F.items()), flush=True)
    FN = {"native": fb.native, "openai": fb.openai, "anthropic": anthropic_think}

    def jobs(model, fmt):
        k = dict(k0, model=model, claude=fmt == "anthropic")
        f = FN[fmt]
        low = LOW[fmt]
        js = [("text", f"text#{i}", lambda: f(k, [{"role": "user", "content": fb.Q}], think="")) for i in (1, 2)]
        for th in THINK[fmt]:
            js.append(("think", f"think {th or '不设'}", lambda th=th: f(k, [{"role": "user", "content": fb.Q}], think=th)))
        js += [("card", f"card#{i}", lambda: f(k, [{"role": "system", "content": csys}, {"role": "user", "content": cuser}], think=low))
               for i in (1, 2)]
        js += [("main", f"main#{i}", lambda: f(k, msgs, tools=tools, think=low)) for i in (1, 2)]
        for name, n in (("jpg", 2), ("png", 1), ("webp", 1), ("gif", 1), ("mp3", 2), ("wav", 1), ("mp4", 2), ("gif.mp4", 1)):
            mime, b64, _ = F[name]
            kind = "image" if mime.startswith("image/") else "audio" if mime.startswith("audio/") else "video"
            for i in range(n):
                js.append((kind, f"{kind} {name}#{i + 1}", lambda mime=mime, b64=b64, kind=kind: f(
                    k, [{"role": "user", "content": ASK[kind]}], parts=parts(fmt, mime, b64), think="")))
        return js

    def run_line(arg):
        model, fmt = arg
        rows = []
        for kind, label, call in jobs(model, fmt):
            try:
                ok, dt, said = call()
            except Exception as e:  # noqa: BLE001
                ok, dt, said = False, 0.0, f"{type(e).__name__} {e}"[:90]
            rows.append({"model": model, "fmt": fmt, "kind": kind, "label": label, "ok": ok, "secs": round(dt, 1), "said": said})
            print(f"  {model:<22} {fmt:<6} {label:<14} {'OK ' if ok else 'FAIL'} {dt:5.1f}s {said[:60]!r}", flush=True)
        return rows

    lines = [(m, f) for m in models for f in (fmts or ("native", "openai", "anthropic"))]
    with ThreadPoolExecutor(len(lines)) as ex:
        rows = [r for part in ex.map(run_line, lines) for r in part]
    json.dump(rows, open(os.path.join(out, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    labels = list(dict.fromkeys(r["label"].split("#")[0] for r in rows))
    md = [f"# {host} 全面测试（{time.strftime('%Y-%m-%d %H:%M')}）", "", "格子：成几次/测几次 平均秒数。回答开头见下面。", "",
          "| 模型 | 格式 | " + " | ".join(labels) + " |", "|---|---|" + "---|" * len(labels)]
    for m, f in lines:
        cells = []
        for lb in labels:
            rs = [r for r in rows if r["model"] == m and r["fmt"] == f and r["label"].split("#")[0] == lb]
            good = [r for r in rs if r["ok"]]
            cells.append((f"{len(good)}/{len(rs)} {sum(r['secs'] for r in good) / len(good):.1f}s" if good else f"0/{len(rs)}") if rs else "—")
        md.append(f"| {m} | {f} | " + " | ".join(cells) + " |")
    md += ["", "## 回答开头", ""]
    for r in rows:
        md.append(f"- {r['model']} {r['fmt']} {r['label']}：{'' if r['ok'] else '失败 '}{r['secs']}s {r['said'][:90]!r}")
    open(os.path.join(out, "report.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("完成：" + os.path.join(out, "report.md"), flush=True)


if __name__ == "__main__":
    main()
