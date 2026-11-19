"""kaju_life 1.1.0 关于自己（selffacts.py）：按对方的话想起最相关的几条。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_selffacts.py [--live]
--live 再用本机 Ollama 的 bge-m3 真算一遍，打印几句话各想起了什么（只读，不改机器人的数据）。
"""

import asyncio
import json
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins"))
sys.path.insert(0, os.path.dirname(HERE))  # 源码里的 kaju_core
os.environ.setdefault("STUB_DATA", tempfile.mkdtemp())

import importlib  # noqa: E402

sf = importlib.import_module("kaju_core.life.selffacts")
failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


VOCAB = ["做饭", "点心", "兄长", "学生会", "盆栽", "小说"]


def fake_vec(text):
    return [float(text.count(w)) + 0.01 for w in VOCAB]


async def fake_embed(texts):
    fake_embed.calls.append(list(texts))
    return [fake_vec(t) for t in texts]


async def unit():
    d = tempfile.mkdtemp()
    facts = [{"fact": "佳树擅长做饭，尤其是和食。"}, {"fact": "佳树是学生会副会长。"},
             {"fact": "佳树会做点心，点心能卖。"}, {"fact": "佳树在养盆栽。"}]
    with open(os.path.join(d, "self_facts.json"), "w", encoding="utf-8") as f:
        json.dump(facts, f, ensure_ascii=False)
    s = sf.SelfFacts(d, lambda: {"top_k": 2})
    fake_embed.calls = []
    s._embed = fake_embed
    note, picked, _ = await s.note_for("今天学生会开会好累")
    expect("top1 学生会", picked[0], "佳树是学生会副会长。")
    expect("top_k 2", len(picked), 2)
    expect("render head", note.startswith(sf.HEAD), True)
    expect("embedded facts once + query", [len(c) for c in fake_embed.calls], [4, 1])
    await s.note_for("想吃点心")
    expect("vectors cached", [len(c) for c in fake_embed.calls], [4, 1, 1])
    expect("cache file", os.path.exists(os.path.join(d, "self_facts.vec.json")), True)
    # 改文件：只给新句子算向量，删掉的句子的向量清掉
    time.sleep(0.05)
    facts[3] = {"fact": "佳树在读小说。"}
    with open(os.path.join(d, "self_facts.json"), "w", encoding="utf-8") as f:
        json.dump(facts, f, ensure_ascii=False)
    os.utime(os.path.join(d, "self_facts.json"), (time.time() + 5, time.time() + 5))
    note, picked, _ = await s.note_for("最近在看什么小说")
    expect("reload picks new fact", picked[0], "佳树在读小说。")
    expect("only new fact embedded", fake_embed.calls[-2], ["佳树在读小说。"])
    expect("old vec dropped", len(s.vecs), 4)
    # 关掉 / 空消息 / 出错
    expect("empty query", (await s.note_for("  "))[0], "")
    s2 = sf.SelfFacts(d, lambda: {"enable": False})
    s2._embed = fake_embed
    expect("disabled", (await s2.note_for("学生会"))[0], "")

    async def boom(texts):
        raise TimeoutError("ollama 没开")
    s3 = sf.SelfFacts(tempfile.mkdtemp(), lambda: {})
    expect("seed copied when missing", len(s3.facts) == 0 and os.path.exists(s3.path), True)
    s3._embed = boom
    try:
        await s3.note_for("学生会")
        raised = False
    except TimeoutError:
        raised = True
    expect("embed error propagates to caller (main.py catches)", raised, True)


async def plugin_hook():
    """main.py 的钩子：出错不影响，正常时加到系统提示末尾。"""
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.provider import ProviderRequest
    from astrbot.api.star import Context
    lm = importlib.import_module("kaju_life.main")
    life = lm.KajuLife(Context(), {})
    life._loop_task.cancel()

    async def note_for(q):
        return sf.render(["佳树是学生会副会长。"]), ["佳树是学生会副会长。"], 0.01
    life.selffacts.note_for = note_for
    req = ProviderRequest(prompt="x", system_prompt="原来的")
    await life.inject_self_facts(AstrMessageEvent(text="学生会好忙"), req)
    expect("hook appends", req.system_prompt.startswith("原来的") and "学生会副会长" in req.system_prompt, True)

    async def boom(q):
        raise ConnectionError("down")
    life.selffacts.note_for = boom
    req = ProviderRequest(prompt="x", system_prompt="原来的")
    await life.inject_self_facts(AstrMessageEvent(text="学生会好忙"), req)
    expect("hook survives error", req.system_prompt, "原来的")


async def live():
    d = tempfile.mkdtemp()
    s = sf.SelfFacts(d, lambda: {})  # 从 seed 复制 64 条
    for q in ["兄长大人：今晚吃什么好呢", "女王大人：佳树会做蛋糕吗", "兄长大人：最近学校怎么样",
              "哆啦a梦学姐：佳树喜欢看什么书", "兄长大人：你是谁呀"]:
        _, picked, secs = await s.note_for(q)
        print(f"\n{q}  （{secs:.2f}s）")
        for p in picked:
            print("   -", p)


asyncio.run(unit())
asyncio.run(plugin_hook())
if "--live" in sys.argv:
    asyncio.run(live())
print("FAILURES:", len(failures)) if failures else print("all selffacts tests passed")
sys.exit(1 if failures else 0)
