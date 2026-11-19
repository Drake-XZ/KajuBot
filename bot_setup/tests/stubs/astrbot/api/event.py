"""Minimal stand-ins for astrbot.api.event used by the offline tests."""


class _Filter:
    class EventMessageType:
        ALL = "all"
        GROUP_MESSAGE = "group"
        PRIVATE_MESSAGE = "private"

    class PermissionType:
        ADMIN = "admin"
        MEMBER = "member"

    def __getattr__(self, name):
        def deco(*a, **k):
            return lambda fn: fn
        return deco


filter = _Filter()


class AstrMessageEvent:
    def __init__(self, sender="111111111", group="", text="", admin=True, name="晴川",
                 self_id="555555555", messages=None, platform="aiocqhttp", raw=None):
        self._s, self._g, self._a, self._n, self._self = sender, group, admin, name, self_id
        self._platform = platform
        self.message_str = text
        self._msgs = messages or []
        self.message_obj = type("MsgObj", (), {})()
        self.message_obj.message = self._msgs
        self.message_obj.raw_message = {"message": raw or []}
        self.unified_msg_origin = f"qq:{'GroupMessage' if group else 'FriendMessage'}:{group or sender}"
        self._extra = {}
        self._stopped = False
        self._result = None
        self.is_at_or_wake_command = False
        self.is_wake = False
        self.sent = []  # event.send 直接发出去的话
        import time as _t
        self.created_at = _t.time()

    async def send(self, chain):
        self.sent.append("".join(str(x) for x in getattr(chain, "chain", [chain])))

    def get_sender_id(self): return self._s
    def get_group_id(self): return self._g
    def get_self_id(self): return self._self
    def get_platform_name(self): return self._platform
    def get_sender_name(self): return self._n
    def get_messages(self): return self._msgs
    def get_message_str(self): return self.message_str
    def is_admin(self): return self._a
    def set_extra(self, k, v): self._extra[k] = v
    def get_extra(self, k=None, default=None): return self._extra.get(k, default)
    def plain_result(self, t): return t
    def stop_event(self): self._stopped = True
    def is_stopped(self): return self._stopped
    def get_result(self): return self._result
    def set_result(self, r): self._result = r
    def clear_result(self): self._result = None


class MessageChain:
    def __init__(self, chain=None): self.chain = chain or []
    def message(self, text): self.chain.append(text); return self
