"""让佳树在兄长（管理员）的要求下，把聊天里的图片存进自己的表情包。

流程（关键步骤由插件直接完成，不依赖模型愿不愿意调用工具）：
1. 兄长说“把这个存成表情包”之类的话 → 插件当场取图。
   - 话里已经说了分类 → 直接存好；
   - 没说分类 → 图片暂存 10 分钟，并告诉佳树“图已收下，问兄长放哪个分类”。
2. 有暂存图时，兄长回答分类（分类名、中文近义词、或“新建个 XX 分类”）→ 插件直接存好。
3. 插件认不出的说法，交给模型调用 save_meme 工具兜底。

图片来源（按优先级）：当前消息 → 引用的消息 → 暂存的图 → 本会话最近几分钟的图。
真正的写入、去重、刷新都交给 meme_manager 插件完成。
"""

import asyncio
import json
import re
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Reply
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register

# “存/加/收藏 …… 表情（包）”“表情包 …… 存/加/收”“这张 …… 存”
SAVE_INTENT = re.compile(
    r"(存|加|收|放|保存|收藏|添加|塞|记).{0,12}(表情|图库|图包)"
    r"|(表情|图库).{0,8}(存|加|收|保存|收藏|添加)"
    r"|(这张|那张|这个图|这图|刚才那).{0,6}(存|收藏)"
)
CANCEL_INTENT = re.compile(r"不存了|别存了|不用存|算了|取消")
NEW_CATEGORY = re.compile(
    r"新建(?:一个|个)?(?:分类|类别)?\s*[「“\"'《]?"
    r"([一-鿿A-Za-z0-9_-]{1,12}?)[」”\"'》]?\s*(?:的)?(?:分类|类别|类)?"
    r"(?:[，,。：:；;\s]|$)(.*)"
)

# 现有分类的中文说法（越靠前越优先，避免“吃惊”被当成“吃”）
CATEGORY_ALIASES = {
    "surprised": ["惊讶", "震惊", "吃惊", "被吓", "意外"],
    "cold-shoulder": ["嫌弃", "冷淡", "不想理", "冷漠", "无视"],
    "affection": ["喜欢", "亲昵", "摸头", "撒娇", "贴贴", "感谢", "安慰"],
    "angry": ["生气", "愤怒", "不满", "抗议", "发火"],
    "approval": ["同意", "认可", "赞同", "确认", "点赞", "可以的"],
    "confused": ["疑问", "疑惑", "困惑", "不懂", "迷惑", "问号"],
    "eating": ["吃饭", "零食", "美食", "干饭", "投喂"],
    "happy": ["开心", "高兴", "快乐", "庆祝", "兴奋", "大笑"],
    "sad": ["难过", "伤心", "委屈", "哭", "沮丧"],
    "shy": ["害羞", "脸红", "不好意思", "尴尬"],
    "teasing": ["调侃", "吐槽", "玩梗", "坏笑", "嘲讽", "得意"],
    "tired": ["疲惫", "困了", "犯困", "累", "无语", "摆烂"],
    "reply": ["普通回应", "日常回复", "普通回复", "回应"],
}

# 分类的中文叫法（回复兄长时用）
CATEGORY_LABELS = {
    "surprised": "惊讶", "cold-shoulder": "嫌弃", "affection": "亲昵", "angry": "生气",
    "approval": "认可", "confused": "疑惑", "eating": "吃东西", "happy": "开心",
    "sad": "难过", "shy": "害羞", "teasing": "调侃", "tired": "累了", "reply": "日常回应",
}
# 模型仍然嘴硬说“做不到”时，用插件准备好的回复替换
REFUSAL = re.compile(r"做不到|做不来|办不到|没法|没办法|不行|不能|没有.{0,6}本事|存不了|帮不了|无法")

RECENT_SECONDS = 5 * 60      # 最近图片缓存保留时间
PENDING_SECONDS = 10 * 60    # 等兄长确认分类时，图片暂存时间
RECENT_PER_SESSION = 6       # 每个会话最多记几条带图消息
MAX_IMAGES = 9               # 一次最多保存几张
HANDLED_KEY = "meme_saver_result"
FALLBACK_KEY = "meme_saver_fallback_reply"


