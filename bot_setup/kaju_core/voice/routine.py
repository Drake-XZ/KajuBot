"""发之前查套路（2026-11-10，参考 fishtalk 的 check：github.com/Nozzi2455/fishtalk lib/fishrules.js）。

写手写好、核对也过了的那句，发之前再看三样：
  same    和她在这个会话最近 50 句里的某一句太像（整条，或其中一行）
  opener  开头和前两次回复一模一样（连着三次）
  soft    书面套路命中两条以上（"不是…而是""本质上""总之"开头……）
撞了怎么办由 mind.py 定：rewrite.routine = "log" 只记不拦（默认）；"on" 拿同一张卡让写手再写一遍、两遍里挑撞得少的发。
这里只判断，不改字、不出提示词。

不算套路的：称呼、自称、语气词（"兄长大人""佳树""呢""哦""诶嘿嘿"）。2026-11-01 把它们当套路提醒之后她变得干巴巴，
这些是她的味道。所以比较之前先把称呼和自称去掉，太短的话（去掉后不到 6 个字，比如"晚安"）不比。
考试里的两把量尺（voice_train\\scripts\\routine_stats.py）用的是同一份判断。
"""

import glob
import json
import os
import re

MEME_TAG = re.compile(r"&&[^&\n]*&&")
# 比较整句时不算的东西：称呼、自称、标点（原来在 variety.py，2026-11-13 那几条已关的说话规则删掉时挪过来）
FILLER = re.compile(r"兄长大人|佳树|女王大人|[^\s，,！!？?～~]{0,8}学[长姐]|[\W_]")


def text_of(content) -> str:
    """Plain text of a history message content (str or OpenAI-style part list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def clean_reply(text: str) -> str:
    """Drop meme tags like &&happy&& and surrounding whitespace."""
    return MEME_TAG.sub("", text or "").strip()


WINDOW = 50       # 和最近多少句比
SAME = 0.8         # 两字片段重合到多少算"太像"（fishtalk 的默认值）
MIN_CHARS = 6      # 去掉称呼、标点后不到这么多字的不比
OPENER_CHARS = 3   # 开头看几个字（去掉称呼、自称之后）
SOFT_MIN = 2       # 书面套路命中几条才算

# fishtalk 的软信号里适用于她的几条（鱼自称、"主人"那些不适用）
SOFT = {
    "不是…而是": re.compile(r"不是[^，。！？\n]{0,20}(?:而是|，是)"),
    "本质上": re.compile(r"这本身|本质上|归根结底|说到底"),
    "与其…不如": re.compile(r"与其[^。！？\n]{0,20}不如|看似[^。！？\n]{0,20}实则|不仅[^。！？\n]{0,20}而且"),
    "总之开头": re.compile(r"(?:^|\n)\s*(?:总之|所以说|由此可见|总的来说|换句话说|也就是说)"),
    "报告腔": re.compile(r"值得一提的是|希望对你有帮助|让我们一起|总而言之|综上"),
}


def norm(text: str) -> str:
    return FILLER.sub("", MEME_TAG.sub("", text or ""))


def _grams(s: str) -> set[str]:
    return {s[i:i + 2] for i in range(len(s) - 1)}


def sim(a: str, b: str) -> float:
    """两句话去掉称呼和标点后，两字片段的重合度（交集 / 并集）。太短的不比，返回 0。"""
    x, y = norm(a), norm(b)
    if len(x) < MIN_CHARS or len(y) < MIN_CHARS:
        return 0.0
    if x == y:
        return 1.0
    ga, gb = _grams(x), _grams(y)
    return len(ga & gb) / len(ga | gb)


def _lines(text: str) -> list[str]:
    return [x for x in (text or "").split("\n") if len(norm(x)) >= MIN_CHARS]


def most_alike(text: str, recent: list[str]) -> tuple[float, str]:
    """(最高重合度, 像的是哪句)：整条对整条，和一行对一行，取最高的。"""
    best, which = 0.0, ""
    mine = _lines(text)
    for old in recent[-WINDOW:]:
        pairs = [(text, old)]
        if len(mine) > 1 or "\n" in (old or ""):
            pairs += [(a, b) for a in mine for b in _lines(old)]
        for a, b in pairs:
            s = sim(a, b)
            if s > best:
                best, which = s, b
    return best, which


def opener(text: str) -> str:
    """开头几个字（去掉称呼、自称、标点）；不够长返回 ''。"""
    s = norm((text or "").strip().split("\n")[0])
    return s[:OPENER_CHARS] if len(s) >= OPENER_CHARS else ""


def soft_hits(text: str) -> list[str]:
    return [name for name, rx in SOFT.items() if rx.search(text or "")]


def check(text: str, recent: list[str]) -> list[str]:
    """这句话撞了哪些套路（空列表 = 没撞）。recent 是她在这个会话里之前发过的话，旧的在前。"""
    hits = []
    s, which = most_alike(text, recent)
    if s >= SAME:
        hits.append(f"same:{s:.2f}:{which.strip()[:30]}")
    op = opener(text)
    last = [opener(x) for x in recent[-2:]]
    if op and len(last) == 2 and last[0] == last[1] == op:
        hits.append(f"opener:{op}")
    soft = soft_hits(text)
    if len(soft) >= SOFT_MIN:
        hits.append("soft:" + "、".join(soft))
    return hits


def load_sent(folder: str, days: int = 14) -> dict[str, list[str]]:
    """重启后把她最近发过的话从重说记录里读回来：{会话: [发出去的话…]}（每个会话最多 WINDOW 句，旧的在前）。"""
    out: dict[str, list[str]] = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.jsonl")))[-days:]:
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("umo") and (r.get("final") or "").strip():
                        out.setdefault(r["umo"], []).append(MEME_TAG.sub("", r["final"]).strip())
        except OSError:
            continue
    return {k: v[-WINDOW:] for k, v in out.items()}
