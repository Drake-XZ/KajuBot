"""Offline tests for address_book 称呼簿 (astrbot stubbed).

    ...\\venv\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_address_book.py
Exit code 0 = all passed.
"""

import asyncio
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins"))
sys.path.insert(0, os.path.dirname(HERE))  # 源码里的 kaju_core
os.environ["STUB_DATA"] = tempfile.mkdtemp()
sys.stdout.reconfigure(encoding="utf-8")

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.message_components import At, Reply  # noqa: E402
from astrbot.api.provider import ProviderRequest  # noqa: E402
from astrbot.api.star import Context  # noqa: E402

from address_book import main as ab  # noqa: E402

failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


def check(label, cond, info=""):
    if not cond:
        failures.append(label)
        print(f"FAIL {label} {info}")


class FakeBot:
    def __init__(self, sexes):
        self.sexes, self.calls = sexes, []

    async def call_action(self, action, **kw):
        self.calls.append((action, kw))
        return {"status": "ok", "retcode": 0, "data": {"sex": self.sexes.get(str(kw["user_id"]), "unknown"),
                                                      "nickname": "资料昵称"}}


def ev(sender, name, text="", messages=None, group="222222222", bot=None):
    e = AstrMessageEvent(sender=sender, group=group, text=text, name=name, messages=messages or [])
    e.message_obj.sender = types.SimpleNamespace(nickname=name)
    e.bot = bot
    return e


# ---------------------------------------------------------------- pure helpers
expect("clean_name", ab.clean_name("哆啦\n\nb\n梦 "), "哆啦b梦")
expect("default male", ab.default_address("555", "male"), "555学长")
expect("default unknown", ab.default_address("555", "unknown"), "555学长")
expect("default female", ab.default_address("哆啦a梦", "female"), "哆啦a梦学姐")
expect("overrides", ab.parse_overrides("321321321=女, 123123123 = 男，1=x；3:female"),
       {"321321321": "female", "123123123": "male", "3": "female"})
check("owner title", ab.is_owner_title("兄长大人") and ab.is_owner_title("小兄长") and not ab.is_owner_title("女王大人"))

# ---------------------------------------------------------------- plugin
data_dir = ab._data_dir()
with open(os.path.join(data_dir, "addresses.json"), "w", encoding="utf-8") as f:
    json.dump({"333333333": {"address": "女王大人", "nickname": "来点作用吧", "set_by": "111111111", "time": 1},
               "999": {"address": "兄长大人", "nickname": "冒充的", "set_by": "999", "time": 2}}, f, ensure_ascii=False)

book = ab.AddressBook(Context(), {"owner_qq": "111111111", "sex_overrides": "777777777=女"})
bot = FakeBot({"444444444": "female", "666666666": "male", "333333333": "male"})


