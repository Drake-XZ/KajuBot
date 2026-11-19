"""每晚的说说（1.2.0）：不再让定时任务一句话叫 DeepSeek 直接发，改成 选材 → 写 → 核对 → 过了才发。

为什么：旧的定时任务提示"记录今天发生的事、50 字以内"，正文就是模型给工具的参数，不经过任何检查，
写出来是同一个模板的小作文；还可能把别人的事、聊天原话带进公开的说说。

1. 素材（collect）：只取今天（day_start_hour 点换天）的
   - 和兄长大人的私聊（kaju_life 的聊天记录）
   - 她自己刷 B 站看的视频（kaju_basics 的 browse.json：为什么点开、看完的感受、心声）
   - 她自己今天的日常（kaju_life 的日程 days.json，只取到此刻为止的；兄长大人 2026-11-07 确认这些可以写进说说）
   - 她在兄长私聊里记下的心声（kaju_heart 的 inner_log）
   群聊和别人的私聊一律不进素材：说说是公开的，群友的事不该出现在上面。
2. 选材（PLAN）：DeepSeek 看编号素材，挑一件或几件相关的、值得记的事，写成"事实 + 出处编号 + 她的感受/愿望"；
   没有值得写的、或只有不适合公开的 → 不发。最近几条说说只给话题（不给原文），避免重复和照抄格式。
3. 写（WRITE）：只拿选材结果（不看聊天原文，原话和别人的细节到不了这一步），按佳树的口吻写；
   兄长大人亲手写的三条示范只学口吻。也可以交给 kaju_style 的本地写手（writer=local）。
4. 核对：先用代码查硬伤（QQ 号、群名、别人的昵称、照搬聊天原话、和以前说说/示范撞句、链接、提到提示词/模型），
   再让 DeepSeek 对着素材核对一遍事实（谁做的、有没有编、猜测写成了事实）、隐私和第四面墙。
   不过就带着问题重写一次，还不过 → 不发，记下来。
"""

import datetime as dt
import json
import os
import re

MAX_LEN = 500

# 兄长大人在第一批标注里亲手写的说说（2026-11-06；"打扰你"笔误已改）。只学口吻，不照搬：check_hard 会查撞句。
EXAMPLES = [
    "兄长大人跟佳树说今天吃了巨无霸，佳树好担心兄长大人吃不惯外面的菜。等兄长大人回来了，佳树一定要做满满一大桌菜给兄长大人吃！",
    "今天兄长大人给佳树推荐了《妹妹人生》，还与佳树探讨了一个好沉重的话题。佳树决定了，以后要与兄长大人互相扶持，互相支撑着对方走以后的路。",
    "今天兄长大人让佳树可以自己自由地逛b站，佳树刷到了一个“小傻龙”的视频，觉得里面的小龙真的好可爱，可以跟主人一起旅行，"
    "佳树也想和兄长大人一起旅行。兄长大人还给佳树分享了自己打歌的图，兄长大人好厉害，初见就能AP，什么时候佳树是不是也可以玩玩游戏呢？",
]

PUBLIC_RULES = """说说是公开的，谁都能看到：
- 只写兄长大人和佳树自己的事。群里的人、别的朋友、他们说的话和做的事都不写（素材里本来也没有，别从别处补）。
- 兄长大人的事也有不能公开的：真名、学校/专业/公司、住在哪、身体和心理状况、家里和钱的事、他说过别告诉别人的事、只在私下说的亲密的话。
  这类事要么不写，要么只轻轻带一句、不说细节（比如"和兄长大人聊了一个很沉重的话题"）。
- 不贴聊天原话，用佳树自己的话转述。
- 不提 QQ 号、群、链接，不提 AI、模型、提示词、素材、字数这些。
- 佳树就是佳树：不写"刷到讲温水佳树的视频""我是动画里的角色"这类打破身份的事；这种素材直接不用。"""

