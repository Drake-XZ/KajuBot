"""她自己的几个部分互相找（心情找记忆、刷视频找心情和知识本、说说找写手……）用的登记表。

每个部分（kaju_core 的 HeartMind / MemoryMind / LearnMind / LifeMind / StyleMind，kaju_platforms 的 DmMind）
起来时 register(名字, 自己)，停下时 unregister(名字, 自己)。别的部分用 body.find(attr) 找：先在这里找，
这里没有（比如称呼簿、memorix 这些不是她本人的插件）才退回接入平台自己的清单（AstrBot 的插件表）。

同一个名字后登记的顶掉先登记的（热重载时新实例起来、旧实例还没停的那一两秒也不会找到旧的）。
这个模块不跟着 fresh() 换新（登记表要一直在）；改了它要重启 AstrBot。
"""

from __future__ import annotations

_parts: dict[str, object] = {}


def register(name: str, obj) -> None:
    _parts[name] = obj


def unregister(name: str, obj) -> None:
    """只在登记的还是 obj 时才去掉（新实例已经顶上了就不动）。"""
    if _parts.get(name) is obj:
        _parts.pop(name, None)


def get(name: str):
    return _parts.get(name)


def find(attr: str):
    """有 attr 这个属性的那个部分；没有返回 None。"""
    for obj in list(_parts.values()):
        if hasattr(obj, attr):
            return obj
    return None


def names() -> list[str]:
    return list(_parts)