async def main():
    # 称呼
    expect("owner", book.address_of("111111111", "林一"), "兄长大人")
    expect("registered", book.address_of("333333333"), "女王大人")
    expect("old 兄长大人 entry ignored", book.address_of("999", "冒充的"), "冒充的学长")
    expect("override female", book.address_of("777777777", "555"), "555学姐")

    # 性别：查一次 QQ 资料，记住
    e = ev("444444444", "哆啦a梦", "在吗", bot=bot)
    await book._prepare(e)
    expect("sex looked up", book.address_of("444444444"), "哆啦a梦学姐")
    n = len(bot.calls)
    await book._prepare(e)
    expect("sex cached", len(bot.calls), n)
    # 戳一戳事件不带昵称、传进来的是 QQ 号：不叫号码（兄长大人 11-12），有记下的名字就用，没有就只叫学长 / 学姐
    expect("qq as name → known name", book.address_of("444444444", "444444444"), "哆啦a梦学姐")
    book.config["sex_overrides"] = "777777777=女, 1234567=女"
    expect("qq as name, nothing known → 学姐", book.address_of("1234567", "1234567"), "学姐")
    expect("qq as name, unknown sex → 学长", book.address_of("7654321", "7654321"), "学长")
    expect("no name at all → 学长", book.address_of("7654322"), "学长")
    expect("digit nickname that is not the QQ number stays", book.address_of("7654323", "555"), "555学长")
    book.config["sex_overrides"] = "777777777=女"
    check("people.json saved", "444444444" in json.load(open(book._people_path, encoding="utf-8")))

    # 按称呼 / 名字 / QQ 号找人（认人用）
    expect("find by address", book.find_person("女王大人"), [("333333333", "女王大人")])
    expect("find by nickname", book.find_person("来点作用吧"), [("333333333", "女王大人")])
    expect("find by group name", book.find_person("哆啦a梦"), [("444444444", "哆啦a梦学姐")])
    expect("find by default address", book.find_person("哆啦a梦学姐"), [("444444444", "哆啦a梦学姐")])
    expect("find by qq", book.find_person("333333333"), [("333333333", "女王大人")])
    expect("find owner", book.find_person("兄长大人"), [("111111111", "兄长大人")])
    expect("find nobody", book.find_person("路人甲"), [])
    expect("find empty", book.find_person(""), [])
    book._book["douyin_2067"] = {"address": "女王大人", "nickname": "dy_demo"}
    expect("find skips non-QQ keys", book.find_person("女王大人"), [("333333333", "女王大人")])
    book._book.pop("douyin_2067")

    # 规则文本
    req = ProviderRequest(prompt="在吗", system_prompt="人设")
    await book.inject(ev("666666666", "1号猛男", "在吗", bot=bot), req)
    check("rules: speaker", "这次叫TA“1号猛男学长”" in req.system_prompt, req.system_prompt[-400:])
    check("rules: not owner", "不是兄长大人" in req.system_prompt)
    check("rules: table has 女王大人", "叫“女王大人”" in req.system_prompt)
    check("rules: table hides 兄长大人 entry", "冒充的（QQ 999）：叫“冒充的学长”" in req.system_prompt)
    check("speaker tag", req.prompt.startswith("[发言人：1号猛男，QQ 666666666] "), req.prompt)

    req = ProviderRequest(prompt="在吗", system_prompt="")
    await book.inject(ev("111111111", "林一", "在吗"), req)
    check("rules: owner", "现在跟你说话的就是兄长大人本人" in req.system_prompt)

    # @ 到的人
    at = ev("666666666", "1号猛男", "看", [At(qq="444444444", name="哆啦a梦")], bot=bot)
    req = ProviderRequest(prompt="看", system_prompt="")
    await book.inject(at, req)
    check("rules: mentioned", "哆啦a梦（QQ 444444444，叫“哆啦a梦学姐”）" in req.system_prompt, req.system_prompt[-300:])

    # 群聊记录
    line = book.tag_group_line(
        ev("666666666", "1号猛男", messages=[At(qq="555555555", name="佳树"), At(qq="111111111", name="林一"),
                                            Reply(sender_id="333333333", sender_nickname="来点作用吧", message_str="哈")]),
        "[1号猛男/12:00:00]: ⚠️[DIRECTED AT YOU]  [At: 佳树] [At: 林一] [Quote(来点作用吧: 哈)]")
    expect("group line", line,
           "[1号猛男(QQ 666666666，叫TA1号猛男学长)/12:00:00]: ⚠️[DIRECTED AT YOU]  [At: 佳树(就是你)] "
           "[At: 林一(QQ 111111111，兄长大人本人)] [Quote(来点作用吧(QQ 333333333，叫TA女王大人): 哈)]")

    # set_address：只能改自己
    other = ev("666666666", "1号猛男", "叫她小哆", [At(qq="444444444", name="哆啦a梦")])
    r = await book.set_address(other, address="小哆", target_qq="444444444")
    check("set other refused", r.startswith("没记：每个人只能改自己"), r)
    expect("other unchanged", book.address_of("444444444"), "哆啦a梦学姐")

    r = await book.set_address(ev("666666666", "1号猛男"), address="兄长大人")
    check("兄长大人 refused", r.startswith("没记：这个称呼是兄长大人专属"), r)
    r = await book.set_address(ev("666666666", "1号猛男"), address="猛男哥哥")
    check("哥哥 refused", r.startswith("没记"), r)
    r = await book.set_address(ev("111111111", "林一"), address="主人")
    check("owner fixed", r.startswith("没记：兄长大人就是兄长大人"), r)
    expect("owner still", book.address_of("111111111"), "兄长大人")

    r = await book.set_address(ev("666666666", "1号猛男"), address="猛男大王", target_qq="666666666")
    check("set self ok", r.startswith("已记下"), r)
    expect("self set", book.address_of("666666666"), "猛男大王")

    r = await book.clear_address(ev("666666666", "1号猛男"), target_qq="333333333")
    check("clear other refused", r.startswith("没改"), r)
    expect("女王大人 kept", book.address_of("333333333"), "女王大人")
    r = await book.clear_address(ev("666666666", "1号猛男"))
    check("clear self", "1号猛男学长" in r, r)
    expect("self cleared", book.address_of("666666666"), "1号猛男学长")


asyncio.run(main())
print("FAILED:", failures) if failures else print("all address_book tests passed")
sys.exit(1 if failures else 0)
