"""她自己的 B 站小号（原来在 kaju_basics 的 main.py 里）：扫码登录、每天自己续期、登录掉了告诉兄长。
B 站那边的接口在 bililogin.py。

BiliAccount 是 mixin，宿主要有：body（kaju_core.body.Body）、log、_sec(name)、_describer（download_dir()）、
_tell_owner(text)（shared.owner.Owner）。登录存在 self._login（bililogin.Store），扫码任务在 self._qr_task。
"""

from __future__ import annotations

import asyncio
import os
import time

from kaju_core import paths

from . import bililogin


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


class BiliAccount:
    def _bili_account_init(self) -> None:
        self._login = bililogin.Store(paths.account("bili_login.json"))  # 她自己的 B 站小号（登录放 kaju_data/accounts）
        self._qr_task = None  # 正在等扫码的任务
        self._login_task = None

    def _lg(self, key: str, default):
        v = self._sec("bili_login").get(key, default)
        try:
            return type(default)(v) if v is not None and v != "" else default
        except (TypeError, ValueError):
            return default

    def _http(self, seconds: float = 0):
        import aiohttp

        return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(
            total=seconds or float(self._sec("media").get("bili_timeout", 15))))

    async def _login_loop(self) -> None:
        """每小时看一眼：离上次检查超过 check_hours 就问 B 站要不要刷新 Cookie（要就刷新）。"""
        await asyncio.sleep(90)
        while True:
            try:
                if (self._login.cookies.get("SESSDATA") and not self._login.data.get("gone")
                        and time.time() - float(self._login.data.get("checked_at") or 0) > self._lg("check_hours", 20.0) * 3600):
                    await self._refresh_login()
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"kaju_basics: B站登录续期出错 {type(e).__name__}: {e}")
            await asyncio.sleep(3600)

    async def _refresh_login(self, force: bool = False) -> str:
        try:
            async with self._http() as s:
                said = await bililogin.refresh_if_needed(s, self._login, force=force)
                d = await bililogin.check_login(s, self._login)
            if not d.get("isLogin"):
                raise bililogin.LoginGone("刷新后还是没登录上")
            said = f"B站小号「{self._login.data.get('uname', '')}」登录着，Cookie {said}"
            self.log.info(f"kaju_basics: {said}")
        except bililogin.LoginGone as e:
            self._login.data["gone"] = True
            said = f"B站小号登录没了（{e}），要重新扫码"
            self.log.warning(f"kaju_basics: {said}")
            await self._warn_login_gone()
        except Exception as e:  # noqa: BLE001
            # 网络之类的问题：两小时后再试
            self._login.data["checked_at"] = time.time() - max(0.0, self._lg("check_hours", 20.0) - 2) * 3600
            said = f"B站登录续期没成（{type(e).__name__}: {e}），过两小时再试"
            self.log.warning(f"kaju_basics: {said}")
        self._login.save()
        return said

    async def _warn_login_gone(self) -> None:
        """登录掉了：私聊兄长一句（三天最多一次）。"""
        if not self._lg("notify_owner", True) or time.time() - float(self._login.data.get("warned_at") or 0) < 3 * 86400:
            return
        if await self._tell_owner("兄长大人，佳树的B站小号登录掉了…有空的时候私聊发「/佳树B站登录」给我，用小号的B站App扫一下码就好啦"):
            self._login.data["warned_at"] = time.time()

    async def bili_login_command(self, action: str, where: str, in_group: bool) -> tuple[str, bool]:
        """/佳树B站登录 [状态｜续期｜退出]：返回 (要回的话, 要不要拦下这条消息)。
        扫码：二维码直接发到 where（会话 id），回的话为空，后台等扫码。"""
        action = action.strip()
        if action in ("状态", "看看"):
            d = self._login.data
            if not self._login.cookies.get("SESSDATA"):
                return "还没登录B站小号。私聊发「/佳树B站登录」扫码。", False

            def fmt(t):
                return time.strftime("%m-%d %H:%M", time.localtime(float(t))) if t else "没有"
            return (f"B站小号「{d.get('uname') or '?'}」{'登录掉了，要重新扫码' if d.get('gone') else '登录着'}；"
                    f"扫码 {fmt(d.get('login_at'))}，上次检查 {fmt(d.get('checked_at'))}，上次续期 {fmt(d.get('refreshed_at'))}"), False
        if action in ("续期", "刷新"):
            return await self._refresh_login(force=True), False
        if action in ("退出", "登出"):
            self._login.logout()
            self._login.save()
            return "B站小号退出了（只删了这边存的登录，账号本身没动）。", False
        if in_group:
            return "扫码登录请私聊发我哦，二维码别发在群里。", False
        if self._qr_task is not None and not self._qr_task.done():
            self._qr_task.cancel()
        try:
            async with self._http() as s:
                url, key = await bililogin.qr_generate(s)
        except Exception as e:  # noqa: BLE001
            return f"二维码没要到：{e}", False
        png = os.path.join(self._describer.download_dir(), f"bili_qr_{key[:8]}.png")
        await asyncio.to_thread(bililogin.make_qr_png, url, png)
        await self.body.send(where, "用佳树的B站小号在手机B站App里扫这个码，再点「确认登录」（3 分钟内有效）。", image=png)
        self._qr_task = asyncio.create_task(self._wait_scan(where, key, png))
        return "", True

    async def _wait_scan(self, umo: str, key: str, png: str) -> None:
        said, scanned = "二维码过期了，要登录就再发一次「/佳树B站登录」。", False
        try:
            async with self._http() as s:
                for _ in range(90):  # 2 秒问一次，最多 3 分钟
                    await asyncio.sleep(2)
                    code, cookies, token = await bililogin.qr_poll(s, key)
                    if code == bililogin.QR_SCANNED and not scanned:
                        scanned = True
                        await self.body.send(umo, "扫到啦，在手机上点一下确认~")
                    elif code == bililogin.QR_EXPIRED:
                        break
                    elif code == bililogin.QR_OK:
                        if not cookies.get("SESSDATA"):
                            said = "扫码成功了，但没拿到登录信息，再试一次吧。"
                            break
                        self._login.set_login(cookies, token)
                        await bililogin.ensure_device(s, self._login)
                        d = await bililogin.check_login(s, self._login)
                        self._login.save()
                        said = (f"B站小号「{d.get('uname') or '?'}」登录好啦！以后每天会自己续期，掉了才要再扫。"
                                if d.get("isLogin") else "扫码成功了，但检查登录时没通过，再试一次吧。")
                        self.log.info(f"kaju_basics: B站小号扫码登录：{d.get('uname')}（mid {d.get('mid')}），"
                                      f"refresh_token {'有' if token else '没有'}")
                        break
        except asyncio.CancelledError:
            _remove(png)
            raise
        except Exception as e:  # noqa: BLE001
            said = f"等扫码时出错了（{type(e).__name__}: {e}），再发一次「/佳树B站登录」试试。"
            self.log.warning(f"kaju_basics: B站扫码登录出错 {type(e).__name__}: {e}")
        _remove(png)
        await self.body.send(umo, said)
