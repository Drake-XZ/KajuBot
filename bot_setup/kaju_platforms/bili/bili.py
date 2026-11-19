"""B 站视频链接：认出聊天里的链接 / QQ 分享卡片，读视频页面上公开的信息，写成一段给她看的介绍。

能拿到的都是不登录、普通浏览器打开视频页就能看到的东西：
- 视频页（www.bilibili.com/video/BV…）里的 __INITIAL_STATE__：标题、UP 主、时长、分区、标签、简介、播放数据、封面、分 P；
- 封面图（交给看图模型描述）；
- 公开弹幕（comment.bilibili.com/<cid>.xml）：观众边看边发的话，按时间挑一些（兄长让她看弹幕时才给）；
- 手机版视频页（m.bilibili.com）给访客的最低画质 mp4：兄长让她看视频（2026-11-01），describe.py 下载下来看完，
  过一阵自动删。下载不成时只看页面，介绍里写明"没看到视频本身"。

配置里填了兄长自己的 B 站登录 Cookie（media.bili_cookie）时，再用它向 B 站播放器接口（x/player/v2）要字幕
（UP主上传的或 B 站 AI 识别的旁白/台词），长的让模型写成观后笔记。Cookie 只发给 api.bilibili.com。

这里只有纯逻辑（认链接、解析页面/弹幕、挑弹幕、拼文字），联网在 describe.py 里。
"""

from __future__ import annotations

import html as htmllib
import json
import math
import re

# 短链、电脑版/手机版视频页；单独的 BV 号也认
LINK_RE = re.compile(
    r"https?://(?:b23\.tv|bili2233\.cn)/[A-Za-z0-9]+"
    r"|(?:https?://)?(?:www\.|m\.)?bilibili\.com/video/(?:BV[0-9A-Za-z]{10}|av\d+)[^\s\"'<>，。！？）】]*"
    r"|(?<![0-9A-Za-z])BV1[0-9A-Za-z]{9}(?![0-9A-Za-z])",
    re.I,
)
BV_RE = re.compile(r"BV1[0-9A-Za-z]{9}")
AV_RE = re.compile(r"/video/av(\d+)", re.I)
P_RE = re.compile(r"[?&]p=(\d+)")
SHORT_RE = re.compile(r"^https?://(?:b23\.tv|bili2233\.cn)/", re.I)


def find_links(text: str, limit: int = 2) -> list[str]:
    """Bilibili links in a piece of text, in order, de-duplicated by video."""
    out, seen = [], set()
    for m in LINK_RE.finditer(text or ""):
        url = m.group(0).rstrip(".,;!?)]}")
        if not url.lower().startswith(("http", "bv")):
            url = "https://" + url
        key = video_key(url) or url
        if key in seen:
            continue
        seen.add(key)
        out.append(url)
        if len(out) >= limit:
            break
    return out


def card_links(data, limit: int = 2) -> list[str]:
    """Links inside a QQ share card (Json component): the B 站 mini-app card keeps it in meta.detail_1.qqdocurl."""
    if isinstance(data, dict) and isinstance(data.get("data"), str):
        try:
            data = json.loads(data["data"])
        except json.JSONDecodeError:
            pass
    try:
        text = json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(data)
    return find_links(text.replace("\\/", "/"), limit)


def is_short(url: str) -> bool:
    return bool(SHORT_RE.match(url or ""))


def video_key(url: str) -> str:
    """'BV…' / 'av…' plus '#p' for a part other than the first; '' when the url names no video."""
    m = BV_RE.search(url or "")
    vid = m.group(0) if m else ""
    if not vid:
        a = AV_RE.search(url or "")
        vid = f"av{a.group(1)}" if a else ""
    if not vid:
        return ""
    p = P_RE.search(url or "")
    return vid + (f"#{int(p.group(1))}" if p and int(p.group(1)) > 1 else "")


def page_url(key: str) -> str:
    vid, _, p = key.partition("#")
    return f"https://www.bilibili.com/video/{vid}/" + (f"?p={p}" if p else "")


