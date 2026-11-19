r"""看视频 / 听歌的模型三方对比（2026-11-12 兄长在考虑换掉 qwen omni）。同样 6 条素材、同样大小的文件：

  old     现在线上的做法：qwen3.8-omni-flash + 现在的提示（直接取 voice_train\data\review8_felt.json 里已有的，不重跑）
  qwen2   qwen3.8-omni-flash + 新提示（多要一栏听感；感受的条数跟着触动程度走）
  gem     gemini-3.8-flash（中转平台，kaju_data\accounts\gemini.json）+ 同一份新提示

    python -I compare_models.py run     → results\models_r9.json（已有的不重跑）
    python -I compare_models.py page    → voice_train\review\omni2.html + voice_train\data\omni2_key.json

不改线上的 kaju_core\senses\omni.py：新提示只在这里拼。
"""
import asyncio
import base64
import json
import os
import random
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
VT = r"D:\JiashuBot\voice_train"
sys.path.insert(0, os.path.join(VT, "scripts"))
import build_review8 as b8  # noqa: E402  (samples：素材清单和路径；顺带把 bot_setup 放进 sys.path)
from kaju_core.senses import omni  # noqa: E402

OUT = os.path.join(HERE, "results", "models_r9.json")
PICK = ["01_mv_jixie", "03_song_kohaku", "06_dance_miku", "04_clip_red", "17_shelf18", "20_browse"]
GEM = omni.gemini_key()  # 2026-11-12 起 key 在 accounts\gemini_keys.json（排第一的那个）
GEM_MODEL = GEM.get("model") or "gemini-3.8-flash"

# 新提示 = 现在的提示改三处：多一栏听感；感受条数跟触动程度走；声音可以写具体
SOUND = (' "sound": "声音和音乐本身听起来怎么样、让你有什么感觉：歌声、旋律、节奏、乐器、音效里真正让你有感觉的地方（大白话，用“我”）。'
         '被打动得越深写得越细，最多五句；没有声音、或者声音没给你什么感觉就留空",\n')


def new_prompt(kind, title):
    p = omni.build_prompt(kind, title)
    a = ' "arc": '
    assert a in p
    p = p.replace(a, SOUND + a, 1)
    old1 = "- moments 只挑真正有感觉的 2 到 6 个时刻，没感觉的地方不要硬写。"
    new1 = "- moments 只挑真正有感觉的时刻，条数跟着有多触动走：没什么感觉的内容 0 到 2 个就够，很打动你的可以写到 8 个；没感觉的地方不要硬写。"
    old2 = "声音说听起来的感觉，不用术语；"
    new2 = "声音写听起来的感觉，可以说到歌声、节奏、乐器、音效，不用乐理术语；"
    assert old1 in p and old2 in p
    return p.replace(old1, new1).replace(old2, new2)


def parse(text):
    raw = text[text.find("{"):text.rfind("}") + 1]
    try:
        d = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(d, dict):
        return None
    ms = [{"t": omni._s(m.get("t"), 8), "what": omni._s(m.get("what"), 120), "feel": omni._s(m.get("feel"), 120), "strength": omni._n(m.get("strength"))}
          for m in d.get("moments") or [] if isinstance(m, dict) and (m.get("feel") or m.get("what"))]
    return {"facts": omni._s(d.get("facts"), 260), "moments": ms[:8], "sound": omni._s(d.get("sound"), 500), "arc": omni._s(d.get("arc"), 120),
            "after": omni._s(d.get("after"), 200), "emotion": omni._s(d.get("emotion"), 4), "intensity": omni._n(d.get("intensity"))}


def ask_gemini(path, kind, prompt):
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    body = {"contents": [{"role": "user", "parts": [{"inline_data": {"mime_type": "audio/mp3" if kind == "audio" else "video/mp4", "data": b64}}, {"text": prompt}]}]}
    req = urllib.request.Request(GEM["base_url"].rstrip("/") + f"/v1beta/models/{GEM_MODEL}:generateContent", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "python-client", "x-goog-api-key": GEM["api_key"],
                                  "Authorization": "Bearer " + GEM["api_key"]})
    d = json.load(urllib.request.urlopen(req, timeout=300))
    text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"] if not p.get("thought"))
    u = d.get("usageMetadata") or {}
    return text, {"in": u.get("promptTokenCount"), "out": (u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0)}


