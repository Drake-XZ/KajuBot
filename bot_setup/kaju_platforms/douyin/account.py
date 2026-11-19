"""她自己的抖音小号（原来在 kaju_basics 的 main.py 里）：扫码登录到一个 Chrome 资料夹、常驻浏览器保持登录、
登录掉了告诉兄长。抖音那边的页面操作在 douyin.py，常驻浏览器在 dykeeper.py。

DouyinAccount 是 mixin，宿主要有：body（kaju_core.body.Body）、log、_sec(name)、_describer（download_dir()）、
_tell_owner(text)（shared.owner.Owner）。登录记录在 self._dy_login，常驻浏览器是 self._dy_keeper。
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from kaju_core import paths

from . import douyin, dykeeper


def _q(name) -> str:
    """「名字」；没拿到名字就不写。"""
    return f"「{name}」" if name else ""


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


class JsonFile:
    """一个小 JSON 文件（.data 是字典）。"""

    def __init__(self, path: str):
        self.path = path
        try:
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f) or {}
        except (OSError, ValueError):
            self.data = {}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)


class DouyinAccount:
    def _douyin_account_init(self) -> None:
        self._dy_profile = paths.account("douyin_profile")  # 她自己的抖音小号：扫码登录过的 Chrome 资料夹
        self._dy_login = JsonFile(paths.account("douyin_login.json"))  # {nickname, login_at, checked_at, gone}
        self._dy_qr_task = None
        # 抖音小号的常驻浏览器（dykeeper.py）：扫码后一直开着她的资料夹，抖音自己续登录；看抖音时借它开标签页
        self._dy_keeper = dykeeper.Keeper(self._dy_profile, lambda: self._dy_login.data, self._dy_login.save,
                                          cache=paths.cache_dir("douyin_chrome"),
                                          channel=self._dy_channel())
        douyin.KEEPER = self._dy_keeper if self._dy_keep_on() else None
        self._dy_keep_task = None

    def _dy_logged(self) -> bool:
        d = self._dy_login.data
        return bool(d.get("login_at")) and not d.get("gone") and os.path.isdir(self._dy_profile)

    def _dy_channel(self) -> str:
        return str(self._sec("media").get("douyin_browser") or "chrome")

    def _dy_keep_on(self) -> bool:
        return bool(self._sec("media").get("douyin_keep", True))

    def _dy_num(self, key: str, default: float) -> float:
        try:
            return float(self._sec("media").get(key, default))
        except (TypeError, ValueError):
            return default

    async def _dy_keep_loop(self) -> None:
        """登录着：常驻浏览器一直开着；每 douyin_keep_check_minutes 问一次"我是谁"，每 douyin_keep_refresh_hours
        把它停着的那页刷新一下。登录没了：记下、关掉它、告诉兄长（三天最多一次）。没登录：它开着就关掉。"""
        await asyncio.sleep(20)
        while True:
            try:
                await self._dy_keep_tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"kaju_basics: 抖音常驻浏览器出错 {type(e).__name__}: {e}")
            await asyncio.sleep(300)

    async def _dy_keep_tick(self, force: bool = False) -> str:
        d = self._dy_login.data
        if not self._dy_logged():
            if d.get("keeper"):
                await self._dy_keeper.stop()
                self.log.info("kaju_basics: 抖音小号没登录着，常驻浏览器关了")
            return "没登录"
        now = time.time()
        said = ""
        async with douyin._gate():
            async with douyin._playwright() as p:
                fresh = not await self._dy_keeper.running(True)
                if force or fresh or now - float(d.get("checked_at") or 0) > self._dy_num("douyin_keep_check_minutes", 30) * 60:
                    me = await self._dy_keeper.whoami(p)  # 没开着会先起一个
                    d["checked_at"] = now
                    if me["state"] == "ok":
                        d["nickname"] = me["nickname"] or d.get("nickname", "")
                        said = f"登录着（{d['nickname']}）"
                    elif me["state"] == "out":
                        self._dy_login.save()
                        self._dy_gone("常驻浏览器里问抖音：没登录（status_code 8）")
                        await self._dy_keeper.stop()
                        await self._warn_dy_gone()
                        return "登录掉了"
                    else:
                        said = "没问出来"
                    if fresh:
                        self.log.info(f"kaju_basics: 抖音常驻浏览器起来了，{said}")
                if now - float(d.get("refreshed_at") or 0) > self._dy_num("douyin_keep_refresh_hours", 2) * 3600:
                    await self._dy_keeper.refresh(p)
                    d["refreshed_at"] = now
        self._dy_login.save()
        return said or "登录着"

    async def _warn_dy_gone(self) -> None:
        d = self._dy_login.data
        if not self._sec("media").get("douyin_notify_owner", True) or time.time() - float(d.get("warned_at") or 0) < 3 * 86400:
            return
        if await self._tell_owner("【佳树抖音】抖音小号的网页登录掉了，要用的话私聊发「/佳树抖音登录」重新扫码。"):
            d["warned_at"] = time.time()
            self._dy_login.save()

    def _dy_gone(self, why: str) -> None:
        """登录没了（抖音那边过期了 / 被退出了）：记下来，以后看链接、刷抖音都不用小号。"""
        if self._dy_login.data.get("login_at") and not self._dy_login.data.get("gone"):
            self._dy_login.data["gone"] = True
            self._dy_login.save()
            self.log.warning(f"kaju_basics: 抖音小号登录没了（{why}），要重新扫码")

    async def douyin_login_command(self, action: str, where: str, in_group: bool) -> tuple[str, bool]:
        """/佳树抖音登录 [状态｜退出]：返回 (要回的话, 要不要拦下这条消息)。扫码：后台开浏览器，二维码发到 where。"""
        action = action.strip()
        d = self._dy_login.data
        if action in ("状态", "看看"):
            if not d.get("login_at"):
                return "还没登录抖音小号。私聊发「/佳树抖音登录」扫码。", False
            try:
                now = await douyin.check_login(self._dy_profile, channel=self._dy_channel())
            except Exception as e:  # noqa: BLE001
                return f"查登录状态时出错了：{type(e).__name__}: {e}", False
            keep = d.get("keeper") or {}
            d["checked_at"] = time.time()
            if now["logged_in"]:
                d["gone"] = False
                d["nickname"] = now["nickname"] or d.get("nickname", "")
            self._dy_login.save()
            if not now["logged_in"]:
                self._dy_gone("查状态时没登录")
            when = time.strftime("%m-%d %H:%M", time.localtime(float(d["login_at"])))
            alive = bool(keep) and bool(await self._dy_keeper.running(True))
            return (f"抖音小号{_q(d.get('nickname'))}"
                    + ("登录着" if now["logged_in"] else "登录掉了，要重新扫码") + f"；扫码 {when}"
                    + (f"；常驻浏览器开着（端口 {keep.get('port')}，从 "
                       f"{time.strftime('%m-%d %H:%M', time.localtime(float(keep.get('started') or 0)))}）"
                       if alive else "；常驻浏览器没开")), False
        if action in ("退出", "登出"):
            await self._dy_keeper.stop()
            douyin.logout(self._dy_profile)
            self._dy_login.data = {}
            self._dy_login.save()
            return "抖音小号退出了（只删了这台电脑上存的登录，账号本身没动）。", False
        if in_group:
            return "扫码登录请私聊发我哦，二维码别发在群里。", False
        if self._dy_qr_task is not None and not self._dy_qr_task.done():
            return "上一个二维码还在等着扫呢（电脑上那个浏览器窗口还开着）。", False
        if time.time() - float(getattr(self, "_dy_qr_at", 0) or 0) < 5:  # 同一条命令几乎同时到了两次：只处理一次
            return "", True
        self._dy_qr_at = time.time()
        self._dy_qr_task = asyncio.create_task(self._douyin_scan(where))
        return "在电脑上开抖音登录窗口，二维码马上发过来…", True

    async def _douyin_scan(self, umo: str) -> None:
        png = os.path.join(self._describer.download_dir(), f"douyin_qr_{int(time.time())}.png")

        async def say(kind: str, data: str) -> None:
            if kind == "qr":
                await self.body.send(umo, "用佳树的抖音小号在手机抖音App里扫这个码（首页左上角 ≡ → 扫一扫），再点「确认登录」。"
                                     "在电脑旁边的话，直接扫电脑上那个浏览器窗口里的码最稳（那个一直是新的）；"
                                     "要是还要短信验证码或者拖滑块，就在那个窗口里做完~（等 5 分钟）", image=data)
            elif kind == "scanned":
                await self.body.send(umo, "扫到啦，在手机上点一下确认~ 电脑上要是还要验证，就在那个窗口里做完")

        try:
            got = await douyin.qr_login(self._dy_profile, png, say, channel=self._dy_channel())
        except asyncio.CancelledError:
            _remove(png)
            raise
        except Exception as e:  # noqa: BLE001
            got = {"logged_in": False, "why": f"出错了（{type(e).__name__}: {e}）"}
            self.log.warning(f"kaju_basics: 抖音扫码登录出错 {type(e).__name__}: {e}")
        _remove(png)
        if got.get("logged_in"):
            self._dy_login.data = {"nickname": got.get("nickname", ""), "login_at": time.time(),
                                   "checked_at": time.time(), "gone": False}
            self._dy_login.save()
            if self._dy_keep_on():
                try:
                    await self._dy_keeper.ensure(True)
                    self.log.info("kaju_basics: 扫码登录后，抖音常驻浏览器起来了")
                except Exception as e:  # noqa: BLE001
                    self.log.warning(f"kaju_basics: 抖音常驻浏览器没起来 {type(e).__name__}: {e}")
            said = (f"抖音小号{_q(got.get('nickname'))}登录好啦！电脑上的窗口已经关了，"
                    "后台留了一个看不见的浏览器一直开着，帮小号保持登录。")
            self.log.info(f"kaju_basics: 抖音小号扫码登录：{got.get('nickname')}（问抖音：{got.get('check', '-')}）")
        else:
            said = f"抖音小号没登录上：{got.get('why', '')}。要再试就再发一次「/佳树抖音登录」。"
            self.log.info(f"kaju_basics: 抖音扫码登录没成：{got.get('why', '')}")
        await self.body.send(umo, said)
