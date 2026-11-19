"""工作记忆：边聊边记一份"刚才聊天的备忘"，下一轮回复前放在她眼前（原 working_memory 插件，2026-11-03 并进记忆轻重）。

问题：刚聊过、刚推断过的事她转头就忘。比如她自己猜出"鬼鱼 = 图里水+幽灵那只"，
两分钟后被问"对面六只都叫什么"，又说"剩下两只对不上号"。原因：
- 这些东西虽然在聊天记录里，但埋在几轮之前，模型回答时主要盯着最新一条消息；
- 她在思考里推出来的东西不会带到下一轮；
- 图片只在发图那一轮有描述，之后不会再提醒。

做法：
- 每次她回复完（on_agent_done），后台用聊天模型把【旧备忘】+【最近几轮对话】整理成一份新备忘：
  在聊什么、已经弄清的事（外号/缩写指什么、图里按位置都有什么、谁纠正过什么）、她自己的推断
  （标"佳树猜的"）、还没弄清的问题。
- 下一轮请求时把备忘追加到系统提示末尾（stable_prefix 会把它挪到本轮消息末尾，不进历史、不破坏缓存）。
  后台整理还没完成时最多等 max_wait 秒。
- 备忘超过 ttl_minutes 没更新就作废；换了对话（/reset）也作废。
- 备忘存在记忆轻重的数据目录 working_notes.json。
"""

import asyncio
import datetime as dt
import json
import os
import re
import time
import zoneinfo


DATETIME_REMINDER = re.compile(r"<system_reminder>\s*Current datetime:[^<]*</system_reminder>", re.S)
DATETIME_HHMM = re.compile(r"Current datetime:\s*\d{4}-\d{2}-\d{2}\s+(\d{1,2}:\d{2})")
MEME_TAG = re.compile(r"&&[^&\s]+&&")

NOTE_SYSTEM = """你是 QQ 聊天角色"佳树"的速记员。根据【旧备忘】和【最近对话】写一份新的备忘，给佳树下一次回复前快速回顾，免得她忘了刚聊过、刚弄清楚的事。

要记的（只记跟最近正在聊的话题有关、对接下来聊天有用的具体信息）：
- 现在在聊什么、在跟谁聊（用对话里的昵称）。
- 已经弄清的事实和对应关系：外号/缩写/谐音指的是什么，"最上面那只""第二张图""他说的那个"指的是什么。
- 图片内容：按位置/顺序记，带上看得到的图标、属性、文字、数字。图片的自动描述经常认错名字（尤其是角色、宝可梦），但图标颜色、位置一般是对的；和群友说的对不上时以群友为准。
- 有清单类的东西（队伍、名单、选项、几张图……）时，合成一张逐项对照表：每一项写"目前最可能是什么 + 依据"（图第几个、什么图标/属性、谁说的、佳树猜的），把图片、群友的话、佳树的推断对到一起。比如群友说的外号对得上某一项的属性，就写进那一项。
- 佳树自己说过的推断和猜测，标"（佳树猜的）"；被谁确认或纠正过就改成确认后的说法。可靠程度：群友明确说的 > 佳树猜的 > 图片自动描述的名字。
- 对方纠正过佳树的理解或看法（不只是事实，也包括"他觉得是怎么回事、他不同意佳树哪种说法"）：写成"他的意思：……（佳树之前以为……，不对）"。他为同一点纠正了好几次，就写明"他已经纠正了 N 次"。
- 还没弄清的问题、佳树明确答应了要做还没做的事。

规则：
- 旧备忘里还有用的保留；前后矛盾以新的、更可靠的为准。
- 对话前面的 [时:分] 是时间，【现在】是现在的时间。早就聊完、和现在的话题无关的旧事（比如半小时前别的话题）直接删掉，不要记；超过一小时、之后再没人提起的事（包括"没弄清"里的）也删掉。
- 佳树说自己能不能做某件事（能不能看到群、能不能在群里发消息、能不能存图……）不要记成事实：她有哪些功能以系统给她的功能清单为准，她嘴上说的常常不对。
- 佳树自己讲的她今天的生活小事（做了什么、买了什么、学校里的事）不用记，除非对方接着在跟她聊这件事。
- "没弄清"里只放对方在等答案的问题、佳树明确答应了还没做的事；对方没要求、佳树也没答应的事不算待办。
- 不编造对话里没有的内容；不写佳树的性格设定，不写聊天建议。
- 用简短的中文条目，总共不超过 {max_chars} 字，格式：
话题：……
已知：
- ……
没弄清：
- ……（没有就省略这一节）
- 如果最近对话只是寒暄闲聊、没有需要记的东西，就只输出：无"""

