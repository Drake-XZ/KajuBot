"""本地模型服务（便携 Ollama，127.0.0.1:11435）一直开着。

2026-11-02 起 memorix 的向量模型（bge-m3）和看图用的 qwen3-vl 都跑在这个 Ollama 上，硅基流动不用了。
佳树控制台启动机器人时会先拉起它，但从 AstrBot Launcher 单独启动、或者 Ollama 半路退出时没人管，
记忆就只能按关键词找。这里在插件加载时和之后每隔一阵看一眼端口，没开就跑
`local_vision\\runtime.ps1 -Action Start`（可以重复执行，已经在跑就什么都不做）。

预热（2026-11-04）：模型闲置 10 分钟（runtime.ps1 的 OLLAMA_KEEP_ALIVE）会卸载，再用时 bge-m3 冷启动约 2 秒。
私聊来消息（连"正在输入"也算）或群里有人叫她时，先让 Ollama 把 bge-m3 加载上，等记忆检索真正用到时已经热了。
"""

import asyncio
import json
import os
import sys

CREATE_NO_WINDOW = 0x08000000  # 别弹黑窗口


async def is_up(host: str, port: int, timeout: float = 2.0) -> bool:
    """Something is listening on host:port."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


async def start(script: str, timeout: float = 180.0) -> tuple[bool, str]:
    """Run runtime.ps1 -Action Start. Returns (ok, last output line or reason)."""
    if not os.path.isfile(script):
        return False, f"找不到 {script}"
    try:
        proc = await asyncio.create_subprocess_exec(
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-Action", "Start",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    except OSError as e:
        return False, f"{type(e).__name__}: {e}"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return False, f"{timeout:.0f} 秒还没起来"
    text = (out or b"").decode("utf-8", "replace").strip()
    last = text.splitlines()[-1] if text else (err or b"").decode("utf-8", "replace").strip()[-200:]
    try:
        ok = proc.returncode == 0 and json.loads(last).get("state") == "running"
    except (ValueError, AttributeError):
        ok = False
    return ok, last


async def prewarm(url: str, body: dict, timeout: float = 60.0) -> None:
    """Ask Ollama to load a model now without producing anything (embed with empty input / generate without
    a prompt), so it is already in VRAM when the real request comes. Best effort: errors are ignored."""
    import aiohttp

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.post(url, json=body) as r:
                await r.read()
    except Exception:  # noqa: BLE001
        pass
