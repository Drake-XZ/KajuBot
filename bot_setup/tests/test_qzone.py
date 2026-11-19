"""Offline tests for qzone_post 1.1.0 (说说的点赞和评论) + kaju_heart.feel_outside.

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_qzone.py
"""

import asyncio
import importlib
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, PLUGINS)
sys.path.insert(0, os.path.dirname(os.path.abspath(PLUGINS)))  # 源码里的 kaju_core
DATA = tempfile.mkdtemp()
os.environ["STUB_DATA"] = DATA

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.provider import ProviderRequest  # noqa: E402
from astrbot.api.star import Context  # noqa: E402

ia = importlib.import_module("qzone_post.interact")
turn = importlib.import_module("qzone_post.turn")
qm = importlib.import_module("qzone_post.main")
hm = importlib.import_module("kaju_heart.main")

SELF, OWNER, A, B = "555555555", "111111111", "111", "222"
failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


# ------------------------------------------------------------------ pure
expect("clean emoji+mention", ia.clean("好看[em]e100[/em] @{uin:555555555,nick:佳树,who:1} 嗯"), "好看[表情] @佳树 嗯")
expect("brief", ia.brief("一二三四五六", 4), "一二三四…")
expect("new likers first time", ia.new_likers(None, [{"fuin": 1, "nick": "x"}, {"fuin": int(SELF)}], SELF),
       [{"uin": "1", "nick": "x"}])
expect("new likers diff", ia.new_likers(["1"], [{"fuin": 1, "nick": "x"}, {"fuin": 2, "nick": "y"}], SELF),
       [{"uin": "2", "nick": "y"}])
expect("join reply", ia.join_reply(["兄长大人看到啦～ &&开心&&", "佳树好开心哦\n嘿嘿"]), "兄长大人看到啦～ 佳树好开心哦 嘿嘿")
expect("join skip", ia.join_reply(["[SKIP]"]), "")

now = 1_800_000_000


def c(uin, cid, t, text, name=None, replies=None):
    return {"uin": int(uin), "name": name or f"n{uin}", "time": t, "content": text, "comment_id": cid,
            "replies": replies or []}


def r(uin, cid, t, text, parent, name=None):
    return {"uin": int(uin), "name": name or f"n{uin}", "time": t, "content": text, "comment_id": cid,
            "parent_comment_id": parent["comment_id"], "parent_comment_uin": parent["uin"]}


top1 = c(A, "1", now - 100, "好可爱")
detail = {"tid": "T", "comments": [top1]}
items, skip = ia.scan(detail, SELF, {}, now, 86400)
expect("top comment → item", [(x["uin"], x["texts"], x["is_reply"], x["comment_id"], x["comment_uin"]) for x in items],
       [(A, ["好可爱"], False, "1", A)])
expect("top comment keys", items[0]["keys"], ["T/1"])
expect("thread lines", items[0]["thread"], [f"n{A}：好可爱"])
items, skip = ia.scan(detail, SELF, {}, now, 0)
expect("first run (max_age 0) → skipped", (items, skip), ([], ["T/1"]))
items, skip = ia.scan(detail, SELF, {"T/1": now}, now, 86400)
expect("seen → nothing", (items, skip), ([], []))

# 她回过之后：楼主接着回她 → 要回；别人插一句没提她、她也没在那之前说过 → 不回
top2 = c(A, "2", now - 300, "今天好吗")
top2["replies"] = [r(SELF, "a", now - 200, "好呀", top2), r(A, "b", now - 100, "那就好", top2),
                   r(B, "c", now - 50, "我也来", top2)]
items, skip = ia.scan({"tid": "T", "comments": [top2]}, SELF, {"T/2": now}, now, 86400)
expect("thread: owner reply + other after her",
       [(x["uin"], x["texts"], x["is_reply"], x["reply_to"]) for x in items],
       [(A, ["那就好"], True, None), (B, ["我也来"], True, {"uin": B, "name": f"n{B}"})])
expect("her own lines in thread", items[0]["thread"][1], "你：好呀")

