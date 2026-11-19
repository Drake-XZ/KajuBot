r"""第八批第三版：感受换成 Gemini + 新问法（2026-11-12 盲选 5:1:0），短卡由全模态模型自己给要点（决定 9），不再经 DeepSeek。

和上一版（build_review8_p3.py）的区别：
  感受      Gemini 3.8 Flash，新问法（有听感）；另外多要一栏 points——她看完想说的几件短事实，条数跟触动程度走。
            points 这一栏现在只在这个脚本里加在问法后面；等线上做"全模态 → 短卡 → 写手"时把同一段话并进 kaju_core\senses\omni.py。
  局面      代码拼的：谁分享了什么 / 自己刷到什么、刚看完。不写心情（决定 11：心情不进局面，以后单独一行）。
  要说到的  就是 points，不压缩、不改写。
  长短      兄长不要这一栏。现在的 8b-A 训练时每张卡都有，出候选时临时按要点条数填；card_gold 不带。
  心情      每条存 emotion / intensity（items 里的 mood），格式等兄长定了再拼成那一行。
三个候选：两个 8b-A 照同一张卡写的；一个是 Gemini 照感受直接替她写的（代替原来 DeepSeek 那句，兄长上次就是拿这一类当底改的）。

    python -I build_review8_g.py feel    → data\review8_felt_g.json（30 次 Gemini，已有的不重跑）
    python -I build_review8_g.py cand    → data\review8_items.json、review8_key.json（上一版改名 *_p3a.json 留底）
    python -I build_review8_g.py page    → review\review8.html
"""
import asyncio
import json
import os
import random
import re
import sqlite3
import sys
import tempfile
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_review8 as b8  # noqa: E402
from kaju_core.senses import omni  # noqa: E402
import train_keys  # noqa: E402  (训练专用的 Gemini 接口，见 train_keys.py)

VT = b8.VT
FELT = os.path.join(VT, "data", "review8_felt_g.json")
WRITER = "kaju-writer-p3-8b-a"
SYS3 = json.load(open(os.path.join(VT, "train_pack", "kaju_train_pack", "data", "system.json"), encoding="utf-8"))["2"]

POINTS = (' "points": ["佳树看完最想跟人说的事，每条一件、10 到 22 个字的短事实，写成“哪一下 + 佳树怎样”，叫她“佳树”不用“我”，用平常说话的词。'
          '条数跟着有多触动走：没什么感觉 1 条，有点感觉 1 到 2 条，明显被打动 2 到 4 条，很强烈 4 到 6 条；声音值得说就占其中一两条。只写上面感受里有的"],\n')


def prompt_for(kind, title):
    p = omni.build_prompt(kind, title)
    a = ' "arc": '
    assert a in p
    return p.replace(a, POINTS + a, 1)


async def feel():
    felt = b8.load(FELT, {})
    k = train_keys.gemini()
    assert k, "accounts\\gemini_keys.json 一个 key 都没填"
    tmp = tempfile.mkdtemp()
    sem = asyncio.Semaphore(2)

    async def one(s):
        if s["id"] in felt:
            return
        title = "" if s["media"] == "audio" else s["title"]
        async with sem:
            t = time.time()
            try:
                send, temp = await asyncio.to_thread(omni.prepare, s["path"], s["media"], tmp, 600 if s["media"] == "video" else 1500)
                p = None
                for _ in range(2):  # 回的不是能用的 JSON 就再问一次
                    text, usage = await omni._ask_gemini(k, send, s["media"], prompt_for(s["media"], title), 180)
                    p = omni.parse(text)
                    if p:
                        d = json.loads(text[text.find("{"):text.rfind("}") + 1])
                        p["points"] = [omni._s(x, 40).strip("。 ") for x in d.get("points") or [] if str(x).strip()][:6]
                        break
                if temp:
                    os.remove(send)
                if not p or not p["points"]:
                    print("FAIL", s["id"], "没给出能用的感受", flush=True)
                    return
            except Exception as e:  # noqa: BLE001
                print("FAIL", s["id"], type(e).__name__, str(e)[:160], flush=True)
                return
        p.update(media=s["media"], title=s["title"], usage=usage, secs=round(time.time() - t, 1), by=k["model"])
        felt[s["id"]] = p
        b8.save(FELT, felt)
        print("ok", s["id"], p["emotion"], p["intensity"], len(p["moments"]), "处", len(p["points"]), "条要点", p["secs"], "s", flush=True)

    await asyncio.gather(*(one(s) for s in b8.samples()))
    print(len(felt), "条有感受 →", FELT)


def scene(s, p):
    name = (f"《{s['title']}》" if s["title"] and s["media"] != "audio" else "") + (f"（{p['genre']}）" if p.get("genre") else "")
    what = "一首歌" if s["what"] == "歌" else "一个" + s["what"]
    if s["src"] == "browse":
        return f"佳树自己刷B站刷到{what}{name}，刚从头看完；兄长大人问她刚才刷到什么。轮到佳树回。"
    said = b8.own_words(s["said"])
    verb = "听" if s["media"] == "audio" else "看"
    return f"兄长大人给佳树分享了{what}{name}" + (f"，说“{said}”" if said else "，别的什么都没说") + f"；佳树刚从头{verb}完。轮到佳树回。"


