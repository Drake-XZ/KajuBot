"""聊天节奏：一句话一条消息，句尾不打句号。

大部分人在 QQ 上聊天几乎不打句号，一条消息就一句话，没说完就再发一条。
restyle() 把模型回复里的句号去掉、句号处改成换行；分段回复（regex [^\n]+）随后把每一行
作为单独一条消息发出去。引号里的句号、连续的"。。。"、代码块不动。

2026-11-03 句长校准：原作（《败犬女主太多了！》台版）里佳树一句话中位 11 字，她在 QQ 上一条消息却常是
20 多字、用逗号把两三句串成一长句。split_long() 把超过 20 字的消息在逗号处拆成两条（引号/书名号里不拆，
两边都要 ≥6 字），整条回复最多拆到 5 条。真模型对比（24 个真实时刻 ×3，盲评）：只拆不改内容，
"更像真人打 QQ" 38 胜 12 负，回应质量打平。
"""

import re

OPEN_Q = "“「『（("
CLOSE_Q = "”」』）)"
# 单独成行时应该并回上一行的东西（只剩标点/右括号之类）
ONLY_PUNCT = re.compile(r"^[\s，,、；;：:！!？?…~～—\-”」』）)\]】]*$")

SOFT = "！？!?"
SOFT_MIN_LEFT = 4
SOFT_MIN_RIGHT = 6

# 长消息在逗号处拆开
LONG_LINE = 20
SPLIT_SIDE = 6
SPLIT_MAX_LINES = 5
COMMAS = "，,"
OPEN_ANY = OPEN_Q + "《【["
CLOSE_ANY = CLOSE_Q + "》】]"

NOTE = (
    "\n\n【说话节奏】像真人发聊天消息：按内容自然分条，意思连贯的句子可以放在一条消息里；"
    "句尾不打句号（问号、感叹号、～、……照常用）。"
)


def _core_len(t: str) -> int:
    return len(re.sub(r"[\s\W_]", "", t))


def _split_line(line: str) -> list[str]:
    """在引号外的单个句号处断开，并去掉这些句号。"""
    pieces: list[str] = []
    buf: list[str] = []
    depth = 0
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if ch in OPEN_Q:
            depth += 1
        elif ch in CLOSE_Q:
            depth = max(0, depth - 1)
        elif ch == '"':
            depth = 0 if depth else 1
        if ch in SOFT and depth == 0:
            # 问号/感叹号：两边都够长才另起一条，"是的！""好吗？"这种短的不拆
            j = i
            while j < n and line[j] in SOFT + "～~":
                j += 1
            left = "".join(buf).strip()
            rest = line[j:].strip()
            buf.append(line[i:j])
            if _core_len(left) >= SOFT_MIN_LEFT and _core_len(rest.split("。")[0]) >= SOFT_MIN_RIGHT:
                pieces.append("".join(buf))
                buf = []
            i = j
            continue
        if ch == "。":
            j = i
            while j < n and line[j] == "。":
                j += 1
            if j - i >= 2 or depth > 0:
                # "。。。" 当省略号用 / 引号里的句号：原样保留
                buf.append(line[i:j])
            else:
                pieces.append("".join(buf))
                buf = []
            i = j
            continue
        buf.append(ch)
        i += 1
    pieces.append("".join(buf))

    out: list[str] = []
    for p in pieces:
        p = p.strip()
        if not p:
            continue
        if out and ONLY_PUNCT.match(p):
            out[-1] += p
        else:
            out.append(p)
    return out


def _merge(lines: list[str], max_lines: int) -> list[str]:
    while len(lines) > max(1, max_lines):
        i = min(range(len(lines) - 1), key=lambda k: len(lines[k]) + len(lines[k + 1]))
        lines[i : i + 2] = [lines[i] + " " + lines[i + 1]]
    return lines


def _comma_points(line: str) -> list[int]:
    """Positions of the commas that are not inside quotes, brackets or 《》."""
    points = []
    depth = 0
    for i, ch in enumerate(line):
        if ch in OPEN_ANY:
            depth += 1
        elif ch in CLOSE_ANY:
            depth = max(0, depth - 1)
        elif ch == '"':
            depth = 0 if depth else 1
        elif ch in COMMAS and depth == 0:
            points.append(i)
    return points


def _split_at(line: str, side: int) -> int | None:
    """The comma closest to the middle with at least `side` characters on both sides (None if none)."""
    total = _core_len(line)
    best = None
    for p in _comma_points(line):
        left = _core_len(line[:p])
        if left < side or total - left < side:
            continue
        if best is None or abs(left - total / 2) < abs(_core_len(line[:best]) - total / 2):
            best = p
    return best


def split_long(lines: list[str], max_lines: int = SPLIT_MAX_LINES,
               long_line: int = LONG_LINE, side: int = SPLIT_SIDE) -> list[str]:
    """Split messages longer than `long_line` characters at a comma, longest first, while fewer than `max_lines`."""
    lines = list(lines)
    while len(lines) < max_lines:
        best = None
        for idx, line in enumerate(lines):
            if _core_len(line) <= long_line:
                continue
            p = _split_at(line, side)
            if p is not None and (best is None or _core_len(line) > _core_len(lines[best[0]])):
                best = (idx, p)
        if best is None:
            break
        idx, p = best
        lines[idx : idx + 1] = [lines[idx][:p].rstrip(), lines[idx][p + 1 :].lstrip()]
    return lines


def restyle(text: str, max_lines: int = 4, split_max: int = SPLIT_MAX_LINES, long_line: int = LONG_LINE) -> str:
    """Remove sentence-final 。, put each sentence on its own line, and split long lines at a comma.

    Args:
        text: The model's reply.
        max_lines: Merge the shortest neighbouring lines until at most this many remain
            (lines the model already split itself are never merged below their count).
        split_max: Split lines longer than `long_line` at a comma until the reply has this many
            lines (0 = never split at commas).
        long_line: How long (characters, punctuation not counted) a line must be before it is split.

    Returns:
        The restyled reply (unchanged when there is nothing to do or it contains code).
    """
    if not text or "```" in text:
        return text
    ends = bool(re.search(r"[。！？!?]", text))
    if not ends and split_max <= 0:
        return text
    lead = text[: len(text) - len(text.lstrip())]
    raw_lines = [raw.strip() for raw in text.strip().split("\n") if raw.strip()]
    lines: list[str] = []
    for raw in raw_lines:
        lines.extend(_split_line(raw) if ends else [raw])
    if not lines:
        return text
    # 原本就多于上限的行数不去合并（那是模型自己分的）
    lines = _merge(lines, max(max_lines, len(raw_lines)))
    if split_max > 0 and long_line > 0:
        lines = split_long(lines, split_max, long_line)
    if not ends and lines == raw_lines:
        return text
    return lead + "\n".join(lines)