# 别人在别人的楼里说话、她没参与、没提她 → 不回
top3 = c(A, "3", now - 300, "哈哈")
top3["replies"] = [r(B, "x", now - 100, "笑死", top3)]
items, skip = ia.scan({"tid": "T", "comments": [top3]}, SELF, {"T/3": now}, now, 86400)
expect("not to her → skip", (items, skip), ([], ["T/3/x"]))
top3["replies"] = [r(B, "y", now - 100, "佳树怎么看", top3)]
items, _ = ia.scan({"tid": "T", "comments": [top3]}, SELF, {"T/3": now}, now, 86400)
expect("mentions 佳树 → item", [x["texts"] for x in items], [["佳树怎么看"]])

# 已经回过了（她的话在后面）→ 不回；同一人连着两句 → 并成一条
top4 = c(A, "4", now - 300, "在吗")
top4["replies"] = [r(SELF, "z", now - 100, "在哦", top4)]
items, skip = ia.scan({"tid": "T", "comments": [top4]}, SELF, {}, now, 86400)
expect("already answered", (items, skip), ([], ["T/4"]))
top5 = c(A, "5", now - 300, "在吗")
top5["replies"] = [r(A, "q", now - 200, "想你了", top5)]
items, _ = ia.scan({"tid": "T", "comments": [top5]}, SELF, {}, now, 86400)
expect("merge same person", (len(items), items[0]["texts"], items[0]["keys"]), (1, ["在吗", "想你了"], ["T/5", "T/5/q"]))
expect("message text", ia.message_text(items[0], "今天读完《妹妹人生》上下两卷，心里沉了好一阵"),
       "【QQ空间】在你的说说「今天读完《妹妹人生》上下两卷，心里沉了好一阵」下评论：在吗\n想你了")


# ------------------------------------------------------------------ turn.run
class FakePlatform:
    def __init__(self): self.committed = []
    def commit_event(self, e): self.committed.append(e)
    def meta(self): return type("M", (), {"id": "qq_555555555"})()


async def turn_tests():
    clock = [1000.0]
    orig = time.time
    time.time = lambda: clock[0]
    try:
        async def tick(_):
            clock[0] += 1

        ev = AstrMessageEvent(sender=A)
        ev.collected, ev.last_send = [], 0.0
        pf = FakePlatform()

        async def scenario():
            ev.set_extra(turn.DONE_KEY, None)
            task = asyncio.create_task(turn.run(pf, ev, timeout=60, sleep=tick))
            await asyncio.sleep(0)
            return task

        # agent 结束后 6 秒没新句子 → ok
        ev.set_extra(turn.DONE_KEY, {"t": 1002.0, "err": False})
        ev.collected = ["好呀"]
        ev.last_send = 1004.0
        status, parts = await turn.run(pf, ev, timeout=60, sleep=tick)
        expect("turn ok", (status, parts, pf.committed == [ev]), ("ok", ["好呀"], True))
        expect("turn waited settle", clock[0] >= 1010.0, True)
        ev.set_extra(turn.DONE_KEY, {"t": clock[0], "err": True})
        status, _ = await turn.run(pf, ev, timeout=60, sleep=tick)
        expect("turn err", status, "err")
        ev.set_extra(turn.DONE_KEY, None)
        status, _ = await turn.run(pf, ev, timeout=5, sleep=tick)
        expect("turn timeout", status, "timeout")
        del scenario
    finally:
        time.time = orig


# ------------------------------------------------------------------ flow
class FakeBot:
    def __init__(self):
        self.posts = []
        self.details = {}
        self.calls = []

    async def call_action(self, action, **p):
        self.calls.append((action, p))
        if action == "get_cookies":
            return {"cookies": "uin=o555555555; p_skey=abc"}
        if action == "get_qzone_msg_list":
            return {"total": len(self.posts), "msglist": self.posts}
        if action == "get_qzone_msg_detail":
            return self.details[p["tid"]]
        if action == "comment_qzone":
            return {"comment_id": "new"}
        raise AssertionError(action)


class FakeHeart:
    def __init__(self): self.calls = []

    async def feel_outside(self, qq, name, **kw):
        self.calls.append((qq, name, kw["affection"], kw["umo"]))
        return kw["affection"]


