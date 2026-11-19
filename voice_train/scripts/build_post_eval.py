"""出一批"照卡写说说"的新盲评题：真实素材 → 每晚说说流程（选材、DeepSeek 写、核对）→ 从过了核对的稿子抽要点卡
→ 旧写手和新写手照同一张卡各写一条（和线上 writer=local 时 kaju_style.polish(kind="说说") 一样：上下文为空、卡片对象"无"）。

    D:\\JiashuBot\\voice_train\\venv\\Scripts\\python.exe -I build_post_eval.py OUT.jsonl [--baseline kaju-writer] [--candidate kaju-writer-curated-v1] [--n 10]

只读机器人数据（复制到临时目录），不发布。和训练里兄长大人亲手写的三条说说同话题的（麦当劳、妹妹人生、小傻龙、AP）跳过，
免得新写手因为见过答案占便宜。输出每行：id、kind=说说、ctx（给投票的人看的"要写的事"）、card、draft、baseline、candidate。
之后：v4_eval.py paired OUT.jsonl --out 新目录
"""
import argparse
import asyncio
import datetime as dt
import importlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zoneinfo

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
ROOT = r"D:\JiashuBot"
sys.path.insert(0, os.path.join(ROOT, "bot_setup", "tests", "stubs"))
sys.path.insert(0, os.path.join(ROOT, "bot_setup", "plugins"))
sys.path.insert(0, os.path.join(ROOT, "bot_setup", "kaju_core", "voice"))
CORE = r"C:\Users\18525\.astrbot_launcher\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
PD = os.path.join(CORE, "data", "plugin_data")
TMP = tempfile.mkdtemp(prefix="post_eval_")
os.environ["STUB_DATA"] = TMP
for rel in ["astrbot_plugin_kaju_life/log", "astrbot_plugin_kaju_life/names.json", "astrbot_plugin_kaju_life/days.json",
            "astrbot_plugin_address_book/addresses.json", "astrbot_plugin_kaju_basics/browse.json",
            "astrbot_plugin_kaju_heart/state.json", "astrbot_plugin_qzone_post/posts.json"]:
    src, dst = os.path.join(PD, rel), os.path.join(TMP, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(src):
        shutil.copytree(src, dst)
    elif os.path.exists(src):
        shutil.copy2(src, dst)

from openai import AsyncOpenAI  # noqa: E402

from astrbot.api.star import Context  # noqa: E402

import card  # noqa: E402
import rewrite  # noqa: E402

qm = importlib.import_module("qzone_post.main")
TZ = zoneinfo.ZoneInfo("Asia/Shanghai")
SEEN_IN_TRAINING = ("麦当劳", "巨无霸", "妹妹人生", "小傻龙", "AP", "全连", "打歌")

cfg = json.load(open(os.path.join(CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
key = src.get("key")
ds = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"], timeout=90)


async def llm_generate(chat_provider_id=None, prompt="", system_prompt=""):
    r = await ds.chat.completions.create(model="deepseek-flash", messages=[
        {"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}])
    return type("Resp", (), {"completion_text": r.choices[0].message.content or ""})()


async def extract(draft):
    r = await ds.chat.completions.create(model="deepseek-flash", temperature=0.3, extra_body=card.EXTRACT_EXTRA_BODY,
                                         messages=[{"role": "system", "content": card.EXTRACT},
                                                   {"role": "user", "content": card.extract_prompt([], draft, "说说", "")}])
    c = card.parse(r.choices[0].message.content or "")
    return card.render(c, "说说", "") if c else ""


def write(model, card_text):
    body = json.dumps({"model": model, "temperature": 0.7, "top_p": 0.9, "max_tokens": 220,
                       "messages": [{"role": "system", "content": card.WRITE_SYSTEM[2]},
                                    {"role": "user", "content": card.write_prompt([], card_text)}]},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:11435/v1/chat/completions", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return rewrite.clean_output(json.load(r)["choices"][0]["message"]["content"])


class Prov:
    provider_config = {"id": "deepseek"}


async def no_publish(*a, **k):
    raise AssertionError("出题不发布")


async def main(a):
    with open(os.path.join(TMP, "astrbot_plugin_qzone_post", "posts.json"), encoding="utf-8") as f:
        all_posts = json.load(f)
    days = sorted(x[:-6] for x in os.listdir(os.path.join(TMP, "astrbot_plugin_kaju_life", "log")))
    slots = [(d, hm) for hm in ((22, 29), (17, 0), (13, 0)) for d in days]  # 先每天晚上一条，不够再取白天
    rows, drafts = [], []
    for day, (h, m) in slots:
        if len(rows) >= a.n:
            break
        ctx = Context()
        ctx.providers = {"deepseek": Prov()}
        ctx.llm_generate = llm_generate
        p = qm.QzonePost(ctx, {"nightly": {"timeout_seconds": 120}})
        p._publish = no_publish
        d = dt.date.fromisoformat(day)
        now = dt.datetime(d.year, d.month, d.day, h, m, tzinfo=TZ).timestamp()
        p._posts = [x for x in all_posts if x["time"] < now]
        try:
            run = await p.run_nightly(publish=False, now=now)
        except Exception as exc:  # noqa: BLE001
            print(f"{day} {h}:{m:02d} 出错 {exc}")
            continue
        draft = run.get("text") or ""
        tag = f"{day} {h}:{m:02d}"
        if run["status"] != "draft":
            print(f"{tag} 跳过：{run['status']} {run.get('reason', '')[:60]}")
            continue
        if any(w.lower() in draft.lower() for w in SEEN_IN_TRAINING):
            print(f"{tag} 跳过：和训练里的说说同话题")
            continue
        if any(len(set(draft) & set(x)) / max(1, len(set(draft) | set(x))) > 0.6 for x in drafts):
            print(f"{tag} 跳过：和已经出的题太像")
            continue
        card_text = await extract(draft)
        if not card_text:
            print(f"{tag} 跳过：没抽出卡")
            continue
        base, cand = write(a.baseline, card_text), write(a.candidate, card_text)
        if not base.strip() or not cand.strip():
            print(f"{tag} 跳过：写手输出空")
            continue
        facts = [f["say"] for f in (run.get("plan") or {}).get("facts", [])]
        feel = (run.get("plan") or {}).get("feel", "")
        drafts.append(draft)
        rows.append({"id": f"post-{day}-{h:02d}{m:02d}", "kind": "说说",
                     "ctx": ["（这条说说要写的事）"] + [f"· {x}" for x in facts] + ([f"· 感受：{feel}"] if feel else []),
                     "card": card_text, "draft": draft, "baseline": base, "candidate": cand})
        print(f"{tag} 出好第 {len(rows)} 题")
    with open(a.out, "x", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"共 {len(rows)} 题 → {a.out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--baseline", default="kaju-writer")
    ap.add_argument("--candidate", default="kaju-writer-curated-v1")
    ap.add_argument("--n", type=int, default=10)
    try:
        asyncio.run(main(ap.parse_args()))
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
