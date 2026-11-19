"""记忆轻重：分量和遗忘曲线（weigh）、给记忆打分量的提示（rater）、触景生情（cue）、珍藏的文件（shelf）、褪色（fade）。

不认识 AstrBot，也不认识任何聊天软件；memory_weight 插件是它的 AstrBot 外壳。"""

import time as _time

LOADED_AT = _time.time()  # kaju_core.fresh("memory") 用：文件比这个新 = 重新部署过，热重载时要重新读
