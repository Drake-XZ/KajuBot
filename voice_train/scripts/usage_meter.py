r"""数一数造数据时调了多少、谁答的、进出多少字，用来估钱（2026-11-17，兄长：“先跑一点小规模的，然后告诉我预估多少钱”）。

中转站不回价格，这里只记：每家（omni.plan_names 的名字）调了几次、送进去多少字、拿回来多少字。
估钱：字 → token（中文约 1.4 字一个 token，粗估）× model_router.json 里的 price（“Gemini Flash 官方价 = 1”的倍数）× 假设的官方价。
官方价是假设（见 FLASH_USD），实际以中转后台为准；Gemini 的思考 token 按输出算，这里数不到，所以输出可能偏少。

用法：import usage_meter; usage_meter.patch()   之后 omni.text 的每次调用都会记下；usage_meter.report(path) 存 JSON 并返回摘要。
"""
import json
import os
import threading

USAGE = {}
_lock = threading.Lock()
CHARS_PER_TOKEN = 1.4
FLASH_USD = {"in": 0.30, "out": 2.50}  # 每百万 token 的美元价（按 Gemini 2.5 Flash 官方价假设；3.x 可能更贵）
USD_RMB = 7.2


def patch():
    from kaju_core.senses import omni
    if getattr(omni.text, "_metered", False):
        return
    orig = omni.text

    async def text(system, user, *a, **kw):
        out, n = await orig(system, user, *a, **kw)
        names = omni.plan_names("card")
        who = names[n - 1] if 0 < n <= len(names) else str(n)
        try:  # 记下这家的地址：router 表按地址（match）认价格，光看名字认不出（11-17 hardysapi 的 Claude 被当成 1 倍）
            k = omni.plan("card", omni.gemini_keys())[n - 1][0]
            url = f"{k.get('base_url', '')} {k.get('model', '')}"
        except Exception:  # noqa: BLE001
            url = ""
        with _lock:
            u = USAGE.setdefault(who, {"calls": 0, "in_chars": 0, "out_chars": 0, "url": url})
            u["calls"] += 1
            u["in_chars"] += len(system or "") + len(user or "")
            u["out_chars"] += len(out or "")
        return out, n
    text._metered = True
    omni.text = text


def _price(name, url=""):
    """model_router.json tasks.card 里这一家的 price（Gemini Flash 官方价 = 1）；按名字 + 地址找 match，模型名也要对上；找不到按 1。"""
    try:
        from kaju_core import paths
        t = json.load(open(os.path.join(paths.root(), "accounts", "model_router.json"), encoding="utf-8"))
        hay = f"{name} {url}"
        for row in t["tasks"]["card"]["models"]:
            if row.get("match", "") in hay and str(row.get("model", "")) in hay:
                return float(row.get("price", 1))
    except Exception:  # noqa: BLE001
        pass
    return 1.0


def project(by: dict, scale: float, price_override: dict | None = None) -> float:
    """按这批每家的字数，换一种“由谁来答”的比例估全量（比如全落到便宜的 bb-api）。price_override：{名字片段: 价格倍数}。"""
    tin = sum(u["in_chars"] for u in by.values()) / CHARS_PER_TOKEN
    tout = sum(u["out_chars"] for u in by.values()) / CHARS_PER_TOKEN
    base = (tin * FLASH_USD["in"] + tout * FLASH_USD["out"]) / 1e6 * USD_RMB * scale
    return round(base * (price_override or 1.0), 2) if not isinstance(price_override, dict) else round(base, 2)


def report(path=None, scale=1.0):
    """返回 {每家: calls/in_chars/out_chars/价格倍数/估的人民币}；scale = 全量是这次的几倍。"""
    rows, total = {}, 0.0
    for who, u in USAGE.items():
        p = _price(who, u.get("url", ""))
        tin, tout = u["in_chars"] / CHARS_PER_TOKEN, u["out_chars"] / CHARS_PER_TOKEN
        rmb = (tin * FLASH_USD["in"] + tout * FLASH_USD["out"]) / 1e6 * p * USD_RMB
        rows[who] = {**u, "price": p, "rmb": round(rmb, 4), "rmb_full": round(rmb * scale, 2)}
        total += rmb
    res = {"by": rows, "rmb": round(total, 4), "rmb_full": round(total * scale, 2), "scale": scale,
           "assume": {"chars_per_token": CHARS_PER_TOKEN, "flash_usd_per_m": FLASH_USD, "usd_rmb": USD_RMB}}
    if path:
        json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return res
