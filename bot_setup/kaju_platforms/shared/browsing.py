"""有许可时自己刷 B 站 / 抖音（原来在 kaju_basics 的 main.py 里）：刷一页 → 按她的口味挑几个 → 一个个看完 →
感受交给心情、学到的交给知识本 → 特别想说的跟兄长说一句。规矩和提示词在 browse.py。

Browsing 是 mixin，宿主（kaju_basics 插件）要有：config/_sec()、body、log、_describer、_browse_log、
_heart()、_learner()、_tz()、_owner()、_owner_umo()、say_to_owner()、_http() 等（见各方法）。
"""

from __future__ import annotations

from kaju_core.slots import slot_model  # noqa: E402  每项工作一格（11-18）
import asyncio
import datetime as dt
import json
import os
import random
import re
import time

from kaju_platforms.bili import bili, bililogin
from kaju_platforms.douyin import douyin

from . import browse

class _QuietEvent:
    """自己刷 B 站时看视频用的"事件"：只告诉看视频的代码用哪个聊天的模型（兄长私聊），不对应任何一条消息。"""

    def __init__(self, umo: str):
        self.unified_msg_origin = umo
        self.bot = None
        self._extra: dict = {}

    def get_extra(self, k=None, default=None):
        return self._extra.get(k, default)

    def set_extra(self, k, v):
        self._extra[k] = v


