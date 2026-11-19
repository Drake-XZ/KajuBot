r"""第八批（看完感想，第三版页面 NyHdjjr7nPXyxLAT8SAXtd）→ K 层训练数据 + 考试题 + 偏好对（2026-11-12 第二版）。

旧版（DeepSeek 判卡、旧格式）留在 make_gold8_v1.py。这一版按兄长标完后的分析改（决定记录"第八批标完了"一节）：
  - 25 条能用：去掉"这条不要"、空的，和 r8-30（写的是给 Claude 的话，不是回复）。
  - 卡全部按他的最终版重新抽：19 条他是拿 Gemini 直接写的那句当底改的，原卡和他的字对不上。
    抽卡用 Gemini（和线上看完东西的来源一致），给它那条视频的感受 + 他的最终版。
    "要说到的"写成"事实（感受词）"，不写成她的句子——写手以前就是把"那下佳树…"照念。
  - 不带"长短"、不带心情（决定 16）。
  - 每 3 条留 1 条做考试题；训练的每条写 1 份（原想 2 份，见 COPIES 的注释）。
  - 偏好对：chosen = 他的最终版；rejected = 写手两句（念卡）+ Gemini 原句（"我"、套话尾巴、编的日常、说过头）。
    两边长短方向相反（写手比他短、Gemini 比他长），合起来不让模型靠"变短 / 变长"赢——上次 DPO 就是靠变短过的。

输出都在 data\gold8\（不碰训练包；造训练包那一步再并进去）：
  train.jsonl  eval.jsonl  prefs.jsonl  cards.json（抽出来的卡，已有的不重抽、不重花钱）
用法（AstrBot venv）：python -I make_gold8.py
撤销：删掉 data\gold8。
"""
import glob
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("KAJU_DATA", r"D:\JiashuBot\kaju_data")
sys.path.insert(0, r"D:\JiashuBot\bot_setup")
from kaju_core.senses import omni  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import train_keys  # noqa: E402  (训练专用的 Gemini 接口，见 train_keys.py)

VT = r"D:\JiashuBot\voice_train"
DATA = os.path.join(VT, "data")
ITEMS = os.path.join(DATA, "review8_items.json")
KEY = os.path.join(DATA, "review8_key.json")
FELT = os.path.join(DATA, "review8_felt_g.json")
LABELS = os.path.join(DATA, "review8_labels_v2", "labels")
OUT = os.path.join(DATA, "gold8")
NOT_REPLY = {"r8-30_browse"}  # 他写的是要求（"她应该认出来那个女孩是她自己…"），不是她的回复
COPIES = 1  # 原来想写 2 份；测出训练包里写 3 份的人工样本 8b-A 七成一字不差背出来，改 1 份

EXTRACT = """你在给一个回复整理"要点卡"。下面是佳树看完一个视频（或歌、动图）后的感受记录，和她最后真正说出口的回复。
把回复里**真正说到的**每件事列出来，一条一件：
- 写成"事实（感受词）"，例如"巨兽被画成生姜（好笑）""全员合唱的大爆发（心里发酸）""歌里讲人造的琥珀不是真宝物（被打动）"。
- 事实 6 到 20 个字，用平常的词；感受词 1 到 5 个字。不写主语，不写"佳树""我"，不要写成她要说的句子。
- 回复里讲的是主题、自己的理解、歌手或作品名，也照样列一条。
- 回复没说到的不要列（感受记录里有也不要）；开头的"看完了""刚才刷到"、结尾的问句不用列。
- 条数就是回复说到的件数，1 到 6 条。
只回 JSON：{"points": ["…", "…"]}"""


def lines(t):
    """页面上几条之间用 / 隔开（和线上分条发一样）→ 换行；句号断开；去掉空行。"""
    t = re.sub(r"\s*[/／]\s*", "\n", str(t or "").strip())
    t = t.replace("兄大人", "兄长大人").replace("兄长长大人", "兄长大人")
    t = re.sub(r"。+(?=.)", "\n", t).replace("。", "")
    return "\n".join(x.strip() for x in t.split("\n") if x.strip())


def load(p, d):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else d


def felt_text(f):
    if not f:
        return "（没有感受记录）"
    out = []
    for k, name in (("facts", "内容"), ("sound", "听感"), ("arc", "过程"), ("after", "看完"), ("about", "讲的是")):
        if f.get(k):
            out.append(f"{name}：{f[k]}")
    for m in f.get("moments") or []:
        out.append(f"{m.get('t', '')} {m.get('what', '')} → {m.get('feel', '')}")
    return "\n".join(out)