NOTE_FOR_REPLY = (
    "【刚才聊天的备忘】下面是你自己边聊边记的要点（最近对话里已经说过、推断过、确认过的事）。"
    "回答前先对照一下：被问到的事如果备忘里有答案或线索，就用上（猜的可以说\"佳树猜是……\"），"
    "别说\"对不上号\"\"没听过\"、也别重新问已经弄清楚的事；有人纠正过的以纠正为准，别再用被纠正掉的说法。"
    "备忘只是帮你回想，\"没弄清\"里的事对方这条没提就先放着，先好好回应对方这条消息。\n{note}"
)


def _parts_text(content) -> str:
    """Flatten a message content (str or list of parts / dicts) into plain text, skipping temp parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    out = []
    if isinstance(content, list):
        for p in content:
            get = p.get if isinstance(p, dict) else (lambda k, d=None, _p=p: getattr(_p, k, d))
            if get("_no_save", False):
                continue
            kind = get("type")
            if kind == "text":
                out.append(get("text", "") or "")
            elif kind == "image_url":
                out.append("[图片]")
    return "\n".join(t for t in out if t)


def build_transcript(messages, turns: int, per_msg: int = 1500) -> tuple[str, str]:
    """Turn the agent run's message list into a compact transcript of the last `turns` user turns.

    Args:
        messages: run_context.messages (Message objects or dicts).
        turns: How many user turns to keep.
        per_msg: Max characters kept per message.

    Returns:
        (transcript, last_reply): transcript text, and her final visible reply in this run.
    """
    rows: list[tuple[str, str]] = []
    for m in messages or []:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        if role not in ("user", "assistant", "tool"):
            continue
        raw = _parts_text(content)
        when = DATETIME_HHMM.search(raw)
        text = MEME_TAG.sub("", DATETIME_REMINDER.sub("", raw)).strip()
        if not text:
            continue
        if when:
            text = f"[{when.group(1)}] {text}"
        rows.append((role, text))
    last_reply = next((t for r, t in reversed(rows) if r == "assistant"), "")
    user_idx = [i for i, (r, _) in enumerate(rows) if r == "user"]
    if user_idx:
        rows = rows[user_idx[-turns] if len(user_idx) >= turns else user_idx[0]:]
    label = {"user": "对方", "assistant": "佳树", "tool": "工具结果"}
    lines = []
    for role, text in rows:
        cap = 400 if role == "tool" else per_msg
        if len(text) > cap:  # 保留开头和结尾（群聊记录最新的在最后）
            text = text[: cap // 3] + " …… " + text[-(cap - cap // 3):]
        lines.append(f"【{label[role]}】{text}")
    return "\n\n".join(lines), last_reply

class WorkingMemo:
    """Per-session notes: rewritten in the background after each reply, shown before the next one."""

    def __init__(self, body, cfg, folder: str):
        """
        Args:
            body: kaju_core.body.Body（模型、设置、对话 id、日志）。
            cfg: Callable returning the "working" config section.
            folder: Plugin data folder (working_notes.json lives here).
        """
        self.body = body
        self.log = body.log
        self.cfg = cfg
        self._dir = folder
        self._path = os.path.join(folder, "working_notes.json")
        self._notes: dict[str, dict] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        try:
            with open(self._path, encoding="utf-8") as f:
                self._notes = json.load(f)
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"memory_weight: 读工作记忆备忘失败 {e}")

    def _c(self, key: str, default):
        try:
            return type(default)((self.cfg() or {}).get(key, default))
        except (TypeError, ValueError):
            return default

    def _now_hhmm(self) -> str:
        """Current time in the bot's configured timezone (the same clock as the [时:分] in the chat)."""
        try:
            tz = zoneinfo.ZoneInfo(self.body.settings().get("timezone") or "Asia/Shanghai")
        except Exception:  # noqa: BLE001
            tz = dt.timezone(dt.timedelta(hours=8))
        return dt.datetime.now(tz).strftime("%H:%M")

    def _save(self):
        try:
            os.makedirs(self._dir, exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._notes, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._path)
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"memory_weight: 存工作记忆备忘失败 {e}")

    async def fresh_note(self, umo: str) -> str:
        """The current note for this session, or "" if stale / from another conversation."""
        rec = self._notes.get(umo)
        if not rec or time.time() - rec.get("updated", 0) > self._c("ttl_minutes", 90.0) * 60:
            return ""
        cid = await self.body.conversation_id(umo)
        if rec.get("cid") and cid and rec["cid"] != cid:
            return ""
        note = (rec.get("note") or "").strip()
        return "" if note in ("", "无") else note

    async def note_for(self, umo: str) -> str:
        """Text to append to the system prompt (waits briefly for an update still being written)."""
        if not self._c("enable", True):
            return ""
        task = self._tasks.get(umo)
        if task and not task.done():  # 上一轮的备忘还在整理，等一下
            t0 = time.time()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=self._c("max_wait", 12.0))
            except Exception:  # noqa: BLE001
                pass
            self.log.info(f"memory_weight: 等工作记忆备忘整理 {time.time() - t0:.1f}s")
        note = await self.fresh_note(umo)
        return "\n\n" + NOTE_FOR_REPLY.format(note=note) if note else ""

    def on_done(self, umo: str, run_context) -> None:
        """After a reply: rewrite this session's note in the background."""
        if not self._c("enable", True):
            return
        try:
            transcript, last_reply = build_transcript(run_context.messages, self._c("turns", 6))
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"memory_weight: 读本轮对话失败 {e}")
            return
        if not last_reply or "[SKIP]" in last_reply.upper():  # 插话时选择不说：这一轮不进历史，也不记
            return
        prev = self._tasks.get(umo)

        async def run():
            if prev and not prev.done():
                try:
                    await prev
                except Exception:  # noqa: BLE001
                    pass
            await self._update(umo, transcript)

        self._tasks[umo] = asyncio.create_task(run())

    async def _update(self, umo: str, transcript: str):
        pid = await self.body.model_id(who=umo)
        if not pid:
            return
        old = await self.fresh_note(umo) or "（无）"
        max_chars = self._c("max_chars", 400)
        prompt = (f"【现在】{self._now_hhmm()}\n\n【旧备忘】\n{old}\n\n"
                  f"【最近对话】（从旧到新，最后一条是佳树刚说的）\n{transcript}\n\n请输出新的备忘：")
        t0 = time.time()
        try:
            note = await self.body.generate(pid, prompt, NOTE_SYSTEM.format(max_chars=max_chars),
                                            timeout=self._c("timeout_seconds", 60.0))
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"memory_weight: 整理工作记忆备忘失败 {e}")
            return
        note = (note or "").strip()
        if not note:
            return
        if len(note) > max_chars * 2:
            note = note[: max_chars * 2]
        cid = await self.body.conversation_id(umo)
        self._notes[umo] = {"note": note, "updated": time.time(), "cid": cid}
        self._save()
        self.log.info(f"memory_weight: {umo} 工作记忆备忘已更新（{len(note)} 字，{time.time() - t0:.1f}s）: {note[:80]!r}")

    async def describe(self, umo: str) -> str:
        """Text for the /佳树备忘 admin command."""
        rec = self._notes.get(umo)
        if not rec:
            return "这个会话还没有备忘"
        age = (time.time() - rec.get("updated", 0)) / 60
        fresh = "（已过期，不会再提醒）" if not await self.fresh_note(umo) else ""
        return f"备忘（{age:.0f} 分钟前更新）{fresh}：\n{rec.get('note', '')}"
