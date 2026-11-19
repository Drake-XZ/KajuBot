r"""佳树人格的读写工具（给控制台「人格微调」窗口用，也能单独在命令行跑）。只用标准库。

人格的正本在 kaju_data\self\persona\（2026-11-13 起，不属于哪个聊天平台，也不属于 AstrBot）：
    persona.json          下面四样（加 skills）
    persona.txt           人设正文，方便直接看
    system_prompt         人设正文（每次回复前都会给模型看）
    begin_dialogs         示例对话，["兄长大人说", "佳树回", "兄长大人说", "佳树回", ...]
    tools                 她能用的工具；null = 全部（包括以后新装的），[] = 一个都不能用
    custom_error_message  模型请求彻底失败时直接发出去的话
AstrBot 数据库 data_v4.db 的 personas 表（persona_id = default）里那份是给 AstrBot 用的副本：save 两边一起写。
（skills 控制台不改，原样保留）
另外一样不在数据库里：
    self_facts            「关于自己」清单（2026-11-07 起人设只留两句身份，她是谁的细节放这里），
                          kaju_data\self\kaju_life\self_facts.json，[{"fact": "佳树……", "kind": "家人"}, ...]；
                          kaju_life 每轮按文件修改时间自动重读，在线离线都直接改文件

机器人在线：走 AstrBot 接口（PUT /api/v1/personas/default），立刻生效。
机器人离线：直接改数据库，下次启动生效。
每次保存前，先把当前版本备份到 D:\JiashuBot\_backup\persona\。

用法（输入输出都走 UTF-8 文件，避免控制台编码问题）:
    python persona.py get     --out 结果.json              读当前人格 + 可用工具列表
    python persona.py save    --in 新人格.json --out 结果.json   保存（只改 json 里出现的字段）
    python persona.py history --out 结果.json              列出备份
    python persona.py show    <备份文件名> --out 结果.json   读一个备份的内容
    python persona.py export  --out 结果.json              AstrBot 里的 → 正本（在 AstrBot 面板里直接改过人格之后）
    python persona.py sync    --out 结果.json              正本 → AstrBot（重装 AstrBot、换平台、手改了正本之后）
不写 --out 就打印到标准输出。结果都是 {"ok": true/false, ...}，出错时有 "error"。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

SETUP = Path(__file__).resolve().parent.parent
CORE = Path(r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core")
DB = CORE / "data" / "data_v4.db"
PLUGINS = CORE / "data" / "plugins"
BACKUP = Path(r"D:\JiashuBot\_backup\persona")
DATA = Path(os.environ.get("KAJU_DATA") or r"D:\JiashuBot\kaju_data")
MASTER = DATA / "self" / "persona"  # 正本：persona.json + persona.txt
FACTS = DATA / "self" / "kaju_life" / "self_facts.json"
FACTS_SEED = SETUP / "kaju_core" / "life" / "self_facts_seed.json"
BASE = "http://127.0.0.1:6185"
PERSONA_ID = "default"
DB_FIELDS = ("system_prompt", "begin_dialogs", "tools", "custom_error_message")
FIELDS = (*DB_FIELDS, "self_facts")
KEEP_BACKUPS = 200

# 测试用：设了 PERSONA_TEST_DIR 就只动那个目录里的数据库副本，当作机器人离线
TEST_DIR = os.environ.get("PERSONA_TEST_DIR")
if TEST_DIR:
    DB = Path(TEST_DIR) / "data_v4.db"
    BACKUP = Path(TEST_DIR) / "backup"
    MASTER = Path(TEST_DIR) / "master"
    FACTS = Path(TEST_DIR) / "self_facts.json"


class PersonaError(Exception):
    pass


# ---------------------------------------------------------------- AstrBot 接口
def _password() -> str:
    panel = (SETUP / "bot-panel.ps1").read_text(encoding="utf-8-sig")
    m = re.search(r"^\$Pass\s*=\s*'([^']*)'", panel, re.M)
    if not m:
        raise PersonaError("bot-panel.ps1 里找不到 $Pass")
    return m[1]


class Api:
    def __init__(self) -> None:
        self.token = ""
        login = self.call("POST", "/api/auth/login", {"username": "astrbot", "password": _password()})
        if not isinstance(login, dict) or not login.get("token"):
            raise PersonaError("登录 AstrBot 失败")
        self.token = login["token"]

    def call(self, method: str, path: str, body: dict | None = None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = urllib.request.Request(BASE + path, data, headers, method=method)
        try:
            raw = urllib.request.urlopen(req, timeout=30).read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                msg = json.loads(raw).get("message") or raw.decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                msg = raw.decode("utf-8", "replace")
            raise PersonaError(f"AstrBot 拒绝了请求（{e.code}）：{msg}") from e
        res = json.loads(raw)
        if isinstance(res, dict) and res.get("status") not in (None, "ok"):
            raise PersonaError(f"AstrBot 返回错误：{res.get('message')}")
        return res.get("data") if isinstance(res, dict) and "data" in res else res


def online() -> bool:
    if TEST_DIR:
        return False
    try:
        urllib.request.urlopen(BASE, timeout=3)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- 数据库
def _db() -> sqlite3.Connection:
    if not DB.exists():
        raise PersonaError(f"找不到数据库：{DB}")
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _load_json(v):
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return None


def db_read() -> dict:
    with _db() as con:
        row = con.execute("select * from personas where persona_id = ?", (PERSONA_ID,)).fetchone()
    if not row:
        raise PersonaError(f"数据库里没有人格 {PERSONA_ID}")
    return {
        "system_prompt": row["system_prompt"] or "",
        "begin_dialogs": _load_json(row["begin_dialogs"]) or [],
        "tools": _load_json(row["tools"]),
        "skills": _load_json(row["skills"]),
        "custom_error_message": row["custom_error_message"],
        "updated_at": row["updated_at"],
    }


def db_write(changes: dict) -> None:
    sets, args = [], []
    for k, v in changes.items():
        sets.append(f"{k} = ?")
        args.append(json.dumps(v, ensure_ascii=False) if k in ("begin_dialogs", "tools") and v is not None else v)
    sets.append("updated_at = ?")
    args.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"))
    with _db() as con:
        cur = con.execute(f"update personas set {', '.join(sets)} where persona_id = ?", (*args, PERSONA_ID))
        if cur.rowcount != 1:
            raise PersonaError(f"数据库里没有人格 {PERSONA_ID}")


# ---------------------------------------------------------------- 关于自己
def _clean_facts(rows) -> list[dict]:
    out = []
    for r in rows or []:
        if isinstance(r, str):
            r = {"fact": r}
        if not isinstance(r, dict):
            continue
        fact = " ".join(str(r.get("fact") or "").split())
        if fact:
            out.append({"fact": fact, "kind": " ".join(str(r.get("kind") or "").split())})
    return out


def facts_read() -> list[dict]:
    path = FACTS if FACTS.exists() else FACTS_SEED  # 插件第一次启用前，文件还没从种子复制过来
    if not path.exists():
        return []
    try:
        return _clean_facts(json.loads(path.read_text(encoding="utf-8-sig")))
    except ValueError as e:
        raise PersonaError(f"「关于自己」文件不是合法的 JSON：{path}（{e}）") from e


def facts_write(rows: list[dict]) -> None:
    FACTS.parent.mkdir(parents=True, exist_ok=True)
    tmp = FACTS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, FACTS)  # 插件按修改时间重读，整份换掉，不会读到写了一半的


# ---------------------------------------------------------------- 读
def _normalize(p: dict) -> dict:
    return {
        "system_prompt": p.get("system_prompt") or "",
        "begin_dialogs": [str(x) for x in (p.get("begin_dialogs") or [])],
        "tools": None if p.get("tools") is None else [str(x) for x in p["tools"]],
        "skills": p.get("skills"),
        "custom_error_message": p.get("custom_error_message") or "",
        "self_facts": None if p.get("self_facts") is None else _clean_facts(p["self_facts"]),
        "updated_at": p.get("updated_at"),
    }


def _offline_tools() -> list[dict]:
    """离线时没法问 AstrBot，就用上次在线时缓存的列表，再补上插件源码里能找到的工具名。"""
    tools: dict[str, dict] = {}
    cache = BACKUP / "tools-cache.json"
    if cache.exists():
        try:
            for t in json.loads(cache.read_text(encoding="utf-8")):
                tools[t["name"]] = t
        except Exception:  # noqa: BLE001
            pass
    if PLUGINS.exists():
        for py in PLUGINS.glob("*/*.py"):
            try:
                text = py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for name in re.findall(r"llm_tool\(\s*name\s*=\s*[\"']([^\"']+)", text):
                tools.setdefault(name, {"name": name, "description": "", "origin": "plugin",
                                        "origin_name": py.parent.name, "active": True})
    return sorted(tools.values(), key=lambda t: (t.get("origin") != "plugin", t.get("origin_name") or "", t["name"]))


def _api_tools(api: Api) -> list[dict]:
    out = []
    for t in api.call("GET", "/api/v1/tools") or []:
        out.append({
            "name": t.get("name"),
            "description": (t.get("description") or "").strip(),
            "origin": t.get("origin"),
            "origin_name": t.get("origin_display_name") or t.get("origin_name"),
            "active": bool(t.get("active", True)),
        })
    out.sort(key=lambda t: (t.get("origin") != "plugin", t.get("origin_name") or "", t["name"] or ""))
    try:
        BACKUP.mkdir(parents=True, exist_ok=True)
        (BACKUP / "tools-cache.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return out


def _api_persona(api: Api) -> dict:
    p = api.call("GET", f"/api/v1/personas/{PERSONA_ID}")
    if isinstance(p, dict) and isinstance(p.get("persona"), dict):
        p = p["persona"]
    if not isinstance(p, dict) or "system_prompt" not in p:
        raise PersonaError(f"AstrBot 返回的人格看不懂：{str(p)[:200]}")
    return _normalize({**p, "self_facts": facts_read()})


def _db_persona() -> dict:
    return _normalize({**db_read(), "self_facts": facts_read()})


def cmd_get() -> dict:
    if online():
        api = Api()
        return {"ok": True, "online": True, "persona": _api_persona(api), "tools": _api_tools(api), "master": str(MASTER)}
    return {"ok": True, "online": False, "persona": _db_persona(), "tools": _offline_tools(), "master": str(MASTER)}


# ---------------------------------------------------------------- 写
def validate(changes: dict) -> dict:
    out = {}
    for k, v in changes.items():
        if k not in FIELDS:
            continue
        if k == "system_prompt":
            v = str(v or "").replace("\r\n", "\n")
            if not v.strip():
                raise PersonaError("人设正文不能为空。")
        elif k == "begin_dialogs":
            v = [str(x).replace("\r\n", "\n") for x in (v or [])]
            if len(v) % 2:
                raise PersonaError("示例对话必须成对（一句兄长大人说的 + 一句佳树回的）。")
            if any(not x.strip() for x in v):
                raise PersonaError("示例对话里有空的格子，填上或者把那一组删掉。")
        elif k == "tools":
            v = None if v is None else sorted({str(x) for x in v if str(x).strip()})
        elif k == "custom_error_message":
            v = str(v or "").strip() or None
        elif k == "self_facts":
            if not isinstance(v, list):
                raise PersonaError("「关于自己」要是一个清单。")
            v = _clean_facts(v)
            seen = set()
            for r in v:
                if r["fact"] in seen:
                    raise PersonaError(f"「关于自己」里有两条一模一样的：{r['fact'][:30]}")
                seen.add(r["fact"])
        out[k] = v
    if not out:
        raise PersonaError("没有要保存的内容。")
    return out


def _backup(current: dict, reason: str) -> Path:
    BACKUP.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUP / f"persona-{stamp}.json"
    n = 1
    while path.exists():
        n += 1
        path = BACKUP / f"persona-{stamp}-{n}.json"
    data = {"saved_at": datetime.now().isoformat(timespec="seconds"), "reason": reason,
            "persona": {k: current.get(k) for k in (*FIELDS, "skills", "updated_at")}}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    olds = sorted(BACKUP.glob("persona-*.json"))
    for old in olds[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)
    return path


# ---------------------------------------------------------------- 正本
def master_read() -> dict | None:
    r"""kaju_data\self\persona\persona.json 里的四样（+ skills）；还没有正本返回 None。"""
    path = MASTER / "persona.json"
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise PersonaError(f"正本不是合法的 JSON：{path}（{e}）") from e
    p = _normalize(d)
    return {k: p[k] for k in (*DB_FIELDS, "skills")}


def master_write(p: dict) -> None:
    MASTER.mkdir(parents=True, exist_ok=True)
    data = {"persona_id": PERSONA_ID, "saved_at": datetime.now().isoformat(timespec="seconds"),
            **{k: p.get(k) for k in DB_FIELDS}, "skills": p.get("skills")}
    data["custom_error_message"] = data["custom_error_message"] or None
    tmp = MASTER / "persona.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, MASTER / "persona.json")
    (MASTER / "persona.txt").write_text(p.get("system_prompt") or "", encoding="utf-8")


def _current() -> tuple[dict, "Api | None"]:
    api = Api() if online() else None
    return (_api_persona(api) if api else _db_persona()), api


def cmd_save(changes: dict) -> dict:
    changes = validate(changes)
    is_online = online()
    api = Api() if is_online else None
    if api:
        current = _api_persona(api)
    else:
        current = _db_persona()

    def now(k):
        v = current.get(k)
        if k == "custom_error_message":
            return v or None
        if k == "tools" and v is not None:
            return sorted(v)
        return v

    changes = {k: v for k, v in changes.items() if v != now(k)}
    if not changes:
        if master_read() is None:
            master_write(current)
        return {"ok": True, "online": is_online, "changed": [], "backup": None, "persona": current}
    backup = _backup(current, "保存前的版本（改了：" + "、".join(changes) + "）")
    db_changes = {k: v for k, v in changes.items() if k in DB_FIELDS}
    if "self_facts" in changes:
        facts_write(changes["self_facts"])
    if db_changes:
        if api:
            api.call("PUT", f"/api/v1/personas/{PERSONA_ID}", db_changes)
        else:
            db_write(db_changes)
    after = _api_persona(api) if api else _db_persona()
    for k, v in changes.items():
        got = after.get(k)
        if k == "custom_error_message":
            got = got or None
        if k == "tools" and got is not None:
            got = sorted(got)
        if got != v:
            raise PersonaError(f"保存后核对不一致：{k}。备份在 {backup}")
    master_write(after)
    changed = [k for k in FIELDS if k in changes]
    return {"ok": True, "online": is_online, "changed": changed, "backup": str(backup), "persona": after}


def cmd_export() -> dict:
    """AstrBot 里的 → 正本（第一次建正本，或在 AstrBot 面板里直接改过人格之后）。"""
    current, api = _current()
    master_write(current)
    return {"ok": True, "online": api is not None, "master": str(MASTER), "chars": len(current["system_prompt"])}


def cmd_sync() -> dict:
    """正本 → AstrBot（重装 AstrBot、换平台、手改了正本之后）：走 save，照样先备份 AstrBot 里的旧版本。"""
    m = master_read()
    if m is None:
        raise PersonaError(f"还没有正本：{MASTER}（先跑 export）")
    res = cmd_save({k: m[k] for k in DB_FIELDS})
    res["master"] = str(MASTER)
    return res


# ---------------------------------------------------------------- 历史
def cmd_history() -> dict:
    items = []
    for p in sorted(BACKUP.glob("persona-*.json"), reverse=True) if BACKUP.exists() else []:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            per = d.get("persona", {})
            items.append({
                "file": p.name,
                "saved_at": d.get("saved_at", ""),
                "reason": d.get("reason", ""),
                "chars": len(per.get("system_prompt") or ""),
                "dialogs": len(per.get("begin_dialogs") or []) // 2,
                "tools": None if per.get("tools") is None else len(per["tools"]),
                "facts": None if per.get("self_facts") is None else len(per["self_facts"]),  # 11-07 之前的备份没有
            })
        except Exception:  # noqa: BLE001
            continue
    return {"ok": True, "items": items, "dir": str(BACKUP)}


def cmd_show(name: str) -> dict:
    path = BACKUP / Path(name).name
    if not path.exists():
        raise PersonaError(f"没有这个备份：{name}")
    d = json.loads(path.read_text(encoding="utf-8"))
    return {"ok": True, "file": path.name, "saved_at": d.get("saved_at"), "persona": _normalize(d.get("persona") or {})}


# ---------------------------------------------------------------- 入口
def main(argv: list[str]) -> int:
    out_path = None
    in_path = None
    rest = []
    it = iter(argv)
    for a in it:
        if a == "--out":
            out_path = next(it, None)
        elif a == "--in":
            in_path = next(it, None)
        else:
            rest.append(a)
    try:
        if not rest:
            raise PersonaError(__doc__)
        cmd = rest[0]
        if cmd == "get":
            res = cmd_get()
        elif cmd == "save":
            if not in_path:
                raise PersonaError("save 需要 --in 文件")
            res = cmd_save(json.loads(Path(in_path).read_text(encoding="utf-8-sig")))
        elif cmd == "history":
            res = cmd_history()
        elif cmd == "show" and len(rest) > 1:
            res = cmd_show(rest[1])
        elif cmd == "export":
            res = cmd_export()
        elif cmd == "sync":
            res = cmd_sync()
        else:
            raise PersonaError(__doc__)
    except PersonaError as e:
        res = {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
