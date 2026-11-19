"""用真模型（deepseek-flash）把每晚的说说流程在过去几天的真实素材上走一遍，只打印，绝不发布。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\try_nightly_live.py [2026-11-05 ...]

只读机器人的数据：先把要用的几个文件复制到临时目录，插件读的是副本。发布函数换成直接报错的假函数。
不带日期 = 最近 4 天。每一天按当天 22:30 算（只用到那时为止的素材）。
"""

import asyncio
import datetime as dt
import importlib
import json
import os
import shutil
import sys
import tempfile
import zoneinfo

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins"))
sys.path.insert(0, os.path.dirname(HERE))  # 源码里的 kaju_core
CORE = r"C:\Users\18525\.astrbot_launcher\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
PD = os.path.join(CORE, "data", "plugin_data")
TMP = tempfile.mkdtemp(prefix="nightly_live_")
os.environ["STUB_DATA"] = TMP

for rel in ["astrbot_plugin_kaju_life/log", "astrbot_plugin_kaju_life/names.json", "astrbot_plugin_kaju_life/days.json",
            "astrbot_plugin_address_book/addresses.json", "astrbot_plugin_kaju_basics/browse.json",
            "astrbot_plugin_kaju_heart/state.json", "astrbot_plugin_qzone_post/posts.json"]:
    src, dst = os.path.join(PD, rel), os.path.join(TMP, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(src):
        shutil.copytree(src, dst)
    elif os.path.exists(src):
        shutil.copy2(src, dst)

from openai import AsyncOpenAI  # noqa: E402

from astrbot.api.star import Context  # noqa: E402

qm = importlib.import_module("qzone_post.main")
TZ = zoneinfo.ZoneInfo("Asia/Shanghai")

cfg = json.load(open(os.path.join(CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
key = src.get("key")
ds = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"], timeout=90)


async def llm_generate(chat_provider_id=None, prompt="", system_prompt=""):
    r = await ds.chat.completions.create(model="deepseek-flash", messages=[
        {"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}])
    return type("Resp", (), {"completion_text": r.choices[0].message.content or ""})()


class Prov:
    provider_config = {"id": "deepseek"}


async def no_publish(*a, **k):
    raise AssertionError("试跑不发布")


async def main(days):
    with open(os.path.join(TMP, "astrbot_plugin_qzone_post", "posts.json"), encoding="utf-8") as f:
        all_posts = json.load(f)
    for day in days:
        ctx = Context()
        ctx.providers = {"deepseek": Prov()}
        ctx.llm_generate = llm_generate
        p = qm.QzonePost(ctx, {"nightly": {"timeout_seconds": 120}})
        p._publish = no_publish
        d = dt.date.fromisoformat(day)
        now = dt.datetime(d.year, d.month, d.day, 22, 29, tzinfo=TZ).timestamp()
        p._posts = [x for x in all_posts if x["time"] < now]
        old = [x["content"] for x in all_posts if now <= x["time"] < now + 3 * 3600]
        run = await p.run_nightly(publish=False, now=now)
        print(f"\n==================== {day}（素材 {run.get('material', 0)} 条）")
        if old:
            print("当晚旧流程发的：" + " / ".join(old))
        plan = run.get("plan") or {}
        if plan:
            print("选材：" + ("发" if plan["post"] else "不发") + f"（{plan['reason']}）话题：{'、'.join(plan['topics'])}")
            for f in plan["facts"]:
                print(f"  - {f['say']}  ← {f['src']}")
            print(f"  感受：{plan['feel']}")
            if plan.get("avoid"):
                print(f"  避开：{'；'.join(plan['avoid'])}")
        for i, a in enumerate(run.get("attempts") or [], 1):
            print(f"第{i}稿：{a['text']}")
            print(f"  检查：{'通过' if not a['problems'] else '；'.join(a['problems'])}")
        print(f"结果：{run['status']} {run.get('reason', '')}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        today = dt.datetime.now(TZ).date()
        args = [(today - dt.timedelta(days=i)).isoformat() for i in range(4, 0, -1)]
    try:
        asyncio.run(main(args))
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