async def flow_tests():
    ctx = Context()
    bot, pf, heart = FakeBot(), FakePlatform(), FakeHeart()
    ctx.get_platform = lambda name: pf
    pf.get_client = lambda: bot
    ctx.stars = [type("Meta", (), {"star_cls": heart, "name": "astrbot_plugin_kaju_heart"})()]
    plugin = qm.QzonePost(ctx, {})
    likes = {"T1": [{"fuin": int(OWNER), "nick": "晴川"}], "T2": []}

    async def likers(cookies, uin, g_tk, tid):
        return likes[tid]

    plugin._likers = likers
    t0 = time.time()
    bot.posts = [{"tid": "T1", "content": "今天被兄长大人夸了", "time": int(t0 - 3600), "comment_num": 1},
                 {"tid": "T2", "content": "很久以前", "time": int(t0 - 30 * 86400), "comment_num": 0}]
    old = c(A, "1", int(t0 - 1000), "旧评论")
    bot.details["T1"] = {"tid": "T1", "content": "今天被兄长大人夸了", "comment_num": 1, "comments": [old]}

    runs = []
    answers = {"next": ("ok", ["学长好呀～", "佳树也很开心哦 &&开心&&"])}

    def make_event(platform, b, self_uin, uin, name, text, extra):
        ev = AstrMessageEvent(sender=uin, name=name, text=text)
        ev.set_extra(turn.QZ_KEY, extra)
        runs.append((self_uin, uin, name, text, extra))
        return ev

    async def run(platform, ev, timeout, settle=6.0, sleep=None):
        return answers["next"]

    qm.turn.make_event, qm.turn.run = make_event, run

    # 第一次：已有的赞和评论只记下
    stats = await plugin.check_interactions()
    expect("first: nothing new", (stats, heart.calls, runs), ({"likes": 0, "comments": 0, "replied": 0}, [], []))
    expect("first: likes recorded", plugin._istate["likes"], {"T1": [OWNER]})
    expect("first: comment seen", list(plugin._istate["seen"]), ["T1/1"])
    expect("first: T2 out of window not fetched", any(p.get("tid") == "T2" for a, p in bot.calls if a == "get_qzone_msg_detail"), False)

    # 第二次：A 点赞 + 新评论
    likes["T1"].append({"fuin": int(A), "nick": "小A"})
    new = c(A, "2", int(time.time() - 60), "好棒呀", name="小A")
    bot.details["T1"]["comments"].append(new)
    stats = await plugin.check_interactions()
    expect("second: stats", stats, {"likes": 1, "comments": 1, "replied": 1})
    expect("second: heart", heart.calls, [(A, "小A", 1.0, "qq_555555555:FriendMessage:" + A)])
    expect("second: turn text", runs[0][3], "【QQ空间】在你的说说「今天被兄长大人夸了」下评论：好棒呀")
    expect("second: turn extra thread", runs[0][4]["thread"], ["小A：好棒呀"])
    sent = [p for a, p in bot.calls if a == "comment_qzone"]
    expect("second: comment_qzone params", sent,
           [{"tid": "T1", "content": "学长好呀～ 佳树也很开心哦", "comment_id": "2", "comment_uin": int(A)}])
    expect("second: recent", [(x["kind"], x["uin"], x.get("her")) for x in plugin._istate["recent"]],
           [("like", A, None), ("comment", A, "学长好呀～ 佳树也很开心哦")])

    # 第三次：没有新东西，不重复
    bot.details["T1"]["comments"][-1]["replies"] = [r(SELF, "m", int(time.time()), "学长好呀～ 佳树也很开心哦", new)]
    stats = await plugin.check_interactions()
    expect("third: no repeat", (stats, len(heart.calls), len(runs)), ({"likes": 0, "comments": 0, "replied": 0}, 1, 1))

    # 出错：不发，下次再试，两次后放弃
    answers["next"] = ("err", ["唔…佳树刚才走神了"])
    bot.details["T1"]["comments"].append(c(B, "3", int(time.time() - 30), "你好", name="小B"))
    await plugin.check_interactions()
    expect("err: not sent", len([1 for a, _ in bot.calls if a == "comment_qzone"]), 1)
    expect("err: tries", plugin._istate["tries"], {"T1/3": 1})
    await plugin.check_interactions()
    expect("err: give up after 2", ("T1/3" in plugin._istate["seen"], plugin._istate["tries"]), (True, {}))
    expect("err: ran twice", len(runs), 3)

    # [SKIP]：不发，但算处理过
    answers["next"] = ("ok", ["[SKIP]"])
    bot.details["T1"]["comments"].append(c(B, "4", int(time.time() - 20), "路过", name="小B"))
    await plugin.check_interactions()
    expect("skip: not sent, seen", (len([1 for a, _ in bot.calls if a == "comment_qzone"]), "T1/4" in plugin._istate["seen"]),
           (1, True))

    # 楼中楼别人回她 → @ 回这个人
    answers["next"] = ("ok", ["小B学长说得对"])
    top = bot.details["T1"]["comments"][1]
    top["replies"].append(r(B, "k", int(time.time() + 5), "我也觉得", top, name="小B"))
    await plugin.check_interactions()
    last = [p for a, p in bot.calls if a == "comment_qzone"][-1]
    expect("reply in thread → reply_to", (last["comment_id"], last["comment_uin"], last.get("reply_uin"), last.get("reply_name")),
           ("2", int(A), int(B), "小B"))

    # 点赞提示：跟 A 聊天时提一次
    ev = AstrMessageEvent(sender=A, name="小A")
    req = ProviderRequest()
    await plugin.inject(ev, req)
    expect("like notice shown", "对方最近给你的说说点了赞：「今天被兄长大人夸了」" in req.system_prompt, True)
    expect("post style allows related events and feelings", ("长短按内容" in req.system_prompt,
           "相关的事" in req.system_prompt, "不要贴别人的聊天原话或隐私" in req.system_prompt), (True, True, True))
    req = ProviderRequest()
    await plugin.inject(ev, req)
    expect("like notice once", "对方最近给你的说说点了赞" in req.system_prompt, False)
    req = ProviderRequest()
    await plugin.inject(AstrMessageEvent(sender=B), req)
    expect("like notice not for others", "对方最近给你的说说点了赞" in req.system_prompt, False)

    # 评论那一轮：只给评论区的规矩，post_qzone 拒绝
    ev = AstrMessageEvent(sender=A, name="小A")
    ev.set_extra(turn.QZ_KEY, {"name": "小A", "post": "今天被兄长大人夸了", "thread": ["小A：好棒呀"]})
    req = ProviderRequest()
    await plugin.inject(ev, req)
    expect("comment note", ("【QQ空间评论】" in req.system_prompt, "  小A：好棒呀" in req.system_prompt,
                            "post_qzone 工具发说说" in req.system_prompt), (True, True, False))
    expect("post refused in comment turn", (await plugin.post_qzone(ev, "x", True)).startswith("没发：现在是在回评论区"), True)
    await plugin.mark_done(ev, None, type("R", (), {"role": "assistant"})())
    expect("mark_done", ev.get_extra(turn.DONE_KEY)["err"], False)

    # 工具：看最近的点赞和评论
    out = await plugin.qzone_activity(AstrMessageEvent(), 3)
    expect("activity", ("小A 赞了「今天被兄长大人夸了」" in out, "→ 你回：学长好呀～ 佳树也很开心哦" in out), (True, True))

    # 状态存盘后重载一致
    plugin2 = qm.QzonePost(ctx, {})
    expect("state persisted", plugin2._istate["seen"].keys() == plugin._istate["seen"].keys(), True)

    # 关掉回评论：只记下
    plugin.config = {"interact": {"reply_comments": False}}
    n = len(runs)
    bot.details["T1"]["comments"].append(c(B, "5", int(time.time() - 5), "嗨", name="小B"))
    await plugin.check_interactions()
    expect("reply off", (len(runs), "T1/5" in plugin._istate["seen"]), (n, True))


