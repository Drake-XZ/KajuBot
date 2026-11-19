"""谁是谁：一个人在 QQ / B站 / 抖音上的号，认成同一个人（她对这个人的心情、好感、记忆、称呼、聊天记录都是一份）。

人的"钥匙"（person key）沿用各插件一直在用的那个号，老数据不用改：
- 有 QQ 的人：QQ 号（"111111111"）
- 只在 B站 私信过的人："bili_<UID>"；只在抖音私信过的："douyin_<数字 uid>"
没登记过的号就是它自己的钥匙（default_key）；登记了（link）的号都认到那个人的钥匙上。
兄长大人本人 = owner 那把钥匙（只有一个）。

存在 kaju_data/self/people/people.json（她本人的东西，backup-self 会备份）：
    {"owner": "111111111",
     "people": {"111111111": {"accounts": {"bili": "10000001", "douyin": "MS4w…"}, "note": "兄长大人本人"}}}
抖音的号用 sec_uid 登记（私信、主页链接里用的就是它）。
改这个文件（botctl people …、/佳树认人）之后，各插件下次用到时自己会重新读（看文件修改时间）。
"""

from __future__ import annotations

import json
import os
import threading

from . import paths

PLATFORMS = {"qq": "QQ", "bili": "B站", "douyin": "抖音"}
PREFIX = {"bili": "bili_", "douyin": "douyin_"}  # QQ 没有前缀


def default_key(platform: str, account: str) -> str:
    """没登记过的号自己当钥匙：QQ 号原样，B站 bili_<UID>，抖音 douyin_<数字 uid>。"""
    account = str(account or "").strip()
    return PREFIX.get(platform, "") + account if platform != "qq" else account


def split_key(key: str) -> tuple[str, str]:
    """钥匙 → (平台, 号)：bili_123 → ("bili", "123")；111111111 → ("qq", "111111111")。"""
    key = str(key or "")
    for platform, prefix in PREFIX.items():
        if key.startswith(prefix):
            return platform, key[len(prefix):]
    return "qq", key


def label(key: str) -> str:
    """号码怎么写给她看："QQ n" / "B站 n" / "抖音 n"。"""
    platform, account = split_key(key)
    return f"{PLATFORMS.get(platform, platform)} {account}"


