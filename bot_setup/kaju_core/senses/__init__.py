"""佳树的感官（不认识 AstrBot，也不认识任何聊天软件）。她只有这一套，QQ、B站、抖音、自己刷视频都用它。

- 拿到它：kaju_core.senses.get()（起来的时候登记在 kaju_core.parts 里，名字 "senses"）。
- 统一入口：Senses.perceive(本地文件) → Percept（看到听到了什么 + 以后放感受的位置），按文件类型自己分。
- perceive.py：Senses —— 看图和动图、看视频（画面分批看 + 声音转写 + 观后笔记）、补看某一段、听音乐、读文字文件，带半小时缓存。
  文件从哪来、用哪个模型由调用的地方给（open_file / Models）。
- media.py：视频截帧、拼图、音轨切段；animation.py：动图按时间拆帧拼成一张；relook.py：问到的时间点 → 补看哪一段。
- music.py + soundcheck/：听音乐本身（dsh-soundcheck 引擎，MIT）；localstt.py：本地 SenseVoice 语音转文字。
- docs.py：txt/md/字幕/代码、网页、docx、pdf、epub 读成文字。
"""

import time as _time

LOADED_AT = _time.time()  # kaju_core.fresh("senses") 用：文件比这个新 = 重新部署过，热重载时要重新读

PART = "senses"  # 在 kaju_core.parts 里登记的名字


def get():
    """她的感官（perceive.Senses）；还没起来返回 None。"""
    from kaju_core import parts

    return parts.get(PART)


def start(models, cfg, learner=lambda: None, log=None):
    """接入的地方（现在是 kaju_basics）给模型和设置，造出她的感官并登记。再调一次就换成新的。"""
    from kaju_core import parts

    from .perceive import Senses

    senses = Senses(models, cfg, learner=learner, log=log)
    parts.register(PART, senses)
    return senses


def stop(senses) -> None:
    """登记的还是这一个才去掉（热重载时新的已经顶上就不动）。"""
    from kaju_core import parts

    parts.unregister(PART, senses)
