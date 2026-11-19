"""Offline checks for speaker identity in the rewrite context."""

import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins"))
sys.path.insert(0, os.path.dirname(HERE))  # 源码里的 kaju_core
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from astrbot.api.event import AstrMessageEvent
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context
from kaju_core.voice import card, rewrite
from kaju_style.main import KajuStyle


async def main():
    context = Context()
    style = KajuStyle(context, {"rewrite": {"enable": True}})
    group = AstrMessageEvent(sender="111", group="222", name="小雨", text="我去睡了")
    req = ProviderRequest("SYS", contexts=[
        {"role": "user", "content": "先去休息吧"},
        {"role": "user", "content": "[发言人：555，QQ 12345678] 晚安"},
    ])
    await style.rewrite_snapshot(group, req)
    assert group.get_extra("_ks_rw_title") == "对方"
    assert group.get_extra("_ks_rw_ctx") == ["身份不明：先去休息吧", "555：晚安", "对方：我去睡了"]
    assert rewrite.label("user", "[发言人：，QQ 123] 晚安", lambda qq, name: "") == "身份不明：晚安"

    class AddressBook:
        def address_of(self, qq, name):
            return {"111": "小雨学姐", "12345678": "555学长"}.get(qq, "")

    context.stars = [SimpleNamespace(star_cls=AddressBook())]
    await style.rewrite_snapshot(group, req)
    assert group.get_extra("_ks_rw_ctx") == ["身份不明：先去休息吧", "555学长：晚安", "小雨学姐：我去睡了"]

    quoted = ProviderRequest("SYS", contexts=[])
    quoted.extra_user_content_parts = [SimpleNamespace(text="<Quoted Message>\n(555): 明天一起拍照吧\n</Quoted Message>")]
    await style.rewrite_snapshot(group, quoted)
    assert group.get_extra("_ks_rw_ctx")[-1] == "小雨学姐：我去睡了（引用555：明天一起拍照吧）"
    quoted.extra_user_content_parts = [SimpleNamespace(text="<Quoted Message>\n明天一起拍照吧\n</Quoted Message>")]
    await style.rewrite_snapshot(group, quoted)
    assert group.get_extra("_ks_rw_ctx")[-1] == "小雨学姐：我去睡了（引用身份不明：明天一起拍照吧）"

    # 群聊（2026-11-09）：前文用聊天记录里这一句之前的几行群聊（别人之间说的也在），和训练时一样
    class Diary:
        def __init__(self, recs):
            self.recs = recs

        def recent(self, chat, n):
            return [r for r in self.recs if r["c"] == chat][-n:]

    class Life:
        def __init__(self, recs):
            self.diary = Diary(recs)

        def log_own(self, chat, text):
            pass

    recs = [{"c": "g222", "u": "999", "n": "哆啦a梦", "x": "感觉两个号比较合适"},
            {"c": "g333", "u": "999", "n": "哆啦a梦", "x": "别的群的话"},
            {"c": "g222", "u": "self", "n": "佳树", "x": "嗯嗯\n是呀"},
            {"c": "g222", "u": "12345678", "n": "555", "x": "太贵了"},
            {"c": "g222", "u": "111", "n": "小雨", "x": "我去睡了"},
            {"c": "g222", "u": "999", "n": "哆啦a梦", "x": "晚安"}]  # 她开始回之后才到的：不算前文
    context.stars = [SimpleNamespace(star_cls=AddressBook()), SimpleNamespace(star_cls=Life(recs))]
    hist = ProviderRequest("SYS", contexts=[{"role": "user", "content": "先去休息吧"}])
    await style.rewrite_snapshot(group, hist)
    assert group.get_extra("_ks_rw_ctx") == ["哆啦a梦：感觉两个号比较合适", "佳树：嗯嗯 / 是呀", "555学长：太贵了",
                                             "小雨学姐：我去睡了"], group.get_extra("_ks_rw_ctx")
    style.config["rewrite"]["group_ctx_lines"] = 1
    await style.rewrite_snapshot(group, hist)
    assert group.get_extra("_ks_rw_ctx") == ["555学长：太贵了", "小雨学姐：我去睡了"]
    style.config["rewrite"]["group_ctx_lines"] = 0  # 关掉：老办法（她自己那段对话）
    await style.rewrite_snapshot(group, hist)
    assert group.get_extra("_ks_rw_ctx") == ["身份不明：先去休息吧", "小雨学姐：我去睡了"]
    style.config["rewrite"].pop("group_ctx_lines")
    # 戳一戳：消息改写过（TA刚说的话包在里面）→ 那句不重复进前文
    poke = AstrMessageEvent(sender="999", group="222", name="哆啦a梦",
                            text="（有人戳了戳你。戳你之前，TA刚说了：「晚安」）")
    await style.rewrite_snapshot(poke, ProviderRequest("SYS", contexts=[]))
    assert poke.get_extra("_ks_rw_ctx")[-2:] == ["小雨学姐：我去睡了", "对方：（有人戳了戳你。戳你之前，TA刚说了：「晚安」）"], \
        poke.get_extra("_ks_rw_ctx")
    # 记录里对不上这一句：到这个人最后一句为止都算前文
    other = AstrMessageEvent(sender="12345678", group="222", name="555", text="[图片] 看这个")
    await style.rewrite_snapshot(other, ProviderRequest("SYS", contexts=[]))
    assert other.get_extra("_ks_rw_ctx")[-2:] == ["555学长：太贵了", "555学长：[图片] 看这个"], other.get_extra("_ks_rw_ctx")
    # 记录里没有这个群：老办法
    group2 = AstrMessageEvent(sender="111", group="444", name="小雨", text="早")
    await style.rewrite_snapshot(group2, hist)
    assert group2.get_extra("_ks_rw_ctx") == ["身份不明：先去休息吧", "小雨学姐：早"]

    private = AstrMessageEvent(text="我去睡了")
    context.stars = []
    await style.rewrite_snapshot(private, ProviderRequest("SYS", contexts=[{"role": "user", "content": "先去休息吧"}]))
    assert private.get_extra("_ks_rw_ctx")[0] == "兄长大人：先去休息吧"
    assert card.fix_formal("您说的对", "说得对", "") == "您说的对"
    assert card.fix_formal("您说的对", "说得对", "小雨学姐") == "小雨学姐说的对"
    assert style._restyle("佳树今天买了很多好吃的东西，晚上准备和大家一起吃") == "佳树今天买了很多好吃的东西，晚上准备和大家一起吃"
    style.config["rhythm"] = {"split_long": 20}
    assert "\n" in style._restyle("佳树今天买了很多好吃的东西，晚上准备和大家一起吃")


if __name__ == "__main__":
    asyncio.run(main())
    print("style identity checks passed")
