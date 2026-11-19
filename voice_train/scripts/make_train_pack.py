r"""造训练包第四版（2026-11-12，最后一次大规模重训用；以后只在这个格式上微调 / 偏好纠正）。

和第三版（make_train_pack_v3.py）的区别（决定 17 / 18 / 19，见决定记录）：
  - 所有卡删掉“长短：”那一行。
  - 人工样本：数据里去重成 1 份（原来同一条最多写了 3 份，再乘 run_all 的 --curated-repeat 3，最多看 9 遍，8b-A 背答案），
    run_all 里改成 --curated-repeat 2 → 每条实际看 2 遍（决定 17）。
  - 加进第八批（data\gold8\train.jsonl，17 条）和兄长改定的 30 / 36（review8_selfrec_drafts.json）。
    视频讲的就是她自己 / 兄长的几条（22 / 26 / 30 / 31 / 36），“局面”里写明（决定 18）。
  - 心情那一行（决定 19）：K 层（stage2）和考题约七成的行在卡的最后加一行 `心情：…`，用线上同一个函数
    （bot_setup\kaju_core\heart\mood_line.py）从心情读数生成；原作读数在 data\novel_mood，人工样本 / 考题在 data\chat_mood。
    哪些行带由 id 的哈希定（每次造包都一样）。H 层（stage1，群聊 / 贴吧等别人说的话）不带。
  - 偏好训练的数据进包（data\prefs\）：成对 dpo.jsonl（第八批 48、删要点 383、以前的 481 换成新格式卡）、单条 kto.jsonl（挖出的 142 句 bad）、
    留出 heldout.jsonl（成对里按对话留 1/10，只用来量）。每对有权重 w：线上那几批和第八批 2，删要点 0.5，其它 1。
  - 考题 eval.jsonl：原来 53 题 + 第八批留出的 8 题（scene=看完感想），同样去长短、七成带心情行。

用法（AstrBot venv 或 voice_train venv）：python -I make_train_pack.py [--no-zip] [--full]
  --full：一键训练包（兄长 11-12 要的）：把包里的 python\（独立 Python + 训练用的库）和 models\Qwen3-8B 一起打进去，
          对方解压后双击 run.bat 就开训，不装、不下载。大文件不压缩（压了也小不了多少，还慢），约 24GB。
输出 voice_train\train_pack\kaju_train_pack\data\ 和 kaju_train_pack.zip；上一版数据备份在 train_pack\_backup_pack_v3_data\。
"""
import collections
import glob
import hashlib
import json
import os
import re
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8")
VT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(VT), "bot_setup"))
from kaju_core.heart.mood_line import mood_line  # noqa: E402  线上同一个函数

SRC = os.path.join(VT, "data", "layered_v3")
DATA = os.path.join(VT, "data")
PACK = os.path.join(VT, "train_pack", "kaju_train_pack")
KEEP = ("src", "id", "group", "ctx", "target", "card", "scene")
SKIP_DIRS = {".venv", "out", "out_smoke", "results", "results_smoke", "models", "__pycache__"}
MOOD_SHARE = 0.7

# 决定 18：视频讲的就是她自己 / 兄长时，“局面”里写明
SELF_NOTE = {
    "gold-r8-22_browse": "讲的就是佳树自己（《败犬女主太多了！》里的温水佳树）",
    "gold-r8-26_browse": "讲的就是佳树自己（《败犬女主太多了！》里的温水佳树）",
    "gold-r8-31_browse": "讲的就是兄长大人（《败犬女主太多了！》里的温水和彦）",
}
# 30 / 36：兄长没看过视频，Claude 看完代写、兄长改定（review8_selfrec_drafts.json）；卡照第八批的格式手写
SELFREC_CARDS = {
    "r8-30_browse": "场合：私聊\n对象：兄长大人\n局面：佳树自己刷B站刷到一个视频《假如向佳树告白会发生什么？》（同人动画），讲的就是佳树自己（《败犬女主太多了！》里的温水佳树），刚从头看完；兄长大人问她刚才刷到什么。轮到佳树回。\n要说到的：视频讲的是假如向佳树告白的故事（害羞）；把佳树说没人比兄长大人更棒的那段做成了动画（害羞）；把佳树画成黑掉的眼睛（生气）；数择偶条件那段不想让兄长大人看（害羞）",
    "r8-36_browse": "场合：私聊\n对象：兄长大人\n局面：佳树自己刷B站刷到一个视频《一个“普通”女生眼里的温水和彦》（旁白短片），讲的就是兄长大人（《败犬女主太多了！》里的温水和彦），刚从头看完；兄长大人问她刚才刷到什么。轮到佳树回。\n要说到的：一个女生讲她眼里的兄长大人（开心）；说兄长大人像教室的墙一样安静、有人难过会默默递纸巾、对方不想被打扰就退开（认同）；说兄长大人像背景板（生气）；好奇这个女生是谁、想面试她（好奇）",
}


