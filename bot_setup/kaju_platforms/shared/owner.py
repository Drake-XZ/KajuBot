"""找兄长大人本人（原来在 kaju_basics 的 main.py 里）：他是谁、和他私聊的会话、私聊他一句。

Owner 是 mixin，宿主要有 body（kaju_core.body.Body）。
"""

from __future__ import annotations

import os

from kaju_core import people

DEFAULT_OWNER = os.environ.get("KAJU_OWNER_QQ", "").strip()  # 兜底；兄长正式登记在 kaju_data\self\people\people.json


class Owner:
    def _owner(self) -> str:
        """兄长大人本人的 QQ：身份表（kaju_core.people）；没登记时问称呼簿（有 address_of 的那个部分的 owner）。"""
        if people.owner():
            return people.owner()
        book = self.body.find("address_of")
        owner = str(getattr(book, "owner", "") or "").strip() if book is not None else ""
        return owner or DEFAULT_OWNER

    def _owner_umo(self, event=None) -> str:
        """和兄长大人私聊的会话 id（有消息就借它的平台名）。"""
        return self.body.private_chat_id(self._owner(), like=str(getattr(event, "unified_msg_origin", "") or ""))

    async def _tell_owner(self, text: str) -> bool:
        """私聊兄长大人一句（QQ）。发不出去返回 False。"""
        try:
            await self.body.qq_call("send_private_msg", user_id=int(self._owner()),
                                    message=[{"type": "text", "data": {"text": text}}])
            return True
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_basics: 私聊兄长失败 {type(e).__name__}: {e}")
            return False
