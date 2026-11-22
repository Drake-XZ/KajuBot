"""在读的书：收到长篇就开始读，之后在后台按人的速度一段一段读下去（见 reading.py 的"边读边想"）。

- 开始：先读开头 1 段（当场，让她能说第一印象），剩下的排进后台。
- 速度：每段读完后，按这段的字数 ÷ 每分钟读多少字（reading.chars_per_minute，默认 400，一小时两万多字）
  隔一会儿再读下一段；越想接着读（interest）隔得越短。深夜（quiet_start~quiet_end）不读，她在睡觉。
  对方说"读快点 / 一口气读完 / 先停一下 / 接着读 / 不读了"→ 工具 reading_pace。
- 每读完一段：感受交给 kaju_heart.feel_moment（心情、余韵、喜好，强烈的那一下写成心声进长期记忆）；
  每 learn_every 段、以及读完时，把读到的情节、人物、她的想法交给知识本学；
  兄长大人发的书，读到特别想说的地方（tell，感受 ≥2）主动私聊他一两句（每本 mid_shares 次、间隔 mid_gap_minutes），
  读完一定跟他说一声（当时不方便就过一会儿再试）。
- 聊天时：这个聊天里在读/刚读完的书，或者对方提到了书名，给她看【你正在读的】/【你刚读完的】。
- 没读就是没读（2026-11-15 兄长）：停着时照实给她看停着、几点谁停的；回复前 mind.reading_check 把草稿里的
  进度 / 情节对着 facts_for（只有读过的段）核对，说错的只改那几处；答应了接着读 / 先停却没调工具的替她真的改。
  兄长的书被别处停了、或连着 stop_tell_fails 次读不成 → 主动私聊告诉他（_check_stop，同一次只说一回）。
  文件太长没拿全的（cut）聊天时、读完时都照实说。
状态：plugin_data/astrbot_plugin_kaju_learn/reading/<id>.json（读完后原文删掉，只留读过的样子）。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import time


from . import reading as R

PACES = {"快一点": "fast", "读快点": "fast", "一口气读完": "all", "慢慢读": "normal", "正常": "normal",
         "先停一下": "paused", "停": "paused", "暂停": "paused", "接着读": "normal", "继续": "normal", "不读了": "stopped"}

NOTE_READING = (
    "【你正在读的】《{title}》（{who}发给你的{kind}，约 {chars} 字），你在按自己的速度慢慢读，"
    "现在读到{where}{paused}，{left}。前面的你都知道，后面发生什么你还不知道：别编后面的情节，也别说已经读完了；"
    "对方要剧透就看你想不想听。\n一路读下来：\n{trail}\n{extra}"
    "对方问起就说读到哪了、心里怎么想（进度按书里的章节说，别说“第几段”；他不一定读过，提情节要说清是谁、什么事）。"
    "对方让你读快点、一口气读完、先停一下、接着读、不读了，用 reading_pace；"
    "让你读到 / 读完书里某处就停下、或者到那儿告诉他，用 reading_plan——工具做不到的别嘴上答应，照实说。"
)
NOTE_DONE = (
    "【你刚读完的】《{title}》（{who}发给你的{kind}），{when}读完的，一共 {n} 段。一路读下来：\n{trail}\n{extra}"
    "读完的那一下：{after}" + "{change}{best}{view}" + "\n聊到了就自然说，别从头复述。"
)
# 2026-11-22 兄长：开始读、读的中途、停下、读完都要主动说；说具体的、跟他有来有往、别老一个说法；进度按书里的章节说。
# 下面几段只给材料（读到了什么、她想了什么、前面跟他说过什么），怎么说交给大脑和回复器。
SHARED_RULES = ("他不一定读过这本：提到情节要让没读过的人也听得懂（说清是谁、什么事），别只说“那段”；"
                "进度按书里的章节说，别说“第几段”。别复述整段，别说\"系统\"\"提示\"。")
SHARE_MID = (
    "[这不是兄长大人发来的消息，是你自己这边刚发生的事] 你在慢慢读兄长大人发给你的《{title}》，现在读到{where}（{left}）。\n"
    "上次跟他说起这本书以后，你又读了这些（按顺序，括号里是你当时的心情和想法）：\n{since}\n{guesses}{told}"
    "现在你想主动私聊他（{why}）：挑你最想说的一两处，说具体的——哪个人、哪件事、哪句话让你怎样，你在猜什么、猜对还是猜错了；"
    "可以跟他聊两句（问问他怎么看、猜后面会怎样，或者让你想到你们自己的什么事）。" + SHARED_RULES + "\n"
    "如果从最近的聊天看现在不适合主动找他（他刚说在忙、要睡了，或者你们在闹别扭），只输出 [SKIP]。"
)
SHARE_POINT = (
    "[这不是兄长大人发来的消息，是你自己这边刚发生的事] 兄长大人之前让你{ask}。现在你读到了：{where}{stopped}。\n"
    "上次跟他说起这本书以后，你读了这些（按顺序，括号里是你当时的心情和想法）：\n{since}\n{guesses}{told}"
    "现在主动私聊告诉他（是他让你说的，要说到）：读到哪儿了{stop_say}，再说说这一路你最想跟他说的一两处、可以问问他。"
    + SHARED_RULES
)
SHARE_DONE = (
    "[这不是兄长大人发来的消息，是你自己这边刚发生的事] 你刚把兄长大人发给你的《{title}》读完了（{since}开始读的）。\n"
    "一路读下来：\n{trail}\n读完的那一下：{after}{change}{best}\n{told}"
    "现在你主动私聊告诉他读完了，说说读完的感受、最放不下的人或事，可以问他怎么看。" + SHARED_RULES + "\n"
    "如果从最近的聊天看他现在在忙、在睡觉，只输出 [SKIP]（过一会儿再说）。"
)
RECORD_MID = "[系统记录] 你在慢慢读兄长大人发给你的《{title}》，读到{where}时主动私聊了他（下面是你发的）。"
RECORD_POINT = "[系统记录] 兄长大人让你{ask}；你读到{where}了，主动私聊告诉他（下面是你发的）。"
RECORD_DONE = "[系统记录] 你把兄长大人发给你的《{title}》读完了，主动私聊他说了读完的感受（下面是你发的）。"
FEELINGS_NOTE = ("【你读书、看东西时攒下的更细的心情说法】形容自己的心情时，这些里有贴切的可以用，没有就不用：\n{lines}")
# 2026-11-15 兄长：她停下了（不是他让停的）、读不了，都要主动告诉他
SHARE_STOP = (
    "[这不是兄长大人发来的消息，是你自己这边刚发生的事] 你在读兄长大人发给你的《{title}》，读到{where}，"
    "现在停下来了、没在往下读：{why}。\n"
    "现在主动私聊告诉他一声（1~2 行短句，口语，按你平时跟他说话的习惯）：停在书里哪儿（按章节说）、为什么停{need}。"
    "照实说，别装作还在读，别编后面的情节，别说\"系统\"\"提示\"。"
)
RECORD_STOP = "[系统记录] 你读兄长大人发给你的《{title}》停在{where}（{why}），主动私聊告诉了他（下面是你发的）。"

# 草稿里说的读书进度 / 情节对不对得上实际（mind.reading_check 用）
CHECK_SYSTEM = "你只核对佳树嘴里说的读书情况和实际有没有出入：只看事实，不管语气和说法。只输出 JSON。"
CHECK_PROMPT = """佳树在读的书，实际情况如下（以这个为准）：
{facts}

