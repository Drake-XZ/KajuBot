"""收语料、抽卡，外加训练脚本共用的小工具（make_gguf / run / ollama_* / hard_flags / exam_items …）。

原来是 4B 写手（kaju-writer-l1a）的“每晚自学”：收语料 → 抽卡 → 训一轮 H、K → 考试 → 过了换上线。
2026-11-18 兄长定 4B 那条线整条删：训一轮 / 重考 / 考试 / 每晚 / 自动关机这些命令和计划任务 KajuNightlyLearn 都删了
（删之前的版本在 _backup\\archive-20261118.zip）。留下的：

    （用 AstrBot 的 venv 跑，它有 openai）
    D:\\JiashuBot\\AstrBot-Data\\instances\\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\\venv\\Scripts\\python.exe -I daily_learn.py collect   收新语料：群聊 + 她刷过的 B 站视频的弹幕和评论
    ...                                                       cards        给新语料抽要点卡（deepseek-flash，关思考，约 0.001 元/条）
    ...                                                       idle-cards   空闲时段（北京 00:30～08:30）才抽卡，贴吧这种大批的只在这时抽
    ...                                                       status       语料池攒了多少

语料池（data\\daily\\pool.jsonl、cards.jsonl）是 8B 训练 H 层数据的来源之一；round_train.py、run_r7.py、import_pack_v4.py 等
从这里拿 make_gguf（合并 → GGUF → Q4_K_M → 导入 Ollama）这些工具，它们自己会把 BASE / TEMPLATE 设成 8B 的。

数据原则：
- 群聊：去掉名字、QQ 号、链接（build_layered.group_samples）。
- B 站：她自己刷过的视频（browse.json），不够时从 B 站热门补。弹幕当作"群友分享了这个视频后大家的反应"，评论楼当作"有人说了一句、另一个人接话"；
  黄段子、脏话、戾气话、广告不要；@ 的名字换掉。
- 新语料只进 H；K 只用原作台词和兄长大人认可的样本。
"""
import argparse
import asyncio
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zlib

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_layered as bl  # noqa: E402  （DeepSeek 客户端、群聊去名字、card 模块）

sys.path.insert(0, os.path.join(bl.ROOT, "bot_setup", "kaju_platforms", "bili"))  # bili.py 现在在 kaju_platforms\bili
sys.path.insert(0, os.path.join(bl.ROOT, "bot_setup", "kaju_core", "voice"))
import bili  # noqa: E402
import rewrite as live_rw  # noqa: E402

card = bl.card
VT = bl.VT
PY = os.path.join(VT, "venv", "Scripts", "python.exe")
BASE = os.path.join(VT, "models", "Qwen3-8B")  # make_gguf 合并时的原模型；8B 的脚本还会自己再设一遍
DD = os.path.join(VT, "data", "daily")
RES = os.path.join(VT, "results", "daily")
LAYERED = os.path.join(VT, "data", "layered_v1")
POOL = os.path.join(DD, "pool.jsonl")
CARDS = os.path.join(DD, "cards.jsonl")
BILI_DONE = os.path.join(DD, "bili_done.json")
STATE = os.path.join(DD, "state.json")
LLAMA = os.path.join(VT, "downloads", "llama.cpp-b11756")
CONVERT = os.path.join(LLAMA, "src", "llama.cpp-b11756", "convert_hf_to_gguf.py")
QUANT = os.path.join(LLAMA, "bin", "llama-quantize.exe")
OLLAMA = r"D:\JiashuBot\local_vision\runtime\ollama.exe"
OLLAMA_URL = "http://127.0.0.1:11435"
TEMPLATE = os.path.join(VT, "models", "kaju-writer-p3-8b.Modelfile")  # 8B 带空 <think></think> 的导入模板
CORE = bl.CORE
BOT_PY = os.path.join(os.path.dirname(CORE), "venv", "Scripts", "python.exe")
REWRITES = os.path.join(bl.PD, "astrbot_plugin_kaju_style", "rewrites")