async def cookie_tests():
    """1.2.1：cookie 留着用；-3000 重拿一次再试；重拿的也不认就停读这一轮；失败只报一行；外面出错隔久一点。"""
    ctx = Context()
    bot, pf = FakeBot(), FakePlatform()
    ctx.get_platform = lambda name: pf
    pf.get_client = lambda: bot
    ctx.stars = []
    plugin = qm.QzonePost(ctx, {})
    t0 = time.time()
    bot.posts = [{"tid": f"T{i}", "content": f"说说{i}", "time": int(t0 - 3600), "comment_num": 0} for i in range(4)]
    seen = []
    mode = {"bad": set()}  # 哪些 cookie 会被说没登录

    async def likers(cookies, uin, g_tk, tid):
        seen.append((cookies, tid))
        if cookies in mode["bad"]:
            raise qm.NotLoggedIn("like list code=-3000 对不起，您还没有登录!")
        return []

    plugin._likers = likers
    n_ck = lambda: sum(1 for a, _ in bot.calls if a == "get_cookies")  # noqa: E731

    await plugin.check_interactions()
    await plugin.check_interactions()
    expect("cookie cached across rounds", n_ck(), 1)
    expect("all likes read", len(seen), 8)

    # 旧 cookie 不认了：重拿一次，同一条再试，后面都用新的
    old = plugin._ck[0]
    mode["bad"] = {old}
    bot.call_action_orig = bot.call_action

    async def call_action(action, **p):
        if action == "get_cookies":
            bot.calls.append((action, p))
            return {"cookies": "uin=o555555555; p_skey=new"}
        return await bot.call_action_orig(action, **p)

    bot.call_action = call_action
    seen.clear()
    await plugin.check_interactions()
    expect("refresh once on -3000", n_ck(), 2)
    expect("retry same post then new cookie", [c_ for c_, _ in seen], [old, "uin=o555555555; p_skey=new"] + ["uin=o555555555; p_skey=new"] * 3)

    # 新的也不认：这一轮停读，只报一行，cookie 丢掉下次重拿
    mode["bad"] = {"uin=o555555555; p_skey=new"}
    seen.clear()
    logged = []
    orig_warn = qm.logger.warning
    qm.logger.warning = lambda msg, *a, **k: logged.append(msg)
    try:
        await plugin.check_interactions()
    finally:
        qm.logger.warning = orig_warn
    expect("stop after refreshed cookie also rejected", len(seen), 2)
    expect("one summary line", [m for m in logged if "读点赞失败" in m and "剩下的这轮先不读" in m].__len__(), 1)
    expect("cookie dropped", plugin._ck, None)

    # 拿 cookie 失败但有旧的：先用旧的
    plugin._ck = ("uin=o555555555; p_skey=cached", SELF, 1, 0.0)  # 早就过期

    async def broken(action, **p):
        if action == "get_cookies":
            raise RuntimeError("boom")
        return await bot.call_action_orig(action, **p)

    bot.call_action = broken
    expect("fallback to stale cookie", (await plugin._cookies(bot))[0], "uin=o555555555; p_skey=cached")
    expect("_why empty exc", qm._why(asyncio.TimeoutError()), "TimeoutError")


async def heart_tests():
    ctx = Context()
    h = hm.KajuHeart(ctx, {})
    a0 = h.affection(A)
    d = await h.feel_outside(A, "小A", affection=1, emotion="开心", intensity=1, cause="小A给你的说说点了赞",
                             reason="给说说点赞", umo="qq:FriendMessage:" + A)
    expect("heart: affection up", (d > 0, round(h.affection(A) - a0, 2) == d), (True, True))
    expect("heart: event recorded", h._state["events"][-1]["cause"], "小A给你的说说点了赞")
    for _ in range(10):
        await h.feel_outside(A, "小A", affection=3, emotion="开心", intensity=1, cause="赞", reason="赞")
    expect("heart: daily cap", h.affection(A) - a0 <= 6.01, True)
    note = h.build_note(A, "小A", "qq:FriendMessage:" + A)
    expect("heart: note mentions like", "：赞，你有点开心" in note, True)


asyncio.run(turn_tests())
asyncio.run(flow_tests())
asyncio.run(cookie_tests())
asyncio.run(heart_tests())
print("FAILURES:", len(failures)) if failures else print("all qzone tests passed")
sys.exit(1 if failures else 0)
