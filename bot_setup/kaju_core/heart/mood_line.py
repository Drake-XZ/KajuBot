"""给写手的“心情”那一行（决定 19，2026-11-12）：线上和训练共用这一个函数，格式定死，改了就得大规模重训。

输入是 HeartMind.mood_snapshot() 的结构（原作补标的 snapshot 也是这个结构）：
  {"mood": {joy, energy, stress, warm: 0~1}, "recent": [{emo, i, src, ...}], "threads": [{emo, c, kind, ...}]}
输出例：
  心情：开心6 精神6 紧绷1 亲近5｜刚才：吃醋2 开心1 感动2(看的东西)｜心事：委屈1.4
规则：
  - 底色四个数：joy→开心、energy→精神、stress→紧绷、warm→亲近，0~1 乘 9 四舍五入、夹在 0~9。
  - 刚才：最近的感受按先后排，最多 6 个，“标签+强度”，强度 0 的不写；来自看的内容（src=content）的后面加“(看的东西)”。没有就不写这一段。
  - 心事：还挂着的心事按原顺序，“标签+分量（一位小数）”，分量 <0.1 的不写；来自内容的同样加“(看的东西)”。没有就不写这一段。
  - 全是读数：不写原因、不写她该怎么表现。
  - 合并重复（2026-11-16 晚兄长定“合并重复项”，线上和训练一起改）：读小说那天每一段都记成一件事，
    整行变成“难过2(看的东西) 难过2(看的东西) 难过2(看的东西)…”。现在：
      刚才：**挨着的**一样的项合成一个、后面写“×次数”（“难过2×6(看的东西)”），不挨着的照旧分开，先后顺序不变；
      心事：同一种感受、同一来路的合成一个，分量取最重的、后面写“×个数”（“难过2.4×2(看的东西)”），按第一次出现的顺序。
    例：心情：开心0 精神3 紧绷9 亲近8｜刚才：担心2×2(看的东西) 害怕3(看的东西) 难过3(看的东西) 害怕3(看的东西) 难过2(看的东西)｜心事：感动1.5×2(看的东西) 难过3.0×3(看的东西) 担心2.9(看的东西) 害怕3.0(看的东西)
"""

import re

DIM_NAMES = (("joy", "开心"), ("energy", "精神"), ("stress", "紧绷"), ("warm", "亲近"))
CONTENT_MARK = "(看的东西)"
MAX_RECENT = 6


def _num(v) -> int:
    try:
        return max(0, min(9, int(round(float(v) * 9))))
    except (TypeError, ValueError):
        return 0


def mood_line(snap: dict | None) -> str:
    """snapshot → “心情：……”一行；没有 snapshot 返回空串（写手照常写）。"""
    if not snap or not isinstance(snap.get("mood"), dict):
        return ""
    m = snap["mood"]
    parts = [" ".join(f"{name}{_num(m.get(key, 0))}" for key, name in DIM_NAMES)]
    runs = []  # 刚才：[标签, 强度, 来路记号, 次数]，挨着的一样的合成一个
    for e in (snap.get("recent") or [])[-MAX_RECENT:]:
        i = int(e.get("i", 0) or 0)
        emo = str(e.get("emo", "")).strip()
        if emo and i > 0:
            mark = CONTENT_MARK if e.get("src") == "content" else ""
            if runs and runs[-1][:3] == [emo, i, mark]:
                runs[-1][3] += 1
            else:
                runs.append([emo, i, mark, 1])
    if runs:
        parts.append("刚才：" + " ".join(f"{emo}{i}" + (f"×{n}" if n > 1 else "") + mark for emo, i, mark, n in runs))
    groups = {}  # 心事：同一种感受、同一来路的合成一个，分量取最重的
    for t in snap.get("threads") or []:
        c = float(t.get("c", 0) or 0)
        emo = str(t.get("emo", "")).strip()
        if emo and c >= 0.1:
            key = (emo, CONTENT_MARK if t.get("kind") == "content" else "")
            g = groups.setdefault(key, [0.0, 0])
            g[0], g[1] = max(g[0], c), g[1] + 1
    if groups:
        parts.append("心事：" + " ".join(f"{emo}{c:.1f}" + (f"×{n}" if n > 1 else "") + mark
                                       for (emo, mark), (c, n) in groups.items()))
    return "心情：" + "｜".join(parts)


_TOKEN = re.compile(r"^(\D+?)(\d+(?:\.\d+)?)(?:×(\d+))?(\(看的东西\))?$")


def normalize(text: str) -> str:
    """把一段卡里旧格式的心情行（没合并的）改成现在的写法；别的行原样不动。11-16 合并以前存下的卡（训练数据、线上记录）都用它转。
    旧行里本来就有每一项的先后、强度 / 分量和来路，按同样的规则合并，结果和对同一份读数调 mood_line 一样。"""
    if not text or "心情：" not in text:
        return text
    out = []
    for line in str(text).split("\n"):
        if line.startswith("心情："):
            line = _normalize_line(line)
        out.append(line)
    return "\n".join(out)


def _normalize_line(line: str) -> str:
    segs = line[len("心情："):].split("｜")
    res = [segs[0]]
    for seg in segs[1:]:
        head, _, body = seg.partition("：")
        toks = []
        for t in body.split():
            m = _TOKEN.match(t)
            if not m:
                return line  # 认不出的格式不动
            toks.append((m.group(1), m.group(2), int(m.group(3) or 1), m.group(4) or ""))
        if head == "刚才":
            runs = []
            for emo, v, n, mark in toks:
                if runs and runs[-1][:2] == [emo, v] and runs[-1][3] == mark:
                    runs[-1][2] += n
                else:
                    runs.append([emo, v, n, mark])
            res.append("刚才：" + " ".join(f"{e}{v}" + (f"×{n}" if n > 1 else "") + mk for e, v, n, mk in runs))
        elif head == "心事":
            groups = {}
            for emo, v, n, mark in toks:
                g = groups.setdefault((emo, mark), [0.0, 0])
                g[0], g[1] = max(g[0], float(v)), g[1] + n
            res.append("心事：" + " ".join(f"{e}{c:.1f}" + (f"×{n}" if n > 1 else "") + mk for (e, mk), (c, n) in groups.items()))
        else:
            res.append(seg)
    return "心情：" + "｜".join(res)
