"""她的生活：关于自己的事实（selffacts）。日程、日记还在 kaju_life 插件里（要用 AstrBot 的模型和 QQ）。

不认识 AstrBot，也不认识任何聊天软件；kaju_life 插件是它的 AstrBot 外壳。"""

import time as _time

LOADED_AT = _time.time()  # kaju_core.fresh("life") 用：文件比这个新 = 重新部署过，热重载时要重新读
