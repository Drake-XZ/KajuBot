"""meme_manager 本地补丁的离线检查（patches/meme_manager-local.patch）。

从部署好的插件源码里把打过补丁的几个方法抠出来（ast），配上假的 self，在真实表情包数据上跑（只读）：
  1. 提示词：别名分类（category_aliases.json）不列出来，大分类还在；没有图的分类不列。
  2. 取图：她写大分类时，别名目录里的图也算进去；写别名本身也能取到整组图。
  3. 选图：不加权（2026-11-15 降回去），佳树表情包和其他包一样按包均分，不按图片张数（ATRI 500 多张不会挤掉小包）；
     提示词里不再附「亲手添加的表情」。
用法：venv python -I tests/test_meme_patch.py
"""

import ast
import json
import logging
import random
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CORE = Path(r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core\data")
PLUGIN = CORE / "plugins" / "meme_manager"
DATA = CORE / "plugin_data" / "meme_manager"
EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def grab(path: Path, names: set[str]) -> str:
    """Source of the named methods (dedented) from a plugin file."""
    src = path.read_text(encoding="utf-8")
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            out.append(ast.get_source_segment(src, node))
    assert len(out) == len(names), f"没找到全部方法: {names}"
    return "\n\n".join(out)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def real_context() -> dict:
    """Same shape as resolver.resolve_pack_context for the default rule (enough for these methods)."""
    rules = load_json(DATA / "selection_rules.json", {})
    ids = next(r["pack_ids"] for r in rules["rules"] if r["scope"] == "default")
    dirs = {i: DATA / "packs" / i for i in ids}
    merged = {}
    for i in reversed(ids):
        merged.update(load_json(dirs[i] / "memes_data.json", {}))
    merged.pop("needs_review", None)
    return {"pack_id": ids[0], "pack_ids": ids, "pack_dirs": dirs, "pack_dir": dirs[ids[0]],
            "memes_dir": dirs[ids[0]] / "memes", "category_mapping": merged}


ns = {
    "Path": Path, "json": json, "random": random, "logger": logging.getLogger("t"),
    "IMAGE_EXTENSIONS": EXTS, "REVIEW_CATEGORY": "needs_review", "PLUGIN_DATA_DIR": DATA,
    "runtime_category_mapping": lambda m: dict(m),
    "dict_to_string": lambda d: "\n".join(f"{k} - {v}" for k, v in d.items()),
    "resolve_safe_category_directory": lambda root, name: Path(root) / name,
    "AstrMessageEvent": object, "ProviderRequest": object,
}
methods = grab(PLUGIN / "mixins" / "event_handlers.py", {"_get_category_meme_files", "_category_aliases", "_pick_weighted_meme"})
methods += "\n\n" + grab(PLUGIN / "main.py", {"_apply_request_prompt", "_own_pack_category_note"})
body = "\n".join("    " + line for line in methods.splitlines())
exec(
    "class Fake:\n"
    "    PRIMARY_PACK_WEIGHT = None\n"
    "    OWN_PACK_NOTE = False\n"
    "    CATEGORY_ALIASES_FILE = PLUGIN_DATA_DIR / 'category_aliases.json'\n"
    "    emotion_llm_enabled = False\n"
    "    def _semantic_pack_ready(self, **kw): return False\n"
    "    def _remove_semantic_tool(self, req): pass\n"
    "    def _resolve_runtime_pack_context(self, event=None, req=None): return CTX\n"
    "    def _build_meme_prompt(self, s): return s\n"
    "    def _wrap_meme_prompt(self, p): return '<<' + p + '>>'\n"
    "    def _strip_meme_prompt(self, p): return (p or '').split('<<')[0]\n"
    + body,
    ns,
)
CTX = real_context()
ns["CTX"] = CTX
me = ns["Fake"]()
aliases = me._category_aliases()
fails = []


def check(ok: bool, what: str) -> None:
    print(("  ok  " if ok else "  FAIL") + " " + what)
    if not ok:
        fails.append(what)


class Req:
    system_prompt = "人设"
    session_id = ""


req = Req()
me._apply_request_prompt(req, None)
shown = [line.split(" - ")[0] for line in req.system_prompt.split("<<")[1].split("\n") if " - " in line]
print(f"提示词里的分类 {len(shown)} 个: {', '.join(shown)}")
check(req.system_prompt.startswith("人设<<"), "人设保留，表情提示接在后面")
check(not any(k in shown for k in aliases if aliases[k] in shown), "别名分类不在提示词里")
check(all(aliases[k] in shown for k in aliases if k in CTX["category_mapping"]), "别名对应的大分类都在")
check("默认分类" not in shown, "没有图的分类不列")
check("亲手添加的表情" not in req.system_prompt, "不再附「亲手添加的表情」优先提示")

eating = me._get_category_meme_files(None, "eating")
food_dirs = [d / "memes" / "food" for d in CTX["pack_dirs"].values() if (d / "memes" / "food").is_dir()]
n_food = sum(1 for d in food_dirs for f in d.iterdir() if f.suffix.lower() in EXTS)
check(n_food > 0 and sum(1 for f in eating if f.parent.name == "food") == n_food, f"写 eating 时 food 目录的 {n_food} 张也算进去（共 {len(eating)} 张）")
check(len(me._get_category_meme_files(None, "food")) == len(eating), "写别名 food 也拿到整组")
happy_names = {"happy"} | {k for k, v in aliases.items() if v == "happy"}
n_happy = sum(1 for d in CTX["pack_dirs"].values() for c in happy_names if (d / "memes" / c).is_dir()
              for f in (d / "memes" / c).iterdir() if f.suffix.lower() in EXTS)
check(n_happy > 0 and len(me._get_category_meme_files(None, "happy")) == n_happy, f"普通分类照常（happy 共 {n_happy} 张）")

# 选图：happy 主包有 3 张
random.seed(7)
happy = me._get_category_meme_files(None, "happy")
packs = Counter(Path(me._pick_weighted_meme(None, happy)).parents[2].name for _ in range(3000))
spread = max(packs.values()) / min(packs.values())
n_packs = len({Path(f).parents[2].name for f in happy})
own = packs["kaju_memes"] / 3000
print("happy 选图分布:", dict(packs.most_common()))
check(abs(own - 1 / n_packs) < 0.05, f"佳树表情包不加权，约 1/{n_packs}（{own:.1%}）")
check(spread < 1.6, f"所有包大致均分（最多/最少 = {spread:.2f}）")

# 佳树表情包这类没图：其他包均分
sad = me._get_category_meme_files(None, "sad")
cnt = Counter(Path(me._pick_weighted_meme(None, sad)).parents[2].name for _ in range(1500))
sad_packs = {Path(f).parents[2].name for f in sad}
check("kaju_memes" not in sad_packs and len(sad_packs) >= 2 and set(cnt) == sad_packs,
      f"主包没图时在有这类图的其他 {len(sad_packs)} 个包里都挑得到")

print("全部通过" if not fails else f"{len(fails)} 项没通过")
sys.exit(1 if fails else 0)
