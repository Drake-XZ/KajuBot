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
    "【你正在读的】《{title}》（{who}发给你的{kind}，约 {chars} 字，分成 {n} 段），你在按自己的速度慢慢读，"
    "现在读到第 {pos}/{n} 段{label}{paused}。前面的你都知道，后面发生什么你还不知道：别编后面的情节，也别说已经读完了；"
    "对方要剧透就看你想不想听。\n一路读下来：\n{trail}\n{extra}"
    "对方问起就说读到哪了、心里怎么想；对方让你读快点、一口气读完、先停一下、接着读、不读了，用 reading_pace。"
)
NOTE_DONE = (
    "【你刚读完的】《{title}》（{who}发给你的{kind}），{when}读完的，一共 {n} 段。一路读下来：\n{trail}\n{extra}"
    "读完的那一下：{after}" + "{change}{best}{view}" + "\n聊到了就自然说，别从头复述。"
)
SHARE_MID = (
    "[这不是兄长大人发来的消息，是你自己这边刚发生的事] 你在慢慢读兄长大人发给你的《{title}》，刚读到第 {pos}/{n} 段{label}。\n"
    "这一段讲了：{happened}\n你读到这里{emotion}（{cause}），心里想：{thought}{quote}\n"
    "现在你忍不住主动私聊他，像读到一半跟他说那样说一两句（1~2 行短句，口语，按你平时跟他说话的习惯）："
    "哪里戳到你、你在担心或猜什么，可以问他一句（他可能读过，别让他剧透后面的）。别复述整段，别说\"系统\"\"提示\"。\n"
    "如果从最近的聊天看现在不适合主动找他（他刚说在忙、要睡了，或者你们在闹别扭），只输出 [SKIP]。"
)
SHARE_DONE = (
    "[这不是兄长大人发来的消息，是你自己这边刚发生的事] 你刚把兄长大人发给你的《{title}》读完了（{n} 段，{since}开始读的）。\n"
    "一路读下来：\n{trail}\n读完的那一下：{after}{change}{best}\n"
    "现在你主动私聊他说一两句（1~2 行短句，口语，按你平时跟他说话的习惯）：读完的感受、最放不下的，可以问他读的时候怎么想。"
    "别复述情节，别说\"系统\"\"提示\"。如果从最近的聊天看现在不适合主动找他，只输出 [SKIP]。"
)
RECORD_MID = "[系统记录] 你在慢慢读兄长大人发给你的《{title}》，读到第 {pos} 段时忍不住主动私聊了他（下面是你发的）。"
RECORD_DONE = "[系统记录] 你把兄长大人发给你的《{title}》读完了，主动私聊他说了读完的感受（下面是你发的）。"
# 2026-11-15 兄长：她停下了（不是他让停的）、读不了，都要主动告诉他
SHARE_STOP = (
    "[这不是兄长大人发来的消息，是你自己这边刚发生的事] 你在读兄长大人发给你的《{title}》，读到第 {pos}/{n} 段，"
    "现在停下来了、没在往下读：{why}。\n"
    "现在主动私聊告诉他一声（1~2 行短句，口语，按你平时跟他说话的习惯）：停在第几段、为什么停{need}。"
    "照实说，别装作还在读，别编后面的情节，别说\"系统\"\"提示\"。"
)
RECORD_STOP = "[系统记录] 你读兄长大人发给你的《{title}》停在第 {pos} 段（{why}），主动私聊告诉了他（下面是你发的）。"

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
3. 她在草稿里答应了怎么读、而实际还不是那样的，记进 commit：现在停着 / 不读了，她却说会读、会接着读、会（慢慢）读完 → "接着读"；现在在读，她说先停、先不读 → "先停一下" / "不读了"；说读快点、一口气读完同理。实际已经是那样就留空。
只输出 JSON：{{"wrong": ["草稿里说错的原话", ...], "fixed": "把说错的地方改成跟实际一样之后的整份草稿：只动说错的那几处，别的字一个不动；没读到的情节删掉或改成还没读到；没说错就留空", "commit": "接着读 / 先停一下 / 不读了 / 读快点 / 一口气读完 之一；没答应就留空"}}"""
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
    return {"wrong": wrong, "fixed": fixed, "commit": commit, "ok": ok}


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
        t = job["segs"][k]["title"] if k < len(job.get("segs", [])) else ""
        return f"第{k + 1}段" + (f"（{t}）" if t else "")

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
        first = max(1, int(self.cfg("first_segments", 1)))
        try:  # 新书不进后台那把锁：后台"一口气读完"别的书时可能要占好几分钟
            for _ in range(min(first, job["n"])):
                await self.read_next(job, now)
        except Exception as exc:  # noqa: BLE001
            self.p.log.warning(f"kaju_learn: 《{title}》开头没读成 {type(exc).__name__}: {exc}")
            if not job["state"]["moments"]:
                self.jobs.pop(jid, None)
                return ""
        job["next_at"] = time.time() + self._gap(job, max(0, job["pos"] - 1))
        self.save(job)
        self.p.log.info(f"kaju_learn: 开始读《{title}》（{who}发的，{len(text)} 字，{job['n']} 段），先读了开头")
        return self.progress_text(job)

    def progress_text(self, job: dict, again: bool = False) -> str:
        """回复这一轮给她看的：读到哪了、一路的样子。"""
        st = job["state"]
        if job.get("done"):
            return (f"约 {job['chars']} 字的{job['kind']}，你已经一段一段读完了。一路读下来：\n{R.trail(st)}\n"
                    f"读完的那一下：{(job.get('final') or {}).get('after', st.get('impression', ''))}")
        head = (f"约 {job['chars']} 字的{job['kind']}（分成 {job['n']} 段），太长了，你没一口气读完，是像平时看书那样"
                f"一段一段读的：")
        if again:
            head = f"这本你之前就开始读了（{job['kind']}，{job['n']} 段），现在读到第 {job['pos']} 段："
        last = st["moments"][-1] if st.get("moments") else {}
        body = R.trail(st, 4)
        tail = (f"\n现在的感觉：{st.get('impression', '')}" if st.get("impression") else "") + \
               (f"\n你猜：{'；'.join(st['guesses'])}" if st.get("guesses") else "")
        quote = f"\n打动你的一句：「{last['quote']}」" if last.get("quote") else ""
        return (head + "\n" + body + tail + quote +
                f"\n后面还有 {job['n'] - job['pos']} 段没读，你会在空的时候接着慢慢读（不用等谁催）："
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
            return f"想往下读，但第 {job['pos'] + 1} 段连着 {job['fails']} 次没读成，过一会儿再试"
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
        lines = [f"《{job['title']}》（{job['who']}发的{job['kind']}，共 {job['n']} 段）",
                 f"实际进度：读完了第 1~{job['pos']} 段，还有 {job['n'] - job['pos']} 段没读。" if job["pos"] < job["n"]
                 else f"实际进度：{job['n']} 段全读完了。",
                 "现在：" + self.state_line(job, now)]
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
                    job["next_at"] = time.time() + self._gap(job, job["pos"] - 1)
                self.save(job)
                break  # 一次只读一本
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
                    f"第 {job['pos'] + 1} 段连着 {job['fails']} 次没读成（原因：{job.get('last_err', '不清楚')}，用大白话说）",
                    "，你会过一会儿再试")
        return "", "", ""

    async def _check_stop(self, job: dict, now: float) -> None:
        key, why, need = self.stop_reason(job)
        if not key or job.get("stop_told") == key or not self.cfg("stop_tell", True):
            return
        if now - float(job.get("stop_try", 0)) < 600:
            return
        job["stop_try"] = now
        prompt = SHARE_STOP.format(title=job["title"], pos=job["pos"], n=job["n"], why=why, need=need)
        if await self._say(job, prompt, RECORD_STOP.format(title=job["title"], pos=job["pos"], why=why),
                           said=f"（佳树读兄长大人发的《{job['title']}》停下了，主动告诉他）"):
            job["stop_told"] = key
            self.p.log.info(f"kaju_learn: 《{job['title']}》停在第 {job['pos']} 段（{why}），告诉兄长了")
        self.save(job)

    async def _after_segment(self, job: dict, m: dict) -> None:
        every = int(self.cfg("learn_every", 6))
        if every > 0 and job["pos"] % every == 0 and job["pos"] < job["n"]:
            await self._learn(job, final=False)
        if m.get("tell") and int(m.get("intensity", 0)) >= 2:
            await self._tell_mid(job, m)

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

    async def _say(self, job: dict, prompt: str, record: str, said: str) -> bool:
        basics = self._star("say_to_owner")
        if basics is None or not self._owner_book(job):
            return False
        try:
            ok, why = await basics.say_to_owner(prompt, said=said, record=record)
        except Exception as exc:  # noqa: BLE001
            ok, why = False, f"{type(exc).__name__}: {exc}"
        if ok:
            job["shares"].append(time.time())
        else:
            self.p.log.info(f"kaju_learn: 读《{job['title']}》想跟兄长说，没说成：{why}")
        return ok

    async def _tell_mid(self, job: dict, m: dict) -> None:
        now = time.time()
        if not self.cfg("share", True) or not self._owner_book(job) or job.get("pace") == "all":
            return
        mids = [t for t in job.get("shares", []) if t < float(job.get("t_done") or 1e18)]
        if len(mids) >= int(self.cfg("mid_shares", 2)) or self._shares_today(now) >= int(self.cfg("share_per_day", 4)):
            return
        if mids and now - mids[-1] < float(self.cfg("mid_gap_minutes", 90)) * 60:
            return
        quote = f"；打动你的一句「{m['quote']}」" if m.get("quote") else ""
        seg_title = job["segs"][job["pos"] - 1]["title"] if job["pos"] else ""
        prompt = SHARE_MID.format(title=job["title"], pos=job["pos"], n=job["n"], label=f"（{seg_title}）" if seg_title else "",
                                  happened=m["happened"], emotion=m["emotion"], cause=m.get("cause", ""),
                                  thought=m.get("thought", ""), quote=quote)
        await self._say(job, prompt, RECORD_MID.format(title=job["title"], pos=job["pos"]),
                        said=f"（佳树在读兄长大人发的《{job['title']}》，读到一半主动跟他说）")

    async def _tell_done(self, job: dict) -> None:
        job["tell_try"] = time.time()
        if not self.cfg("share", True) or not self._owner_book(job):
            job["finish_told"] = True
            return
        f = job.get("final") or {}
        since = dt.datetime.fromtimestamp(job["t0"], self.p._tz).strftime("%m月%d日%H点")
        prompt = SHARE_DONE.format(title=job["title"], n=job["n"], since=since, trail=R.trail(job["state"], 6, quotes=False),
                                   after=f.get("after", ""), change=f"；看法的变化：{f['change']}" if f.get("change") else "",
                                   best=f"；最难忘：{f['best']}" if f.get("best") else "")
        if job.get("cut"):  # 文件被截了：读完的只是拿到的那部分
            prompt += f"\n注意：文件太长，你只拿到了前 {job['chars']} 字，后面的没拿到——要跟他说清楚，别当成整本读完了。"
        if await self._say(job, prompt, RECORD_DONE.format(title=job["title"]),
                           said=f"（佳树读完了兄长大人发的《{job['title']}》，主动跟他说）"):
            job["finish_told"] = True

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
        return NOTE_READING.format(title=job["title"], who=job["who"], kind=job["kind"], chars=job["chars"], n=job["n"],
                                   pos=job["pos"], label=f"（{job['segs'][job['pos'] - 1]['title']}）" if job["pos"] and job["segs"][job["pos"] - 1]["title"] else "",
                                   paused=paused, trail=R.trail(st, 6), extra=extra)

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
                "paused": f"好，《{job['title']}》先停在第 {job['pos']} 段，说接着读再读。",
                "stopped": f"好，《{job['title']}》不读了（读到第 {job['pos']} 段）。"}[pace]

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
        if not state["moments"]:
            return ""
        self.p.log.info(f"kaju_learn: 边看边想《{title}》{len(segments)} 段，看完：{state.get('impression', '')}")
        return ("你是从头一段一段看下来的，边看边这么想（看前面的时候还不知道后面）：\n" + R.trail(state, 8)
                + (f"\n看到最后的感觉：{state['impression']}" if state.get("impression") else ""))
