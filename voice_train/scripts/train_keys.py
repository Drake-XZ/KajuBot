r"""训练 / 标注脚本用的 Gemini 接口。

2026-11-12 起 Gemini 的 key 都在 kaju_data\accounts\gemini_keys.json（一个列表，机器人和训练脚本共用，兄长有新 key 就往后加；
兄长：“不用刻意标注 gemini_train 了”）。这里按列表顺序，用一句很短的话试一下，**第一个答得上来的**就给脚本用
（每次运行只试一次；中转平台常常“账号用尽”，这样一个挂了自动换下一个）。都答不上来就给第一个，让脚本自己重试 / 报错。
没有 gemini_keys.json 时退回旧的 gemini.json / gemini_backup.json（kaju_core.senses.omni.gemini_keys 里处理）。
"""
import json
import os
import sys
import urllib.error
import urllib.request

os.environ.setdefault("KAJU_DATA", r"D:\JiashuBot\kaju_data")
sys.path.insert(0, r"D:\JiashuBot\bot_setup")
from kaju_core.senses import omni  # noqa: E402

_picked = None


def keys() -> list[dict]:
    """全部 Gemini key，按顺序。"""
    return omni.gemini_keys()


def _alive(k: dict) -> str:
    """用一句话试这个 key（原生格式 / "format": "openai" 的都走 omni._gemini_text，和机器人一样）；通了返回 ''。"""
    try:
        omni._gemini_text(k, "", "回一个字：好", "low", 60)
        return ""
    except urllib.error.HTTPError as e:
        return f"{e.code} {e.read()[:80].decode('utf-8', 'replace')}"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__} {str(e)[:80]}"


def gemini() -> dict:
    """给脚本用的那个 key（{api_key, base_url, model, api}）；一个都没填是 {}。"""
    global _picked
    if _picked is not None:
        return _picked
    ks = keys()
    if not ks:
        _picked = {}
        return _picked
    for n, k in enumerate(ks):
        err = _alive(k)
        if not err:
            print(f"Gemini：用第 {n + 1} 个 key（{k['base_url'].split('//')[-1]}，模型 {k['model']}）", flush=True)
            _picked = k
            return k
        print(f"Gemini：第 {n + 1} 个 key（{k['base_url'].split('//')[-1]}）现在用不了：{err}", flush=True)
    print("Gemini：几个 key 都用不了，先给第一个", flush=True)
    _picked = ks[0]
    return _picked
