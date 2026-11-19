"""佳树表情包管理（控制台「表情包管理」窗口的后端，也能单独在命令行跑）。只用标准库。

表情包插件 meme_manager 的存法：每个包 packs/<包>/memes/<分类>/<文件>，一张图属于哪个分类就放在哪个分类目录里。
「一张图属于多个分类」= 同一个包里，几个分类目录各放一份同样的图（插件自己的 batch_copy 就是这么做的）。
这里按内容（sha256）把同一个包里的同一张图归成一项，界面上显示成一张图 + 几个分类标签。

所有改动都走插件自己的接口（机器人要开着），插件的索引、语义数据会跟着更新。
插件的删除是直接删文件，所以这里加了回收站：
    D:\\JiashuBot\\_backup\\meme-trash\\<编号>\\ 里放一份图 + meta.json（哪个包、原来在哪些分类、分类描述、删除时间）。
    恢复 = 把图按原来的分类重新传回去（分类没了会先建回来）。回收站不会自己清，要手动清空。

用法（输入输出都走 UTF-8 JSON 文件）:
    python memes.py inventory --out 结果.json        全部包、分类、图（按内容归并）、回收站
    python memes.py apply --in 操作.json --out 结果.json
操作.json = {"ops": [ {...}, ... ]}，一项一个操作（按顺序执行，出错的记下来接着做后面的）:
    {"op": "add",        "pack": 包, "cat": 分类, "paths": [本地图片路径...]}
    {"op": "set_cats",   "pack": 包, "items": [项...], "add": [分类...], "remove": [分类...]}
    {"op": "move",       "pack": 包, "items": [项...], "to": 分类}          只留在这一个分类
    {"op": "trash",      "pack": 包, "items": [项...]}                     整张图删掉（进回收站）
    {"op": "restore",    "ids": [回收站编号...]}
    {"op": "purge",      "ids": [回收站编号...]}  /  {"op": "purge_all"}     彻底删除（不能恢复）
    {"op": "cat_create", "pack": 包, "cat": 分类, "desc": 描述}
    {"op": "cat_desc",   "pack": 包, "cat": 分类, "desc": 描述}
    {"op": "cat_rename", "pack": 包, "cat": 旧名, "new": 新名}
    {"op": "cat_delete", "pack": 包, "cat": 分类}       只在这个分类里的图进回收站，其它分类里也有的图不受影响
「项」= inventory 里的一张图：{"cats": {分类: 文件名, ...}}（多传的字段不管）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

SETUP = Path(__file__).resolve().parent.parent
ROOT = Path(r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core\data\plugin_data\meme_manager")
TRASH = Path(r"D:\JiashuBot\_backup\meme-trash")
HASH_CACHE = Path(tempfile.gettempdir()) / "jiashu-meme-hashes.json"
BASE = "http://127.0.0.1:6185"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
PRIMARY = "kaju_memes"

# 测试用：设了 MEMES_TEST_DIR 就只动那个目录（ROOT = 目录/meme_manager，回收站 = 目录/trash）
if os.environ.get("MEMES_TEST_DIR"):
    _t = Path(os.environ["MEMES_TEST_DIR"])
    ROOT, TRASH, HASH_CACHE = _t / "meme_manager", _t / "trash", _t / "hashes.json"
if os.environ.get("MEMES_TEST_BASE"):
    BASE = os.environ["MEMES_TEST_BASE"]


class MemeError(Exception):
    pass


def safe_cat(name: str) -> bool:
    """和插件 is_safe_category_name 一样：单个目录段，首尾无空格。"""
    return bool(name) and name == name.strip() and name not in (".", "..") and "/" not in name and "\\" not in name


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- 插件接口
class Api:
    def __init__(self) -> None:
        self.token = ""
        if not online():
            raise MemeError("机器人没开：改表情包要通过表情包插件，先在控制台启动机器人。")
        status, body = self.call("POST", "/api/auth/login", {"username": "astrbot", "password": _password()})
        token = (body.get("data") or {}).get("token") if isinstance(body, dict) else None
        if status != 200 or not token:
            raise MemeError(f"登录 AstrBot 失败：{status} {body}")
        self.token = token

    def call(self, method: str, path: str, body: dict | None = None, raw: bytes | None = None,
             ctype: str = "application/json") -> tuple[int, dict]:
        headers = {"Content-Type": ctype}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = raw if raw is not None else (json.dumps(body, ensure_ascii=False).encode() if body is not None else None)
        req = urllib.request.Request(BASE + path, data, headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=120)
            status, text = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, text = e.code, e.read()
        try:
            obj = json.loads(text)
        except ValueError:
            obj = {"message": text.decode("utf-8", "replace")[:300]}
        return status, obj if isinstance(obj, dict) else {"data": obj}

    def plug(self, route: str, body: dict) -> dict:
        status, obj = self.call("POST", "/api/plug/meme_manager/" + route, body)
        if status != 200:
            raise MemeError(f"{route}：{status} {obj.get('message', '')}")
        return obj

    def upload(self, pack: str, cat: str, path: Path) -> str:
        """传一张图到 pack/cat。返回 'ok' / 'dup'（这个分类里已经有一模一样的）。"""
        name = path.name if re.fullmatch(r"[\x20-\x7e]+", path.name) else "upload" + path.suffix.lower()
        boundary = uuid.uuid4().hex
        raw = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
               f"Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        route = f"/api/plug/meme_manager/emoji/add/{urllib.parse.quote(pack, safe='')}/{urllib.parse.quote(cat, safe='')}"
        status, obj = self.call("POST", route, raw=raw, ctype=f"multipart/form-data; boundary={boundary}")
        if status == 201:
            return "ok"
        if status == 409 and obj.get("code") == "duplicate_emoji":
            return "dup"
        raise MemeError(f"上传 {path.name} 到「{cat}」失败：{status} {obj.get('message', '')}")


def _password() -> str:
    panel = (SETUP / "bot-panel.ps1").read_text(encoding="utf-8-sig")
    m = re.search(r"^\$Pass\s*=\s*'([^']*)'", panel, re.M)
    if not m:
        raise MemeError("bot-panel.ps1 里找不到 $Pass")
    return m[1]


def online() -> bool:
    try:
        urllib.request.urlopen(BASE, timeout=3)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- 读
def pack_mapping(pack_dir: Path) -> dict[str, str]:
    """分类 → 描述，和插件 load_pack_category_mapping 一样：先 memes_data.json，空的话看 manifest.json。"""
    data = _read_json(pack_dir / "memes_data.json")
    mapping = {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    if not mapping:
        man = _read_json(pack_dir / "manifest.json") or {}
        for k, v in (man.get("categories") or {}).items():
            mapping[str(k)] = v if isinstance(v, str) else str((v or {}).get("description") or "请添加描述")
    return {k: v for k, v in mapping.items() if safe_cat(k) and k != "needs_review"}


class Hasher:
    def __init__(self) -> None:
        self.cache = _read_json(HASH_CACHE) or {}
        self.dirty = False

    def __call__(self, path: Path) -> str:
        st = path.stat()
        key = str(path)
        hit = self.cache.get(key)
        if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
            return hit[2]
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        self.cache[key] = [st.st_size, st.st_mtime_ns, h]
        self.dirty = True
        return h

    def save(self) -> None:
        if self.dirty:
            try:
                HASH_CACHE.write_text(json.dumps(self.cache), encoding="utf-8")
            except OSError:
                pass


def read_pack(pack_id: str, hasher: Hasher) -> dict:
    pack_dir = ROOT / "packs" / pack_id
    if not pack_dir.is_dir():
        raise MemeError(f"没有这个表情包：{pack_id}")
    mapping = pack_mapping(pack_dir)
    items: dict[str, dict] = {}
    folders = {}
    memes = pack_dir / "memes"
    for cdir in sorted(memes.iterdir()) if memes.is_dir() else []:
        if not cdir.is_dir() or not safe_cat(cdir.name):
            continue
        files = sorted(p for p in cdir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
        folders[cdir.name] = len(files)
        for f in files:
            try:
                h = hasher(f)
            except OSError:
                continue
            it = items.setdefault(h, {"id": h[:16], "sha": h, "cats": {}, "path": str(f),
                                      "ext": f.suffix.lower(), "size": f.stat().st_size, "mtime": f.stat().st_mtime})
            # 同一个分类里放了两份一样的图：只记第一份（插件上传时会拦下重复，正常不会有）
            it["cats"].setdefault(cdir.name, f.name)
            it["mtime"] = max(it["mtime"], f.stat().st_mtime)
    cats = []
    for key in list(mapping) + [k for k in folders if k not in mapping]:
        cats.append({"key": key, "desc": mapping.get(key, ""), "count": folders.get(key, 0), "in_config": key in mapping})
    return {"cats": cats, "items": sorted(items.values(), key=lambda x: -x["mtime"])}


def read_trash() -> list[dict]:
    out = []
    for d in sorted(TRASH.iterdir(), reverse=True) if TRASH.is_dir() else []:
        meta = _read_json(d / "meta.json")
        if not isinstance(meta, dict):
            continue
        img = d / str(meta.get("file", ""))
        if not img.is_file():
            continue
        out.append({**meta, "id": d.name, "path": str(img), "size": img.stat().st_size})
    return out


def cmd_inventory() -> dict:
    reg = _read_json(ROOT / "registry.json") or {}
    rules = _read_json(ROOT / "selection_rules.json") or {}
    names, enabled = {}, {}
    for p in reg.get("installed_packs") or []:
        if p.get("id"):
            names[p["id"]] = p.get("name") or p["id"]
            enabled[p["id"]] = p.get("enabled", True) is not False
    bound: list[str] = []
    for r in rules.get("rules") or []:
        if r.get("scope") == "default":
            for pid in r.get("pack_ids") or ([r["pack_id"]] if r.get("pack_id") else []):
                if pid not in bound and (ROOT / "packs" / pid).is_dir() and enabled.get(pid, True):
                    bound.append(pid)
    all_ids = bound + sorted(d.name for d in (ROOT / "packs").iterdir() if d.is_dir() and d.name not in bound)
    aliases = {}
    for k, v in (_read_json(ROOT / "category_aliases.json") or {}).items():
        if not k.startswith("_") and isinstance(v, str) and k != v:
            aliases[k] = v
    hasher = Hasher()
    packs = []
    for pid in all_ids:
        name = names.get(pid) or (_read_json(ROOT / "packs" / pid / "manifest.json") or {}).get("name") or pid
        data = read_pack(pid, hasher)
        packs.append({"id": pid, "name": name, "in_use": pid in bound, "primary": bool(bound) and bound[0] == pid,
                      "dir": str(ROOT / "packs" / pid), **data})
    hasher.save()
    # 她看得到的分类 = 能用的包的分类合起来（排前面的包的描述优先），别名分类并进大分类
    merged: dict[str, str] = {}
    for p in reversed([p for p in packs if p["in_use"]]):
        for c in p["cats"]:
            if c["in_config"]:
                merged[c["key"]] = c["desc"]
    return {"ok": True, "online": online(), "packs": packs, "aliases": aliases, "visible": merged,
            "shared": shared_view(packs, aliases, merged), "primary": bound[0] if bound else PRIMARY,
            "trash": read_trash(), "trash_dir": str(TRASH)}


def shared_view(packs: list[dict], aliases: dict[str, str], merged: dict[str, str]) -> list[dict]:
    """所有能用的包共用一套分类（取并集）：同义的小分类并进大分类（别名表），
    每个用途记下它在各个包里对应哪些分类目录。顺手给每张图写上它属于哪些共用分类（item["shared"]）。"""
    used = [p for p in packs if p["in_use"]]
    present = {c["key"] for p in used for c in p["cats"]}

    def main_of(k: str) -> str:
        m = aliases.get(k)
        return m if m and m in present else k

    rows: dict[str, dict] = {}
    for p in used:
        for c in p["cats"]:
            k = main_of(c["key"])
            row = rows.setdefault(k, {"key": k, "desc": "", "members": {}, "count": 0, "visible": k in merged})
            row["members"].setdefault(p["id"], []).append(c["key"])
            if not row["desc"] and c["desc"] and c["key"] == k:
                row["desc"] = c["desc"]
        for it in p["items"]:
            it["pack"] = p["id"]
            it["shared"] = sorted({main_of(c) for c in it["cats"]})
            for k in it["shared"]:
                rows[k]["count"] += 1
    for k, row in rows.items():
        if k in merged:
            row["desc"] = merged[k]
        if not row["desc"]:   # 只有别名分类有描述
            row["desc"] = next((c["desc"] for p in used for c in p["cats"] if main_of(c["key"]) == k and c["desc"]), "")
        # 每个包里优先用和用途同名的目录
        for pid, dirs in row["members"].items():
            dirs.sort(key=lambda d: d != k)
    return sorted(rows.values(), key=lambda r: (-r["count"], r["key"]))


# ---------------------------------------------------------------- 改
def _pack_dir(pack: str) -> Path:
    d = ROOT / "packs" / pack
    if not pack or not safe_cat(pack) or not d.is_dir():
        raise MemeError(f"没有这个表情包：{pack}")
    return d


def _item_cats(pack: str, item: dict) -> dict[str, str]:
    """只留下磁盘上真的还在的 {分类: 文件名}。"""
    memes = _pack_dir(pack) / "memes"
    cats = {}
    for cat, name in (item.get("cats") or {}).items():
        if safe_cat(cat) and safe_cat(name) and (memes / cat / name).is_file():
            cats[cat] = name
    return cats


def _ensure_cat(api: Api, pack: str, cat: str, desc: str = "") -> None:
    if not safe_cat(cat):
        raise MemeError(f"分类名不合法：「{cat}」（不能有 / \\，首尾不能有空格）")
    if cat not in pack_mapping(_pack_dir(pack)):
        api.plug("category/restore", {"category": cat, "description": desc or "请添加描述", "managed_pack_id": pack})


def _to_trash(pack: str, cats: dict[str, str], reason: str) -> Path:
    """先把图复制进回收站（记下原来的分类和描述），复制成功才允许去删。"""
    pdir = _pack_dir(pack)
    first_cat, first_name = next(iter(cats.items()))
    src = pdir / "memes" / first_cat / first_name
    TRASH.mkdir(parents=True, exist_ok=True)
    d = TRASH / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6])
    d.mkdir()
    shutil.copy2(src, d / first_name)
    mapping = pack_mapping(pdir)
    reg = _read_json(ROOT / "registry.json") or {}
    pname = next((p.get("name") for p in reg.get("installed_packs") or [] if p.get("id") == pack), pack)
    meta = {"pack": pack, "pack_name": pname, "file": first_name, "cats": cats,
            "descs": {c: mapping.get(c, "") for c in cats}, "deleted_at": datetime.now().isoformat(timespec="seconds"),
            "reason": reason, "sha": hashlib.sha256(src.read_bytes()).hexdigest()}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def _delete_files(api: Api, pack: str, by_cat: dict[str, list[str]]) -> None:
    for cat, names in by_cat.items():
        if names:
            r = api.plug("emoji/batch_delete", {"category": cat, "image_files": names, "managed_pack_id": pack})
            if r.get("missing_count"):
                raise MemeError(f"「{cat}」里有 {r['missing_count']} 张找不到了（可能已经被删）")


def op_trash(api: Api, pack: str, items: list[dict], reason: str = "删除") -> dict:
    trashed, by_cat = 0, {}
    for item in items:
        cats = _item_cats(pack, item)
        if not cats:
            continue
        _to_trash(pack, cats, reason)
        trashed += 1
        for c, n in cats.items():
            by_cat.setdefault(c, []).append(n)
    _delete_files(api, pack, by_cat)
    return {"trashed": trashed}


def op_set_cats(api: Api, pack: str, items: list[dict], add: list[str], remove: list[str],
                descs: dict | None = None) -> dict:
    add = [c for c in dict.fromkeys(add) if c not in remove]
    for c in add:
        _ensure_cat(api, pack, c, (descs or {}).get(c, ""))
    memes = _pack_dir(pack) / "memes"
    added = removed = trashed = 0
    to_delete: dict[str, list[str]] = {}
    to_trash = []
    for item in items:
        cats = _item_cats(pack, item)
        if not cats:
            continue
        src_cat, src_name = next(iter(cats.items()))
        for c in add:
            if c in cats:
                continue
            target = memes / c / src_name
            if target.exists():
                # 目标分类里有同名的别的图：改走上传（插件会自动改名）
                api.upload(pack, c, memes / src_cat / src_name)
            else:
                r = api.plug("emoji/batch_copy", {"source_category": src_cat, "target_category": c,
                                                   "image_files": [src_name], "managed_pack_id": pack})
                if not r.get("copied_count"):
                    api.upload(pack, c, memes / src_cat / src_name)
            added += 1
        drop = [c for c in remove if c in cats]
        keep_after = set(cats) - set(drop) | set(add)
        if drop and not keep_after:
            to_trash.append({"cats": cats})   # 一个分类都不剩 = 整张图删掉，进回收站
            continue
        for c in drop:
            to_delete.setdefault(c, []).append(cats[c])
            removed += 1
    _delete_files(api, pack, to_delete)
    if to_trash:
        trashed = op_trash(api, pack, to_trash, "取消了它所有的分类")["trashed"]
    return {"added": added, "removed": removed, "trashed": trashed}


def op_restore(api: Api, ids: list[str]) -> dict:
    restored, notes = 0, []
    for tid in ids:
        d = TRASH / Path(tid).name
        meta = _read_json(d / "meta.json")
        if not isinstance(meta, dict):
            notes.append(f"{tid}：回收站里没有这一项")
            continue
        pack, img = meta.get("pack", ""), d / meta.get("file", "")
        _pack_dir(pack)
        for cat in meta.get("cats") or {}:
            _ensure_cat(api, pack, cat, (meta.get("descs") or {}).get(cat, ""))
            api.upload(pack, cat, img)
        shutil.rmtree(d)
        restored += 1
    return {"restored": restored, "notes": notes}


def op_purge(ids: list[str] | None) -> dict:
    n = 0
    targets = [TRASH / Path(t).name for t in ids] if ids is not None else (list(TRASH.iterdir()) if TRASH.is_dir() else [])
    for d in targets:
        if d.is_dir() and (d / "meta.json").is_file():
            shutil.rmtree(d)
            n += 1
    return {"purged": n}


def op_add(api: Api, pack: str, cat: str, paths: list[str], desc: str = "") -> dict:
    _ensure_cat(api, pack, cat, desc)
    ok = dup = 0
    fail = []
    for p in paths:
        path = Path(p)
        if path.suffix.lower() not in IMAGE_EXTS or not path.is_file():
            fail.append(f"{path.name}（不是图片）")
            continue
        try:
            if api.upload(pack, cat, path) == "ok":
                ok += 1
            else:
                dup += 1
        except MemeError as e:
            fail.append(f"{path.name}（{e}）")
    return {"added": ok, "dup": dup, "fail": fail}


def op_cat_delete(api: Api, pack: str, cat: str) -> dict:
    """只在这个分类里的图进回收站；别的分类里也有的图只是少了这个分类。"""
    hasher = Hasher()
    data = read_pack(pack, hasher)
    hasher.save()
    only_here = [{"cats": {cat: it["cats"][cat]}} for it in data["items"] if list(it["cats"]) == [cat]]
    trashed = 0
    for it in only_here:
        _to_trash(pack, it["cats"], f"删除了分类「{cat}」")
        trashed += 1
    api.plug("category/delete", {"category": cat, "managed_pack_id": pack})
    return {"trashed": trashed}


def _set_alias_target(old: str, new: str) -> None:
    """共用分类改名后，别名表里指向旧名的同义分类改指新名。"""
    path = ROOT / "category_aliases.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return
    changed = False
    for k, v in list(data.items()):
        if not k.startswith("_") and v == old:
            data[k] = new
            changed = True
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def op_shared(api: Api, kind: str, cat: str, new: str, desc: str) -> dict:
    """「全部表情包」视图里的分类操作：一个用途 = 各个包里对应的分类目录，一起改。"""
    inv = cmd_inventory()
    row = next((r for r in inv["shared"] if r["key"] == cat), None)
    if kind == "shared_create":
        if not safe_cat(cat):
            raise MemeError(f"分类名不合法：「{cat}」")
        if row:
            raise MemeError(f"已经有「{cat}」这个用途了")
        api.plug("category/restore", {"category": cat, "description": desc or "请添加描述", "managed_pack_id": inv["primary"]})
        return {"packs": 1}
    if not row:
        raise MemeError(f"没有「{cat}」这个用途")
    if kind == "shared_desc":
        if not desc:
            raise MemeError("描述不能为空")
        n = 0
        for pid, dirs in row["members"].items():
            mapping = pack_mapping(_pack_dir(pid))
            if cat in dirs and cat in mapping:
                api.plug("category/update_description", {"tag": cat, "description": desc, "managed_pack_id": pid})
            elif cat in dirs:
                api.plug("category/restore", {"category": cat, "description": desc, "managed_pack_id": pid})
            else:
                continue
            n += 1
        return {"packs": n}
    if kind == "shared_rename":
        if not safe_cat(new):
            raise MemeError(f"新分类名不合法：「{new}」")
        owners = [pid for pid, dirs in row["members"].items() if cat in dirs]
        for pid in owners:
            if new in pack_mapping(_pack_dir(pid)) or (_pack_dir(pid) / "memes" / new).exists():
                raise MemeError(f"「{pid}」里已经有「{new}」了，没有改名")
        for pid in owners:
            if cat not in pack_mapping(_pack_dir(pid)):   # 只有目录、没写进配置的分类，先补进配置才能改名
                api.plug("category/restore", {"category": cat, "description": row["desc"] or "请添加描述", "managed_pack_id": pid})
            api.plug("category/rename", {"old_name": cat, "new_name": new, "managed_pack_id": pid})
        _set_alias_target(cat, new)
        return {"packs": len(owners)}
    if kind == "shared_delete":
        trashed = 0
        for pid, dirs in row["members"].items():
            for d in dirs:
                trashed += op_cat_delete(api, pid, d)["trashed"]
        return {"trashed": trashed, "packs": len(row["members"])}
    raise MemeError(f"不认识的操作：{kind}")


def run_ops(ops: list[dict]) -> dict:
    api = None
    results = []
    for op in ops:
        kind = op.get("op")
        # PowerShell 会把只有一项的数组拆成单个值：这里统一包回列表
        for key in ("items", "paths", "ids", "add", "remove"):
            if isinstance(op.get(key), (dict, str)):
                op[key] = [op[key]]
        try:
            if kind in ("purge", "purge_all"):
                res = op_purge(None if kind == "purge_all" else list(op.get("ids") or []))
            else:
                api = api or Api()
                pack = str(op.get("pack") or "")
                if kind == "add":
                    res = op_add(api, pack, str(op.get("cat") or ""), list(op.get("paths") or []), str(op.get("desc") or ""))
                elif kind == "set_cats":
                    res = op_set_cats(api, pack, list(op.get("items") or []), list(op.get("add") or []),
                                      list(op.get("remove") or []), op.get("descs"))
                elif kind == "move":
                    to = str(op.get("to") or "")
                    items = list(op.get("items") or [])
                    others = sorted({c for it in items for c in (it.get("cats") or {}) if c != to})
                    res = op_set_cats(api, pack, items, [to], others, op.get("descs"))
                elif kind == "trash":
                    res = op_trash(api, pack, list(op.get("items") or []))
                elif kind == "restore":
                    res = op_restore(api, list(op.get("ids") or []))
                elif kind == "cat_create":
                    cat = str(op.get("cat") or "")
                    if not safe_cat(cat):
                        raise MemeError(f"分类名不合法：「{cat}」")
                    if cat in pack_mapping(_pack_dir(pack)):
                        raise MemeError(f"已经有「{cat}」这个分类了")
                    api.plug("category/restore", {"category": cat, "description": op.get("desc") or "请添加描述", "managed_pack_id": pack})
                    res = {}
                elif kind == "cat_desc":
                    _pack_dir(pack)
                    api.plug("category/update_description", {"tag": op.get("cat"), "description": op.get("desc"), "managed_pack_id": pack})
                    res = {}
                elif kind == "cat_rename":
                    new = str(op.get("new") or "")
                    if not safe_cat(new):
                        raise MemeError(f"新分类名不合法：「{new}」")
                    if new in pack_mapping(_pack_dir(pack)) or (_pack_dir(pack) / "memes" / new).exists():
                        raise MemeError(f"已经有「{new}」这个分类了")
                    api.plug("category/rename", {"old_name": op.get("cat"), "new_name": new, "managed_pack_id": pack})
                    res = {}
                elif kind == "cat_delete":
                    res = op_cat_delete(api, pack, str(op.get("cat") or ""))
                elif kind.startswith("shared_"):
                    res = op_shared(api, kind, str(op.get("cat") or ""), str(op.get("new") or ""), str(op.get("desc") or ""))
                else:
                    raise MemeError(f"不认识的操作：{kind}")
            results.append({"op": kind, **res, "ok": True})
        except MemeError as e:
            results.append({"op": kind, "ok": False, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            results.append({"op": kind, "ok": False, "error": f"{type(e).__name__}: {e}"})
    errors = [r["error"] for r in results if not r["ok"]]
    return {"ok": not errors, "results": results, "error": "；".join(errors)}


# ---------------------------------------------------------------- 入口
def main(argv: list[str]) -> int:
    out_path = in_path = None
    rest = []
    it = iter(argv)
    for a in it:
        if a == "--out":
            out_path = next(it, None)
        elif a == "--in":
            in_path = next(it, None)
        else:
            rest.append(a)
    t0 = time.time()
    try:
        if rest[:1] == ["inventory"]:
            res = cmd_inventory()
        elif rest[:1] == ["apply"] and in_path:
            res = run_ops(list((json.loads(Path(in_path).read_text(encoding="utf-8-sig")) or {}).get("ops") or []))
        else:
            raise MemeError(__doc__ or "")
    except MemeError as e:
        res = {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    res["seconds"] = round(time.time() - t0, 2)
    text = json.dumps(res, ensure_ascii=False)
    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