# ------------------------------------------------------------------ 视频页
def _initial_state(page: str) -> dict:
    i = page.find("window.__INITIAL_STATE__=")
    if i < 0:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(page[i + len("window.__INITIAL_STATE__="):])
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _meta_tags(page: str) -> dict:
    out = {}
    for m in re.finditer(r"<meta\b[^>]*>", page or "", re.I):
        tag = m.group(0)
        k = re.search(r'(?:name|property|itemprop)\s*=\s*"([^"]+)"', tag)
        v = re.search(r'content\s*=\s*"([^"]*)"', tag, re.S)
        if k and v and k.group(1) not in out:
            out[k.group(1)] = htmllib.unescape(v.group(1)).strip()
    t = re.search(r"<title[^>]*>(.*?)</title>", page or "", re.S | re.I)
    if t:
        out.setdefault("title", htmllib.unescape(t.group(1)).strip())
    return out


def _site_suffix(title: str) -> str:
    return re.sub(r"_哔哩哔哩_bilibili$|_bilibili$|-哔哩哔哩$", "", title or "").strip()


def parse_page(page: str, part: int = 1) -> dict:
    """视频页 → {title, up, duration, area, tags, desc, stat, cover, cid, part_title, parts, pubdate}；读不出标题返回 {}。"""
    st = _initial_state(page)
    v = st.get("videoData")
    v = v if isinstance(v, dict) else {}
    if v.get("title"):
        pages = [p for p in v.get("pages") or [] if isinstance(p, dict)]
        cur = next((p for p in pages if int(p.get("page", 0) or 0) == part), pages[0] if pages else {})
        stat = v.get("stat") or {}
        return {
            "title": str(v.get("title") or "").strip(),
            "bvid": str(v.get("bvid") or ""),
            "up": str((v.get("owner") or {}).get("name") or ""),
            "duration": int(cur.get("duration") or v.get("duration") or 0),
            "area": str(v.get("tname") or v.get("tname_v2") or ""),
            "tags": [str(t.get("tag_name")) for t in st.get("tags") or [] if isinstance(t, dict) and t.get("tag_name")],
            "desc": str(v.get("desc") or "").strip(),
            "stat": {k: int(stat.get(k) or 0) for k in ("view", "like", "danmaku", "favorite", "coin", "reply")},
            "cover": str(v.get("pic") or ""),
            "cid": int(cur.get("cid") or v.get("cid") or 0),
            "aid": int(v.get("aid") or 0),
            "part_title": str(cur.get("part") or "") if len(pages) > 1 else "",
            "parts": len(pages),
            "pubdate": int(v.get("pubdate") or 0),
            "p": part,
        }
    # 拿不到页面数据（改版、出错页）：退回网页的 meta 标签（标题、简介、作者、封面）
    meta = _meta_tags(page)
    title = _site_suffix(meta.get("og:title") or meta.get("title") or "")
    if not title or title.startswith("出错啦"):
        return {}
    return {"title": title, "bvid": "", "up": meta.get("author", ""), "duration": 0, "area": "",
            "tags": [], "desc": _desc_from_meta(meta.get("description", ""), title), "stat": {},
            "cover": meta.get("og:image", "").split("@")[0], "cid": 0, "part_title": "", "parts": 0, "pubdate": 0}


def _desc_from_meta(desc: str, title: str) -> str:
    # B 站的 description 是 "标题, 视频播放量…, 视频作者…, 作者简介…，相关视频：…"，只留真正的简介部分
    if desc.startswith(title):
        return ""
    return desc.split("，相关视频")[0][:300]


def parse_generic(page: str) -> dict:
    """不是普通视频（番剧、直播、专栏……）：只读网页标题和简介。"""
    meta = _meta_tags(page)
    title = _site_suffix(meta.get("og:title") or meta.get("title") or "")
    if not title or title.startswith("出错啦"):
        return {}
    return {"title": title, "desc": (meta.get("og:description") or meta.get("description") or "")[:300],
            "cover": (meta.get("og:image") or "").split("@")[0]}


# ------------------------------------------------------------------ 弹幕
def parse_danmaku(xml: str) -> list[tuple[float, str]]:
    out = []
    for m in re.finditer(r'<d p="([^"]+)">([^<]*)</d>', xml or ""):
        try:
            sec = float(m.group(1).split(",")[0])
        except ValueError:
            continue
        text = " ".join(htmllib.unescape(m.group(2)).split())
        if text:
            out.append((sec, text))
    out.sort(key=lambda x: x[0])
    return out


