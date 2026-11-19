"""佳树本人：不认识任何聊天软件、也不依赖 AstrBot 的那一部分。

- paths：她的东西放在哪（kaju_data 的 self / accounts / cache）。
- senses：她的感官——看视频（画面 + 声音）、补看一段、看动图、听音乐、听语音、读文字文件。
以后人格、记忆、心情、知识、说话方式也会一块块搬进来；插件（AstrBot 外壳）和各平台（QQ / B站 / 抖音）都只调这里。

部署：botctl deploy kaju_core（或 deploy 不带名字）复制到 AstrBot 旁边，venv 里的 kaju_core.pth 指过去。
插件热重载时调 fresh("senses") 就会重新读重新部署过的那部分；kaju_core 自己（本文件、paths）改了要重启 AstrBot。
"""

import os
import sys


def _changed(pkg) -> bool:
    """包里有 .py 比这个包被 import 的时候新（重新部署过）。包得在 __init__ 里记 LOADED_AT。"""
    loaded = getattr(pkg, "LOADED_AT", None)
    folder = os.path.dirname(getattr(pkg, "__file__", "") or "")
    if loaded is None or not folder:
        return False
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.endswith(".py"):
                try:
                    if os.path.getmtime(os.path.join(root, f)) > loaded:
                        return True
                except OSError:
                    pass
    return False


def fresh(*parts: str) -> list[str]:
    """kaju_core.<part> 重新部署过（文件比 import 时新）就把它和下面的模块从 sys.modules 拿掉，
    接下来的 import 会重新读文件（插件热重载时用）。没改过就什么都不做（测试里打的补丁也不会丢）。
    已经拿到旧模块的别的插件照旧用旧的，直到它们自己重载。返回拿掉了哪些。"""
    gone = []
    for part in parts:
        name = f"{__name__}.{part}"
        pkg = sys.modules.get(name)
        if pkg is None or not _changed(pkg):
            continue
        for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
            sys.modules.pop(key, None)
            gone.append(key)
        if hasattr(sys.modules[__name__], part):
            delattr(sys.modules[__name__], part)
    return gone
