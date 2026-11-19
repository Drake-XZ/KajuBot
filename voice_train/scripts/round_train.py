r"""本机小步纠正 · 第二步：兄长的标注 → 训练数据 → 本机训 → 导入 Ollama → 考试 → 盲选页（2026-11-12 写）。
方法和注意事项见 voice_train\本机微调方案-20261112.md；第一步是 round_pick.py。**不自动上线**：上线要兄长盲选点头后手动换。

前提：兄长标完 round_pick 做的标注页，Claude 用 ArtifactData list 把 collection "labels" 存到 data\rounds_v4\r<N>\labels（out_dir）。

  python -I -X utf8 scripts\round_train.py data   --round N   标注 → data\rounds_v4\r<N>\data\（pref.py 吃的格式）
  python -I -X utf8 scripts\round_train.py train  --round N   本机 4060 训（默认 60 步约 1 小时 10 分钟；先把 Ollama 里的模型卸下，她回话会变慢）
  python -I -X utf8 scripts\round_train.py import --round N   合并 → GGUF → Ollama：kaju-writer-p4-8b-r<N>（约 20 分钟）
  python -I -X utf8 scripts\round_train.py exam   --round N   exam_p3.py 61 题（约 40 分钟；评判 11-13 起用 Gemini；线上那个的成绩不是 Gemini 判的就一起重考），和线上那个的成绩并排比
  python -I -X utf8 scripts\round_train.py ab     --round N   盲选页 review\round_r<N>_ab.html（新 vs 线上，各写一遍，A/B 随机）
  python -I -X utf8 scripts\round_train.py all    --round N   data → train → import → exam → ab 一口气跑完
兄长盲选点头后上线（这个脚本只打印命令、记 state，不替他换）：
  python -I -X utf8 scripts\round_train.py live   --round N

三种训练信号（兄长 11-12 定的做法）：
  - 认可（ok）          → 正例：进 stage2 复习（照着学）+ KTO good
  - 改写（text≠原句）   → 正例 + 成对（他的写法 好于 原句，DPO，权重 2）。先问 Gemini（11-13 前是 DeepSeek）他的写法照线上那张卡算不算说得通（AGREE）；
                          不算（他改了要说的事）就用 Gemini 照他的写法重新整理一张卡（同 EXTRACT_V4，心情行沿用线上那张）——
                          训练卡必须把答案里的事都列出来，否则写手学会编。
  - 不要（skip）        → KTO bad（权重 1.5）
  - 自动反例 auto_bad   → 线上核对拦下的那几遍（编造 / 漏点 / 叫错人，对错类）+ 同一个词说了三遍以上的（src repeat，11-13 加），KTO bad，最多 3 倍于兄长标的条数
每轮还混：训练包 prefs 里随机 100 对旧成对（权重 0.5）、原作台词和以前的人工样本（pref.py 的复习 anchor），防止丢口吻。
改写的每 5 条留 1 条做留出题（不进训练），看“比起点更偏向兄长写法”涨到多少。
防崩（11-12 R 的教训：2e-5 训了 206 大步就打转、念心情行、编身世）：lr 5e-6、最多 2 轮、--max-steps 60（默认）；
原作台词损失比起点涨 5% 以上、或兄长写法的留出损失变差，报告里标红，不建议上。
“比起点更偏向”只当参考：11-13 试跑 2 步就到 0.67（它只看方向不看幅度），不能拿它当停的信号；真正的闸门是考试（打转、漏答、编造）和盲选。
用时（11-13 试跑实测，RTX 4060 笔记本）：加载 + 算起点 + 量留出题约 8 分钟，之后每步约 1 分钟（4 对 + 2 条 + 4 条复习）——默认 60 步约 1 小时 10 分钟。
"""
import argparse
import asyncio
import glob
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
VT = os.path.dirname(HERE)
ROOT = os.path.join(VT, "data", "rounds_v4")
STATE = os.path.join(ROOT, "state.json")
PACK = os.path.join(VT, "train_pack", "kaju_train_pack")
PY_TRAIN = os.path.join(VT, "venv", "Scripts", "python.exe")
# K 接在哪个 H 上训：照 state.json 的 live_base_h / live_h_adapter（r6 上线时写的）；没写才用下面的默认。
# 11-18 整理删了 p4 的底子 models\Qwen3-8B-H-p4（要接着训 p4 那条线得用 Qwen3-8B + p4 的 H 重新合出来）
BASE_H = os.path.join(VT, "models", "Qwen3-8B-H-r6")          # 原模型 + r6 的 H（本机微调的底子）
BASE = os.path.join(VT, "models", "Qwen3-8B")
H_ADAPTER = os.path.join(ROOT, "r6", "H", "best")


