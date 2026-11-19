"""她跟外面打交道要用的几样东西。kaju_core 里的代码只认这里，不认 AstrBot、不认哪个聊天平台（QQ / B站 / 抖音）。

由接入的平台实现（现在是 AstrBot：kaju_astr.AstrBody）：
- think(prompt, system, who, model, timeout)：让一个模型读一段话写东西。model = 指定模型 id；
  不指定就用 who（哪段聊天）正在用的模型；who 也没有就用默认模型。没有可用的模型抛异常。
- model_id(model, who)：要用的模型 id——指定的 model 在就用它，不在（或没指定）就用 who 正在用的模型；都没有返回 ""。
- slot_model(slot, model, who)：这项工作（utils / learner / fast……，kaju_core/slots.py）要用的模型 id：
  model 填了用 model；没填看那一格；格子空着用主模型。
- generate(model_id, prompt, system, timeout)：用这个模型写东西（不做挑选）。
- chat(messages, temperature, extra_body, timeout)：直接发一组 messages 给正在用的模型（能带 extra_body，比如关掉思考）；
  没有可用的模型返回 None。
- conversation_id(who)：这段聊天现在是哪一次对话（换了新对话 id 就变；拿不到返回 ""）。
- settings()：全局设置（timezone、admins_id……）。
- qq()：(QQ 平台, QQ 客户端)，没有是 (None, None)（只给 QQ 专用的部分用：私信借这个适配器进完整流程、找兄长、说说）。
- group_name(turn, gid)：群叫什么（拿不到返回 ""）。
- find(attr)：别的部分（现在还是别的插件）里有 attr 这个属性的那个对象，没有返回 None。
- stars()：别的部分的清单（每项有 star_cls / name / activated），find 不够用时自己挑。
- send(where, text, image)：往一段聊天（会话 id）发一条，图（本机文件）在前、文字在后。
- private_chat_id(user_id, like)：和 user_id 私聊的会话 id（like = 一段已知的会话 id，借它的平台名；没有就用 QQ 的）。
- qq_call(action, turn, **params)：调一个 QQ（OneBot v11）接口，返回去掉外壳的 data；连不上 QQ 抛 RuntimeError。
- add_to_history(where, user, assistant)：往一段聊天当前的对话里补一轮，她以后在那段聊天里看得到。
- log：info / warning / debug / error。

一条消息（turn）是鸭子类型，用到哪些就要有哪些（AstrBot 的事件本来就是这样）：
  get_sender_id()、get_sender_name()、get_group_id()、get_self_id()、message_str、get_messages()、
  unified_msg_origin、get_extra(key)、set_extra(key, value)。
"""

from __future__ import annotations

import logging
from typing import Any

# 类型标注用的名字（都是鸭子类型）：一条消息 / 发给模型的请求 / 模型的回复（AstrBot 里是 AstrMessageEvent /
# ProviderRequest / LLMResponse）。请求要有 system_prompt、contexts、prompt、extra_user_content_parts。
Turn = Any
Request = Any
Answer = Any


class Body:
    def __init__(self, log=None):
        self.log = log or logging.getLogger("kaju")

    async def think(self, prompt: str, system: str = "", who: str = "", model: str = "",
                    timeout: float | None = None) -> str:
        raise NotImplementedError

    async def model_id(self, model: str = "", who: str = "") -> str:
        return ""

    async def slot_model(self, slot: str, model: str = "", who: str = "") -> str:
        """这项工作要用的模型 id（2026-11-18 每项工作一格，kaju_core/slots.py）：指定了 model 就用它；
        没指定就看 slot 那一格（kaju_data/accounts/model_slots.json）；格子空着就和 model_id 一样用主模型。"""
        return await self.model_id(model, who)

    async def generate(self, model_id: str, prompt: str, system: str = "", timeout: float | None = None) -> str:
        raise NotImplementedError

    async def chat(self, messages: list[dict], temperature: float | None = None, extra_body: dict | None = None,
                   timeout: float | None = None) -> str | None:
        return None

    async def conversation_id(self, who: str) -> str:
        return ""

    def settings(self) -> dict:
        return {}

    def qq(self):
        return None, None

    async def group_name(self, turn, gid: str) -> str:
        return ""

    def find(self, attr: str):
        return None

    def stars(self) -> list:
        return []

    async def send(self, where: str, text: str = "", image: str = "") -> bool:
        return False

    def private_chat_id(self, user_id: str, like: str = "") -> str:
        return ""

    async def qq_call(self, action: str, turn=None, **params):
        raise RuntimeError("连不上 QQ")

    async def add_to_history(self, where: str, user: str, assistant: str) -> bool:
        return False
