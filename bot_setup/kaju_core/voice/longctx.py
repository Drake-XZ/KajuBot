"""写手看到的“长一点的聊天”（2026-11-17 第 7 轮：写手多看聊天，往 MaiBot 的回复器靠）。线上和训练共用这一个函数，格式定死。

原来写手只看到最后 3～4 行（私聊最多 4 行、约 200 字），更早的事只能靠卡转述——于是照念卡、也没法拿聊天核对卡（规划器错了就接着串）。
现在：最后 ≤ MAX_LINES 行、≤ MAX_CHARS 字（超了从前面截），每行“时间 称呼：话”，换了一天先插一行日期。
没有时间的来源（原作、lccc、B 站评论）就不写时间，只有“称呼：话”。

items：[(日期 "YYYY-MM-DD" 或 None, 时间 "HH:MM" 或 None, 称呼, 话)]，按先后排，最后一条一般是对方刚说的那句。
例：
  【11-15】
  21:30 兄长大人：佳树读完有什么感想呢？
  21:31 佳树：是的兄长大人，佳树也觉得……
  21:36 兄长大人：我觉得他们没有把世界缩的太小……
"""
import re

MAX_LINES = 12   # 11-17 起先定 16 行 / 1500 字，本机 4060（8GB）训 K 时长样本（约 1300 token）显存不够 → 12 行 / 1000 字
MAX_CHARS = 1000
LINE_CHARS = 160


def _clean(text: str) -> str:
    """一行话：换行变“ / ”；@人后面的号码、链接、本机文件路径去掉（聊天记录里是原样，写手不该看到号码和路径）。"""
    t = str(text or "")
    t = re.sub(r"\[File Attachment: name ([^,\]]+)[^\]]*\]", r"[文件 \1]", t)
    t = re.sub(r"(@[^\s(（]{1,20})[(（]\d{5,}[)）]", r"\1", t)
    t = re.sub(r"https?://\S+", "[链接]", t)
    t = re.sub(r"[A-Za-z]:\\[^\s，。]+", "[文件]", t)
    t = re.sub(r"\s*\n\s*", " / ", t).strip()
    return t[:LINE_CHARS + 160] if "[图片：" in t else t[:LINE_CHARS]  # 带图片描述的行放长一点


def format_lines(items: list[tuple], max_lines: int = MAX_LINES, max_chars: int = MAX_CHARS) -> list[str]:
    rows = [(d, t, str(w or "").strip() or "身份不明", _clean(x)) for d, t, w, x in items if _clean(x)]
    rows = rows[-max_lines:] if max_lines > 0 else rows
    while len(rows) > 1 and sum(len(w) + len(x) + 8 for _, _, w, x in rows) > max_chars:
        rows = rows[1:]
    out, last_day = [], None
    for d, t, w, x in rows:
        if d and d != last_day:
            out.append(f"【{d[5:] if len(d) >= 10 else d}】")
            last_day = d
        out.append(f"{t} {w}：{x}" if t else f"{w}：{x}")
    return out


def trim(lines: list[str], max_lines: int = MAX_LINES, max_chars: int = MAX_CHARS) -> list[str]:
    """已经拼好的长前文再截短（训练包用：上限改小了不用重建）：从前面去掉，去掉后开头那天的日期行补回来。
    日期行（【MM-DD】）不算行数。"""
    day = re.compile(r"^【[^】]+】$")
    rows, cur = [], None
    for x in lines:
        if day.match(x):
            cur = x
        else:
            rows.append((cur, x))
    rows = rows[-max_lines:] if max_lines > 0 else rows
    while len(rows) > 1 and sum(len(x) + 2 for _, x in rows) > max_chars:
        rows = rows[1:]
    out, last = [], None
    for d, x in rows:
        if d and d != last:
            out.append(d)
            last = d
        out.append(x)
    return out


def marked(r: dict, who_of, me: str = "佳树") -> str:
    """一条记录的话，带上 11-18 晚多记的几样：引用（“（回复X：…）”）、@她（“@佳树 ”）、图片内容（“[图片：…]”）。
    没有这几样就是原话。who_of(uid, name) 给被引用的人的称呼；引用她自己的写 me。"""
    x = str(r.get("x") or "")
    caps = [str(c) for c in (r.get("cap") or []) if c]
    if caps:
        for c in caps:
            if "[图片]" in x:
                x = x.replace("[图片]", f"[图片：{c[:120]}]", 1)
            else:
                x = (x + " " if x else "") + f"[图片：{c[:120]}]"
    if r.get("am") and "@佳树" not in x:
        x = "@佳树 " + x
    q = r.get("q")
    if isinstance(q, dict):
        qu = str(q.get("u") or "")
        qn = me if qu == "self" else (who_of(qu, str(q.get("n") or "")) or str(q.get("n") or "") or "身份不明")
        qx = str(q.get("x") or "").replace("\n", " ")[:40]
        x = f"（回复{qn}：{qx}）" + x if qx else f"（回复{qn}）" + x
    return x


def from_log(recs: list[dict], title_of, current: tuple | None = None, max_lines: int = MAX_LINES,
             max_chars: int = MAX_CHARS, me: str = "佳树", rich: bool = False) -> list[str]:
    """kaju_life 的聊天记录（{"d": 日期, "t": "HH:MM", "u": QQ 或 "self", "n": 昵称, "x": 话}）→ 长前文。
    title_of(uid, name) 给称呼（她自己写 me，回复器用“佳树(你)”）；current = (日期, 时间, 称呼, 话) 是对方刚说的那句（记录里还没有或对不上时补在最后）。
    rich：带上引用 / @她 / 图片内容（marked；回复器用，11-18 晚）。"""
    items = []
    for r in recs:
        uid = str(r.get("u") or "")
        who = me if uid == "self" else (title_of(uid, str(r.get("n") or "")) or str(r.get("n") or "") or "身份不明")
        items.append((r.get("d"), r.get("t"), who, marked(r, title_of, me) if rich else r.get("x")))
    if current:
        items.append(current)
    return format_lines(items, max_lines, max_chars)