def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()] if os.path.exists(path) else []


def dump(path, rows, keep=KEEP):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps({k: r[k] for k in keep if k in r}, ensure_ascii=False) + "\n")


def strip_length(card):
    return "\n".join(x for x in str(card).split("\n") if not x.startswith("长短："))


def picked(key):
    """这一行带不带心情行：按 key 的哈希定，每次造包都一样。"""
    h = int(hashlib.md5(str(key).encode("utf-8")).hexdigest()[:8], 16)
    return (h % 1000) / 1000 < MOOD_SHARE


def with_mood(card, snap, key):
    line = mood_line(snap) if snap and picked(key) else ""
    return (card + "\n" + line) if line else card


def base_id(i):
    return re.sub(r"-\d+$", "", str(i))


def main():
    out = os.path.join(PACK, "data")
    os.makedirs(out, exist_ok=True)
    novel_mood = {r["id"]: r["snapshot"] for r in load(os.path.join(DATA, "novel_mood", "labels.jsonl"))}
    chat_mood = {r["key"]: r["snapshot"] for r in load(os.path.join(DATA, "chat_mood", "labels.jsonl"))}

    # ---------- H 层：去重、去长短，不带心情
    seen, h = set(), []
    for r in load(os.path.join(SRC, "stage1.jsonl")) + load(os.path.join(SRC, "stage1_pool.jsonl")):
        k = ("|".join(r.get("ctx") or []), r["target"].strip())
        if k not in seen and r.get("card"):
            seen.add(k)
            h.append(dict(r, card=strip_length(r["card"])))

    # ---------- K 层
    s2, by_pair, miss = [], {}, collections.Counter()
    seen = set()

    def add_k(r, mood_key, snap):
        k = (tuple(r["ctx"]), r["target"].strip())
        if r["src"] != "novel":  # 只给人工样本去重（决定 17）；原作台词原来的份数是 A 版配方的一部分，不动
            if k in seen:
                return
            seen.add(k)
        card = strip_length(r["card"])
        row = dict(r, card=with_mood(card, snap, mood_key))
        if not snap:
            miss[r["src"]] += 1
        s2.append(row)
        by_pair[k] = {"snap": snap, "key": mood_key, "card_plain": card, "card": row["card"]}

    for r in load(os.path.join(SRC, "stage2.jsonl")):
        if not r.get("card"):
            continue
        if r["src"] == "novel":
            add_k(r, r["id"], novel_mood.get(r["id"]))
        else:
            key = r.get("group") or r["id"]  # 和 label_chat_mood.rows() 取 key 的方式一样（第一份）
            add_k(r, key, chat_mood.get(key))
    for r in load(os.path.join(DATA, "gold8", "train.jsonl")):
        card = r["card"]
        note = SELF_NOTE.get(base_id(r["id"]))
        if note:
            card = card.replace("，刚从头看完", "，" + note + "，刚从头看完", 1)
        add_k(dict(r, card=card, src="curated", group=base_id(r["id"])), r["id"], chat_mood.get(r["id"]))
    sr = json.load(open(os.path.join(DATA, "review8_selfrec_drafts.json"), encoding="utf-8"))
    for rid, card in SELFREC_CARDS.items():
        d = sr[rid]
        assert str(d.get("status", "")).startswith("approved"), rid
        row = {"src": "curated", "id": "gold-" + rid, "group": "gold-" + rid, "scene": "看完感想",
               "ctx": ["兄长大人：佳树刚才刷到什么了呀"], "card": card, "target": d["final"].replace(" / ", "\n")}
        add_k(row, "gold-" + rid, chat_mood.get("gold-" + rid))

    # ---------- 考题
    ev, seen = [], set()
    for p in sorted(glob.glob(os.path.join(SRC, "eval_*.jsonl"))):
        for r in load(p):
            if not r.get("card") or r["id"] in seen:
                continue
            seen.add(r["id"])
            ev.append(dict(r, card=with_mood(strip_length(r["card"]), chat_mood.get("eval:" + r["id"]), "eval:" + r["id"])))
    for r in load(os.path.join(DATA, "gold8", "eval.jsonl")):
        ev.append(dict(r, src="curated", scene="看完感想", card=with_mood(strip_length(r["card"]), chat_mood.get(r["id"]), r["id"])))

    # ---------- 偏好训练的数据
    pdir = os.path.join(out, "prefs")
    os.makedirs(pdir, exist_ok=True)
    pairs, dropped = [], collections.Counter()

    def add_pair(p, src, w):
        k = (tuple(p["ctx"]), p["chosen"].strip())
        info = by_pair.get(k)
        if not info:
            dropped[src] += 1
            return
        pairs.append({"id": p.get("id"), "src": src, "group": info["key"], "ctx": p["ctx"], "card": info["card"],
                      "chosen": p["chosen"].strip(), "rejected": p["rejected"].strip(), "w": w})

    for p in load(os.path.join(DATA, "gold8", "prefs.jsonl")):  # chosen 是 gold8 训练行的答案
        add_pair(p, "r8", 2.0)
    for p in load(os.path.join(DATA, "prefs_v2", "droppoint.jsonl")):
        add_pair(p, "drop", 0.5)
    for p in load(os.path.join(DATA, "prefs_v1", "dpo.jsonl")):  # 旧格式卡 → 换成 K 层里同一条的新格式卡
        add_pair(p, p.get("src", "v1"), 2.0 if p.get("src") in ("r4", "r5", "r6", "r7") else 1.0)
    held_groups = {g for g in {p["group"] for p in pairs} if int(hashlib.md5(str(g).encode()).hexdigest()[:8], 16) % 10 == 0}
    dpo = [p for p in pairs if p["group"] not in held_groups]
    held = [p for p in pairs if p["group"] in held_groups]
    kto = [{"id": k["id"], "src": "fresh", "ctx": k["ctx"], "card": strip_length(k["card"]), "text": k["text"],
            "label": "bad", "w": 1.0} for k in load(os.path.join(DATA, "prefs_v2", "fresh_kto.jsonl"))]
    pk = ("id", "src", "group", "ctx", "card", "chosen", "rejected", "w")
    dump(os.path.join(pdir, "dpo.jsonl"), dpo, pk)
    dump(os.path.join(pdir, "heldout.jsonl"), held, pk)
    dump(os.path.join(pdir, "kto.jsonl"), kto, ("id", "src", "ctx", "card", "text", "label", "w"))

    dump(os.path.join(out, "stage1.jsonl"), h)
    dump(os.path.join(out, "stage2.jsonl"), s2)
    dump(os.path.join(out, "eval.jsonl"), ev)
    open(os.path.join(out, "system.json"), "w", encoding="utf-8").write(open(os.path.join(SRC, "system.json"), encoding="utf-8").read())
    mood_n = sum("\n心情：" in r["card"] for r in s2)
    info = {"版本": "第四版（2026-11-12）：去长短、人工样本 1 份×curated-repeat 2、第八批、心情行、偏好数据",
            "stage1": dict(collections.Counter(r["src"] for r in h)), "stage1_total": len(h),
            "stage2": dict(collections.Counter(r["src"] for r in s2)), "stage2_total": len(s2),
            "stage2_带心情行": mood_n, "stage2_没有心情读数": dict(miss),
            "eval": len(ev), "eval_看完感想": sum(r.get("scene") == "看完感想" for r in ev),
            "eval_带心情行": sum("\n心情：" in r["card"] for r in ev),
            "prefs": {"dpo": len(dpo), "dpo_来源": dict(collections.Counter(p["src"] for p in dpo)), "heldout": len(held),
                      "kto": len(kto), "对不上被丢的": dict(dropped)},
            "卡里还有长短的": sum("长短：" in r["card"] for r in h + s2 + ev)}
    json.dump(info, open(os.path.join(out, "info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False, indent=1))
    if "--no-zip" in sys.argv:
        return
    full = "--full" in sys.argv
    skip = SKIP_DIRS - ({"models"} if full else set())
    if full:
        for need in (os.path.join(PACK, "python", "python.exe"), os.path.join(PACK, "models", "Qwen3-8B", "config.json")):
            assert os.path.exists(need), f"一键包缺 {need}"
    zp = os.path.join(VT, "train_pack", "kaju_train_pack_full.zip" if full else "kaju_train_pack.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
        for root, dirs, files in os.walk(PACK):
            rel_root = os.path.relpath(root, PACK)
            top = rel_root.split(os.sep)[0]
            if not full and top == "python":
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in skip and not (rel_root == "." and d == "python" and not full)]
            for f in files:
                if f.endswith((".log", ".zip", ".bak")) or (f.endswith(".pyc") and top != "python"):
                    continue
                p = os.path.join(root, f)
                big = os.path.getsize(p) > 20 * 2**20 or top in ("python", "models")
                z.write(p, os.path.join("kaju_train_pack", os.path.relpath(p, PACK)),
                        compress_type=zipfile.ZIP_STORED if big else zipfile.ZIP_DEFLATED)
    print(f"{zp}  {os.path.getsize(zp) / 2**20:.1f}MB")


if __name__ == "__main__":
    main()
