"""各平台怎么接：B站、抖音、QQ 的客户端和规矩（不碰 AstrBot）。佳树本人在 kaju_core，AstrBot 外壳在 plugins。

- bili/：B站；douyin/：抖音；shared/：B站和抖音共用的（自己刷视频、私信的规矩）；qq/：QQ 上的动作。
- 和 kaju_core 一起部署到 AstrBot 旁边（core\\data\\kaju_lib），venv 的 kaju_core.pth 指过去。
- 插件热重载时调 kaju_platforms.fresh("bili", ...)：重新部署过的那块就重新读（没改过什么都不做）。本文件改了要重启 AstrBot。
"""

import os
import sys


def _changed(pkg) -> bool:
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
    """同 kaju_core.fresh：kaju_platforms.<part> 重新部署过就从 sys.modules 拿掉，接下来的 import 读新的。"""
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
