"""佳树机器人的小工具：部署插件、热重载、查看/修改插件配置。只用标准库，任何 python 都能跑。

用法:
    python botctl.py deploy [名字 ...] [--reload]   把 bot_setup\\plugins\\<名字> 复制到 AstrBot（不写名字 = 全部）
    python botctl.py reload <名字 ...>               让运行中的 AstrBot 热重载这些插件
    python botctl.py config <名字>                   打印插件当前配置
    python botctl.py config <名字> a.b=值 ...        改配置（值按 JSON 解析，解析不了就当字符串）；
                                                     机器人在线走 AstrBot 接口（会热重载），离线直接改文件
    python botctl.py clean-cache [--dry] [--all]     清缓存（kaju_data\\cache、抖音浏览器缓存、AstrBot temp），不碰她本人
    python botctl.py backup-self [--accounts]        备份她本人（kaju_data\\self + 人格和聊天记录 + 插件配置）到 _backup
    python botctl.py people [list|init|link 钥匙 平台 号 [备注]|unlink 平台 号|owner 钥匙]
                                                     谁是谁：一个人的 QQ / B站(bili) / 抖音(douyin，sec_uid) 号认成同一个人
名字可以写短名（kaju_style）或全名（astrbot_plugin_kaju_style）。kaju_core 也算一个名字（改了要重启 AstrBot）。
"""

import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kajudata  # noqa: E402

SETUP = Path(__file__).resolve().parent.parent
SOURCES = SETUP / "plugins"
DATA = Path(r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core\data")
BASE = "http://127.0.0.1:6185"


def full_name(name: str) -> str:
    return name if name.startswith("astrbot_plugin_") else "astrbot_plugin_" + name


def short_name(name: str) -> str:
    return name.removeprefix("astrbot_plugin_")


def api(path: str, body: dict, token: str | None = None) -> dict:
    """POST to the AstrBot dashboard API (logs in with the panel's password when token is None)."""
    if token is None:
        # 11-20：仓库公开后 bot-panel.ps1 里的密码换成了假的，真值在 kaju_data\accounts\panel.json（不进仓库）
        password = ""
        try:
            password = json.loads((SETUP.parent / "kaju_data" / "accounts" / "panel.json").read_text(encoding="utf-8-sig")).get("dashboard_password", "")
        except (OSError, ValueError):
            pass
        if not password:
            panel = (SETUP / "bot-panel.ps1").read_text(encoding="utf-8-sig")
            password = re.search(r"^\$Pass\s*=\s*'([^']*)'", panel, re.M)[1]
        token = api("/api/auth/login", {"username": "astrbot", "password": password}, "")["data"]["token"]
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), headers)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def online() -> bool:
    try:
        urllib.request.urlopen(BASE, timeout=3)
        return True
    except Exception:  # noqa: BLE001
        return False


def deploy(names: list[str]) -> list[str]:
    """部署；返回 kaju_core 里改了的块对应的插件（--reload 时一起重载）。"""
    plugins = [n for n in names if n != "kaju_core"]
    core_users: list[str] = []
    if not names or len(plugins) < len(names):
        core_users = kajudata.deploy_core()
        if names and not plugins:
            return core_users
    names = plugins or sorted(p.name for p in SOURCES.iterdir() if (p / "main.py").exists())
    for name in names:
        src = SOURCES / short_name(name)
        dst = DATA / "plugins" / full_name(name)
        if not (src / "main.py").exists():
            sys.exit(f"没有这个插件的源码: {src}")
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        print(f"已部署 {src.name} -> {dst}")
    return core_users


def reload(names: list[str]) -> None:
    for name in names:
        res = api("/api/plugin/reload", {"name": full_name(name)})
        print(full_name(name), res.get("status"), res.get("message", ""))


def config(name: str, edits: list[str]) -> None:
    path = DATA / "config" / f"{full_name(name)}_config.json"
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    if not edits:
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        return
    for edit in edits:
        key, _, raw = edit.partition("=")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        *parents, leaf = key.split(".")
        node = cfg
        for p in parents:
            node = node.setdefault(p, {})
        node[leaf] = value
    if online():
        print(api(f"/api/config/plugin/update?plugin_name={full_name(name)}", cfg))
    else:
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=4), encoding="utf-8")
        print("机器人没在运行，已直接改文件，下次启动生效")
    print(json.dumps(cfg, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if not sys.stdout.isatty():  # 输出进管道（Git Bash、控制台的后台任务）时按 UTF-8 写，不然中文是乱码
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if not args or args[0] not in ("deploy", "reload", "config", "clean-cache", "backup-self", "people"):
        sys.exit(__doc__)
    cmd, rest = args[0], args[1:]
    if cmd == "clean-cache":
        kajudata.clean_cache(dry="--dry" in rest, everything="--all" in rest)
    elif cmd == "backup-self":
        kajudata.backup_self(accounts="--accounts" in rest)
    elif cmd == "people":
        kajudata.people_cmd(rest)
    elif cmd == "deploy":
        targets = [a for a in rest if a != "--reload"]
        core_users = deploy(targets)
        if "--reload" in rest:
            named = [t for t in targets if t != "kaju_core"]
            if targets:  # 写了的插件 + kaju_core 里改了的块对应的插件（它们开头的 fresh() 会换上新的）
                reload(list(dict.fromkeys(named + core_users)))
            else:
                reload(sorted(p.name for p in SOURCES.iterdir() if (p / "main.py").exists()))
    elif cmd == "reload":
        reload(rest)
    else:
        if not rest:
            sys.exit(__doc__)
        config(rest[0], rest[1:])
