r"""第 7 轮（写手多看聊天，2026-11-17，AGENT.md 第十节）：给训练样本换上长前文。

线上写手（rewrite.long_ctx 开着时）看 kaju_core\voice\longctx.py 拼的最后 ≤16 行 / ≤1500 字、带时间的聊天；
训练也得看一样的。这一步不调模型、不花钱：
  ctx   从原始来源重建长前文 → data\rounds_v4\r7\long_ctx.json（id → 行），并报每种来源成了几条、行数变化
        - 群聊（h6_group / group，id = g-<日>-<第几条>）：kaju_life 聊天记录，和 build_layered.group_samples 同样换名
          （“我” = 说这句的人、群友A… 先按原来 8 行窗口的顺序给，卡上写的群友X 不变；更早的人接着往后排）
        - 兄长私聊（h6_owner / owner，“我” = 兄长）、金句和旧人工样本（curated / curated_old，用称呼）：
          拿前文最后两行的字去聊天记录里找，找到了就往前取
        - 原作（novel）：在原文里找到前文最后一行，往前取段落（原作没有时间、没有“称呼：”，照原来一行一段）
        - lccc、B 站评论：没有更长的，照旧
用法（AstrBot 的 Python）：python -I -X utf8 scripts\prepare_r7.py ctx
"""
import argparse
import collections
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, r"D:\JiashuBot\bot_setup")
from kaju_core.voice import longctx  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
SELF = r"D:\JiashuBot\kaju_data\self"
LOG = os.path.join(SELF, "kaju_life", "log")
R6 = os.path.join(VT, "data", "rounds_v4", "r6")
R7 = os.path.join(VT, "data", "rounds_v4", "r7")
TXT_DIR = r"D:\Persona\Kaju\txt"
OWNER_QQ = None  # 兄长的号从称呼簿里认（称呼是“兄长大人”的那个），不写在代码里
MEDIA = re.compile(r"^(\[(图片|表情|视频|语音|文件[^\]]*|动画表情|小黄脸[^\]]*)\]\s*)+$")
COMMON = {"佳树", "兄长", "兄长大人", "学长", "学姐", "哥哥", "姐姐", "妹妹", "大家", "我"}


def jl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


# ---------------------------------------------------------------- 聊天记录
def logs():
    """[(日, 当天第几条, 记录)]，按日、按到达顺序。"""
    out = []
    for p in sorted(glob.glob(os.path.join(LOG, "*.jsonl"))):
        day = os.path.basename(p)[:-6]
        for i, r in enumerate(jl(p)):
            out.append((day, i, r))
    return out


def by_chat(recs):
    d = collections.defaultdict(list)
    for day, i, r in recs:
        d[str(r.get("c", ""))].append((day, i, r))
    return d


def scrub_names():
    names = json.load(open(os.path.join(SELF, "kaju_life", "names.json"), encoding="utf-8"))
    addr = json.load(open(os.path.join(SELF, "address_book", "addresses.json"), encoding="utf-8"))
    by_uid = {}
    for uid, n in (names.get("people") or {}).items():
        by_uid.setdefault(uid, set()).add(n)
    for uid, v in addr.items():
        if isinstance(v, dict) and v.get("address"):
            by_uid.setdefault(uid, set()).add(v["address"])
    groups = [g for g in (names.get("groups") or {}).values() if g and not g.isdigit()]
    return by_uid, groups, addr


def scrub(text, label_of, by_uid, groups):
    s = re.sub(r"https?://\S+", "[链接]", text)
    s = re.sub(r"\d{5,}", "[号码]", s)
    for g in groups:
        s = s.replace(g, "群里")
    pairs = [(n, uid) for uid, ns in by_uid.items() for n in ns if len(n) >= 2 and n not in COMMON]
    for n, uid in sorted(pairs, key=lambda p: -len(p[0])):
        if n in s:
            s = s.replace(n, label_of(uid))
    return s


LETTER = re.compile(r"群友[A-H]")


