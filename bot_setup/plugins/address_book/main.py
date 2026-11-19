"""称呼簿：佳树怎么叫群里的每个人。

- "兄长大人"只叫一个人：兄长大人本人（主人 QQ，默认 111111111），这个称呼固定，别人不能用、也不能改走。
- 其他人默认叫"名字+学长"（男生）或"名字+学姐"（女生）：名字用群名片（没有就用 QQ 昵称），
  性别看 QQ 资料（查一次存 7 天）；资料里没写性别的先叫学长。配置 sex_overrides 可以手动指定。
- 每个人只能改自己的称呼（比如"叫我女王大人""我是女生"），由模型调用 set_address / clear_address；
  替别人改不行，改成"兄长大人"也不行。
- 每次请求 LLM 前，在用户消息前标注发言人（昵称 + QQ），系统提示里放称呼规则和称呼表。
- 群聊记录（内置群聊上下文）里每条消息也带上 QQ 号和该怎么叫TA：[昵称(QQ 123，叫TA昵称学长)/时间]，
  @ 和引用也一样，改名、重名时也分得清是谁。
"""

import asyncio
import json
import os
import re
import sys
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Reply
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from kaju_core import paths, people

PLUGIN_NAME = "astrbot_plugin_address_book"
OWNER_ADDRESS = "兄长大人"
DEFAULT_OWNER = os.environ.get("KAJU_OWNER_QQ", "").strip()  # 兜底；兄长正式登记在 kaju_data\self\people\people.json
MAX_ADDRESS_LEN = 12
MAX_TABLE_ROWS = 40
SEX_TTL = 7 * 86400
SEX_RETRY = 3600  # 查不到时隔多久再查

FEMALE_WORDS = ("女", "female", "f", "girl", "学姐")
MALE_WORDS = ("男", "male", "m", "boy", "学长")


def _data_dir() -> str:
    folder = paths.self_dir(PLUGIN_NAME)
    os.makedirs(folder, exist_ok=True)
    return folder


def clean_name(name: str) -> str:
    """群名片里的换行、空格去掉（有人的名片是"哆啦\\n\\nb\\n梦"）。"""
    return re.sub(r"\s+", "", str(name or ""))


def default_address(name: str, sex: str) -> str:
    return clean_name(name) + ("学姐" if sex == "female" else "学长")


def parse_sex(text: str) -> str:
    t = str(text or "").strip().lower()
    if t in FEMALE_WORDS or t.startswith("女"):
        return "female"
    if t in MALE_WORDS or t.startswith("男"):
        return "male"
    return ""


def parse_overrides(text: str) -> dict[str, str]:
    """"321321321=女, 123123123=男" → {qq: female|male}"""
    out: dict[str, str] = {}
    text = re.sub(r"\s*([=:：])\s*", r"\1", str(text or ""))
    for part in re.split(r"[,，;；\s]+", text):
        if "=" in part or "：" in part or ":" in part:
            qq, _, sex = re.split(r"([=:：])", part, maxsplit=1)
            sex = parse_sex(sex)
            if qq.strip().isdigit() and sex:
                out[qq.strip()] = sex
    return out


def id_text(qq: str) -> str:
    """号码怎么写给她看：QQ 号写"QQ n"；B站私信来的人（kaju_dm，id 是 bili_<UID>）写"B站 UID"。"""
    return people.label(qq)


def quote_only_text(event) -> str:
    """这条只有引用（加 @）、没写字时，写给大脑看的那句；不是这种消息就空。"""
    me = str(event.get_self_id() or "")
    quote, at_me = None, False
    for c in event.get_messages() or []:
        if isinstance(c, Reply) and quote is None:
            quote = c
        elif isinstance(c, At) and me and str(getattr(c, "qq", "")) == me:
            at_me = True
    if quote is None:
        return ""
    if me and str(getattr(quote, "sender_id", "") or "") == me:
        who = "佳树自己"
    else:
        who = str(getattr(quote, "sender_nickname", "") or "").strip() or "别人"
    said = str(getattr(quote, "message_str", "") or "").strip().replace("\n", " / ")[:80]
    what = f"“{said}”" if said else "那条"
    return f"（这条没写字，只引用了{who}的{what}" + ("，还 @ 了佳树）" if at_me else "）")


