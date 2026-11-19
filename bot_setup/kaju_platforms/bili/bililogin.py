"""佳树自己的 B 站小号：扫码登录 + Cookie 自动续期，WBI 签名。

- 扫码登录：/佳树B站登录 → 向 passport 要一张二维码（链接画成图片发到私聊）→ 兄长用小号的 B 站 App 扫码、点确认
  → 拿到登录 Cookie（SESSDATA、bili_jct……）和 refresh_token，存在插件数据目录的 bili_login.json（不进插件配置）。
  全程不碰密码。
- 自动续期：B 站网页版自己的机制——每天问一次 cookie/info "该刷新了吗"，要刷新就
  用公钥把 refresh_<毫秒时间戳> 加密成 correspondPath → 打开 /correspond/1/<path> 拿 refresh_csrf
  → cookie/refresh 换一套新 Cookie 和新 refresh_token → confirm/refresh 让旧的作废。
  续不上（太久没开、改了密码、被强制下线）才需要再扫一次码。
- 匿名的 buvid3/buvid4（B 站认设备用的）从 finger/spi 要；WBI 签名用的 img_key/sub_key 从 nav 接口拿，每天会换。

Cookie 只发给 *.bilibili.com。
"""

from __future__ import annotations

import binascii
import hashlib
import json
import os
import re
import time
import urllib.parse
from functools import reduce
from http.cookies import SimpleCookie

PASSPORT = "https://passport.bilibili.com"
API = "https://api.bilibili.com"
WWW = "https://www.bilibili.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")

# 二维码状态（qrcode/poll 返回的 data.code）
QR_OK, QR_WAIT, QR_SCANNED, QR_EXPIRED = 0, 86101, 86090, 86038

# 登录后要留的 Cookie
LOGIN_KEYS = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
DEVICE_KEYS = ("buvid3", "buvid4")

# B 站网页端生成 correspondPath 用的公钥（RSA-OAEP / SHA-256）
PUBKEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDLgd2OAkcGVtoE3ThUREbio0Eg
Uc/prcajMKXvkCKFCWhJYJcLkcM2DKKcSeFpD/j6Boy538YXnR6VhcuUJOhH2x71
nzPjfdTcqMz7djHum0qSZA0AyCBDABUqCrfNgCiJ00Ra7GmRj+YCK1NJEuewlb40
JNrRuoEUXpabUzGB8QIDAQAB
-----END PUBLIC KEY-----"""

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]


class LoginGone(Exception):
    """登录没了（Cookie 失效、refresh_token 对不上），要重新扫码。"""


# ------------------------------------------------------------------ 纯函数
def cookie_header(cookies: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items() if v)


def parse_set_cookie(headers: list[str]) -> dict:
    """响应里的 Set-Cookie 们 → {名字: 值}（只要还有值的；过期删除的 Cookie 值是空的，不要）。"""
    out = {}
    for h in headers or []:
        jar = SimpleCookie()
        try:
            jar.load(h)
        except Exception:  # noqa: BLE001
            continue
        for k, m in jar.items():
            if m.value and m.value.lower() != "deleted":
                out[k] = m.value
    return out


def cookies_from_cross_url(url: str) -> dict:
    """扫码成功时 data.url 是 crossDomain?DedeUserID=…&SESSDATA=…&bili_jct=…：Set-Cookie 没拿到时从这里补。"""
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url or "").query)
    return {k: q[k][0] for k in LOGIN_KEYS if q.get(k) and q[k][0]}


def correspond_path(ts_ms: int, pubkey: str = PUBKEY) -> str:
    """refresh_<毫秒时间戳> 用公钥 RSA-OAEP(SHA-256) 加密，小写十六进制。"""
    msg = f"refresh_{int(ts_ms)}".encode()
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        key = serialization.load_pem_public_key(pubkey.encode())
        enc = key.encrypt(msg, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    except ImportError:
        from Crypto.Cipher import PKCS1_OAEP
        from Crypto.Hash import SHA256
        from Crypto.PublicKey import RSA

        enc = PKCS1_OAEP.new(RSA.importKey(pubkey), SHA256).encrypt(msg)
    return binascii.b2a_hex(enc).decode()


def parse_refresh_csrf(html: str) -> str:
    m = re.search(r'<div\s+id="1-name"\s*>\s*([0-9a-zA-Z]+)\s*</div>', html or "")
    return m.group(1) if m else ""


def wbi_keys(nav_data: dict) -> tuple[str, str]:
    """nav 接口的 data.wbi_img → (img_key, sub_key)。未登录时 nav 返回 -101，但 data.wbi_img 照样有。"""
    w = (nav_data or {}).get("wbi_img") or {}

    def name(u: str) -> str:
        return (u or "").rsplit("/", 1)[-1].split(".")[0]
    return name(w.get("img_url", "")), name(w.get("sub_url", ""))


def mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    if len(raw) < 64:
        return ""
    return reduce(lambda s, i: s + raw[i], MIXIN_KEY_ENC_TAB, "")[:32]


def wbi_sign(params: dict, mixin: str, now: float | None = None) -> dict:
    """给请求参数加 wts、w_rid（参数按名字排序、去掉 !'()* 后 urlencode，拼上 mixin_key 取 MD5）。"""
    p = dict(params)
    p["wts"] = int(round(now if now is not None else time.time()))
    p = {k: "".join(c for c in str(v) if c not in "!'()*") for k, v in sorted(p.items())}
    p["w_rid"] = hashlib.md5((urllib.parse.urlencode(p) + mixin).encode()).hexdigest()
    return p


