"""佳树的数据：部署 kaju_core、清缓存（clean-cache）、备份她本人（backup-self）。
（11-08 的一次性搬家 migrate 11-18 整理时删了，旧版在 _backup\archive-20261118.zip）

kaju_data 的排法见 bot_setup\\kaju_core\\paths.py。由 botctl.py 调用，只用标准库。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

SETUP = Path(__file__).resolve().parent.parent
HOME = SETUP.parent                                   # D:\JiashuBot
KAJU = Path(os.environ.get("KAJU_DATA") or HOME / "kaju_data")
SELF, ACCOUNTS, CACHE = KAJU / "self", KAJU / "accounts", KAJU / "cache"
INSTANCE = HOME / "AstrBot-Data" / "instances" / "c3dc9f47-5318-45ea-9792-d00fb8f0f15b"
DATA = INSTANCE / "core" / "data"
PLUGIN_DATA = DATA / "plugin_data"
LIB = DATA / "kaju_lib"                               # 部署好的 kaju_core 在 LIB\kaju_core
SITE = INSTANCE / "venv" / "Lib" / "site-packages"
BACKUP = HOME / "_backup"

THIRD_PARTY = {"memorix": "astrbot_plugin_memorix", "meme_manager": "meme_manager"}
LOGINS = ["bili_login.json", "douyin_login.json", "douyin_profile"]  # 原来在 kaju_basics 的数据目录里
# 浏览器资料夹里的缓存（删了浏览器会自己重建；登录在 Default\Network\Cookies 等处，不在这些里面）
CHROME_CACHES = ["Default/Cache", "Default/Code Cache", "Default/GPUCache", "Default/DawnGraphiteCache",
                 "Default/DawnWebGPUCache", "Default/Service Worker/CacheStorage", "Default/Service Worker/ScriptCache",
                 "GrShaderCache", "GraphiteDawnCache", "ShaderCache", "GPUPersistentCache",
                 "component_crx_cache", "extensions_crx_cache"]


def _own_plugins() -> list[str]:
    return sorted(p.name for p in (SETUP / "plugins").iterdir() if (p / "main.py").exists())


def _legacy(short: str) -> Path:
    return PLUGIN_DATA / (THIRD_PARTY.get(short) or "astrbot_plugin_" + short)


def _is_link(p: Path) -> bool:
    return os.path.isjunction(p) or p.is_symlink()


def _mb(n: int) -> str:
    return f"{n / 1048576:.1f} MiB"


def keeper_running() -> list[int] | None:
    """返回抖音常驻浏览器进程号，查不到进程状态时返回 None。"""
    ps = ("Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" -ErrorAction Stop | "
          "Where-Object { $_.CommandLine -like '*douyin_profile*' } | ForEach-Object { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             encoding="oem", errors="replace", timeout=30, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    pids = [int(x) for x in out.split() if x.isdigit()]
    port = _keeper_port() if not pids else 0
    if port:
        import socket

        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return None  # 端口还开着，但未能从进程列表确认浏览器身份。
        except ConnectionRefusedError:
            pass
        except OSError:
            return None
    return pids


def _keeper_port() -> int:
    for p in (ACCOUNTS / "douyin_login.json", _legacy("kaju_basics") / "douyin_login.json"):
        try:
            return int((json.loads(p.read_text(encoding="utf-8")).get("keeper") or {}).get("port") or 0)
        except (OSError, ValueError):
            continue
    return 0


def close_keeper(wait: float = 15) -> bool:
    """请抖音常驻浏览器自己正常关掉（CDP Browser.close，和点"关闭"一样，登录照样存着）。关掉了返回 True。"""
    import base64
    import socket
    import urllib.request

    port = _keeper_port()
    if not port:
        return keeper_running() == []
    try:
        ver = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5).read())
        path = "/" + ver["webSocketDebuggerUrl"].split("/", 3)[3]
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        if b" 101 " not in s.recv(4096):
            return False
        data = json.dumps({"id": 1, "method": "Browser.close"}).encode()
        mask = os.urandom(4)
        head = bytes([0x81, 0x80 | len(data)]) if len(data) < 126 else bytes([0x81, 0xFE]) + len(data).to_bytes(2, "big")
        s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        s.close()
    except Exception as e:  # noqa: BLE001
        print(f"没能请常驻浏览器关掉：{e}")
        return False
    end = time.time() + wait
    while time.time() < end:
        if keeper_running() == []:
            return True
        time.sleep(1)
    return False


# ---------------------------------------------------------------- deploy

# 哪一块由哪些插件用（热重载那些插件，它们开头的 kaju_core.fresh / kaju_platforms.fresh 就会换上新的）
AREA_PLUGINS = {"senses": ["kaju_basics"], "heart": ["kaju_heart"], "memory": ["memory_weight"], "learn": ["kaju_learn"],
                "life": ["kaju_life"], "voice": ["kaju_style"]}
PLATFORM_PLUGINS = {"bili": ["kaju_basics", "kaju_dm"], "douyin": ["kaju_basics", "kaju_dm"],
                    "shared": ["kaju_basics", "kaju_dm"], "qq": ["kaju_heart"], "dm": ["kaju_dm"]}
# 部署到 kaju_lib 的几个包：(名字, 块 → 插件)。块以外的顶层文件改了要重启 AstrBot
LIBS = [("kaju_core", AREA_PLUGINS), ("kaju_astr", {}), ("kaju_platforms", PLATFORM_PLUGINS)]


def _core_changes(src: Path, dst: Path) -> tuple[set[str], list[str]]:
    """(改了的块, 改了的顶层文件——只算已部署过的，新加的还没人 import，不用重启)：比源码和已部署的那份。"""
    def files(root: Path) -> dict[str, bytes]:
        out = {}
        if root.exists():
            for f in root.rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts and f.name != "_root.py":
                    out[f.relative_to(root).as_posix()] = f.read_bytes()
        return out
    a, b = files(src), files(dst)
    changed = {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)}
    areas = {k.split("/", 1)[0] for k in changed if "/" in k}
    top = sorted(k for k in changed if "/" not in k and k in b)
    return areas, top


def deploy_core() -> list[str]:
    """部署 kaju_core、kaju_astr、kaju_platforms，返回要热重载的插件（改了哪块就重载用它的插件）。"""
    plugins: set[str] = set()
    restart: list[str] = []
    said = []
    for name, users in LIBS:
        src, dst = SETUP / name, LIB / name
        if not src.exists():
            continue
        areas, top = _core_changes(src, dst)
        if dst.exists():
            shutil.rmtree(dst)
        # copy（不是 copy2）：文件时间 = 部署时间，热重载时 fresh() 才知道这是新部署的
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "_root.py"), copy_function=shutil.copy)
        if name == "kaju_core":
            (dst / "_root.py").write_text(f'ROOT = r"{KAJU}"\n', encoding="utf-8")
        for a in areas:
            if a in users:
                plugins.update(users[a])
            elif not users:  # kaju_astr 没有块：子目录改了也算本身
                top.append(a)
        restart += [f"{name}/{t}" for t in top]
        said.append(f"{name}：{'、'.join(sorted(areas) + top) or '没改'}")
    pth = SITE / "kaju_core.pth"
    if not pth.exists() or pth.read_text(encoding="utf-8").strip() != str(LIB):
        pth.write_text(str(LIB) + "\n", encoding="utf-8")
    plugins_l = sorted(plugins)
    print(f"已部署到 {LIB}（数据根 {KAJU}）。改了——{'；'.join(said)}"
          + (f"；--reload 会重载 {'、'.join(plugins_l)}" if plugins_l else ""))
    if restart:
        print(f"  注意：{'、'.join(restart)} 改了，热重载换不了，要重启 AstrBot 才生效")
    return plugins_l


# ---------------------------------------------------------------- clean-cache

def _old_files(folder: Path, older_than: float, skip: tuple[str, ...] = ()) -> list[tuple[Path, os.stat_result]]:
    out = []
    try:
        if folder.resolve() != folder.absolute():
            return out
    except OSError:
        return out
    cutoff = time.time() - older_than
    for root, dirs, files in os.walk(folder):
        parent = Path(root)
        dirs[:] = [d for d in dirs if (parent != folder or d not in skip) and not _is_link(parent / d)]
        for name in files:
            if parent == folder and name in skip:
                continue
            p = parent / name
            try:
                info = p.lstat()
                if stat.S_ISREG(info.st_mode) and info.st_mtime <= cutoff:
                    out.append((p, info))
            except OSError:
                pass
    return out


def _profile() -> Path:
    p = ACCOUNTS / "douyin_profile"
    return p if p.exists() else _legacy("kaju_basics") / "douyin_profile"


def clean_cache(dry: bool = False, everything: bool = False) -> None:
    """清理可重建缓存，浏览器停用后才清它的缓存，保留运行状态和登录文件。"""
    pids = keeper_running()
    skip = ("gpu_busy", "model_health.json")
    if pids != []:
        skip += ("douyin_chrome",)
        state = f"开着（进程 {pids}）" if pids else "状态无法确认"
        print(f"抖音常驻浏览器{state}，跳过浏览器缓存")
    memes = SELF / "meme_manager"
    if not memes.exists():
        memes = _legacy("meme_manager")
    groups = [
        ("kaju_data\\cache", _old_files(CACHE, 0 if everything else 600, skip)),
        ("AstrBot temp（一天前的）", _old_files(DATA / "temp", 86400)),
        ("表情包插件 temp（一天前的）", _old_files(memes / "temp", 86400)),
    ]
    if pids == []:
        prof = _profile()
        browser_files = [item for c in CHROME_CACHES for item in _old_files(prof / c, 0)]
        groups.append(("抖音浏览器资料夹缓存", browser_files))
    total = 0
    for title, items in groups:
        count = size = 0
        for p, info in items:
            if not dry:
                try:
                    current = p.lstat()
                    if p.resolve() != p.absolute() or (current.st_ino, current.st_mtime_ns, current.st_size) != (
                        info.st_ino, info.st_mtime_ns, info.st_size
                    ):
                        continue
                    p.unlink()
                except OSError:
                    continue
            count += 1
            size += info.st_size
        total += size
        print(f"{title}: {count} 项，{_mb(size)}")
        if count < len(items):
            print(f"  有 {len(items) - count} 项发生变化或无法删除")
    print(("会清掉" if dry else "清掉了") + f" 一共 {_mb(total)}")


# ---------------------------------------------------------------- backup-self

def _sqlite_copy(src: Path, dst: Path, timeout: float = 30) -> bool:
    """运行中的数据库也能拿到一致的一份（sqlite 自己的 backup）。被锁住一直拿不到（sqlite 的 backup 会无限重试）
    就放弃，返回 False，由调用的地方改成直接拷文件。"""
    import threading

    ok: list[bool] = []

    def run():
        con = sqlite3.connect(Path(src).as_uri() + "?mode=ro", uri=True, timeout=5)
        out = sqlite3.connect(dst)
        try:
            con.backup(out)
            ok.append(True)
        finally:
            out.close()
            con.close()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    return bool(ok)


def _add_tree(z: zipfile.ZipFile, folder: Path, arc: str, skip=(), tmp: Path | None = None) -> int:
    """skip：不要的子目录（相对 folder，/ 分隔）。.db 用 sqlite backup（tmp 给了的话），拿不到就直接拷。"""
    n = 0
    for root, dirs, files in os.walk(folder):
        rel_root = Path(root).relative_to(folder)
        dirs[:] = [d for d in dirs if d != "__pycache__" and (rel_root / d).as_posix() not in skip]
        for f in files:
            p = Path(root) / f
            rel = (rel_root / f).as_posix()
            if f.endswith(("-wal", "-shm", "-journal")) or f in ("LOCK", "lockfile", "SingletonLock") or rel in skip:
                continue
            name = f"{arc}/{rel}"
            try:
                c = tmp / f"{n}.db" if tmp is not None else None
                if c is not None and f.endswith((".db", ".sqlite", ".sqlite3")) and _sqlite_copy(p, c):
                    z.write(c, name)
                else:
                    z.write(p, name)
                n += 1
            except (OSError, sqlite3.Error) as e:
                print(f"  没备份上 {p}: {e}")
    return n


def backup_self(accounts: bool = False) -> None:
    BACKUP.mkdir(exist_ok=True)
    out = BACKUP / f"self-{dt.datetime.now():%Y%m%d-%H%M%S}.zip"
    with tempfile.TemporaryDirectory() as td, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        tmp = Path(td)
        counts = {}
        for short in _own_plugins() + list(THIRD_PARTY):
            folder = SELF / short if (SELF / short).exists() else _legacy(short)
            if folder.exists():  # 没 migrate 之前登录还在 kaju_basics 里：不算她本人，跳过（--accounts 另外放）
                counts[short] = _add_tree(z, folder, f"self/{short}", tmp=tmp,
                                          skip={"temp", "web_import_tmp", *LOGINS})
        db = DATA / "data_v4.db"
        if db.exists():
            if _sqlite_copy(db, tmp / "data_v4.db"):
                z.write(tmp / "data_v4.db", "astrbot/data_v4.db")  # 人格、聊天记录
            else:
                print("  data_v4.db 被锁着，直接拷了一份（机器人正在写的话可能不完整）")
                z.write(db, "astrbot/data_v4.db")
        cfg = DATA / "config"
        names = {f"astrbot_plugin_{s}_config.json" for s in _own_plugins()} | \
                {f"{v}_config.json" for v in THIRD_PARTY.values()}
        for p in sorted(cfg.glob("*.json")) if cfg.exists() else []:
            if p.name in names:
                z.write(p, f"astrbot/config/{p.name}")
        if accounts:  # 浏览器资料夹里的库被 Chrome 锁着：直接拷文件（tmp=None），不走 sqlite backup
            caches = {f"douyin_profile/{c}" for c in CHROME_CACHES}
            if ACCOUNTS.exists():
                _add_tree(z, ACCOUNTS, "accounts", skip=caches)
            else:  # 还没 migrate：登录在 kaju_basics 的目录里
                basics = _legacy("kaju_basics")
                for f in LOGINS:
                    p = basics / f
                    if p.is_file():
                        z.write(p, f"accounts/{f}")
                    elif p.is_dir():
                        _add_tree(z, p, f"accounts/{f}", skip={c for c in CHROME_CACHES})
            if (DATA / "cmd_config.json").exists():
                z.write(DATA / "cmd_config.json", "astrbot/cmd_config.json")
        z.writestr("_说明.txt", (
            f"佳树本人的备份 {dt.datetime.now():%Y-%m-%d %H:%M}\n"
            "self/        = kaju_data\\self（每个插件一个目录）\n"
            "astrbot/     = data_v4.db（人格、聊天记录）+ 插件配置\n"
            + ("accounts/    = 登录（有 Cookie，别外传）+ cmd_config.json（有 API key）\n" if accounts else "")
            + "恢复：停机器人 → 解到对应位置 → 启动。\n"
            + json.dumps(counts, ensure_ascii=False)))
    print(f"备份好了：{out}（{_mb(out.stat().st_size)}）" + ("，含登录和 API key，别外传" if accounts else ""))


# ---------------------------------------------------------------- people（谁是谁）

def _people():
    os.environ.setdefault("KAJU_DATA", str(KAJU))
    sys.path.insert(0, str(SETUP))
    from kaju_core import people

    return people


def people_cmd(args: list[str]) -> None:
    """botctl people [list] | init | link 钥匙 平台 号 [备注] | unlink 平台 号 | owner 钥匙"""
    people = _people()
    reg = people.registry()
    cmd = args[0] if args else "list"
    if cmd == "init":  # 一次性：从以前散在各插件配置里的兄长账号生成
        def cfg(name):
            try:
                return json.loads((DATA / "config" / f"astrbot_plugin_{name}_config.json").read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                return {}
        book, dm = cfg("address_book"), cfg("kaju_dm")
        owner = str(book.get("owner_qq") or "").strip()
        if not owner:
            sys.exit("称呼簿配置里没有 owner_qq，不知道兄长的 QQ")
        if reg.owner() and reg.owner() != owner:
            sys.exit(f"身份表里的兄长已经是 {reg.owner()}，和配置里的 {owner} 不一样：先自己看一下")
        reg.set_owner(owner)
        for platform, key in (("bili", "owner_bili_mid"), ("douyin", "owner_douyin_uid")):
            account = str(dm.get(key) or "").strip()
            if account:
                print(reg.link(owner, platform, account))
    elif cmd == "link" and len(args) >= 4:
        print(reg.link(args[1], args[2], args[3], " ".join(args[4:])))
    elif cmd == "unlink" and len(args) >= 3:
        print(reg.unlink(args[1], args[2]))
    elif cmd == "owner" and len(args) >= 2:
        reg.set_owner(args[1])
    elif cmd != "list":
        sys.exit(people_cmd.__doc__)
    print(f"身份表 {reg.path}：")
    print("\n".join(reg.describe()) or "（空的）")
