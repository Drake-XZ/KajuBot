"""记忆轻重：让佳树记得牢的是"郑重的话"和"常用的事"，琐碎又从没用过的闲聊慢慢忘掉。

memorix 自己的遗忘对所有记忆一视同仁（关系一律 30 天半衰期，聊天摘要段落永远不忘），
也从来没把"用上过"算进去（access_count 全是 0）。这里补上三件事：

1. 记下时看分量（编码）：
   - 铭记：后台每几分钟读一遍 kaju_life 的聊天记录，挑出别人对她说的、分量重的话
     （语重心长、真心话、郑重叮嘱、诉说心事、气氛凝重时说的；约定、规矩、以后怎么称呼谁……），
     存成"铭记"——一句话 + 原话。同一件事被郑重地说了好几次，记得更牢。
   - memorix 的每条聊天记忆段落也打分量（0 琐碎闲聊 / 1 一般 / 2 要紧 / 3 郑重），参考当时的原始聊天和气氛。
2. 用上了就更牢（使用）：每轮看 memorix 给她检索出的记忆、给她看的铭记、以及她回复里出现的
   "只有某几条记忆才有的词"（比如"女王大人"），她回复里真用上了（对方这次没说过、她自己说出来的）就算用了一次：
   半衰期翻倍、从现在重新算，memorix 里对应的关系也加强一次。
3. 遗忘曲线：保留强度 = 2^(-距上次用上的天数 / 半衰期)，半衰期按分量 4 / 15 / 90 / 365 天，每用一次翻倍。
   - 分量 ≥2 或用过的：memorix 里的关系加保护，在它该被记住的期间不会被 memorix 冻结删除。
   - 分量 ≤1、强度降到 0.1 以下、至少记了 7 天的聊天摘要：从 memorix 里软删除（可以 /记忆轻重 恢复）。
     人物事实（person_fact）和导入的资料不删。
   - 铭记强度太低就不再拿给她看（不删，命令里还能看到）。

3b. 褪色（fade.py）：细节比"这件事本身"忘得快。聊天摘要的细节清晰度按分量 2 / 7 / 30 / 90 天半衰，
   当时情绪越强、想起得越多越慢，同一个聊天里差不多的事越多越快。清晰度 < 0.5 褪成"片段"，< 0.2 只剩"印象"
   （模型改写一次，两个版本一起存）。原文留在 memorix 里，只是给她看的时候换成褪色后的样子、提醒她别补细节；
   只来自褪了色的记忆的关系（细节事实）也不再给她看。她自己的心里话、人物事实不褪。

3c. 触景生情（cue.py）：对方一句话里少见的词（在她记忆里少见、平常说话里也少见）和这个聊天里一段旧记忆对上，
   按"意义 + 情绪残留 + 线索 + 新近 + 想起次数 − 干扰"算可检索性，够了就让那段记忆（长摘要只给被勾到的那一两句）
   自己冒出来，提示她可以自然带一句。memorix 这轮已经给的、琐碎的、刚聊过的不算；有冷却。

4. 珍藏的文件（shelf.py）：兄长大人分享给她的文件（kaju_basics 读过的那些）单独收好——当时读到的内容（全文或读后笔记）、
   他分享时说的话、她读完的回复和情绪（kaju_heart 的判断），原文件也复制一份。模型按分量打 1 普通 / 2 要紧 / 3 郑重
   （读完情绪波动大、兄长大人语重心长的更重），封存 30 / 180 / 365 天内一直记得清楚，之后才按遗忘曲线淡忘，
   每想起一次（她回复里用上、或者用 recall_shared_file 翻出来）半衰期翻倍。

5. 工作记忆（working.py，原 working_memory 插件）：每回完一轮，后台把刚才聊天的要点（弄清的事、图里有什么、
   她自己的推断、没弄清的）整理成一份备忘，下一轮回复前放在她眼前；90 分钟没更新或换了对话就作废。

6. 未了的事（loops.py）：对方提过、还不知道后来怎么样的事，聊到相关的或日子近了放进【还没结果的事】。

兄长大人本人是谁：读称呼簿（address_book）的 owner_qq，这里不另配。

给她看：
- 【铭记在心】这次说话的人以前郑重对她说过的话（群里只给这个群里说过的，私聊给这个人说过的全部）。
- 【珍藏的文件】这次说话的人分享给她、还记得的文件清单（同样的范围）；对方提到其中某份时，把当时读到的内容也翻出来。
  2026-11-03（1.5.0）：翻出来以后 shelf.carry_minutes（20）分钟内接着聊（"而且节奏很快""也没多少剧情"这种不提书名的话）
  也继续给，期间又碰到文件里的词就重新计时。以前只有提到文件名/关键词的那一句才给，后面几句她手里只剩书名，
  只能说"心里一沉""平平的"这种空话。对比测试（9 个真实聊书时刻 ×2，配合 kaju_style 的"说具体"）：具体 1.11→2.00。
- memorix 检索结果里，郑重的标"这是很郑重的事"，快忘了的标"记得有点模糊了"。

管理员命令：/记忆轻重 [铭记|珍藏|褪色|遗忘|删 编号|恢复 操作号|整理]、/佳树备忘（这个会话的工作记忆）
"""

from __future__ import annotations

from ..body import Answer, Request, Turn  # noqa: F401 — 只用在类型标注里
import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import zoneinfo
from collections import defaultdict
from pathlib import Path
from kaju_core import parts, paths, people  # noqa: E402
from kaju_core.memory import cue, fade, impress, loops, rater, shelf, weigh, working  # noqa: E402
from kaju_core.slots import slot_model  # noqa: E402  每项工作一格（11-18）

PLUGIN_NAME = "astrbot_plugin_memory_weight"


MEMORIX = "astrbot_plugin_memorix"


DEFAULT_OWNER = os.environ.get("KAJU_OWNER_QQ", "").strip()  # 兜底；兄长正式登记在 kaju_data\self\people\people.json


MEME_TAG = re.compile(r"&&[^&\n]{1,40}&&")


CHAT_ID = re.compile(r"^[pg]\d+$")


FORGETTABLE = ("chat_summary", "conversation")


RATED = ("chat_summary", "conversation", "person_fact")


KEEP_NOTE = (
    "\n\n【铭记在心】下面是对方以前郑重对你说过的话，你一直记在心里。不用每次都提，"
    "但该照着做的就照着做，聊到相关的事自然会想起来：\n{items}"
)


SHELF_NOTE = (
    "\n\n【珍藏的文件】下面是{who}以前分享给你、你一直好好收着的东西（文件你都读过，B站视频你看过页面和弹幕）。不用每次都提，"
    "聊到相关的会自然想起来（比如\"就像你上次给佳树看的那个故事\"）；要说里面的细节又想不起来时，"
    "用 recall_shared_file 翻出来重读一遍，别瞎编：\n{items}"
)


LOOP_NOTE = (
    "\n\n【还没结果的事】下面是{who}以前提过、你还不知道后来怎么样的事。不用每次都提；聊到相关的，"
    "或者日子到了、过了，自然会惦记：\n{items}"
)


SHELF_DETAIL = (
    "【翻出来的珍藏】对方这次提到的，可能是{who}以前分享给你的《{file}》（{date}，你读完{feeling}）。"
    "下面是你当时读到的内容，用来回想，别整段复述：\n{content}"
)


SHELF_CARRY = (
    "【还在聊的珍藏】你们刚才在聊{who}以前分享给你的《{file}》（{date}，你读完{feeling}），这句可能还在接着聊它"
    "（要是已经换了话题，就别提它）。下面是你当时读到的内容，说看法时拿里面具体的情节、人物、原话来说，别整段复述：\n{content}"
)


