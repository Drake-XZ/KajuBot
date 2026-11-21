"""线上重说记录（2026-11-07，借鉴 MaiBot 的"回复效果记录"）：每一次重说都原样记下来。

为什么（2026-11-07 起；那时是本地写手照要点卡写，11-21 删了）：训练和线上看到的东西
要是一回事。MaiBot 的经验也是"线上输入必须和训练分布对齐"。把线上真实的输入（上下文、大脑的指导、回复器的
提示）和输出（回复器写的、核对结论、最后发出去的）都记下来，以后出盲选题、让兄长大人改写、攒训练数据，
都用这份和线上一模一样的材料。

- 记在 kaju_data\\self\\kaju_style\\rewrites\\日期.jsonl，一次重说一行；超过 rewrite.record_days（60）天的删掉。
- 不改重说的任何行为：只在外面包一层，把核对的输入输出顺手记下（回复器、大脑、再想一遍由 mind.py 自己 note）；记录本身出错只打日志。
- 主回复（rewrite_reply 外面那层调用 begin/end）和插件主动发的话（polish）都记。
- 2026-11-11 起每条多记一栏 mood：开始重说那一刻 kaju_heart 的原始读数（HeartMind.mood_snapshot）。
- 2026-11-13 起主回复多记“草稿是照什么写的”（兄长：加日志）：主模型这一轮收到的完整输入（系统提示、本轮消息、历史、
  图片 / 工具个数），存在旁边的 draft_inputs\\日期.jsonl（一轮一行，用 t 对上；太大，不放进 rewrites）；rewrites 那行只记
  draft_input = {字数、这一轮加了哪些【…】提醒、sha}。以后改草稿那一步的提示，就能拿真实的输入回放、盲选。
  读的是 AstrBot 放在 event 上的 provider_request（所有插件改完、最后挪动之后的那份）。开关 rewrite.record_draft_input。
"""

import contextvars
import datetime as dt
import functools
import hashlib
import json
import os
import re
import time

NOTE_TITLE = re.compile(r"【([^】\n]{1,30})】")

_CUR: contextvars.ContextVar = contextvars.ContextVar("kaju_style_rewrite_record", default=None)


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def outcome(rec: dict) -> str:
    """一次重说的结局：skipped（没走回复器）/ writer_error（回复器一句没写成）/ unusable（写出来不像回复或一样）/
    guard_rejected / guard_error / used（换上了）。"""
    if rec.get("used"):
        return "used"
    tries = rec.get("replyer") or []
    if not tries:
        return "skipped"
    if not any(w.get("text") for w in tries) and any(w.get("errors") for w in tries):
        return "writer_error"
    g = rec.get("guard") or []
    if g and g[-1].get("error"):
        return "guard_error"
    if g and g[-1].get("bad"):
        return "guard_rejected"
    return "unusable"


