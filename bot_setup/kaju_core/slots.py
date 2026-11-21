"""每项工作一格模型（2026-11-18 兄长：“我们可不可以也参考他们的结构……每项工作都调用 api，而不是全押给主脑做”→“先做第一步”；AGENT.md 第十节）。

照 MaiBot 的 model_task_config：每格填一串 AstrBot 的模型 id（provider id），从前往后试；格子空着 = 用主模型（和原来一样）。
表在 kaju_data\\accounts\\model_slots.json：{"slots": {"utils": ["gemini_bbapi15", ...], ...}}，改了下一次调用就读到。
谁用哪格（插件自己的 provider_id 填了就还是用它，空着才看格子）：
  planner  规划（大脑）+ 调工具 —— 现在就是 AstrBot 主模型本身，这一格先只记着，不接管
  utils    心情变化（kaju_heart）、刷 B站挑视频（browsing）这类小的分析活
  memory   长期记忆的总结、抽取、写回（memorix 是别人的插件，用它自己的 chat_provider_id；这一格先只记着）
  learner  知识本消化（kaju_learn），以后的“表达方式学习”；空着用 utils
  fast     要马上出结果的小活：问句把关（asks）、读书核对（kaju_learn reading check）；空着用 utils
  emoji    挑表情包（第二步再接）
回复器（kaju_style rewrite.replyer_models）、看图看视频（gemini_keys / model_router）、核对（guard_provider_id）、
语音转文字、向量（本机）本来就各管各的，不在这张表里。
"""

from __future__ import annotations

import json
import os

FILE = "model_slots.json"
FALLBACK = {"learner": "utils", "fast": "utils"}  # 跟 MaiBot 一样：空着回退到 utils
SLOTS = ("planner", "utils", "memory", "learner", "fast", "emoji")
_cache: tuple[float, dict] = (0.0, {})


def _path() -> str:
    from kaju_core import paths
    return paths.account(FILE)


def table(path: str = "") -> dict:
    global _cache
    try:
        p = path or _path()
        mt = os.path.getmtime(p)
    except Exception:  # noqa: BLE001  （没有这个文件 = 全都用主模型）
        return {}
    if mt != _cache[0]:
        try:
            with open(p, encoding="utf-8-sig") as f:
                d = json.load(f)
            s = d.get("slots") if isinstance(d, dict) else None
            _cache = (mt, {k: [str(x) for x in v if str(x).strip()] for k, v in (s or {}).items() if isinstance(v, list)})
        except (OSError, ValueError):
            pass  # 写坏了：接着用上次读到的
    return _cache[1]


def providers(slot: str, path: str = "") -> list[str]:
    """这一格填的模型 id（空着就看它回退的那一格）；都空 = []，用主模型。"""
    t = table(path)
    ids = list(t.get(slot) or [])
    if not ids and slot in FALLBACK:
        ids = list(t.get(FALLBACK[slot]) or [])
    return ids


def slot_rest(pid: str, path: str = "") -> list[str]:
    """pid 在哪一格里：返回那一格里排在它后面的（当后备）；不在任何一格返回 []。"""
    for ids in table(path).values():
        if pid in ids:
            return ids[ids.index(pid) + 1:]
    return []


async def slot_model(body, slot: str, model: str = "", who: str = "") -> str:
    """body.slot_model 的稳妥版：body 是旧的（热重载换不了 body.py，要重启 AstrBot 才有 slot_model）就照原来 model_id。"""
    fn = getattr(body, "slot_model", None)
    if fn is not None:
        return await fn(slot, model, who)
    return await (body.model_id(model, who) if who else body.model_id(model))