THRESHOLD = 200       # 攒够这么多条新语料才训一轮
# 热门里不适合初三女生学说话的：政治时事、擦边、恐怖血腥
POPULAR_SKIP = re.compile(
    r"特朗普|拜登|普京|泽连斯基|选举|总统|政府|弹劾|战争|军事|导弹|台海|中美|美军|俄乌|以色列|巴勒斯坦|时政|"
    r"身体|性感|擦边|福利|热舞|丝袜|美腿|女团|写真|比基尼|Miniskirt|舞蹈|"
    r"恐怖|血腥|凶杀|命案|尸|车祸|事故", re.I)
BILI_GAP = 2.5         # B 站每次请求之间隔几秒（11-07 连着请求几十个视频后匿名请求被 412 风控，别连累她的小号）
BILI_THREADS = 3       # 每个视频整楼翻开几楼
POPULAR_PER_NIGHT = 10  # 每晚最多从 B 站热门补几个视频
POPULAR_BACKLOG = 500   # 没训过的 B 站语料超过这么多就不补
BULK_SRC = ("tieba",)  # 大批的来源：只在 DeepSeek 空闲时段抽卡（兄长大人 11-08 定：关思考、每条 2 张卡、空闲时段抽）
# 每晚自学最早的那一轮（4B，11-18 整个删了，只剩 state.json 里的旧记录）
FIRST = {"name": "kaju-writer-l1a", "h": os.path.join(VT, "results", "layered_v1", "L1_H"),
         "k": os.path.join(VT, "results", "layered_v1", "L1_K"), "round": 0}


def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def say(msg):
    print(f"[{now()}] {msg}", flush=True)