def is_owner_title(address: str) -> bool:
    """别人不能被叫"兄长大人"（含"兄长"的都算）。"""
    return "兄长" in str(address or "")


@register(PLUGIN_NAME, "dsh", "称呼簿：只叫主人兄长大人，别人叫XX学长/学姐，每人只能改自己的称呼", "2.3.0")
class AddressBook(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        folder = _data_dir()
        self._path = os.path.join(folder, "addresses.json")
        self._people_path = os.path.join(folder, "people.json")
        self._lock = asyncio.Lock()
        self._book: dict[str, dict] = self._load(self._path)
        self._people: dict[str, dict] = self._load(self._people_path)  # qq -> {name, sex, t}
        self._people_dirty = False
        self._gcc = None
        self._orig_format = None
        self._hook_group_context()

    # ---------- 配置 ----------
    @property
    def owner(self) -> str:
        """兄长大人本人：身份表（kaju_core.people）说了算；身份表还没登记时用老配置 owner_qq。"""
        return people.owner() or str(self.config.get("owner_qq") or DEFAULT_OWNER).strip()

    def _overrides(self) -> dict[str, str]:
        return parse_overrides(self.config.get("sex_overrides", ""))

    # ---------- 存取 ----------
    @staticmethod
    def _load(path: str) -> dict[str, dict]:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"address_book: 读取 {os.path.basename(path)} 失败: {exc}")
            return {}

    @staticmethod
    def _write(path: str, data: dict) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    async def _save(self) -> None:
        self._write(self._path, self._book)

    def _save_people(self) -> None:
        if self._people_dirty:
            try:
                self._write(self._people_path, self._people)
                self._people_dirty = False
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"address_book: 保存 people.json 失败: {exc}")

    # ---------- 称呼 ----------
    def sex_of(self, qq: str) -> str:
        qq = str(qq)
        return self._overrides().get(qq) or (self._people.get(qq) or {}).get("sex") or "unknown"

    def address_of(self, qq: str, name: str | None = None) -> str:
        """佳树叫这个人什么。别的插件（kaju_heart / kaju_style）也调这个；它们也从这里的 owner 认兄长大人本人。"""
        qq = str(qq)
        if qq == self.owner:
            return OWNER_ADDRESS
        entry = self._book.get(qq)
        if entry and entry.get("address") and not is_owner_title(entry["address"]):
            return entry["address"]
        # 戳一戳之类的事件不带昵称，传进来的"名字"就是 QQ 号：不叫号码（兄长大人 11-12："不要带QQ号，只喊学长或学姐"）。
        # 先找记下的名字，还没有就只叫"学长 / 学姐"。（"555" 这种纯数字群名片不是 QQ 号，照常叫"555学长"。）
        known = [n for n in (name, (self._people.get(qq) or {}).get("name"), (entry or {}).get("nickname"))
                 if n and clean_name(n) != qq]
        return default_address(known[0] if known else "", self.sex_of(qq))

    def find_person(self, text: str) -> list[tuple[str, str]]:
        """按称呼 / 群名片 / 昵称 / QQ 号找人 → [(QQ, 怎么叫TA)]（认人用：抖音上的人说"我是女王大人"）。
        只找有 QQ 号的人；兄长大人本人也算（"兄长大人"就是他）。完全对上的优先，没有再找包含的。"""
        t = clean_name(text).strip("“”\"'「」")
        if not t:
            return []
        if t.isdigit():
            return [(t, self.address_of(t))] if t == self.owner or t in self._book or t in self._people else []
        if is_owner_title(t):
            return [(self.owner, OWNER_ADDRESS)]
        names: dict[str, set[str]] = {}
        for qq, e in self._book.items():
            names.setdefault(qq, set()).update(x for x in (e.get("address"), e.get("nickname")) if x)
        for qq, p in self._people.items():
            if p.get("name"):
                names.setdefault(qq, set()).add(p["name"])
        for qq in names:
            names[qq].add(self.address_of(qq))
        names = {q: {clean_name(x) for x in ns} for q, ns in names.items() if q.isdigit()}
        exact = [q for q, ns in names.items() if t in ns]
        hits = exact or [q for q, ns in names.items() if len(t) >= 2 and any(t in x or x in t for x in ns if len(x) >= 2)]
        return [(q, self.address_of(q)) for q in hits[:5]]

    def _remember_name(self, qq: str, name: str) -> None:
        qq, name = str(qq), clean_name(name)
        if not qq or not name:
            return
        p = self._people.setdefault(qq, {})
        if p.get("name") != name:
            p["name"] = name
            self._people_dirty = True

    @staticmethod
    def _client(event: AstrMessageEvent):
        return getattr(event, "bot", None)

    async def _ensure_sex(self, event: AstrMessageEvent, qq: str, name: str = "") -> None:
        """QQ 资料里的性别，查一次存 7 天（查不到 1 小时后再试）。"""
        qq = str(qq)
        if not qq.isdigit() or qq == self.owner or qq == str(event.get_self_id() or ""):
            return
        if name:
            self._remember_name(qq, name)
        p = self._people.setdefault(qq, {})
        now = time.time()
        ttl = SEX_TTL if p.get("sex") in ("male", "female") else SEX_RETRY
        if now - float(p.get("t", 0)) < ttl:
            return
        bot = self._client(event)
        if bot is None:
            return
        p["t"] = now
        self._people_dirty = True
        try:
            res = await asyncio.wait_for(bot.call_action("get_stranger_info", user_id=int(qq)), 5)
            data = res.get("data", res) if isinstance(res, dict) else {}
            sex = str((data or {}).get("sex") or "unknown")
            p["sex"] = sex if sex in ("male", "female") else "unknown"
            if not p.get("name") and (data or {}).get("nickname"):
                p["name"] = clean_name(data["nickname"])
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"address_book: 查 {qq} 的性别失败: {exc}")

    # ---------- 群聊记录带 QQ 号和称呼 ----------
    def label(self, qq: str, name: str, self_id: str) -> str:
        qq = str(qq)
        if qq == self_id:
            return "就是你"
        if qq == self.owner:
            return f"QQ {qq}，兄长大人本人"
        return f"{id_text(qq)}，叫TA{self.address_of(qq, name)}"

    def tag_group_line(self, event: AstrMessageEvent, text: str) -> str:
        """给内置群聊上下文的一行记录加上 QQ 号和称呼。

        "[昵称/12:00:00]:  你好 [At: 某人]" → "[昵称(QQ 1，叫TA昵称学长)/12:00:00]:  你好 [At: 某人(QQ 2，叫TA某人学姐)]"
        """
        self_id = str(event.get_self_id() or "")
        sender_id = str(event.get_sender_id() or "")
        nick = event.message_obj.sender.nickname
        head = f"[{nick}/"
        if sender_id and text.startswith(head):
            text = f"[{nick}({self.label(sender_id, nick, self_id)})/" + text[len(head):]

        for comp in event.get_messages():
            if isinstance(comp, At):
                qq = str(comp.qq)
                if qq == "all":
                    continue
                lab = self.label(qq, comp.name or "", self_id)
                text = text.replace(f" [At: {comp.name}]", f" [At: {comp.name}({lab})]", 1)
            elif isinstance(comp, Reply):
                qq = str(comp.sender_id or "")
                if qq and qq != "0":
                    name = comp.sender_nickname
                    lab = self.label(qq, name or "", self_id)
                    text = text.replace(f" [Quote({name}: ", f" [Quote({name}({lab}): ", 1)
        return text

    async def _prepare(self, event: AstrMessageEvent) -> None:
        """记下名字、查好性别（发言人、@ 到的人、被引用的人）。"""
        await self._ensure_sex(event, str(event.get_sender_id() or ""), event.get_sender_name() or "")
        for comp in event.get_messages() or []:
            if isinstance(comp, At) and str(comp.qq) != "all":
                await self._ensure_sex(event, str(comp.qq), comp.name or "")
            elif isinstance(comp, Reply) and str(comp.sender_id or "0") != "0":
                await self._ensure_sex(event, str(comp.sender_id), comp.sender_nickname or "")
        self._save_people()

    def _hook_group_context(self) -> None:
        for meta in self.context.get_all_stars():
            gcc = getattr(getattr(meta, "star_cls", None), "group_chat_context", None)
            if gcc is not None and hasattr(gcc, "_format_message"):
                break
        else:
            return

        orig = gcc._format_message

        async def _format_message(event, *args, **kwargs):
            text = await orig(event, *args, **kwargs)
            try:
                await self._prepare(event)
                return self.tag_group_line(event, text)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"address_book: 群聊记录加 QQ 号失败: {exc}")
                return text

        gcc._format_message = _format_message
        self._gcc, self._orig_format = gcc, orig
        logger.info("address_book: 群聊记录已带上 QQ 号和称呼")

    async def terminate(self):
        if self._gcc is not None and self._orig_format is not None:
            self._gcc._format_message = self._orig_format
        self._save_people()

    # 加载时内置插件可能还没实例化：在第一条群消息时挂上（要早于内置群聊上下文记录这条消息）
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=sys.maxsize)
    async def ensure_hooked(self, event: AstrMessageEvent):
        if self._gcc is None:
            self._hook_group_context()

    # ---------- 辅助 ----------
    @staticmethod
    def _mentioned(event: AstrMessageEvent) -> dict[str, str]:
        """本条消息里 @ 到的人（不含机器人自己），qq -> 昵称"""
        self_id = str(event.get_self_id() or "")
        out: dict[str, str] = {}
        for comp in event.message_obj.message or []:
            if isinstance(comp, At):
                qq = str(comp.qq)
                if qq not in ("all", self_id):
                    out[qq] = comp.name or ""
        return out

    # ---------- 注入 ----------
    def build_rules(self, event: AstrMessageEvent) -> str:
        sender_id = str(event.get_sender_id() or "")
        sender_name = event.get_sender_name() or ""
        mentioned = self._mentioned(event)
        is_owner = sender_id == self.owner

        # 称呼表：优先放当前发言人和被 @ 的人，其余按最近修改排序
        first = [q for q in [sender_id, *mentioned] if q in self._book]
        ordered = list(dict.fromkeys(first)) + [
            qq for qq, _ in sorted(self._book.items(), key=lambda kv: kv[1].get("time", 0), reverse=True)
            if qq not in first
        ]
        rows = [
            f"  - {self._book[qq].get('nickname') or '某人'}（{id_text(qq)}）：叫“{self.address_of(qq)}”"
            for qq in ordered[:MAX_TABLE_ROWS]
            if qq != self.owner
        ]

        if is_owner:
            now = f"- 现在跟你说话的就是兄长大人本人（QQ {sender_id}），叫他“{OWNER_ADDRESS}”。"
        else:
            now = (
                f"- 现在跟你说话的是 {sender_name}（{id_text(sender_id)}），不是兄长大人，"
                f"这次叫TA“{self.address_of(sender_id, sender_name)}”。"
            )
        lines = [
            "",
            "【称呼规则（优先于上面所有关于称呼的说法）】",
            now,
            f"- “{OWNER_ADDRESS}”只属于一个人：兄长大人本人（QQ {self.owner}）。对其他任何人都不叫“{OWNER_ADDRESS}”，"
            "也不叫“兄长”“哥哥”，TA自己要求也不行（笑着说这个称呼是兄长大人专属的）。",
            "- 其他人默认叫“名字+学长”（男生）或“名字+学姐”（女生），名字用TA的群名片；称呼表里登记过的人按表里的叫。"
            "群聊记录里每个人名字后面都写了该怎么叫TA，照着叫，同一个人每次叫法一样。",
            "- 每个人只能改自己的称呼：有人要你以后换个叫法叫TA自己（包括说自己其实是女生/男生、想被叫学姐/学长），"
            "就开开心心答应，并调用 set_address 记下新称呼；想改回默认就调用 clear_address。"
            "有人想替别人改称呼、或者让你换个叫法叫别人，就笑着说要本人来说才行，不调用工具。",
            "- 称呼不能是脏话、侮辱人的词或越过兄妹界限的称呼；遇到这种请求，用妹妹的方式岔开，不要调用工具。",
            "- 消息开头的 [发言人：…] 是系统标注，回复里不要复述，也不要提 QQ 号。",
            "- 群聊记录里名字后面的 (QQ …) 也是系统标注：QQ 号相同就是同一个人，哪怕名字改了；"
            "名字一样但 QQ 号不同就是两个人。(就是你) 指的是你自己。回复里只用称呼，不提 QQ 号。",
            "- 以前的聊天里你可能管别人也叫过“兄长大人”，那是以前的习惯，现在不这么叫了。",
        ]
        if mentioned:
            lines.append(
                "- 这条消息 @ 到了："
                + "、".join(
                    f"{n or '某人'}（{'兄长大人本人' if q == self.owner else f'QQ {q}，叫“{self.address_of(q, n)}”'}）"
                    for q, n in mentioned.items()
                )
            )
        lines.append("- 称呼表（自己要求过的特别称呼）：" + ("\n" + "\n".join(rows) if rows else "（暂无）"))
        return "\n".join(lines)

    @filter.on_llm_request()
    async def inject(self, event: AstrMessageEvent, req: ProviderRequest):
        sender_id = str(event.get_sender_id() or "")
        if not sender_id:
            return
        sender_name = event.get_sender_name() or ""
        try:
            await self._prepare(event)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"address_book: 准备称呼失败: {exc}")

        # 标注发言人，写进历史后模型也能分清以前谁说过什么
        tag = f"[发言人：{sender_name}，{id_text(sender_id)}]"
        if (req.prompt or "").strip() == "<attachment>":
            # 11-19 12:30：兄长引用哆啦a梦的“什么配置能玩”再 @ 她、没写字，AstrBot 把这条写成 "<attachment>"，
            # 大脑当成“发了个附件”，反问“要佳树看什么”。这里照实写出这条是什么。
            req.prompt = quote_only_text(event) or req.prompt
        if req.prompt is not None and not req.prompt.startswith("[发言人："):
            req.prompt = f"{tag} {req.prompt}"

        req.system_prompt = (req.system_prompt or "") + self.build_rules(event)

    # ---------- 工具 ----------
    @filter.llm_tool(name="set_address")
    async def set_address(self, event: AstrMessageEvent, address: str, target_qq: str = ""):
        """有人要你以后用某个称呼叫TA自己时（比如"叫我女王大人"，或者说自己其实是女生/男生），调用这个工具记下来。只能改发言人自己的称呼。

        Args:
            address(string): 以后叫发言人的称呼，例如“女王大人”“小雨学姐”，不超过 12 个字
            target_qq(string): 不用填；只能是发言人自己的 QQ
        """
        sender_id = str(event.get_sender_id() or "")
        target = str(target_qq or "").strip() or sender_id
        address = str(address or "").strip().strip("“”\"'「」")

        if target != sender_id:
            return "没记：每个人只能改自己的称呼。用佳树的口吻笑着说，要TA本人来跟佳树说才行。"
        if sender_id == self.owner:
            return f"没记：兄长大人就是兄长大人，这个称呼不会改。用佳树的口吻撒个娇说佳树只想叫他“{OWNER_ADDRESS}”。"
        if is_owner_title(address) or "哥哥" in address:
            return "没记：这个称呼是兄长大人专属的，不能叫别人。用佳树的口吻笑着拒绝，可以说照旧叫TA原来的称呼。"
        if not address or len(address) > MAX_ADDRESS_LEN:
            return f"没记：称呼需要 1~{MAX_ADDRESS_LEN} 个字。"

        nickname = clean_name(event.get_sender_name() or "") or self._book.get(target, {}).get("nickname", "")
        async with self._lock:
            self._book[target] = {
                "address": address,
                "nickname": nickname,
                "set_by": sender_id,
                "time": int(time.time()),
            }
            await self._save()
        logger.info(f"address_book: {sender_id}({nickname}) 把自己的称呼设为 {address}")
        return f"已记下：以后叫 {nickname or target} “{address}”。现在用佳树的口吻回应一下。"

    @filter.llm_tool(name="clear_address")
    async def clear_address(self, event: AstrMessageEvent, target_qq: str = ""):
        """有人想让你把TA自己的称呼改回默认（名字+学长/学姐）时调用。只能改发言人自己的。

        Args:
            target_qq(string): 不用填；只能是发言人自己的 QQ
        """
        sender_id = str(event.get_sender_id() or "")
        target = str(target_qq or "").strip() or sender_id
        if target != sender_id:
            return "没改：每个人只能改自己的称呼。用佳树的口吻说要TA本人来说才行。"
        async with self._lock:
            removed = self._book.pop(target, None)
            if removed:
                await self._save()
        logger.info(f"address_book: {sender_id} 清除了自己的称呼")
        return f"已恢复默认称呼“{self.address_of(sender_id, event.get_sender_name() or '')}”。现在用佳树的口吻回应一下。"

    # ---------- 谁是谁（身份表 kaju_core.people） ----------
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("佳树认人")
    async def cmd_people(self, event: AstrMessageEvent, action: str = "", platform: str = "", account: str = "",
                         key: str = ""):
        """一个人在 QQ / B站 / 抖音 的号认成同一个人：/佳树认人（看表）｜认 平台 号 [QQ号或钥匙，默认兄长]｜不认 平台 号
        平台写 B站 / 抖音（抖音的号用主页链接 douyin.com/user/ 后面那串 sec_uid）。"""
        reg = people.registry()
        names = {"b站": "bili", "bili": "bili", "哔哩哔哩": "bili", "抖音": "douyin", "douyin": "douyin", "qq": "qq"}
        try:
            if action in ("认", "绑", "link"):
                site = names.get(platform.strip().lower())
                if not site or not account:
                    yield event.plain_result("用法：/佳树认人 认 B站|抖音 号 [QQ号，默认兄长]")
                    return
                said = reg.link(key.strip() or self.owner, site, account)
            elif action in ("不认", "解绑", "unlink"):
                site = names.get(platform.strip().lower())
                if not site or not account:
                    yield event.plain_result("用法：/佳树认人 不认 B站|抖音 号")
                    return
                said = reg.unlink(site, account)
            elif action:
                yield event.plain_result("用法：/佳树认人｜认 平台 号 [QQ号]｜不认 平台 号")
                return
            else:
                said = ""
        except ValueError as e:
            yield event.plain_result(f"没改：{e}")
            return
        if said:
            logger.info(f"address_book: 身份表 {said}（{event.get_sender_id()}）")
        rows = reg.describe()
        yield event.plain_result(((said + "\n") if said else "") + "谁是谁：\n" + ("\n".join(rows) if rows else "（还没登记）"))
