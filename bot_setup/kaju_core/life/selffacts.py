"""关于自己（2026-11-07）：人设卡换成两句身份以后，"她是谁"靠这里——每轮按对方刚说的话，
从"关于自己"清单里想起最相关的几条，放进系统提示的【你记得的关于自己】。

- 清单在 plugin_data/astrbot_plugin_kaju_life/self_facts.json：[{"fact": "佳树……", "kind": "…"}]。
  直接改这个文件就行（加、删、改字），下一轮自动重新读；第一次启用时从 bot_setup 带的 self_facts_seed.json 复制。
  来源：原作小说提炼的 64 条，兄长大人 11-07 过目改过（去掉"温水和彦"、删同住、年级统一初三）。
- 用本机 Ollama 的 bge-m3 算向量（和 memorix 用的同一个），向量按句子缓存在 self_facts.vec.json，改了的句子才重算。
- 这一步出任何问题（Ollama 没开、超时）都只是这一轮不放，不影响回复。
"""

import hashlib
import json
import math
import os
import re
import time

import aiohttp

SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "self_facts_seed.json")
# 从经历里学到的“关于自己”（11-19，kaju_learn 每晚复盘时抽的：能做 / 做不到 / 做过 / 有的）：单独一个文件，
# 不碰兄长维护的人格正本 self_facts.json（tools\persona.py 管）；挑的时候两份一起挑。
LEARNED = "self_learned.json"
MAX_LEARNED = 40
# 只收能力和经历；性格、感情、关系、长相这些不从聊天里学
SELF_OFF = re.compile(r"喜欢|爱|恋|依恋|独占|吃醋|心动|亲密|亲昵|撒娇|黏|想念|害羞|性格|脾气|长相|身材|好感|关系")
_NEG = re.compile(r"不能|不会|没法|无法|做不到|不|没")


def _topic(text: str) -> str:
    return _NEG.sub("", re.sub(r"[\W_]", "", text or ""))


def add_learned(folder: str, items: list[dict], now: float) -> dict:
    """记进 self_learned.json。items = [{"fact": "佳树……", "kind": "能做|做不到|做过|有的", "day", "line"}]。
    同一件事（去掉“不/没/不能”后两字片段重合 ≥0.6）就换成新的说法（能 ↔ 不能 以最新的为准）。返回 {"new", "updated", "dropped"}。"""
    from kaju_core.heart.taste import bigram_overlap

    path = os.path.join(folder, LEARNED)
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
    except (OSError, json.JSONDecodeError):
        rows = []
    st = {"new": 0, "updated": 0, "dropped": 0}
    nxt = max([int(r.get("id", 0)) for r in rows] + [0]) + 1
    for it in items:
        fact = " ".join(str(it.get("fact") or "").split())[:60]
        kind = str(it.get("kind") or "").strip()
        if not fact.startswith("佳树") or kind not in ("能做", "做不到", "做过", "有的") or SELF_OFF.search(fact):
            st["dropped"] += 1
            continue
        same = next((r for r in rows if r.get("status") == "active" and bigram_overlap(_topic(r["fact"]), _topic(fact)) >= 0.6), None)
        ev = {"day": it.get("day", ""), "line": str(it.get("line", ""))[:120]}
        if same:
            same.update({"fact": fact, "kind": kind, "t": now, "n": int(same.get("n", 1)) + 1, "evidence": ev})
            st["updated"] += 1
        else:
            rows.append({"id": nxt, "fact": fact, "kind": kind, "t": now, "n": 1, "status": "active", "evidence": ev})
            nxt += 1
            st["new"] += 1
    act = sorted((r for r in rows if r.get("status") == "active"), key=lambda r: (-int(r.get("n", 1)), -float(r.get("t", 0))))
    for r in act[MAX_LEARNED:]:
        r["status"] = "dropped"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return st
