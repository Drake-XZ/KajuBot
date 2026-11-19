"""佳树的东西放在哪：按"能不能删"分成三类，都在 kaju_data 下面。

    kaju_data/
      self/       她本人：心情、记忆、知识本、日记、称呼簿、表情包……   → 要备份，不能乱删
        <名字>/   一个插件一个目录（kaju_life、memory_weight、memorix、meme_manager……）
      accounts/   各平台的登录：B站小号 Cookie、抖音小号的 Chrome 资料夹   → 丢了要重新扫码
      cache/      下载的视频、截的帧、临时音频、浏览器缓存……             → 随时可以清（botctl clean-cache）

AstrBot 原来的 plugin_data/<插件全名> 现在是指到 self/<名字> 的目录联接，老路径照样能读。

根目录：环境变量 KAJU_DATA → 部署时写的 _root.py → 都没有就报错。
离线测试（只设了 STUB_DATA）：仍按老的 plugin_data 排法放在 STUB_DATA 下，测试不用改。
"""

from __future__ import annotations

import os

# 第三方插件的数据目录名（不是 astrbot_plugin_ 开头的照原样）
THIRD_PARTY = {"memorix": "astrbot_plugin_memorix", "meme_manager": "meme_manager"}


def short(name: str) -> str:
    """astrbot_plugin_kaju_life → kaju_life；meme_manager 照旧。"""
    return name.removeprefix("astrbot_plugin_")


def legacy_name(name: str) -> str:
    """kaju_life → astrbot_plugin_kaju_life（AstrBot plugin_data 下的目录名）。"""
    s = short(name)
    return THIRD_PARTY.get(s) or "astrbot_plugin_" + s


def _stub() -> str:
    return "" if os.environ.get("KAJU_DATA") else os.environ.get("STUB_DATA", "")


def root() -> str:
    env = os.environ.get("KAJU_DATA")
    if env:
        return env
    stub = os.environ.get("STUB_DATA")
    if stub:
        return os.path.join(stub, "kaju_data")
    try:
        from ._root import ROOT  # botctl deploy 写的
    except ImportError as e:
        raise RuntimeError("kaju_core 不知道 kaju_data 在哪：设 KAJU_DATA，或用 botctl deploy kaju_core 部署") from e
    return ROOT


def self_dir(name: str) -> str:
    """她本人的数据目录（不会自动建）。"""
    stub = _stub()
    if stub:
        return os.path.join(stub, legacy_name(name))
    return os.path.join(root(), "self", short(name))


def account(name: str) -> str:
    """accounts/ 下的一个文件或目录路径（会建好上一级）。"""
    stub = _stub()
    path = os.path.join(stub, "accounts", name) if stub else os.path.join(root(), "accounts", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def cache_dir(name: str) -> str:
    """cache/<name>/（会建好）。里面的东西随时可能被 clean-cache 删掉，只放能重新拿到的。"""
    stub = _stub()
    path = os.path.join(stub, "cache", name) if stub else os.path.join(root(), "cache", name)
    os.makedirs(path, exist_ok=True)
    return path