def gemini(k, system, user):
    body = {"model": k["model"], "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    req = urllib.request.Request(k["base_url"].rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "python-client",
                                  "Authorization": "Bearer " + k["api_key"]})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.load(r)
    return (d["choices"][0]["message"]["content"] or "").strip(), d.get("usage") or {}


def extract(k, f, target):
    for _ in range(3):
        try:
            text, usage = gemini(k, EXTRACT, f"感受记录：\n{felt_text(f)}\n\n她的回复：\n{target}")
            j = json.loads(text[text.find("{"):text.rfind("}") + 1])
            pts = [str(x).strip("。；; ") for x in j.get("points") or [] if str(x).strip()][:6]
            if pts:
                return pts, usage
        except Exception as e:  # noqa: BLE001
            print("  重试", type(e).__name__, str(e)[:120])
    return [], {}


def card_of(it, pts):
    head = it["card_gold"].split("\n要说到的：")[0]
    return head + "\n要说到的：" + "；".join(pts)


def main():
    items = {x["id"]: x for x in load(ITEMS, [])}
    key = load(KEY, {})
    felt = load(FELT, {})
    labs = {}
    for p in glob.glob(os.path.join(LABELS, "*.json")):
        d = json.load(open(p, encoding="utf-8"))
        labs[os.path.splitext(os.path.basename(p))[0]] = d.get("data", d)
    use = []
    for i in sorted(labs):
        lb = labs[i]
        if lb.get("skip") or i in NOT_REPLY or not lines(lb.get("text")):
            continue
        use.append((items[i], lb, lines(lb["text"])))
    print(f"标注 {len(labs)} 条，能用 {len(use)} 条")

    os.makedirs(OUT, exist_ok=True)
    cpath = os.path.join(OUT, "cards.json")
    cards = load(cpath, {})
    k = train_keys.gemini()
    assert k, "accounts\\gemini_keys.json 一个 key 都没填"
    todo = [(it, t) for it, _, t in use if cards.get(it["id"], {}).get("target") != t]
    tok = {"in": 0, "out": 0}

    def one(a):
        it, t = a
        pts, u = extract(k, felt.get(it["id"].removeprefix("r8-")), t)
        tok["in"] += u.get("prompt_tokens", 0)
        tok["out"] += u.get("completion_tokens", 0)
        return it["id"], t, pts

    with ThreadPoolExecutor(4) as ex:
        for i, t, pts in ex.map(one, todo):
            if pts:
                cards[i] = {"target": t, "points": pts}
            else:
                print("FAIL 没抽出卡", i)
    json.dump(cards, open(cpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if todo:
        print(f"抽卡 {len(todo)} 次，输入 {tok['in']} 输出 {tok['out']} tokens")

    train, exam, prefs = [], [], []
    n = 0
    for it, lb, t in use:
        c = cards.get(it["id"])
        if not c:
            continue
        card = card_of(it, c["points"])
        gid = "gold-" + it["id"]
        row = {"src": "curated", "id": gid, "ctx": it["ctx"], "card": card, "target": t, "group": gid,
               "scene": "看完感想"}
        held = n % 3 == 2
        n += 1
        if held:
            exam.append(row)
            continue
        for j in range(COPIES):
            train.append(dict(row, id=f"{gid}-{j}"))
        for who, cand in zip(key[it["id"]], it["cands"]):
            r = lines(cand)
            if r and r != t:
                prefs.append({"id": f"{gid}-{who}", "src": "r8", "ctx": it["ctx"], "card": card, "chosen": t,
                              "rejected": r, "rej_from": "gemini" if who == "gem" else "writer"})

    for name, data in (("train", train), ("eval", exam), ("prefs", prefs)):
        with open(os.path.join(OUT, name + ".jsonl"), "w", encoding="utf-8") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    L = lambda s: len(s.replace("\n", ""))  # noqa: E731
    for src in ("writer", "gemini"):
        ps = [p for p in prefs if p["rej_from"] == src]
        if ps:
            print(f"偏好对·对{src} {len(ps)} 对：chosen 平均 {sum(L(p['chosen']) for p in ps) / len(ps):.0f} 字，"
                  f"rejected 平均 {sum(L(p['rejected']) for p in ps) / len(ps):.0f} 字")
    print(f"训练 {len(train)} 行（{len(train) // COPIES} 条 × {COPIES}），考试 {len(exam)} 条，偏好对 {len(prefs)} 对 → {OUT}")


if __name__ == "__main__":
    main()