def _label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def _dumps(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


@register(
    "astrbot_plugin_meme_saver",
    "dsh",
    "兄长一句话，佳树就把指定的图片/表情包收进自己的表情库；分类拿不准时会先问兄长",
    "1.2.0",
)
class MemeSaver(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # session_id -> [(时间, 发送者, [Image, ...]), ...]
        self._recent: dict[str, list[tuple[float, str, list]]] = {}
        # session_id_sender -> {"time": t, "images": [bytes, ...], "source": str}
        self._pending: dict[str, dict] = {}

    # ------------------------------------------------------------------ 缓存

    @filter.event_message_type(filter.EventMessageType.ALL, priority=10)
    async def remember_images(self, event: AstrMessageEvent):
        """记住会话里最近出现的图片，方便“把刚才那张存起来”。"""
        try:
            images = [c for c in event.get_messages() if isinstance(c, Image)]
            if not images:
                return
            now = time.time()
            bucket = self._recent.setdefault(event.session_id, [])
            bucket.append((now, str(event.get_sender_id()), images))
            bucket[:] = [b for b in bucket if now - b[0] < RECENT_SECONDS][-RECENT_PER_SESSION:]
        except Exception as exc:  # 缓存失败不能影响正常聊天
            logger.debug(f"meme_saver: 记录图片失败 {exc}")

    # ------------------------------------------------------- 请求前直接处理

    @filter.on_llm_request()
    async def handle_before_llm(self, event: AstrMessageEvent, req: ProviderRequest):
        try:
            await self._handle_before_llm(event, req)
        except Exception as exc:
            logger.warning(f"meme_saver: 预处理失败 {exc}", exc_info=True)

    async def _handle_before_llm(self, event: AstrMessageEvent, req: ProviderRequest):
        text = event.message_str or ""
        wants_save = bool(SAVE_INTENT.search(text))
        if not event.is_admin():
            if wants_save:
                logger.info(f"meme_saver: {event.get_sender_id()} 想存表情但不是管理员")
            return

        key = self._pending_key(event)
        pending = self._pending.get(key)
        has_pending = bool(pending and time.time() - pending["time"] < PENDING_SECONDS)
        if not has_pending:
            self._pending.pop(key, None)
        if not wants_save and not has_pending:
            return

        lines = ["", "【收藏表情包（本轮优先于其它说法）】"]

        if has_pending and not wants_save and CANCEL_INTENT.search(text):
            self._pending.pop(key, None)
            lines.append("- 兄长说这张图不存了，暂存的图已经丢掉。简单应一声就好。")
            self._inject(req, lines, "取消")
            return

        categories = await self._categories(event)
        category, new_desc = self._match_category(text, categories or {})

        if wants_save or category:
            result = await self._save(event, category, new_desc)
            event.set_extra(HANDLED_KEY, result)
            fact = self._describe(result, categories or {})
            lines.append(fact)
            event.set_extra(FALLBACK_KEY, self._fallback_reply(result, categories or {}))
            # 放进这条消息末尾：模型对最近的内容最敏感，比只写在系统提示里管用
            if req.prompt is not None:
                req.prompt = f"{req.prompt}\n\n（系统旁白，回复里不要复述：{fact.lstrip('- ')}）"
            self._inject(req, lines, f"直接处理 category={category or '-'} ok={result.get('ok')}")
            return

        # 有暂存图，但这句话认不出是在回答分类：交给模型判断
        lines.append(
            "- 你刚才问过兄长那张图放哪个分类，图还暂存着。如果兄长这句话是在回答分类，"
            "就带上对应的 category 调用 save_meme（可选分类："
            + "、".join(f"{k}（{v}）" for k, v in (categories or {}).items())
            + "）；兄长在说别的事就正常聊。"
        )
        self._inject(req, lines, "交给模型")

    @filter.on_llm_response()
    async def fix_refusal(self, event: AstrMessageEvent, resp: LLMResponse):
        """插件已经处理过收藏，但模型还说“做不到”时，换成准备好的回复。"""
        try:
            fallback = event.get_extra(FALLBACK_KEY)
            if not fallback or resp is None:
                return
            text = resp.completion_text or ""
            if text and not REFUSAL.search(text):
                return
            resp.completion_text = fallback
            logger.info(f"meme_saver: 模型回复与收藏结果矛盾，已替换。原回复：{text[:60]}")
        except Exception as exc:
            logger.warning(f"meme_saver: 替换回复失败 {exc}")

    @staticmethod
    def _fallback_reply(result: dict, categories: dict) -> str:
        if result.get("need_confirm"):
            options = [_label(c) for c in categories if c != "默认分类"][:5]
            return (
                "诶嘿嘿，这张佳树先收下啦！兄长大人想把它放进哪一类呢？"
                + (f"比如{'、'.join(options)}……" if options else "")
                + "也可以新建一个哦。"
            )
        label = _label(str(result.get("category") or ""))
        if result.get("saved"):
            head = f"佳树新建了「{label}」分类，" if result.get("created_new_category") else ""
            return f"{head}收好啦！已经放进「{label}」里了，佳树以后会用的哦～"
        if result.get("duplicate"):
            return f"诶？这张佳树早就收着啦，在「{label}」里哦。"
        return f"唔……这次没存上呢。{result.get('reason') or ''}"

    @staticmethod
    def _inject(req: ProviderRequest, lines: list[str], tag: str) -> None:
        lines.append(
            "- 你现在完全有能力收藏表情包，之前对话里说“做不到”的话已经过时，别再那样说。"
            "回复里不要提工具、插件、文件夹等后台细节，用佳树的语气简短说。"
        )
        req.system_prompt = (req.system_prompt or "") + "\n".join(lines)
        logger.info(f"meme_saver: 已注入收藏说明（{tag}）")

    @staticmethod
    def _describe(result: dict, categories: dict) -> str:
        if result.get("need_confirm"):
            return (
                f"- 兄长要收藏的图（{result.get('image_count')} 张，来自{result.get('image_source')}）"
                "佳树已经收下暂存了，但还没定放哪个分类。现在请问兄长放哪个分类，可以顺便给个建议，"
                "也可以问要不要新建分类。" + (f"（情况：{result.get('reason')}）" if result.get("reason") else "")
                + "可选分类：" + "、".join(f"{k}（{v}）" for k, v in categories.items())
            )
        if result.get("saved") or result.get("duplicate"):
            parts = []
            if result.get("created_new_category"):
                parts.append(f"新建了「{result['category']}」分类")
            if result.get("saved"):
                parts.append(f"已经把 {result['saved']} 张存进「{result['category']}」分类")
            if result.get("duplicate"):
                parts.append(f"{result['duplicate']} 张本来就在这个分类里了")
            return "- 收藏已经完成：" + "，".join(parts) + "。开心地告诉兄长，以后聊天就能用上了。"
        return f"- 这次没存成：{result.get('reason') or '未知原因'}。用佳树的语气告诉兄长，并说怎么做能存上。"

    # ------------------------------------------------------------- 工具函数

    def _meme_manager(self):
        meta = self.context.get_registered_star("meme_manager")
        if not meta or not meta.activated or meta.star_cls is None:
            return None
        return meta.star_cls

    def _pending_key(self, event: AstrMessageEvent) -> str:
        return f"{event.session_id}_{event.get_sender_id()}"

    @staticmethod
    def _match_category(text: str, categories: dict) -> tuple[str, str]:
        """从兄长的话里认出分类；认不出或有歧义就返回空。"""
        m = NEW_CATEGORY.search(text)
        if m:
            name = m.group(1).strip()
            desc = m.group(2).strip(" ，,。：:；;") if m.group(2) else ""
            if name in categories:
                return name, ""
            if name:
                return name, desc or f"用于和「{name}」有关的场景。"
        low = text.lower()
        # 直接写了分类名（英文代号或中文分类名），选最长的那个，避免 sad 撞到别的词
        direct = [c for c in categories if c and c.lower() in low]
        if direct:
            return max(direct, key=len), ""
        hits = []
        for cat, words in CATEGORY_ALIASES.items():
            if cat in categories and any(w in text for w in words):
                hits.append(cat)
        if len(hits) == 1:
            return hits[0], ""
        return "", ""

    def _find_image_components(self, event: AstrMessageEvent) -> tuple[list, str]:
        chain = event.get_messages()
        current = [c for c in chain if isinstance(c, Image)]
        if current:
            return current, "当前消息"
        for comp in chain:
            if isinstance(comp, Reply) and comp.chain:
                quoted = [c for c in comp.chain if isinstance(c, Image)]
                if quoted:
                    return quoted, "引用的消息"
        return [], ""

    def _recent_image_components(self, event: AstrMessageEvent) -> tuple[list, str]:
        now = time.time()
        bucket = [b for b in self._recent.get(event.session_id, []) if now - b[0] < RECENT_SECONDS]
        sender = str(event.get_sender_id())
        for _, who, imgs in reversed(bucket):
            if who == sender:
                return imgs, "兄长刚才发的图"
        if bucket:
            return bucket[-1][2], "群里刚才出现的图"
        return [], ""

    @staticmethod
    async def _read_bytes(images: list) -> tuple[list[bytes], int]:
        contents, failed = [], 0
        for img in images[:MAX_IMAGES]:
            try:
                path = Path(await asyncio.wait_for(img.convert_to_file_path(), timeout=30))
                contents.append(await asyncio.to_thread(path.read_bytes))
            except Exception as exc:
                failed += 1
                logger.warning(f"meme_saver: 读取图片失败 {exc}")
        return contents, failed

    async def _collect(self, event: AstrMessageEvent) -> tuple[list[bytes], str, int]:
        comps, source = self._find_image_components(event)
        if comps:
            contents, failed = await self._read_bytes(comps)
            return contents, source, failed

        pending = self._pending.get(self._pending_key(event))
        if pending and time.time() - pending["time"] < PENDING_SECONDS:
            return list(pending["images"]), pending.get("source") or "之前暂存的图", 0

        comps, source = self._recent_image_components(event)
        if comps:
            contents, failed = await self._read_bytes(comps)
            return contents, source, failed
        return [], "", 0

    async def _categories(self, event: AstrMessageEvent) -> dict | None:
        mm = self._meme_manager()
        if mm is None:
            return None
        from data.plugins.meme_manager.backend.packs.resolver import (
            get_pack_paths,
            load_pack_category_mapping,
        )

        pack_id = str(mm._resolve_runtime_pack_context(event=event).get("pack_id") or "").strip()
        if not pack_id:
            return None
        memes_dir = Path(get_pack_paths(pack_id)["memes_dir"]).resolve()
        mapping = await asyncio.to_thread(load_pack_category_mapping, pack_id)
        names = set(mapping)
        if memes_dir.is_dir():
            names |= {p.name for p in memes_dir.iterdir() if p.is_dir()}
        return {k: mapping.get(k, "") for k in sorted(names)}

    # ------------------------------------------------------------- 保存核心

    async def _save(self, event: AstrMessageEvent, category: str, new_desc: str) -> dict:
        mm = self._meme_manager()
        if mm is None:
            return {"ok": False, "reason": "表情包管理插件没有加载，暂时存不了。"}

        try:
            from data.plugins.meme_manager.backend.packs.images import (
                DuplicateEmojiError,
                save_chat_upload_image,
            )
            from data.plugins.meme_manager.backend.packs.resolver import get_pack_paths
            from data.plugins.meme_manager.backend.semantic.storage import (
                invalidate_semantic_metadata,
            )
        except Exception as exc:
            logger.error(f"meme_saver: 无法导入 meme_manager 模块 {exc}")
            return {"ok": False, "reason": "表情包插件版本不兼容，请兄长检查。"}

        contents, source, read_failed = await self._collect(event)
        if not contents:
            return {
                "ok": False,
                "reason": "没找到要存的图片。把图片和这句话一起发，或者引用（回复）那张图再说一次就行。",
            }

        ctx = mm._resolve_runtime_pack_context(event=event)
        pack_id = str(ctx.get("pack_id") or "").strip()
        if not pack_id:
            return {"ok": False, "reason": "当前没有可写入的表情包。"}
        paths = get_pack_paths(pack_id)
        pack_dir = Path(paths["pack_dir"]).resolve()
        memes_dir = Path(paths["memes_dir"]).resolve()
        existing = set(await self._categories(event) or {})

        category = str(category or "").strip()
        new_desc = str(new_desc or "").strip()
        key = self._pending_key(event)

        def ask(reason: str) -> dict:
            self._pending[key] = {"time": time.time(), "images": contents, "source": source}
            return {
                "ok": False,
                "need_confirm": True,
                "reason": reason,
                "image_count": len(contents),
                "image_source": source,
            }

        if not category:
            return ask("")

        created_new = False
        if category not in existing:
            if not new_desc:
                return ask(f"兄长说的「{category}」不是现有分类，要确认是放进现有分类还是新建它")
            default_pack = str(mm._resolve_runtime_pack_context().get("pack_id") or "")
            if default_pack != pack_id:
                return {"ok": False, "reason": "当前会话用的不是默认表情包，没法在聊天里新建分类，要去后台建。"}
            try:
                created = await mm._run_default_pack_mutation(
                    "创建表情分类",
                    lambda: mm.category_manager.create_category(category, new_desc),
                )
            except Exception as exc:
                return {"ok": False, "reason": f"新建分类失败：{exc}"}
            if not created:
                return {"ok": False, "reason": f"新建分类「{category}」失败，分类名可能不合法。"}
            mm._reload_personas()
            created_new = True

        try:
            mm.semantic_task_manager.begin_external_pack_operation(pack_id, "聊天中收藏表情")
        except RuntimeError as exc:
            self._pending[key] = {"time": time.time(), "images": contents, "source": source}
            return {"ok": False, "reason": f"表情库正忙（{exc}），图先暂存着，过一会儿再说一次。"}

        saved = dup = failed = 0
        try:
            for content in contents:
                try:
                    await asyncio.to_thread(save_chat_upload_image, memes_dir, category, content)
                    saved += 1
                except DuplicateEmojiError:
                    dup += 1
                except Exception as exc:
                    failed += 1
                    logger.warning(f"meme_saver: 保存失败 {exc}")
            if saved:
                try:
                    await asyncio.to_thread(invalidate_semantic_metadata, pack_dir)
                except Exception as exc:
                    logger.warning(f"meme_saver: 语义元数据刷新失败 {exc}")
                await mm.reload_emotions()
        finally:
            mm.semantic_task_manager.end_external_pack_operation(pack_id)

        self._pending.pop(key, None)
        logger.info(
            f"meme_saver: {event.get_sender_id()} 收藏到 {pack_id}/{category}："
            f"新增{saved} 重复{dup} 失败{failed + read_failed}（来源：{source}）"
        )
        result = {
            "ok": saved > 0 or dup > 0,
            "pack": pack_id,
            "category": category,
            "created_new_category": created_new,
            "saved": saved,
            "duplicate": dup,
            "failed": failed + read_failed,
            "image_source": source,
        }
        if not result["ok"]:
            result["reason"] = "图片读取或保存失败了。"
        return result

    # ------------------------------------------------------------- LLM 工具

    @filter.llm_tool(name="save_meme")
    async def save_meme(
        self,
        event: AstrMessageEvent,
        category: str = "",
        new_category_description: str = "",
    ) -> str:
        """把聊天里的图片/表情包保存进佳树自己的表情包库，以后聊天时可以发出来。
        只有当对方明确要求“存下来/收藏/加进表情包”或在回答“放哪个分类”时才调用，不要自作主张收图。
        图片会自动从：当前消息、对方引用的消息、暂存的图或最近几分钟聊天里的图片中获取，不需要你传图片。
        只有在你很确定该放哪个分类时才填 category；拿不准就留空，工具会暂存图片，然后你问对方放哪。
        如果对方要新建分类，category 填新分类名，new_category_description 写一句它适合的情绪/场景。

        Args:
            category(string): 要存入的分类名（现有分类，或对方已确认的新分类名）；拿不准就留空。
            new_category_description(string): 仅在新建分类时填写：这个分类适用的情绪/场景。其余情况留空。
        """
        if not event.is_admin():
            return _dumps({"ok": False, "reason": "只有兄长大人（管理员）可以让佳树收表情包，请委婉拒绝对方。"})
        handled = event.get_extra(HANDLED_KEY)
        if handled:
            return _dumps({**handled, "note": "这一轮已经处理过了，直接按结果回复即可。"})
        result = await self._save(event, category, new_category_description)
        if result.get("need_confirm"):
            result["existing_categories"] = await self._categories(event)
            result["instruction"] = "图片已暂存10分钟。用佳树的语气问兄长放哪个分类（可给建议），兄长回答后带上分类再调用一次。"
        event.set_extra(HANDLED_KEY, result)
        return _dumps(result)