def base_h(st):
    return st.get("live_base_h") or BASE_H


def h_adapter(st):
    return st.get("live_h_adapter") or H_ADAPTER
OLLAMA = "http://127.0.0.1:11435"
sys.path.insert(0, HERE)
sys.path.insert(0, r"D:\JiashuBot\bot_setup")
os.environ.setdefault("KAJU_DATA", r"D:\JiashuBot\kaju_data")


def rdir(n):
    return os.path.join(ROOT, f"r{n}")


def state():
    return json.load(open(STATE, encoding="utf-8"))


def save_state(st):
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def jl(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()] if os.path.exists(path) else []


def wjl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def lines(t):
    """页面上几条之间用 / 隔开（和线上分条发一样）→ 换行；去掉句号和空行（同 make_gold6）。"""
    t = re.sub(r"\s*[/／]\s*", "\n", str(t or "").strip())
    t = re.sub(r"。+(?=.)", "\n", t).replace("。", "")
    return "\n".join(x.strip() for x in t.split("\n") if x.strip())


def labels_of(n):
    out = {}
    for p in glob.glob(os.path.join(rdir(n), "labels", "**", "*.json"), recursive=True):
        d = json.load(open(p, encoding="utf-8"))
        out[os.path.splitext(os.path.basename(p))[0]] = d.get("data", d) if isinstance(d, dict) else {}
    return out