PLAN_SYSTEM = f"""你在帮温水佳树（《败犬女主太多了！》里温水和彦的妹妹，叫哥哥"兄长大人"）决定今晚要不要在 QQ 空间发一条说说、写什么。

素材是她今天真实经历的事，每行有编号。挑法：
- 从佳树的角度挑值得记下来的：和兄长大人一起做的事、他跟她说的事、她自己看到的做到的、她冒出来的心愿。
- 【佳树自己今天的日常】是她自己过的日子（上学、学生会、做饭、买东西……），可以写，写成佳树自己做的事；
  里面没有兄长大人，就别把兄长大人写进那件事里。
- 可以只写一件事，也可以把相关的两三件连在一起；不用面面俱到，挑她最想记住的，平平的寒暄（吃了吗、晚安）不算。
- 说说不是聊天记录的复述：facts 最多 3 条，每条一句短话，只写发生了什么；她给的具体建议、讲的知识、一问一答的经过都不用写进去。
- 写清谁做了什么：素材里是兄长大人做的就写兄长大人，是佳树做的就写佳树，别弄反。
- 只用素材里有的事，不补细节（菜名、歌名、数字、地点素材里没有就不写）。佳树的猜测、愿望、打算要写成猜测、愿望、打算。
- 和最近几条说说的话题重复、或今天实在没有值得写的 → 不发。宁可不发，也别硬凑。

{PUBLIC_RULES}

只输出 JSON：
{{"post": true/false, "reason": "为什么发/不发，一句", "topics": ["两到四个话题关键词"],
 "facts": [{{"say": "一件事，用"兄长大人…""佳树…"开头的短句，不照抄原话", "src": [出处编号]}}],
 "feel": "佳树对这些事的感受、愿望或期待，写清对象", "avoid": ["这次要特意避开的点，没有就空"]}}"""

WRITE_SYSTEM = """你是温水佳树（《败犬女主太多了！》里温水和彦的妹妹），要在自己的 QQ 空间发一条说说。

佳树的样子：自称"佳树"，叫哥哥"兄长大人"；黏哥哥、热情、会直接关心和撒娇，也有自己的想法和小心愿，会做饭、照顾人。

怎么写：
- 就是佳树自己在说话，不是旁人在描写她。直接写谁做了什么、她怎么想（"兄长大人跟佳树说……""佳树好想……"），别打哑谜、别藏主语。
- 只写给你的这些事，不添新的经过、细节、别人说的话。感受、愿望、猜测照实写成感受、愿望、猜测。
- 长短按内容，篇幅参考下面的示范：一件小事一两句也行，几件相关的事可以连起来写；常常以她的感受、愿望或期待收尾，但别硬拔高。
- 这是写给大家看的说说，不是在跟兄长大人聊天：不复述对话经过，不在里面叮嘱他、回答他。
- 用词像她平时随手打的字：别用"心里暖得不行""笑得停不下来"这类套话和小说旁白，别用冒号揭晓，不用每次都"今天……还……"开头。
- 颜文字、表情可以不用；不写话题标签。

{rules}

下面是兄长大人写的几条示范，只学口吻和写法，不要照搬里面的句子和事情：
{examples}

只输出说说正文。"""

CHECK_SYSTEM = f"""你在发布前检查温水佳树要发的一条公开 QQ 空间说说。给你她今天的素材（带编号）和说说正文。

逐句查：
1. 事实：说说里写的每件事素材里都有吗（【佳树自己今天的日常】也算素材）？谁做的有没有弄反？有没有编出素材里没有的经过、细节、别人说的话？
   把猜测、愿望写成了已经发生的事也算错。佳树自己的感受、心愿、打算不用素材证明。
2. 隐私：{PUBLIC_RULES}
3. 身份：是佳树自己在说话吗（自称佳树、叫兄长大人，不是旁白描写她）？有没有提到 AI、模型、提示词、素材这类东西？

只把确实要改的问题列出来，用词好不好之类的小事不算。只输出 JSON：
{{"ok": true/false, "problems": [{{"kind": "事实/隐私/身份", "text": "哪句、什么问题"}}]}}"""