class Recorder:
    def __init__(self, star, folder: str, tz):
        self.star = star
        self.folder = folder
        self.tz = tz
        self._pruned = ""

    # ---------------------------------------------------------------- config
    def _cfg(self) -> dict:
        try:
            return self.star._sec("rewrite")
        except Exception:  # noqa: BLE001
            return {}

    def on(self) -> bool:
        return bool(self._cfg().get("record", True))

    # ---------------------------------------------------------------- one rewrite
    def begin(self, src: str, event=None, resp=None, **extra) -> dict | None:
        """src = reply（主回复）/ polish（插件主动发的话）。主回复只在这一轮真要重说时记（和 rewrite_reply 的入口条件一样）。"""
        if not self.on():
            return None
        try:
            rec = {"t": round(time.time(), 1), "src": src}
            if event is not None:
                ctx = event.get_extra("_ks_rw_ctx")
                if not ctx or getattr(resp, "tools_call_name", None):
                    return None
                rec.update(umo=str(getattr(event, "unified_msg_origin", "") or ""),
                           kind="群聊" if event.get_group_id() else "私聊",
                           title=event.get_extra("_ks_rw_title") or "", said=event.message_str or "",
                           ctx=list(ctx), draft=getattr(resp, "completion_text", "") or "")
                if self._cfg().get("record_draft_input", True):
                    snap = self._draft_input(event)
                    if snap:
                        rec["_draft_in"] = snap
            rec.update(extra)
            cfg = self._cfg()
            rec["config"] = {k: cfg.get(k) for k in ("replyer_models", "guard", "guard_provider_id")
                             if cfg.get(k) is not None}
            rec["guard"] = []
            mood = self._mood()
            if mood is not None:
                rec["mood"] = mood
            rec["_token"] = _CUR.set(rec)
            rec["_t0"] = time.time()
            return rec
        except Exception as e:  # noqa: BLE001
            self._warn(f"begin {type(e).__name__}: {e}")
            return None

    def _mood(self) -> dict | None:
        """这一刻她的心情读数（2026-11-11 起记）：以后教写手"心情怎么影响说话"要用，没有这份记录就没数据可训。
        心情那部分不在、或者读的时候出错，就不记这一栏，不影响重说。"""
        try:
            from kaju_core import parts
            h = parts.find("mood_snapshot")
            return h.mood_snapshot() if h is not None else None
        except Exception as e:  # noqa: BLE001
            self._warn(f"mood {type(e).__name__}: {e}")
            return None

    @staticmethod
    def _text(v) -> str:
        """content 可能是字符串，也可能是 [{type, text, ...}] 这种分段；图片只记个占位。"""
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            out = []
            for p in v:
                if isinstance(p, dict):
                    out.append(str(p.get("text") or "") if p.get("type", "text") == "text" else f"[{p.get('type')}]")
                else:
                    out.append(str(getattr(p, "text", "") or ""))
            return "".join(out)
        return "" if v is None else str(v)

    def _draft_input(self, event) -> dict | None:
        """主模型这一轮收到的完整输入（读不到、出错就不记，不影响重说）。"""
        try:
            # kaju_style 在请求钩子最后记下的那份（插话那条路 event 上的 provider_request 是插件发起时那份，没系统提示、没历史）
            req = event.get_extra("_ks_draft_req") or event.get_extra("provider_request")
            if req is None or not hasattr(req, "system_prompt"):
                return None
            hist = [{"role": str(m.get("role") or ""), "text": self._text(m.get("content"))}
                    for m in (getattr(req, "contexts", None) or []) if isinstance(m, dict)]
            extra = [str(getattr(p, "text", "") or "") for p in (getattr(req, "extra_user_content_parts", None) or [])]
            tools = getattr(req, "func_tool", None)
            names = []
            try:
                names = sorted(str(getattr(t, "name", "")) for t in (getattr(tools, "tools", None) or []))
            except Exception:  # noqa: BLE001
                names = []
            snap = {"system_prompt": str(req.system_prompt or ""), "prompt": str(getattr(req, "prompt", "") or ""),
                    "extra": extra, "contexts": hist, "images": len(getattr(req, "image_urls", None) or []),
                    "tools": names, "model": str(getattr(req, "model", "") or "")}
            whole = snap["system_prompt"] + "\n" + snap["prompt"] + "\n" + "\n".join(extra)
            snap["_meta"] = {"chars": len(whole) + sum(len(h["text"]) for h in hist),
                             "notes": list(dict.fromkeys(NOTE_TITLE.findall(whole))), "sha": _sha(whole)}
            return snap
        except Exception as e:  # noqa: BLE001
            self._warn(f"draft_input {type(e).__name__}: {e}")
            return None

    def end(self, rec: dict | None, final: str = "", used: bool | None = None) -> None:
        if rec is None:
            return
        try:
            _CUR.reset(rec.pop("_token"))
        except Exception:  # noqa: BLE001
            pass
        snap = None
        try:
            snap = rec.pop("_draft_in", None)
            if snap:
                rec["draft_input"] = snap.pop("_meta")
                self._write_draft_input(rec["t"], snap)
        except Exception as e:  # noqa: BLE001
            self._warn(f"draft_input {type(e).__name__}: {e}")
        try:
            rec["ms"] = int((time.time() - rec.pop("_t0", time.time())) * 1000)
            rec["final"] = final
            rec["used"] = bool(used) if used is not None else bool(final) and final.strip() != (rec.get("draft") or "").strip()
            rec["outcome"] = outcome(rec)
            self._write(rec)
        except Exception as e:  # noqa: BLE001
            self._warn(f"end {type(e).__name__}: {e}")
            return
        # 影子规划器（11-14 shadow.py，11-18 关）11-20 删了：大脑模式让主模型自己出指导，用不上了

    def note(self, key: str, item: dict) -> None:
        rec = _CUR.get()
        if rec is not None:
            rec.setdefault(key, []).append(item)

    # ---------------------------------------------------------------- wrap helpers
    def install(self) -> None:
        """把核对 / polish 包一层（只包存在的）；不改它们的返回值和异常。"""
        st = self.star

        def wrap(name, before, after):
            fn = getattr(st, name, None)
            if fn is None or getattr(fn, "_kaju_rec", False):
                return

            @functools.wraps(fn)
            async def inner(*a, **k):
                info = before(*a, **k)
                t = time.time()
                try:
                    out = await fn(*a, **k)
                except Exception as e:
                    info.update(error=f"{type(e).__name__}: {e}"[:200], ms=int((time.time() - t) * 1000))
                    self.note(after, info)
                    raise
                info["ms"] = int((time.time() - t) * 1000)
                self.note(after, self._result(after, info, out))
                return out
            setattr(inner, "_kaju_rec", True)
            setattr(st, name, inner)

        wrap("_guard", lambda said, draft, new, title="", ctx=None, **k: {"new": new}, "guard")

        fn = getattr(st, "polish", None)
        if fn is not None and not getattr(fn, "_kaju_rec", False):
            @functools.wraps(fn)
            async def polish(draft, ctx=None, said="", *a, **k):
                rec = self.begin("polish", ctx=list(ctx or []), draft=draft or "", said=said or "",
                                 kind=k.get("kind") or "私聊", title=k.get("title") or (a[0] if a else "兄长大人"))
                out = ""
                try:
                    out = await fn(draft, ctx, said, *a, **k)
                    return out
                finally:
                    used = bool(rec) and any(w.get("text") for w in rec.get("replyer") or []) and \
                        not (rec.get("guard") and rec["guard"][-1].get("bad"))
                    self.end(rec, out, used=used and bool(out))
            setattr(polish, "_kaju_rec", True)
            st.polish = polish

    @staticmethod
    def _result(after: str, info: dict, out) -> dict:
        if after == "guard":
            out = tuple(out) if isinstance(out, (tuple, list)) else (out,)
            info["bad"] = bool(out[0]) if out else None
            info["why"] = str(out[1]) if len(out) > 1 else ""
            if len(out) > 2:
                info["opener_ok"] = bool(out[2])
        return info

    # ---------------------------------------------------------------- file
    def _draft_folder(self) -> str:
        return os.path.join(os.path.dirname(self.folder.rstrip("\\/")), "draft_inputs")

    def _write_draft_input(self, t: float, snap: dict) -> None:
        folder = self._draft_folder()
        os.makedirs(folder, exist_ok=True)
        day = dt.datetime.fromtimestamp(t, self.tz).strftime("%Y-%m-%d")
        with open(os.path.join(folder, day + ".jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": t, **snap}, ensure_ascii=False, default=str) + "\n")

    def _write(self, rec: dict) -> None:
        os.makedirs(self.folder, exist_ok=True)
        day = dt.datetime.fromtimestamp(rec["t"], self.tz).strftime("%Y-%m-%d")
        with open(os.path.join(self.folder, day + ".jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if self._pruned != day:
            self._pruned = day
            self._prune(day)

    def _prune(self, today: str) -> None:
        try:
            keep = int(self._cfg().get("record_days", 60) or 60)
        except (TypeError, ValueError):
            keep = 60
        cut = (dt.date.fromisoformat(today) - dt.timedelta(days=keep)).isoformat()
        for folder in (self.folder, self._draft_folder()):
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                if name.endswith(".jsonl") and name[:-6] < cut:
                    try:
                        os.remove(os.path.join(folder, name))
                    except OSError:
                        pass

    def _warn(self, msg: str) -> None:
        try:
            self.star.log.warning(f"kaju_style: 重说记录出错（不影响回复） {msg}")
        except Exception:  # noqa: BLE001
            pass