HEAD = "\n\n【你记得的关于自己】（这是你自己的事，想起来了而已；用得上就自然带出来，用不上就不提）\n"


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def cosine(a, b) -> float:
    num = sum(x * y for x, y in zip(a, b))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0


def top_k(query_vec, facts: list[str], vecs: dict, k: int) -> list[str]:
    scored = [(cosine(query_vec, vecs[_key(f)]), f) for f in facts if _key(f) in vecs]
    scored.sort(key=lambda s: -s[0])
    return [f for _, f in scored[:k]]


def render(facts: list[str]) -> str:
    return HEAD + "\n".join(f"- {f}" for f in facts) if facts else ""


class SelfFacts:
    def __init__(self, folder: str, cfg):
        self.cfg = cfg  # () -> dict
        self.path = os.path.join(folder, "self_facts.json")
        self.vec_path = os.path.join(folder, "self_facts.vec.json")
        self._mtime = -1.0
        self.facts: list[str] = []
        self.vecs: dict = {}
        if not os.path.exists(self.path) and os.path.exists(SEED):
            with open(SEED, encoding="utf-8") as f, open(self.path, "w", encoding="utf-8") as g:
                g.write(f.read())
        try:
            with open(self.vec_path, encoding="utf-8") as f:
                self.vecs = json.load(f)
        except Exception:  # noqa: BLE001
            self.vecs = {}

    def _c(self, key, default):
        v = (self.cfg() or {}).get(key, default)
        return default if v in (None, "") else type(default)(v)

    def reload_if_changed(self) -> None:
        learned = os.path.join(os.path.dirname(self.path), LEARNED)
        try:
            m = os.path.getmtime(self.path)
        except OSError:
            self.facts = []
            return
        m = (m, os.path.getmtime(learned) if os.path.exists(learned) else 0.0)
        if m == self._mtime:
            return
        with open(self.path, encoding="utf-8") as f:
            rows = json.load(f)
        self.facts = [str(r["fact"]).strip() for r in rows if isinstance(r, dict) and str(r.get("fact", "")).strip()]
        try:  # 从经历里学到的（11-19）
            with open(learned, encoding="utf-8") as f:
                self.facts += [str(r["fact"]).strip() for r in json.load(f)
                               if isinstance(r, dict) and r.get("status") == "active" and str(r.get("fact", "")).strip()]
        except (OSError, json.JSONDecodeError):
            pass
        self._mtime = m

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        url = self._c("ollama_url", "http://127.0.0.1:11435").rstrip("/") + "/api/embed"
        body = {"model": self._c("model", "bge-m3"), "input": texts}
        timeout = aiohttp.ClientTimeout(total=self._c("timeout_seconds", 4.0))
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(url, json=body) as r:
                r.raise_for_status()
                return (await r.json())["embeddings"]

    async def _ensure_vectors(self) -> None:
        missing = [f for f in self.facts if _key(f) not in self.vecs]
        if not missing:
            return
        for i in range(0, len(missing), 32):
            chunk = missing[i:i + 32]
            for f, v in zip(chunk, await self._embed(chunk)):
                self.vecs[_key(f)] = v
        keep = {_key(f) for f in self.facts}
        self.vecs = {k: v for k, v in self.vecs.items() if k in keep}
        tmp = self.vec_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.vecs, f)
        os.replace(tmp, self.vec_path)

    async def note_for(self, query: str) -> tuple[str, list[str], float]:
        """(要加进系统提示的那段, 想起的几条, 用时秒)。不放时返回 ("", [], 用时)。"""
        t0 = time.time()
        query = (query or "").strip()
        if not query or not self._c("enable", True):
            return "", [], 0.0
        self.reload_if_changed()
        if not self.facts:
            return "", [], 0.0
        await self._ensure_vectors()
        q = (await self._embed([query[-300:]]))[0]
        picked = top_k(q, self.facts, self.vecs, self._c("top_k", 5))
        return render(picked), picked, time.time() - t0
