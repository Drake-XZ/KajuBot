"""学到的东西：她接触到的一切——私聊、群聊、看过的视频、读过的书和文件、听过的歌、上网查过的——
都能让她学到东西，攒成她自己的一本"懂的东西"，越学越懂。

以前：看完视频只留"感受"（kaju_heart 的心声、喜好账本只记喜不喜欢），聊天里别人讲给她的事
只在那一轮的上下文里，过了就没了。她每次都像第一次看，不会越看越懂。

这里做五件事：
1. 学（从哪儿学）
   - 聊天：后台每几分钟读 kaju_life 的聊天记录（私聊、群聊都算，她没说话的群聊也算），一段聊天安静下来后
     整段交给模型，挑出她能学到的"世上的东西"（作品、角色、梗、歌、UP主、知识、做法……），
     比如兄长大人说"那只小傻龙是终末地的陈千语"。她自己说的只当上下文（她可能说错），别人纠正她的记对的。
     聊天里这些人自己的私事、对她的要求和称呼不记（另有人物记忆、铭记、称呼簿）。
   - 看过/读过/听过的：kaju_basics 读过的文件、看过的 B站/抖音视频、听过的歌（event extra kaju_docs_read），
     她自己刷 B 站看完的每个视频（kaju_basics 调 learn_content）。记视频讲到的东西，不是视频本身。
   - 上网查过的：她调用搜索/打开网页的工具，查到的内容也学进去。
   - 第一次启用时：最近几天的聊天记录、memory_weight 珍藏里兄长大人分享过的书和视频也补学一遍。
2. 记（book.py）：一样东西一条——是什么、知道的几个点、她的看法、跟别的东西的关系、拿不准的说法、
   在哪儿碰到过。再碰到就往这条上补；不靠谱的说法（"好像"、二创玩梗、跟已有的对不上）进"拿不准"；
   被纠正了把旧说法挪走、记一句"以前弄错过"。碰到的日子越多、知道得越多、用得越多就越熟
   （听说过 → 知道一些 → 挺熟 → 很懂）；很久没碰也没用就记不清（越熟忘得越慢）。
3. 消化：每天睡前（digest_hour 点）把最近碰到过的条目和跟它们有关的旧条目一起交给模型理一理：
   同一样东西合并、知道的去重、矛盾的以靠谱的为准、发现东西之间的联系、冒出"想弄明白的事"，
   有时还有一句"原来是这样"。想弄明白的事会在她自己刷 B 站又没说看什么时拿去搜（kaju_basics 调 wonder_topic）。
4. 用：每轮请求前，对方这句话（还有这轮她正在看的视频/文件）提到了她知道的东西（名字、别名，
   或者本地向量模型 bge-m3 觉得意思很近），就在提示里给她看【你知道的】：熟悉程度、是什么、知道的几点、
   关系、看法、拿不准的、从哪儿知道的（别人私聊里讲的只说"听人说的"）。她回复里说出来了就算用了一次（更熟、更不容易忘）。
   工具 recall_knowledge 让她自己想一想（"你最近学到什么了""你知道 XX 吗"）。
5. 命令 /佳树学到的 [最近｜看 名字｜忘掉 名字｜好奇｜消化｜学]（管理员）。

状态在 plugin_data/astrbot_plugin_kaju_learn/book.json（本子 + 读到哪了），向量在 vec.json。
"""

from __future__ import annotations

from ..body import Answer, Request, Turn  # noqa: F401 — 只用在类型标注里
import asyncio
import datetime as dt
import hashlib
import json
import math
import os
import random
import re
import time
import zoneinfo
from typing import Any
from kaju_core.slots import slot_model  # noqa: E402  每项工作一格（11-18）
from kaju_core import parts, paths, people  # noqa: E402
from kaju_core.learn import book as B  # noqa: E402
from kaju_core.learn import extract as X  # noqa: E402
from kaju_core.learn import reading as R  # noqa: E402
from kaju_core.learn import lessons as LS  # noqa: E402  自己总结教训（11-19）
from kaju_core.learn import jargon as JG  # noqa: E402  这个群的叫法和黑话（11-19）
from kaju_core.learn import phrases as PH  # noqa: E402  例句库从真实聊天里长（11-20 晚）
from kaju_core.learn.reader import Reader, parse_check, CHECK_SYSTEM as R_CHECK_SYSTEM  # noqa: E402

PLUGIN_NAME = "astrbot_plugin_kaju_learn"


DEFAULT_OWNER = os.environ.get("KAJU_OWNER_QQ", "").strip()  # 兜底；兄长正式登记在 kaju_data\self\people\people.json


CHAT_ID = re.compile(r"^[pg]\d+$")


MEME_TAG = re.compile(r"&&[^&\n]{1,40}&&")
# 这一轮说到读书了（才去核对草稿里的读书情况；只是开关，不改她的字）
READING_WORDS = re.compile(r"读|段|卷|章|书|小说|看到|看完|结局|情节|剧情|后面|接着|继续|停")


NOISE = re.compile(r"^\[(图片|表情|视频|语音|文件[^\]]*|动画表情|戳一戳)[^\]]*\]$")


WEB_TOOLS = ("web_search", "deepseek_fetch", "tavily_", "exa_", "firecrawl_", "bocha")


ASK_LEARNED = re.compile(r"(学到|学了|学会|知道了|懂了|长见识|涨知识|新知识).{0,8}(什么|啥|没|吗|么)|"
                         r"(最近|今天|这几天|这阵子).{0,6}(看了|刷到|学).{0,6}(什么|啥)")


RECENT_NOTE = ("【你最近学到的】对方在问你最近学到/知道了什么。下面是你最近真学到的（自己看的、听人讲的、查的），"
               "挑一两样你最有感觉的，用自己的话说，别念清单，也别编下面没有的。")


# kaju_life 聊天记录的读法和记忆那边同一份（11-18 整理合并）
from kaju_core.memory.rater import line_time as _line_time, read_log_lines as _read_lines  # noqa: E402,F401


def _cos(a: list[float], b: list[float]) -> float:
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return s / (na * nb)


def _tool_text(tool_result) -> str:
    if tool_result is None:
        return ""
    parts = []
    for c in getattr(tool_result, "content", None) or []:
        t = getattr(c, "text", None)
        if t:
            parts.append(str(t))
    return "\n".join(parts) if parts else str(tool_result)