async def run():
    res = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    old = json.load(open(b8.FELT, encoding="utf-8"))
    tmp = tempfile.mkdtemp()
    S = {s["id"]: s for s in b8.samples()}
    for sid in PICK:
        s = S[sid]
        r = res.setdefault(sid, {"title": s["title"], "what": s["what"], "media": s["media"]})
        r["old"] = {k: old[sid].get(k) for k in ("facts", "moments", "arc", "after", "emotion", "intensity", "secs", "usage")}
        title = "" if s["media"] == "audio" else s["title"]
        prompt = new_prompt(s["media"], title)
        send, temp = omni.prepare(s["path"], s["media"], tmp, 600 if s["media"] == "video" else 1500)
        r["bytes"] = os.path.getsize(send)
        if "qwen2" not in r:
            t = time.time()
            try:
                text, usage, effort = await omni._ask_patient(send, s["media"], prompt, {"omni_effort": "low", "omni_timeout": 150})
                p = parse(text)
                if p:
                    r["qwen2"] = {**p, "secs": round(time.time() - t, 1), "usage": usage, "effort": effort}
                else:
                    print("  qwen2 回的不是 JSON", sid, text[:100])
            except Exception as e:  # noqa: BLE001
                print("  qwen2 FAIL", sid, type(e).__name__, str(e)[:150])
        if "gem" not in r:
            t = time.time()
            try:
                text, usage = await asyncio.to_thread(ask_gemini, send, s["media"], prompt)
                p = parse(text)
                if p:
                    r["gem"] = {**p, "secs": round(time.time() - t, 1), "usage": usage}
                else:
                    print("  gem 回的不是 JSON", sid, text[:100])
            except urllib.error.HTTPError as e:
                print("  gem FAIL", sid, e.code, e.read().decode("utf-8", "replace")[:200])
            except Exception as e:  # noqa: BLE001
                print("  gem FAIL", sid, type(e).__name__, str(e)[:150])
        json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(sid, r["bytes"] // 1000, "KB", {k: (r[k]["emotion"], r[k]["intensity"], len(r[k]["moments"]), len(r[k].get("sound") or ""), r[k].get("secs"), r[k].get("usage"))
                                              for k in ("old", "qwen2", "gem") if k in r}, flush=True)
        if temp:
            try:
                os.remove(send)
            except OSError:
                pass


def show(p):
    """一份感受 → 页面上的几行（三边同一种排法）。"""
    lines = [f"整体：{p['emotion']}，强度 {p['intensity']}（0–3）"]
    for m in p["moments"]:
        lines.append(f"· {m['t']} {m['what']}——{m['feel']}（{m['strength']}）")
    if p.get("sound"):
        lines.append("听感：" + p["sound"])
    if p.get("arc"):
        lines.append("整个下来：" + p["arc"])
    if p.get("after"):
        lines.append("看完留下的：" + p["after"])
    return "\n".join(lines)


def page():
    res = json.load(open(OUT, encoding="utf-8"))
    rnd = random.Random(20261112)
    items, key = [], {}
    for n, sid in enumerate(PICK):
        r = res[sid]
        order = [k for k in ("old", "qwen2", "gem") if k in r]
        rnd.shuffle(order)
        iid = f"om2-{n + 1}"
        key[iid] = {"ABC"[i]: k for i, k in enumerate(order)} | {"rec": sid}
        it = {"id": iid, "n": n + 1, "src": "audio" if r["media"] == "audio" else "video", "to": r["what"],
              "ctx": [f"《{r['title']}》" if r["title"] else "（没有标题）"], "draft": r["old"]["facts"], "draft_label": "这条是什么（备忘）"}
        for i, k in enumerate(order):
            it["ABC"[i]] = {"text": show(r[k]), "blocked": ""}
        items.append(it)
    json.dump(key, open(os.path.join(VT, "data", "omni2_key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(VT, "review", "omni2.template.html"), encoding="utf-8").read()
    open(os.path.join(VT, "review", "omni2.html"), "w", encoding="utf-8", newline="\n").write(
        tpl.replace("__ITEMS__", json.dumps(items, ensure_ascii=False).replace("</", "<\\/")))
    print(len(items), "条 → review\\omni2.html")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        asyncio.run(run())
    else:
        page()