# ------------------------------------------------------------------ data
async def make_data(n):
    import build_layered as bl  # AGREE（2026-11-13 兄长：换 Gemini）
    bl.use_gemini()
    from kaju_core.senses import omni
    from kaju_core.voice import card

    ip = os.path.join(rdir(n), "items.json")
    items = {it["id"]: it for it in json.load(open(ip, encoding="utf-8"))} if os.path.exists(ip) else {}
    lb = labels_of(n)
    has_gold = os.path.exists(os.path.join(rdir(n), "gold.jsonl"))
    if not lb and not has_gold:
        sys.exit(f"{rdir(n)}\\labels 里没有标注：先用 ArtifactData list 把 collection labels 存下来")
    # 11-14 第 2 轮：兄长要先只用盲选备注（gold.jsonl）训，线上标注没有也行
    ok, rew, bad = [], [], []
    for iid, v in lb.items():
        it = items.get(iid)
        if not it or not isinstance(v, dict):
            continue
        if v.get("skip"):
            bad.append(it)
        elif v.get("ok") or lines(v.get("text")) == lines(it["reply_raw"]):
            ok.append(it)
        elif str(v.get("text") or "").strip():
            rew.append((it, lines(v["text"])))
    print(f"标注：认可 {len(ok)}、改写 {len(rew)}、不要 {len(bad)}（共 {len(items)} 条）", flush=True)
    # 可选 r<N>\focus.json（11-13 兄长：重复 / 多余不准的话重点学，改动小的放宽）——格式见 r1\focus.json 的 _说明
    fp = os.path.join(rdir(n), "focus.json")
    fc = json.load(open(fp, encoding="utf-8")) if os.path.exists(fp) else {}
    focus, light = set(fc.get("focus") or []), set(fc.get("light") or [])
    w_focus, w_light = float(fc.get("w_focus", 3.0)), float(fc.get("w_light", 1.0))
    copies, auto_w = int(fc.get("focus_copies", 1)), float(fc.get("auto_focus_w", 1.0))
    if fc:
        print(f"focus.json：重点 {len(focus)} 条（权重 {w_focus}×{copies} 份）、放宽 {len(light)} 条（权重 {w_light}）", flush=True)

    async def card_for(it, text, force=False):
        """他的写法照线上那张卡说得通就用那张；说不通就照他的写法重新整理（心情行沿用）。
        force：重点条（他删了卡上的点）一律重新整理——AGREE 允许“省掉次要的点”，留着旧卡写手会学成漏点。"""
        agree = False
        if not force:
            m = re.search(r"\{.*\}", await bl.ask(bl.AGREE, f"要点卡：\n{it['card']}\n\n回复：\n{text}", 0.0) or "", re.S)
            try:
                agree = bool(json.loads(m.group(0)).get("ok")) if m else True
            except ValueError:
                agree = True
        if agree:
            return it["card"], False
        try:
            out, _ = await omni.text(card.EXTRACT_V4, card.extract_prompt_v4(it["train_ctx"], text, it["kind"], it["to"]), timeout=40)
            g = card.parse_v4(out)
        except Exception as e:  # noqa: BLE001
            print("  重新整理卡没成（用线上那张）", it["id"], type(e).__name__, flush=True)
            return it["card"], False
        if not g:
            return it["card"], False
        mood = next((x for x in it["card"].splitlines() if x.startswith("心情：")), "")
        return card.render_v4(it["kind"], it["to"], g, mood), True

    cards = await asyncio.gather(*[card_for(it, t, it["id"] in focus) for it, t in rew])
    sft, pairs, held, kto = [], [], [], []
    rew_sorted = sorted(zip(rew, cards), key=lambda x: x[0][0]["t"])
    # 留出题：每 5 条留 1 条；有 focus.json 时先从“放宽”的里挑（重点条都进训练）
    n_held = len(rew_sorted) // 5
    pool = [x[0][0]["id"] for x in rew_sorted if x[0][0]["id"] in light] if fc else []
    held_ids = set(pool[::max(1, len(pool) // n_held)][:n_held]) if pool and n_held else \
        {x[0][0]["id"] for k, x in enumerate(rew_sorted) if k % 5 == 4}
    for (it, text), (ct, recarded) in rew_sorted:
        row = {"id": f"live-r{n}-{it['t']}", "src": "live", "group": f"live-r{n}-{it['t']}", "ctx": it["train_ctx"], "card": ct}
        is_focus = it["id"] in focus
        w = w_focus if is_focus else w_light if it["id"] in light else 2.0
        pair = {**row, "chosen": text, "rejected": it["reply_raw"], "w": w, "recarded": recarded, "focus": is_focus}
        if it["id"] in held_ids:
            held.append(pair)  # 留出题：不进训练
            continue
        pairs += [pair] * (copies if is_focus else 1)
        sft.append({**row, "target": text})
        if is_focus:  # 原句当反例、他的写法当正例（KTO 是绝对的推拉，DPO 只管相对）
            kto.append({**row, "text": it["reply_raw"], "label": "bad", "w": 2.0, "src": "focus"})
            kto.append({**row, "text": text, "label": "good", "w": 1.5, "src": "focus"})
    for it in ok:
        row = {"id": f"live-r{n}-{it['t']}", "src": "live", "group": f"live-r{n}-{it['t']}", "ctx": it["train_ctx"], "card": it["card"]}
        sft.append({**row, "target": it["reply_raw"]})
        kto.append({**row, "text": it["reply_raw"], "label": "good", "w": 1.0})
    for it in bad:
        kto.append({"id": f"live-r{n}-{it['t']}", "src": "live", "ctx": it["train_ctx"], "card": it["card"],
                    "text": it["reply_raw"], "label": "bad", "w": 1.5})
    # prepare_r2.py 这类额外的金数据（11-14：兄长两次盲选写的备注）：金句进复习、成对进 DPO（每 5 条留 1 条量偏向）、单条进 KTO
    gold_x = sorted(jl(os.path.join(rdir(n), "gold.jsonl")), key=lambda r: r["id"])
    held_gold = {g["id"] for k, g in enumerate(gold_x) if k % 5 == 4}
    sft += [{k: g[k] for k in ("id", "src", "group", "ctx", "card", "target")} for g in gold_x if g["id"] not in held_gold]
    for p in jl(os.path.join(rdir(n), "pairs.jsonl")):
        (held if p["id"] in held_gold else pairs).append(p)
    kto += jl(os.path.join(rdir(n), "kto.jsonl"))
    # 金句混在两三千条复习里一轮只轮得到零点几次：也当 KTO 正例（权重和别的一样，不加重——第 1 轮的教训）
    kto += [{"id": g["id"], "src": "gold", "ctx": g["ctx"], "card": g["card"], "text": g["target"], "label": "good", "w": 1.0}
            for g in gold_x if g["id"] not in held_gold]
    if gold_x:
        print(f"额外金数据：金句 {len(gold_x)}（留出 {len(held_gold)}）、成对 {sum(p['id'] not in held_gold for p in jl(os.path.join(rdir(n), 'pairs.jsonl')))}", flush=True)
    auto = jl(os.path.join(rdir(n), "auto_bad.jsonl"))
    if auto_w != 1.0:  # 重复、加了草稿没有的事 / 说错的：兄长要重点纠正的那类
        hot = re.compile(r"加了|捏造|虚构|篡改|说错|误说|胡言乱语")
        auto = [dict(a, w=auto_w) if a.get("src") == "repeat" or hot.search(a.get("why") or "") else a for a in auto]
    random.Random(n).shuffle(auto)
    kto += auto[:max(10, 3 * (len(bad) + len(rew)))]
    rng = random.Random(1000 + n)
    old = jl(os.path.join(PACK, "data", "prefs", "dpo.jsonl"))
    replay = [dict(p, w=0.5) for p in rng.sample(old, min(100, len(old)))]
    old_held = jl(os.path.join(PACK, "data", "prefs", "heldout.jsonl"))
    held_all = held + rng.sample(old_held, min(30, len(old_held)))

    d = os.path.join(rdir(n), "data")
    os.makedirs(os.path.join(d, "prefs"), exist_ok=True)
    shutil.copy2(os.path.join(PACK, "data", "system.json"), os.path.join(d, "system.json"))
    stage2 = jl(os.path.join(PACK, "data", "stage2.jsonl"))
    for p in sorted(glob.glob(os.path.join(ROOT, "r*", "sft.jsonl"))):  # 以前各轮兄长认可 / 改写的也一起复习
        if os.path.dirname(p) != rdir(n):
            stage2 += jl(p)
    wjl(os.path.join(rdir(n), "sft.jsonl"), sft)
    stage2 += jl(os.path.join(rdir(n), "extra_stage2.jsonl"))  # 11-14 第 3 轮：带“背景”的原作复习（prepare_r3.py）
    wjl(os.path.join(d, "stage2.jsonl"), stage2 + sft)
    wjl(os.path.join(d, "prefs", "dpo.jsonl"), pairs + replay)
    wjl(os.path.join(d, "prefs", "heldout.jsonl"), held_all)
    wjl(os.path.join(d, "prefs", "kto.jsonl"), kto)
    info = {"认可": len(ok), "改写": len(rew), "不要": len(bad), "改写里重新整理卡的": sum(c[1] for c in cards),
            "成对（本轮）": len(pairs), "成对（旧的复习）": len(replay), "留出": len(held_all), "KTO": len(kto),
            "其中自动反例": sum(1 for x in kto if x.get("src") in ("guard", "repeat")),
            "其中同一个词说三遍": sum(1 for x in kto if x.get("src") == "repeat"), "复习（stage2）": len(stage2) + len(sft),
            "重点条（focus.json）": len({p["id"] for p in pairs if p.get("focus")}),
            "本轮留出的改写": [p["id"] for p in held]}
    json.dump(info, open(os.path.join(d, "info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("训练数据 →", d, info, flush=True)


# ------------------------------------------------------------------ train
def ollama_unload():
    try:
        with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=10) as r:
            names = [m["name"] for m in json.load(r).get("models", [])]
    except Exception:  # noqa: BLE001
        return
    for nm in names:
        try:
            urllib.request.urlopen(urllib.request.Request(OLLAMA + "/api/generate", json.dumps({"model": nm, "keep_alive": 0}).encode(),
                                                          {"Content-Type": "application/json"}), timeout=30).read()
        except Exception:  # noqa: BLE001
            pass


def train(n, max_steps, lr, epochs):
    st = state()
    out = os.path.join(rdir(n), "R")
    if os.path.exists(os.path.join(out, "run.json")):
        sys.exit(f"{out} 已经训过了（有 run.json）")
    ollama_unload()
    from kaju_core import gpu_busy  # 训练这段时间她先不回群聊（标记文件；这个进程不在了 / 超过 6 小时自动失效）
    gpu_busy.mark(f"训练第 {n} 轮写手")
    cmd = [PY_TRAIN, "-s", os.path.join(PACK, "pref.py"), "--base", base_h(st), "--init-adapter", st["live_adapter"],
           "--out", out, "--data-dir", os.path.join(rdir(n), "data"), "--bits", "4", "--lowmem", "--grad-ckpt",
           "--lr", str(lr), "--epochs", str(epochs), "--pairs", "4", "--kto", "2", "--sft", "4", "--max_steps", str(max_steps)]
    env = {**os.environ, "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
           "PYTORCH_CUDA_ALLOC_CONF": "max_split_size_mb:128"}  # 少留碎片（Windows 不支持 expandable_segments）
    print("训练：", " ".join(os.path.basename(c) if i < 2 else c for i, c in enumerate(cmd)), flush=True)
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=PACK, env=env)
    finally:
        gpu_busy.clear()
    if p.returncode:
        sys.exit(f"训练失败（{p.returncode}），看 {out}\\train_log.txt")
    run = json.load(open(os.path.join(out, "run.json"), encoding="utf-8"))
    m0, m1 = run["metrics"][0], run["metrics"][-1]
    warn = []
    if m0.get("原作台词损失") and m1.get("原作台词损失", 0) > m0["原作台词损失"] * 1.05:
        warn.append("原作台词损失比起点涨了 5% 以上（口吻在丢）")
    if m0.get("留出兄长写法损失") and m1.get("留出兄长写法损失", 0) > m0["留出兄长写法损失"] * 1.02:
        warn.append("兄长写法的留出损失变差了（没学到他的写法）")
    st["rounds"].setdefault(str(n), {}).update({"trained_at": time.strftime("%Y-%m-%d %H:%M"), "minutes": round((time.time() - t0) / 60, 1),
                                                "metrics_start": m0, "metrics_end": m1, "warn": warn})
    save_state(st)
    print(f"训完 {(time.time() - t0) / 60:.0f} 分钟：起点 {m0}\n结束 {m1}\n" + ("！！" + "；".join(warn) if warn else "防崩检查都过了"), flush=True)


# ------------------------------------------------------------------ import
def model_name(n):
    return f"kaju-writer-p4-8b-r{n}"


def do_import(n):
    sys.argv = sys.argv[:1]
    import daily_learn as dl  # make_gguf：合并、转换、量化、导入
    dl.BASE = BASE
    dl.TEMPLATE = os.path.join(VT, "models", "kaju-writer-p3-8b.Modelfile")  # 8B 带空 <think></think> 的模板
    ad = os.path.join(rdir(n), "R", "last")
    if not os.path.exists(os.path.join(ad, "adapter_config.json")):
        sys.exit(f"没有训好的 {ad}")
    out = os.path.join(rdir(n), "gguf")
    os.makedirs(out, exist_ok=True)
    ollama_unload()
    print(f"{model_name(n)}：Qwen3-8B → H → 第 {n} 轮的 K", flush=True)
    dl.make_gguf(model_name(n), out, [h_adapter(state()), ad], os.path.join(out, "import.log"))
    print(f"{model_name(n)} 导入好了", flush=True)


# ------------------------------------------------------------------ exam
def summary(model):
    path = os.path.join(VT, "data", f"exam_p3_{model}.json")
    if not os.path.exists(path):
        return None
    its = json.load(open(path, encoding="utf-8"))
    excl = os.path.join(ROOT, "exam_exclude.json")  # 进了训练的考试题两边都不算（11-14）
    skip = set(json.load(open(excl, encoding="utf-8")).get("ids") or []) if os.path.exists(excl) else set()
    its = [it for it in its if it.get("id") not in skip]
    s = {"题数": len(its), "漏答": 0, "编造": 0, "硬伤": 0, "有漏": 0, "说错": 0, "自然赢": 0, "自然输": 0, "佳树赢": 0, "佳树输": 0, "打转": 0}
    from kaju_core.voice import card
    for it in its:
        for v in it.get("verdicts") or []:
            s["漏答"] += bool(v.get("new漏答"))
            s["编造"] += bool(v.get("new编造"))
            s["自然赢"] += v.get("自然") == "new"
            s["自然输"] += v.get("自然") == "old"
            s["佳树赢"] += v.get("佳树") == "new"
            s["佳树输"] += v.get("佳树") == "old"
        s["硬伤"] += sum(bool(f) for f in it.get("flags_new") or [])
        s["有漏"] += sum(c.get("漏", 0) > 0 for c in it.get("cover") or [])
        s["说错"] += sum(c.get("错", 0) > 0 for c in it.get("cover") or [])
        s["打转"] += sum(card.loops(x) for x in it.get("new") or [])
    return s


def exam(n):
    st = state()
    ollama_unload()
    py = sys.executable
    # 线上那个的成绩要是别的评判判的（11-13 前是 DeepSeek），这次一起重考，两边同一个评判才能并排比
    extra = os.path.join(VT, "data", f"exam_p3_{st['live_model']}_extra.json")
    try:
        live_judge = json.load(open(extra, encoding="utf-8")).get("judge", "deepseek")
    except (OSError, ValueError):
        live_judge = ""
    models = [model_name(n)] + ([st["live_model"]] if live_judge != "gemini" else [])
    if len(models) > 1:
        print(f"线上 {st['live_model']} 的成绩是 {live_judge or '没有'} 判的，这次和第 {n} 轮一起用 Gemini 重考", flush=True)
    p = subprocess.run([py, "-I", "-X", "utf8", os.path.join(HERE, "exam_p3.py"), *models], cwd=VT)
    if p.returncode:
        sys.exit("考试没跑完")
    a, b = summary(st["live_model"]), summary(model_name(n))
    lines_ = [f"| 项 | 线上 {st['live_model']} | 第 {n} 轮 {model_name(n)} |", "|---|---|---|"]
    for k in (b or {}):
        lines_.append(f"| {k} | {(a or {}).get(k, '?')} | {b[k]} |")
    rep = os.path.join(rdir(n), "exam.md")
    open(rep, "w", encoding="utf-8").write("考试（都对 r003 判；看两边的数并排比）\n\n" + "\n".join(lines_) + "\n")
    st["rounds"].setdefault(str(n), {})["exam"] = {"live": a, "new": b}
    save_state(st)
    print("\n".join(lines_), "\n→", rep, flush=True)
    print("闸门：漏答、编造、硬伤、打转都不比线上多，才往下做盲选。", flush=True)


# ------------------------------------------------------------------ ab
def write(model, ctx, card_text):
    from kaju_core.voice import card, rewrite
    body = {"model": model, "temperature": 0.7, "top_p": 0.9, "max_tokens": 1024, "reasoning_effort": "none",
            "messages": [{"role": "system", "content": card.SYSTEM_V4}, {"role": "user", "content": card.write_prompt_v4(ctx, card_text)}]}
    req = urllib.request.Request(OLLAMA + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                out = rewrite.clean_output(json.load(r)["choices"][0]["message"]["content"]).strip()
            if out and not card.loops(out):
                return out
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return ""


def ab(n, count):
    """盲选：留出题（他改写过、没进训练的）+ 线上新近没挑过的回复，同一张卡两边各写一遍。"""
    import round_pick as rp
    st = state()
    new = model_name(n)
    rows = [{"ctx": p["ctx"], "card": p["card"], "kind": "群聊" if "场合：群聊" in p["card"] else "私聊", "ref": p["chosen"]}
            for p in jl(os.path.join(rdir(n), "data", "prefs", "heldout.jsonl")) if str(p.get("id", "")).startswith(f"live-r{n}-")]
    picked = set(map(str, st.get("picked", [])))
    fresh = []
    for r in rp.records():
        c, ctx = rp.parse(r.get("card")), rp.parse(r.get("ctx"))
        ct = (c[0].get("card") if c else "") or ""
        if "局面：" in ct and r.get("outcome") == "used" and str(r.get("t")) not in picked:
            fresh.append({"ctx": ctx, "card": ct, "kind": r.get("kind", "私聊"), "ref": "", "t": r["t"]})
    fresh.sort(key=lambda x: -x["t"])
    rows = (rows + fresh)[:count]
    rng = random.Random(77 + n)
    page, key = [], {}
    for i, r in enumerate(rows):
        a, b = write(st["live_model"], r["ctx"], r["card"]), write(new, r["ctx"], r["card"])
        if not a or not b or a == b:
            continue
        iid = f"r{n}ab-{len(page) + 1}"
        order = ["live", "new"]
        rng.shuffle(order)
        texts = {"live": a, "new": b}
        key[iid] = {"A": order[0], "B": order[1], "live": st["live_model"], "new": new}
        to = next((x.split("：", 1)[1] for x in r["card"].splitlines() if x.startswith("对象：")), "")
        page.append({"id": iid, "n": len(page) + 1, "src": "group" if r["kind"] == "群聊" else "private", "to": to or "无",
                     "draft": r["ref"] or next((x.split("：", 1)[1] for x in r["card"].splitlines() if x.startswith("要说到的：")), ""),
                     "draft_label": "兄长改写的那版（留出题）" if r["ref"] else "卡上要说到的",
                     "ctx": r["ctx"][-6:] or ["（没有前文）"], "A": {"text": texts[order[0]], "blocked": ""}, "B": {"text": texts[order[1]], "blocked": ""}})
        print(f"  {len(page)} 对", flush=True)
    json.dump(key, open(os.path.join(rdir(n), "ab_key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(VT, "review", "round_ab.template.html"), encoding="utf-8").read()
    html = os.path.join(VT, "review", f"round_r{n}_ab.html")
    open(html, "w", encoding="utf-8", newline="\n").write(
        tpl.replace("/*TITLE*/", f"写手盲选 · 第 {n} 轮").replace("__ITEMS__", json.dumps(page, ensure_ascii=False).replace("</", "<\\/")))
    print(f"盲选页 {html}（{len(page)} 对；发布成 Artifact：capabilities db + user，collection votes）；对照 {rdir(n)}\\ab_key.json", flush=True)


def live(n):
    st = state()
    old = st["live_model"]
    print("兄长盲选点头后，按顺序做：\n"
          f"  1. 备份：copy AstrBot 的 data\\config\\astrbot_plugin_kaju_style_config.json 到 _backup\\\n"
          f"  2. 换：%PY% -I bot_setup\\tools\\botctl.py config kaju_style rewrite.card_model={model_name(n)}\n"
          f"  3. 回滚：%PY% -I bot_setup\\tools\\botctl.py config kaju_style rewrite.card_model={old}\n"
          "  4. 看几天线上记录，没问题再开下一轮（下一轮从这一轮的 K 接着训）")
    if input("已经换上线了吗？要把 state 里的线上写手记成这一轮的吗（y/N）：").strip().lower() == "y":
        st["previous"] = {"live_model": old, "live_adapter": st["live_adapter"]}
        st["live_model"], st["live_adapter"] = model_name(n), os.path.join(rdir(n), "R", "last")
        st["rounds"].setdefault(str(n), {})["live_at"] = time.strftime("%Y-%m-%d %H:%M")
        save_state(st)
        print("记好了")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["data", "train", "import", "exam", "ab", "all", "live"])
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--max-steps", type=int, default=60)
    ap.add_argument("--lr", type=float, default=5e-6)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--ab", type=int, default=20)
    a = ap.parse_args()
    if a.cmd in ("data", "all"):
        asyncio.run(make_data(a.round))
    if a.cmd in ("train", "all"):
        train(a.round, a.max_steps, a.lr, a.epochs)
    if a.cmd in ("import", "all"):
        do_import(a.round)
    if a.cmd in ("exam", "all"):
        exam(a.round)
    if a.cmd in ("ab", "all"):
        ab(a.round, a.ab)
    if a.cmd == "live":
        live(a.round)


if __name__ == "__main__":
    main()