_NOISE = re.compile(r"^[\W\d_a-zA-Z]*$|^(哈+|啊+|草+|awsl|xswl|nb+|6+|？+|\?+|。+|！+)$", re.I)
# 弹幕里的黄段子、脏话不给她看（她是初三女生，观众拿角色开的荤玩笑很多）
_CRUDE = re.compile(
    r"叠|涩|色色|瑟瑟|做爱|上床|床上|开房|怀孕|生孩子|孩子|内裤|胖次|奶子|欧派|胸|舔|腿|脚|"
    r"操|艹|屌|逼|鸡巴|jb|几把|妈的|死妈|nmsl|sb|傻[逼比b]|卧槽|我草|淦|骚|撸|冲了|导管|"
    r"老婆|老公|结婚|娶|嫁|亲亲|亲嘴|接吻|h本|本子|里番|18禁|r18|nsfw|玩具|[x×]玩|那层关系|伦理",
    re.I,
)


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower())


def _usable(text: str) -> bool:
    if not 4 <= len(text) <= 40 or _NOISE.match(text) or _CRUDE.search(text):
        return False
    return len(set(text)) / len(text) >= 0.4  # "我的我的我的…" 这种刷屏


def pick_danmaku(items: list[tuple[float, str]], n: int = 14, duration: float = 0,
                 skip: set[str] | None = None) -> list[tuple[float, str]]:
    """按时间均匀挑 n 条有内容的弹幕：每一段里挑说得最具体的（长一点），几个人都发过的加分。
    skip 里的（单独列出的"刷得最多"那几句）不再挑。"""
    skip = {_norm(t) for t in skip or ()}
    good = [(s, t) for s, t in items if _usable(t) and _norm(t) not in skip]
    if not good or n <= 0:
        return []
    counts: dict[str, int] = {}
    for _, t in good:
        counts[_norm(t)] = counts.get(_norm(t), 0) + 1
    end = max(duration, good[-1][0]) or 1
    span = end / n
    picked, used = [], set()
    for i in range(n):
        lo, hi = i * span, (i + 1) * span
        cands = [(s, t) for s, t in good if lo <= s < hi and _norm(t) not in used]
        if not cands:
            continue
        s, t = max(cands, key=lambda x: min(len(x[1]), 24) + 2 * math.log2(counts[_norm(x[1])]))
        used.add(_norm(t))
        picked.append((s, t))
    return picked


def popular(items: list[tuple[float, str]], k: int = 3, at_least: int = 5) -> list[tuple[str, int]]:
    """被很多人刷的话（≥at_least 条）。"""
    counts: dict[str, list] = {}
    for _, t in items:
        if 2 <= len(t) <= 20 and not _CRUDE.search(t):
            counts.setdefault(_norm(t), [t, 0])[1] += 1
    top = sorted(counts.values(), key=lambda x: -x[1])
    return [(t, c) for t, c in top if c >= at_least and _norm(t)][:k]


# ------------------------------------------------------------------ 拼成给她看的文字
def fmt_count(n: int) -> str:
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}亿".replace(".0亿", "亿")
    if n >= 10_000:
        return f"{n / 10_000:.0f}万" if n >= 100_000 else f"{n / 10_000:.1f}万".replace(".0万", "万")
    return str(n)


def fmt_secs(sec: float) -> str:
    sec = int(sec)
    if sec >= 3600:
        return f"{sec // 3600}小时{sec % 3600 // 60}分"
    if sec >= 60:
        return f"{sec // 60}分{sec % 60}秒" if sec % 60 else f"{sec // 60}分钟"
    return f"{sec}秒"