class LearnMind:
    """KajuLearn 的逻辑（AstrBot 外壳在 plugins\\kaju_learn\\main.py；只认 self.body = kaju_core.body.Body）。"""

    def __init__(self, body, config: dict | None = None):
        self.body = body  # kaju_core.body.Body：模型、设置、别的部分、日志
        parts.register(PLUGIN_NAME.removeprefix("astrbot_plugin_"), self)  # 登记成她的一个部分：别的部分用 body.find 先在这里找
        self.log = body.log
        self.config = config or {}
        self._dir = paths.self_dir(PLUGIN_NAME)
        os.makedirs(self._dir, exist_ok=True)
        self._path = os.path.join(self._dir, "book.json")
        self._vec_path = os.path.join(self._dir, "vec.json")
        self._state = self._load()
        self._vec: dict[str, list] = self._load_vec()
        self._lessons_path = os.path.join(self._dir, "lessons.json")
        self.lessons = self._load_lessons()
        self._lvec: dict[int, list] = {}  # 教训的向量（内存里，id -> [key, vec]）
        try:
            self._tz = zoneinfo.ZoneInfo(self.body.settings().get("timezone") or "Asia/Shanghai")
        except Exception:  # noqa: BLE001
            self._tz = dt.timezone(dt.timedelta(hours=8))
        self._lock = asyncio.Lock()
        self._qtask: asyncio.Task | None = None
        self._dirty = False
        self.reader = Reader(self)
        self._task = self._rtask = None
        if self._cfg("enable", True):
            try:
                loop = asyncio.get_running_loop()
                self._task = loop.create_task(self._loop())
                self._rtask = loop.create_task(self._read_loop())
            except RuntimeError:  # 离线测试里没有事件循环
                self._task = self._rtask = None

    # ------------------------------------------------------------ config / state
    def _cfg(self, path: str, default=None) -> Any:
        cur = self.config
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return default if cur is None or cur == "" else cur

    def _load(self) -> dict:
        try:
            with open(self._path, encoding="utf-8") as f:
                st = json.load(f)
        except FileNotFoundError:
            st = {}
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_learn: book.json 读不了，重新开始: {exc}")
            st = {}
        st.setdefault("book", B.new_book())
        for k in ("cards", "wonders", "digests"):
            st["book"].setdefault(k, B.new_book()[k])
        for k, v in (("log_pos", {}), ("pending", {}), ("tail", {}), ("fails", {}), ("queue", []),
                     ("last_digest", 0.0), ("log", []), ("backfilled", False), ("done_docs", [])):
            st.setdefault(k, v)
        return st

    def _load_vec(self) -> dict:
        try:
            with open(self._vec_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        self._state["log"] = self._state["log"][-300:]
        self._state["done_docs"] = self._state["done_docs"][-400:]
        self._state["book"]["digests"] = self._state["book"]["digests"][-60:]
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._path)
        self._save_lessons()
        self._dirty = False

    def _load_lessons(self) -> dict:
        try:
            with open(self._lessons_path, encoding="utf-8") as f:
                st = json.load(f)
        except FileNotFoundError:
            st = {}
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_learn: lessons.json 读不了，重新开始: {exc}")
            st = {}
        for k, v in LS.new_store().items():
            st.setdefault(k, v)
        return st

    def _save_lessons(self) -> None:
        self.lessons["reflected"] = self.lessons["reflected"][-30:]
        tmp = self._lessons_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.lessons, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._lessons_path)

    def _save_vec(self) -> None:
        tmp = self._vec_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._vec, f)
        os.replace(tmp, self._vec_path)

    @property
    def book(self) -> dict:
        return self._state["book"]

    def _day(self, ts: float) -> str:
        dsh = int(self._cfg("day_start_hour", 5))
        return (dt.datetime.fromtimestamp(ts, self._tz) - dt.timedelta(hours=dsh)).strftime("%Y-%m-%d")

    def _half(self) -> float:
        return float(self._cfg("half_life_days", 30.0))

    def _life_log_dir(self) -> str:
        return os.path.join(paths.self_dir("kaju_life"), "log")

    def _owners(self) -> set[str]:
        """兄长大人本人：身份表（kaju_core.people）；没登记时问称呼簿，再不行用老配置 owner_qq。"""
        if people.owner():
            return {people.owner()}
        book = self.body.find("address_of")
        if book is not None and getattr(book, "owner", ""):
            return {str(book.owner).strip()}
        return {str(self._cfg("owner_qq", DEFAULT_OWNER))}

    def labels(self) -> dict:
        """QQ → 佳树对这个人的称呼（兄长大人本人 + 称呼簿里设过的）。"""
        out = {}
        try:
            with open(os.path.join(paths.self_dir("address_book"), "addresses.json"), encoding="utf-8") as f:
                for qq, e in json.load(f).items():
                    if isinstance(e, dict) and e.get("address"):
                        out[str(qq)] = str(e["address"])
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            pass
        for qq in self._owners():
            out[qq] = "兄长大人"
        return out

    def _chat(self, event: Turn) -> str:
        gid = str(event.get_group_id() or "")
        return f"g{gid}" if gid else f"p{event.get_sender_id()}"

    def _who(self, qq: str, name: str = "") -> str:
        if qq in self._owners():
            return "兄长大人"
        return self.labels().get(qq) or name or "对方"

    def _note(self, kind: str, text: str) -> None:
        self._state["log"].append({"t": time.time(), "k": kind, "x": text[:200]})
        self.log.info(f"kaju_learn: {text}")

    async def _ask(self, system: str, prompt: str) -> str:
        pid = str(self._cfg("provider_id", "") or "")
        if not pid:
            pid = await slot_model(self.body, "learner")  # 每项工作一格（kaju_core/slots.py）
            if not pid:
                raise RuntimeError("没有可用的模型")
        return await self.body.generate(pid, prompt, system, timeout=float(self._cfg("timeout_seconds", 120)))

    # ------------------------------------------------------------ 向量（本地 bge-m3，可选）
    async def _embed(self, texts: list[str]) -> list[list[float]] | None:
        if not texts or not self._cfg("embed.enable", True):
            return None
        import aiohttp

        url = str(self._cfg("embed.url", "http://127.0.0.1:11435")).rstrip("/") + "/api/embed"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=float(self._cfg("embed.timeout", 4)))) as s:
                async with s.post(url, json={"model": str(self._cfg("embed.model", "bge-m3")), "input": texts}) as r:
                    data = await r.json(content_type=None)
            vecs = data.get("embeddings") or []
            if len(vecs) != len(texts) or any(not v or any(x != x for x in v[:4]) for v in vecs):
                return None
            return vecs
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _card_text(c: dict) -> str:
        return " ".join([c["name"], *c.get("aliases", [])[:4], c.get("what", "")])[:120]

    async def _refresh_vectors(self, limit: int = 48) -> int:
        todo = []
        for c in B.live(self.book):
            h = hashlib.sha1(self._card_text(c).encode()).hexdigest()[:10]
            got = self._vec.get(c["id"])
            if not got or got[0] != h:
                todo.append((c["id"], h, self._card_text(c)))
        alive = {c["id"] for c in B.live(self.book)}
        dead = [k for k in self._vec if k not in alive]
        for k in dead:
            self._vec.pop(k, None)
        done = 0
        for i in range(0, min(len(todo), limit), 16):
            chunk = todo[i:i + 16]
            vecs = await self._embed([t for _, _, t in chunk])
            if vecs is None:
                break
            for (cid, h, _), v in zip(chunk, vecs):
                self._vec[cid] = [h, [round(float(x), 4) for x in v]]
                done += 1
        if done or dead:
            self._save_vec()
        return done

    async def _similar(self, text: str, k: int, threshold: float, skip: set[str] | None = None) -> list[tuple[float, dict]]:
        text = (text or "").strip()[:300]
        if len(text) < 4 or not self._vec:
            return []
        q = await self._embed([text])
        if not q:
            return []
        out = []
        for c in B.live(self.book):
            if skip and c["id"] in skip:
                continue
            got = self._vec.get(c["id"])
            if not got:
                continue
            sim = _cos(q[0], got[1])
            if sim >= threshold:
                out.append((sim, c))
        out.sort(key=lambda x: -x[0])
        return out[:k]

    async def _known_for(self, text: str, k: int = 8) -> str:
        """抽取前给模型看的旧条目：提到名字的 + 意思近的。"""
        cards = B.relevant(self.book, text, k)
        ids = {c["id"] for c in cards}
        for _, c in await self._similar(text[:300], 4, float(self._cfg("embed.known_threshold", 0.55)), ids):
            cards.append(c)
        return "\n".join(B.ref_line(c) for c in cards[:k + 2])

    # ------------------------------------------------------------ background
    async def _loop(self) -> None:
        await asyncio.sleep(float(self._cfg("first_delay_seconds", 90)))
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"kaju_learn: 整理出错: {type(exc).__name__}: {exc}")
            await asyncio.sleep(max(60.0, float(self._cfg("interval_minutes", 5)) * 60))

    async def _read_loop(self) -> None:
        """在读的书：每分钟看一眼，到时间了就读下一段。"""
        await asyncio.sleep(30)
        while True:
            try:
                if self._cfg("reading.enable", True):
                    await self.reader.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"kaju_learn: 读书出错: {type(exc).__name__}: {exc}")
            await asyncio.sleep(60)

    async def start_reading(self, title: str, text: str, event, kind: str = "小说", name: str = "", cut: bool = False) -> str:
        """给 kaju_basics 用：收到一本长篇，开始一段一段读。返回这一轮给她看的内容；
        不像故事（资料、作业、代码）或读不成返回空（照旧一口气读）。cut：文件太长，text 只是前面一部分。"""
        if not self._cfg("enable", True) or not self._cfg("reading.enable", True):
            return ""
        if not R.is_story(text, name or title):
            return ""
        who = self._who(str(event.get_sender_id() or ""), event.get_sender_name() or "")
        return await self.reader.start(title, text, who=who, chat=self._chat(event), umo=event.unified_msg_origin, kind=kind,
                                       cut=cut)

    def keep_feeling(self, m: dict, src: str) -> None:
        """给感官用（2026-11-22）：看视频、听歌时说得更细的心情、里面人表达心情的一句，也攒进心情说法。"""
        if self._cfg("enable", True) and self._cfg("reading.feelings", True):
            self.reader.keep_feeling(m, src)

    async def watch_along(self, title: str, segments: list[dict], umo: str = "", who: str = "") -> str:
        """给 kaju_basics 用：长视频切成几段，一段一段看、边看边想。"""
        if not self._cfg("enable", True) or not self._cfg("reading.video", True):
            return ""
        return await self.reader.watch_along(title, segments, umo, who)

    async def terminate(self):
        parts.unregister(PLUGIN_NAME.removeprefix("astrbot_plugin_"), self)
        for t in (self._task, self._qtask, self._rtask):
            if t:
                t.cancel()
        try:
            self._save()
        except Exception:  # noqa: BLE001
            pass

    async def tick(self, now: float | None = None) -> dict:
        now = now or time.time()
        stats = {}
        async with self._lock:
            if not self._state["backfilled"]:
                self._backfill(now)
            stats["chat"] = await self.scan_logs(now)
            stats["wonder"] = await self._wonder_search(now)
            stats["content"] = await self._drain(now)
            if self._digest_due(now):
                stats["digest"] = await self.digest(now)
            stats["verify"] = await self.verify_facts(now)
            stats["lessons"] = await self.reflect(now)
            stats["jargon"] = await self.learn_jargon(now)
            stats["phrases"] = await self.learn_phrases(now)
            stats["vec"] = await self._refresh_vectors()
            self._save()
        if any(stats.values()):
            self.log.info(f"kaju_learn: 整理完 {stats}")
        return stats

    def _backfill(self, now: float) -> None:
        """第一次启用：最近几天的聊天记录从头读；兄长大人分享过的书和视频（memory_weight 珍藏）也学一遍。"""
        days = int(self._cfg("backfill_days", 7))
        oldest = (dt.datetime.fromtimestamp(now, self._tz) - dt.timedelta(days=days)).strftime("%Y-%m-%d")
        folder = self._life_log_dir()
        if os.path.isdir(folder):
            for fname in os.listdir(folder):
                if fname.endswith(".jsonl") and fname[:-6] < oldest:
                    self._state["log_pos"][fname] = 10 ** 9  # 更早的不补
        try:
            with open(os.path.join(paths.self_dir("memory_weight"), "state.json"), encoding="utf-8") as f:
                shelf = json.load(f).get("shelf") or []
        except (OSError, json.JSONDecodeError, AttributeError):
            shelf = []
        n = 0
        for it in shelf:
            if not isinstance(it, dict) or it.get("removed") or not it.get("content"):
                continue
            who = self._who(str(it.get("qq", "")), str(it.get("name", "")))
            kind = it.get("kind") or "文件"
            self._enqueue({"kind": kind, "title": it.get("file", ""), "content": it["content"],
                           "how": f"看了{who}分享的{kind}" if "视频" in kind else f"读了{who}分享的{kind}",
                           "who": who, "chat": it.get("chat", ""), "t": float(it.get("created") or now),
                           "extra": (f"她当时的回复：{str(it.get('reply', ''))[:200]}" if it.get("reply") else ""),
                           "key": "shelf:" + str(it.get("id", ""))}, kick=False)
            n += 1
        self._state["backfilled"] = True
        self._note("backfill", f"第一次启用：补读最近 {days} 天的聊天记录，补学珍藏里的 {n} 样")

    # ------------------------------------------------------------ 1a. 聊天
    async def scan_logs(self, now: float) -> int:
        folder = self._life_log_dir()
        if not os.path.isdir(folder) or not self._cfg("chat.enable", True):
            return 0
        dsh = int(self._cfg("day_start_hour", 5))
        oldest = (dt.datetime.fromtimestamp(now, self._tz) - dt.timedelta(days=14)).strftime("%Y-%m-%d")
        for fname in sorted(f for f in os.listdir(folder) if f.endswith(".jsonl")):
            day = fname[:-6]
            if day < oldest:
                continue
            pos = int(self._state["log_pos"].get(fname, 0))
            new = _read_lines(os.path.join(folder, fname), pos)
            if not new:
                continue
            self._state["log_pos"][fname] = pos + len(new)
            for r in new:
                chat = str(r.get("c", ""))
                if not CHAT_ID.match(chat):
                    continue
                try:
                    r = {**r, "ts": _line_time(day, r.get("t", "00:00"), dsh, self._tz)}
                except ValueError:
                    continue
                self._state["pending"].setdefault(chat, []).append(r)
        settle = float(self._cfg("chat.settle_seconds", 150))
        size = int(self._cfg("chat.batch_lines", 40))
        max_calls = int(self._cfg("chat.max_calls_per_round", 4))
        learned = calls = 0
        for chat in list(self._state["pending"]):
            lines = self._state["pending"][chat]
            while lines and calls < max_calls:
                if now - lines[-1]["ts"] < settle and len(lines) < size:
                    break  # 还在聊，等安静下来看整段
                batch = lines[:size]
                called = False
                try:
                    n, called = await self._learn_chat(chat, batch, now)
                except Exception as exc:  # noqa: BLE001
                    fails = self._state["fails"].get(chat, 0) + 1
                    self._state["fails"][chat] = fails
                    self.log.warning(f"kaju_learn: 读聊天学东西失败（{chat} 第{fails}次）: {type(exc).__name__}: {exc}")
                    calls += 1
                    if fails < 3:
                        break
                    n = 0
                self._state["fails"].pop(chat, None)
                learned += n
                calls += int(called)
                self._state["tail"][chat] = (self._state["tail"].get(chat, []) + batch)[-8:]
                del lines[:len(batch)]
            if not lines:
                self._state["pending"].pop(chat, None)
        return learned

    def _worth(self, batch: list[dict]) -> bool:
        """有人认真讲了点东西才值得看：别人说的话（去掉图片、表情）加起来够长。"""
        texts = [str(r.get("x", "")) for r in batch if r.get("u") not in (None, "", "self")]
        texts = [t for t in texts if not NOISE.match(t.strip())]
        total = sum(len(t) for t in texts)
        return total >= int(self._cfg("chat.min_chars", 12)) and any(len(t) >= 8 for t in texts)

    def _fmt(self, r: dict, labels: dict, idx: int | None = None) -> str:
        qq = str(r.get("u", ""))
        if qq == "self":
            who = "佳树"
        else:
            call = labels.get(qq, "")
            who = f"{r.get('n') or '某人'}({qq})" + (f"（{call}）" if call and call != r.get("n") else "")
        text = str(r.get("x", "")).replace("\n", " / ")[:240]
        return f"{idx}. [{r.get('t', '')}] {who}: {text}" if idx is not None else f"[{r.get('t', '')}] {who}: {text}"

    def _place(self, chat: str, labels: dict) -> tuple[str, str]:
        """(给模型看的地方, 记在本子上的"在哪儿知道的")"""
        if chat.startswith("g"):
            return f"QQ群（{chat[1:]}）", "群里聊天时听人说的"
        qq = chat[1:]
        who = "兄长大人" if qq in self._owners() else (labels.get(qq) or "别人")
        return f"佳树和{who}的私聊", ("兄长大人跟你说的" if who == "兄长大人" else f"和{who}私聊时听说的")

    def _checked_fixes(self, items: list, batch: list[dict]) -> list:
        """聊天里学到的“纠正”要指得出是哪条别人的消息纠正的（fix_by = 【新消息】编号，不能是她自己那条）；
        指不出来就不当纠正（11-19：没人纠正，模型拿自己的旧印象把她说对的“GTA6 11 月 19 日发售”记成了“以前弄错过”）。"""
        out = []
        for it in items:
            if isinstance(it, dict) and it.get("fix"):
                try:
                    k = int(it.get("fix_by") or 0)
                except (TypeError, ValueError):
                    k = 0
                if not (1 <= k <= len(batch)) or batch[k - 1].get("u") in ("self", None):
                    self.log.info(f"kaju_learn: 说她弄错了却指不出谁纠正的，不当纠正：{it.get('name', '')}「{str(it['fix'])[:30]}」")
                    it = {**it, "fix": ""}
            out.append(it)
        return out

    async def _learn_chat(self, chat: str, batch: list[dict], now: float) -> tuple[int, bool]:
        if not self._worth(batch):
            return 0, False
        labels = self.labels()
        before = "\n".join(self._fmt(r, labels) for r in self._state["tail"].get(chat, [])[-6:])
        lines = "\n".join(self._fmt(r, labels, i + 1) for i, r in enumerate(batch))
        known = await self._known_for(" ".join(str(r.get("x", "")) for r in batch))
        place, how = self._place(chat, labels)
        data = B.parse_json(await self._ask(X.CHAT_SYSTEM, X.chat_prompt(place=place, before=before, lines=lines, known=known)))
        if data is None:
            raise ValueError("模型没按 JSON 回")
        people = {str(r.get("n", "")) for r in batch if r.get("u") not in ("self", None)} | set(labels.values())
        people = {p for p in people if len(p) >= 2}
        ts = batch[-1]["ts"]
        items = self._checked_fixes(data.get("items") or [], batch)
        st = B.apply_items(self.book, items, {"how": how, "who": "", "chat": chat, "trust": 1},
                           ts, self._day(ts), exclude=people, max_items=int(self._cfg("chat.max_items", 6)))
        n = len(st["new"]) + len(st["more"])
        if n:
            self._note("chat", f"从{place}学到：" + "、".join(st["new"] + st["more"])
                       + (f"（新的 {len(st['new'])} 样）" if st["new"] else "") + (f"，纠正了 {st['fixed']} 处" if st["fixed"] else ""))
        return n, True

    async def _wonder_search(self, now: float) -> int:
        """想弄明白的事自己上网查一次（11-19）：原来只在她自己刷 B 站又没定主题时才拿去搜，那种时候几乎没有，
        睡前攒下的“想弄明白”一次都没真的去查过。现在攒下 min_age_hours 以后、每 every_hours 小时最多查一件，
        查到的照“上网查到的”学进本子；查成了这件就不再查（tried = 2），没查成隔一天再试。返回这次学进队列的件数。"""
        if not self._cfg("enable", True) or not self._cfg("wonder.search", True):
            return 0
        last = float(self._state.get("wonder_search_t", 0) or 0)
        if now - last < float(self._cfg("wonder.every_hours", 6)) * 3600:
            return 0
        min_age = float(self._cfg("wonder.min_age_hours", 2)) * 3600
        w = next((x for x in self.book.get("wonders", []) if x.get("kw") and int(x.get("tried", 0)) < 2
                  and now - float(x.get("tried_t", 0)) >= 86400 and now - float(x.get("t", now)) >= min_age), None)
        if w is None:
            return 0
        self._state["wonder_search_t"] = now
        w["tried"], w["tried_t"] = int(w.get("tried", 0)) + 1, now
        self._dirty = True
        text = await self._web_search(str(w["kw"])[:120], str(w.get("q", ""))[:120])
        if len(text) < 80:
            self.log.info(f"kaju_learn: 想弄明白「{w.get('q', '')}」，上网查「{w['kw']}」没查到东西")
            return 0
        w["tried"] = 2
        self._enqueue({"kind": "上网查到的", "title": w["kw"], "content": text[:6000], "how": "自己好奇上网查到的",
                       "who": "网上", "chat": "", "extra": f"她为什么去查：她一直想弄明白「{w.get('q', '')}」"}, kick=False)
        self.log.info(f"kaju_learn: 想弄明白「{w.get('q', '')}」，自己上网查了「{w['kw']}」")
        return 1

    async def _web_search(self, query: str, question: str = "") -> str:
        """用 AstrBot 里配好的 DeepSeek 网页搜索（provider_settings.websearch_deepseek_key，和她聊天时用的同一个）查一次，
        返回“标题：摘要”几段文字；没配 / 出错返回 ''。"""
        try:
            import aiohttp
            ps = (self.body.settings() or {}).get("provider_settings") or {}
            keys = [k for k in (ps.get("websearch_deepseek_key") or []) if k]
            if not keys or not query.strip():
                return ""
            payload = {"query": query, "count": 6, "need_content": False}
            if question:
                payload["ori_question"] = question
            async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=40)) as s:
                async with s.post("https://api.deepseek.com/v1/tools/search", json=payload,
                                  headers={"Authorization": f"Bearer {keys[0]}", "Content-Type": "application/json"}) as r:
                    if r.status != 200:
                        self.log.info(f"kaju_learn: 网页搜索没成（HTTP {r.status}）")
                        return ""
                    data = await r.json()
        except Exception as exc:  # noqa: BLE001
            self.log.info(f"kaju_learn: 网页搜索出错 {type(exc).__name__}: {exc}")
            return ""
        parts = []
        for it in data.get("results") or []:
            snip = str(it.get("summary") or it.get("snippet") or "").strip()
            if snip:
                parts.append(f"{str(it.get('title') or '').strip()}：{snip[:1200]}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------ 1b. 看过 / 读过 / 听过 / 查过的
    def _enqueue(self, job: dict, kick: bool = True) -> None:
        key = job.get("key") or hashlib.sha1(f"{job.get('title')}|{str(job.get('content'))[:200]}".encode()).hexdigest()[:12]
        if key in self._state["done_docs"] or any(j.get("key") == key for j in self._state["queue"]):
            return
        job["key"] = key
        job.setdefault("t", time.time())
        self._state["queue"].append(job)
        self._state["queue"] = self._state["queue"][-40:]
        self._dirty = True
        if kick and (self._qtask is None or self._qtask.done()):
            self._qtask = asyncio.create_task(self._drain_soon())

    async def _drain_soon(self) -> None:
        await asyncio.sleep(float(self._cfg("content.delay_seconds", 20)))  # 让她先回完话，别抢模型
        try:
            async with self._lock:
                n = await self._drain(time.time())
                if n:
                    await self._refresh_vectors()
                self._save()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_learn: 学看过的东西出错: {type(exc).__name__}: {exc}")

    async def _drain(self, now: float) -> int:
        n = 0
        max_jobs = int(self._cfg("content.max_per_round", 6))
        for _ in range(max_jobs):
            if not self._state["queue"]:
                break
            job = self._state["queue"][0]
            try:
                n += await self._learn_content(job)
            except Exception as exc:  # noqa: BLE001
                job["fails"] = int(job.get("fails", 0)) + 1
                self.log.warning(f"kaju_learn: 学《{job.get('title', '')}》失败（第{job['fails']}次）: {type(exc).__name__}: {exc}")
                if job["fails"] < 3:
                    break
            self._state["queue"].pop(0)
            self._state["done_docs"].append(job["key"])
        return n

    async def _learn_content(self, job: dict) -> int:
        content = str(job.get("content") or "").strip()
        if len(content) < 20 or content.startswith(("没读成", "没打开", "没看成")):
            return 0
        title = str(job.get("title") or "")
        known = await self._known_for(title + " " + content[:1500])
        prompt = X.content_prompt(how=job.get("how", "看了一样东西"), title=title, meta=job.get("meta", ""),
                                  content=content, extra=job.get("extra", ""), known=known,
                                  limit=int(self._cfg("content.max_chars", 3500)),
                                  max_items=int(self._cfg("content.max_items", 6)))
        data = B.parse_json(await self._ask(X.CONTENT_SYSTEM, prompt))
        if data is None:
            raise ValueError("模型没按 JSON 回")
        ts = float(job.get("t") or time.time())
        trust = 1 if job.get("kind") != "上网查到的" or self._cfg("web.trust", True) else 0
        src = {"how": job.get("how", ""), "who": job.get("who", ""), "chat": job.get("chat", ""),
               "title": title[:40], "trust": trust}
        st = B.apply_items(self.book, data.get("items") or [], src, ts, self._day(ts),
                           max_items=int(self._cfg("content.max_items", 6)))
        n = len(st["new"]) + len(st["more"])
        if n:
            self._note("content", f"{job.get('how', '')}《{title[:30]}》，学到：" + "、".join(st["new"] + st["more"]))
        return n

    async def learn_content(self, *, kind: str, title: str, content: str, how: str, who: str = "", chat: str = "",
                            meta: str = "", extra: str = "", key: str = "") -> None:
        """给别的插件用（kaju_basics 刷 B 站看完一个视频）：交给后台学。"""
        if not self._cfg("enable", True) or not self._cfg("content.enable", True):
            return
        self._enqueue({"kind": kind, "title": title, "content": content, "how": how, "who": who, "chat": chat,
                       "meta": meta, "extra": extra, "t": time.time(), **({"key": key} if key else {})})

    # ------------------------------------------------------------ 3. 消化
    def _digest_due(self, now: float) -> bool:
        if not self._cfg("digest.enable", True):
            return False
        last = float(self._state.get("last_digest") or 0)
        if not any(c["t1"] > last for c in B.live(self.book)):
            return False
        local = dt.datetime.fromtimestamp(now, self._tz)
        hour = int(self._cfg("digest.hour", 4))
        if self._day(now) != self._day(last) and local.hour >= hour and now - last > 6 * 3600:
            return True
        return now - last > 36 * 3600  # 那个点机器人没开：过了一天半也理一次

    async def digest(self, now: float) -> dict:
        last = float(self._state.get("last_digest") or 0)
        recent = sorted((c for c in B.live(self.book) if c["t1"] > last), key=lambda c: -c["t1"])
        size = int(self._cfg("digest.batch", 14))
        total = {"merged": 0, "updated": 0, "links": 0, "wonders": 0, "aha": []}
        for i in range(0, min(len(recent), size * int(self._cfg("digest.max_batches", 4))), size):
            group = recent[i:i + size]
            older = B.neighbors(self.book, group, int(self._cfg("digest.neighbors", 12)))
            ids = {c["id"] for c in group + older}
            wonders = "；".join(w["q"] for w in self.book.get("wonders", []))
            prompt = X.digest_prompt(recent="\n".join(B.ref_line(c) for c in group),
                                     older="\n".join(B.ref_line(c) for c in older), wonders=wonders)
            data = B.parse_json(await self._ask(X.DIGEST_SYSTEM, prompt))
            if data is None:
                self.log.warning("kaju_learn: 消化时模型没按 JSON 回")
                continue
            st = B.apply_digest(self.book, data, now, ids)
            for k in ("merged", "updated", "links", "wonders"):
                total[k] += st[k]
            if st["aha"]:
                total["aha"].append(st["aha"])
        self._state["last_digest"] = now
        self.book["digests"].append({"t": now, **{k: v for k, v in total.items()}})
        self._note("digest", f"睡前理了理 {len(recent)} 样：合并 {total['merged']}、理顺 {total['updated']}、"
                   f"新关系 {total['links']}、新的好奇 {total['wonders']}" + (f"；{total['aha'][0]}" if total["aha"] else ""))
        return total

    # ------------------------------------------------------------ 3b. 自己总结教训（lessons.py，11-19）
    async def reflect(self, now: float, force_day: str = "") -> dict:
        """复盘一天：没复盘过的、已经过完的那几天（最多往回 lessons.days_back 天），一轮最多一天。
        force_day：/佳树教训 复盘 某天（不管复盘过没有）。"""
        if not self._cfg("lessons.enable", True):
            return {}
        today = self._day(now)
        if force_day:
            day = force_day
        else:
            back = int(self._cfg("lessons.days_back", 2))
            days = [(dt.datetime.fromtimestamp(now, self._tz) - dt.timedelta(days=k)).strftime("%Y-%m-%d") for k in range(1, back + 1)]
            day = next((d for d in sorted(days) if d < today and d not in self.lessons["reflected"]), "")
            if not day:
                return {}
        rows = self._day_rows(day)
        records = self._day_records(day)
        st = {"day": day, "said": sum(1 for r in rows if r.get("u") == "self"), "new": 0, "more": 0, "active": 0,
              "again": 0, "dropped": 0}
        if st["said"]:
            st["self"] = 0
            for prompt, lines in self._reflect_batches(rows, records):
                try:
                    out = await self._ask(LS.SYSTEM, LS.PROMPT.format(known=LS.known_block(self.lessons), eps=prompt))
                except Exception as exc:  # noqa: BLE001
                    self.log.warning(f"kaju_learn: 复盘 {day} 出错 {type(exc).__name__}: {exc}")
                    return st  # 这天下次再复盘
                for k, v in LS.apply(self.lessons, LS.parse(out), lines, now, day).items():
                    st[k] += v
                selfs = LS.parse_self(out, lines, day)
                if selfs and self._cfg("lessons.self_facts", True):  # 关于自己的能力和经历（11-19）→ 【关于自己】
                    try:
                        from kaju_core.life import selffacts as SF
                        got = SF.add_learned(paths.self_dir("kaju_life"), selfs, now)
                        st["self"] += got["new"] + got["updated"]
                        if got["new"] or got["updated"]:
                            self.log.info("kaju_learn: 关于自己学到：" + "；".join(s["fact"] for s in selfs)[:200])
                    except Exception as exc:  # noqa: BLE001
                        self.log.warning(f"kaju_learn: 关于自己没记进去 {type(exc).__name__}: {exc}")
        await self._revise(now)
        st.update(LS.tidy(self.lessons, now, int(self._cfg("lessons.learned_after", 6)),
                          float(self._cfg("lessons.fade_days", 30)), int(self._cfg("lessons.max_active", 30))))
        if day not in self.lessons["reflected"]:
            self.lessons["reflected"].append(day)
        self._dirty = True
        self._note("lessons", f"复盘了 {day}（她说了 {st['said']} 句）：新教训 {st['new']}、又碰到 {st['more']}、"
                   f"生效 {st['active']}、看过还犯 {st['again']}、不算 {st['dropped']}")
        return st

    def _day_rows(self, day: str) -> list[dict]:
        dsh = int(self._cfg("day_start_hour", 5))
        path = os.path.join(self._life_log_dir(), day + ".jsonl")
        out = []
        for r in _read_lines(path, 0) if os.path.exists(path) else []:
            if CHAT_ID.match(str(r.get("c", ""))):
                try:
                    out.append({**r, "ts": _line_time(day, r.get("t", "00:00"), dsh, self._tz)})
                except ValueError:
                    continue
        return out

    def _day_records(self, day: str) -> list[dict]:
        """程序记录：说到做到插件记下的“答应了却没做”、知识本里被人纠正的说法（都按 chat 归好）。"""
        out = []
        path = os.path.join(paths.self_dir("follow_through"), "misses.jsonl")
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        m = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if self._day(float(m.get("t", 0))) == day:
                        out.append({"chat": str(m.get("chat", "")), "t": float(m["t"]),
                                    "text": f"答应了却没做（{m.get('what', '')}）：她说「{str(m.get('reply', ''))[:60]}」，这一轮什么都没做"
                                            + (f"，后来{m['after']}" if m.get("after") else "")})
        except OSError:
            pass
        for c in B.live(self.book):
            for x in c.get("fixed", []):
                if self._day(float(x.get("t", 0))) == day:
                    chat = next((s.get("chat", "") for s in reversed(c.get("srcs", [])) if abs(float(s.get("t", 0)) - float(x["t"])) < 3600), "")
                    out.append({"chat": chat, "t": float(x["t"]), "text": f"被纠正：她以前说的「{x['x'][:50]}」（{c['name']}）是错的"})
        return out

    def _reflect_batches(self, rows: list[dict], records: list[dict]) -> list[tuple[str, dict]]:
        """她说的每句 + 前 6 行后 8 行（同一个聊天），每批 8 句；行号用当天的行序（L 编号），程序记录 R 编号。"""
        labels = self.labels()
        by_chat: dict[str, list[int]] = {}
        for i, r in enumerate(rows):
            by_chat.setdefault(r["c"], []).append(i)
        lines: dict[str, dict] = {}
        eps = []
        for chat, idx in by_chat.items():
            place = self._place(chat, labels)[0]
            for k, i in enumerate(idx):
                if rows[i].get("u") != "self":
                    continue
                around = idx[max(0, k - 6):k + 9]
                text = []
                for j in around:
                    lid = f"L{j + 1}"
                    s = self._fmt(rows[j], labels)
                    lines[lid] = {"self": rows[j].get("u") == "self", "text": s}
                    tag = "【她这句】" if j == i else ""
                    text.append(f"{lid} {tag}{s}")
                eps.append((chat, rows[i]["ts"], f"（{place}）\n" + "\n".join(text)))
        out = []
        size = int(self._cfg("lessons.batch", 8))
        for b in range(0, len(eps), size):
            chunk = eps[b:b + size]
            chats = {c for c, _, _ in chunk}
            t0, t1 = min(t for _, t, _ in chunk) - 600, max(t for _, t, _ in chunk) + 1800
            recs = [r for r in records if (r["chat"] in chats or not r["chat"]) and t0 <= r["t"] <= t1]
            rlines = {}
            for n, r in enumerate(recs, 1):
                rlines[f"R{b + n}"] = {"self": False, "text": r["text"]}
            body = "\n\n".join(f"===== 第 {n} 句 =====\n{e}" for n, (_, _, e) in enumerate(chunk, 1))
            if rlines:
                body += "\n\n程序记录：\n" + "\n".join(f"{k} {v['text']}" for k, v in rlines.items())
            out.append((body, {**{k: v for k, v in lines.items() if k in body}, **rlines}))
        return out

    async def verify_facts(self, now: float, force: bool = False) -> int:
        """睡前核对旧事实（11-19）：每天一次，挑最近 verify.days 天聊天里又被人提到、记了一天以上、verify.every_days 天内没核对过的卡，
        最多 verify.max_cards 张；把这张卡的事实和提到它的聊天给模型看，被后来的聊天说成不对、或按日期已过时的挪进“拿不准”。
        只按材料判断（证据要是别人那行，或“日期”且那句真和日子有关）。返回挪了几条。"""
        if not self._cfg("verify.enable", True):
            return 0
        today = self._day(now)
        if not force and self._state.get("verify_day") == today:
            return 0
        days = int(self._cfg("verify.days", 14))
        oldest = (dt.datetime.fromtimestamp(now, self._tz) - dt.timedelta(days=days)).strftime("%Y-%m-%d")
        folder = self._life_log_dir()
        rows = []
        for fname in sorted(f for f in os.listdir(folder) if f.endswith(".jsonl") and f[:-6] >= oldest) if os.path.isdir(folder) else []:
            rows += [{**r, "day": fname[:-6]} for r in _read_lines(os.path.join(folder, fname), 0) if CHAT_ID.match(str(r.get("c", "")))]
        every = float(self._cfg("verify.every_days", 7)) * 86400
        labels = self.labels()
        cand = []
        for c in B.live(self.book):
            if not c.get("facts") or now - float(c.get("t0", now)) < 86400 or now - float(c.get("verified_t", 0)) < every:
                continue
            hits = [r for r in rows if r.get("u") != "self" and B.mentioned(c, str(r.get("x", "")))]
            if hits:
                cand.append((len(hits), c))
        cand.sort(key=lambda x: -x[0])
        moved = 0
        timed = re.compile(r"预计|即将|将于|快要|计划于|定于")
        for _, c in cand[: int(self._cfg("verify.max_cards", 10))]:
            ment = [r for r in rows if B.mentioned(c, str(r.get("x", "")))][-30:]
            lines = {f"L{i}": {"self": r.get("u") == "self", "text": f"{r['day'][5:]} " + self._fmt(r, labels)} for i, r in enumerate(ment, 1)}
            facts = {f"K{i}": f["x"] for i, f in enumerate(c["facts"], 1)}
            prompt = X.VERIFY_PROMPT.format(today=dt.datetime.fromtimestamp(now, self._tz).strftime("%Y年%m月%d日"), name=c["name"],
                                            kind=c.get("kind", ""), facts="\n".join(f"{k} {v}" for k, v in facts.items()),
                                            lines="\n".join(f"{k} {v['text']}" for k, v in lines.items()))
            try:
                data = B.parse_json(await self._ask(X.VERIFY_SYSTEM, prompt)) or {}
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"kaju_learn: 核对「{c['name']}」出错 {type(exc).__name__}: {exc}")
                break
            c["verified_t"] = now
            for it in data.get("不对") or []:
                if not isinstance(it, dict):
                    continue
                fx = facts.get(str(it.get("K") or "").strip().upper())
                ev = str(it.get("证据") or "").strip().upper()
                line = lines.get(ev)
                if not fx:
                    continue
                if ev == "日期":
                    # 11-19 首轮把“11 月 19 日主机版发售”判成过时：日期得真写在这条里、比今天早，还得是“预计 / 即将”这种还没发生的说法
                    ok = bool(timed.search(fx)) and self._date_passed(fx, now)
                elif line is not None and not line["self"]:
                    # 11-19 首轮把“6.2 能满足日常”和证据里同一句话判成不对：说的是同一件事的不算；剩下的再单独问一遍“是不是明确相反”
                    ok = B.bigram_overlap(fx, line["text"]) < 0.5 and await self._contradicts(fx, line["text"])
                else:
                    ok = False
                if ok and B.demote(c, fx, str(it.get("为什么") or ""), now):
                    moved += 1
                    self._note("verify", f"核对「{c['name']}」：「{fx[:30]}」挪进拿不准（{str(it.get('为什么') or '')[:20]}）")
        self._state["verify_day"] = today
        self._dirty = True
        return moved

    def _date_passed(self, text: str, now: float) -> bool:
        """这句话里写着的日期（2026年11月19日 / 11月19日）比今天早。没写日期 → False。"""
        today = dt.datetime.fromtimestamp(now, self._tz).date()
        for m in re.finditer(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]", text or ""):
            try:
                d = dt.date(int(m.group(1) or today.year), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            if d < today:
                return True
        return False

    async def _contradicts(self, fact: str, line: str) -> bool:
        try:
            d = B.parse_json(await self._ask(X.CONFIRM_SYSTEM, X.CONFIRM_PROMPT.format(fact=fact, line=line))) or {}
        except Exception:  # noqa: BLE001
            return False
        return d.get("相反") is True

    async def learn_jargon(self, now: float, force_day: str = "") -> dict:
        """这个群的叫法和黑话（jargon.py）：没学过的、已经过完的那几天（往回 jargon.days_back 天），一轮一天，每个群分开。"""
        if not self._cfg("jargon.enable", True):
            return {}
        d = JG.load(self._dir)
        today = self._day(now)
        if force_day:
            day = force_day
        else:
            back = int(self._cfg("jargon.days_back", 2))
            days = [(dt.datetime.fromtimestamp(now, self._tz) - dt.timedelta(days=k)).strftime("%Y-%m-%d") for k in range(1, back + 1)]
            day = next((x for x in sorted(days) if x < today and x not in d["reflected"]), "")
            if not day:
                return {}
        labels = self.labels()
        by_group: dict[str, list[tuple[int, dict]]] = {}
        for i, r in enumerate(self._day_rows(day)):
            if str(r.get("c", "")).startswith("g"):
                by_group.setdefault(r["c"][1:], []).append((i, r))
        st = {"day": day, "new": 0, "more": 0, "sure": 0, "dropped": 0}
        size = int(self._cfg("jargon.batch_lines", 150))
        for gid, rows in by_group.items():
            if len(rows) < int(self._cfg("jargon.min_lines", 20)):
                continue
            texts = [str(r.get("x", "")) for _, r in rows]
            for b in range(0, len(rows), size):
                chunk = rows[b:b + size]
                lines = {f"L{i + 1}": {"self": r.get("u") == "self", "text": self._fmt(r, labels)} for i, r in chunk}
                body = "\n".join(f"{k} {v['text']}" for k, v in lines.items())
                try:
                    out = await self._ask(JG.SYSTEM, JG.PROMPT.format(known=JG.known_block(d, gid), lines=body))
                except Exception as exc:  # noqa: BLE001
                    self.log.warning(f"kaju_learn: 学 {day} 群 {gid} 的叫法出错 {type(exc).__name__}: {exc}")
                    return st  # 这天下次再学
                d = JG.load(self._dir)  # 随读随写：离线脚本同时写也不会互相盖掉
                for k, v in JG.add(d, gid, JG.parse(out), lines, texts, now, day,
                                   int(self._cfg("jargon.confirm_uses", 3))).items():
                    st[k] += v
                JG.save(self._dir, d)
        d = JG.load(self._dir)
        if day not in d["reflected"]:
            d["reflected"].append(day)
        JG.save(self._dir, d)
        self._jargon_cache = None
        self._note("jargon", f"学了 {day} 群里的叫法：新 {st['new']}、又碰到 {st['more']}、确定了 {st['sure']}、不算 {st['dropped']}")
        return st

    async def learn_phrases(self, now: float, force_day: str = "") -> dict:
        """例句库从真实聊天里长（phrases.py）：没学过的、已经过完的那几天（往回 phrases.days_back 天），一轮一天；
        她说的每句带前 10 行后 8 行（群里回话常隔好几条），挑效果好的进 kaju_style\\replyer_learned.json，给回复器当参考。"""
        if not self._cfg("phrases.enable", True):
            return {}
        folder = paths.self_dir("kaju_style")
        d = PH.load(folder)
        today = self._day(now)
        if force_day:
            day = force_day
        else:
            back = int(self._cfg("phrases.days_back", 2))
            days = [(dt.datetime.fromtimestamp(now, self._tz) - dt.timedelta(days=k)).strftime("%Y-%m-%d") for k in range(1, back + 1)]
            day = next((x for x in sorted(days) if x < today and x not in d["reflected"]), "")
            if not day:
                return {}
        rows = self._day_rows(day)
        labels = self.labels()
        by_chat: dict[str, list[int]] = {}
        for i, r in enumerate(rows):
            by_chat.setdefault(r["c"], []).append(i)
        lines: dict[str, dict] = {}
        eps = []
        for chat, idx in by_chat.items():
            place = self._place(chat, labels)[0]
            for k, i in enumerate(idx):
                if rows[i].get("u") != "self" or not PH.as_line(rows[i].get("x", "")):
                    continue
                text = []
                for j in idx[max(0, k - 10):k + 9]:
                    lines[f"L{j + 1}"] = {"self": rows[j].get("u") == "self", "text": str(rows[j].get("x", "")),
                                          "chat": chat, "i": j}
                    text.append(f"L{j + 1} {'【她这句】' if j == i else ''}{self._fmt(rows[j], labels)}")
                eps.append(f"（{place}）\n" + "\n".join(text))
        st = {"day": day, "said": len(eps), "picked": 0, "new": 0, "same": 0}
        size = int(self._cfg("phrases.batch", 8))
        got: list[dict] = []
        for b in range(0, len(eps), size):
            body = "\n\n".join(f"===== 第 {n} 句 =====\n{e}" for n, e in enumerate(eps[b:b + size], 1))
            try:
                out = await self._ask(PH.SYSTEM, PH.PROMPT.format(eps=body))
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"kaju_learn: 学 {day} 的例句出错 {type(exc).__name__}: {exc}")
                return st  # 这天下次再学
            got += PH.check(PH.parse(out), lines)
        got = got[:int(self._cfg("phrases.per_day", 6))]
        st["picked"] = len(got)
        if got:
            from kaju_core.voice import replyer
            vecs = await self._embed([replyer.example_query(g["situation"]) or g["situation"] for g in got])
            if not vecs:
                self.log.info(f"kaju_learn: 学 {day} 的例句：向量服务不在，下次再学")
                return st
            base = [b["line"] for b in replyer.load_bank()]
            d = PH.load(folder)  # 随读随写
            st.update(PH.add(d, got, vecs, base, now, day, int(self._cfg("phrases.max_total", 200))))
        else:
            d = PH.load(folder)
        if day not in d["reflected"]:
            d["reflected"].append(day)
        PH.save(folder, d)
        self._note("phrases", f"学了 {day} 的例句（她说了 {st['said']} 句）：挑中 {st['picked']}、新进库 {st.get('new', 0)}、"
                   f"和库里太像 {st.get('same', 0)}"
                   + ("：" + "；".join(g["line"][:30] for g in got) if got else ""))
        return st

    def _jargon(self) -> dict:
        """聊天时用的黑话本（按文件改动时间缓存）。"""
        path = os.path.join(self._dir, JG.FILE)
        try:
            m = os.path.getmtime(path)
        except OSError:
            return {"groups": {}, "reflected": []}
        cache = getattr(self, "_jargon_cache", None)
        if not cache or cache[0] != m:
            self._jargon_cache = cache = (m, JG.load(self._dir))
        return cache[1]

    async def _revise(self, now: float) -> None:
        for x in [x for x in self.lessons["lessons"] if x.get("revise")][:3]:
            ev = "\n".join(f"- {e.get('day', '')}：{e.get('line', '')}" for e in x.get("evidence", [])[-4:])
            try:
                out = await self._ask(LS.REVISE_SYSTEM, LS.REVISE_PROMPT.format(situation=x["situation"], lesson=x["lesson"], evidence=ev))
                d = B.parse_json(out) or {}
            except Exception:  # noqa: BLE001
                continue
            s, l = " ".join(str(d.get("场合") or "").split())[:40], " ".join(str(d.get("教训") or "").split())[:60]
            if s and l and not LS.OFF_TOPIC.search(s + l):
                self.log.info(f"kaju_learn: 教训 #{x['id']} 看过还犯，改写：{LS.lesson_text(x)} -> {s}：{l}")
                x["situation"], x["lesson"] = s, l
            x["revise"] = False

    async def _lesson_lines(self, text: str, kind: str, now: float) -> list[dict]:
        """这一轮挑哪几条教训给她（大脑）看：生效的、场合对得上的里面，和眼前这句意思最像的 lessons.max_show 条。"""
        rows = LS.usable(self.lessons, kind)
        text = (text or "").strip()[:300]
        if not rows or len(text) < 2:
            return []
        todo = [x for x in rows if (self._lvec.get(x["id"]) or [""])[0] != LS.vec_key(x)]
        if todo:
            vecs = await self._embed([LS.lesson_text(x) for x in todo])
            if vecs is None:
                return []
            for x, v in zip(todo, vecs):
                self._lvec[x["id"]] = [LS.vec_key(x), v]
        q = await self._embed([text])
        if not q:
            return []
        thr = float(self._cfg("lessons.threshold", 0.45))
        scored = sorted(((_cos(q[0], self._lvec[x["id"]][1]), x) for x in rows), key=lambda s: -s[0])
        picked_s = [(s, x) for s, x in scored if s >= thr][: int(self._cfg("lessons.max_show", 3))]
        picked = [x for _, x in picked_s]
        close = float(self._cfg("lessons.learned_sim", 0.6))
        for s, x in picked_s:
            LS.mark_shown(x, now, relevant=s >= close)
        if picked:
            self._dirty = True
        return picked

    def wonder_topic(self, now: float | None = None) -> dict | None:
        """她自己刷 B 站又没说看什么时：拿一件想弄明白的事去搜（同一件最多搜 2 次，每次之间隔一天）。"""
        now = now or time.time()
        if not self._cfg("enable", True) or random.random() >= float(self._cfg("wonder.browse_chance", 0.5)):
            return None
        for w in self.book.get("wonders", []):
            if not w.get("kw") or int(w.get("tried", 0)) >= 2 or now - float(w.get("tried_t", 0)) < 86400:
                continue
            w["tried"] = int(w.get("tried", 0)) + 1
            w["tried_t"] = now
            self._dirty = True
            return {"kw": w["kw"], "q": w["q"]}
        return None

    # ------------------------------------------------------------ 4. 用
    async def _hits(self, text: str, docs_text: str, now: float) -> list[tuple[str, dict]]:
        """这轮该给她看的：对方提到的（名字）、意思很近的、她正在看的东西里提到的。"""
        half = self._half()
        out: list[tuple[str, dict]] = []
        ids: set[str] = set()
        for c in sorted(B.live(self.book), key=lambda c: -B.familiarity(c)):
            if B.visible(c, now, half) and B.mentioned(c, text):
                out.append(("said", c))
                ids.add(c["id"])
        if docs_text:
            for c in sorted(B.live(self.book), key=lambda c: -B.familiarity(c)):
                if c["id"] not in ids and B.visible(c, now, half) and B.mentioned(c, docs_text[:2500]):
                    out.append(("doc", c))
                    ids.add(c["id"])
        if len(text) >= 4 and len(out) < int(self._cfg("use.max_cards", 4)):
            # 意思近的：bge-m3 实测真聊到的 ≥0.67，闲聊（"哈哈哈哈"）最高到 0.53，所以要过门槛、还要明显比第二名近；
            # 字面对上三个字（"小傻龙是谁呀"↔说明里的"小傻龙玩偶"，0.56）的放宽到 0.5；没开向量模型时字面对上就算
            grams = B.grams3(text)
            worded = {c["id"]: c for c in B.live(self.book)
                      if c["id"] not in ids and B.visible(c, now, half) and B.word_hit(c, grams)}
            scored = await self._similar(text, 10 ** 6, 0.0)
            if scored:
                top, second = scored[0][0], (scored[1][0] if len(scored) > 1 else 0.0)
                thr = float(self._cfg("embed.use_threshold", 0.62))
                # 第一名明显比第二名近，或者前两名都过了门槛（真跟两样都有关），才算"意思近"
                clear = top - second >= float(self._cfg("embed.use_margin", 0.1)) or second >= thr
                for sim, c in scored:
                    if len(out) >= int(self._cfg("use.max_cards", 4)) or sim < 0.5:
                        break
                    if c["id"] in ids or not B.visible(c, now, half):
                        continue
                    if (sim >= thr and clear) or (c["id"] in worded and sim >= float(self._cfg("embed.word_threshold", 0.5))):
                        out.append(("near", c))
                        ids.add(c["id"])
            elif worded and not self._vec:
                for c in list(worded.values())[:2]:
                    out.append(("near", c))
                    ids.add(c["id"])
        return out[: int(self._cfg("use.max_cards", 4))]

    async def inject(self, event: Turn, req: Request):
        if not self._cfg("enable", True):
            return
        if event.get_platform_name() in (self._cfg("ignore_platforms", ["webchat"]) or []):
            return
        text = (event.get_message_str() if hasattr(event, "get_message_str") else event.message_str) or ""
        if self._cfg("reading.enable", True):  # 在读 / 刚读完的书
            jobs = self.reader.jobs_for(self._chat(event), text)
            if jobs:
                now = time.time()
                req.system_prompt = (req.system_prompt or "") + "\n\n" + "\n\n".join(self.reader._note(j, now) for j in jobs)
                event.set_extra("_kl_reading", [j["id"] for j in jobs if not j.get("done")])  # 回复回来时对着实际核对
                event.set_extra("_kl_reading_all", [j["id"] for j in jobs])  # 她回的话记进 told（主动说时别重复）
                for j in jobs:
                    if j["chat"] == self._chat(event):
                        j["talked_at"] = now  # 他在这儿聊着：“好一阵没说了”从这儿算
            if self._cfg("reading.feelings", True):  # 读书、看东西时攒下的更细的心情说法（11-22）
                fn = self.reader.feelings_note()
                if fn:
                    req.system_prompt = (req.system_prompt or "") + "\n\n" + fn
        gid = str(event.get_group_id() or "")
        if gid and self._cfg("jargon.enable", True) and self._cfg("jargon.inject", True):  # 这个群的叫法（11-19）
            hits = JG.lookup(self._jargon(), gid, text, int(self._cfg("jargon.max_show", 4)),
                             guesses=bool(self._cfg("jargon.show_guesses", False)))
            if hits:
                req.system_prompt = (req.system_prompt or "") + "\n\n" + JG.note(hits)
                self.log.info("kaju_learn: 告诉她这个群的叫法：" + "、".join(f"{e['term']}={e['meaning'][:12]}" for e in hits))
        if self._cfg("lessons.enable", True) and self._cfg("lessons.inject", True):  # 以前的教训（11-19）
            kind = "群聊" if event.get_group_id() else "私聊"
            picked = await self._lesson_lines(text, kind, time.time())
            if picked:
                req.system_prompt = (req.system_prompt or "") + "\n\n" + LS.note(picked)
                self.log.info("kaju_learn: 给她看了以前的教训：" + "；".join(f"#{x['id']} {x['lesson'][:20]}" for x in picked))
        if not self._cfg("use.enable", True) or not B.live(self.book):
            return
        docs = [d for d in (event.get_extra("kaju_docs_read") or []) if isinstance(d, dict)]
        docs_text = " ".join(f"{d.get('name', '')} {str(d.get('content', ''))[:1500]}" for d in docs)
        now = time.time()
        hits = await self._hits(text[:400], docs_text, now)
        if not hits and ASK_LEARNED.search(text):  # "最近学到啥新东西了"：说不出名字，给她看最近学到的几样
            recent = sorted((c for c in B.live(self.book) if B.visible(c, now, self._half()) and c.get("what")),
                            key=lambda c: -float(c["t0"]))[:5]
            if recent:
                req.system_prompt = (req.system_prompt or "") + "\n\n" + RECENT_NOTE + "\n" + "\n".join(
                    f"- {c['name']}（{c['kind']}）：{c['what']}（{dt.datetime.fromtimestamp(c['t0'], self._tz):%m月%d日}，"
                    f"{B._src_text(c, self._chat(event)) or '不记得在哪儿'}）" for c in recent)
                event.set_extra("_kl_offered", [c["id"] for c in recent])
                self.log.info("kaju_learn: 问她最近学到什么，给她看了：" + "、".join(c["name"] for c in recent))
            return
        if not hits:
            return
        here = self._chat(event)
        lines = [B.note_line(self.book, c, now, here, self._half())
                 + ("（这次在看的东西里也有它）" if why == "doc" else "") for why, c in hits]
        wonders = [w for w in self.book.get("wonders", []) if any(w.get("about") == c["id"] for _, c in hits)]
        if wonders:
            lines.append(f"- 你一直想弄明白：{wonders[0]['q']}（正好聊到了，可以顺口问问对方）")
        req.system_prompt = (req.system_prompt or "") + "\n\n" + B.NOTE_HEAD + "\n" + "\n".join(lines)
        event.set_extra("_kl_offered", [c["id"] for _, c in hits])
        self.log.info("kaju_learn: 给她看了知道的：" + "、".join(f"{c['name']}（{B.LEVELS[B.level(c)]}）" for _, c in hits))

    async def learn_from_tool(self, event: Turn, tool, tool_args, tool_result):
        """上网查过的：查到的内容也学进去。"""
        name = str(getattr(tool, "name", "") or "")
        if name in ("reading_pace", "reading_plan"):  # 这一轮真的改过读书节奏 / 安排（核对时就不再替她改）
            event.set_extra("_kl_paced", (event.get_extra("_kl_paced") or []) + [_tool_text(tool_result)[:120]])
            return
        if not self._cfg("enable", True) or not self._cfg("web.enable", True):
            return
        if not any(name.startswith(p) for p in WEB_TOOLS):
            return
        text = _tool_text(tool_result)
        if len(text) < 80 or text.lstrip().lower().startswith("error"):
            return
        args = tool_args if isinstance(tool_args, dict) else {}
        query = str(args.get("query") or args.get("q") or args.get("keyword") or args.get("url") or "")[:80]
        said = (event.get_message_str() if hasattr(event, "get_message_str") else event.message_str) or ""
        who = self._who(str(event.get_sender_id() or ""), event.get_sender_name() or "")
        self._enqueue({"kind": "上网查到的", "title": query or said[:30], "content": text[:6000], "how": "上网查到的",
                       "who": "网上", "chat": self._chat(event),
                       "extra": f"她为什么去查：{who}问「{said[:120]}」" if said else ""})

    async def after_reply(self, event: Turn, resp: Answer):
        if not self._cfg("enable", True):
            return
        reply = MEME_TAG.sub("", getattr(resp, "completion_text", "") or "").strip()
        if reply and "[SKIP]" not in reply.upper():
            self.credit(event, reply)
            if self._cfg("reading.enable", True):
                await self._reading_after(event, reply)
        self._take_docs(event, reply)

    async def reading_check(self, event: Turn, resp: Answer):
        """草稿说的读书情况对着实际核对（2026-11-15 兄长：没读就是没读，读了就是读了）：
        - 读到哪、在不在读、读过的情节说错了 → 让模型只改说错的那几处（还是草稿，之后照常交给大脑的指导 / 回复器）；
        - 草稿里答应了现在就接着读 / 先停 / 不读了，这一轮却没调 reading_pace → 照她答应的真的改过来。
        出错、超时就照原样（不挡她说话）。"""
        ids = event.get_extra("_kl_reading")
        if not ids or getattr(resp, "tools_call_name", None) or getattr(resp, "role", "") == "err":
            return
        if event.get_extra("_ks_brain"):  # 主模型这一轮当大脑（kaju_style main_role=brain）：回来的是 JSON 指导，不是草稿，不改它
            return
        event.set_extra("_kl_reading", None)  # 一轮只看一次
        if not self._cfg("reading.check", True):
            return
        raw = getattr(resp, "completion_text", "") or ""
        tags = MEME_TAG.findall(raw)
        draft = MEME_TAG.sub("", raw).strip()
        if not draft or "[SKIP" in draft.upper():
            return
        said = (event.get_message_str() if hasattr(event, "get_message_str") else event.message_str) or ""
        jobs = [self.reader.jobs[i] for i in ids if i in self.reader.jobs]
        words = [B.clean(j["title"])[:4] for j in jobs] + [k for j in jobs for k in j["state"].get("people", {})]
        if not jobs or not (READING_WORDS.search(draft + said) or any(w and w in draft for w in words)):
            return
        paced = event.get_extra("_kl_paced") or []
        now, t0 = time.time(), time.time()
        prompt = self.reader.check_prompt(jobs, now, who=self._who(str(event.get_sender_id() or ""), event.get_sender_name() or ""),
                                          said=said, draft=draft, paced=paced)
        try:
            pid = str(self._cfg("reading.check_provider_id", "") or self._cfg("provider_id", "") or "") or await slot_model(self.body, "fast")
            out = await self.body.generate(pid, prompt, R_CHECK_SYSTEM, timeout=float(self._cfg("reading.check_timeout", 30)))
            res = parse_check(out, draft)
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_learn: 读书情况没核对成（照原样） {type(exc).__name__}: {exc}")
            return
        if not res["ok"]:
            self.log.warning(f"kaju_learn: 读书核对的回答看不懂，照原样（{time.time() - t0:.1f}s）：{(out or '')[:120]!r}")
            return
        if res["fixed"]:
            resp.completion_text = res["fixed"] + ("".join(tags) if tags else "")
            event.set_extra("_kl_read_fixed", resp.completion_text)
            self.log.info(f"kaju_learn: 草稿里读书的事说错了 {res['wrong'][:3]}，改成实际的（{time.time() - t0:.1f}s）："
                          f"{draft[:40]!r} -> {res['fixed'][:40]!r}")
        if res["commit"] and not paced:
            title = jobs[0]["title"] if len(jobs) == 1 else ""
            out = self.reader.set_pace(self._chat(event), res["commit"], title)
            self.log.info(f"kaju_learn: 她答应了「{res['commit']}」却没改，替她改了：{out}")
        if res.get("plan") and not paced:
            p = res["plan"]
            out = self.reader.set_plan(self._chat(event), p["at"], p["then"], jobs[0]["title"] if len(jobs) == 1 else "", p["edge"])
            self.log.info(f"kaju_learn: 她答应了「{p['edge']}{p['at']}就{p['then']}」却没定，替她定了：{out}")
        if not res["commit"] and not res.get("plan") and not res["fixed"]:
            self.log.info(f"kaju_learn: 读书的事核对过，没说错（{time.time() - t0:.1f}s）")

    async def _reading_after(self, event: Turn, reply: str) -> None:
        """她这句发出去以后（2026-11-22）：
        - 说起了在读的书 → 记进 told（主动说时别重复、从这儿接着说）；
        - 大脑那一轮（kaju_style main_role=brain）reading_check 看到的是 JSON 指导、不核对：这里对着她真正说出去的话，
          只看她答应了什么（接着读 / 先停 / 读到哪儿就停或告诉他）而实际还没那样的，替她真的改过来。她的话一个字不动。"""
        ids = event.get_extra("_kl_reading_all") or []
        jobs = [self.reader.jobs[i] for i in ids if i in self.reader.jobs]
        if not jobs or event.get_extra("_kl_reading_after"):
            return
        event.set_extra("_kl_reading_after", True)
        words = [B.clean(j["title"])[:4] for j in jobs] + [k for j in jobs for k in j["state"].get("people", {})]
        said = (event.get_message_str() if hasattr(event, "get_message_str") else event.message_str) or ""
        if not (READING_WORDS.search(reply + said) or any(w and w in reply for w in words)):
            return
        for j in jobs:
            if j["chat"] == self._chat(event):
                self.reader.note_reply(j, reply)
        live = [j for j in jobs if not j.get("done")]
        if not live or not event.get_extra("_ks_brain") or not self._cfg("reading.check", True):
            return
        if event.get_extra("_kl_paced"):  # 这一轮真的调过工具
            return
        prompt = self.reader.check_prompt(live, time.time(), who=self._who(str(event.get_sender_id() or ""), event.get_sender_name() or ""),
                                          said=said, draft=reply, paced=[])
        t0 = time.time()
        try:
            pid = str(self._cfg("reading.check_provider_id", "") or self._cfg("provider_id", "") or "") or await slot_model(self.body, "fast")
            out = await self.body.generate(pid, prompt, R_CHECK_SYSTEM, timeout=float(self._cfg("reading.check_timeout", 30)))
            res = parse_check(out, reply)
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_learn: 她答应的读书安排没核对成 {type(exc).__name__}: {exc}")
            return
        if not res["ok"]:
            return
        title = live[0]["title"] if len(live) == 1 else ""
        if res["commit"]:
            done = self.reader.set_pace(self._chat(event), res["commit"], title)
            self.log.info(f"kaju_learn: 她说了「{res['commit']}」却没改，替她改了：{done}")
        if res.get("plan"):
            p = res["plan"]
            done = self.reader.set_plan(self._chat(event), p["at"], p["then"], title, p["edge"])
            self.log.info(f"kaju_learn: 她答应了「{p['edge']}{p['at']}就{p['then']}」却没定，替她定了：{done}")
        if not res["commit"] and not res.get("plan"):
            self.log.info(f"kaju_learn: 她说的读书安排核对过，都做到了（{time.time() - t0:.1f}s）")

    async def reading_history(self, event: Turn, run_context, response: Answer):
        """历史里存的是核对前的草稿：kaju_style 没换成写手的话时，换成改过的那份（免得下一轮她信了说错的）。"""
        fixed = event.get_extra("_kl_read_fixed")
        if not fixed or event.get_extra("kaju_style_rewritten"):
            return
        try:
            msgs = run_context.messages
            if not msgs or msgs[-1].role != "assistant":
                return
            msg = msgs[-1]
            if isinstance(msg.content, str):
                msg.content = fixed
            elif isinstance(msg.content, list):  # 存的是一段段 text
                for part in msg.content:
                    if getattr(part, "type", None) == "text" and getattr(part, "text", None):
                        part.text = fixed
                        break
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_learn: 历史里说错的读书进度没换掉: {exc!r}")

    def credit(self, event: Turn, reply: str, now: float | None = None) -> list[str]:
        """她回复里说出了给她看的东西（对方这句没提）：算用了一次。"""
        now = now or time.time()
        said = (event.get_message_str() if hasattr(event, "get_message_str") else event.message_str) or ""
        out = []
        for cid in event.get_extra("_kl_offered") or []:
            c = B.get(self.book, cid)
            if c is None or not B.mentioned(c, reply):
                continue
            if B.mentioned(c, said) and not B.carries(c, reply, said):
                continue  # 对方说了名字、她只是跟着说名字：不算真用上
            c["used"] = int(c.get("used", 0)) + 1
            c["last_used"] = now
            out.append(c["name"])
            self._dirty = True
        if out:
            self.log.info("kaju_learn: 用上了知道的：" + "、".join(out))
        return out

    def _take_docs(self, event: Turn, reply: str) -> None:
        if not self._cfg("content.enable", True) or event.get_extra("_kl_docs_taken"):
            return
        docs = [d for d in (event.get_extra("kaju_docs_read") or []) if isinstance(d, dict)]
        if not docs:
            return
        event.set_extra("_kl_docs_taken", True)
        qq = str(event.get_sender_id() or "")
        who = self._who(qq, event.get_sender_name() or "")
        said = (event.get_message_str() if hasattr(event, "get_message_str") else event.message_str) or ""
        for d in docs:
            kind = str(d.get("kind") or "文件")
            verb = "听了" if kind == "音乐" else "看了" if "视频" in kind else "读了"
            extra = []
            if said:
                extra.append(f"{who}发来时说：{said[:150]}")
            if reply:
                extra.append(f"她看完回的：{reply[:200]}")
            self._enqueue({"kind": kind, "title": str(d.get("name") or ""), "content": str(d.get("content") or ""),
                           "how": f"{verb}{who}发的{kind}", "who": who, "chat": self._chat(event),
                           "extra": "\n".join(extra), "key": str(d.get("url") or "") or ""})

    # ------------------------------------------------------------ 她自己想一想
    async def recall_knowledge(self, event: Turn, keyword: str = ""):
        """想一想你自己以前学到、知道的东西（看过的视频和书、听别人讲过的、上网查过的）。对方问你知不知道某样东西（作品、角色、梗、歌、知识……）、你想不起细节时，或者问你最近学到了什么、懂些什么时用。

        Args:
            keyword(string): 要想的东西的名字或者话题，比如"伊蕾娜"、"蓝色大肥鱼"、"星星"；想看最近学到了什么就留空
        """
        if not self._cfg("enable", True):
            return "这个功能关掉了。"
        now = time.time()
        here = self._chat(event)
        q = str(keyword or "").strip()
        cards = [c for c in B.live(self.book) if B.visible(c, now, self._half())]
        if not cards:
            return "你还没攒下什么知道的东西。老实说不太清楚，可以好奇地问问对方。"
        if not q:
            recent = sorted(cards, key=lambda c: -c["t0"])[:8]
            lines = [f"- {c['name']}（{c['kind']}，{B.LEVELS[B.level(c)]}）：{c.get('what') or '只听说过'}" for c in recent]
            aha = [d["aha"][0] for d in self.book.get("digests", [])[-5:] if d.get("aha")]
            wonders = [w["q"] for w in self.book.get("wonders", [])]
            return ("你最近学到的：\n" + "\n".join(lines)
                    + (f"\n你想明白过：{aha[-1]}" if aha else "")
                    + (f"\n你还想弄明白：{'；'.join(wonders[:3])}" if wonders else "")
                    + "\n用自己的话挑一两样说，别念清单。")
        hits = [c for c in cards if B.mentioned(c, q) or any(q.lower() in x.lower() for x in B.names_of(c))]
        if not hits:
            hits = [c for _, c in await self._similar(q, 3, float(self._cfg("embed.known_threshold", 0.55)))]
        if not hits:
            return f"你不知道「{q}」。老实说没听过，可以好奇地问问，或者上网查一查。"
        for c in hits[:3]:
            c["last_used"] = now
        self._dirty = True
        return "你知道的：\n" + B.recall_text(self.book, hits[:3], now, here) + "\n用自己的话说，没写到的别编。"

    async def reading_pace(self, event: Turn, action: str, title: str = ""):
        """改你读那本长书的节奏。对方让你读快点、一口气读完、先停一下、接着读、不读了时用（你在读的书在【你正在读的】里）。

        Args:
            action(string): 快一点 / 一口气读完 / 慢慢读 / 先停一下 / 接着读 / 不读了
            title(string): 书名（只在读好几本时才需要）
        """
        if not self._cfg("enable", True) or not self._cfg("reading.enable", True):
            return "这个功能关掉了。"
        out = self.reader.set_pace(self._chat(event), action, str(title or "").strip())
        self.log.info(f"kaju_learn: 读书节奏 {action} → {out}")
        return out

    async def reading_plan(self, event: Turn, at: str, then: str = "告诉对方", edge: str = "读完", title: str = ""):
        """给你在读的那本长书定个安排：对方让你读到 / 读完书里某处就停下、或者读到那儿就告诉他时用（比如“读完第二部跟我说一声”“今天读到一半就停”“读完这一章就先别读了”）。定好了到时候会真的停、真的主动告诉他；定不了（书里没那个地方）就照实说。

        Args:
            at(string): 书里的哪儿：章节名（“第二部”“看星星的人”）、“这一章”、“一半”“三分之二”，或者“第25段”
            then(string): 停下 / 告诉对方 / 停下并告诉对方
            edge(string): 读完（那部分整个读完，默认）/ 读到（刚读到那儿就停）
            title(string): 书名（只在读好几本时才需要）
        """
        if not self._cfg("enable", True) or not self._cfg("reading.enable", True):
            return "这个功能关掉了。"
        out = self.reader.set_plan(self._chat(event), str(at or ""), str(then or ""), str(title or "").strip(), str(edge or "读完"))
        self.log.info(f"kaju_learn: 读书安排 {edge}{at}就{then} → {out}")
        return out

    def reading_report(self, now: float | None = None) -> str:
        now = now or time.time()
        jobs = sorted(self.reader.jobs.values(), key=lambda j: -float(j.get("t0", 0)))
        if not jobs:
            return "现在没有在读的书。"
        out = []
        for j in jobs[:8]:
            state = "读完了" if j.get("done") else {"paused": "停着", "stopped": "不读了", "all": "一口气读",
                                                    "fast": "读快点"}.get(j.get("pace"), "慢慢读")
            nxt = "" if j.get("done") or j.get("pace") in ("paused", "stopped") else \
                f"，下一段 {dt.datetime.fromtimestamp(float(j.get('next_at', now)), self._tz):%H:%M}"
            out.append(f"· 《{j['title']}》{j['who']}发的，{j['pos']}/{j['n']} 段，{state}{nxt}："
                       f"{(j.get('final') or {}).get('after') or j['state'].get('impression', '')}")
        return "\n".join(out)

    # ------------------------------------------------------------ 命令
    def report(self, what: str = "", arg: str = "", now: float | None = None) -> str:
        now = now or time.time()
        cards = B.live(self.book)
        if what in ("", "最近"):
            if not cards:
                return "还没学到什么。"
            levels = [0, 0, 0, 0]
            for c in cards:
                levels[B.level(c)] += 1
            recent = sorted(cards, key=lambda c: -c["t1"])[:15]
            lines = [f"共 {len(cards)} 样：" + "、".join(f"{B.LEVELS[i]} {n}" for i, n in enumerate(levels) if n),
                     f"排队等着学的 {len(self._state['queue'])} 样，聊天里还没看的 {sum(len(v) for v in self._state['pending'].values())} 条"]
            lines += [f"· {c['name']}〔{c['kind']}·{B.LEVELS[B.level(c)]}〕{c.get('what', '')[:30]}" for c in recent]
            log = self._state["log"][-5:]
            if log:
                lines.append("最近：")
                lines += [f"  {dt.datetime.fromtimestamp(e['t'], self._tz):%m-%d %H:%M} {e['x'][:80]}" for e in log]
            return "\n".join(lines)
        if what == "看":
            c = B.find(self.book, arg) or next((c for c in cards if arg and arg in c["name"]), None)
            if c is None:
                return f"本子里没有「{arg}」。"
            src = "；".join(f"{dt.datetime.fromtimestamp(s['t'], self._tz):%m-%d} {s.get('how', '')}{('·' + s['who']) if s.get('who') else ''}"
                           for s in c.get("srcs", [])[-6:])
            return (B.ref_line(c) + f"\n熟悉度 {B.familiarity(c):.1f}，记得 {B.strength(c, now, self._half()):.2f}，"
                    f"用过 {c.get('used', 0)} 次，碰到过 {len(c.get('days', []))} 天\n关系：{B.link_text(self.book, c) or '无'}\n"
                    f"来源：{src}" + (f"\n想明白过：{c['aha']}" if c.get("aha") else ""))
        if what == "忘掉":
            c = B.find(self.book, arg)
            if c is None:
                return f"本子里没有「{arg}」。"
            c["removed"] = True
            self._dirty = True
            return f"忘掉了「{c['name']}」。"
        if what == "好奇":
            ws = self.book.get("wonders", [])
            return "\n".join(f"· {w['q']}（搜「{w.get('kw', '')}」，搜过 {w.get('tried', 0)} 次）" for w in ws) or "现在没有特别想弄明白的。"
        if what == "在读":
            return self.reading_report(now)
        if what == "黑话":
            return JG.report(JG.load(self._dir), arg)
        if what == "例句":
            return PH.report(PH.load(paths.self_dir("kaju_style")))
        if what == "删例句":
            folder = paths.self_dir("kaju_style")
            d = PH.load(folder)
            x = next((x for x in PH.active(d) if str(x.get("id")) == arg.lstrip("#")), None)
            if x is None:
                return f"例句里没有 #{arg}。"
            x["status"] = "removed"
            PH.save(folder, d)
            return f"删掉了例句 #{x['id']}：{x['line'][:60]}"
        if what == "删黑话":
            d = JG.load(self._dir)
            for rows in d["groups"].values():
                for e in rows:
                    if e.get("status") == "active" and arg and arg.lower() in [n.lower() for n in JG.names(e)]:
                        e["status"] = "removed"
                        JG.save(self._dir, d)
                        self._jargon_cache = None
                        return f"删掉了叫法「{e['term']}」（{e['meaning']}）。"
            return f"没记着「{arg}」这个叫法。"
        return "用法：/佳树学到的 [最近｜看 名字｜忘掉 名字｜好奇｜在读｜黑话 [群号]｜删黑话 叫法｜例句｜删例句 编号｜消化｜学]"

    async def lessons_admin(self, event: Turn, action: str = "", arg: str = ""):
        if action == "删":
            x = next((x for x in self.lessons["lessons"] if str(x["id"]) == arg.lstrip("#")), None)
            if x is None:
                yield event.plain_result(f"没有 #{arg} 这条教训。")
                return
            x["status"], x["done_t"] = "removed", time.time()
            self._save_lessons()
            yield event.plain_result(f"删掉了 #{x['id']} {LS.lesson_text(x)}")
            return
        if action == "复盘":
            now = time.time()
            day = arg or (dt.datetime.fromtimestamp(now, self._tz) - dt.timedelta(days=1)).strftime("%Y-%m-%d")
            async with self._lock:
                st = await self.reflect(now, force_day=day)
                self._save()
            yield event.plain_result(f"复盘完 {day}：{st}")
            return
        learned_path = os.path.join(paths.self_dir("kaju_life"), "self_learned.json")
        try:
            with open(learned_path, encoding="utf-8") as f:
                learned = json.load(f)
        except (OSError, json.JSONDecodeError):
            learned = []
        if action == "删自己":
            r = next((r for r in learned if str(r.get("id")) == arg.lstrip("#") and r.get("status") == "active"), None)
            if r is None:
                yield event.plain_result(f"关于自己里没有 #{arg} 这条。")
                return
            r["status"] = "removed"
            with open(learned_path, "w", encoding="utf-8") as f:
                json.dump(learned, f, ensure_ascii=False, indent=1)
            yield event.plain_result(f"删掉了关于自己 #{r['id']} {r['fact']}")
            return
        act = [r for r in learned if r.get("status") == "active"]
        extra = ("\n\n从经历里学到的关于自己（" + str(len(act)) + " 条；删：/佳树教训 删自己 编号）：\n"
                 + "\n".join(f"#{r['id']} 〔{r.get('kind', '')}〕{r['fact']}\n    证据 {r.get('evidence', {}).get('day', '')}："
                             f"{r.get('evidence', {}).get('line', '')[:60]}" for r in act)) if act else ""
        yield event.plain_result(LS.report(self.lessons) + extra)

    async def admin(self, event: Turn, action: str = "", arg: str = ""):
        if action == "消化":
            async with self._lock:
                st = await self.digest(time.time())
                self._save()
            yield event.plain_result(f"理完了：{st}")
            return
        if action == "学":
            st = await self.tick()
            yield event.plain_result(f"学完一轮：{st}")
            return
        text = self.report(action, arg)
        if self._dirty:
            self._save()
        yield event.plain_result(text)