def render(c, with_length=True):
    lines = ["场合：私聊", "对象：兄长大人", "局面：" + c["局面"], "要说到的：" + ("；".join(c["要说到的"]) or "无")]
    if with_length:
        n = len(c["要说到的"])
        lines.append("长短：" + ("简短" if n <= 1 else "正常" if n <= 3 else "长"))
    return "\n".join(lines)


def write(ctx, card_text, temp):
    body = {"model": WRITER, "temperature": temp, "top_p": 0.9, "max_tokens": 400, "reasoning_effort": "none", "messages": [
        {"role": "system", "content": SYS3},
        {"role": "user", "content": "聊天：\n" + ("\n".join(ctx) or "（没有前文）") + "\n\n材料：\n" + card_text}]}
    req = urllib.request.Request("http://127.0.0.1:11435/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer local"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return (json.load(r)["choices"][0]["message"]["content"] or "").strip()


def gemini_say(k, persona, user):
    body = {"model": k["model"], "messages": [{"role": "system", "content": persona}, {"role": "user", "content": user}]}
    req = urllib.request.Request(k["base_url"].rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "python-client", "Authorization": "Bearer " + k["api_key"]})
    with urllib.request.urlopen(req, timeout=180) as r:
        return (json.load(r)["choices"][0]["message"]["content"] or "").strip()


def cand():
    felt = b8.load(FELT, {})
    old_items = {it["id"]: it for it in b8.load(b8.ITEMS, [])}
    done_items = []
    if old_items and next(iter(old_items.values())).get("format") == "g":
        done_items = list(old_items.values())  # 这一版自己做到一半：接着做
    else:
        for p in (b8.ITEMS, b8.KEY):  # 上一版（DeepSeek 压的短卡）留底
            bak = p.replace(".json", "_p3a.json")
            if os.path.exists(p) and not os.path.exists(bak):
                os.replace(p, bak)
    key = b8.load(b8.KEY, {}) if done_items else {}
    k = train_keys.gemini()
    db = sqlite3.connect("file:" + os.path.join(b8.CORE, "data", "data_v4.db") + "?mode=ro", uri=True)
    persona = db.execute("select system_prompt from personas where persona_id='default'").fetchone()[0]
    rnd = random.Random(2026111201)
    items = done_items
    have = {it["id"] for it in items}
    for s in b8.samples():
        sid = "r8-" + s["id"]
        if s["id"] not in felt or sid in have:
            rnd.random(), rnd.random()  # 接着做时保持后面的打乱顺序不变不重要，只求不报错
            continue
        p = felt[s["id"]]
        said = b8.own_words(s["said"])
        ctx = (["兄长大人：佳树刚才刷到什么了呀"] if s["src"] == "browse" else
               [f"兄长大人：[分享了{'一首歌' if s['what'] == '歌' else '一个' + s['what']}] {said}".rstrip()])
        c = {"局面": scene(s, p), "要说到的": p["points"]}
        card_text = render(c)
        w1 = write(ctx, card_text, 0.7)
        w2 = w1
        for t in (0.9, 1.0, 1.1):
            w2 = write(ctx, card_text, t)
            if w2 != w1:
                break
        material = omni.render(p, "一段", s["media"], 8)
        user = (f"{ctx[0].split('：', 1)[1]}\n<system_reminder>\n[你刚看完的{s['what']}] {material}\n"
                "回他的时候说你自己看完的感受，像平时聊天那样，不要把内容讲一遍。\n</system_reminder>")
        try:
            g = gemini_say(k, persona, user)
        except Exception as e:  # noqa: BLE001
            print("  Gemini 那句没写成", sid, type(e).__name__, str(e)[:120], flush=True)
            g = ""
        opts = [("w1", w1), ("w2", w2), ("gem", g)]
        rnd.shuffle(opts)
        key[sid] = [o[0] for o in opts]
        ms = sorted(p["moments"], key=lambda m: -m["strength"])[:3]
        items.append({
            "id": sid, "src": s["src"], "what": s["what"], "title": s["title"], "ctx": ctx, "card": card_text, "card_gold": render(c, False),
            "user": "聊天：\n" + "\n".join(ctx) + "\n\n材料：\n" + card_text, "format": "g", "writer": WRITER, "felt_by": p.get("by"),
            "mood": {"emotion": p["emotion"], "intensity": p["intensity"], "src": "content"},
            "felt": {"emotion": p["emotion"], "intensity": p["intensity"],
                     "moment": "　".join(f"{m['t']} {m['what']}：{m['feel']}" for m in ms),
                     "after": p.get("after", "") + (f"　｜听感：{p['sound']}" if p.get("sound") else ""), "facts": p.get("facts", "")},
            "cands": [o[1].replace("\n", " / ") for o in opts], "reply_then": re.sub(r"\n", " / ", s.get("reply_then", "")),
        })
        b8.save(b8.ITEMS, items)
        b8.save(b8.KEY, key)
        print(sid, f"{p['emotion']}{p['intensity']}", len(p["points"]), "条", [len(o[1]) for o in opts], "|", w1.replace("\n", " / ")[:90], flush=True)
    print(len(items), "条 →", b8.ITEMS)


if __name__ == "__main__":
    step = sys.argv[1]
    if step == "feel":
        asyncio.run(feel())
    elif step == "cand":
        cand()
    else:
        b8.page()
