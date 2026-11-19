"""显卡在训练：这段时间她先不回群聊（2026-11-13 兄长：“可以让她训练时先不回群聊的消息吗，群聊我控制不了”）。

本机 8GB 显卡训写手时只剩几百 MB，群里有人叫她 → 写手 / bge-m3 加载进显存 → 训练爆显存。
训练脚本（voice_train\\scripts\\round_train.py train）开训前写一个标记文件、训完删掉；kaju_basics 看到标记就不回群聊
（在所有请求钩子之前停掉，记忆检索、主模型、写手都不跑；群聊记录照记）。私聊照常。

标记文件 kaju_data\\cache\\gpu_busy\\training.json：{"pid", "since", "what"}。为了不让她一直不说话：
写标记的进程已经不在了、或者标记超过 MAX_HOURS 小时，都当没有（训练崩了没删掉也不碍事）。
"""

import json
import os
import time

MAX_HOURS = 6.0


def _path() -> str:
    from kaju_core import paths
    return os.path.join(paths.cache_dir("gpu_busy"), "training.json")


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            ok = k.GetExitCodeProcess(h, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _write(p: str, obj: dict) -> None:
    """先写临时文件再换过去：hold 每 20 分钟重写一次，机器人刚好在读时不会读到写了一半的空文件（11-17 测试里撞上过）。"""
    tmp = f"{p}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, p)


def mark(what: str, pid: int | None = None, path: str | None = None) -> str:
    p = path or _path()
    _write(p, {"pid": int(pid or os.getpid()), "since": time.time(), "what": what})
    return p


def clear(path: str | None = None) -> None:
    try:
        os.remove(path or _path())
    except OSError:
        pass


def _pause_path() -> str:
    from kaju_core import paths
    return os.path.join(paths.cache_dir("gpu_busy"), "group_pause.json")


def pause(what: str = "兄长在控制台暂停了群聊", path: str | None = None) -> str:
    """手动暂停群聊（2026-11-17 兄长：“在控制台上加一个控制功能，我不希望在跑训练时她会说话”）。
    和训练标记不一样：不看进程、不会过期，一直到 resume() 才恢复。控制台（bot-panel.ps1 的「群聊暂停」）直接写 / 删这个文件。"""
    p = path or _pause_path()
    _write(p, {"since": time.time(), "what": what})
    return p


def resume(path: str | None = None) -> None:
    try:
        os.remove(path or _pause_path())
    except OSError:
        pass


def paused(path: str | None = None) -> str:
    """手动暂停着就返回原因，没暂停返回 ""。文件在但读不出来也算暂停（宁可不说）。"""
    p = path or _pause_path()
    if not os.path.exists(p):
        return ""
    try:
        with open(p, encoding="utf-8") as f:
            return str(json.load(f).get("what") or "兄长暂停了群聊")
    except Exception:  # noqa: BLE001
        return "兄长暂停了群聊"


def quiet_group(busy_path: str | None = None, pause_path: str | None = None) -> str:
    """群里这会儿该不该说话：显卡在训练（busy）或兄长手动暂停（paused）就返回原因，不然 ""。群聊的回复、主动去群里说话都先问它。"""
    return busy(busy_path) or paused(pause_path)


class hold:
    """训练整段都挂着标记（2026-11-16 兄长：“训练期间让佳树暂时不要回复群聊消息”）：
        with gpu_busy.hold("训练 H 层"): ...
    进去写标记、出来删掉；中间每 REFRESH 秒重写一次 since，训练超过 MAX_HOURS 小时也不会失效（原来 H 这种长训练过 6 小时她就又回群聊了）。
    进程崩了 / 被杀了，标记照旧按 pid 失效，不会让她一直不说话。"""

    REFRESH = 1200

    def __init__(self, what: str, path: str | None = None):
        self.what, self.path = what, path
        self._stop = None

    def __enter__(self):
        import threading
        mark(self.what, path=self.path)
        stop = self._stop = threading.Event()

        def loop():
            while not stop.wait(self.REFRESH):
                try:
                    mark(self.what, path=self.path)
                except OSError:
                    pass
        threading.Thread(target=loop, daemon=True).start()
        return self

    def __exit__(self, *exc):
        if self._stop:
            self._stop.set()
        clear(self.path)
        return False


def busy(path: str | None = None, now: float | None = None) -> str:
    """显卡在训练就返回在干什么（标记里的 what），不在 / 标记失效返回 ""。读不到、出错都当不忙。"""
    try:
        with open(path or _path(), encoding="utf-8") as f:
            v = json.load(f)
        if (now or time.time()) - float(v.get("since") or 0) > MAX_HOURS * 3600:
            return ""
        if not _alive(int(v.get("pid") or 0)):
            return ""
        return str(v.get("what") or "训练")
    except Exception:  # noqa: BLE001
        return ""