def group_long(chat_rs, j, ctx, by_uid, groups, window=8):
    """群聊长前文：原来那几行（ctx，卡就是照它写的）一字不动，只在前面补更早的行。
    原来那几行的说话人是谁 → 群友X 的字母从原来的行里认（names.json 后来长了，照 build_layered 重新换名字母会变）；
    更早的行里新出现的人接着用没用过的字母。对不上（去掉字母后原来的行和记录不一样）→ None。"""
    me = str(chat_rs[j][2].get("u"))
    lo = max(0, j - window)
    near = [q for q in chat_rs[lo:j] if str(q[2].get("x") or "").strip()][-len(ctx):] if ctx else []
    if len(near) != len(ctx):
        return None
    labels = {}
    for (_, _, qr), line in zip(near, ctx):
        who = line.split("：", 1)[0]
        uid = str(qr.get("u"))
        want = "我" if uid == me else ("佳树" if uid == "self" else None)
        if want and who != want:
            return None
        if not want:
            if not LETTER.fullmatch(who) or labels.get(uid, who) != who:
                return None
            labels[uid] = who

    def mention(uid):
        if uid == "self":
            return "佳树"
        if uid not in labels:
            used = set(labels.values())
            labels[uid] = next((f"群友{c}" for c in "ABCDEFGH" if f"群友{c}" not in used), "群友H")
        return labels[uid]

    def clean(t):
        t = scrub(t, mention, by_uid, groups)
        t = re.sub(r"\(\[号码\]\)", "", t)
        return re.sub(r"\s*\n\s*", " / ", t).strip()

    for (_, _, qr), line in zip(near, ctx):  # 原来的行对得上记录才用（字母不比）
        if LETTER.sub("X", norm(text_of(line))) != LETTER.sub("X", norm(clean(str(qr.get("x") or "")))[:len(norm(text_of(line)))]):
            return None
    items = []
    for qd, _, qr in chat_rs[max(0, j - 40):lo + 0]:
        qx = str(qr.get("x") or "").strip()
        if qx and (qd, _, qr) not in near:
            uid = str(qr.get("u"))
            items.append((qd, qr.get("t"), "我" if uid == me else mention(uid), clean(qx)[:120]))
    first = chat_rs.index(near[0]) if near else j
    for qd, _, qr in chat_rs[lo:first]:  # 窗口里、原来那几行之前的（空行被跳过的那种）
        qx = str(qr.get("x") or "").strip()
        if qx:
            uid = str(qr.get("u"))
            items.append((qd, qr.get("t"), "我" if uid == me else mention(uid), clean(qx)[:120]))
    for (qd, _, qr), line in zip(near, ctx):
        who, text = line.split("：", 1)
        items.append((qd, qr.get("t"), who, text))
    return longctx.format_lines(items)


def norm(s):
    return re.sub(r"[\s/…。，、！？!?,.「」“”\"『』~～—\-：:（）()]", "", str(s or ""))


def text_of(line):
    return line.split("：", 1)[1] if "：" in line else line


def find_in_logs(ctx, chats, need=2):
    """前文最后 need 行（够长的）在哪个聊天、第几条：拿字去对，前后顺序也要对。返回 (chat, 第几条) 或 None。"""
    keys = [norm(text_of(x))[:24] for x in ctx][-need:]
    keys = [k for k in keys if len(k) >= 4]
    if not keys:
        return None
    hits = []
    for chat, rs in chats.items():
        xs = [norm(r.get("x")) for _, _, r in rs]
        for j in range(len(xs) - 1, -1, -1):
            if keys[-1] and keys[-1][:16] in xs[j]:
                ok, k = True, j
                for key in reversed(keys[:-1]):  # 前面几行要在它前面不远处依次出现
                    k = next((m for m in range(k - 1, max(-1, k - 6), -1) if key[:16] in xs[m]), None)
                    if k is None:
                        ok = False
                        break
                if ok:
                    hits.append((chat, j))
    return hits[0] if len(hits) == 1 else (hits[0] if hits and len({h[0] for h in hits}) == 1 else None)


def chat_long(chat_rs, j, title_of):
    """chat_rs[j] 是前文最后一行；往前取（含它），用 title_of(uid, 昵称) 给称呼。"""
    items = []
    for d, _, r in chat_rs[max(0, j - 40):j + 1]:
        uid = str(r.get("u") or "")
        items.append((d, r.get("t"), title_of(uid, str(r.get("n") or "")), r.get("x")))
    return longctx.format_lines(items)


# ---------------------------------------------------------------- 原作
def norm_map(s):
    keep, idx = [], []
    for i, ch in enumerate(s):
        if ch.isspace() or ch in "…。，、！？!?,.「」“”\"『』~～—-":
            continue
        keep.append(ch)
        idx.append(i)
    return "".join(keep), idx


def load_txts():
    out = []
    for name in sorted(os.listdir(TXT_DIR)):
        if name.endswith(".txt"):
            raw = open(os.path.join(TXT_DIR, name), encoding="utf-8", errors="ignore").read()
            n, idx = norm_map(raw)
            out.append((name, raw, n, idx))
    return out


def novel_long(txts, ctx):
    """原文里找到前文最后一行，往前取段落：≤16 段、≤1500 字（和 longctx 一样的上限），一段一行。找不到 → None。"""
    for line in reversed(ctx[-2:]):
        k = norm_map(line)[0][:24]
        if len(k) < 6:
            continue
        for _, raw, n, idx in txts:
            p = n.find(k)
            if p < 0:
                continue
            end = idx[min(len(idx) - 1, p + len(norm_map(line)[0]) - 1)] + 1
            start = max(0, idx[p] - 4000)
            paras = [x.strip() for x in raw[start:end].split("\n") if x.strip()][1:]  # 第一段可能是半截
            if line is not ctx[-1]:  # 找到的是倒数第二行：把最后一行补上
                paras.append(ctx[-1])
            elif paras and ctx[-1].startswith(paras[-1]):  # 截在最后一个字上，句号掉了：用原来那行
                paras[-1] = ctx[-1]
            paras = [re.sub(r"\s+", " ", x)[:longctx.LINE_CHARS] for x in paras][-longctx.MAX_LINES:]
            while len(paras) > 1 and sum(len(x) + 4 for x in paras) > longctx.MAX_CHARS:
                paras = paras[1:]
            return paras
    return None