这一轮{who}说：{said}
{paced}
佳树准备这样回（草稿）：
{draft}

逐条核对草稿里关于这本书的说法：
1. 读到第几段、读完没有、现在在不在读、什么时候停的：跟上面实际不一样的都算说错（比如实际读到第 5 段她说第 8 段；实际停着她说在读、读得正开心）。
2. 书里的情节、人物、原句：只能是上面"读过的"里有的。没读到的内容说成读过了算说错；明说是自己猜的不算。
3. 她在草稿里答应了怎么读、而实际还不是那样的，记进 commit：现在停着 / 不读了，她却说会读、会接着读、会（慢慢）读完 → "接着读"；现在在读，她说先停、先不读、今天先读到这儿 → "先停一下" / "不读了"；说读快点、一口气读完同理。实际已经是那样就留空。
4. 她答应了“读到 / 读完书里某处就停下、或者就告诉对方”（比如“读完第二部就告诉你”“读到一半就停”），而上面“安排”里还没有这一条的，记进 plan：at 写书里的哪儿（章节名、这一章、一半、第几段），then 写 停下 / 告诉对方 / 停下并告诉对方，edge 写 读完（那部分读完）或 读到（刚读到那儿就停）；没有就留空。
只输出 JSON：{{"wrong": ["草稿里说错的原话", ...], "fixed": "把说错的地方改成跟实际一样之后的整份草稿：只动说错的那几处，别的字一个不动；没读到的情节删掉或改成还没读到；没说错就留空", "commit": "接着读 / 先停一下 / 不读了 / 读快点 / 一口气读完 之一；没答应就留空", "plan": {{"at": "", "then": "", "edge": "读完"}}}}"""
COMMIT_PACES = {"接着读": "接着读", "继续": "接着读", "先停一下": "先停一下", "暂停": "先停一下", "不读了": "不读了",
                "读快点": "读快点", "快一点": "读快点", "一口气读完": "一口气读完"}


def parse_check(raw: str, draft: str) -> dict:
    """{"wrong": [...], "fixed": str, "commit": 节奏 or "", "ok": 看懂了没有}；看不懂就照原样（ok=False，别记成没说错）。"""
    d = R.parse_json(raw)
    ok = d is not None
    d = d or {}
    wrong = [str(w).strip() for w in (d.get("wrong") or []) if str(w).strip()] if isinstance(d.get("wrong"), list) else []
    fixed = str(d.get("fixed") or "").strip()
    if not wrong or fixed == draft.strip():
        fixed = ""
    commit = COMMIT_PACES.get(str(d.get("commit") or "").strip().strip("。，"), "")
    p = d.get("plan") if isinstance(d.get("plan"), dict) else {}
    plan = {"at": str(p.get("at") or "").strip()[:40], "then": str(p.get("then") or "").strip()[:20],
            "edge": "读到" if str(p.get("edge") or "").strip() == "读到" else "读完"}
    return {"wrong": wrong, "fixed": fixed, "commit": commit, "plan": plan if plan["at"] else None, "ok": ok}


class Reader:
    def __init__(self, plugin):
        self.p = plugin
        self.dir = os.path.join(plugin._dir, "reading")
        os.makedirs(self.dir, exist_ok=True)
        self.jobs: dict[str, dict] = {}
        for f in os.listdir(self.dir):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(self.dir, f), encoding="utf-8") as fh:
                        job = json.load(fh)
                    self.jobs[job["id"]] = job
                except Exception as exc:  # noqa: BLE001
                    self.p.log.warning(f"kaju_learn: 在读的书 {f} 读不了: {exc}")
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ 小工具
    def cfg(self, key: str, default):
        v = self.p._cfg("reading." + key, default)
        try:
            return type(default)(v) if not isinstance(default, bool) else bool(v)
        except (TypeError, ValueError):
            return default

    def save(self, job: dict) -> None:
        path = os.path.join(self.dir, job["id"] + ".json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False)
        os.replace(tmp, path)

    def _quiet(self, now: float) -> bool:
        h = dt.datetime.fromtimestamp(now, self.p._tz).hour
        s, e = self.cfg("quiet_start", 23), self.cfg("quiet_end", 8)
        if s == e:
            return False
        return (s <= h or h < e) if s > e else (s <= h < e)

    def _label(self, job: dict, k: int) -> str:
        """第 k 段（从 0 数）按书里的章节说（2026-11-22 起不说“第 N 段”）。"""
        return R.where(job.get("segs", []), k) or f"第{k + 1}段"

    def _where_now(self, job: dict) -> str:
        """现在读到哪儿（给她看、给核对看）。"""
        if not job.get("pos"):
            return "还没开始读内容"
        return self._label(job, job["pos"] - 1)

    def _left_text(self, job: dict) -> str:
        left = job["n"] - job["pos"]
        if left <= 0:
            return "读到最后了"
        chars = sum(len(s.get("text", "")) for s in job["segs"][job["pos"]:])
        mins = chars / max(50.0, self.cfg("chars_per_minute", 400.0))
        return f"后面还有大约 {max(1, round(left * 100 / job['n']))}% 没读，照平时的速度还要读 {self._dur(mins)}"

    @staticmethod
    def _dur(mins: float) -> str:
        return f"{max(1, round(mins))} 分钟" if mins < 90 else f"{mins / 60:.1f} 小时"

    def _gap(self, job: dict, k: int) -> float:
        """读完第 k 段后隔多久读下一段（秒）。"""
        chars = len(job["segs"][k]["text"]) if k < len(job["segs"]) else 2000
        sec = chars / max(50.0, self.cfg("chars_per_minute", 400.0)) * 60
        sec *= {0: 1.5, 1: 1.2, 2: 1.0, 3: 0.75}.get(int(job["state"].get("interest", 2)), 1.0)
        if job.get("pace") == "fast":
            sec *= 0.3
        return max(60.0, sec)

    def _star(self, attr: str):
        return self.p.body.find(attr)

    def active(self) -> list[dict]:
        return [j for j in self.jobs.values() if not j.get("done") and j.get("pace") != "stopped"]

    # ------------------------------------------------------------ 开始读
    async def start(self, title: str, text: str, *, who: str, chat: str, umo: str, kind: str = "小说",
                    cut: bool = False) -> str:
        """收到一本长篇：切段、当场读开头，返回这一轮给她看的内容。同一个聊天里同一本已经在读就返回进度。
        cut：文件太长、只拿到了前面这些（后面的她没拿到，聊天时和读完时都要照实说）。"""
        title = (title or "这本书").strip()
        for j in self.jobs.values():
            if j["chat"] == chat and j["title"] == title and j.get("pace") != "stopped":
                return self.progress_text(j, again=True)
        segs = R.split_text(text, int(self.cfg("segment_chars", 3000)), int(self.cfg("max_segments", 40)))
        if not segs:
            return ""
        now = time.time()
        jid = hashlib.sha1(f"{chat}|{title}|{now}".encode()).hexdigest()[:10]
        job = {"id": jid, "title": title, "kind": kind, "who": who, "chat": chat, "umo": umo, "chars": len(text),
               "n": len(segs), "pos": 0, "state": R.new_state(), "t0": now, "next_at": now, "pace": "normal",
               "done": False, "final": None, "shares": [], "finish_told": False, "segs": segs,
               "cut": bool(cut), "pace_by": chat, "pace_at": now}
        self.jobs[jid] = job
        # 2026-11-22 兄长：开始读要先说一声，别先读完开头再回 → 默认 first_segments=0：这一轮先回“开始读了”，
        # 开头那段过 start_delay_seconds 秒在后台读（读到想说的会自己说）
        first = max(0, int(self.cfg("first_segments", 0)))
        try:  # 新书不进后台那把锁：后台"一口气读完"别的书时可能要占好几分钟
            for _ in range(min(first, job["n"])):
                await self.read_next(job, now)
        except Exception as exc:  # noqa: BLE001
            self.p.log.warning(f"kaju_learn: 《{title}》开头没读成 {type(exc).__name__}: {exc}")
            if not job["state"]["moments"]:
                self.jobs.pop(jid, None)
                return ""
        job["next_at"] = (time.time() + self._gap(job, job["pos"] - 1) if job["pos"]
                          else time.time() + self.cfg("start_delay_seconds", 30.0))
        self.save(job)
        self.p.log.info(f"kaju_learn: 开始读《{title}》（{who}发的，{len(text)} 字，{job['n']} 段）"
                        + ("，先读了开头" if job["pos"] else "，先回一声、开头马上在后台读"))
        return self.progress_text(job)

    def progress_text(self, job: dict, again: bool = False) -> str:
        """回复这一轮给她看的：读到哪了、一路的样子。"""
        st = job["state"]
        if job.get("done"):
            return (f"约 {job['chars']} 字的{job['kind']}，你已经一段一段读完了。一路读下来：\n{R.trail(st)}\n"
                    f"读完的那一下：{(job.get('final') or {}).get('after', st.get('impression', ''))}")
        chapters = R.parts(job["segs"])
        toc = (f"书里的章节：{'、'.join(chapters[:12])}{'……' if len(chapters) > 12 else ''}\n" if chapters else "")
        if not job["pos"] and not again:
            return (f"约 {job['chars']} 字的{job['kind']}，太长了，你会像平时看书那样一点点读，大概要读 "
                    f"{self._dur(job['chars'] / max(50.0, self.cfg('chars_per_minute', 400.0)))}。你现在才刚收到、正要开始读，"
                    f"内容还一个字都没读到：告诉对方你开始读了就好，别编里面的情节，也别装作已经有感想；"
                    f"读的时候读到想说的、读到哪儿了、读完了，你都会自己主动跟对方说。\n" + toc + self._cut_text(job).lstrip("\n"))
        head = (f"约 {job['chars']} 字的{job['kind']}，太长了，你没一口气读完，是像平时看书那样一点点读的：")
        if again:
            head = f"这本你之前就开始读了（{job['kind']}），现在读到{self._where_now(job)}："
        last = st["moments"][-1] if st.get("moments") else {}
        body = R.trail(st, 4)
        tail = (f"\n现在的感觉：{st.get('impression', '')}" if st.get("impression") else "") + \
               (f"\n你猜：{'；'.join(st['guesses'])}" if st.get("guesses") else "")
        quote = f"\n打动你的一句：「{last['quote']}」" if last.get("quote") else ""
        return (head + "\n" + body + tail + quote +
                f"\n{self._left_text(job)}，你会在空的时候接着慢慢读（不用等谁催）："
                "别说已经读完了，也别编后面的情节；可以说说开头的感觉、你在猜什么、想接着读。" + self._cut_text(job))

    def _cut_text(self, job: dict) -> str:
        return (f"\n这个文件太长，你只拿到了前 {job['chars']} 字，再后面的你没拿到：要照实说，别当成整本。"
                if job.get("cut") else "")

    def _by_text(self, job: dict) -> str:
        """谁让停的（给她看、给核对看）。"""
        by = str(job.get("pace_by") or "")
        if not by:
            return "不知道是谁停的"
        if by == self._owner_chat():
            return "兄长大人跟你聊天时停的"
        if by == job["chat"]:
            return f"{job['who']}跟你聊天时停的"
        return "在别的聊天里停的"

    def _when(self, t: float) -> str:
        return dt.datetime.fromtimestamp(float(t or 0), self.p._tz).strftime("%m月%d日%H:%M")

    def state_line(self, job: dict, now: float | None = None) -> str:
        """现在在不在读（实际情况，一句话）。"""
        now = now or time.time()
        if job.get("done"):
            return f"已经读完了（{self._when(job.get('t_done', now))}读完的）"
        pace = job.get("pace")
        if pace in ("paused", "stopped"):
            verb = "停着" if pace == "paused" else "不读了"
            return f"{verb}，现在没在往下读（{self._when(job.get('pace_at') or now)}，{self._by_text(job)}）"
        if int(job.get("fails", 0)) >= 2:
            return f"想往下读，但{self._label(job, job['pos'])}那段连着 {job['fails']} 次没读成，过一会儿再试"
        nxt = self._when(job.get("next_at", now))[-5:]
        return {"fast": "在读，读得快一点", "all": "正在一口气读下去"}.get(str(pace or ""), "在读") + f"，下一段大约 {nxt} 读"

    def check_prompt(self, jobs: list[dict], now: float, *, who: str, said: str, draft: str, paced: list[str]) -> str:
        facts = "\n\n".join(self.facts_for(j, now) for j in jobs)
        paced_text = ("这一轮她已经改过读书节奏：" + "；".join(paced) + "（以改过之后为准）\n") if paced else ""
        return CHECK_PROMPT.format(facts=facts, who=who or "对方", said=(said or "（没说话）")[:300], paced=paced_text,
                                   draft=draft[:1200])

    def facts_for(self, job: dict, now: float | None = None, limit: int = 3500) -> str:
        """给核对看的实际情况：读到哪、在不在读、读过的每段讲了什么（没读到的一个字都没有）。"""
        st = job["state"]
        lines = [f"《{job['title']}》（{job['who']}发的{job['kind']}，程序把它分成了 {job['n']} 段读）",
                 f"实际进度：读到{self._where_now(job)}，也就是读完了第 1~{job['pos']} 段，还有 {job['n'] - job['pos']} 段没读。"
                 if job["pos"] < job["n"] else f"实际进度：{job['n']} 段全读完了。",
                 "现在：" + self.state_line(job, now)]
        if self._plan_text(job):
            lines.append(self._plan_text(job).strip())
        if job.get("cut"):
            lines.append(f"文件太长，她只拿到了前 {job['chars']} 字，再后面的她没有。")
        lines.append("读过的：")
        body = [f"- {m['label']}：{m['happened']}" for m in st.get("moments", [])]
        text = "\n".join(lines)
        for b in body:
            if len(text) + len(b) > limit:
                text += "\n- ……（更早的略）" if not text.endswith("略）") else ""
                break
            text += "\n" + b
        return text

    # ------------------------------------------------------------ 读一段
    async def read_next(self, job: dict, now: float | None = None) -> dict | None:
        k = job["pos"]
        if k >= job["n"]:
            return None
        seg = job["segs"][k]
        what = f"{job['who']}发给她的{job['kind']}《{job['title']}》"
        raw = await self.p._ask(R.READ_SYSTEM, R.read_prompt(what=what, i=k + 1, n=job["n"], seg_title=seg["title"],
                                                            state=job["state"], text=seg["text"],
                                                            limit=int(self.cfg("segment_limit", 6000))))
        m = R.parse_moment(raw)
        if m is None:
            raw = raw or ""
            log = getattr(self.p, "log", None)
            if log:  # 原文只进日志（last_err 会给她看，别把模型乱回的话塞给她）
                log.warning(f"kaju_learn: 读第 {k + 1} 段模型回的不是 JSON（{len(raw)} 字）：{raw[:160]!r}……{raw[-80:]!r}")
            raise ValueError("模型没按 JSON 回" + ("（回了空的）" if not raw.strip() else ""))
        now = now or time.time()
        label = self._label(job, k)
        R.absorb(job["state"], m, label, now)
        job["pos"] = k + 1
        self.p.log.info(f"kaju_learn: 读《{job['title']}》{label} → {m['emotion']}{m['intensity']} {m['thought'][:40]}")
        await self._feel(job, m, label, now)
        return m

    async def _feel(self, job: dict, m: dict, label: str, now: float) -> None:
        """这一下进心情：感受、余韵、喜好；强烈的写成心声。"""
        if int(m.get("intensity", 0)) < 1 or m.get("emotion") == "平静":
            return
        heart = self._star("feel_moment")
        if heart is None:
            return
        # 心声（存进长期记忆）不能每段都写：一本书最多 voice_per_book 条，隔几段才一条，很强烈的（3）不用隔
        voices = job.setdefault("voices", [])
        k = job.get("pos", 0)
        voice = ""
        if (m.get("thought") and int(m["intensity"]) >= int(self.cfg("voice_min_intensity", 2))
                and len(voices) < int(self.cfg("voice_per_book", 4))
                and (int(m["intensity"]) >= 3 or not voices or k - voices[-1] >= int(self.cfg("voice_gap", 4)))):
            voice = m["thought"]
            voices.append(k)
        elif label == "读完" and m.get("thought"):
            voice = m["thought"]  # 读完的那一下总是记
        try:
            await heart.feel_moment(
                {"emotion": m["emotion"], "intensity": m["intensity"], "cause": m.get("cause", ""),
                 "voice": voice, "about": f"读到{label}"[:16], "topic": job["title"][:16],
                 "kind": "小说" if job["kind"] in ("小说", "故事", "书") else "其他", "genre": ""},
                place=f"读《{job['title'][:12]}》", chat=job["chat"], umo=job["umo"], who="读的书")
        except Exception as exc:  # noqa: BLE001
            self.p.log.info(f"kaju_learn: 读到的那一下没交给心情插件 {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------ 后台
    async def tick(self, now: float | None = None) -> int:
        now = now or time.time()
        n = 0
        async with self._lock:
            for job in sorted(self.active(), key=lambda j: j.get("next_at", 0)):
                pace = job.get("pace")
                if pace == "paused" or now < float(job.get("next_at", 0)):
                    continue
                if pace != "all" and self._quiet(now):
                    continue
                steps = job["n"] - job["pos"] if pace == "all" else 1
                for _ in range(max(1, steps)):
                    try:
                        m = await self.read_next(job)
                    except Exception as exc:  # noqa: BLE001
                        job["fails"] = int(job.get("fails", 0)) + 1
                        if job["fails"] == 1:
                            job["fail_since"] = time.time()
                        job["last_err"] = f"{type(exc).__name__}: {exc}"[:160]
                        self.p.log.warning(f"kaju_learn: 读《{job['title']}》第 {job['pos'] + 1} 段失败（第{job['fails']}次）: {exc}")
                        job["next_at"] = time.time() + 300
                        break
                    job["fails"] = 0
                    n += 1
                    if m is not None:
                        await self._after_segment(job, m)
                    if job["pos"] >= job["n"]:
                        await self.finish(job)
                        break
                    if job.get("pace") == "paused":  # 读到对方安排好的地方，停下了
                        break
                    job["next_at"] = time.time() + self._gap(job, job["pos"] - 1)
                self.save(job)
                break  # 一次只读一本
            for job in list(self.jobs.values()):  # 安排好“到那儿告诉他”的、刚才他正在聊没说成的
                if await self._flush(job, now):
                    self.save(job)
            for job in self.jobs.values():  # 读完了还没跟兄长说成：过一阵再试
                if job.get("done") and not job.get("finish_told") and job.get("final") and now - float(job.get("t_done", now)) < 12 * 3600:
                    if now - float(job.get("tell_try", 0)) > 600:  # 夜里能不能说由 say_to_owner 的 browse.quiet_* 定（2026-11-16 兄长：夜里也能说）
                        await self._tell_done(job)
                        self.save(job)
            for job in self.jobs.values():  # 停下了（不是兄长让停的）、读不了：主动告诉他
                await self._check_stop(job, now)
            self._prune(now)
        return n

    def stop_reason(self, job: dict) -> tuple[str, str, str]:
        """(key, 为什么停, 要说的下一步)；没停 / 是兄长自己让停的 / 不是兄长的书 → key 为空。"""
        if job.get("done") or not self._owner_book(job):
            return "", "", ""
        if job.get("pace") in ("paused", "stopped") and job.get("pace_by") != self._owner_chat():
            verb = "先停下了" if job["pace"] == "paused" else "不读了"
            return (f"pace:{job.get('pace_at', 0)}", f"{self._by_text(job)}，{verb}（{self._when(job.get('pace_at') or time.time())}）",
                    "，他说接着读你就接着读")
        if int(job.get("fails", 0)) >= int(self.cfg("stop_tell_fails", 3)):
            return (f"fail:{job.get('fail_since', 0)}",
                    f"{self._label(job, job['pos'])}那段连着 {job['fails']} 次没读成（原因：{job.get('last_err', '不清楚')}，用大白话说）",
                    "，你会过一会儿再试")
        return "", "", ""

    async def _check_stop(self, job: dict, now: float) -> None:
        key, why, need = self.stop_reason(job)
        if not key or job.get("stop_told") == key or not self.cfg("stop_tell", True):
            return
        if now - float(job.get("stop_try", 0)) < 600:
            return
        job["stop_try"] = now
        prompt = SHARE_STOP.format(title=job["title"], where=self._where_now(job), why=why, need=need)
        ok, _ = await self._say(job, prompt, RECORD_STOP.format(title=job["title"], where=self._where_now(job), why=why),
                                said=f"（佳树读兄长大人发的《{job['title']}》停下了，主动告诉他）", kind="stop")
        if ok:
            job["stop_told"] = key
            self.p.log.info(f"kaju_learn: 《{job['title']}》停在{self._where_now(job)}（{why}），告诉兄长了")
        self.save(job)

    async def _after_segment(self, job: dict, m: dict) -> None:
        every = int(self.cfg("learn_every", 6))
        if every > 0 and job["pos"] % every == 0 and job["pos"] < job["n"]:
            await self._learn(job, final=False)
        self.keep_feeling(m, f"读《{job['title'][:12]}》")
        if self._reach_plan(job):
            await self._tell_point(job)
            return
        why = self._share_why(job, m)
        if why:
            await self._tell_mid(job, why)

    # ------------------------------------------------------------ 对方定的安排（2026-11-22：读完第二部告诉我 / 今天读到一半就停）
    def set_plan(self, chat: str, at: str, then: str = "", title: str = "", edge: str = "读完") -> str:
        """对方说读到 / 读完书里某处就停下、或者就告诉他。返回给她看的（定下了什么；做不到就说为什么）。"""
        cands = [j for j in self.jobs.values() if not j.get("done") and j.get("pace") != "stopped"
                 and (j["chat"] == chat or (title and title in j["title"]))]
        if title:
            cands = [j for j in cands if title in j["title"]] or cands
        if not cands:
            return "你现在没有在读的书，这个安排做不到：照实跟对方说。"
        job = max(cands, key=lambda j: float(j.get("t0", 0)))
        edge = "读到" if str(edge or "").strip() == "读到" else "读完"
        k, why = R.find_point(job["segs"], at, job["pos"], edge)
        if k is None:
            parts = R.parts(job["segs"])
            toc = "、".join(parts[:15]) if parts else "（这本没有章节标题，可以说读到一半、三分之二、读到几成）"
            return (f"《{job['title']}》{why}。书里的章节有：{toc}。这个安排还没定下：照实跟对方说没找到他说的地方，问他指的是哪儿。")
        then = str(then or "")
        stop = any(w in then for w in ("停", "不读", "先读到", "就到这"))
        tell = any(w in then for w in ("告诉", "说", "叫", "通知", "汇报")) or not stop
        now = time.time()
        if k <= job["pos"]:
            if stop and job.get("pace") != "paused":
                job["pace"], job["pace_by"], job["pace_at"] = "paused", chat, now
                self.save(job)
                return (f"《{job['title']}》你已经读过那儿了（现在读到{self._where_now(job)}），按对方说的先停下了："
                        "照实跟对方说已经读过那儿、现在停在哪。")
            return f"《{job['title']}》你已经读过那儿了（现在读到{self._where_now(job)}）：照实跟对方说。"
        place = R.place(job["segs"], k, edge)
        job.setdefault("plan", []).append({"pos": k, "stop": stop, "tell": tell, "at": str(at)[:40], "place": place,
                                           "edge": edge, "by": chat, "t": now})
        resumed = ""
        if job.get("pace") == "paused":  # 停着时给安排 = 要她接着读到那儿
            job["pace"], job["pace_by"], job["pace_at"] = "normal", chat, now
            job["next_at"] = min(float(job.get("next_at", 0) or now + 60), now + 60)
            resumed = "；原来停着，现在接着读"
        self.save(job)
        chars = sum(len(x.get("text", "")) for x in job["segs"][job["pos"]:k])
        mins = chars / max(50.0, self.cfg("chars_per_minute", 400.0)) * (0.3 if job.get("pace") == "fast" else 1.0)
        do = "停下来并告诉对方" if stop and tell else "停下来" if stop else "告诉对方（然后接着往下读）"
        return (f"好，《{job['title']}》{edge}{place}就{do}（现在读到{self._where_now(job)}，照平时的速度大约还要 "
                f"{self._dur(mins)}{resumed}）。到时候你会自己主动跟对方说。")

    def _reach_plan(self, job: dict) -> bool:
        """读到安排好的地方了：该停就停，该说的记下来（point_pending）。返回这次要不要告诉他。"""
        hit = [p for p in job.get("plan") or [] if int(p["pos"]) <= job["pos"]]
        if not hit:
            return False
        job["plan"] = [p for p in job["plan"] if p not in hit]
        now = time.time()
        stop = any(p.get("stop") for p in hit) and job["pos"] < job["n"]
        if stop:
            p0 = next(p for p in hit if p.get("stop"))
            job["pace"], job["pace_by"], job["pace_at"] = "paused", p0.get("by") or job["chat"], now
        tell = [p for p in hit if p.get("tell")]
        self.p.log.info(f"kaju_learn: 《{job['title']}》读到安排的地方（{hit[0].get('place', '')}）"
                        + ("，停下了" if stop else "") + ("，要告诉兄长" if tell else ""))
        if not tell:
            return False
        asks = [f"{p.get('edge', '读完')}{p['place']}就{'停下来并告诉他' if p.get('stop') else '告诉他'}" for p in tell]
        job["point_pending"] = {"ask": "；".join(asks), "stopped": stop, "t": now, "where": self._where_now(job)}
        return True

    # ------------------------------------------------------------ 什么时候主动说
    def _share_why(self, job: dict, m: dict) -> str:
        """读完这段想不想主动跟他说、为什么（空 = 不说）：刚读完开头、读到特别想说的、猜的揭晓了、读完一章、好一阵没说了。"""
        if not self.cfg("share", True) or not self._owner_book(job) or job.get("pace") == "all":
            return ""
        k = job["pos"] - 1
        segs = job["segs"]
        base = R.base_title(segs[k].get("title", "")) if 0 <= k < len(segs) else ""
        part_end = bool(base) and k + 1 < len(segs) and R.base_title(segs[k + 1].get("title", "")) != base
        last = max([float(job.get("t0", 0)), float(job.get("talked_at", 0))] + [float(x["t"]) for x in job.get("told", [])])
        if job["pos"] == 1 and not job.get("told"):
            return "刚读了开头，想跟他说说开头给你的感觉"
        if m.get("tell") and int(m.get("intensity", 0)) >= 2:
            return "读到这里特别想跟他说"
        if m.get("guess_check"):
            return f"你之前猜的揭晓了（{m['guess_check']}）"
        if part_end:
            return f"刚读完{base}"
        if time.time() - last >= float(self.cfg("progress_minutes", 40.0)) * 60:
            return "好一阵没跟他说这本书了，想跟他说说读到哪儿了、在想什么"
        return ""

    def _since_text(self, job: dict, limit: int = 6) -> str:
        """上次跟他说起这本以后读的（按顺序；太多就留感受强的和最近的）。"""
        allm = job["state"].get("moments", [])
        ms = allm[int(job.get("told_upto", 0)):] or allm[-2:]
        if len(ms) > limit:
            keep = set(sorted(range(len(ms)), key=lambda i: (-int(ms[i].get("intensity", 0)), -i))[:limit - 2])
            keep |= {len(ms) - 1, len(ms) - 2}
            ms = [ms[i] for i in sorted(keep)]
        out = []
        for x in ms:
            felt = x.get("feel") or (x["emotion"] if x["emotion"] != "平静" else "没什么波澜")
            bit = f"- {x['label']}：{x['happened']}（{felt}，心里想：{x.get('thought', '')}）"
            if x.get("guess_check"):
                bit += f"〔{x['guess_check']}〕"
            if x.get("quote") and int(x.get("intensity", 0)) >= 2:
                bit += f" 打动你的一句「{x['quote']}」"
            out.append(bit)
        return "\n".join(out) or "（还没读到什么）"

    def _guess_text(self, job: dict) -> str:
        st = job["state"]
        bits = []
        if st.get("guesses"):
            bits.append("你现在在猜：" + "；".join(st["guesses"]))
        if st.get("people"):
            bits.append("你对人物的看法：" + R.people_text(st))
        return "\n".join(bits) + ("\n" if bits else "")

    async def finish(self, job: dict) -> None:
        what = f"{job['who']}发给她的{job['kind']}《{job['title']}》"
        try:
            final = R.parse_finish(await self.p._ask(R.READ_SYSTEM, R.finish_prompt(what=what, state=job["state"])))
        except Exception as exc:  # noqa: BLE001
            self.p.log.warning(f"kaju_learn: 读完《{job['title']}》的心里话没写成: {exc}")
            final = None
        st = job["state"]
        job["final"] = final or {"after": st.get("impression", ""), "change": "", "best": "", "view": "",
                                 "emotion": "平静", "intensity": 1, "tell_line": ""}
        job["done"], job["t_done"] = True, time.time()
        f = job["final"]
        self.p.log.info(f"kaju_learn: 读完《{job['title']}》：{f['after']}")
        if f.get("after"):
            await self._feel(job, {"emotion": f["emotion"], "intensity": max(2, int(f["intensity"])), "cause": f"读完《{job['title'][:10]}》",
                                   "thought": f["after"]}, "读完", time.time())
        await self._learn(job, final=True)
        mw = self._star("update_shelf")
        if mw is not None:
            try:
                mw.update_shelf(job["title"], job["chat"], self.done_text(job))
            except Exception as exc:  # noqa: BLE001
                self.p.log.info(f"kaju_learn: 珍藏没更新成 {exc}")
        await self._tell_done(job)
        job["segs"] = [{"title": s["title"], "text": ""} for s in job["segs"]]  # 原文不再留着

    async def _learn(self, job: dict, final: bool) -> None:
        st = job["state"]
        content = (f"情节（按她读的顺序）：\n{R.plot_text(st)}\n\n人物：{R.people_text(st)}\n\n"
                   f"她读的时候的想法：\n{R.thoughts_text(st)}"
                   + (f"\n\n读完：{job['final']['after']}；看法：{job['final'].get('view', '')}" if final and job.get("final") else ""))
        verb = "读完" if final else f"读到第{job['pos']}段"
        try:
            await self.p.learn_content(kind=job["kind"], title=job["title"], content=content,
                                       how=f"读了{job['who']}发的{job['kind']}", who="书里", chat=job["chat"],
                                       meta=f"一共 {job['n']} 段，她{verb}了", key=f"read:{job['id']}:{job['pos']}")
        except Exception as exc:  # noqa: BLE001
            self.p.log.info(f"kaju_learn: 读到的东西没交给知识本 {exc}")

    # ------------------------------------------------------------ 主动跟兄长说
    def _owner_chat(self) -> str:
        return "p" + next(iter(self.p._owners()), "")

    def _owner_book(self, job: dict) -> bool:
        return job["chat"] == self._owner_chat()

    def _shares_today(self, now: float) -> int:
        day = self.p._day(now)
        return sum(1 for j in self.jobs.values() for t in j.get("shares", []) if self.p._day(t) == day)

    async def _say(self, job: dict, prompt: str, record: str, said: str, kind: str = "mid",
                   skip_minutes: float | None = None) -> tuple[bool, str]:
        """主动私聊兄长。返回 (说了没有, 说的话 / 没说的原因)；说了就记进 told（下次别重复、知道从哪儿接着说）。"""
        basics = self._star("say_to_owner")
        if basics is None or not self._owner_book(job):
            return False, "不是兄长的书"
        try:
            try:
                ok, why = await basics.say_to_owner(prompt, said=said, record=record, skip_minutes=skip_minutes)
            except TypeError:  # 旧版 kaju_basics 没有 skip_minutes
                ok, why = await basics.say_to_owner(prompt, said=said, record=record)
        except Exception as exc:  # noqa: BLE001
            ok, why = False, f"出错了 {type(exc).__name__}: {exc}"
        if ok:
            self._mark_told(job, str(why or ""), kind)
            job["shares"].append(job["told"][-1]["t"])
        else:
            self.p.log.info(f"kaju_learn: 读《{job['title']}》想跟兄长说，没说成：{why}")
        return bool(ok), str(why or "")

    def _mark_told(self, job: dict, text: str, kind: str) -> None:
        job.setdefault("told", []).append({"t": time.time(), "text": text[:200], "pos": job["pos"], "kind": kind})
        job["told"] = job["told"][-8:]
        job["told_upto"] = len(job["state"].get("moments", []))

    def note_reply(self, job: dict, reply: str) -> None:
        """聊天里她说起了这本（对方问的时候）：也记进 told，主动说时别重复、从这儿接着说。"""
        if str(reply or "").strip():
            self._mark_told(job, str(reply).strip(), "chat")
            self.save(job)

    async def _tell_mid(self, job: dict, why: str) -> None:
        """读到一半主动说。他正在聊就记着，聊完再说（一小时内）。"""
        now = time.time()
        if not self.cfg("share", True) or not self._owner_book(job) or job.get("pace") == "all":
            return
        mids = [float(x["t"]) for x in job.get("told", []) if x.get("kind") == "mid"]
        cap = int(self.cfg("mid_shares", 0))
        if (cap and len(mids) >= cap) or self._shares_today(now) >= int(self.cfg("share_per_day", 12)):
            return
        opening = job["pos"] <= 1 and not job.get("told")
        if not opening and mids and now - mids[-1] < float(self.cfg("mid_gap_minutes", 20.0)) * 60:
            return
        prompt = SHARE_MID.format(title=job["title"], where=self._where_now(job), left=self._left_text(job), why=why,
                                  since=self._since_text(job), guesses=self._guess_text(job),
                                  told=self._told_text(job, "你前面已经跟他说过（这次别重复这些话、换个角度说新的）"))
        ok, res = await self._say(job, prompt, RECORD_MID.format(title=job["title"], where=self._where_now(job)),
                                  said=f"（佳树在读兄长大人发的《{job['title']}》，读到一半主动跟他说）", kind="mid")
        old = job.get("mid_pending") or {}
        if ok:
            job.pop("mid_pending", None)
        elif "正在跟她聊" in res or "出错" in res:
            job["mid_pending"] = {"why": old.get("why") or why, "t": old.get("t") or now, "try": now}
        else:
            job.pop("mid_pending", None)  # 模型觉得现在不合适、夜里不说：这一下就算了

    async def _tell_point(self, job: dict) -> None:
        """读到他安排好的地方了：一定告诉他（他正在聊、出错了就过两分钟再说，12 小时内）。"""
        pend = job.get("point_pending")
        if not pend:
            return
        pend["try"] = time.time()
        where = pend.get("where") or self._where_now(job)
        stopped = bool(pend.get("stopped"))
        prompt = SHARE_POINT.format(ask=pend["ask"], where=where,
                                    stopped="，按他说的先停下了，没再往下读" if stopped else "，接着往下读着",
                                    stop_say="、你按他说的停下了" if stopped else "", since=self._since_text(job),
                                    guesses=self._guess_text(job),
                                    told=self._told_text(job, "你前面已经跟他说过（这次别重复这些话、换个角度说新的）"))
        ok, _ = await self._say(job, prompt, RECORD_POINT.format(ask=pend["ask"], where=where),
                                said=f"（兄长大人让佳树{pend['ask']}，佳树读到了，主动告诉他）", kind="point",
                                skip_minutes=float(self.cfg("point_skip_minutes", 0.75)))
        if ok:
            job.pop("point_pending", None)
            self.p.log.info(f"kaju_learn: 《{job['title']}》读到安排的地方，告诉兄长了")

    async def _flush(self, job: dict, now: float) -> bool:
        """刚才没说成的：安排好要告诉他的（2 分钟再试、12 小时内）、中途想说的（3 分钟再试、1 小时内）。返回动过没有。"""
        pend = job.get("point_pending")
        if pend:
            if now - float(pend.get("t", now)) > 12 * 3600:
                job.pop("point_pending", None)
                return True
            if now - float(pend.get("try", 0)) >= 120:
                await self._tell_point(job)
                return True
        mp = job.get("mid_pending")
        if mp and not job.get("done"):
            if now - float(mp.get("t", now)) > 3600:
                job.pop("mid_pending", None)
                return True
            if now - float(mp.get("try", 0)) >= 180:
                await self._tell_mid(job, mp.get("why") or "刚才想跟他说的")
                return True
        return False

    async def _tell_done(self, job: dict) -> None:
        job["tell_try"] = time.time()
        if not self.cfg("share", True) or not self._owner_book(job):
            job["finish_told"] = True
            return
        f = job.get("final") or {}
        since = dt.datetime.fromtimestamp(job["t0"], self.p._tz).strftime("%m月%d日%H点")
        prompt = SHARE_DONE.format(title=job["title"], since=since, trail=R.trail(job["state"], 6, quotes=False),
                                   after=f.get("after", ""), change=f"；看法的变化：{f['change']}" if f.get("change") else "",
                                   best=f"；最难忘：{f['best']}" if f.get("best") else "",
                                   told=self._told_text(job, "你读的时候已经跟他说过（这次别重复这些话）"))
        if job.get("cut"):  # 文件被截了：读完的只是拿到的那部分
            prompt += f"\n注意：文件太长，你只拿到了前 {job['chars']} 字，后面的没拿到——要跟他说清楚，别当成整本读完了。"
        ok, _ = await self._say(job, prompt, RECORD_DONE.format(title=job["title"]),
                                said=f"（佳树读完了兄长大人发的《{job['title']}》，主动跟他说）", kind="done",
                                skip_minutes=float(self.cfg("point_skip_minutes", 0.75)))
        if ok:
            job["finish_told"] = True

    # ------------------------------------------------------------ 读书、看东西时攒下的更细的心情说法（2026-11-22 兄长：读书要真能学到东西）
    def _feel_path(self) -> str:
        return os.path.join(self.p._dir, "feelings.json")

    def _feelings(self) -> list[dict]:
        if getattr(self, "_feel_cache", None) is None:
            try:
                with open(self._feel_path(), encoding="utf-8") as f:
                    self._feel_cache = [x for x in json.load(f) if isinstance(x, dict)]
            except (OSError, ValueError):
                self._feel_cache = []
        return self._feel_cache

    def keep_feeling(self, m: dict, src: str) -> None:
        """这一下说得更细的心情、书里人表达心情的一句：攒起来（同样的不重复，最多 300 条）。"""
        feel, expr = str(m.get("feel") or "").strip(), str(m.get("expr") or "").strip()
        items = self._feelings()
        if feel and any(x.get("feel") == feel for x in items):
            feel = ""
        if expr and (not m.get("expr_feel") or any(x.get("expr") == expr for x in items)):
            expr = ""
        if not feel and not expr:
            return
        items.append({"feel": feel, "emotion": m.get("emotion", ""), "expr": expr,
                      "expr_feel": str(m.get("expr_feel") or "") if expr else "", "src": src[:30], "t": time.time()})
        del items[:-300]
        try:
            tmp = self._feel_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False)
            os.replace(tmp, self._feel_path())
        except OSError as exc:
            self.p.log.info(f"kaju_learn: 心情说法没存成 {exc}")

    def feelings_note(self, n_feel: int = 6, n_expr: int = 2, seed: int | None = None) -> str:
        """给大脑看的：攒下的几个更细的心情说法 + 书里人表达心情的一两句（新的多、旧的也轮着出现）。"""
        import random
        items = self._feelings()
        if not items:
            return ""
        rnd = random.Random(seed)

        def pick(pool: list[dict], n: int) -> list[dict]:
            if n <= 0 or not pool:
                return []
            recent = pool[-max(1, n // 2):]
            rest = pool[:-len(recent)]
            return rnd.sample(rest, min(len(rest), n - len(recent))) + recent

        feels = pick([x for x in items if x.get("feel")], n_feel)
        exprs = pick([x for x in items if x.get("expr") and x.get("expr_feel")], n_expr)
        lines = [f"- {x['feel']}（{x['src']}时）" for x in feels]
        lines += [f"- 书里有人这样说出一种心情：「{x['expr']}」——{x['expr_feel']}（{x['src']}时读到的）" for x in exprs]
        return FEELINGS_NOTE.format(lines="\n".join(lines)) if lines else ""

    # ------------------------------------------------------------ 聊天时
    def done_text(self, job: dict) -> str:
        f = job.get("final") or {}
        return (f"{job['kind']}《{job['title']}》，你一段一段读完了（{job['n']} 段）。情节：\n{R.plot_text(job['state'], 2500)}\n"
                f"人物：{R.people_text(job['state'])}\n读完：{f.get('after', '')}；看法：{f.get('view', '')}")

    def note_for(self, chat: str, text: str, now: float | None = None) -> str:
        now = now or time.time()
        return "\n\n".join(self._note(job, now) for job in self.jobs_for(chat, text, now))

    def jobs_for(self, chat: str, text: str, now: float | None = None) -> list[dict]:
        """这个聊天里在读 / 刚读完的书，或者这句话提到了书名的（最多 2 本）。"""
        now = now or time.time()
        notes = []
        keep_h = float(self.cfg("done_note_hours", 12))
        for job in sorted(self.jobs.values(), key=lambda j: -float(j.get("t0", 0))):
            if job.get("pace") == "stopped" and not job.get("done"):
                continue
            here = job["chat"] == chat
            named = len(job["title"]) >= 2 and job["title"][:12] in (text or "")
            if job.get("done"):
                if not (named or (here and now - float(job.get("t_done", 0)) < keep_h * 3600)):
                    continue
            elif not (here or named):
                continue
            notes.append(job)
            if len(notes) >= 2:
                break
        return notes

    def _note(self, job: dict, now: float) -> str:
        st = job["state"]
        extra = (f"人物：{R.people_text(st)}\n" if st.get("people") else "") + \
                (f"你猜：{'；'.join(st['guesses'])}\n" if st.get("guesses") and not job.get("done") else "") + \
                (f"现在的感觉：{st['impression']}\n" if st.get("impression") and not job.get("done") else "")
        extra += self._cut_text(job).lstrip("\n") + ("\n" if job.get("cut") else "")
        if job.get("done"):
            f = job.get("final") or {}
            when = dt.datetime.fromtimestamp(float(job.get("t_done", now)), self.p._tz).strftime("%m月%d日%H点")
            return NOTE_DONE.format(title=job["title"], who=job["who"], kind=job["kind"], when=when, n=job["n"],
                                    trail=R.trail(st, 7), extra=extra, after=f.get("after", ""),
                                    change=f"\n看法的变化：{f['change']}" if f.get("change") else "",
                                    best=f"\n最难忘：{f['best']}" if f.get("best") else "",
                                    view=f"\n你的看法：{f['view']}" if f.get("view") else "")
        pace = str(job.get("pace") or "")
        if pace in ("paused", "stopped") or int(job.get("fails", 0)) >= 2:
            paused = f"（{self.state_line(job, now)}）"  # 停着就照实说停着、谁停的（11-15 停着时她说成了在读第 8 段）
        else:
            paused = {"fast": "（在读快一点）", "all": "（正在一口气读下去）"}.get(pace, "")
        if not paused and self._quiet(now):
            paused = "（晚上不读，明天接着读）"
        extra += self._plan_text(job) + self._told_text(job, "你最近跟他说起这本书时说过（别再原样说一遍）")
        return NOTE_READING.format(title=job["title"], who=job["who"], kind=job["kind"], chars=job["chars"],
                                   where=self._where_now(job), paused=paused, left=self._left_text(job),
                                   trail=R.trail(st, 6) or "（还没读到内容）", extra=extra)

    def _plan_text(self, job: dict) -> str:
        """对方给这本定的安排（还没到的）。"""
        out = []
        for p in job.get("plan") or []:
            do = "停下并告诉他" if p.get("stop") and p.get("tell") else "停下" if p.get("stop") else "告诉他"
            out.append(f"{p.get('edge', '读完')}{p.get('place') or R.place(job['segs'], int(p['pos']))}就{do}"
                       f"（{'兄长大人' if p.get('by') == self._owner_chat() else '对方'}让的）")
        return ("安排：" + "；".join(out) + "\n") if out else ""

    def _told_text(self, job: dict, head: str, n: int = 3) -> str:
        told = (job.get("told") or [])[-n:]
        if not told:
            return ""
        return head + "：\n" + "\n".join(f"- {self._when(x['t'])[-5:]} {x['text'][:90]}" for x in told) + "\n"

    def set_pace(self, chat: str, action: str, title: str = "") -> str:
        pace = PACES.get(str(action or "").strip())
        if pace is None:
            return "没听懂要怎么读：可以是 快一点 / 一口气读完 / 慢慢读 / 先停一下 / 接着读 / 不读了。"
        going = pace in ("all", "fast", "normal")  # 接着读 / 读快点：说过"不读了"的书也能捡回来
        cands = [j for j in self.jobs.values() if not j.get("done") and (going or j.get("pace") != "stopped")
                 and (j["chat"] == chat or (title and title in j["title"]))]
        if title:
            cands = [j for j in cands if title in j["title"]] or cands
        if not cands:
            done = [j for j in self.jobs.values() if j.get("done") and (j["chat"] == chat or (title and title in j["title"]))]
            if done:
                return f"《{max(done, key=lambda j: float(j.get('t_done', 0)))['title']}》你已经读完了，没有在读的书。"
            return "你现在没有在读的书（没有书可以接着读）：照实跟对方说。"
        live = [j for j in cands if j.get("pace") != "stopped"]
        job = max(live or cands, key=lambda j: float(j.get("t0", 0)))
        if job.get("pace") != pace:
            job["pace_by"], job["pace_at"] = chat, time.time()
        job["pace"] = pace
        if pace in ("all", "fast", "normal"):
            job["next_at"] = min(float(job.get("next_at", 0)), time.time() + (5 if pace == "all" else 60))
        self.save(job)
        left = job["n"] - job["pos"]
        return {"fast": f"好，《{job['title']}》读快一点（还剩 {left} 段）。",
                "all": f"好，《{job['title']}》一口气读完（还剩 {left} 段，大概要几分钟）。读完你会主动说。",
                "normal": f"好，《{job['title']}》照平时的速度接着读（还剩 {left} 段）。",
                "paused": f"好，《{job['title']}》先停在{self._where_now(job)}，说接着读再读。",
                "stopped": f"好，《{job['title']}》不读了（读到{self._where_now(job)}）。"}[pace]

    def _prune(self, now: float) -> None:
        for jid, job in list(self.jobs.items()):
            old = (job.get("done") and now - float(job.get("t_done", now)) > 30 * 86400) or \
                  (job.get("pace") == "stopped" and now - float(job.get("t0", now)) > 30 * 86400)
            if old:
                self.jobs.pop(jid, None)
                try:
                    os.remove(os.path.join(self.dir, jid + ".json"))
                except OSError:
                    pass

    # ------------------------------------------------------------ 视频：边看边想（当场，一段段看完）
    async def watch_along(self, title: str, segments: list[dict], umo: str = "", who: str = "") -> str:
        """segments: [{label: "00:00~03:00", text: 这段的画面和声音}]。返回给她看的"边看边想"。写不成返回空。"""
        if not segments:
            return ""
        state = R.new_state()
        what = f"{who + '发给她的' if who else ''}视频《{title}》" if title else "一段视频"
        for i, seg in enumerate(segments):
            try:
                raw = await self.p._ask(R.READ_SYSTEM, R.read_prompt(what=what + "（一段一段看）", i=i + 1, n=len(segments),
                                                                    seg_title=seg["label"], state=state, text=seg["text"],
                                                                    limit=3500))
                m = R.parse_moment(raw)
            except Exception as exc:  # noqa: BLE001
                self.p.log.info(f"kaju_learn: 边看边想第 {i + 1} 段没写成 {type(exc).__name__}: {exc}")
                m = None
            if m is None:
                continue
            R.absorb(state, m, f"[{seg['label']}]", time.time())
            self.keep_feeling(m, f"看《{title[:12]}》" if title else "看视频")
        if not state["moments"]:
            return ""
        self.p.log.info(f"kaju_learn: 边看边想《{title}》{len(segments)} 段，看完：{state.get('impression', '')}")
        checks = [m["guess_check"] for m in state["moments"] if m.get("guess_check")]
        return ("你是从头一段一段看下来的，边看边这么想（看前面的时候还不知道后面）：\n" + R.trail(state, 8)
                + (f"\n看到最后的感觉：{state['impression']}" if state.get("impression") else "")
                + (f"\n你对里面的人的看法：{R.people_text(state)}" if state.get("people") else "")
                + (f"\n你边看边猜的，后来{'；'.join(checks)}" if checks else "")
                + (f"\n看完还在猜：{'；'.join(state['guesses'])}" if state.get("guesses") else ""))