def stamp(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"


SEEN_ONLY_PAGE = "（这些是视频页面上能看到的：标题、简介和封面。视频本身的画面和声音佳树没看到。）"
SEEN_SUBTITLE = "（佳树看了这个视频的字幕——旁白和台词都知道了；画面没看到。）"
SEEN_VIDEO = "（佳树已看过这个视频的代表画面；声音是否转写成功、听了多少，以前面的记录为准。画面经过抽样，短暂细节可能遗漏。）"


def mobile_play_urls(page: str) -> list[dict]:
    """手机版视频页（m.bilibili.com）给不登录的访客的播放地址：最低画质（360P）、带声音的整段 mp4。
    返回 [{url, size, length(毫秒)}]，长视频可能分成几段。"""
    def find(o):
        if isinstance(o, dict):
            if isinstance(o.get("playUrlInfo"), list):
                return o["playUrlInfo"]
            for v in o.values():
                r = find(v)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = find(v)
                if r is not None:
                    return r
        return None

    out = []
    for seg in find(_initial_state(page)) or []:
        url = str(seg.get("url") or "") if isinstance(seg, dict) else ""
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("http"):
            backup = [str(b) for b in (seg.get("backup_url") or seg.get("backupUrl") or []) if b]
            out.append({"url": url, "size": int(seg.get("size") or 0), "length": int(seg.get("length") or 0),
                        "backup": backup})
    return out


# 视频文件服务器（upos）的几个镜像：同一个下载地址换个服务器名也能下（2026-11-08 实测 cosov/aliov/hw/cos 都 206）。
# 手机版页面有时给 upos-hz-mirrorakam.akamaized.net（海外节点，os=akam）：它的地址换到上面几台也能下；
# 反过来别的地址换到 akamaized 是 403，所以它不在备选里。一台连不上、下到一半断了就换下一台。
MIRRORS = ("upos-sz-mirrorcosov.bilivideo.com", "upos-sz-mirroraliov.bilivideo.com",
           "upos-sz-mirrorhw.bilivideo.com", "upos-sz-mirrorcos.bilivideo.com")
_UPOS = re.compile(r"^https://(upos-[a-z0-9-]+\.(?:bilivideo\.(?:com|cn)|akamaized\.net))/", re.I)


def video_urls(url: str, backups=(), limit: int = 4) -> list[str]:
    """一个视频文件能从哪些地址下：原地址、B站给的备用地址、换成别的镜像服务器的原地址（去重，最多 limit 个）。"""
    out = []
    for u in [url, *(backups or [])]:
        u = str(u or "")
        if u.startswith("//"):
            u = "https:" + u
        if u.startswith("http"):
            out.append(u)
    m = _UPOS.match(out[0]) if out else None
    if m:
        out += [out[0].replace(m.group(1), h, 1) for h in MIRRORS if h.lower() != m.group(1).lower()]
    return list(dict.fromkeys(out))[:limit]


# ------------------------------------------------------------------ 登录后能拿到的：字幕
def cookie_header(raw: str) -> str:
    """配置里填的 Cookie → 请求头。可以填整段 "SESSDATA=…; buvid3=…"，也可以只填 SESSDATA 的值。"""
    raw = " ".join(str(raw or "").split()).strip().strip(";").strip()
    if not raw:
        return ""
    if raw.lower().startswith("cookie:"):
        raw = raw[7:].strip()
    return raw if "=" in raw else f"SESSDATA={raw}"


def parse_player(data: dict) -> tuple[list[dict], bool]:
    """播放器接口（x/player/v2）→ (字幕列表 [{lan, name, url}], 是否登录着)。"""
    d = data.get("data") if isinstance(data, dict) else None
    if not isinstance(d, dict):
        return [], False
    subs = []
    for s in ((d.get("subtitle") or {}).get("subtitles") or []):
        url = str(s.get("subtitle_url") or "")
        if url:
            subs.append({"lan": str(s.get("lan") or ""), "name": str(s.get("lan_doc") or ""),
                         "url": "https:" + url if url.startswith("//") else url})
    return subs, bool(d.get("login_mid") or d.get("is_login") or d.get("login_mid_hash"))


_LAN_ORDER = ("zh-CN", "ai-zh", "zh-Hans", "zh", "zh-TW", "zh-HK", "zh-Hant", "ai-ja", "ja", "ai-en", "en-US", "en")


def rank_subtitles(subs: list[dict]) -> list[dict]:
    """中文优先（UP主自己传的 > AI 识别的 > 繁体），再日文、英文（B 站把旁白自动翻译的版本），其它最后。"""
    rank = {lan: i for i, lan in enumerate(_LAN_ORDER)}
    return sorted(subs, key=lambda s: rank.get(s["lan"], len(rank) + (0 if "zh" in s["lan"] else 1)))


def is_chinese(lan: str) -> bool:
    return "zh" in (lan or "")


def subtitle_url_ok(url: str, aid) -> bool:
    """B 站的播放器接口有时会把别的视频的 AI 字幕塞过来（2026-10-31 实测：同一个请求连发几次，
    时而是这个视频的、时而是别的视频的、时而没有）。AI 字幕文件名以所属视频的 aid 开头，对不上就是串了。"""
    name = (url or "").split("?")[0].rsplit("/", 1)[-1]
    if "/ai_subtitle/" not in (url or "") or not name[:1].isdigit() or not aid:
        return True
    return name.startswith(str(aid))


def subtitle_fits(lines: list[tuple[float, str]], duration: float) -> bool:
    """字幕的时间跟视频长度对得上：不超出视频，也不是只有开头一小段（长视频至少覆盖三成）。"""
    if not lines:
        return False
    if not duration:
        return True
    last = lines[-1][0]
    return last <= duration + 15 and (duration < 90 or last >= 0.3 * duration)


def parse_subtitle(data: dict) -> list[tuple[float, str]]:
    out = []
    for b in (data.get("body") if isinstance(data, dict) else None) or []:
        text = " ".join(str(b.get("content") or "").split())
        if text:
            try:
                out.append((float(b.get("from") or 0), text))
            except (TypeError, ValueError):
                out.append((0.0, text))
    return out


def transcript(lines: list[tuple[float, str]], every: float = 60) -> str:
    """字幕连成一段，每隔一分钟左右插一个时间点，方便模型讲顺序。"""
    parts, next_mark = [], 0.0
    for sec, text in lines:
        if sec >= next_mark:
            parts.append(f"[{stamp(sec)}]")
            next_mark = sec + every
        parts.append(text)
    return " ".join(parts)


def describe(info: dict, cover: str = "", danmaku: list[tuple[float, str]] | None = None,
             hot: list[tuple[str, int]] | None = None, desc_chars: int = 200, watched: str = "",
             seen: str | None = None) -> str:
    """一段介绍：先说是什么视频，看过就接着写内容（观后笔记/字幕），再标签、播放数据、简介、封面，
    对方让她看弹幕时最后附弹幕。重要的放前面（情绪判断、珍藏都只取开头一段）。"""
    head = f"B站视频《{info['title']}》"
    bits = []
    if info.get("part_title"):
        bits.append(f"第{info.get('p') or 1}P「{info['part_title']}」")
    if info.get("up"):
        bits.append(f"UP主：{info['up']}")
    if info.get("duration"):
        bits.append(fmt_secs(info["duration"]))
    if info.get("area"):
        bits.append(info["area"])
    if bits:
        head += "（" + "，".join(bits) + "）"
    lines = [head]
    if watched:
        lines.append(watched)
    if info.get("tags"):
        lines.append("标签：" + "、".join(info["tags"][:8]))
    st = info.get("stat") or {}
    if st.get("view"):
        nums = [f"播放{fmt_count(st['view'])}"]
        if st.get("like"):
            nums.append(f"点赞{fmt_count(st['like'])}")
        if st.get("danmaku"):
            nums.append(f"弹幕{fmt_count(st['danmaku'])}")
        lines.append("，".join(nums))
    desc = " ".join((info.get("desc") or "").split())
    if desc and desc != "-":
        lines.append("简介：" + (desc[:desc_chars] + "…" if len(desc) > desc_chars else desc))
    if cover:
        lines.append("封面：" + cover)
    if seen is None:
        seen = SEEN_SUBTITLE if watched else SEEN_ONLY_PAGE
    text = "。".join(x.rstrip("。") for x in lines) + "。" + seen
    dm = danmaku_text(danmaku, hot)
    return text + dm if dm else text


def danmaku_text(danmaku: list[tuple[float, str]] | None, hot: list[tuple[str, int]] | None = None) -> str:
    parts = []
    if danmaku:
        parts.append("弹幕（观众边看边发的，按视频时间）：" + " / ".join(f"{stamp(s)} {t}" for s, t in danmaku))
    if hot:
        parts.append("刷得最多的弹幕：" + "、".join(f"「{t}」×{c}" for t, c in hot))
    return "。".join(parts) + ("。" if parts else "")


ASKS_DANMAKU = re.compile(r"弹幕")


def asks_danmaku(text: str) -> bool:
    """对方让她看弹幕（自己的话里提到"弹幕"）时才给她看弹幕。分享链接带的【标题】和链接本身不算（标题里常有"弹幕版"）。"""
    text = re.sub(r"【[^】]*】|https?://\S+", "", text or "")
    return bool(ASKS_DANMAKU.search(text))


# ------------------------------------------------------------------ 评论区（1.24.0）
ASKS_COMMENTS = re.compile(r"评论区|热评|楼中楼|评论(里|都|怎么|咋|说)|网友(都|们)?(怎么|咋)?说")
_EMOTE = re.compile(r"\[[^\[\]]{1,32}\]")
_REPLY_HEAD = re.compile(r"^回复\s*@[^:：]{1,30}[:：]\s*")
_AT = re.compile(r"@[^\s@:：,，。!！?？]{1,20}")


def asks_comments(text: str) -> bool:
    """对方让她看评论区（自己的话里提到"评论/热评/楼中楼/网友怎么说"）。分享链接带的【标题】和链接本身不算。"""
    text = re.sub(r"【[^】]*】|https?://\S+", "", text or "")
    return bool(ASKS_COMMENTS.search(text))


def clean_comment(text: str) -> str:
    t = _REPLY_HEAD.sub("", text or "")
    t = re.sub(r"https?://\S+", "", t)
    t = _EMOTE.sub("", t)
    t = _AT.sub("", t)
    return " / ".join(x.strip() for x in t.splitlines() if x.strip()).strip()


def comment_ok(text: str) -> bool:
    if not 2 <= len(text) <= 120 or _CRUDE.search(text) or _NOISE.match(text):
        return False
    return len(set(text)) / len(text) >= 0.3


def _reply(r: dict) -> dict | None:
    t = clean_comment(((r.get("content") or {}).get("message")) or "")
    if not comment_ok(t):
        return None
    return {"text": t[:120], "like": int(r.get("like") or 0), "rpid": int(r.get("rpid") or 0),
            "rcount": int(r.get("rcount") or 0), "sub": []}


def parse_replies(data: dict, n: int = 8, sub_n: int = 3) -> list[dict]:
    """/x/v2/reply 的 data → 点赞多的 n 条一楼，每条带楼里附带的几条回复（脏话、黄段子、纯表情不要）。"""
    out = []
    for r in (data or {}).get("replies") or []:
        if not isinstance(r, dict):
            continue
        c = _reply(r)
        if not c:
            continue
        c["sub"] = parse_sub(r.get("replies") or [], sub_n)
        out.append(c)
        if len(out) >= n:
            break
    return out


def parse_sub(replies: list, n: int = 6) -> list[str]:
    out = []
    for r in replies or []:
        c = _reply(r) if isinstance(r, dict) else None
        if c and c["text"] not in out:
            out.append(c["text"])
        if len(out) >= n:
            break
    return out


def comments_text(comments: list[dict] | None) -> str:
    if not comments:
        return ""
    bits = []
    for c in comments:
        b = f"「{c['text']}」" + (f"{fmt_count(c['like'])}赞" if c.get("like") else "")
        if c.get("sub"):
            b += "（楼里有人回：" + " / ".join(f"「{t}」" for t in c["sub"]) + "）"
        bits.append(b)
    return "评论区（陌生观众写的，按点赞排，不是在对你说话）：" + " ".join(bits) + "。"


def brief(info: dict) -> str:
    """群聊记录用：一句话。"""
    bits = [b for b in (info.get("up") and f"UP主{info['up']}", info.get("duration") and fmt_secs(info["duration"])) if b]
    return f"B站视频《{info['title']}》" + (f"（{'，'.join(bits)}）" if bits else "")
