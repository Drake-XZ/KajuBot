"""她抖音小号的常驻浏览器（2026-11-08，思路来自 NEWJO123/dsh-douyin-scroll 的 lib/chrome.mjs）。

为什么：以前每次看抖音都用 Playwright 临时开一个 Chrome、用完就关。2026-11-08 19:53 扫码登录，
不到一个小时抖音那边就把网页登录注销了（profile/self 回 status_code 8），本地的 sessionid 还在。
那个仓库的做法是：扫码之后让一个普通的 chrome.exe（不是 Playwright 起的，没有自动化标记）带着同一个资料夹
一直开着、停在抖音页面上，由抖音自己的网页续登录；要用时连上它的调试端口开个新标签页，用完只关标签页。

这里也这样：
- Keeper.ensure()：资料夹的 Chrome 活着就复用，不在就起一个（--headless=new，屏幕上没有窗口）。
  端口和进程号记在 douyin_login.json 的 keeper 里；插件重载不关它，重载后照样接回去。
- 扫码时 ensure(headless=False)：同一个资料夹起一个看得见的 Chrome，扫完关掉，再起无头的。
- whoami()：用浏览器自己的 Cookie 问一下抖音"我是谁"（不签名的只读接口 user/profile/self），
  status_code 0 = 登录着，8 = 登录没了。
- refresh()：隔几个小时把它停着的那页刷新一下（让抖音的网页自己活动一下）。

不做的（照旧）：不导出 Cookie、不伪造签名参数（a_bogus 之类）、不伪装 TLS、不碰验证码。
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import time
import urllib.request

PORTS = range(9350, 9390)
CACHE_BYTES = 100 * 1024 * 1024  # 网页缓存最多 100 MB（以前放在资料夹里涨到 160 多 MB）
REST_URL = "https://www.douyin.com/user/self"  # 停在"我的"页面：抖音的网页一直在，又不会一直放视频
# 无头常驻时省内存（2026-11-13）：Chrome 自带的几个后台扩展（各开一个 service worker）、翻译、组件更新、
# 优化提示这些她用不着的后台服务都不开。不碰抖音网页本身、不碰 Cookie。
LEAN = ["--disable-component-extensions-with-background-pages", "--disable-component-update",
        "--disable-default-apps", "--disable-sync", "--no-pings",
        "--disable-features=Translate,OptimizationHints,MediaRouter,DialMediaRouteProvider,AutofillServerCommunication"]
SELF_API = "https://www.douyin.com/aweme/v1/web/user/profile/self/?device_platform=webapp&aid=6383"


def find_chrome(channel: str = "chrome") -> str:
    names = ("Microsoft\\Edge\\Application\\msedge.exe",) if channel == "msedge" else \
        ("Google\\Chrome\\Application\\chrome.exe", "Microsoft\\Edge\\Application\\msedge.exe")
    roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    roots += ["C:\\Program Files", "C:\\Program Files (x86)", "D:\\Program Files"]
    for name in names:
        for r in filter(None, roots):
            p = os.path.join(r, name)
            if os.path.isfile(p):
                return p
    return ""


def _version(port: int, timeout: float = 2) -> dict:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except Exception:  # noqa: BLE001
        return {}


def _free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        # tasklist 的提示是系统编码（GBK）的中文，按 UTF-8 读会在读输出的线程里报错
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                             encoding="oem", errors="replace",
                             timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return str(pid) in out
    except Exception:  # noqa: BLE001
        return False


def parse_self(d: dict) -> dict:
    """user/profile/self 的回答 → {state: ok/out/unknown, nickname, uid}。"""
    if not isinstance(d, dict) or "status_code" not in d:
        return {"state": "unknown", "nickname": "", "uid": ""}
    user = d.get("user") or {}
    if int(d.get("status_code") or 0) == 0 and (user.get("uid") or user.get("sec_uid") or user.get("nickname")):
        return {"state": "ok", "nickname": str(user.get("nickname") or ""), "uid": str(user.get("uid") or "")}
    if int(d.get("status_code") or 0) == 8 or not user:
        return {"state": "out", "nickname": "", "uid": ""}
    return {"state": "unknown", "nickname": "", "uid": ""}


class Keeper:
    """state：douyin_login.json 的内容（dict，会写入 state["keeper"]）；save()：存它。"""

    def __init__(self, profile: str, state_get, save, channel: str = "chrome", cache: str = ""):
        self.profile = profile
        self.cache = cache  # 网页缓存另放（kaju_data/cache/douyin_chrome），资料夹里只剩登录
        self._state = state_get
        self._save = save
        self.channel = channel
        self._lock = asyncio.Lock()

    def info(self) -> dict:
        return dict(self._state().get("keeper") or {})

    async def running(self, headless: bool | None = None) -> str:
        """活着就返回调试地址，不然 ''。"""
        k = self.info()
        port = int(k.get("port") or 0)
        if not port or (headless is not None and bool(k.get("headless", True)) != headless):
            return ""
        v = await asyncio.to_thread(_version, port)
        return f"http://127.0.0.1:{port}" if v.get("webSocketDebuggerUrl") else ""

    async def ensure(self, headless: bool = True, url: str = REST_URL) -> str:
        async with self._lock:
            ep = await self.running(headless)
            if ep:
                return ep
            await self._stop()
            exe = find_chrome(self.channel)
            if not exe:
                raise RuntimeError("这台电脑上没找到 Chrome")
            os.makedirs(self.profile, exist_ok=True)
            port = next((p for p in PORTS if _free(p)), 0)
            if not port:
                raise RuntimeError("调试端口 9350–9389 都被占了")
            args = [exe, f"--remote-debugging-port={port}", f"--user-data-dir={self.profile}",
                    "--no-first-run", "--no-default-browser-check", "--window-size=1280,800", "--lang=zh-CN"]
            if self.cache:
                args[1:1] = [f"--disk-cache-dir={self.cache}", f"--disk-cache-size={CACHE_BYTES}"]
            if headless:  # 无头的用不着显卡渲染（那个进程单独就占 300 多 MB），也不出声
                args[1:1] = ["--headless=new", "--disable-gpu", "--mute-audio", *LEAN]
            args.append(url)
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            if headless:
                flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
            for _ in range(60):
                await asyncio.sleep(0.5)
                if (await asyncio.to_thread(_version, port)).get("webSocketDebuggerUrl"):
                    st = self._state()
                    st["keeper"] = {"port": port, "pid": proc.pid, "headless": headless, "started": time.time()}
                    self._save()
                    return f"http://127.0.0.1:{port}"
                if proc.poll() is not None:
                    break
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError("Chrome 没起来（多半是资料夹被别的 Chrome 占着）")

    async def stop(self) -> None:
        async with self._lock:
            await self._stop()

    async def _stop(self) -> None:
        """先让 Chrome 自己正常关（Cookie 会写回资料夹），关不掉再强关。"""
        k = self.info()
        port, pid = int(k.get("port") or 0), int(k.get("pid") or 0)
        if not port and not pid:
            return
        v = await asyncio.to_thread(_version, port) if port else {}
        ws = v.get("webSocketDebuggerUrl")
        if ws:
            try:
                import aiohttp

                async with aiohttp.ClientSession() as s:
                    w = await asyncio.wait_for(s.ws_connect(ws), 5)
                    async with w:
                        await w.send_json({"id": 1, "method": "Browser.close"})
                        try:
                            await asyncio.wait_for(w.receive(), 5)
                        except Exception:  # noqa: BLE001
                            pass
            except Exception:  # noqa: BLE001
                pass
        for _ in range(20):
            if not (port and (await asyncio.to_thread(_version, port, 1)).get("webSocketDebuggerUrl")) \
                    and not await asyncio.to_thread(_pid_alive, pid):
                break
            await asyncio.sleep(0.5)
        else:
            if pid:
                await asyncio.to_thread(subprocess.run, ["taskkill", "/PID", str(pid), "/T", "/F"],
                                        capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                await asyncio.sleep(1)
        st = self._state()
        st.pop("keeper", None)
        self._save()

    # ------------------------------------------------------------ 用它
    async def whoami(self, p) -> dict:
        """连上常驻浏览器问一下"我是谁"。p 是 async_playwright() 给的对象。"""
        ep = await self.ensure(True)
        browser = await p.chromium.connect_over_cdp(ep)
        try:
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            r = await ctx.request.get(SELF_API, headers={"Referer": "https://www.douyin.com/"}, timeout=15000)
            try:
                d = await r.json()
            except Exception:  # noqa: BLE001
                d = {}
            return parse_self(d)
        finally:
            await browser.close()  # 只断开连接，常驻的 Chrome 不关

    async def refresh(self, p) -> None:
        """把它停着的抖音页刷新一下（没有就开一页停在"我的"）。"""
        ep = await self.ensure(True)
        browser = await p.chromium.connect_over_cdp(ep)
        try:
            ctx = browser.contexts[0]
            page = next((pg for pg in ctx.pages if "douyin.com" in (pg.url or "")), None)
            if page is None:
                page = await ctx.new_page()
                await page.goto(REST_URL, wait_until="domcontentloaded", timeout=30000)
            else:
                await page.reload(wait_until="domcontentloaded", timeout=30000)
        finally:
            await browser.close()
