"""kaju_core.paths：她的东西放在哪（离线，不碰真数据）。python -I tests\\test_kaju_core.py"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "..", "plugins"))
sys.stdout.reconfigure(encoding="utf-8")

from kaju_core import paths  # noqa: E402

fails = 0


def expect(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"got {got!r} want {want!r}")


stub = tempfile.mkdtemp()
kaju = tempfile.mkdtemp()
os.environ.pop("KAJU_DATA", None)
os.environ["STUB_DATA"] = stub
# 测试里：照老的 plugin_data 排法
expect("stub self", paths.self_dir("kaju_life"), os.path.join(stub, "astrbot_plugin_kaju_life"))
expect("stub self full name", paths.self_dir("astrbot_plugin_kaju_life"), os.path.join(stub, "astrbot_plugin_kaju_life"))
expect("stub memorix", paths.self_dir("memorix"), os.path.join(stub, "astrbot_plugin_memorix"))
expect("stub memes", paths.self_dir("meme_manager"), os.path.join(stub, "meme_manager"))
expect("stub account", paths.account("bili_login.json"), os.path.join(stub, "accounts", "bili_login.json"))
expect("stub cache made", os.path.isdir(paths.cache_dir("video")), True)
# 真用时：kaju_data/self|accounts|cache
os.environ["KAJU_DATA"] = kaju
expect("self", paths.self_dir("astrbot_plugin_kaju_heart"), os.path.join(kaju, "self", "kaju_heart"))
expect("self not created", os.path.exists(os.path.join(kaju, "self", "kaju_heart")), False)
expect("memorix", paths.self_dir("astrbot_plugin_memorix"), os.path.join(kaju, "self", "memorix"))
expect("account", paths.account("douyin_profile"), os.path.join(kaju, "accounts", "douyin_profile"))
expect("account parent made", os.path.isdir(os.path.join(kaju, "accounts")), True)
expect("cache", paths.cache_dir("tmp"), os.path.join(kaju, "cache", "tmp"))
expect("legacy name", paths.legacy_name("kaju_life"), "astrbot_plugin_kaju_life")
expect("legacy memes", paths.legacy_name("meme_manager"), "meme_manager")

from qzone_post import nightly  # noqa: E402

expect("nightly dir fn", nightly._dir(paths.self_dir, "kaju_life"), os.path.join(kaju, "self", "kaju_life"))
expect("nightly dir str", nightly._dir("X", "kaju_life"), os.path.join("X", "astrbot_plugin_kaju_life"))

# fresh：没重新部署过什么都不做；文件比 import 时新才拿掉
import time  # noqa: E402

import kaju_core  # noqa: E402
from kaju_core.senses import relook  # noqa: E402

expect("fresh unchanged keeps", kaju_core.fresh("senses"), [])
expect("fresh unchanged same module", sys.modules.get("kaju_core.senses.relook") is relook, True)
pkg = sys.modules["kaju_core.senses"]
real = pkg.LOADED_AT
pkg.LOADED_AT = time.time() - 10 ** 9  # 假装很早以前 import 的 → 文件都"更新"
gone = kaju_core.fresh("senses")
expect("fresh changed drops pkg", "kaju_core.senses" in gone and "kaju_core.senses.relook" in gone, True)
expect("fresh changed not in modules", "kaju_core.senses.relook" in sys.modules, False)
from kaju_core.senses import relook as relook2  # noqa: E402

expect("fresh reimports new", relook2 is not relook, True)
expect("fresh never loaded", kaju_core.fresh("nothing_here"), [])

# people：谁是谁
from kaju_core import people  # noqa: E402

os.environ["KAJU_DATA"] = tempfile.mkdtemp()
reg = people.registry()
expect("people empty owner", people.owner(), "")
expect("default key qq", reg.key("qq", "123"), "123")
expect("default key bili", reg.key("bili", "777"), "bili_777")
expect("fallback key", reg.key("douyin", "MS4w", fallback="douyin_42"), "douyin_42")
expect("split key", people.split_key("douyin_42"), ("douyin", "42"))
expect("label", [people.label("487"), people.label("bili_9"), people.label("douyin_8")], ["QQ 487", "B站 9", "抖音 8"])
reg.set_owner("111111111")
reg.link("111111111", "bili", "10000001")
reg.link("111111111", "douyin", "MS4wOWNER")
expect("owner", people.owner(), "111111111")
expect("owner bili", reg.key("bili", "10000001"), "111111111")
expect("owner account", reg.account("111111111", "douyin"), "MS4wOWNER")
expect("is owner", (reg.is_owner("bili", "10000001"), reg.is_owner("bili", "1")), (True, False))
expect("accounts", reg.accounts("111111111"), {"qq": "111111111", "bili": "10000001", "douyin": "MS4wOWNER"})
reg.link("555", "bili", "888", "群友")
expect("friend bili → qq", reg.key("bili", "888"), "555")
expect("linked", (reg.is_linked("bili", "888"), reg.is_linked("bili", "999")), (True, False))
said = reg.link("666", "bili", "888")
expect("relink moves", (reg.key("bili", "888"), "原来认在 555" in said), ("666", True))
expect("unlink", (reg.unlink("bili", "888") != "", reg.key("bili", "888")), (True, "bili_888"))
other = people.People(reg.path)  # 另一个插件里的那份：看文件时间重新读
reg.link("111111111", "bili", "30000")
expect("other instance sees change", other.key("bili", "30000"), "111111111")
expect("describe owner first", reg.describe()[0].startswith("111111111（兄长大人本人）"), True)
# 日记（kaju_life）：谁能看私聊的日记 = 身份表里的兄长；管理员 999999999 不是兄长
sys.path.insert(0, os.path.join(HERE, "stubs"))
from astrbot.api.star import Context  # noqa: E402
from kaju_astr import AstrBody  # noqa: E402
from kaju_core.life.diary import Diary  # noqa: E402


class _Ev:
    def __init__(self, sender, group=""):
        self.s, self.g = sender, group

    def get_sender_id(self):
        return self.s

    def get_group_id(self):
        return self.g


diary_cfg = {}
ctx = Context({"timezone": "Asia/Shanghai", "admins_id": ["111111111", "999999999"]})
d = Diary(AstrBody(ctx), lambda: diary_cfg, tempfile.mkdtemp(), lambda: None, lambda *_: "", lambda *_: None)
expect("diary owner from table", d._owner_ids(), {"111111111"})
expect("diary private: owner yes, admin no, group no",
       (d.can_see_private(_Ev("111111111")), d.can_see_private(_Ev("999999999")), d.can_see_private(_Ev("111111111", "1"))),
       (True, False, False))
diary_cfg["owner_ids"] = "1, 2"
expect("diary owner_ids config wins", d._owner_ids(), {"1", "2"})
# 最近几行（kaju_style 群聊前文用）：只要这个聊天的，今天不够往前一天补，按到达顺序
for day, rows in (("2026-11-08", [("g1", "a"), ("g1", "b"), ("g2", "x")]), ("2026-11-09", [("g1", "c"), ("p5", "y")])):
    with open(os.path.join(d._dir, "log", day + ".jsonl"), "w", encoding="utf-8") as f:
        for c, x in rows:
            f.write(json.dumps({"t": "10:00", "c": c, "u": "9", "n": "某人", "x": x}, ensure_ascii=False) + "\n")
expect("diary recent: across days", [r["x"] for r in d.recent("g1", 5)], ["a", "b", "c"])
expect("diary recent: last n", [r["x"] for r in d.recent("g1", 2)], ["b", "c"])
expect("diary recent: other chat / none", ([r["x"] for r in d.recent("p5", 3)], d.recent("g9", 3)), (["y"], []))


# 2026-11-13：主模型（Gemini 中转）答不上来 → AstrBody.generate / think 按 AstrBot 配置里的后备一个个试
import asyncio as _aio  # noqa: E402


class _Resp:
    def __init__(self, t, role="assistant"):
        self.completion_text, self.role = t, role


class _Prov:
    def __init__(self, pid):
        self.provider_config = {"id": pid}


fctx = Context({"agent_runner": {"config": {"model": {"provider_id": "gemini", "fallback_provider_ids": ["gemini_argon", "x"]}}}})
fctx.providers = {"gemini": _Prov("gemini"), "gemini_argon": _Prov("gemini_argon")}
calls = []


async def _llm(chat_provider_id, prompt, system_prompt=""):
    calls.append(chat_provider_id)
    if chat_provider_id == "gemini":
        raise RuntimeError("502 Upstream request failed")
    return _Resp("在的")

fctx.llm_generate = _llm
fb = AstrBody(fctx)
expect("fallback: main fails -> argon answers", _aio.run(fb.generate("gemini", "在吗", timeout=30)), "在的")
expect("fallback: order", calls, ["gemini", "gemini_argon"])
calls.clear()
expect("fallback: think default provider", _aio.run(fb.think("在吗")), "在的")
calls.clear()
expect("fallback: other provider no chain", fb._fallbacks("deepseek"), [])


async def _hang(chat_provider_id, prompt, system_prompt=""):
    calls.append(chat_provider_id)
    if chat_provider_id == "gemini":
        await _aio.sleep(30)
    return _Resp("后备")

fctx.llm_generate = _hang
expect("fallback: main hangs -> share of time then argon", _aio.run(fb.generate("gemini", "在吗", timeout=20)), "后备")

try:
    reg.link("1", "weibo", "2")
    expect("bad platform raises", False, True)
except ValueError:
    expect("bad platform raises", True, True)

print("全部通过" if not fails else f"{fails} 项没过")
sys.exit(1 if fails else 0)