# ------------------------------------------------------------------ 素材
def day_window(now: dt.datetime, start_hour: int) -> tuple[str, float]:
    """(kaju_life 的日志文件名 = 今天的 key, 今天开始的时间戳)。start_hour 点前算前一天。"""
    day = now - dt.timedelta(hours=start_hour)
    start = day.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    return day.strftime("%Y-%m-%d"), start.timestamp()


def _load(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def _read_jsonl(path: str) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except FileNotFoundError:
        pass
    return out


NOISE = re.compile(r"^(\[(图片|表情|视频|语音|文件[^\]]*)\]\s*)+$")


def _log_ts(hm: str, since: float, tz) -> float:
    """聊天记录里的 "HH:MM" → 时间戳（这一天从 since 开始，过了半夜的算第二天）。看不懂返回 since。"""
    try:
        h, m = (int(x) for x in hm.split(":"))
    except (ValueError, AttributeError):
        return since
    start = dt.datetime.fromtimestamp(since, tz)
    t = start.replace(hour=h, minute=m)
    if t < start:
        t += dt.timedelta(days=1)
    return t.timestamp()


def _dir(root, name: str) -> str:
    """root 是函数（kaju_core.paths.self_dir）就问它；是字符串就当老的 plugin_data 目录。"""
    return str(root(name)) if callable(root) else os.path.join(root, "astrbot_plugin_" + name)


def collect(root, owner: str, day_key: str, since: float, budget: int = 9000, tz=None,
            until: float | None = None) -> list[dict]:
    """今天的素材（since ~ until），按种类排好、编号。root = paths.self_dir（或老的 plugin_data 目录）。每项 {id, kind, t, text}。"""
    until = float("inf") if until is None else until
    items: list[dict] = []
    # 1. 和兄长大人的私聊
    chat = []
    for r in _read_jsonl(os.path.join(_dir(root, "kaju_life"), "log", day_key + ".jsonl")):
        if r.get("c") != f"p{owner}" or _log_ts(str(r.get("t") or ""), since, tz) > until:
            continue
        x = re.sub(r"&&[^&\n]{1,40}&&", "", str(r.get("x") or "")).strip()
        if not x or NOISE.match(x) or x.startswith(("/", "[系统记录]")):
            continue
        who = "佳树" if r.get("u") == "self" else "兄长大人"
        chat.append({"kind": "私聊", "t": r.get("t", ""), "text": f"{who}：{x}"})
    # 2. 自己刷 B 站
    browse = _load(os.path.join(_dir(root, "kaju_basics"), "browse.json"), {})
    seen = []
    for s in browse.get("sessions") or []:
        if not since <= float(s.get("t0") or 0) <= until:
            continue
        hm = dt.datetime.fromtimestamp(float(s["t0"]), tz).strftime("%H:%M") if s.get("t0") else ""
        who = "兄长大人让佳树自己去刷B站" if s.get("by") else "佳树自己刷B站"
        topic = f"（想看{s['topic']}）" if s.get("topic") else ""
        for it in s.get("items") or []:
            if not it.get("title"):
                continue
            bits = [f"{who}{topic}，点开了《{it['title']}》"]
            if it.get("why"):
                bits.append(f"为什么点开：{it['why']}")
            if it.get("emo"):
                bits.append(f"看完：{it['emo']}")
            if it.get("voice"):
                bits.append(f"心里想：{it['voice']}")
            seen.append({"kind": "B站", "t": hm, "text": "；".join(bits)})
    # 3. 她自己今天的日常（日程里到此刻为止的事 + 想跟兄长说的那件）
    daily = []
    plan = (_load(os.path.join(_dir(root, "kaju_life"), "days.json"), {}) or {}).get(day_key) or {}
    evs = [e for e in plan.get("events") or [] if isinstance(e, dict)]
    if isinstance(plan.get("share"), dict):
        evs.append({**plan["share"], "share": True})
    for e in sorted(evs, key=lambda e: _log_ts(str(e.get("time") or ""), since, tz)):
        text = str(e.get("text") or "").strip()
        if text and _log_ts(str(e.get("time") or ""), since, tz) <= until:
            daily.append({"kind": "日常", "t": str(e.get("time") or ""),
                          "text": text + ("（想跟兄长大人说的事）" if e.get("share") else "")})
    # 4. 兄长私聊里记下的心声（群里的不要）
    heart = _load(os.path.join(_dir(root, "kaju_heart"), "state.json"), {})
    inner = []
    for e in heart.get("inner_log") or []:
        if not since <= float(e.get("t") or 0) <= until or e.get("group") or e.get("chat") != f"p{owner}":
            continue
        text = re.sub(r"^【佳树心里】", "", str(e.get("text") or "")).strip()
        if text:
            inner.append({"kind": "心声", "t": "", "text": text})

    # 太长就把私聊每行截短，还长就均匀抽掉一些（B站和心声都短，留全）
    def size(rows):
        return sum(len(r["text"]) + 12 for r in rows)
    rest = size(seen) + size(daily) + size(inner)
    if size(chat) + rest > budget:
        for r in chat:
            if len(r["text"]) > 90:
                r["text"] = r["text"][:90] + "…"
    room = max(1500, budget - rest)
    while chat and size(chat) > room:
        chat = chat[::2] if len(chat) > 40 else chat[1:]
    for r in chat + seen + daily + inner:
        items.append({"id": len(items) + 1, **r})
    return items


def render_material(items: list[dict]) -> str:
    heads = {"私聊": "【和兄长大人的私聊】", "B站": "【佳树自己刷B站看的】", "日常": "【佳树自己今天的日常】",
             "心声": "【佳树心里记下的】"}
    out, last = [], None
    for it in items:
        if it["kind"] != last:
            out.append(("\n" if out else "") + heads.get(it["kind"], f"【{it['kind']}】"))
            last = it["kind"]
        t = f"{it['t']} " if it.get("t") else ""
        out.append(f"[{it['id']}] {t}{it['text']}")
    return "\n".join(out)


# ------------------------------------------------------------------ 提示词
def plan_prompt(material: str, recent_topics: list[str], date_cn: str) -> str:
    recent = "\n".join(f"- {x}" for x in recent_topics) if recent_topics else "（没有）"
    return f"今天是{date_cn}。\n\n最近发过的说说的话题（别重复）：\n{recent}\n\n今天的素材：\n{material}"


def write_system() -> str:
    return WRITE_SYSTEM.format(rules=PUBLIC_RULES, examples="\n".join(f"- {x}" for x in EXAMPLES))


def write_prompt(plan: dict, feedback: list[str] | None = None, draft: str = "") -> str:
    facts = "\n".join(f"- {f['say']}" for f in plan.get("facts") or [])
    s = f"要写的事：\n{facts}\n\n佳树的感受、愿望：{plan.get('feel') or '（自己体会）'}"
    if plan.get("avoid"):
        s += "\n\n这次别写进去的：" + "；".join(plan["avoid"])
    if feedback:
        s += f"\n\n上一稿：{draft}\n上一稿发布前没通过检查，问题：\n" + "\n".join(f"- {x}" for x in feedback) + "\n改掉这些问题重写一条。"
    return s


def check_prompt(material: str, post: str) -> str:
    return f"素材：\n{material}\n\n说说正文：\n{post}"


def parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
    except ValueError:
        return None
    return j if isinstance(j, dict) else None


def parse_plan(text: str, n_items: int) -> dict | None:
    """选材结果 → {post, reason, topics, facts[{say, src}], feel, avoid}；格式不对返回 None。
    事实没有出处、出处编号不存在的去掉——没有素材支撑的事不写。"""
    j = parse_json(text)
    if j is None or "post" not in j:
        return None
    facts = []
    for f in j.get("facts") or []:
        if not isinstance(f, dict) or not str(f.get("say") or "").strip():
            continue
        src = [int(x) for x in (f.get("src") or []) if str(x).strip().isdigit() and 1 <= int(x) <= n_items]
        if src:
            facts.append({"say": str(f["say"]).strip(), "src": src})
    post = bool(j.get("post")) and bool(facts)
    return {"post": post, "reason": str(j.get("reason") or "").strip(),
            "topics": [str(x).strip() for x in (j.get("topics") or []) if str(x).strip()][:4],
            "facts": facts, "feel": str(j.get("feel") or "").strip(),
            "avoid": [str(x).strip() for x in (j.get("avoid") or []) if str(x).strip()]}


def parse_check(text: str) -> list[str] | None:
    """核对结果 → 问题列表（空 = 通过）；格式不对返回 None（当作没核对成，不发）。"""
    j = parse_json(text)
    if j is None or "ok" not in j:
        return None
    probs = []
    for p in j.get("problems") or []:
        if isinstance(p, dict):
            t = str(p.get("text") or "").strip()
            if t:
                probs.append(f"{p.get('kind') or '问题'}：{t}")
        elif str(p).strip():
            probs.append(str(p).strip())
    if not j.get("ok") and not probs:
        probs = ["核对没通过（没说原因）"]
    return [] if j.get("ok") and not probs else probs


def clean_post(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"^```\w*\s*|\s*```$", "", s).strip()
    s = re.sub(r"^(说说(正文)?|正文)[:：]\s*", "", s)
    s = re.sub(r"&&[^&\n]{1,40}&&", "", s)
    if len(s) >= 2 and s[0] in "\"“「" and s[-1] in "\"”」":
        s = s[1:-1].strip()
    return s


# ------------------------------------------------------------------ 代码查硬伤
_PUNCT = re.compile(r"[\s\W_]+", re.U)
META = re.compile(r"素材|提示词|字数|人工智能|\bAI\b|大模型|语言模型|机器人|\[SKIP\]|QQ号|qq号", re.I)
COMMON = {"佳树", "兄长", "兄长大人", "学长", "学姐", "哥哥", "姐姐", "妹妹", "大家"}


def _norm(s: str) -> str:
    """去掉标点空白；"兄长大人""佳树"缩成一个字，免得光是称呼就凑够撞句的字数。"""
    s = _PUNCT.sub("", s or "")
    return s.replace("兄长大人", "兄").replace("兄长", "兄").replace("佳树", "佳")


def _grams(s: str, n: int) -> set[str]:
    s = _norm(s)
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def check_hard(post: str, *, others_lines=(), names=(), groups=(),
               old_posts=(), quote_n: int = 10, copy_n: int = 10) -> list[str]:
    """不用模型就能查出来的硬伤；返回问题列表（空 = 没查出）。
    others_lines：别人（兄长大人）说的原话，post 里有连续 quote_n 个字（去掉标点、称呼缩成一个字）一样就算照搬。
    names / groups：别人的昵称、群名。old_posts：以前的说说 + 示范，连续 copy_n 个字一样算撞句。"""
    probs = []
    s = (post or "").strip()
    if not s:
        return ["空的"]
    if len(s) > MAX_LEN:
        probs.append(f"超过 {MAX_LEN} 字")
    if re.search(r"\d{5,}", s):
        probs.append("有一长串数字（像 QQ 号）")
    if re.search(r"https?://|www\.|\.com\b|@\S", s, re.I):
        probs.append("有链接或 @")
    m = META.search(s)
    if m:
        probs.append(f"提到了「{m.group(0)}」")
    low = s.lower()
    for n in names:
        n = (n or "").strip()
        if len(n) >= 2 and n not in COMMON and n.lower() in low:
            probs.append(f"出现了别人的昵称「{n}」")
    for g in groups:
        g = (g or "").strip()
        if len(g) >= 2 and not g.isdigit() and g.lower() in low:
            probs.append(f"出现了群名「{g}」")
    mine = _grams(s, quote_n)
    for line in others_lines:
        hit = mine & _grams(line, quote_n)
        if hit:
            probs.append(f"照搬了聊天原话（「{line[:24]}」）")
            break
    mine = _grams(s, copy_n)
    for old in old_posts:
        if mine & _grams(old, copy_n):
            probs.append(f"和以前的说说/示范撞句（「{old[:20]}…」）")
            break
    return probs