class Browsing:
    """自己刷视频（宿主见模块说明）。"""

    # ------------------------------------------------------------ 有许可时自己刷 B 站（browse.py）
    def _bw(self, key: str, default):
        v = self._sec("browse").get(key, default)
        try:
            return type(default)(v) if v is not None and v != "" else default
        except (TypeError, ValueError):
            return default

    def start_browsing(self, event=None, minutes: float = 0, topic: str = "", by: str = "兄长大人", site: str = "bili") -> str:
        """开始在后台刷 B 站 / 抖音（site = bili / douyin）。返回给她看的一句话（开始了 / 为什么没开始）。"""
        name = browse.site_name(site)
        if not self._bw("enable", True) or (site == "douyin" and not self._bw("douyin", True)) or (
                site != "douyin" and not self._bili_on()):
            return f"没去成：刷{name}的功能关着。"
        try:
            minutes = float(minutes or 0)
        except (TypeError, ValueError):
            minutes = 0.0
        minutes = max(3.0, min(minutes or self._bw("minutes", 20.0), self._bw("max_minutes", 60.0)))
        topic = " ".join(str(topic or "").split())[:20]
        umo = self._owner_umo(event)
        where = str(getattr(event, "unified_msg_origin", "") or "") or umo  # 在哪儿叫她去的：刷完回那里说
        if self._browsing is not None and not self._browsing.done():
            run = self._browse_log.data.get("running") or {}
            n = len(run.get("items") or [])
            now_site = run.get("site") or self._browse_site
            if not topic and now_site == site:
                return f"已经在刷{name}了，还没看完（看完了 {n} 个）。"
            if topic and now_site == site and (
                    topic == self._browse_topic or (self._browse_next or {}).get("topic") == topic):
                return f"已经在{name}上找「{topic}」相关的了，还没看完（看完了 {n} 个）。"
            # 正在刷别的（她自己挑的、或者之前说的、或者另一个网站）：兄长最新点名的优先，手上这个看完就换过去，不丢掉
            self._browse_next = {"topic": topic, "minutes": minutes, "by": by, "umo": umo, "where": where, "site": site}
            what = f"去{name}上找「{topic}」相关的" if topic else f"去刷{name}"
            if run:
                run["switch_to"] = f"{name}上的{topic}" if topic and site != now_site else (topic or f"刷{name}")
            self.log.info(f"kaju_basics: 刷{browse.site_name(now_site)}：兄长又让{what}，手上这个看完就换过去")
            return (f"换过去了：手上正在看的这个看完，就{what}（还在后台看，还没开始，"
                    f"之前已经看完了 {n} 个）")
        now = time.time()
        if self._browse_log.count_on(browse.life_day(now, self._tz()), self._tz()) >= self._bw("daily_limit", 5):
            return f"没去成：今天已经刷了 {self._bw('daily_limit', 5)} 次了，今天就不刷了。"
        if site == "douyin" and not self._dy_logged():
            self.log.info("kaju_basics: 刷抖音：小号没登录，用不登录的浏览器刷精选")
        self._browse_topic, self._browse_site = topic, site
        self._browsing = asyncio.create_task(self._browse(umo, minutes, topic, by, where, site))
        return (f"开始刷{name}了（在后台看，最多 {minutes:.0f} 分钟、{self._bw('max_videos', 4)} 个视频）"
                + (f"，先找「{topic}」相关的" if topic else ""))

    async def _browse(self, umo: str, minutes: float, topic: str, by: str, where: str = "", site: str = "bili") -> None:
        """site：bili / douyin。umo：兄长私聊（心声、学到的都记在那儿）；where：在哪儿叫她去的（刷完回那里说，群里叫的就回群里）。"""
        log = self._browse_log
        t0 = time.time()
        end = t0 + minutes * 60
        name = browse.site_name(site)
        douyin_ = site == "douyin"
        run = {"t0": t0, "by": by, "topic": topic, "asked": topic, "where": where or umo, "source": "", "items": [],
               "shown": 0, "site": site}
        if self._browse_next:  # 还没开始看，兄长就又点名了别的
            run["switch_to"] = self._browse_next["topic"]
        log.data["running"] = run
        self._browse_topic, self._browse_site = topic, site
        learner = self._learner()
        cancelled = False
        try:
            if not topic and learner is not None:
                try:
                    wonder = learner.wonder_topic()
                except Exception:  # noqa: BLE001
                    wonder = None
                if wonder:  # 没说看什么：拿一件她最近想弄明白的事去搜
                    topic = run["topic"] = wonder["kw"]
                    run["wonder"] = wonder["q"]
                    self.log.info(f"kaju_basics: 刷{name}：她想弄明白「{wonder['q']}」，先搜「{wonder['kw']}」")
            if douyin_:
                cands, run["source"], miss = await douyin.browse_list(
                    self._dy_profile if self._dy_logged() else "", topic, channel=self._dy_channel())
                cands = browse.usable(cands, log.data["seen"], self._bw("max_video_minutes", 12.0) * 60, 8)[:20]
                if miss:  # 没搜成（要验证 / 没结果）：刷的是精选，挑的时候也别再按那个词挑
                    run["miss"] = miss
                    self.log.info(f"kaju_basics: 刷抖音：{miss}，改刷精选")
                    topic = ""
                if self._dy_logged() and run["source"].endswith(douyin.SRC_NOT_LOGGED):
                    self._dy_gone("刷抖音时浏览器里没有登录")
            else:
                cands, run["source"] = await self._browse_candidates(topic)
            if not cands:
                self.log.info(f"kaju_basics: 刷{name}：没刷出能看的视频")
                return
            heart = self._heart()
            tastes = ""
            if heart is not None and hasattr(heart, "taste_list"):
                try:
                    tastes = heart.taste_list() or ""
                except Exception:  # noqa: BLE001
                    tastes = ""
            picks = await self._browse_pick(cands, tastes, topic, umo, "" if run.get("miss") else run.get("wonder", ""), site)
            self.log.info(f"kaju_basics: 刷{name}（{run['source']}，{len(cands)} 个里挑了 {len(picks)} 个）："
                        + "；".join(f"《{v['title']}》{v['why']}" for v in picks))
            quiet = _QuietEvent(umo)
            seen_text: dict[str, str] = {}
            for v in picks:
                # 有人在跟她说话：先别开下一个视频（看视频和她回话抢同一块显卡），等聊天停一会儿
                pause, waited = self._bw("pause_seconds", 20.0), 0.0
                while pause > 0 and time.time() - self._chat_seen < pause and waited < 120 and time.time() < end:
                    await asyncio.sleep(5)
                    waited += 5
                if waited:
                    self.log.info(f"kaju_basics: 刷{name}：有人在跟她说话，等了 {waited:.0f} 秒再看下一个")
                if self._browse_next:
                    run["switched"] = self._browse_next["topic"]
                    self.log.info(f"kaju_basics: 刷{name}：换去找「{run['switched']}」，这次先看到这儿")
                    break
                if time.time() > end:
                    self.log.info(f"kaju_basics: 刷{name}：时间到了，不看了")
                    break
                if douyin_:
                    info, text = await self._describer.douyin_video(v["url"], quiet)
                else:
                    info, text = await self._describer.bili_video(v["url"], quiet)
                log.data["seen"][v["bvid"]] = time.time()
                try:  # 自己刷到的感受下面交给 feel_browsed；这里把感官里记的那份取走，免得算到下一轮聊天头上
                    self._describer.senses.take_felt(umo)
                except Exception:  # noqa: BLE001
                    pass
                if info is None:
                    self.log.info(f"kaju_basics: 刷{name}：《{v['title']}》{text}")
                    continue
                item = {"bvid": v["bvid"], "title": info.get("title") or v["title"],
                        "up": info.get("author" if douyin_ else "up") or v["up"], "why": v.get("why", ""),
                        "url": v["url"], "site": site}
                seen_text[v["bvid"]] = text
                feel = None
                if heart is not None:
                    try:
                        feel = await heart.feel_browsed({**item, "seen": text}, umo)
                    except Exception as e:  # noqa: BLE001
                        self.log.warning(f"kaju_basics: 刷到的视频交给心情插件出错 {type(e).__name__}: {e}")
                if feel:
                    item.update(emo=feel.get("emotion", ""), i=int(feel.get("intensity", 0)),
                                voice=feel.get("voice", ""), share=bool(feel.get("share")))
                if learner is not None:  # 不只留感受：视频讲到的东西也学进她懂的东西里
                    try:
                        felt = f"她看完的感受：{feel.get('emotion', '')}；心里想的：{feel.get('voice', '')}" if feel else ""
                        await learner.learn_content(
                            kind=f"{name}视频", title=item["title"], content=text, how=f"自己刷{name}看到的", who="视频里",
                            chat=f"p{umo.rsplit(':', 1)[-1]}",
                            meta=f"{'作者' if douyin_ else 'UP主'}：{item['up']}；她为什么点开：{item['why']}",
                            extra=felt, key=("douyin:" + v["aid"]) if douyin_ else ("bili:" + v["bvid"]))
                    except Exception as e:  # noqa: BLE001
                        self.log.warning(f"kaju_basics: 刷到的视频交给学东西插件出错 {type(e).__name__}: {e}")
                run["items"].append(item)
                log.save()
            if not run.get("switched"):  # 换去看兄长点名的了：等那次看完一起说
                await self._maybe_share(run, umo, seen_text)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_basics: 刷{name}出错 {type(e).__name__}: {e}")
        finally:
            run["t1"] = time.time()
            log.data.pop("running", None)
            log.data["sessions"].append(run)
            log.prune(time.time())
            log.save()
            self.log.info(f"kaju_basics: 刷完{name}，看了 {len(run['items'])} 个（{(run['t1'] - t0) / 60:.1f} 分钟）")
            nxt, self._browse_next = self._browse_next, None
            if nxt and not cancelled:  # 兄长又点名的：接着去找那个
                self._browsing = asyncio.create_task(
                    self._browse(nxt["umo"], nxt["minutes"], nxt["topic"], nxt["by"], nxt["where"], nxt.get("site", "bili")))

    async def _browse_candidates(self, topic: str) -> tuple[list[dict], str]:
        """刷出一页能看的视频：说了想看什么先搜；然后首页推荐（翻几页）；都不行看热门。"""
        seen = self._browse_log.data["seen"]
        longest = self._bw("max_video_minutes", 12.0) * 60
        store = self._login
        async with self._http() as s:
            await bililogin.ensure_device(s, store)
            mixin = bililogin.mixin_key(*bililogin.wbi_keys(await bililogin.nav(s, store)))
            store.save()
            if topic:
                try:
                    data, _ = await bililogin.api_json(
                        s, "GET", bililogin.API + "/x/web-interface/wbi/search/type", store.header(),
                        params=bililogin.wbi_sign({"search_type": "video", "keyword": topic, "page": 1}, mixin))
                    found = browse.usable(browse.parse_search(data), seen, longest)
                    if found:
                        return found[:20], f"搜「{topic}」"
                except Exception as e:  # noqa: BLE001
                    self.log.info(f"kaju_basics: 刷B站：搜「{topic}」没成 {type(e).__name__}: {e}")
            found = []
            for page in range(1, 4):
                try:
                    data, _ = await bililogin.api_json(
                        s, "GET", bililogin.API + "/x/web-interface/wbi/index/top/feed/rcmd", store.header(),
                        params=bililogin.wbi_sign({"fresh_type": 4, "ps": 20, "fresh_idx": page, "fresh_idx_1h": page,
                                                   "brush": page, "web_location": 1430650}, mixin))
                except Exception as e:  # noqa: BLE001
                    self.log.info(f"kaju_basics: 刷B站：首页推荐没刷出来 {type(e).__name__}: {e}")
                    break
                found = browse.usable(found + browse.parse_rcmd(data), seen, longest)
                if len(found) >= 10:
                    break
            if found:
                return found[:20], "首页推荐" + ("（小号）" if store.logged_in else "（没登录）")
            data, _ = await bililogin.api_json(s, "GET", bililogin.API + "/x/web-interface/popular", store.header(),
                                               params={"ps": 30, "pn": 1})
            return browse.usable(browse.parse_popular(data), seen, longest)[:20], "热门"

    async def _browse_pick(self, cands: list[dict], tastes: str, topic: str, umo: str, wonder: str = "",
                           site: str = "bili") -> list[dict]:
        n = max(1, self._bw("max_videos", 4))
        pid = await slot_model(self.body, "utils", str(self._bw("provider_id", "")).strip(), who=umo)  # 每项工作一格（kaju_core/slots.py）
        if not pid:
            self.log.warning("kaju_basics: 刷B站：没有可用的模型来挑视频")
            return []
        try:
            out = await self.body.generate(pid, browse.pick_prompt(cands, n, tastes, topic, wonder, site),
                                           browse.pick_system(site), timeout=90)
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_basics: 刷B站：挑视频没成 {type(e).__name__}: {e}")
            return []
        return browse.parse_pick(out or "", cands, n)

    async def _maybe_share(self, run: dict, umo: str, seen_text: dict) -> None:
        """刷完跟兄长说一声：挑她特别想说的那个（没有就挑印象最深的，report 开着时）主动私聊一两句 + 链接。
        每天最多 share_per_day 次，夜里不发，他正在跟她聊就不另外发（聊天提示里有）。"""
        log = self._browse_log
        if not self._bw("share", True):
            return
        asked = str(run.get("asked") or "")
        item, wanted = browse.pick_report(run["items"], self._bw("share_min_intensity", 2), must=bool(asked))
        if item is None or (not wanted and not self._bw("report", True)):
            return
        now = time.time()
        tz = self._tz()
        today = browse.life_day(now, tz)
        done = [t for t in log.data.get("shares", []) if browse.life_day(float(t), tz) == today]
        if len(done) >= self._bw("share_per_day", 5) and not asked:
            self.log.info(f"kaju_basics: 刷到《{item['title']}》想说，但不主动发：今天已经主动说过了")
            return
        site = run.get("site") or "bili"
        name = browse.site_name(site)
        link = (item.get("url") or f"https://www.bilibili.com/video/{item['bvid']}") if self._bw("share_link", True) else ""
        where = str(run.get("where") or umo)
        ok, text = await self.say_to_owner(
            browse.share_prompt(item, seen_text.get(item["bvid"], ""), wanted=wanted, asked=asked,
                                in_group=":GroupMessage:" in where, site=site, miss=str(run.get("miss") or "")),
            said=f"（佳树刚自己刷到{name}视频《{item['title']}》，主动跟兄长大人说）",
            record=browse.SHARE_RECORD.format(site=name, title=item["title"]), link=link, umo=where)
        if not ok:
            self.log.info(f"kaju_basics: 刷到《{item['title']}》想说，但没主动发：{text}")
            return
        item["shared"] = True
        log.data.setdefault("shares", []).append(now)
        log.data["shares"] = log.data["shares"][-20:]
        log.save()
        self.log.info(f"kaju_basics: 刷到《{item['title']}》，主动跟兄长说了（{'群里' if ':GroupMessage:' in where else '私聊'}）："
                    f"{text.replace(chr(10), ' / ')}")