# ---------------------------------------------------------------- ctx
def cmd_ctx():
    rows = [("H", r) for r in jl(os.path.join(R6, "h_data", "stage1.jsonl"))] + \
           [("K", r) for r in jl(os.path.join(R6, "k_data", "stage2.jsonl"))]
    by_uid, groups, addr = scrub_names()
    recs = logs()
    chats = by_chat(recs)
    pos = {(d, i): (str(r.get("c", "")), k) for c, rs in chats.items() for k, (d, i, r) in enumerate(rs)}
    os.environ.setdefault("KAJU_DATA", os.path.dirname(SELF))
    from kaju_core import people
    owner = people.owner()  # 兄长本人：身份表说了算（和称呼簿 address_of 一样）
    assert owner, "身份表里没认出兄长"
    folks = json.load(open(os.path.join(SELF, "address_book", "people.json"), encoding="utf-8"))
    pchats = {c: rs for c, rs in chats.items() if c.startswith("p")}

    def addr_of(uid, name):
        """和线上称呼簿 address_of 一样：兄长 → 兄长大人；记了称呼用称呼；别的 = 名字 + 学长 / 学姐。"""
        if uid == "self":
            return "佳树"
        if uid == owner:
            return "兄长大人"
        v = addr.get(uid) or {}
        if v.get("address") and "兄长" not in v["address"]:
            return v["address"]
        p = folks.get(uid) or {}
        known = [re.sub(r"\s+", "", n) for n in (name, p.get("name"), v.get("nickname")) if n and re.sub(r"\s+", "", n) != uid]
        return (known[0] if known else "") + ("学姐" if p.get("sex") == "female" else "学长")

    def owner_title(uid, name):  # H 的兄长私聊：“我” = 兄长
        return "佳树" if uid == "self" else ("我" if uid == owner else (name or "身份不明"))

    txts = load_txts()
    out, stat, mism = {}, collections.Counter(), []
    before, after = collections.defaultdict(list), collections.defaultdict(list)
    for part, r in rows:
        src, ctx = r["src"], list(r.get("ctx") or [])
        kind = {"h6_group": "group", "group": "group", "h6_owner": "owner", "owner": "owner",
                "curated": "curated", "curated_old": "curated", "novel": "novel"}.get(src)
        new = None
        if kind == "group":
            m = re.match(r"g-(\d{4}-\d{2}-\d{2})-(\d+)", r["id"])
            if m and (m.group(1), int(m.group(2))) in pos:
                c, j = pos[(m.group(1), int(m.group(2)))]
                new = group_long(chats[c], j, ctx, by_uid, groups)
                if new is None:
                    mism.append((r["id"], ctx[-2:]))
        elif kind == "owner":
            hit = find_in_logs(ctx, pchats)
            if hit:
                new = chat_long(chats[hit[0]], hit[1], owner_title)
        elif kind == "curated":
            hit = find_in_logs(ctx, chats)
            if hit:
                new = chat_long(chats[hit[0]], hit[1], addr_of if hit[0].startswith("g") else
                                (lambda uid, name: "佳树" if uid == "self" else addr_of(uid, name)))
        elif kind == "novel":
            new = novel_long(txts, ctx)
        key = f"{part}:{src}"
        before[key].append(len(ctx))
        if new and len(new) >= len(ctx):
            out[f"{part}:{r['id']}"] = new
            stat[key + " 换了"] += 1
            after[key].append(len(new))
        else:
            stat[key + " 照旧"] += 1
            after[key].append(len(ctx))
    os.makedirs(R7, exist_ok=True)
    json.dump(out, open(os.path.join(R7, "long_ctx.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0  # noqa: E731
    print("来源 | 换了 | 照旧 | 行数中位 原来→现在")
    for key in sorted(before):
        print(f"{key} | {stat[key + ' 换了']} | {stat[key + ' 照旧']} | {med(before[key])} → {med(after[key])}")
    print(f"群聊重建和原来 6 行对不上：{len(mism)}")
    for x in mism[:5]:
        print("  ", x)
    print("→", os.path.join(R7, "long_ctx.json"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ctx"])
    a = ap.parse_args()
    {"ctx": cmd_ctx}[a.cmd]()


if __name__ == "__main__":
    main()