def make_qr_png(text: str, path: str) -> str:
    import qrcode

    qr = qrcode.QRCode(border=3, box_size=8, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    qr.make_image(fill_color="black", back_color="white").save(path)
    return path


# ------------------------------------------------------------------ 登录状态（存文件）
class Store:
    """bili_login.json：{cookies, refresh_token, uname, mid, login_at, checked_at, refreshed_at, gone, warned_at}"""

    def __init__(self, path: str):
        self.path = path
        self.data: dict = {}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f) or {}
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("cookies", {})

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    @property
    def cookies(self) -> dict:
        return self.data["cookies"]

    @property
    def logged_in(self) -> bool:
        return bool(self.cookies.get("SESSDATA")) and not self.data.get("gone")

    def header(self, with_login: bool = True) -> str:
        """给请求用的 Cookie：登录着就带上登录 Cookie；没登录只带设备号。"""
        keep = (LOGIN_KEYS + DEVICE_KEYS) if with_login and self.logged_in else DEVICE_KEYS
        return cookie_header({k: self.cookies[k] for k in keep if self.cookies.get(k)})

    def set_login(self, cookies: dict, refresh_token: str, now: float | None = None) -> None:
        now = now or time.time()
        for k in LOGIN_KEYS:
            if cookies.get(k):
                self.cookies[k] = cookies[k]
        if refresh_token:
            self.data["refresh_token"] = refresh_token
        self.data.update(login_at=now, checked_at=now, gone=False, warned_at=0)

    def logout(self) -> None:
        for k in LOGIN_KEYS:
            self.cookies.pop(k, None)
        for k in ("refresh_token", "uname", "mid", "login_at", "checked_at", "refreshed_at", "gone", "warned_at"):
            self.data.pop(k, None)


# ------------------------------------------------------------------ 联网（session 是 aiohttp.ClientSession）
def _host_ok(url: str) -> bool:
    host = urllib.parse.urlsplit(url).hostname or ""
    return host == "bilibili.com" or host.endswith(".bilibili.com")


