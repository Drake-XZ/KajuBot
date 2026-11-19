# 测试用的假 AstrBot。顺便让插件 import 到源码里的 kaju_core（而不是部署到 AstrBot 旁边的那份）。
import os as _os
import sys as _sys

_SETUP = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
if _SETUP not in _sys.path:
    _sys.path.insert(0, _SETUP)
