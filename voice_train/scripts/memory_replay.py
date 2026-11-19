r"""记忆检索回放（2026-11-18 兄长：“把最后一项也做了吧”；照 dsh-soul 的 bench/replay：拿真实记录量检索，不是只看测试全绿）。

不调模型、不花钱。读：
  - kaju_data\self\kaju_style\draft_inputs\*.jsonl：每一轮主模型收到的完整材料（memorix 检索结果、铭记、触景生情、还没结果的事都在里面）
  - kaju_data\self\kaju_life\log\*.jsonl：她那一轮真的说了什么（同一个聊天里，对方那句之后 5 分钟内她发的话）
对每一轮、每一样给她看的记忆，看她的回复里有没有用上——和线上 memory_weight 记“用上一次”同一个算法
（weigh.used_terms：回复里出现了这条记忆特有的词，对方这次自己说过的不算，很多条记忆都有的常见词不算）。

  python -I -X utf8 voice_train\scripts\memory_replay.py [--days 7] [--top 12]
输出：每一样来源给了多少条、用上多少条、每轮平均给多少条；哪几条给得最多却一次没用上（多半是该作废 / 该褪色的）。
结果存 voice_train\data\rounds_v4\memory_replay\report.json。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import zoneinfo
from collections import Counter, defaultdict

sys.path.insert(0, r"D:\JiashuBot\bot_setup")
os.environ.setdefault("KAJU_DATA", r"D:\JiashuBot\kaju_data")
from kaju_core.memory import rater, weigh  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
DRAFTS = r"D:\JiashuBot\kaju_data\self\kaju_style\draft_inputs"
LIFE = r"D:\JiashuBot\kaju_data\self\kaju_life\log"
OUT = r"D:\JiashuBot\voice_train\data\rounds_v4\memory_replay"
TZ = zoneinfo.ZoneInfo("Asia/Shanghai")
HEAD = re.compile(r"^\[发言人：([^，,\]]*)[，,]\s*QQ\s*(\d+)\]\s*")


def whole(s):
    return "\n".join([s.get("system_prompt") or ""] + [e if isinstance(e, str) else json.dumps(e, ensure_ascii=False)
                                                       for e in (s.get("extra") or [])])


def section(text, mark, stop=r"\n\n【|\Z"):
    i = text.find(mark)
    if i < 0:
        return ""
    m = re.search(stop, text[i + len(mark):])
    return text[i: i + len(mark) + (m.start() if m else len(text))]


def offered(s):
    """这一轮给她看的记忆：[(来源, 文本)]。"""
    t = whole(s)
    out = []
    mx = section(t, weigh.MEMORIX_MARKER, r"\n\n(?=【(?!长期记忆|人物画像|Memorix))|\Z")
    for h in weigh.parse_hits(mx):
        out.append(("memorix 检索", h["content"]))
    for line in section(mx, "待确认事实线索").splitlines()[1:]:
        if line.strip().startswith("- ") and len(line.strip()) > 3:
            out.append(("memorix 人物线索", line.strip()[2:]))
    for mark, src in (("【铭记在心】", "铭记"), ("【还没结果的事】", "还没结果的事"), ("【珍藏的文件】", "珍藏")):
        for line in section(t, mark).splitlines()[1:]:
            if line.strip().startswith("- "):
                out.append((src, line.strip()[2:]))
    cue = section(t, "【触景生情】")
    if cue:
        out.append(("触景生情", cue))
    return out


def life_lines(days):
    rows = []
    for f in sorted(os.listdir(LIFE)):
        if not f.endswith(".jsonl") or f[:-6] < days:
            continue
        for r in rater.read_log_lines(os.path.join(LIFE, f)):
            try:
                rows.append({**r, "ts": rater.line_time(f[:-6], r.get("t", "00:00"), 5, TZ)})
            except (ValueError, TypeError):
                continue
    return rows


def her_reply(rows, qq, said, t):
    """对方那句（时间最近、同一个人）之后，同一个聊天里 5 分钟内她发的话。"""
    cand = [i for i, r in enumerate(rows) if str(r.get("u")) == qq and abs(r["ts"] - t) <= 180]
    if not cand:
        return "", ""
    key = said[:8]
    cand.sort(key=lambda i: (key not in str(rows[i].get("x", "")), abs(rows[i]["ts"] - t)))
    i = cand[0]
    chat, t0 = rows[i].get("c"), rows[i]["ts"]
    out = [str(r.get("x", "")) for r in rows[i + 1:] if r.get("c") == chat and r.get("u") == "self" and r["ts"] - t0 <= 300]
    return "\n".join(out), str(chat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    since = (dt.datetime.now(TZ) - dt.timedelta(days=a.days)).strftime("%Y-%m-%d")
    rows = life_lines(since)
    turns = []
    for f in sorted(os.listdir(DRAFTS)):
        if not f.endswith(".jsonl") or f[:-6] < since:
            continue
        for line in open(os.path.join(DRAFTS, f), encoding="utf-8"):
            try:
                s = json.loads(line)
            except ValueError:
                continue
            m = HEAD.match(s.get("prompt") or "")
            if not m:
                continue
            said = (s.get("prompt") or "")[m.end():]
            reply, chat = her_reply(rows, m.group(2), said, float(s["t"]))
            if reply:
                turns.append({"t": s["t"], "chat": chat, "said": said, "reply": reply, "items": offered(s),
                              "ctx": " ".join(str(c.get("text", ""))[:200] for c in (s.get("contexts") or [])[-4:])})
    if not turns:
        sys.exit("这几天没有对得上的轮次")
    docs = {txt: weigh.keywords(txt) for tr in turns for _src, txt in tr["items"]}
    common = weigh.common_terms(weigh.doc_freq(list(docs.values())), len(docs))
    per = defaultdict(lambda: {"给了": 0, "用上": 0})
    seen, used_n = Counter(), Counter()
    any_used = 0
    for tr in turns:
        reply_kw = weigh.keywords(tr["reply"])
        echo_kw = weigh.keywords(tr["said"] + " " + tr["ctx"])
        hit = False
        for src, txt in tr["items"]:
            u = weigh.used_terms(docs[txt], reply_kw, echo_kw, common)
            per[src]["给了"] += 1
            seen[(src, txt)] += 1
            if u:
                per[src]["用上"] += 1
                used_n[(src, txt)] += 1
                hit = True
        any_used += hit
    print(f"最近 {a.days} 天：{len(turns)} 轮对得上她的回复；每轮平均给 {sum(len(t['items']) for t in turns) / len(turns):.1f} 条记忆；"
          f"至少用上一条的轮次 {any_used}/{len(turns)}")
    print(f"{'来源':<14}{'给了':>6}{'用上':>6}{'用上率':>8}")
    for src, v in sorted(per.items(), key=lambda x: -x[1]["给了"]):
        print(f"{src:<14}{v['给了']:>6}{v['用上']:>6}{v['用上'] / max(1, v['给了']):>8.0%}")
    never = [(n, src, txt) for (src, txt), n in seen.most_common() if not used_n[(src, txt)]][: a.top]
    print(f"\n给得最多、一次没用上的 {len(never)} 条（多半该作废、该褪色，或者本来就是背景）：")
    for n, src, txt in never:
        print(f"  {n:>3} 次  [{src}] {txt[:60]}")
    os.makedirs(OUT, exist_ok=True)
    json.dump({"days": a.days, "turns": len(turns), "any_used": any_used, "per_source": per,
               "never_used": [{"n": n, "src": s, "text": t} for n, s, t in never]},
              open(os.path.join(OUT, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