async def api_json(session, method: str, url: str, cookie: str = "", **kw) -> tuple[dict, list[str]]:
    if not _host_ok(url):
        raise ValueError(f"不是 B 站的地址：{url}")
    headers = {"User-Agent": UA, "Referer": WWW + "/", "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    async with session.request(method, url, headers=headers, **kw) as r:
        text = await r.text(errors="replace")
        set_cookie = list(r.headers.getall("Set-Cookie", [])) if hasattr(r.headers, "getall") else []
        if r.status != 200:
            raise RuntimeError(f"{url.split('?')[0]} 返回 {r.status}")
    return json.loads(text), set_cookie


async def ensure_device(session, store: Store) -> None:
    """没有 buvid3/buvid4 就向 finger/spi 要一对（B 站认设备用，不登录也要）。"""
    if store.cookies.get("buvid3"):
        return
    data, _ = await api_json(session, "GET", API + "/x/frontend/finger/spi")
    d = data.get("data") or {}
    if d.get("b_3"):
        store.cookies["buvid3"] = d["b_3"]
    if d.get("b_4"):
        store.cookies["buvid4"] = d["b_4"]


async def qr_generate(session) -> tuple[str, str]:
    data, _ = await api_json(session, "GET", PASSPORT + "/x/passport-login/web/qrcode/generate")
    d = data.get("data") or {}
    if data.get("code") != 0 or not d.get("url") or not d.get("qrcode_key"):
        raise RuntimeError(f"二维码没要到：{data.get('message') or data.get('code')}")
    return d["url"], d["qrcode_key"]


async def qr_poll(session, key: str) -> tuple[int, dict, str]:
    """(状态码, 登录 Cookie, refresh_token)；没扫/没确认时 Cookie 是空的。"""
    data, set_cookie = await api_json(session, "GET", PASSPORT + "/x/passport-login/web/qrcode/poll",
                                   params={"qrcode_key": key})
    d = data.get("data") or {}
    code = int(d.get("code", -1))
    if code != QR_OK:
        return code, {}, ""
    cookies = {**cookies_from_cross_url(d.get("url", "")), **parse_set_cookie(set_cookie)}
    return code, {k: v for k, v in cookies.items() if k in LOGIN_KEYS}, str(d.get("refresh_token") or "")


async def nav(session, store: Store) -> dict:
    """nav 接口的 data（isLogin、uname、mid、wbi_img）。"""
    data, _ = await api_json(session, "GET", API + "/x/web-interface/nav", store.header())
    return data.get("data") or {}


async def check_login(session, store: Store) -> dict:
    """登录着就记下昵称；Cookie 失效了标记 gone。返回 nav 的 data。"""
    d = await nav(session, store)
    if store.cookies.get("SESSDATA"):
        if d.get("isLogin"):
            store.data.update(uname=d.get("uname", ""), mid=d.get("mid", 0), gone=False)
        else:
            store.data["gone"] = True
    return d


async def refresh_if_needed(session, store: Store, force: bool = False) -> str:
    """问 B 站要不要刷新 Cookie，要就刷新。返回一句结果；登录已经没了抛 LoginGone。"""
    if not store.cookies.get("SESSDATA"):
        raise LoginGone("还没扫码登录")
    csrf = store.cookies.get("bili_jct", "")
    data, _ = await api_json(session, "GET", PASSPORT + "/x/passport-login/web/cookie/info", store.header(),
                          params={"csrf": csrf})
    store.data["checked_at"] = time.time()
    if data.get("code") == -101:
        store.data["gone"] = True
        raise LoginGone("登录已经失效")
    if data.get("code") != 0:
        raise RuntimeError(f"cookie/info 返回 {data.get('code')}：{data.get('message', '')}")
    d = data.get("data") or {}
    if not d.get("refresh") and not force:
        return "不用刷新"
    old_token = str(store.data.get("refresh_token") or "")
    if not old_token:
        raise LoginGone("没有 refresh_token（不是扫码登录的），续不了期")
    ts = int(d.get("timestamp") or time.time() * 1000)
    url = f"{WWW}/correspond/1/{correspond_path(ts)}"
    headers = {"User-Agent": UA, "Referer": WWW + "/", "Cookie": store.header()}
    async with session.get(url, headers=headers) as r:
        html = await r.text(errors="replace")
        if r.status != 200:
            raise RuntimeError(f"correspond 返回 {r.status}")
    refresh_csrf = parse_refresh_csrf(html)
    if not refresh_csrf:
        raise RuntimeError("correspond 页面里没找到 refresh_csrf")
    data, set_cookie = await api_json(session, "POST", PASSPORT + "/x/passport-login/web/cookie/refresh", store.header(),
                                   data={"csrf": csrf, "refresh_csrf": refresh_csrf, "source": "main_web",
                                         "refresh_token": old_token})
    if data.get("code") in (-101, 86095):
        store.data["gone"] = True
        raise LoginGone(f"刷新被拒（{data.get('code')}：{data.get('message', '')}）")
    if data.get("code") != 0:
        raise RuntimeError(f"cookie/refresh 返回 {data.get('code')}：{data.get('message', '')}")
    new_token = str((data.get("data") or {}).get("refresh_token") or "")
    fresh = {k: v for k, v in parse_set_cookie(set_cookie).items() if k in LOGIN_KEYS}
    if not fresh.get("SESSDATA") or not new_token:
        raise RuntimeError("刷新回来没带新的 Cookie")
    for k, v in fresh.items():
        store.cookies[k] = v
    store.data["refresh_token"] = new_token
    store.data["refreshed_at"] = time.time()
    # 用新 Cookie + 旧 refresh_token 确认，旧的那套才作废；这一步失败不影响新的能用
    try:
        await api_json(session, "POST", PASSPORT + "/x/passport-login/web/confirm/refresh", store.header(),
                    data={"csrf": store.cookies.get("bili_jct", ""), "refresh_token": old_token})
    except Exception:  # noqa: BLE001
        pass
    return "刷新了"
