"""几家模型中转最近好不好用（2026-11-14 兄长：“动态调整调用的 api 顺序”）。

主模型那边（kaju_basics 的 router.py 记 AstrBot 每次请求）和看图那边（omni.look 等记 gemini_keys.json 每个 key）
记在同一个文件里：kaju_data/cache/model_health.json。两边可能是热重载前后的两份模块，所以不靠内存共享，每次读写都对一下文件。

- 账号（account）：中转主机 + key 的指纹。同一个账号挂了，它下面的模型 / 思考档全都一起冷却。
- 槽（slot）：账号 + 模型 + 哪一档，记最近的耗时；大请求（主模型那种带工具、几万字的）和小请求（看图、探测）分开记。
- 连着失败 fail_streak 次 → 冷却 cool_minutes 分钟，这段时间排到最后；冷却中只要成功一次（真实请求或探测）就解除。
- 大请求失败另记（2026-11-15）：bb-api 的 Gemini 小请求（探测“回一个字”）次次成、大请求（她回话）次次 429 / 超时，
  探测一成功就把失败清零，换一档又当没失败过 → 又被排第一、白等 80 秒。现在大请求失败记 big_fail，
  只有大请求成功才清；rank 里 big_bad_minutes 分钟内这个账号的每一档在大请求上都靠后（主模型用，看图不用）。
  share_tiers：某一档还没有大请求成绩时，先借同账号同模型别的档的成绩，不直接用表里的预估。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import threading
import time
from urllib.parse import urlparse

KEEP = 20  # 每个槽每种大小留最近几次
FAIL_STREAK = 2
COOL_MINUTES = 10.0

_lock = threading.Lock()
_state: dict = {"accounts": {}, "slots": {}}
_mtime = 0.0
_path_override: str | None = None  # 测试用


def configure(fail_streak: int | None = None, cool_minutes: float | None = None) -> None:
    global FAIL_STREAK, COOL_MINUTES
    if fail_streak:
        FAIL_STREAK = max(1, int(fail_streak))
    if cool_minutes is not None:
        COOL_MINUTES = max(0.0, float(cool_minutes))


def _path() -> str:
    if _path_override:
        return _path_override
    from kaju_core import paths
    return os.path.join(paths.root(), "cache", "model_health.json")


def account(base_url: str, api_key: str) -> str:
    """中转主机 + key 指纹（不存 key 本身）。"""
    host = urlparse(base_url if "//" in str(base_url) else "//" + str(base_url)).netloc or str(base_url)
    tip = hashlib.sha1(str(api_key or "").encode()).hexdigest()[:6]
    return f"{host}#{tip}"


def _load() -> None:
    global _state, _mtime
    p = _path()
    try:
        m = os.path.getmtime(p)
    except OSError:
        return
    if m == _mtime:
        return
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            _state = {"accounts": dict(d.get("accounts") or {}), "slots": dict(d.get("slots") or {})}
            _mtime = m
    except (OSError, ValueError):
        pass


def _save() -> None:
    global _mtime
    p = _path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f, ensure_ascii=False)
        os.replace(tmp, p)
        _mtime = os.path.getmtime(p)
    except OSError:
        pass


def record(acc: str, slot: str, ok: bool, secs: float, big: bool = False, why: str = "",
           now: float | None = None) -> bool:
    """记一次结果。返回这次是不是刚好让这个账号进了冷却（调用的地方可以写一行日志）。"""
    now = time.time() if now is None else now
    with _lock:
        _load()
        a = _state["accounts"].setdefault(acc, {})
        s = _state["slots"].setdefault(slot, {})
        rows = s.setdefault("big" if big else "small", [])
        rows.append([round(now, 1), 1 if ok else 0, round(float(secs), 2)])
        del rows[:-KEEP]
        cooled_now = False
        if ok:
            a.update(streak=0, cool_until=0, last_ok=round(now, 1))
            if big:
                a.pop("big_fail", None)  # 小请求（探测）成功不算数：它成不代表大请求能成
        else:
            a["streak"] = int(a.get("streak") or 0) + 1
            a["last_fail"] = round(now, 1)
            a["why"] = str(why)[:120]
            if big:
                a["big_fail"] = round(now, 1)
            if a["streak"] >= FAIL_STREAK and float(a.get("cool_until") or 0) <= now:
                a["cool_until"] = round(now + COOL_MINUTES * 60, 1)
                cooled_now = True
        _save()
        return cooled_now


def cooled(acc: str, now: float | None = None) -> float:
    """还要冷却几秒（0 = 没在冷却）。"""
    now = time.time() if now is None else now
    with _lock:
        _load()
        a = _state["accounts"].get(acc) or {}
    return max(0.0, float(a.get("cool_until") or 0) - now)


def latency(slot: str, big: bool = False, n: int = 10) -> float | None:
    """最近 n 次的中位耗时；失败的那次算无穷大（超时、报错都不该显得快）。没有记录返回 None。"""
    with _lock:
        _load()
        rows = ((_state["slots"].get(slot) or {}).get("big" if big else "small") or [])[-n:]
    if not rows:
        return None
    return statistics.median([r[2] if r[1] else math.inf for r in rows])


def family_latency(slot: str, big: bool = False, n: int = 10) -> float | None:
    """slot（账号|模型|档）自己没成绩时，看同账号同模型别的档最近 n 次的中位耗时；都没有返回 None。"""
    head = slot.rsplit("|", 1)[0] + "|"
    key = "big" if big else "small"
    with _lock:
        _load()
        rows = [r for s, v in _state["slots"].items() if s.startswith(head) and s != slot
                for r in ((v or {}).get(key) or [])]
    rows = sorted(rows, key=lambda r: r[0])[-n:]
    if not rows:
        return None
    return statistics.median([r[2] if r[1] else math.inf for r in rows])


def big_fail_ago(acc: str, now: float | None = None) -> float | None:
    """这个账号上次大请求失败（之后没有大请求成功过）是几秒前；没有返回 None。"""
    now = time.time() if now is None else now
    with _lock:
        _load()
        t = (_state["accounts"].get(acc) or {}).get("big_fail")
    return None if not t else max(0.0, now - float(t))


def streak(acc: str) -> int:
    """这个账号最近连着失败了几次（成功一次归零）。"""
    with _lock:
        _load()
        return int((_state["accounts"].get(acc) or {}).get("streak") or 0)


def last_seen(acc: str) -> float:
    """这个账号最近一次有结果（成或败）是什么时候；没有是 0。"""
    with _lock:
        _load()
        a = _state["accounts"].get(acc) or {}
    return max(float(a.get("last_ok") or 0), float(a.get("last_fail") or 0))


def why(acc: str) -> str:
    with _lock:
        _load()
        return str((_state["accounts"].get(acc) or {}).get("why") or "")


def order_keys(keys: list[dict], now: float | None = None) -> list[dict]:
    """看图用：gemini_keys.json 的顺序（兄长排的）不动，只把正在冷却的账号挪到最后。"""
    hot, cold = [], []
    for k in keys:
        (cold if cooled(account(k.get("base_url", ""), k.get("api_key", "")), now) else hot).append(k)
    return hot + cold


def rank(cands: list[dict], want: str, cfg: dict, now: float | None = None) -> list[dict]:
    """cands: [{pid, account, slot, quality, price, think, secs(先验), big?}]，按配置里的顺序给。返回排好的（每项加 why）。
    最近中位耗时在预算内的按「质量 − 价格×price_weight（档位对上 want 再加 think_bonus）」排；超预算的、账号上次没答上来的按快慢排后面；
    冷却中的最后；同一个账号的第二档排在各账号第一档后面。主模型（kaju_basics router.py）和 omni 的各个功能都用它。"""
    now = time.time() if now is None else now
    budget = float(cfg.get("budget_high" if want == "high" else "budget_low", 25 if want == "high" else 12))
    pw = float(cfg.get("price_weight", 0.5))
    tb = float(cfg.get("think_bonus", 1.0))
    bbm = float(cfg.get("big_bad_minutes", 0) or 0)  # 主模型传 15；看图不传 = 不看
    share = bool(cfg.get("share_tiers", False))
    ok, slow, cold = [], [], []
    for i, c in enumerate(cands):
        left = cooled(c["account"], now)
        big = bool(c.get("big", True))
        lat = latency(c["slot"], big=big)
        if lat is None and share:
            lat = family_latency(c["slot"], big=big)
        if streak(c["account"]):  # 这个账号上一次（不管哪一档、真实请求还是探测）没答上来：排到健康的后面
            lat = math.inf
        ago = big_fail_ago(c["account"], now) if (bbm > 0 and big) else None
        big_bad = ago is not None and ago < bbm * 60
        if big_bad:
            lat = math.inf
        est = lat if lat is not None else float(c.get("secs") or budget / 2)
        score = float(c.get("quality", 5)) - pw * float(c.get("price", 1))
        if c.get("think") and c.get("think") == want:
            score += tb
        item = dict(c, est=est, score=score, order=i)
        if left > 0:
            item["why"] = f"冷却中还有 {left / 60:.0f} 分钟"
            cold.append(item)
        elif big_bad:
            item["why"] = f"最近大请求没答上来（{ago / 60:.0f} 分钟前）"
            slow.append(item)
        elif est > budget:
            item["why"] = "最近都没答上来" if math.isinf(est) else f"最近 {est:.0f}s 超预算 {budget:.0f}s"
            slow.append(item)
        else:
            item["why"] = f"约 {est:.0f}s · 分 {score:.1f}"
            ok.append(item)
    ok.sort(key=lambda x: (-x["score"], x["est"], x["order"]))
    slow.sort(key=lambda x: (x["est"], -x["score"], x["order"]))
    cold.sort(key=lambda x: (cooled(x["account"], now), x["order"]))
    out, later, seen = [], [], set()
    for group in (ok, slow):
        for x in group:
            (later if x["account"] in seen else out).append(x)
            seen.add(x["account"])
    return out + later + cold
