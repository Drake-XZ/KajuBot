r"""造数据时只用某一家中转的 Gemini（2026-11-17 兄长：“等 bb-api 好了再跑”——bb-api 哈基米3 / 4 是 0.15 / 0.25 倍价，比 Claude / daitu 便宜十几倍）。

pin("bb-api") 之后，omni.text 只问 base_url 里带 bb-api 的 **Gemini** key（同站的 Claude 不算），顺序照兄长的动态挑选（model_router.json tasks.card）；
几家都没答上来就抛错，不落到别家（不然又按贵的算钱）。返回的序号还是在完整挑选顺序里的位置，usage_meter 照常认得是哪家。
probe("bb-api") 用一句很短的话试一下通不通（几乎不花钱）。
"""
import asyncio
import time

_ORIG = {}


def keys(match: str):
    from kaju_core.senses import omni
    plan = omni.plan("card", omni.gemini_keys())
    return [(i, k) for i, (k, _) in enumerate(plan, 1) if match in str(k.get("base_url", "")) and "gemini" in str(k.get("model", "")).lower()]


def pin(match: str = "bb-api", timeout: float = 60) -> None:
    from kaju_core.senses import omni
    if "text" not in _ORIG:
        _ORIG["text"] = omni.text

    async def text(system, user, *a, **kw):
        err = ""
        for i, k in keys(match):
            t0 = time.monotonic()
            try:
                out = await asyncio.wait_for(asyncio.to_thread(omni._gemini_text, k, system, user, kw.get("thinking", "low"), timeout), timeout + 10)
                omni._note(k, bool(out), time.monotonic() - t0, False, "" if out else "空")
                if out:
                    return out, i
                err = "空"
            except Exception as e:  # noqa: BLE001
                omni._note(k, False, time.monotonic() - t0, False, type(e).__name__)
                err = f"{type(e).__name__}: {str(e)[:60]}"
        raise RuntimeError(f"{match} 的 Gemini 都没答上来：{err}")
    omni.text = text


def probe(match: str = "bb-api") -> tuple[bool, str]:
    """每个 key 试一句短话；有一个答上来就算通。"""
    from kaju_core.senses import omni
    msgs = []
    for _, k in keys(match):
        try:
            out = omni._gemini_text(k, "", "只回一个字：好", "low", 40)
            if out:
                return True, f"{k.get('name')} 通了"
            msgs.append(f"{k.get('name')} 空")
        except Exception as e:  # noqa: BLE001
            msgs.append(f"{str(k.get('name'))[:16]} {type(e).__name__}: {str(e)[:50]}")
    return False, "；".join(msgs) or f"没有 {match} 的 Gemini key"
