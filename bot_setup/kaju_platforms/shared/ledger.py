"""私信的规矩记在这里（纯数据，不联网）：

- 每人每天让她看几条视频（兄长不算）；
- 要兄长批的事（requests）：follow = 要不要关注某人，video = 某人今天第 N 条视频要不要看，
  same = 私信里的人说自己是 QQ 上的某位，是不是同一个人（同意了就记进身份表 kaju_core.people）；
- 没互关的人发来的私信先存着（held），兄长同意关注、对方也关注了她，再接着回；
- 每个会话读到哪条了（seq）。

state.json 结构见 Ledger.EMPTY。uid 一律带平台前缀的 key：site:uid（"bili:123"）。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time

PENDING, YES, NO, DONE = "pending", "yes", "no", "done"
SITE_NAMES = {"bili": "B站", "douyin": "抖音"}


def key(site: str, uid: str) -> str:
    return f"{site}:{uid}"


def day_of(ts: float, tz=None, start_hour: int = 0) -> str:
    """这一天叫什么（配置时区；start_hour 之前算前一天）。"""
    d = dt.datetime.fromtimestamp(ts, tz) - dt.timedelta(hours=start_hour)
    return d.strftime("%Y-%m-%d")


def strip_links(text: str, links: list[str]) -> str:
    for u in links:
        text = text.replace(u, "")
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln and ln not in ("【】",)).strip()


class Ledger:
    EMPTY = {"seq": {}, "videos": {}, "requests": [], "next_id": 1, "held": {}, "known_fans": {}, "people": {}}

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
        for k, v in self.EMPTY.items():
            self.data.setdefault(k, json.loads(json.dumps(v)))

    def save(self) -> None:
        self._trim()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def _trim(self, now: float | None = None) -> None:
        now = now or time.time()
        days = sorted(self.data["videos"])
        for d in days[:-7]:
            self.data["videos"].pop(d, None)
        # 答复过的请求留 30 天
        self.data["requests"] = [r for r in self.data["requests"]
                                 if r["status"] == PENDING or now - float(r.get("answered_at") or r["t"]) < 30 * 86400]

    # ------------------------------------------------------------ 读到哪了
    def seq(self, site: str, talker: str) -> int:
        return int(self.data["seq"].get(key(site, talker)) or 0)

    def set_seq(self, site: str, talker: str, seq: int) -> None:
        if seq > self.seq(site, talker):
            self.data["seq"][key(site, talker)] = int(seq)

    # 抖音网页里消息的 createdAt 会变（11-13 同一条私信隔 12 秒又被当成新的读了一遍、回了两次），
    # 所以读过的还按消息编号记一份：编号见过的不再算新消息。每个会话留最近 300 个。
    SEEN_KEEP = 300

    def seen(self, site: str, talker: str) -> set[str]:
        return set((self.data.setdefault("seen", {}).get(key(site, talker))) or [])

    def add_seen(self, site: str, talker: str, ids) -> None:
        ids = [str(i) for i in ids if i]
        if not ids:
            return
        box = self.data.setdefault("seen", {})
        old = [i for i in (box.get(key(site, talker)) or []) if i not in set(ids)]
        box[key(site, talker)] = (old + ids)[-self.SEEN_KEEP:]

    # ------------------------------------------------------------ 视频
    def videos_used(self, site: str, uid: str, day: str) -> int:
        return int((self.data["videos"].get(day) or {}).get(key(site, uid)) or 0)

    def use_videos(self, site: str, uid: str, day: str, n: int) -> None:
        if n > 0:
            box = self.data["videos"].setdefault(day, {})
            box[key(site, uid)] = self.videos_used(site, uid, day) + n

    def split_videos(self, site: str, uid: str, day: str, links: list[str], limit: int) -> tuple[list[str], list[str]]:
        """这几条视频链接里，今天额度内能看的 / 要先问兄长的。limit < 0 = 不限。"""
        if limit < 0:
            return list(links), []
        room = max(0, limit - self.videos_used(site, uid, day))
        return list(links[:room]), list(links[room:])

    # ------------------------------------------------------------ 要兄长批的事
    def pending(self) -> list[dict]:
        return [r for r in self.data["requests"] if r["status"] == PENDING]

    def get(self, rid) -> dict | None:
        try:
            rid = int(str(rid).lstrip("#").strip())
        except ValueError:
            return None
        return next((r for r in self.data["requests"] if r["id"] == rid), None)

    def find(self, kind: str, site: str, uid: str, url: str = "", status: tuple = (PENDING,)) -> dict | None:
        return next((r for r in reversed(self.data["requests"])
                     if r["kind"] == kind and r["site"] == site and r["uid"] == uid
                     and (not url or r.get("url") == url) and r["status"] in status), None)

    def ask(self, kind: str, site: str, uid: str, name: str, *, url: str = "", title: str = "", text: str = "",
            now: float | None = None) -> tuple[dict, bool]:
        """登记一件要兄长批的事。同一件还在等的就不重复登记。→ (那件事, 是不是新的)"""
        old = self.find(kind, site, uid, url)
        if old:
            if name:
                old["name"] = name
            return old, False
        r = {"id": int(self.data["next_id"]), "kind": kind, "site": site, "uid": str(uid), "name": name,
             "url": url, "title": title, "text": text[:200], "t": now or time.time(), "status": PENDING,
             "told": False}
        self.data["next_id"] = r["id"] + 1
        self.data["requests"].append(r)
        return r, True

    def answer(self, rid, yes: bool, now: float | None = None) -> dict | None:
        r = self.get(rid)
        if r is None or r["status"] != PENDING:
            return r
        r["status"] = YES if yes else NO
        r["answered_at"] = now or time.time()
        return r

    def refused_follow(self, site: str, uid: str) -> bool:
        """兄长说过不关注这个人（之后TA再私信，也不再去问）。"""
        return self.find("follow", site, uid, status=(NO,)) is not None

    # ------------------------------------------------------------ 没互关时先存着的私信
    def hold(self, site: str, uid: str, items: list[dict], keep: int = 20) -> None:
        box = self.data["held"].setdefault(key(site, uid), [])
        box += items
        del box[:-keep]

    def take_held(self, site: str, uid: str) -> list[dict]:
        return self.data["held"].pop(key(site, uid), [])

    # ------------------------------------------------------------ 人
    def person(self, site: str, uid: str) -> dict:
        return self.data["people"].get(key(site, uid)) or {}

    def set_person(self, site: str, who: str, /, **kw) -> None:
        p = self.data["people"].setdefault(key(site, who), {})
        p.update({k: v for k, v in kw.items() if v not in (None, "")})


def describe(r: dict) -> str:
    """一件待批的事，一行（给兄长看的通知和她的提示都用这个）。"""
    site = SITE_NAMES.get(r["site"], r["site"])
    shown = r["uid"] if len(str(r["uid"])) <= 20 else ""  # 抖音的 sec_uid 太长，只写平台
    who = f"{r.get('name') or '某人'}（{site}{' ' + shown if shown else ''}）"
    if r["kind"] == "follow":
        said = f"，TA私信说：「{r['text'][:60]}」" if r.get("text") else ""
        return f"#{r['id']} {who}关注了佳树，要不要回关{said}"
    if r["kind"] == "same":
        # text = TA说自己是谁；title = 看着像 QQ 上的哪位（"QQ号 称呼"，可能空）
        guess = f"，看着像 QQ 上的{r['title']}" if r.get("title") else "，QQ 上没找到这个人"
        return f"#{r['id']} {who}说自己是「{r.get('text') or '?'}」{guess}：是同一个人吗"
    title = f"「{r['title'][:40]}」" if r.get("title") else ""
    return f"#{r['id']} {who}今天让佳树看的视频超过额度了，还想让她看{title} {r.get('url', '')}".rstrip()
