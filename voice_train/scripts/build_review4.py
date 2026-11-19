"""第四轮标注：她开口先复述/点评对方（"555学长给佳树竖大拇指""学姐这是…呀"）的真实回复，兄长大人写该怎么说。

2026-11-08 兄长大人选了"靠训练数据改，不加规则"：这批答案进 K 层（佳树口吻）训练数据，
卡片按线上方式从她当时的回复抽（里面带着复述），答案是不复述的说法——教写手这种时候直接给反应。
一部分留作每晚考试题。

挑法（只在这里离线挑，线上不用）：kaju_life 聊天记录里她的回复，第一行像
  - "称呼(这是/真的/又…)给/帮/说…" 复述对方刚做的事、
  - kaju_style respond.is_commentary 的点评开头、
  - 或者紧跟在对方的图片/表情/红包后面且开头是上面两种之一；
外加"66666"那种原话照念。图片描述能从对话历史里找到的补上。

用法：python -I build_review4.py → data/review4_items.json
"""
import glob
import json
import os
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = r"C:\Users\18525\.astrbot_launcher\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
PD = os.path.join(CORE, "data", "plugin_data")
OWNER = "111111111"
sys.path.insert(0, r"D:\JiashuBot\bot_setup\kaju_core\voice")
import respond  # noqa: E402

WHO = r"(?:[^\s，,。！!？?～~、…]{0,8}?(?:大人|学姐|学长|前辈|老师)|兄长)"
RESTATE = re.compile(r"^(?:(?:呜哇|哇|诶|欸|嘿嘿|哈哈)[，,！!～~\s]*)?" + WHO +
                     r"(?:这是|这下|真的|真|居然|又|也|还|都|这么){0,2}(?:给|帮|对|向|冲|朝|替|在|把|发|说)")
MEDIA = re.compile(r"^\[(图片|动画表情|表情[^\]]*|视频|QQ红包\].*)")
ATTACH = re.compile(r"\[File Attachment: name ([^,\]]*)[^\]]*\]")
SKIP_DAYS = {"2026-10-28"}  # 那天还在调接入，回复是"看不清图"之类的旧问题


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def titles():
    people = json.load(open(os.path.join(PD, "astrbot_plugin_address_book", "people.json"), encoding="utf-8"))
    book = json.load(open(os.path.join(PD, "astrbot_plugin_address_book", "addresses.json"), encoding="utf-8"))

    def title(uid, name):
        if uid == OWNER:
            return "兄长大人"
        if uid in book and book[uid].get("address"):
            return book[uid]["address"]
        sex = (people.get(uid) or {}).get("sex")
        return f"{name}{'学姐' if sex == 'female' else '学长'}"
    return title


def captions():
    """她回复文本 → 那一轮里看到的图片描述（对话历史里还留着的）。"""
    db = sqlite3.connect(os.path.join(CORE, "data", "data_v4.db"))
    out = {}
    for (content,) in db.execute("select content from conversations"):
        hist = json.loads(content or "[]")
        caps = []
        for m in hist:
            parts = m.get("content") if isinstance(m.get("content"), list) else [{"type": "text", "text": m.get("content") or ""}]
            texts = [p.get("text") or "" for p in parts if p.get("type") == "text"]
            if m.get("role") == "user":
                caps = [re.sub(r"^\[Image in this message: |\]$", "", t) for t in texts if t.startswith("[Image in this message:")]
            elif m.get("role") == "assistant" and caps:
                out[match_key(" ".join(texts))] = caps
    return out


def match_key(text):
    """历史里存的那份分过行、标点也可能不同：去掉空白、标点、表情标签再比前 16 个字。"""
    return re.sub(r"\s|&&[^&]*&&|[，,。！!？?～~、…]", "", text or "")[:16]


def short_cap(c):
    if "动起来时" in c:  # 动图：只留动作那段
        c = "动图表情包：" + c.split("动起来时", 1)[1].lstrip("，,")
    return c[:80] + ("…" if len(c) > 80 else "")


def main():
    title = titles()
    caps = captions()
    items = []
    for p in sorted(glob.glob(os.path.join(PD, "astrbot_plugin_kaju_life", "log", "*.jsonl"))):
        day = os.path.basename(p)[:-6]
        if day in SKIP_DAYS:
            continue
        rs = load(p)
        for i, r in enumerate(rs):
            if r.get("u") != "self":
                continue
            c = r["c"]
            prev = [q for q in rs[:i] if q["c"] == c][-6:]
            if not prev or prev[-1].get("u") == "self":
                continue
            first = next((l.strip() for l in r["x"].split("\n") if l.strip() and not l.startswith("&&")), "")
            last = prev[-1]["x"].strip()
            why = []
            if RESTATE.match(first):
                why.append("复述")
            if respond.is_commentary(first):
                why.append("点评")
            if re.sub(r"\s", "", first) == re.sub(r"\s", "", last) and len(last) >= 2 and not re.search(r"晚安|明天见|早", last):
                why.append("照念")
            if not why:
                continue
            group = c.startswith("g")
            cap = caps.get(match_key(r["x"]), [])
            disp, train = [], []
            for q in prev:
                uid = str(q.get("u"))
                x = ATTACH.sub("[图片]", str(q.get("x") or "")).strip()
                if uid == "self":
                    who, t = "佳树", "佳树"
                else:
                    who = ("你" if uid == OWNER else q.get("n") or "群友")
                    t = title(uid, q.get("n") or "")
                if q is prev[-1] and cap and MEDIA.match(x):
                    x = f"[图片：{short_cap(cap[0])}]"
                disp.append({"who": who, "x": x[:200]})
                train.append(f"{t}：{x.replace(chr(10), ' / ')[:160]}")
            to_uid = str(prev[-1].get("u"))
            items.append({
                "id": f"r4-{day}-{r['t'].replace(':', '')}-{len(items)}",
                "when": f"{day[5:]} {r['t']}",
                "where": "妖妖群" if group else "私聊",
                "kind": "群聊" if group else "私聊",
                "to": title(to_uid, prev[-1].get("n") or ""),
                "why": why,
                "ctx": disp,
                "train_ctx": train,
                "reply": "\n".join(l for l in r["x"].split("\n") if l.strip() and not l.startswith("&&")),
            })
    out = os.path.join(ROOT, "data", "review4_items.json")
    json.dump(items, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 标注页：只放页面要显示的字段（训练用的上下文留在 items 文件里）
    show = [{k: it[k] for k in ("id", "when", "where", "to", "why", "ctx", "reply")} for it in items]
    tpl = open(os.path.join(ROOT, "review", "review4.template.html"), encoding="utf-8").read()
    page = tpl.replace("/*ITEMS*/", json.dumps(show, ensure_ascii=False).replace("</", "<\\/"))
    open(os.path.join(ROOT, "review", "review4.html"), "w", encoding="utf-8").write(page)
    print(f"{len(items)} 条 → {out}；标注页 → review\\review4.html")
    for it in items:
        print(it["when"], it["where"], it["why"], it["reply"].split("\n")[0][:40])


if __name__ == "__main__":
    main()
