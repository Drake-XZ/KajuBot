"""她的心情和对人的感觉：心情四维和情绪表（heart）、每轮聊天后的评估（appraise）、心事回想（afterthought）、心里记下的话（inner）、关系的几个侧面（relation）、自己长出来的喜好（taste）、自己刷到的视频的感受（browsed）。

不认识 AstrBot，也不认识任何聊天软件；kaju_heart 插件是它的 AstrBot 外壳。"""

import time as _time

LOADED_AT = _time.time()  # kaju_core.fresh("heart") 用：文件比这个新 = 重新部署过，热重载时要重新读