class People:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(paths.self_dir("people"), "people.json")
        self._lock = threading.Lock()
        self._mtime = -1.0
        self.data: dict = {"owner": "", "people": {}}
        self._index: dict[tuple[str, str], str] = {}

    # ---------------------------------------------------------------- 读写
    def _fresh(self) -> None:
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            mtime = 0.0
        if mtime == self._mtime:
            return
        with self._lock:
            data = {"owner": "", "people": {}}
            if mtime:
                try:
                    with open(self.path, encoding="utf-8") as f:
                        loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data.update(loaded)
                except (OSError, ValueError):
                    return  # 写到一半之类：先用上次读到的
            data.setdefault("people", {})
            self.data, self._mtime = data, mtime
            self._index = {}
            for key, person in data["people"].items():
                for platform, account in (person.get("accounts") or {}).items():
                    if account:
                        self._index[(platform, str(account))] = key

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        self._mtime = -1.0
        self._fresh()

    # ---------------------------------------------------------------- 认人
    def owner(self) -> str:
        """兄长大人本人的钥匙（QQ 号）；还没登记返回 ''。"""
        self._fresh()
        return str(self.data.get("owner") or "")

    def key(self, platform: str, account: str, fallback: str = "") -> str:
        """这个号是谁：登记过的认到那个人，没登记的用 fallback（没给就是 default_key）。"""
        self._fresh()
        account = str(account or "").strip()
        hit = self._index.get((platform, account))
        if hit:
            return hit
        if platform == "qq" and account in self.data["people"]:
            return account
        return fallback or default_key(platform, account)

    def is_owner(self, platform: str, account: str) -> bool:
        owner = self.owner()
        return bool(owner) and self.key(platform, account) == owner

    def accounts(self, key: str) -> dict[str, str]:
        """这个人在各平台的号（含钥匙本身那个号）。"""
        self._fresh()
        platform, account = split_key(key)
        out = {platform: account} if account else {}
        out.update({p: str(a) for p, a in ((self.data["people"].get(key) or {}).get("accounts") or {}).items() if a})
        return out

    def account(self, key: str, platform: str) -> str:
        """这个人在某个平台的号；没有返回 ''。"""
        return self.accounts(key).get(platform, "") if key else ""

    def is_linked(self, platform: str, account: str) -> bool:
        """这个号登记到了别的钥匙上（不是它自己）。"""
        self._fresh()
        hit = self._index.get((platform, str(account or "").strip()))
        return bool(hit) and hit != default_key(platform, account)

    # ---------------------------------------------------------------- 登记
    def link(self, key: str, platform: str, account: str, note: str = "") -> str:
        """把一个号认到 key 这个人上（原来认在别人那就挪过来）。返回说明。"""
        if platform not in PLATFORMS:
            raise ValueError(f"不认识的平台 {platform}（只有 {'、'.join(PLATFORMS)}）")
        key, account = str(key).strip(), str(account or "").strip()
        if not key or not account:
            raise ValueError("钥匙和号都不能空")
        self._fresh()
        people = self.data["people"]
        moved = ""
        for other, person in list(people.items()):
            accs = person.get("accounts") or {}
            if other != key and str(accs.get(platform) or "") == account:
                accs.pop(platform, None)
                moved = f"（原来认在 {other} 上）"
                if not accs and not person.get("note") and other != self.data.get("owner"):
                    people.pop(other)
        person = people.setdefault(key, {"accounts": {}})
        person.setdefault("accounts", {})
        if split_key(key) != (platform, account):
            person["accounts"][platform] = account
        if note:
            person["note"] = note
        self.save()
        return f"{PLATFORMS[platform]} {account} → {key}{moved}"

    def unlink(self, platform: str, account: str) -> str:
        self._fresh()
        account = str(account or "").strip()
        for key, person in self.data["people"].items():
            accs = person.get("accounts") or {}
            if str(accs.get(platform) or "") == account:
                accs.pop(platform)
                self.save()
                return f"{PLATFORMS.get(platform, platform)} {account} 不再认作 {key}"
        return f"{PLATFORMS.get(platform, platform)} {account} 本来就没登记"

    def set_owner(self, key: str) -> None:
        self._fresh()
        key = str(key).strip()
        self.data["owner"] = key
        self.data["people"].setdefault(key, {"accounts": {}}).setdefault("note", "兄长大人本人")
        self.save()

    def describe(self) -> list[str]:
        """一人一行，给 botctl / 命令看。"""
        self._fresh()
        owner = self.owner()
        keys = ([owner] if owner else []) + [k for k in self.data["people"] if k != owner]
        out = []
        for key in keys:
            accs = "，".join(f"{PLATFORMS.get(p, p)} {a}" for p, a in self.accounts(key).items())
            note = (self.data["people"].get(key) or {}).get("note") or ""
            out.append(f"{key}{'（兄长大人本人）' if key == owner else ''}：{accs}" + (f"  — {note}" if note and key != owner else ""))
        return out


_registry: People | None = None


def registry() -> People:
    """大家共用的那一份（kaju_data/self/people/people.json）。"""
    global _registry
    path = os.path.join(paths.self_dir("people"), "people.json")
    if _registry is None or _registry.path != path:  # 测试里数据目录会换
        _registry = People(path)
    return _registry


def owner() -> str:
    """兄长大人本人的钥匙（QQ 号）；身份表还没登记返回 ''（调用的地方用自己的老办法兜底）。"""
    try:
        return registry().owner()
    except Exception:  # noqa: BLE001 — 身份表坏了不能拖垮插件
        return ""