class MemoryMind:
    """MemoryWeight 的逻辑（AstrBot 外壳在 plugins\\memory_weight\\main.py；只认 self.body = kaju_core.body.Body）。"""

    def __init__(self, body, config: dict | None = None):
        self.body = body  # kaju_core.body.Body：模型、设置、别的部分、日志
        parts.register(PLUGIN_NAME.removeprefix("astrbot_plugin_"), self)  # 登记成她的一个部分：别的部分用 body.find 先在这里找
        self.log = body.log
        self.config = config or {}
        self._dir = paths.self_dir(PLUGIN_NAME)
        os.makedirs(self._dir, exist_ok=True)
        self._state_path = os.path.join(self._dir, "state.json")
        self._state = self._load_state()
        try:
            self._tz = zoneinfo.ZoneInfo(self.body.settings().get("timezone") or "Asia/Shanghai")
        except Exception:  # noqa: BLE001
            self._tz = dt.timezone(dt.timedelta(hours=8))
        self._lock = asyncio.Lock()
        self._docs: dict[str, dict] = {}            # memorix 段落 hash → {content, source, start, end, created}
        self._para_rels: dict[str, list[str]] = {}  # 段落 hash → 关系 hash
        self._rel_paras: dict[str, list[str]] = {}  # 关系 hash → 段落 hash
        self._kw: dict[str, set] = {}                # 记忆 id → 关键词
        self._common: set[str] = set()
        self._rare: dict[str, list[str]] = {}        # 少见的词 → 含有它的记忆 id
        self._df: dict = {}
        self._ndocs = 0
        self._last_credit: dict[str, float] = {}
        self._shelf_last: dict[str, dict] = {}     # 会话 → {"ids": 上次翻出来的珍藏, "t": 时间}（话题延续用）
        self.memo = working.WorkingMemo(self.body, lambda: self._cfg("working", {}) or {}, self._dir)
        self._task = asyncio.create_task(self._loop()) if self._cfg("enable", True) else None

    # ------------------------------------------------------------ config / state
    def _cfg(self, path: str, default=None):
        cur = self.config
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def _half_life(self) -> dict:
        hl = self._cfg("half_life_days", {}) or {}
        return {g: float(hl.get(f"g{g}", weigh.DEFAULT_HALF_LIFE[g])) for g in range(4)}

    def _load_state(self) -> dict:
        try:
            with open(self._state_path, encoding="utf-8") as f:
                st = json.load(f)
        except FileNotFoundError:
            st = {}
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"memory_weight: state.json 读不了，重新开始: {exc}")
            st = {}
        for k, v in (("log_pos", {}), ("pending", {}), ("tail", {}), ("fails", {}), ("keepsakes", []),
                     ("paras", {}), ("forgotten", []), ("moods", []), ("shelf", []), ("cue_last", {}), ("cue_chat", {}),
                     ("loops", []), ("impressions", {})):
            st.setdefault(k, v)
        return st

    def _save(self) -> None:
        self._state["forgotten"] = self._state["forgotten"][-200:]
        self._state["moods"] = self._state["moods"][-300:]
        old = time.time() - 90 * 86400  # 收起来 90 天以上的未了事不留了
        self._state["loops"] = [lp for lp in self._state["loops"]
                                if lp.get("status", "open") == "open" or float(lp.get("closed") or time.time()) > old][-400:]
        week = time.time() - 7 * 86400
        self._state["cue_last"] = {h: t for h, t in self._state["cue_last"].items() if t > week}
        tmp = self._state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._state_path)

    def _scope(self) -> str:
        return str(self._cfg("scope_key", "aiocqhttp"))

    def _mx_db(self) -> str:
        return os.path.join(paths.self_dir(MEMORIX), "scopes", self._scope(), "metadata", "metadata.db")

    def _life_log_dir(self) -> str:
        return os.path.join(paths.self_dir("kaju_life"), "log")

    def labels(self) -> dict:
        """QQ → 佳树对这个人的称呼：兄长大人本人 + 称呼簿里设过的。"""
        out = {}
        book = os.path.join(paths.self_dir("address_book"), "addresses.json")
        try:
            with open(book, encoding="utf-8") as f:
                for qq, e in json.load(f).items():
                    if isinstance(e, dict) and e.get("address"):
                        out[str(qq)] = str(e["address"])
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            pass
        for qq in self._owners():
            out[qq] = "兄长大人"
        return out

    def _memorix(self):
        for s in self.body.stars() or []:
            if getattr(s, "name", "") == MEMORIX and getattr(s, "star_cls", None) is not None:
                return s.star_cls
        return None

    async def _ask(self, system: str, prompt: str) -> str:
        return await self.body.think(prompt, system, timeout=float(self._cfg("timeout_seconds", 120)))

    # ------------------------------------------------------------ background
    async def _loop(self) -> None:
        await asyncio.sleep(float(self._cfg("first_delay_seconds", 60)))
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"memory_weight: 整理出错: {exc}")
            await asyncio.sleep(max(60.0, float(self._cfg("interval_minutes", 5)) * 60))

    async def terminate(self):
        parts.unregister(PLUGIN_NAME.removeprefix("astrbot_plugin_"), self)
        if self._task:
            self._task.cancel()
        try:
            self._save()
        except Exception:  # noqa: BLE001
            pass

    async def tick(self, now: float | None = None) -> dict:
        now = now or time.time()
        async with self._lock:
            stats = {"keep": await self.scan_logs(now)}
            if self._loops_on():
                token = str(self._cfg("loops.reset_token", "") or "")
                if token and token != self._state.get("loops_reset"):  # 改了看的提示词：清掉重看一遍（配置里换个新值才会触发）
                    self._state["loops"] = []
                    self._state.pop("loops_seeded", None)
                    self._state.pop("loops_seed_queue", None)
                    self._state["loops_reset"] = token
                    self.log.info(f"memory_weight: 未了的事清掉重看（reset_token={token}）")
                if not self._state.get("loops_seeded"):
                    stats["loops_seed"] = await self.seed_loops(now)
                stats["loops_stale"] = loops.tidy(self._state["loops"], now, self._today(now),
                                                  int(self._cfg("loops.stale_days", 7)),
                                                  undated_days=float(self._cfg("loops.undated_days", 14)))
            self.load_memorix()
            stats["rated"] = await self.rate_paragraphs(now)
            stats["impress"] = await self.build_impressions(now)
            stats.update(await self.maintain(now))
            self.reindex()
            self._save()
        if any(stats.values()):
            self.log.info(f"memory_weight: 整理完 {stats}")
        return stats

    # ------------------------------------------------------------ 1a. 铭记：读聊天记录
    async def scan_logs(self, now: float) -> int:
        folder = self._life_log_dir()
        if not os.path.isdir(folder):
            return 0
        dsh = int(self._cfg("day_start_hour", 5))
        oldest = (dt.datetime.fromtimestamp(now, self._tz) - dt.timedelta(days=14)).strftime("%Y-%m-%d")
        for fname in sorted(f for f in os.listdir(folder) if f.endswith(".jsonl")):
            day = fname[:-6]
            if day < oldest:
                continue
            pos = int(self._state["log_pos"].get(fname, 0))
            new = rater.read_log_lines(os.path.join(folder, fname), pos)
            if not new:
                continue
            self._state["log_pos"][fname] = pos + len(new)
            for r in new:
                chat = str(r.get("c", ""))
                if not CHAT_ID.match(chat):  # 网页聊天等不算
                    continue
                try:
                    r = {**r, "ts": rater.line_time(day, r.get("t", "00:00"), dsh, self._tz)}
                except ValueError:
                    continue
                self._state["pending"].setdefault(chat, []).append(r)

        settle = float(self._cfg("keepsake.settle_seconds", 120))
        max_calls = int(self._cfg("keepsake.max_calls_per_round", 6))
        added = calls = 0
        for chat in list(self._state["pending"]):
            lines = self._state["pending"][chat]
            while lines and calls < max_calls:
                if now - lines[-1]["ts"] < settle and len(lines) < 40:
                    break  # 还在聊，等安静下来再看整段
                batch = lines[:40]
                try:
                    n, called = await self._rate_batch(chat, batch)
                except Exception as exc:  # noqa: BLE001
                    fails = self._state["fails"].get(chat, 0) + 1
                    self._state["fails"][chat] = fails
                    self.log.warning(f"memory_weight: 挑铭记失败（{chat} 第{fails}次）: {exc}")
                    calls += 1
                    if fails < 3:
                        break
                    n, called = 0, False  # 连着失败 3 次就跳过这一段
                self._state["fails"].pop(chat, None)
                added += n
                calls += int(called)
                if self._loops_on():
                    await self._loop_batch(chat, batch, self._state["tail"].get(chat, [])[-8:], now)
                tail = self._state["tail"].get(chat, []) + batch
                self._state["tail"][chat] = tail[-8:]
                del lines[:len(batch)]
            if not lines:
                self._state["pending"].pop(chat, None)
        return added

    async def _rate_batch(self, chat: str, batch: list[dict]) -> tuple[int, bool]:
        min_chars = int(self._cfg("keepsake.min_chars", 10))
        cands = [r for r in batch if rater.is_candidate(r, min_chars)]
        if not cands:
            return 0, False
        if chat.startswith("g") and self._cfg("keepsake.group_needs_her", True):
            # 群里别人之间的话不是对她说的：她在这段里说过话，或者有人提到她，才看
            if not any(r.get("u") == "self" for r in batch) and not any("佳树" in str(r.get("x", "")) for r in cands):
                return 0, False
        labels = self.labels()
        before = "\n".join(rater.fmt_line(r, labels=labels) for r in self._state["tail"].get(chat, [])[-8:]) or "（无）"
        lines = "\n".join(rater.fmt_line(r, i + 1, labels) for i, r in enumerate(batch))
        qqs = {str(r.get("u")) for r in batch if r.get("u") not in (None, "", "self")}
        known = [k for k in self._state["keepsakes"] if self._ks_live(k) and k["qq"] in qqs
                 and (chat.startswith("p") or k["chat"] == chat)]
        known_text = "\n".join(f"{k['id'][:6]}: {self._who(k['qq'], k.get('name', ''))} - {k['memory']}" for k in known[-20:]) or "（无）"
        data = rater.parse_json(await self._ask(
            rater.KEEP_SYSTEM, rater.KEEP_PROMPT.format(before=before, lines=lines, scale=rater.SCALE, known=known_text)))
        if data is None:
            raise ValueError("模型没按 JSON 回")
        self._state["moods"].append({"chat": chat, "start": batch[0]["ts"], "end": batch[-1]["ts"],
                                     "mood": str(data.get("mood", ""))[:20], "level": rater.clamp_g(data.get("level"), 1)})
        added = 0
        for k in data.get("keep") or []:
            if not isinstance(k, dict):
                continue
            try:
                r = batch[int(k.get("i")) - 1]
            except (TypeError, ValueError, IndexError):
                continue
            g = rater.clamp_g(k.get("g"), 0)
            if r.get("u") == "self" or g < 2:
                continue
            memory = str(k.get("memory", "")).strip()[:80]
            quote = (str(k.get("quote", "")).strip() or str(r.get("x", "")))[:60]
            if memory:
                n = self._add_keepsake(chat, r, g, memory, quote)
                added += n
                if k.get("replaces"):
                    new_id = self._state["keepsakes"][-1]["id"] if n else ""
                    self._supersede(known, str(k["replaces"]), r["ts"], f"换成了：{memory[:30]}", new_id)
        for x in data.get("retire") or []:
            if isinstance(x, dict) and x.get("id"):
                self._supersede(known, str(x["id"]), batch[-1]["ts"], str(x.get("why", "") or "不再成立")[:30], "")
        return added, True

    @staticmethod
    def _ks_live(k: dict) -> bool:
        return not k.get("retired") and not k.get("removed") and not k.get("superseded")

    def _supersede(self, known: list[dict], key: str, ts: float, why: str, by: str) -> bool:
        """铭记作废线（2026-11-18 照 dsh-soul 的 supersedes）：旧的那条留着、标上被什么取代 / 为什么不再成立，不再给她看。
        只认这次给模型看过的那几条（known），编号要对得上唯一一条；新的一条取代的就是它自己（合并进去了）不算。"""
        key = key.strip()
        hit = [k for k in known if key and k["id"].startswith(key) and self._ks_live(k)]
        if len(hit) != 1 or (by and hit[0]["id"] == by):
            return False
        k = hit[0]
        k.update({"superseded": True, "superseded_at": ts, "superseded_why": why, "superseded_by": by})
        self.log.info(f"memory_weight: 铭记不再成立（{why}）{k['memory'][:40]}")
        return True

    def _add_keepsake(self, chat: str, r: dict, g: int, memory: str, quote: str) -> int:
        qq = str(r.get("u", ""))
        for ks in self._state["keepsakes"]:
            if ks["qq"] != qq:
                continue
            if ks.get("removed") or ks.get("superseded"):
                continue
            if weigh.overlap(ks["memory"], memory) >= 0.4 or weigh.overlap(ks["quote"], quote) >= 0.5:
                ks["g"] = max(ks["g"], g)
                if r["ts"] - ks.get("last_said", ks["created"]) > 3600:  # 过了一阵又郑重说了一遍 → 更牢
                    ks["said"] = ks.get("said", 1) + 1
                    ks["uses"] = ks.get("uses", 0) + 1
                    ks["last_used"] = r["ts"]
                    ks["retired"] = False
                ks["last_said"] = r["ts"]
                return 0
        kid = hashlib.sha1(f"{chat}|{qq}|{r['ts']}|{quote}".encode()).hexdigest()[:10]
        self._state["keepsakes"].append({
            "id": kid, "qq": qq, "name": str(r.get("n", "")), "chat": chat, "memory": memory, "quote": quote,
            "g": g, "created": r["ts"], "last_said": r["ts"], "said": 1, "uses": 0, "last_used": None, "retired": False,
        })
        self.log.info(f"memory_weight: 新铭记（分量{g}）{memory} ——「{quote}」")
        return 1

    # ------------------------------------------------------------ 1b. memorix 段落打分量
    def load_memorix(self) -> None:
        path = self._mx_db()
        if not os.path.exists(path):
            self._docs, self._para_rels = {}, {}
            return
        try:
            con = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True, timeout=5)
            try:
                rows = con.execute(
                    "SELECT hash, content, source, created_at, event_time_start, event_time_end "
                    "FROM paragraphs WHERE is_deleted = 0").fetchall()
                rels = con.execute("SELECT paragraph_hash, relation_hash FROM paragraph_relations").fetchall()
            finally:
                con.close()
        except sqlite3.Error as exc:
            self.log.warning(f"memory_weight: 读 memorix 数据库失败: {exc}")
            return
        self._docs = {h: {"content": c or "", "source": s or "", "created": float(ca or 0),
                          "start": float(es or ca or 0), "end": float(ee or es or ca or 0)}
                      for h, c, s, ca, es, ee in rows}
        pr: dict[str, list[str]] = defaultdict(list)
        rp: dict[str, list[str]] = defaultdict(list)
        for ph, rh in rels:
            pr[ph].append(rh)
            rp[rh].append(ph)
        self._para_rels = dict(pr)
        self._rel_paras = dict(rp)

    def _emotion_at(self, chat_id: str, start: float, end: float) -> tuple[float, str]:
        """这段聊天当时她的情绪有多强（0~1）、是什么感觉：先看 kaju_heart 的判断，没有就看挑铭记时记下的气氛。"""
        e, feels = 0.0, []
        try:
            with open(os.path.join(paths.self_dir("kaju_heart"), "state.json"), encoding="utf-8") as f:
                events = json.load(f).get("events") or []
        except (OSError, json.JSONDecodeError, AttributeError):
            events = []
        for ev in events:
            if not isinstance(ev, dict) or str(ev.get("umo", "")).rsplit(":", 1)[-1] != chat_id:
                continue
            if start - 600 <= float(ev.get("t", 0)) <= end + 600:
                e = max(e, min(3, int(ev.get("i", 0) or 0)) / 3)
                if ev.get("emo") and int(ev.get("i", 0) or 0) >= 1:
                    feels.append(str(ev["emo"]))
        for m in self._state["moods"]:
            if m["chat"][1:] == chat_id and m["end"] >= start - 600 and m["start"] <= end + 600:
                e = max(e, int(m.get("level", 0)) / 3 * 0.6)
                if not feels and m.get("mood"):
                    feels.append(m["mood"])
        return round(e, 2), "、".join(dict.fromkeys(feels))[:30]

    def _context_lines(self, chat_id: str, start: float, end: float, limit: int = 10) -> list[dict]:
        folder = self._life_log_dir()
        if not chat_id or not os.path.isdir(folder):
            return []
        dsh = int(self._cfg("day_start_hour", 5))
        lo, hi = start - 600, end + 600
        out = []
        d0 = dt.datetime.fromtimestamp(lo, self._tz).date() - dt.timedelta(days=1)
        d1 = dt.datetime.fromtimestamp(hi, self._tz).date()
        d = d0
        while d <= d1:
            day = d.isoformat()
            for r in rater.read_log_lines(os.path.join(folder, day + ".jsonl")):
                if r.get("c") not in (f"p{chat_id}", f"g{chat_id}"):
                    continue
                try:
                    ts = rater.line_time(day, r.get("t", "00:00"), dsh, self._tz)
                except ValueError:
                    continue
                if lo <= ts <= hi:
                    out.append(r)
            d += dt.timedelta(days=1)
        if len(out) > limit:  # 均匀挑，优先保留长一点的
            step = len(out) / limit
            out = [max(out[int(i * step):int((i + 1) * step)] or [out[-1]], key=lambda x: len(str(x.get("x", ""))))
                   for i in range(limit)]
        return out

    def _mood_text(self, chat_id: str, start: float, end: float) -> str:
        moods = [m["mood"] for m in self._state["moods"]
                 if m["chat"][1:] == chat_id and m["end"] >= start - 600 and m["start"] <= end + 600 and m["mood"]]
        return "、".join(dict.fromkeys(moods)) or "不清楚"

    async def rate_paragraphs(self, now: float) -> int:
        paras = self._state["paras"]
        todo = [h for h, d in self._docs.items()
                if d["source"].startswith(RATED) and (h not in paras or paras[h].get("g") is None)]
        todo.sort(key=lambda h: self._docs[h]["created"])
        size, max_batches = 6, int(self._cfg("paragraph.max_batches_per_round", 4))
        done = 0
        labels = self.labels()
        for b in range(0, min(len(todo), size * max_batches), size):
            batch = todo[b:b + size]
            items = []
            for j, h in enumerate(batch, 1):
                d = self._docs[h]
                cid = rater.chat_of_source(d["source"])
                ctx = self._context_lines(cid, d["start"], d["end"])
                ctx_text = "\n".join(rater.fmt_line(r, labels=labels) for r in ctx) or "（找不到）"
                items.append(f"【记录 {j}】{d['content'][:300]}\n当时的聊天：\n{ctx_text}\n当时的气氛：{self._mood_text(cid, d['start'], d['end'])}")
            try:
                data = rater.parse_json(await self._ask(
                    rater.PARA_SYSTEM, rater.PARA_PROMPT.format(scale=rater.SCALE, items="\n\n".join(items))))
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"memory_weight: 给记忆打分量失败: {exc}")
                break
            scores = {}
            for s in (data or {}).get("scores") or []:
                if isinstance(s, dict):
                    try:
                        scores[int(s.get("id"))] = rater.clamp_g(s.get("g"), 1)
                    except (TypeError, ValueError):
                        pass
            if not scores:
                self.log.warning("memory_weight: 打分量的回复解析不了，下次再试")
                break
            for j, h in enumerate(batch, 1):
                d = self._docs[h]
                g = max(scores.get(j, 1), self._keepsake_gravity_near(d))
                old = paras.get(h, {})
                e, feel = self._emotion_at(rater.chat_of_source(d["source"]), d["start"], d["end"])
                paras[h] = {"g": g, "src": d["source"], "created": d["created"] or now,
                            "uses": old.get("uses", 0), "last_used": old.get("last_used"), "prot": old.get("prot", 0),
                            "rated": now, "e": e, "feel0": feel}
                done += 1
        return done

    def _keepsake_gravity_near(self, d: dict) -> int:
        cid = rater.chat_of_source(d["source"])
        g = 0
        for ks in self._state["keepsakes"]:
            if ks["chat"][1:] == cid and d["start"] - 1800 <= ks["created"] <= d["end"] + 1800:
                g = max(g, ks["g"])
        return g

    # ------------------------------------------------------------ 3. 遗忘曲线
    async def maintain(self, now: float) -> dict:
        table = self._half_life()
        threshold = float(self._cfg("forget.threshold", 0.1))
        min_age = float(self._cfg("forget.min_age_days", 7)) * 86400
        max_forget = int(self._cfg("forget.max_per_round", 5))
        forget_on = bool(self._cfg("forget.enable", True))
        mx = self._memorix()
        protected = forgotten = faded = 0
        paras = self._state["paras"]
        fade_on = bool(self._cfg("fade.enable", True))
        max_fade = int(self._cfg("fade.max_per_round", 3))
        if fade_on:
            self._update_fade_inputs(now)
        for h in list(paras):
            p = paras[h]
            if h not in self._docs:
                if self._docs:  # memorix 那边已经没有了（被删 / 合并）
                    paras.pop(h)
                continue
            if p.get("g") is None:
                continue
            r = weigh.retention(p, now, table)
            if (p["g"] >= 2 or p.get("uses", 0) >= 1) and mx is not None and protected < 60:
                life = weigh.days_until(p, now, threshold, table)
                until = now + min(life, 365.0) * 86400
                if p.get("prot", 0) < now + 7 * 86400 and until - p.get("prot", 0) > 86400:
                    for rel in self._para_rels.get(h, [])[:20]:
                        try:
                            await mx.memory_service.protect(scope_key=self._scope(), query_or_hash=rel,
                                                            hours=(until - now) / 3600)
                        except Exception as exc:  # noqa: BLE001
                            self.log.debug(f"memory_weight: 保护关系失败 {rel[:8]}: {exc}")
                    p["prot"] = until
                    protected += 1
            if (forget_on and mx is not None and forgotten < max_forget and p["g"] <= 1
                    and p["src"].startswith(FORGETTABLE) and r < threshold and now - p["created"] >= min_age):
                try:
                    res = await mx.admin_service.delete_admin(scope_key=self._scope(), action="execute",
                                                              mode="paragraph", hash=h)
                except Exception as exc:  # noqa: BLE001
                    self.log.warning(f"memory_weight: 忘掉 {h[:8]} 失败: {exc}")
                    continue
                if isinstance(res, dict) and res.get("success") is False:
                    self.log.warning(f"memory_weight: 忘掉 {h[:8]} 失败: {res.get('error')}")
                    continue
                op = (res or {}).get("operation_id") or ((res or {}).get("operation") or {}).get("operation_id", "")
                self._state["forgotten"].append({
                    "hash": h, "content": self._docs[h]["content"][:120], "g": p["g"], "uses": p.get("uses", 0),
                    "created": p["created"], "at": now, "op": op})
                self.log.info(f"memory_weight: 忘掉了（分量{p['g']}，用过{p.get('uses', 0)}次）{self._docs[h]['content'][:60]}")
                paras.pop(h)
                self._docs.pop(h, None)
                forgotten += 1
                continue
            if fade_on and faded < max_fade and fade.can_fade(p["src"], self._docs[h]["content"]):
                faded += await self._fade_one(h, p, now)
        retired = 0
        for ks in self._state["keepsakes"]:
            if self._ks_live(ks) and weigh.retention(ks, now, table) < threshold:
                ks["retired"] = True
                retired += 1
        return {"protected": protected, "forgotten": forgotten, "faded": faded, "retired": retired}

    # ------------------------------------------------------------ 3b. 褪色
    def _fade_kw(self) -> dict:
        t = self._cfg("fade.detail_half_life_days", {}) or {}
        return {"table": {g: float(t.get(f"g{g}", fade.DETAIL_HALF_LIFE[g])) for g in range(4)},
                "emotion_slow": float(self._cfg("fade.emotion_slow", 1.0)),
                "interference_fast": float(self._cfg("fade.interference_fast", 0.5))}

    def _fade_level(self, p: dict, now: float) -> int:
        return fade.level(p, now, frag_below=float(self._cfg("fade.fragments_below", 0.5)),
                          gist_below=float(self._cfg("fade.gist_below", 0.2)), **self._fade_kw())

    def _update_fade_inputs(self, now: float) -> None:
        """补上情绪强度（以前打分量时没记的），每天重算一次"差不多的事有几条"（干扰）。"""
        paras = self._state["paras"]
        for h, p in paras.items():
            if p.get("g") is not None and "e" not in p and h in self._docs:
                d = self._docs[h]
                p["e"], p["feel0"] = self._emotion_at(rater.chat_of_source(d["source"]), d["start"], d["end"])
        day = dt.datetime.fromtimestamp(now, self._tz).date().isoformat()
        if self._state.get("interf_day") == day or not self._kw:
            return
        ids = {f"p:{h}": self._docs[h]["source"] for h, p in paras.items()
               if h in self._docs and fade.can_fade(p.get("src", ""), self._docs[h]["content"])}
        scores = fade.interference({i: self._kw.get(i, set()) for i in ids}, ids, self._common)
        for i, v in scores.items():
            paras[i[2:]]["i"] = round(v, 2)
        self._state["interf_day"] = day

    async def _fade_one(self, h: str, p: dict, now: float) -> int:
        if p.get("g") is None:
            return 0
        lv = self._fade_level(p, now)
        if lv <= int(p.get("fade", 0) or 0):
            return 0
        if not p.get("frag"):
            fails = self._state["fails"].get(f"fade:{h}", 0)
            if fails >= 3:
                return 0
            content = self._docs[h]["content"]
            try:
                res = fade.parse(await self._ask(fade.FADE_SYSTEM, fade.build_prompt(
                    content, (now - float(p.get("created") or now)) / 86400, p.get("feel0", ""), self._name_book())),
                    content)
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"memory_weight: 褪色失败 {h[:8]}: {exc}")
                res = None
            if not res:
                self._state["fails"][f"fade:{h}"] = fails + 1
                return 1  # 也算一次调用，免得一轮里连着失败
            self._state["fails"].pop(f"fade:{h}", None)
            p.update(res)
        p["fade"] = lv
        p.setdefault("fade_at", {})[str(lv)] = now
        shown_text, _ = fade.shown(p)
        self.log.info(f"memory_weight: 记忆褪成{fade.LEVEL_NAMES[lv]}（分量{p['g']}，情绪{p.get('e', 0)}，"
                    f"干扰{p.get('i', 0)}）{self._docs[h]['content'][:40]} → {shown_text[:60]}")
        return 1

    def _name_book(self) -> list[tuple[str, str]]:
        """称呼簿：(群名/昵称, 佳树对TA的称呼)。"""
        try:
            with open(os.path.join(paths.self_dir("address_book"), "addresses.json"), encoding="utf-8") as f:
                return [(str(e.get("nickname", "")), str(e.get("address", ""))) for e in json.load(f).values()
                        if isinstance(e, dict)]
        except (OSError, json.JSONDecodeError, AttributeError):
            return []

    def faded_rel(self, rel12: str) -> bool:
        """这条关系是不是只来自褪了色的记忆（细节已经忘了）。"""
        for rh, phs in self._rel_paras.items():
            if rh.startswith(rel12):
                ps = [self._state["paras"].get(ph) for ph in phs]
                return bool(ps) and all(p and int(p.get("fade", 0) or 0) >= 1 for p in ps)
        return False

    # ------------------------------------------------------------ 2. 用上了就更牢
    def reindex(self) -> None:
        book = os.path.join(paths.self_dir("address_book"), "addresses.json")
        try:
            with open(book, encoding="utf-8") as f:
                entries = json.load(f).values()
            weigh.add_words([e.get("address", "") for e in entries] + [e.get("nickname", "") for e in entries])
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            pass
        paras = self._state["paras"]
        docs = {f"p:{h}": (fade.shown(paras[h])[0] if h in paras else "") or d["content"] for h, d in self._docs.items()}
        docs.update({f"k:{ks['id']}": ks["memory"] + " " + ks["quote"]
                     for ks in self._state["keepsakes"] if self._ks_live(ks)})
        self._kw = {i: weigh.keywords(t) for i, t in docs.items()}
        df = weigh.doc_freq(list(self._kw.values()))
        self._df, self._ndocs = df, len(docs)
        self._common = weigh.common_terms(df, len(docs))
        rare: dict[str, list[str]] = defaultdict(list)
        for i, kws in self._kw.items():
            for t in kws:
                if len(t) >= 3 and df[t] <= 3:
                    rare[t].append(i)
        self._rare = dict(rare)

    # ------------------------------------------------------------ 6. 未了的事（loops.py）
    def _loops_on(self) -> bool:
        return bool(self._cfg("enable", True)) and bool(self._cfg("loops.enable", True))

    def _today(self, ts: float) -> dt.date:
        return dt.datetime.fromtimestamp(ts, self._tz).date()

    async def _loop_ask(self, system: str, prompt: str) -> str:
        pid = await slot_model(self.body, "memory", str(self._cfg("loops.provider_id", "") or "").strip())
        if not pid:
            return await self._ask(system, prompt)
        return await self.body.generate(pid, prompt, system, timeout=float(self._cfg("timeout_seconds", 120)))

    async def _loop_batch(self, chat: str, batch: list[dict], before: list[dict], now: float) -> int:
        """看一段聊天：有没有新的还没结果的事、记着的有没有下文。出错只记一行，不影响别的。返回调了几次模型。"""
        others = [r for r in batch if r.get("u") not in (None, "", "self")
                  and len(str(r.get("x", "")).strip()) >= 2 and not re.fullmatch(r"\[[^\]]{0,10}\]", str(r.get("x", "")).strip())]
        if not others:
            return 0
        if chat.startswith("g") and self._cfg("loops.group_needs_her", True):
            if not any(r.get("u") == "self" for r in batch) and not any("佳树" in str(r.get("x", "")) for r in others):
                return 0
        qqs = {str(r.get("u")) for r in others}
        known = [lp for lp in self._state["loops"] if any(loops.visible(lp, q, chat) for q in qqs)]
        labels = self.labels()
        at = float(batch[-1].get("ts") or now)
        today = self._today(at)
        first = self._today(float(batch[0].get("ts") or at))
        dated = lambda r: {**r, "t": f"{loops.day_tag(self._today(float(r.get('ts') or at)))} {r.get('t', '')}"}  # noqa: E731
        prompt = loops.PROMPT.format(
            today=loops.span_text(first, today),
            calendar=loops.calendar_text(first, ahead=(today - first).days + 13, weeks=first == today),
            before="\n".join(rater.fmt_line(dated(r), labels=labels) for r in before) or "（无）",
            lines="\n".join(rater.fmt_line(dated(r), i + 1, labels) for i, r in enumerate(batch)),
            known=loops.known_text(known, today, lambda lp: self._who(lp["qq"], lp.get("name", ""))))
        try:
            data = loops.parse_json(await self._loop_ask(loops.SYSTEM, prompt))
            if data is None:
                raise ValueError("模型没按 JSON 回")
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"memory_weight: 看未了的事失败（{chat}）: {exc}")
            return 1
        before_ids = {lp["id"] for lp in self._state["loops"]}
        added, changed = loops.apply(self._state["loops"], data, batch, chat, at, self._today)
        for lp in self._state["loops"]:
            if lp["id"] not in before_ids:
                self.log.info(f"memory_weight: 新的未了的事 [{lp['imp']}/{lp['care']}] {lp['what']}"
                              + (f"（{lp['date']}）" if lp.get("date") else ""))
        if changed:
            self.log.info(f"memory_weight: 未了的事有了下文 {changed} 件")
        return 1

    async def seed_loops(self, now: float) -> int:
        """第一次打开：最近 seed_days 天的聊天记录从头看一遍（分几轮做完，每轮最多 seed_calls_per_round 段）。"""
        q = self._state.get("loops_seed_queue")
        if q is None:
            q = []
            folder, dsh = self._life_log_dir(), int(self._cfg("day_start_hour", 5))
            oldest = (dt.datetime.fromtimestamp(now, self._tz)
                      - dt.timedelta(days=int(self._cfg("loops.seed_days", 7)))).strftime("%Y-%m-%d")
            rows: dict[str, list[dict]] = {}
            for fname in sorted(f for f in os.listdir(folder) if f.endswith(".jsonl")) if os.path.isdir(folder) else []:
                day = fname[:-6]
                if day < oldest:
                    continue
                for r in rater.read_log_lines(os.path.join(folder, fname)):
                    chat = str(r.get("c", ""))
                    if not CHAT_ID.match(chat):
                        continue
                    try:
                        r = {**r, "ts": rater.line_time(day, r.get("t", "00:00"), dsh, self._tz)}
                    except ValueError:
                        continue
                    rows.setdefault(chat, []).append(r)
            for chat, lines in rows.items():
                for i in range(0, len(lines), 40):
                    q.append({"chat": chat, "before": lines[max(0, i - 8):i], "lines": lines[i:i + 40]})
            q.sort(key=lambda b: b["lines"][0]["ts"])
            self._state["loops_seed_queue"] = q
        calls = 0
        while q and calls < int(self._cfg("loops.seed_calls_per_round", 8)):
            b = q.pop(0)
            calls += await self._loop_batch(b["chat"], b["lines"], b["before"], now)
        if not q:
            self._state.pop("loops_seed_queue", None)
            self._state["loops_seeded"] = now
            self.log.info("memory_weight: 未了的事补看完了")
        return calls

    # ------------------------------------------------------------ 人物印象（impress.py，11-19）
    async def build_impressions(self, now: float) -> int:
        """每天一次（impress.hour 点以后）：最近 days 天说话不少于 min_lines 句的人，各综合一份印象，一天最多 max_people 人。
        上次写过、之后又说了不到 refresh_lines 句的不重写。返回这次写了几个人。"""
        if not self._cfg("impress.enable", True):
            return 0
        local = dt.datetime.fromtimestamp(now, self._tz)
        today = local.strftime("%Y-%m-%d")
        if self._state.get("impress_day") == today or local.hour < int(self._cfg("impress.hour", 4)):
            return 0
        days = int(self._cfg("impress.days", 14))
        lines = self._people_lines(now, days)
        imps = self._state["impressions"]
        cand = []
        for qq, rows in lines.items():
            if len(rows) < int(self._cfg("impress.min_lines", 12)):
                continue
            old = imps.get(qq) or {}
            fresh = sum(1 for r in rows if r["ts"] > float(old.get("t", 0)))
            if old and fresh < int(self._cfg("impress.refresh_lines", 10)):
                continue
            cand.append((fresh, qq, rows))
        cand.sort(key=lambda x: -x[0])
        done = 0
        labels = self.labels()
        for _, qq, rows in cand[: int(self._cfg("impress.max_people", 8))]:
            name = str(rows[-1].get("n") or qq)
            call = labels.get(qq, "")
            who = f"{name}（QQ {qq}" + (f"，佳树叫TA{call}" if call and call != name else "") + "）"
            said = "\n".join(f"{r['day'][5:]} {r.get('t', '')} {str(r.get('x', '')).replace(chr(10), ' / ')[:120]}"
                             for r in rows[-int(self._cfg("impress.max_lines", 80)):])
            facts = "\n".join(f"- {x}" for x in self._relations_of({name, call, *{str(r.get('n') or '') for r in rows}} - {""}))
            prompt = impress.PROMPT.format(who=who, lines=said[-5000:], facts=facts or "（没有）",
                                           old=impress.old_text((imps.get(qq) or {}).get("imp")))
            try:
                imp = impress.parse(await self._ask(impress.SYSTEM, prompt))
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"memory_weight: 给 {name} 写印象出错 {type(exc).__name__}: {exc}")
                break
            if imp is None:
                continue
            imps[qq] = {"imp": imp, "name": call or name, "t": now, "lines": len(rows)}
            done += 1
            self.log.info(f"memory_weight: {name} 的印象：{impress.text(call or name, imp)[:120]}")
        self._state["impress_day"] = today
        return done

    def _people_lines(self, now: float, days: int) -> dict[str, list[dict]]:
        """最近 days 天每个人自己说的话（kaju_life 聊天记录；不含她自己）。"""
        folder = self._life_log_dir()
        out: dict[str, list[dict]] = {}
        if not os.path.isdir(folder):
            return out
        oldest = (dt.datetime.fromtimestamp(now, self._tz) - dt.timedelta(days=days)).strftime("%Y-%m-%d")
        for fname in sorted(f for f in os.listdir(folder) if f.endswith(".jsonl") and f[:-6] >= oldest):
            day = fname[:-6]
            for r in rater.read_log_lines(os.path.join(folder, fname), 0):
                qq = str(r.get("u") or "")
                if not qq.isdigit() or str(r.get("x", "")).startswith("["):  # 她自己、私信别的平台、纯图 / 表情
                    continue
                try:
                    ts = rater.line_time(day, r.get("t", "00:00"), int(self._cfg("day_start_hour", 5)), self._tz)
                except ValueError:
                    continue
                out.setdefault(qq, []).append({**r, "day": day, "ts": ts})
        return out

    def _relations_of(self, names: set[str], limit: int = 40) -> list[str]:
        """memorix 里这个人（按名字）没作废的关系，最新的 limit 条。"""
        if not names or not os.path.exists(self._mx_db()):
            return []
        import sqlite3
        try:
            db = sqlite3.connect(f"file:{self._mx_db()}?mode=ro", uri=True)
            q = ",".join("?" * len(names))
            rows = db.execute(f"select subject, predicate, object from relations where is_inactive=0 and subject in ({q}) "
                              f"order by created_at desc limit {int(limit)}", list(names)).fetchall()
            db.close()
        except Exception:  # noqa: BLE001
            return []
        return [f"{s} {p} {o}" for s, p, o in rows]

    async def swap_profiles(self, event: Turn, req: Request):
        """memorix 这轮放进来的【人物画像-内部参考】：有印象的人换成印象（11-19）。"""
        if not self._cfg("impress.enable", True) or not self._cfg("impress.inject", True):
            return
        imps = self._state.get("impressions") or {}
        if not imps:
            return
        names = {q: v.get("name") or q for q, v in imps.items()}
        swapped: list[str] = []
        for part in getattr(req, "extra_user_content_parts", None) or []:
            t = getattr(part, "text", None)
            if isinstance(t, str) and impress.PROFILE_HEAD in t:
                new, have = impress.swap_profiles(t, imps, names)
                if have:
                    part.text = new
                    swapped += have
        if req.system_prompt and impress.PROFILE_HEAD in req.system_prompt:
            req.system_prompt, have = impress.swap_profiles(req.system_prompt, imps, names)
            swapped += have
        if swapped:
            self.log.info("memory_weight: 人物画像换成印象：" + "、".join(names.get(q, q) for q in swapped))

    def loops_for(self, event: Turn, now: float | None = None) -> list[dict]:
        now = now or time.time()
        text = (event.get_message_str() if hasattr(event, "get_message_str") else event.message_str) or ""
        return loops.pick(
            self._state["loops"], str(event.get_sender_id() or ""), self._chat(event), weigh.keywords(text),
            lambda lp: weigh.keywords(lp["what"]), now, self._today(now),
            max_n=int(self._cfg("loops.max_inject", 3)), near_days=int(self._cfg("loops.near_days", 2)),
            high=float(self._cfg("loops.high_priority", 15.0)), cooldown_h=float(self._cfg("loops.cooldown_hours", 6)),
            min_imp_near=int(self._cfg("loops.min_imp_near", 5)))

    async def inject_loops(self, event: Turn, req: Request):
        if not self._loops_on():
            return
        now = time.time()
        items = self.loops_for(event, now)
        if not items:
            return
        sender = str(event.get_sender_id() or "")
        who = self._who(sender, event.get_sender_name() or "") or "对方"
        req.system_prompt = (req.system_prompt or "") + LOOP_NOTE.format(
            who=who, items="\n".join(loops.note_lines(items, self._today(now), self._tz)))
        for lp in items:
            lp["last_shown"] = now
            lp["shown"] = int(lp.get("shown", 0) or 0) + 1
        event.set_extra("memory_weight_loops", [lp["id"] for lp in items])
        self._save()
        self.log.info(f"memory_weight: 给她看未了的事 {'；'.join(lp['what'] for lp in items)}")

    def _chat(self, event: Turn) -> str:
        gid = str(event.get_group_id() or "")
        return f"g{gid}" if gid else f"p{event.get_sender_id()}"

    def keepsakes_for(self, event: Turn, now: float | None = None) -> list[dict]:
        now = now or time.time()
        sid, chat = str(event.get_sender_id() or ""), self._chat(event)
        private = chat.startswith("p")
        table = self._half_life()
        items = [k for k in self._state["keepsakes"]
                 if self._ks_live(k) and k["qq"] == sid and (private or k["chat"] == chat)]
        items.sort(key=lambda k: (-k["g"], -weigh.retention(k, now, table)))
        return items[: int(self._cfg("keepsake.max_inject", 4))]

    async def inject_keepsakes(self, event: Turn, req: Request):
        if not self._cfg("enable", True) or not self._cfg("keepsake.enable", True):
            return
        items = self.keepsakes_for(event)
        if not items:
            return
        lines = []
        for k in items:
            d = dt.datetime.fromtimestamp(k["created"], self._tz)
            lines.append(f"- {d.month}月{d.day}日：{k['memory']}（原话：「{k['quote']}」）")
        req.system_prompt = (req.system_prompt or "") + KEEP_NOTE.format(items="\n".join(lines))
        event.set_extra("memory_weight_keepsakes", [k["id"] for k in items])

    def _resolve12(self, h12: str) -> str:
        for h in self._docs:
            if h.startswith(h12):
                return h
        return ""

    async def collect_offered(self, event: Turn, req: Request):
        if not self._cfg("enable", True):
            return
        table, now = self._half_life(), time.time()
        offered = []
        for part in req.extra_user_content_parts or []:
            text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
            if not isinstance(text, str) or weigh.MEMORIX_MARKER not in text:
                continue
            labels, swaps, drops = {}, {}, set()
            fade_on = self._cfg("fade.enable", True)
            for hit in weigh.parse_hits(text):
                full = self._resolve12(hit["hash12"])
                if full:
                    p = self._state["paras"].get(full)
                    faded_text, fade_label = fade.shown(p) if p and fade_on else ("", "")
                    offered.append({"id": f"p:{full}", "text": faded_text or self._docs[full]["content"]})
                    if faded_text:  # 原文还在 memorix 里，她想得起来的只有褪色后的样子
                        swaps[hit["line"]] = faded_text
                    if p and p.get("g") is not None:
                        notes = []
                        if p["g"] >= 3:
                            notes.append("这是很郑重的事，要放在心上")
                        if fade_label:
                            notes.append(fade_label)
                        elif weigh.retention(p, now, table) < 0.35:
                            notes.append("记得有点模糊了")
                        if notes:
                            labels[hit["line"]] = "；".join(notes)
                elif hit["type"] == "relation":
                    if fade_on and self.faded_rel(hit["hash12"]):
                        drops.add(hit["line"])  # 只来自褪了色的记忆的细节，已经想不起来了
                        continue
                    offered.append({"id": f"r:{hit['hash12']}", "text": hit["content"]})
            if not self._cfg("annotate_hits", True):  # 褪色的标注一定要留：不然她会把片段当成全部
                labels = {i: lab for i, lab in labels.items() if i in swaps}
            if labels or swaps or drops:
                lines = text.split("\n")
                for i, t in swaps.items():
                    lines[i] = fade.replace_hit(lines[i], t)
                new_text = "\n".join(line for i, line in enumerate(weigh.annotate("\n".join(lines), labels).split("\n"))
                                     if i not in drops)
                if isinstance(part, dict):
                    part["text"] = new_text
                else:
                    part.text = new_text
        event.set_extra("memory_weight_offered", offered)

    # ------------------------------------------------------------ 5. 触景生情（cue.py）
    def find_cue(self, chat_id: str, text: str, now: float, skip: set[str] | None = None) -> dict | None:
        """这句话有没有勾起这个聊天里一段（不是这轮 memorix 已经给她看的）旧记忆；返回可检索性最高的那段。"""
        msg_kw = weigh.keywords(text or "")
        if not msg_kw or not self._kw:
            return None
        skip = skip or set()
        min_age = float(self._cfg("cue.min_age_hours", 12)) * 3600
        cool = float(self._cfg("cue.memory_cooldown_hours", 72)) * 3600
        min_cue, need = float(self._cfg("cue.min_cue", 0.35)), float(self._cfg("cue.threshold", 0.5))
        need_inner = float(self._cfg("cue.inner_threshold", 0.45))  # 她自己的心里话（感觉）最容易被勾起来
        best = None
        for h, d in self._docs.items():
            p = self._state["paras"].get(h)
            if (not p or p.get("g") is None or h in skip or rater.chat_of_source(d["source"]) != chat_id
                    or not d["source"].startswith(fade.FADEABLE) or now - d["created"] < min_age
                    or now - float(self._state["cue_last"].get(h, 0)) < cool):
                continue
            inner = d["content"].startswith(fade.INNER_PREFIX)
            if not cue.worth(p, inner):
                continue
            score, terms = cue.cue_score(msg_kw, self._kw.get(f"p:{h}", set()), self._df, self._ndocs, self._common)
            if score < min_cue:
                continue
            r = cue.retrievability(cue=score, **cue.features(p, now, inner=inner))
            if r >= (need_inner if inner else need) and (best is None or r > best["r"]):
                best = {"hash": h, "r": round(r, 3), "cue": score, "terms": terms[:3], "inner": inner}
        return best

    def cue_note(self, hit: dict, now: float) -> tuple[str, str]:
        h = hit["hash"]
        p, d = self._state["paras"][h], self._docs[h]
        text = fade.shown(p)[0] or d["content"]
        if text.startswith(fade.INNER_PREFIX):
            text = "（那时你心里想的）" + text[len(fade.INNER_PREFIX):]
        else:
            text = cue.fragment(text, hit["terms"])
        feel = f"（剩下的感觉：{p['feel']}）" if p.get("fade") and p.get("feel") and p["feel"] not in text else ""
        return cue.NOTE.format(terms="」「".join(hit["terms"]), term0=hit["terms"][0], text=text, feel=feel,
                               when=cue.when_words((now - d["created"]) / 86400)), text

    async def cue_recall(self, event: Turn, req: Request):
        if not self._cfg("enable", True) or not self._cfg("cue.enable", True):
            return
        text = event.get_message_str() if hasattr(event, "get_message_str") else event.message_str
        chat, now = self._chat(event), time.time()
        if not text or now - float(self._state["cue_chat"].get(chat, 0)) < float(self._cfg("cue.chat_cooldown_minutes", 30)) * 60:
            return
        offered = event.get_extra("memory_weight_offered", []) or []
        hit = self.find_cue(chat[1:], text, now, {o["id"][2:] for o in offered if o["id"].startswith("p:")})
        if not hit:
            return
        note, shown_text = self.cue_note(hit, now)
        req.system_prompt = (req.system_prompt or "") + "\n\n" + note
        event.set_extra("memory_weight_offered", offered + [{"id": f"p:{hit['hash']}", "text": shown_text}])
        self._state["cue_last"][hit["hash"]] = now
        self._state["cue_chat"][chat] = now
        self.log.info(f"memory_weight: 触景生情（{'、'.join(hit['terms'])}，线索{hit['cue']}，可检索性{hit['r']}）→ {shown_text[:50]}")
        await self._recall_moves_heart(hit, shown_text, event, now)

    async def _recall_moves_heart(self, hit: dict, shown_text: str, event: Turn, now: float) -> None:
        """想起旧事牵动心情（11-18 照 HCEM）：把那段记忆当时的感受和强度交给 kaju_heart 轻轻推一下心情。
        最多等 3 秒（心情那边正忙就算了），出任何错都只是这次不牵动。"""
        if not self._cfg("cue.moves_heart", True):
            return
        p = self._state["paras"].get(hit["hash"]) or {}
        h = parts.find("feel_recall")
        if h is None:
            return
        try:
            await asyncio.wait_for(h.feel_recall(
                p.get("feel0") or p.get("feel") or "", float(p.get("e", 0) or 0),
                cause=shown_text.replace("（那时你心里想的）", "")[:24], who=str(event.get_sender_id() or ""),
                umo=getattr(event, "unified_msg_origin", "") or "", fade_level=int(p.get("fade", 0) or 0), now=now), 3)
        except Exception as e:  # noqa: BLE001
            self.log.info(f"memory_weight: 想起旧事没牵动心情 {type(e).__name__}: {e}")

    async def after_reply(self, event: Turn, resp: Answer):
        if not self._cfg("enable", True):
            return
        reply = MEME_TAG.sub("", getattr(resp, "completion_text", "") or "").strip()
        if not reply or "[SKIP]" in reply.upper():
            return
        credited = self.credit_usage(event, reply)
        if credited:
            asyncio.create_task(self._reinforce_memorix(credited))
        self.credit_shelf(event, reply)
        self._maybe_shelve(event, reply)

    # ------------------------------------------------------------ 4. 珍藏的文件
    def _owners(self) -> set[str]:
        """兄长大人本人：身份表（kaju_core.people）；没登记时问称呼簿。"""
        if people.owner():
            return {people.owner()}
        book = self.body.find("address_of")
        if book is not None and getattr(book, "owner", ""):
            return {str(book.owner).strip()}
        return {DEFAULT_OWNER}

    def _seal_table(self) -> dict:
        t = self._cfg("shelf.seal_days", {}) or {}
        return {g: float(t.get(f"g{g}", shelf.DEFAULT_SEAL_DAYS[g])) for g in (1, 2, 3)}

    def _who(self, qq: str, name: str = "") -> str:
        return self.labels().get(qq) or name or "对方"

    def shelf_for(self, event: Turn, now: float | None = None, faded: bool = False) -> list[dict]:
        """这次说话的人分享过、在这里能想起来的文件（默认去掉已经淡忘的），按分量、新旧排。"""
        now = now or time.time()
        sid, chat = str(event.get_sender_id() or ""), self._chat(event)
        table, floor = self._seal_table(), float(self._cfg("shelf.forget_below", 0.2))
        items = [it for it in self._state["shelf"] if shelf.visible(it, sid, chat)
                 and (faded or shelf.retention(it, now, table) >= floor)]
        items.sort(key=lambda it: (-it["g"], -float(it["created"])))
        return items

    async def inject_shelf(self, event: Turn, req: Request):
        if not self._cfg("enable", True) or not self._cfg("shelf.enable", True):
            return
        items = self.shelf_for(event)[: int(self._cfg("shelf.max_index", 5))]
        if not items:
            return
        who = self._who(str(event.get_sender_id() or ""), event.get_sender_name() or "")
        lines = [shelf.index_line(it, self._tz, who) for it in items]
        req.system_prompt = (req.system_prompt or "") + SHELF_NOTE.format(who=who, items="\n".join(lines))

    async def shelf_detail(self, event: Turn, req: Request):
        """对方提到了某份珍藏的文件（文件名、关键词、"上次那篇"），把当时读到的内容翻出来给她看。"""
        if not self._cfg("enable", True) or not self._cfg("shelf.enable", True):
            return
        text = event.get_message_str() if hasattr(event, "get_message_str") else event.message_str
        if not text or event.get_extra("kaju_docs_read"):
            return
        now = time.time()
        umo = event.unified_msg_origin
        items = self.shelf_for(event)
        scored = sorted(((shelf.relevance(it, text), it) for it in items), key=lambda x: (-x[0], -x[1]["g"]))
        picked = [it for s, it in scored if s >= 2][:2]
        carried = False
        if picked:
            self._shelf_last[umo] = {"ids": [it["id"] for it in picked], "t": now}
        else:
            picked, carried = self._carried_shelf(umo, items, text, now), True
        if not picked:
            return
        who = self._who(str(event.get_sender_id() or ""), event.get_sender_name() or "")
        budget = int(self._cfg("shelf.content_chars", 4000))
        tpl = SHELF_CARRY if carried else SHELF_DETAIL
        for it in picked:
            d = dt.datetime.fromtimestamp(float(it["created"]), self._tz)
            req.system_prompt = (req.system_prompt or "") + "\n\n" + tpl.format(
                who=who, file=it["file"], date=f"{d.month}月{d.day}日", feeling=it.get("feeling") or "后的感受没记下",
                content=shelf.clip(it.get("content", ""), budget // len(picked)))
        event.set_extra("memory_weight_shelf_offered", [it["id"] for it in picked])
        event.set_extra("memory_weight_shelf_carried", carried)
        self.log.info(f"memory_weight: {'接着给' if carried else '翻出'}珍藏 {[it['file'] for it in picked]}")

    def _carried_shelf(self, umo: str, items: list[dict], text: str, now: float) -> list[dict]:
        """刚翻出来过、话题还没走远：接着给。期间又碰到文件里的词就重新计时。"""
        last = self._shelf_last.get(umo)
        window = float(self._cfg("shelf.carry_minutes", 20)) * 60
        if not last or window <= 0 or now - float(last["t"]) > window:
            self._shelf_last.pop(umo, None)
            return []
        picked = [it for it in items if it["id"] in last["ids"]][:2]
        if picked and any(shelf.relevance(it, text) >= 1 for it in picked):
            last["t"] = now
        return picked

    async def recall_shared_file(self, event: Turn, keyword: str):
        """翻出对方以前分享给你、你收着的文件或B站视频，重读一遍当时读到/看到的内容。对方问起以前发给你的文件、故事、文章、视频，你想不起细节时用。

        Args:
            keyword(string): 文件名、书名或者里面的人物、关键事物，比如"邮差"、"那封信"
        """
        if not self._cfg("enable", True) or not self._cfg("shelf.enable", True):
            return "这个功能关掉了。"
        now = time.time()
        q = str(keyword or "").strip()
        items = self.shelf_for(event, now, faded=True)
        if not items:
            return "对方还没有分享过你收着的文件。老实说没印象，问问是哪一份。"
        scored = sorted(((shelf.relevance(it, q) + (3 if q and q in it["file"] else 0)
                          + weigh.overlap(it.get("memory", ""), q) * 2, it) for it in items), key=lambda x: -x[0])
        best_score, it = scored[0]
        if q and best_score <= 0:
            names = "、".join(f"《{x['file']}》" for x in items[:6])
            return f"没找到和\"{q}\"有关的。对方分享过的有：{names}。可以问问是哪一份。"
        d = dt.datetime.fromtimestamp(float(it["created"]), self._tz)
        head = f"《{it['file']}》（{d.month}月{d.day}日，{self._who(it['qq'], it.get('name', ''))}分享的）"
        if shelf.retention(it, now, self._seal_table()) < float(self._cfg("shelf.forget_below", 0.2)):
            # 已经淡忘：只翻得出个大概，不算"想起"（不然细节又变清楚了）；他再分享一次才会重新记牢
            return f"{head}——这是很久以前看的了，只记得：{it.get('memory', '')}（读完{it.get('feeling', '')}）。细节记不清了，就老实这么说。"
        self._use_shelf(it, now)
        return (f"{head}\n当时读完的感受：{it.get('feeling') or '没记下'}"
                + (f"；分享时说：「{it['said']}」" if it.get("said") else "")
                + f"\n当时读到的内容：\n{it.get('content', '')}\n\n用你的话回答对方，别整段复述。")

    def _use_shelf(self, it: dict, now: float) -> None:
        it["uses"] = int(it.get("uses", 0)) + 1
        it["last_used"] = now
        try:
            self._save()
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"memory_weight: 保存失败: {exc}")

    def credit_shelf(self, event: Turn, reply: str, now: float | None = None) -> list[str]:
        """她回复里用上了某份珍藏（说出了它的关键词、对方这句没说过的）→ 算想起一次。"""
        if not self._cfg("shelf.enable", True):
            return []
        now = now or time.time()
        said = event.get_message_str() if hasattr(event, "get_message_str") else event.message_str
        cooldown = float(self._cfg("usage.cooldown_minutes", 30)) * 60
        offered = set(event.get_extra("memory_weight_shelf_offered", []) or [])
        out = []
        for it in self.shelf_for(event, now, faded=True):
            new_hits = [k for k in shelf.item_keywords(it) if k in reply and k not in (said or "")]
            if not new_hits and not (it["id"] in offered and shelf.relevance(it, reply) >= 1):
                continue
            if now - self._last_credit.get(f"s:{it['id']}", 0) < cooldown:
                continue
            self._last_credit[f"s:{it['id']}"] = now
            self._use_shelf(it, now)
            out.append(it["id"])
            self.log.info(f"memory_weight: 想起了珍藏《{it['file']}》（{'、'.join(new_hits[:3])}）")
        return out

    def _maybe_shelve(self, event: Turn, reply: str) -> None:
        """这一轮她读了兄长大人分享的文件：等一会儿（他可能接着说几句、心情插件也要判断完）再评分量收好。"""
        docs = event.get_extra("kaju_docs_read") or []
        if not docs or event.get_extra("_mw_shelved") or not self._cfg("shelf.enable", True):
            return
        sender = str(event.get_sender_id() or "")
        if str(self._cfg("shelf.keep_from", "owner")) != "all" and sender not in self._owners():
            return
        event.set_extra("_mw_shelved", True)
        job = {"qq": sender, "name": event.get_sender_name() or "", "chat": self._chat(event),
               "said": (event.get_message_str() if hasattr(event, "get_message_str") else event.message_str) or "",
               "reply": reply[:600], "t": time.time(), "docs": [d for d in docs if isinstance(d, dict)]}
        asyncio.create_task(self._shelve(job))

    def update_shelf(self, title: str, chat: str, content: str) -> int:
        """kaju_learn 一段段读完一本长书：珍藏里当时只读了开头的那份，换成她读完的样子。返回改了几份。"""
        title = (title or "").strip()
        if not title or not content:
            return 0
        n = 0
        for it in self._state["shelf"]:
            if it.get("removed") or (chat and it.get("chat") != chat):
                continue
            if title in str(it.get("file", "")):
                it["content"] = content[:6000]
                it["read_through"] = time.time()
                n += 1
        if n:
            self._save()
            self.log.info(f"memory_weight: 珍藏《{title}》换成读完的样子（{n} 份）")
        return n

    def _heart_feeling(self, qq: str, since: float) -> dict | None:
        fn = getattr(self.body.find("latest_feeling"), "latest_feeling", None)
        if callable(fn):
            try:
                return fn(qq, since)
            except Exception:  # noqa: BLE001
                return None
        return None

    async def _shelve(self, job: dict, wait: float | None = None) -> list[dict]:
        wait = float(self._cfg("shelf.settle_seconds", 90)) if wait is None else wait
        await asyncio.sleep(wait)  # 他可能紧接着说"这个你好好看看"；心情插件的判断也在这期间出来
        feeling = self._heart_feeling(job["qq"], job["t"] - 5)
        feel_text = f"{feeling['emo']}（{['没什么感觉', '有一点', '明显', '很强烈'][min(3, int(feeling['i']))]}）" if feeling else ""
        chat_id = job["chat"][1:]
        ctx = [r for r in self._context_lines(chat_id, job["t"] - 300, job["t"] + wait, limit=12)]
        context = "\n".join(f"{'佳树' if r.get('u') == 'self' else self._who(str(r.get('u')), r.get('n', ''))}："
                            f"{str(r.get('x', ''))[:120]}" for r in ctx)
        who = self._who(job["qq"], job["name"])
        place = "私聊" if job["chat"].startswith("p") else "群聊"
        out = []
        for doc in job["docs"]:
            content = str(doc.get("content") or "")
            if not content or content.startswith("没读成"):
                continue
            try:
                verdict = shelf.parse_rate(await self._ask(shelf.rate_system(who), shelf.rate_prompt(
                    who=who, place=place, said=job["said"], context=context, file=doc.get("name", "文件"),
                    content=content, reply=job["reply"], feeling=feel_text, kind=doc.get("kind") or "文件")))
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"memory_weight: 珍藏评分量失败 {exc}")
                verdict = None
            verdict = verdict or {"g": 1, "earnest": False, "memory": f"{who}分享的《{doc.get('name', '文件')}》",
                                  "feeling": "", "keywords": [], "why": "没评上分量，先按普通收着"}
            # 兜底：心情插件判断"很强烈"、或者语重心长的，至少是"要紧"
            if (feeling and int(feeling.get("i", 0)) >= 3) or verdict["earnest"]:
                verdict["g"] = max(verdict["g"], 2)
            async with self._lock:
                out.append(self._add_shelf(job, doc, verdict, feeling))
                self._save()
        return out

    def _add_shelf(self, job: dict, doc: dict, v: dict, feeling: dict | None) -> dict:
        content = shelf.clip(str(doc.get("content") or ""), int(self._cfg("shelf.content_chars", 4000)))
        digest = hashlib.sha1(content[:2000].encode("utf-8")).hexdigest()[:10]
        name = str(doc.get("name") or "文件")
        url = str(doc.get("url") or "")
        for it in self._state["shelf"]:  # 同一份文件（同一个视频）又分享了一次：更牢
            if it["qq"] == job["qq"] and not it.get("removed") and (
                    it.get("digest") == digest or it["file"] == name or (url and it.get("url") == url)):
                it["g"] = max(it["g"], v["g"])
                it["earnest"] = it.get("earnest") or v["earnest"]
                self._use_shelf(it, job["t"])
                self.log.info(f"memory_weight: 珍藏《{name}》又分享了一次，记得更牢")
                return it
        sid = hashlib.sha1(f"{job['qq']}|{name}|{job['t']}".encode()).hexdigest()[:8]
        it = {"id": sid, "qq": job["qq"], "name": job["name"], "chat": job["chat"], "file": name,
              "memory": v["memory"], "feeling": v["feeling"] or (feeling or {}).get("emo", ""), "earnest": v["earnest"],
              "g": v["g"], "why": v["why"], "keywords": v["keywords"], "said": job["said"][:150],
              "reply": job["reply"][:300], "content": content, "digest": digest,
              "heart": feeling, "created": job["t"], "uses": 0, "last_used": None, "removed": False,
              "kind": str(doc.get("kind") or "文件"), "url": url}
        src = doc.get("path") or ""
        if src and os.path.isfile(src) and os.path.getsize(src) <= 20 * 1024 * 1024:
            try:
                folder = os.path.join(self._dir, "shelf")
                os.makedirs(folder, exist_ok=True)
                it["copy"] = os.path.join(folder, sid + os.path.splitext(name)[1].lower())
                shutil.copyfile(src, it["copy"])
            except OSError as exc:
                self.log.info(f"memory_weight: 原文件没复制成 {exc}")
        self._state["shelf"].append(it)
        self.log.info(f"memory_weight: 珍藏《{name}》（{shelf.GRAVITY[v['g']]}，封存 {shelf.seal_days(v['g'], self._seal_table()):.0f} 天）"
                    f"{v['memory']}｜{v['why']}")
        return it

    def credit_usage(self, event: Turn, reply: str, now: float | None = None) -> list[str]:
        """她这次回复用上了哪些记忆：记一次"用过"，返回记忆 id。"""
        now = now or time.time()
        reply_kw = weigh.keywords(reply)
        echo_kw = weigh.keywords(event.get_message_str() if hasattr(event, "get_message_str") else event.message_str)
        cands: dict[str, str] = {}
        ks_by_id = {k["id"]: k for k in self._state["keepsakes"]}
        for kid in event.get_extra("memory_weight_keepsakes", []) or []:
            if kid in ks_by_id:
                cands[f"k:{kid}"] = ks_by_id[kid]["memory"] + " " + ks_by_id[kid]["quote"]
        for o in event.get_extra("memory_weight_offered", []) or []:
            cands.setdefault(o["id"], o["text"])
        # 没被检索出来、但她自己说出了只有这几条记忆才有的词（比如"女王大人"）
        visible = {f"k:{k['id']}" for k in self.keepsakes_for(event, now)}
        for t in reply_kw - echo_kw:
            for i in self._rare.get(t, []):
                if i.startswith("p:") or i in visible:
                    cands.setdefault(i, "")
        cooldown = float(self._cfg("usage.cooldown_minutes", 30)) * 60
        credited = []
        for i, text in cands.items():
            kw = self._kw.get(i) or weigh.keywords(text)
            hits = weigh.used_terms(kw, reply_kw, echo_kw, self._common)
            if not hits or now - self._last_credit.get(i, 0) < cooldown:
                continue
            self._last_credit[i] = now
            item = None
            if i.startswith("k:"):
                item = ks_by_id.get(i[2:])
            elif i.startswith("p:"):
                h = i[2:]
                item = self._state["paras"].setdefault(h, {"g": None, "src": self._docs.get(h, {}).get("source", ""),
                                                           "created": self._docs.get(h, {}).get("created", now),
                                                           "uses": 0, "last_used": None, "prot": 0})
            if item is not None:
                item["uses"] = int(item.get("uses", 0)) + 1
                item["last_used"] = now
                if i.startswith("k:"):
                    item["retired"] = False
            credited.append(i)
            self.log.info(f"memory_weight: 用上了 {i[:14]}（{'、'.join(hits[:3])}）")
        if credited:
            try:
                self._save()
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"memory_weight: 保存失败: {exc}")
        return credited

    async def _reinforce_memorix(self, ids: list[str]) -> None:
        mx = self._memorix()
        if mx is None:
            return
        rels: list[str] = []
        for i in ids:
            if i.startswith("p:"):
                rels += self._para_rels.get(i[2:], [])[:5]
            elif i.startswith("r:"):
                rels.append(i[2:])
        for rel in list(dict.fromkeys(rels))[:10]:
            try:
                await mx.memory_service.reinforce(scope_key=self._scope(), query_or_hash=rel)
            except Exception as exc:  # noqa: BLE001
                self.log.debug(f"memory_weight: 加强关系失败 {rel[:8]}: {exc}")

    # ------------------------------------------------------------ 5. 工作记忆（working.py）
    async def inject_memo(self, event: Turn, req: Request):
        note = await self.memo.note_for(event.unified_msg_origin)
        if note:
            req.system_prompt = (req.system_prompt or "") + note

    async def update_memo(self, event: Turn, run_context, response: Answer):
        self.memo.on_done(event.unified_msg_origin, run_context)

    async def show_memo(self, event: Turn):
        """查看这个会话当前的工作记忆备忘"""
        yield event.plain_result(await self.memo.describe(event.unified_msg_origin))

    # ------------------------------------------------------------ admin
    def report(self, what: str = "", now: float | None = None) -> str:
        now = now or time.time()
        table = self._half_life()
        fmt = lambda ts: dt.datetime.fromtimestamp(ts, self._tz).strftime("%m-%d")  # noqa: E731
        ks = self._state["keepsakes"]
        if what == "铭记":
            rows = sorted((k for k in ks if not k.get("removed")),
                          key=lambda k: (k.get("retired", False), -k["g"], -weigh.retention(k, now, table)))
            rows = sorted(rows, key=lambda k: bool(k.get("superseded")))
            lines = [f"{k['id'][:6]} {'（不再成立：' + k.get('superseded_why', '') + '）' if k.get('superseded') else ''}"
                     f"{'（淡了）' if k.get('retired') else ''}[{weigh.GRAVITY_NAMES[k['g']]} "
                     f"强度{weigh.retention(k, now, table):.2f} 用过{k.get('uses', 0)}次] {fmt(k['created'])} "
                     f"{k['memory']}「{k['quote']}」" for k in rows[:20]]
            return "铭记在心（不对的可以 /记忆轻重 删 编号）\n" + ("\n".join(lines) or "还没有。")
        if what == "珍藏":
            seal = self._seal_table()
            rows = sorted((it for it in self._state["shelf"] if not it.get("removed")),
                          key=lambda it: (-it["g"], -float(it["created"])))
            lines = []
            for it in rows[:20]:
                end = float(it["created"]) + shelf.seal_days(it["g"], seal) * 86400
                state = f"封存到 {fmt(end)}" if now < end else f"强度{shelf.retention(it, now, seal):.2f}"
                lines.append(f"{it['id'][:6]} [{shelf.GRAVITY[it['g']]} {state} 想起{it.get('uses', 0)}次"
                             f"{' 语重心长' if it.get('earnest') else ''}] {fmt(it['created'])}《{it['file']}》"
                             f"{it['memory']}（读完{it.get('feeling', '')}）")
            return "珍藏的文件（不对的可以 /记忆轻重 删 编号）\n" + ("\n".join(lines) or "还没有。")
        if what == "未了":
            today = self._today(now)
            names = {"open": "", "done": "有结果了", "drop": "取消了", "stale": "过去了"}
            rows = sorted((lp for lp in self._state["loops"] if not lp.get("removed")),
                          key=lambda lp: (lp.get("status", "open") != "open", -loops.priority(lp, now, today)))
            lines = []
            for lp in rows[:20]:
                st = lp.get("status", "open")
                w = loops.when_text(lp, today)
                tag = f"分{loops.priority(lp, now, today):.1f}" if st == "open" else names.get(st, st)
                lines.append(f"{lp['id'][:6]} [{tag} 要紧{lp.get('imp')} 给她看过{lp.get('shown', 0)}次] {fmt(lp['created'])} "
                             f"{self._who(lp['qq'], lp.get('name', ''))}：{lp['what']}" + (f"（{w}）" if w else "")
                             + (f" → {lp['result']}" if lp.get("result") else ""))
            seeding = len(self._state.get("loops_seed_queue") or [])
            head = "还没结果的事（不对的可以 /记忆轻重 删 编号）" + (f"\n（最近几天的记录还有 {seeding} 段没补看完）" if seeding else "")
            return head + "\n" + ("\n".join(lines) or "还没有。")
        if what == "褪色":
            rows = sorted(((h, p) for h, p in self._state["paras"].items() if int(p.get("fade", 0) or 0) >= 1),
                          key=lambda x: -max((x[1].get("fade_at") or {"0": 0}).values()))
            lines = []
            for h, p in rows[:12]:
                text, _ = fade.shown(p)
                lines.append(f"{fmt(p['created'])} [{fade.LEVEL_NAMES[p['fade']]}] {text}\n"
                             f"  原来：{self._docs.get(h, {}).get('content', '')[:60]}")
            soon = sorted(((fade.clarity(p, now, **self._fade_kw()), h) for h, p in self._state["paras"].items()
                           if p.get("g") is not None and not p.get("fade") and h in self._docs
                           and fade.can_fade(p.get("src", ""), self._docs[h]["content"])))[:3]
            tail = "\n".join(f"  清晰度 {c:.2f}：{self._docs[h]['content'][:40]}" for c, h in soon)
            return ("褪了色的记忆（原文还在 memorix 里，她只想得起褪色后的样子）\n" + ("\n".join(lines) or "还没有。")
                    + ("\n最先会褪色的：\n" + tail if tail else ""))
        if what == "遗忘":
            rows = self._state["forgotten"][-15:]
            lines = [f"{fmt(f['at'])} 忘了（{weigh.GRAVITY_NAMES.get(f['g'], '?')}，用过{f['uses']}次）{f['content'][:50]}"
                     f"\n  恢复：/记忆轻重 恢复 {f['op']}" for f in reversed(rows)]
            return "最近忘掉的\n" + ("\n".join(lines) or "还没忘过什么。")
        threshold = float(self._cfg("forget.threshold", 0.1))
        min_age = float(self._cfg("forget.min_age_days", 7)) * 86400
        rated = {h: p for h, p in self._state["paras"].items() if p.get("g") is not None}
        paras = list(rated.values())
        by_g = {g: sum(1 for p in paras if p["g"] == g) for g in range(4)}

        def left(p):  # 还有几天会忘（至少要记满 min_age）
            return max(weigh.days_until(p, now, threshold, table), (p["created"] + min_age - now) / 86400)

        fading = sorted((h for h, p in rated.items() if p["g"] <= 1 and p["src"].startswith(FORGETTABLE)),
                        key=lambda h: left(rated[h]))
        soon = [f"  约 {left(rated[h]):.0f} 天后：{self._docs.get(h, {}).get('content', '')[:40]}" for h in fading[:3]]
        ks = [k for k in ks if not k.get("removed")]
        active = [k for k in ks if not k.get("retired")]
        return (f"记忆轻重\n铭记 {len(active)} 条（淡了的 {len(ks) - len(active)} 条）\n"
                f"长期记忆打过分量的 {len(paras)} 条：郑重 {by_g[3]} / 要紧 {by_g[2]} / 一般 {by_g[1]} / 琐碎 {by_g[0]}，"
                f"用上过的 {sum(1 for p in paras if p.get('uses'))} 条\n"
                f"褪成片段 {sum(1 for p in paras if int(p.get('fade', 0) or 0) == 1)} 条 / "
                f"只剩印象 {sum(1 for p in paras if int(p.get('fade', 0) or 0) >= 2)} 条\n"
                f"已经忘掉 {len(self._state['forgotten'])} 条\n"
                + ("最先会忘的：\n" + "\n".join(soon) + "\n" if soon else "")
                + f"珍藏的文件 {sum(1 for it in self._state['shelf'] if not it.get('removed'))} 份\n"
                + "\n/记忆轻重 铭记｜珍藏｜褪色｜遗忘｜删 编号｜恢复 操作号｜整理")

    async def admin(self, event: Turn, action: str = "", arg: str = ""):
        if not event.is_admin():
            return
        action = action.strip()
        if action == "整理":
            stats = await self.tick()
            yield event.plain_result(f"整理完了：{stats}")
            return
        if action == "删":
            hit = [k for k in self._state["keepsakes"] + self._state["shelf"] + self._state["loops"]
                   if arg.strip() and k["id"].startswith(arg.strip()) and not k.get("removed")]
            if len(hit) != 1:
                yield event.plain_result("用法：/记忆轻重 删 编号（编号在 /记忆轻重 铭记、珍藏 或 未了 里，每条开头那 6 位）")
                return
            hit[0]["removed"] = True
            self._save()
            self.reindex()
            if "what" in hit[0]:
                yield event.plain_result(f"好，这件不再算还没结果的事了：{hit[0]['what']}")
                return
            what = f"珍藏的《{hit[0]['file']}》" if "file" in hit[0] else "铭记"
            yield event.plain_result(f"好，这条不再算{what}了：{hit[0]['memory']}")
            return
        if action == "恢复":
            mx = self._memorix()
            if mx is None or not arg:
                yield event.plain_result("用法：/记忆轻重 恢复 操作号（在 /记忆轻重 遗忘 里看）")
                return
            res = await mx.admin_service.delete_admin(scope_key=self._scope(), action="restore", operation_id=arg.strip())
            yield event.plain_result(f"恢复结果：{json.dumps(res, ensure_ascii=False)[:300]}")
            return
        yield event.plain_result(self.report(action))
