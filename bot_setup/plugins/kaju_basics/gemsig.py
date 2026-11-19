"""Gemini 历史整理：空文字补空格、没签名的工具调用补占位签名（daitu 改写成文字）（2026-11-19）。

起因：主模型一轮里先由别家（Claude / 另一个中转）调过工具，再换到 daitu 的 gemini-4-argon 时，
历史里的 function_call 没有 thought_signature。daitu 1 秒回 400
"placeholder thought signatures are not supported by Gemini-VT"。
实测（scratchpad daitu_probe.py / daitu_real_hist.py，兄长私聊的真实历史）：
- 小请求里补谷歌文档写的 b"skip_thought_signature_validator" 能过；但真实历史里补了照样有时被当占位拒
  → daitu 上把没真签名的旧工具调用和对应结果写成文字（UNSIGNED_AS_TEXT），别家照旧补 skip 签名。
- 只有思考、没有正文的旧回复 AstrBot 会转成空文字 part，daitu 每次 "Request contains an invalid argument."
  → 空文字一律补成一个空格（AstrBot 别处也这么补）。
有真签名的工具调用（同一家这一轮自己调的）不动。
"""
from __future__ import annotations

import functools
import json

ORIG = "_kaju_gemsig_orig"
SKIP_SIG = b"skip_thought_signature_validator"
UNSIGNED_AS_TEXT = ("daitu.cc",)  # api_base 里含这些的：没签名的工具调用改写成文字


def _text_part(text: str):
    from google.genai import types
    return types.Part.from_text(text=text)


def _brief(obj, n: int = 600) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        s = str(obj)
    return s if len(s) <= n else s[:n] + "…"


def fix(contents, as_text: bool = False, make_text=None) -> dict:
    """就地整理，返回各改了几处：{"blank": 空文字, "signed": 补签名, "texted": 改成文字}。"""
    make_text = make_text or _text_part
    out = {"blank": 0, "signed": 0, "texted": 0}
    pending: list[str] = []  # 改成文字的调用，等着把它们的结果也改成文字
    for c in contents or []:
        parts = getattr(c, "parts", None) or []
        role = getattr(c, "role", None)
        new = []
        for p in parts:
            fc = getattr(p, "function_call", None)
            fr = getattr(p, "function_response", None)
            if role == "model" and fc is not None and not getattr(p, "thought_signature", None):
                if as_text:
                    name = getattr(fc, "name", "") or ""
                    new.append(make_text(f"[调用了工具 {name} {_brief(getattr(fc, 'args', None) or {}, 300)}]"))
                    pending.append(name)
                    out["texted"] += 1
                    continue
                p.thought_signature = SKIP_SIG
                out["signed"] += 1
            elif fr is not None and pending and getattr(fr, "name", None) in pending:
                pending.remove(fr.name)
                new.append(make_text(f"[工具 {fr.name} 的结果] {_brief(getattr(fr, 'response', None))}"))
                continue
            elif fc is None and fr is None and getattr(p, "text", None) is not None and not p.text.strip() \
                    and getattr(p, "inline_data", None) is None and getattr(p, "file_data", None) is None:
                p.text = " "
                out["blank"] += 1
            new.append(p)
        if parts:
            c.parts = new
    return out


def fill(contents) -> int:
    """老接口：只补签名，返回补了几个。"""
    return fix(contents)["signed"]


def _as_text_for(prov) -> bool:
    base = str(getattr(prov, "api_base", "") or (getattr(prov, "provider_config", None) or {}).get("api_base", "") or "")
    return any(h in base for h in UNSIGNED_AS_TEXT)


def _cls(cls=None):
    if cls is not None:
        return cls
    from astrbot.core.provider.sources.gemini_source import ProviderGoogleGenAI
    return ProviderGoogleGenAI


def install(log=None, cls=None) -> bool:
    try:
        cls = _cls(cls)
    except Exception:  # noqa: BLE001
        return False
    orig = cls.__dict__.get(ORIG) or cls._prepare_conversation
    setattr(cls, ORIG, orig)

    @functools.wraps(orig)
    async def _prepare_conversation(self, payloads):
        contents = await orig(self, payloads)
        try:
            fix(contents, as_text=_as_text_for(self))
        except Exception as e:  # noqa: BLE001
            if log:
                log(f"kaju_basics: 整理 Gemini 历史出错，照原样发 {type(e).__name__}: {e}")
        return contents

    cls._prepare_conversation = _prepare_conversation
    return True


def uninstall(cls=None) -> None:
    try:
        cls = _cls(cls)
    except Exception:  # noqa: BLE001
        return
    orig = cls.__dict__.get(ORIG)
    if orig is not None:
        cls._prepare_conversation = orig
        delattr(cls, ORIG)