def jload(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def jsave(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def state():
    st = jload(STATE, None)
    if not st:
        st = {"current": dict(FIRST), "rounds": []}
    return st


def used_ids():
    out = set()
    for p in glob.glob(os.path.join(RES, "r*", "new_ids.json")):
        out |= set(jload(p, []))
    return out


# ====================================================================== 收语料
TOXIC = re.compile(
    r"滚|傻|脑残|弱智|智障|废物|垃圾|恶心|去死|死全家|狗东西|狗屎|nt|nmd|tmd|cnm|急了|破防|孝子|小丑|典中典|"
    r"吃屎|屁|贱|婊|黑子|喷子|引战|举报|拉黑|网暴|地域黑|骨科|乱伦|干死|干爆|弄死|杀了|自杀|跳楼|"
    r"淘宝|拼多多|加群|私信|vx|微信|qq群|关注我|求关注|互粉|抽奖|广告|链接在|评论区抽|转发",
    re.I,
)
BILI_EMOJI = re.compile(r"\[[^\[\]]{1,32}\]|（doge）|\(doge\)")
REPLY_HEAD = re.compile(r"^回复\s*@[^:：]{1,30}[:：]\s*")
AT = re.compile(r"@[^\s@:：,，。!！?？]{1,20}")


def bili_clean(text):
    t = REPLY_HEAD.sub("", text or "")
    t = re.sub(r"https?://\S+", "", t)
    t = BILI_EMOJI.sub("", t)
    t = AT.sub("群友C", t)
    t = re.sub(r"\d{5,}", "", t)
    return " / ".join(x.strip() for x in t.splitlines() if x.strip()).strip()


def bili_ok(text, lo=2, hi=60):
    if not lo <= len(text) <= hi or TOXIC.search(text) or bili._CRUDE.search(text):
        return False
    if re.fullmatch(r"[\W\d_a-zA-Z]*", text):  # 纯符号、纯英文数字（awsl、666……）
        return False
    return len(set(text)) / len(text) >= 0.4


def http_json(url, cookie=""):
    req = urllib.request.Request(url, headers={"User-Agent": BILI_UA, "Referer": "https://www.bilibili.com/",
                                               **({"Cookie": cookie} if cookie else {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


BILI_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/124.0 Safari/537.36")


def bili_cookie():
    # 2026-11-08 起登录放 kaju_data\accounts（botctl migrate）；老位置留着兜底
    acc = os.path.join(os.environ.get("KAJU_DATA") or r"D:\JiashuBot\kaju_data", "accounts", "bili_login.json")
    d = jload(acc if os.path.exists(acc) else os.path.join(bl.PD, "astrbot_plugin_kaju_basics", "bili_login.json"), {})
    ck = d.get("cookies") or {}
    if isinstance(ck, dict):
        return "; ".join(f"{k}={v}" for k, v in ck.items())
    if isinstance(ck, list):
        return "; ".join(f"{c.get('name')}={c.get('value')}" for c in ck if isinstance(c, dict))
    return str(ck)


def danmaku(cid):
    req = urllib.request.Request(f"https://comment.bilibili.com/{int(cid)}.xml", headers={"User-Agent": BILI_UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
    if not raw.lstrip().startswith(b"<"):
        for wbits in (-zlib.MAX_WBITS, zlib.MAX_WBITS, 16 + zlib.MAX_WBITS):
            try:
                raw = zlib.decompress(raw, wbits)
                break
            except zlib.error:
                continue
    return bili.parse_danmaku(raw.decode("utf-8", errors="replace"))


def browsed_bvids():
    d = jload(os.path.join(bl.PD, "astrbot_plugin_kaju_basics", "browse.json"), {})
    out = []
    for s in d.get("sessions") or []:
        if (s.get("site") or "bili") != "bili":  # 刷抖音的记录（bvid 是 dy…）不是 B 站视频，打开会 -400
            continue
        for it in s.get("items") or []:
            if it.get("bvid") and it["bvid"] not in out:
                out.append(it["bvid"])
    return out


def bili_samples(bvid, cookie):
    v = http_json(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}", cookie)
    if v.get("code") != 0:
        raise RuntimeError(f"view {v.get('code')} {v.get('message')}")
    info = v["data"]
    title, aid, cid = info.get("title", ""), info["aid"], info["cid"]
    share = f"群友A：[分享了B站视频《{title[:40]}》]"
    out, seen = [], set()

    def add(kind, key, ctx, target):
        n = bili_clean(target)
        if not bili_ok(n) or bili._norm(n) in seen:
            return
        seen.add(bili._norm(n))
        out.append({"src": "bili", "id": f"{kind}-{bvid}-{key}", "kind": "群聊", "ctx": ctx, "target": n[:200],
                    "group": f"bili-{bvid}", "from": kind})

    # 弹幕：分享视频后大家的反应（按时间均匀挑，同一句只要一次）
    try:
        dms = danmaku(cid)
        picked = bili.pick_danmaku(dms, n=12, duration=float(info.get("duration") or 0))
        for i, d in enumerate(picked):
            text = d[1] if isinstance(d, (list, tuple)) else str(d)
            add("dm", i, [share], text)
    except Exception as e:  # noqa: BLE001
        say(f"  {bvid} 弹幕没拿到：{type(e).__name__}")
    time.sleep(BILI_GAP)

    def msg_of(r):
        return bili_clean(((r.get("content") or {}).get("message")) or "")
    # 评论：热门评论翻两页，一楼当作对视频的反应
    try:
        roots = []
        for pn in (1, 2):
            r = http_json(f"https://api.bilibili.com/x/v2/reply?type=1&oid={aid}&sort=1&ps=20&pn={pn}", cookie)
            time.sleep(BILI_GAP)
            if r.get("code") != 0:
                break
            roots += (r.get("data") or {}).get("replies") or []
        n_root = 0
        for root in roots:
            if n_root < 14 and bili_ok(msg_of(root)):
                add("cr", root.get("rpid"), [share], msg_of(root))
                n_root += 1
        # 楼中楼：回复多的几楼整楼翻开，按时间排，前面几条当上下文、这一条当接话（最像群聊）
        hot = sorted([r for r in roots if int(r.get("rcount") or 0) >= 3 and bili_ok(msg_of(r))],
                     key=lambda r: -int(r.get("like") or 0))[:BILI_THREADS]
        for root in hot:
            d = http_json(f"https://api.bilibili.com/x/v2/reply/reply?type=1&oid={aid}&root={root['rpid']}&ps=20&pn=1",
                          cookie)
            time.sleep(BILI_GAP)
            subs = ((d.get("data") or {}).get("replies") or []) if d.get("code") == 0 else []
            labels = {str(root.get("mid")): "群友B"}
            hist = [(str(root.get("mid")), msg_of(root)[:120])]
            n_sub = 0
            for sub in sorted(subs, key=lambda x: int(x.get("ctime") or 0)):
                text, mid = msg_of(sub), str(sub.get("mid"))
                if not bili_ok(text):
                    continue
                labels.setdefault(mid, "群友" + "CDEFGHIJ"[min(len(labels) - 1, 7)])
                ctx = [share] + [f"{'我' if m == mid else labels[m]}：{t}" for m, t in hist[-4:]]
                before = len(out)
                add("cm", sub.get("rpid"), ctx, text)
                n_sub += len(out) > before
                hist.append((mid, text[:120]))
                if n_sub >= 12:
                    break
    except Exception as e:  # noqa: BLE001
        say(f"  {bvid} 评论没拿完：{type(e).__name__}")
    return title, out


def collect():
    os.makedirs(DD, exist_ok=True)
    have = bl.done_ids(POOL) | bl.done_ids(os.path.join(LAYERED, "h_group_cards.jsonl"))
    evk = bl.eval_keys() | exam_keys()
    new = [s for s in bl.group_samples() if s["id"] not in have and bl.ctx_key(s["ctx"]) not in evk]
    for s in new:
        s["got"] = now()
    bl.append(POOL, new)
    say(f"群聊新语料 {len(new)} 条")

    done = set(jload(BILI_DONE, []))
    todo = [b for b in browsed_bvids() if b not in done][:20]
    cookie = bili_cookie()
    # 她自己刷的不多时，从 B 站热门里补一些没收过的视频（攒着没训的 B 站语料多了就不补，免得越堆越多）
    backlog = sum(1 for r in pending() if r["src"] == "bili")
    if backlog < POPULAR_BACKLOG:
        try:
            pop = http_json("https://api.bilibili.com/x/web-interface/popular?ps=50&pn=1", cookie)
            extra = [v["bvid"] for v in ((pop.get("data") or {}).get("list") or [])
                     if v.get("bvid") and v["bvid"] not in done and v["bvid"] not in todo
                     and not POPULAR_SKIP.search(v.get("title", "") + " " + str(v.get("tname", "")))]
            todo += extra[:POPULAR_PER_NIGHT]
            say(f"攒着的 B 站语料 {backlog} 条，从热门补 {min(len(extra), POPULAR_PER_NIGHT)} 个视频")
        except Exception as e:  # noqa: BLE001
            say(f"热门没拿到：{type(e).__name__}")
    n_b = 0
    for bvid in todo:
        try:
            title, rows = bili_samples(bvid, cookie)
        except Exception as e:  # noqa: BLE001
            say(f"  {bvid} 没打开：{type(e).__name__}: {str(e)[:60]}")
            continue
        rows = [r for r in rows if r["id"] not in have]
        for r in rows:
            r["got"] = now()
        bl.append(POOL, rows)
        n_b += len(rows)
        done.add(bvid)
        jsave(BILI_DONE, sorted(done))
        say(f"  《{title[:24]}》{len(rows)} 条")
    say(f"B 站新语料 {n_b} 条（这次看了 {len(todo)} 个视频）")


def idle_now():
    """DeepSeek 空闲价时段：北京时间 00:30～08:30（这台电脑是悉尼时间，夏令时 = 03:30～11:30）。"""
    bj = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)
    m = bj.hour * 60 + bj.minute
    return 30 <= m < 510


async def make_cards(limit=0, skip_src=()):
    have = bl.done_ids(CARDS)
    todo = [s for s in bl.load(POOL) if s["id"] not in have and s.get("src") not in skip_src]
    if skip_src:
        later = sum(1 for s in bl.load(POOL) if s["id"] not in have and s.get("src") in skip_src)
        if later:
            say(f"{'、'.join(skip_src)} 的 {later} 条等 DeepSeek 空闲时段（北京 00:30～08:30）再抽")
    if limit:
        todo = todo[:limit]
    say(f"待抽卡 {len(todo)} 条（已有 {len(have)}）")
    if not todo:
        return

    async def one(s):
        cards = []
        for t in (0.3, 0.8):
            c = card.parse(await bl.ask(card.EXTRACT, card.extract_prompt(s["ctx"], s["target"], s.get("kind", "群聊"), ""), t))
            if c:
                cards.append(card.render(c, s.get("kind", "群聊"), ""))
        return {**s, "cards": cards}
    for i in range(0, len(todo), 200):
        rows = await asyncio.gather(*(one(s) for s in todo[i:i + 200]))
        bl.append(CARDS, [r for r in rows if r["cards"]])
    say(f"抽好了。{bl.cost()}")


def pending():
    used = used_ids()
    return [r for r in bl.load(CARDS) if r["id"] not in used]


def status():
    st = state()
    p = pending()
    by = {}
    for r in p:
        by[r["src"]] = by.get(r["src"], 0) + 1
    print(f"线上写手：{st['current']['name']}（第 {st['current']['round']} 轮）")
    print(f"没训过的新语料：{len(p)} 条 {by}，够 {THRESHOLD} 条训一轮")
    print(f"语料池 {len(bl.load(POOL))} 条，已抽卡 {len(bl.load(CARDS))} 条")
    for r in st["rounds"][-5:]:
        print(f"  第 {r['round']} 轮 {r['t']}：{r['result']}  {r.get('summary', '')}")


# ====================================================================== 训练用的小工具（8B 的脚本也用）
def run(cmd, log, env_extra=None, cwd=None):
    say("  $ " + " ".join(os.path.basename(c) if os.path.isabs(c) and i == 0 else c for i, c in enumerate(cmd)))
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", **(env_extra or {})}
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n==== {now()} {' '.join(cmd)}\n")
        f.flush()
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, cwd=cwd)
    if p.returncode != 0:
        raise RuntimeError(f"命令失败（{p.returncode}），看 {log}")


def ollama_unload(names):
    for n in names:
        try:
            req = urllib.request.Request(OLLAMA_URL + "/api/generate", json.dumps({"model": n, "keep_alive": 0}).encode(),
                                         {"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=30).read()
        except Exception:  # noqa: BLE001
            pass


def ollama_loaded():
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/ps", timeout=10) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:  # noqa: BLE001
        return []


def free_gpu():
    """训练要 ~5GB：把写手和看图模型先卸下（bge-m3 留着，记忆检索要用）。有消息来时 Ollama 会自己再装上。"""
    ollama_unload([n for n in ollama_loaded() if not n.startswith("bge-m3")])


def make_gguf(name, out_dir, adapters, log):
    merged = os.path.join(out_dir, "merged")
    f16 = os.path.join(out_dir, f"{name}-f16.gguf")
    q4 = os.path.join(out_dir, f"{name}-q4_k_m.gguf")
    mf = os.path.join(out_dir, f"{name}.Modelfile")
    try:
        run([PY, "-I", os.path.join(HERE, "merge_stream.py"), BASE, merged, *adapters], log)
        run([PY, CONVERT, merged, "--outfile", f16, "--outtype", "f16"], log)
        shutil.rmtree(merged, ignore_errors=True)
        run([QUANT, f16, q4, "Q4_K_M"], log)
        os.remove(f16)
        body = open(TEMPLATE, encoding="utf-8").read()
        body = re.sub(r"(?m)^FROM .+$", lambda _: "FROM " + q4, body)
        open(mf, "w", encoding="utf-8").write(body)
        run([OLLAMA, "create", name, "-f", mf], log, {"OLLAMA_HOST": OLLAMA_URL})
    finally:
        shutil.rmtree(merged, ignore_errors=True)
        for p in (f16, q4):
            if os.path.exists(p):
                os.remove(p)


# ====================================================================== 考试


def exam_keys():
    return {bl.ctx_key(x.get("ctx", [])) for x in exam_items(live_only=True)}


def exam_items(live_only=False, n_live=40):
    """考题：第一轮的评测题（24）+ 留出题（5）+ 第四轮标注留出的（她先复述对方的场合，make_gold4.py）
    + 第五批留出的（写手照卡写时改过意思的场合，make_gold5.py）
    + 最近的线上真实输入（照卡写的原样输入）。"""
    items = []
    if not live_only:
        for name in ("layered_v1_eval.jsonl", "review4_eval.jsonl", "review5_eval.jsonl", "review6_eval.jsonl",
                     "review7_eval.jsonl"):
            p = os.path.join(VT, "data", name)
            for x in (bl.load(p) if os.path.exists(p) else []):
                items.append({"id": x["id"], "ctx": x["ctx"], "card": x["card"], "title": x.get("to", ""),
                              "user": card.write_prompt(x["ctx"], x["card"])})
        for x in bl.load(os.path.join(VT, "data", "curated_second_batch_holdout.jsonl")):
            if x.get("card"):
                items.append({"id": x["id"], "ctx": x["ctx"], "card": x["card"], "title": x.get("to", ""),
                              "user": card.write_prompt(x["ctx"], x["card"])})
    live = []
    used6 = set(jload(os.path.join(VT, "data", "review6_used.json"), []))  # 第六批标过的线上记录进了训练数据，不当考题
    used6 |= set(jload(os.path.join(VT, "data", "review7_used.json"), []))  # 第七批（ab6 盲选）同理
    for p in sorted(glob.glob(os.path.join(REWRITES, "*.jsonl")))[-14:]:
        for r in bl.load(p):
            if str(r.get("t")) in used6:
                continue
            try:
                w = json.loads(r["writer"]) if isinstance(r.get("writer"), str) else (r.get("writer") or [])
                c = json.loads(r["card"]) if isinstance(r.get("card"), str) else (r.get("card") or [])
                ctx = json.loads(r["ctx"]) if isinstance(r.get("ctx"), str) else (r.get("ctx") or [])
            except (TypeError, ValueError):
                continue
            if w and c and w[0].get("user") and c[0].get("card"):
                live.append({"id": f"live-{r['t']}", "ctx": ctx, "card": c[0]["card"], "title": r.get("title", ""),
                             "user": w[0]["user"], "draft": r.get("draft", "")})
    return items + live[-n_live:]


# 她自己说出来的话里不能有的（比收语料时的过滤窄：小傻龙、小丑、叠起来这些正常词不算）
OUT_BAD = re.compile(r"[我你]操|操[你他她蛋]|艹|屌|傻[逼比b屌]|鸡巴|几把|妈的|死妈|nmsl|卧槽|我草|淦|做爱|上床|去死|滚开|智障|弱智|脑残|废物|贱|婊", re.I)


def hard_flags(text, trained):
    f = []
    if not text.strip():
        f.append("空")
    if card.LEAK.search(text):
        f.append("漏卡片格式")
    # “说你”11-17 起不算硬伤（兄长：贴近原作，偶尔说“你”还能接受——原作 1520 句里 3.8% 说了“你”，多是先叫称呼、后面再用“你”）；
    # 改成考试里单独数一个“你”的比例（exam_p3 extra_stats），和原作的 3.8% 比
    if OUT_BAD.search(text):
        f.append("脏话戾气")
    if len(text) > 160:
        f.append("太长")
    if card.trad_chars(text):
        f.append("繁体字")
    flat = re.sub(r"\s+", "", text)
    for t in trained:
        t = re.sub(r"\s+", "", t)
        if len(t) >= 12 and t in flat:
            f.append("背出训练原话")
            break
    return f


# ====================================================================== 入口
async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "cards", "idle-cards", "status"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(DD, exist_ok=True)
    if a.cmd == "collect":
        collect()
    elif a.cmd == "cards":  # 高峰时段默认不抽大批的（贴吧），--force 才抽
        await make_cards(a.limit, skip_src=() if (a.force or idle_now()) else BULK_SRC)
    elif a.cmd == "idle-cards":  # 空闲时段把攒着的（主要是贴吧）一次抽完
        if not idle_now():
            say("现在不是 DeepSeek 空闲时段（北京 00:30～08:30），不抽")
        else:
            await make_cards(a.limit)
    else:
        status()


if __name__ == "__main__":
    asyncio.run(main())
