r"""本机小步纠正 · 第一步：从线上记录挑一批新写手发出去的回复，做成兄长的标注页（2026-11-12 写，方法见 voice_train\本机微调方案-20261112.md）。

来源：kaju_style 的线上重说记录 D:\JiashuBot\kaju_data\self\kaju_style\rewrites\*.jsonl。只要：
  - 第四版卡（卡里有“局面：”，写手是当前线上那个，state.json 的 live_model）；
  - outcome = used（写手写的那句真的发出去了）；
  - 以前各轮没挑过的（state.json 的 picked）。
私聊、群聊各取一半（不够就互相补），越新越优先。
顺带把“写手写了、被核对拦下”的那几遍（核对说编了 / 漏了 / 叫错人——都是对错类毛病，不是口味）存成自动反例 auto_bad.jsonl；
写手哪一遍把同一个 4 字以上的词说了三遍以上（11-13 兄长：“停不下来”说了 3 遍）也存进去（src = repeat）。

输出（data\rounds_v4\r<N>\）：
  items.json      每条的全部信息（训练用：上下文、写手当时看到的卡、原句……）
  auto_bad.jsonl  自动反例
  review\round_r<N>.html  标注页（发布成 Artifact，带 db 和 user；collection "labels"，doc id = 条目 id，内容 {text, skip, ok}）
兄长标完：用 ArtifactData list 把 collection "labels" 存到 data\rounds_v4\r<N>\labels（out_dir），再跑 round_train.py。

用法（AstrBot 的 Python）：python -I -X utf8 scripts\round_pick.py --round 1 [--n 60] [--model kaju-writer-p4-8b-k]
"""
import argparse
import glob
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
VT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REWRITES = r"D:\JiashuBot\kaju_data\self\kaju_style\rewrites"
ROOT = os.path.join(VT, "data", "rounds_v4")
STATE = os.path.join(ROOT, "state.json")
FIRST_LIVE = {"live_model": "kaju-writer-p4-8b-k",
              "live_adapter": os.path.join(VT, "train_pack", "results_v4", "results", "8b-A", "K"),
              "picked": [], "rounds": {}}


def load_state() -> dict:
    os.makedirs(ROOT, exist_ok=True)
    if os.path.exists(STATE):
        return json.load(open(STATE, encoding="utf-8"))
    json.dump(FIRST_LIVE, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return dict(FIRST_LIVE)


def save_state(st: dict) -> None:
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def parse(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return []
    return v or []


def _new_mood(x):
    """11-16 晚心情行合并重复项以前的线上记录：卡里的旧心情行读的时候转成新写法（记录文件本身不改）。"""
    from kaju_core.heart.mood_line import normalize
    if isinstance(x, str):
        return normalize(x)
    if isinstance(x, list):
        return [_new_mood(v) for v in x]
    if isinstance(x, dict):
        return {k: _new_mood(v) for k, v in x.items()}
    return x


def records():
    sys.path.insert(0, os.path.join(os.path.dirname(VT), "bot_setup"))
    for p in sorted(glob.glob(os.path.join(REWRITES, "*.jsonl"))):
        for line in open(p, encoding="utf-8"):
            if line.strip():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if "card" in d:
                    c = d["card"]
                    d["card"] = json.dumps(_new_mood(json.loads(c)), ensure_ascii=False) if isinstance(c, str) and c.startswith("[") else _new_mood(c)
                yield d


# 同一个词说了好几遍（2026-11-13 兄长：“停不下来”一句里说了 3 遍；“把同一个词说三遍也加进微调”）：
# 同一个 4 个字以上的中文词在一条里出现 3 次以上 → 这一遍当自动反例。称呼（××大人 / 学长 / 学姐 / 哥哥）和“佳树”不算。
NAME_RE = re.compile(r"[一-鿿]{2}大人|学长|学姐|哥哥|佳树")  # 只吃“××大人”两个字，别把前面的“来了”一起吃掉


def repeated_word(text: str, n: int = 4, times: int = 3) -> str:
    """一条里说了 times 遍以上的那个词（n 个字）；没有返回 ''。"""
    t = NAME_RE.sub("|", re.sub(r"\s+", "|", text or ""))  # 换行也当断开（行和行之间不拼成一个词）
    seen = {}
    for i in range(len(t) - n + 1):
        g = t[i:i + n]
        if not re.fullmatch(r"[一-鿿]+", g):
            continue
        seen[g] = seen.get(g, 0) + 1
        if seen[g] >= times:
            return g
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--model", default="")
    a = ap.parse_args()
    st = load_state()
    model = a.model or st["live_model"]
    out_dir = os.path.join(ROOT, f"r{a.round}")
    if os.path.exists(os.path.join(out_dir, "items.json")):
        sys.exit(f"{out_dir} 已经有 items.json 了（这一轮挑过了）；要重挑先把它删掉")
    picked = set(map(str, st.get("picked", [])))
    cand, auto_bad, seen = [], [], set()
    for r in records():
        w, c, ctx = parse(r.get("writer")), parse(r.get("card")), parse(r.get("ctx"))
        card_text = (c[0].get("card") if c else "") or ""
        if "局面：" not in card_text or not w:
            continue
        if ((r.get("config") or {}).get("card_model") or w[0].get("model")) != model:
            continue
        # 被核对拦下的那几遍：对错类的毛病（编造 / 漏点 / 叫错人），当反例（不看口味）
        for i, g in enumerate(parse(r.get("guard"))):  # 核对记着它判的那一句（new），不按下标对写手那几遍（写坏的那遍不进核对）
            bad_text = re.sub(r"\s*&&[^&\n]*&&\s*", "", str(g.get("new") or "")).strip()
            if g.get("bad") and bad_text and not str(g.get("why", "")).startswith("核对失败"):
                auto_bad.append({"id": f"auto-{r['t']}-{i}", "src": "guard", "ctx": ctx, "card": card_text,
                                 "text": bad_text, "label": "bad", "why": g.get("why", ""), "w": 1.0})
        # 写手哪一遍把同一个词说了三遍以上（发出去的那句也算）：当反例（对错类，不看口味）
        rep_seen = set()
        for i, x in enumerate(w):
            out = re.sub(r"\s*&&[^&\n]*&&\s*", "", str(x.get("out") or "")).strip()
            word = repeated_word(out)
            if word and out not in rep_seen:
                rep_seen.add(out)
                auto_bad.append({"id": f"rep-{r['t']}-{i}", "src": "repeat", "ctx": ctx, "card": card_text,
                                 "text": out, "label": "bad", "why": f"同一个词说了三遍以上：{word}", "w": 1.0})
        if r.get("outcome") != "used" or str(r.get("t")) in picked:
            continue
        reply = re.sub(r"\s*&&[^&\n]*&&\s*", "", r.get("final") or "").strip()  # 表情包标签不是说法
        key = (tuple(ctx[-2:]), reply)
        if not reply or key in seen:
            continue
        seen.add(key)
        show = []
        for ln in ctx:
            who, _, x = ln.partition("：")
            show.append({"who": who if x else "", "x": x if x else ln})
        gist = next((ln.split("：", 1)[1] for ln in card_text.splitlines() if ln.startswith("要说到的：")), "")
        cand.append({"id": f"r{a.round}-{r['t']}", "t": r["t"], "when": time.strftime("%m-%d %H:%M", time.localtime(r["t"])),
                     "kind": r.get("kind", ""), "to": r.get("title", ""), "model": model, "ctx": show, "train_ctx": ctx,
                     "card": card_text, "gist": gist, "reply": reply.replace("\n", " / "), "reply_raw": reply,
                     "user": w[-1].get("user", "")})
    cand.sort(key=lambda x: -x["t"])
    groups = [x for x in cand if x["kind"] == "群聊"]
    privs = [x for x in cand if x["kind"] != "群聊"]
    half = a.n // 2
    items = privs[:half] + groups[:half]
    rest = [x for x in cand if x not in items]
    items += rest[:a.n - len(items)]
    items.sort(key=lambda x: x["t"])
    if not items:
        sys.exit(f"线上记录里还没有 {model} 发出去、没挑过的回复（新写手上线后要先攒一阵）")
    os.makedirs(out_dir, exist_ok=True)
    json.dump(items, open(os.path.join(out_dir, "items.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "auto_bad.jsonl"), "w", encoding="utf-8") as f:
        for b in auto_bad:
            f.write(json.dumps(b, ensure_ascii=False) + "\n")
    show = [{k: it[k] for k in ("id", "when", "kind", "to", "ctx", "gist", "reply")} for it in items]
    tpl = open(os.path.join(VT, "review", "round.template.html"), encoding="utf-8").read()
    page = (tpl.replace("/*TITLE*/", f"新写手第 {a.round} 轮")
            .replace("/*ITEMS*/", json.dumps(show, ensure_ascii=False).replace("</", "<\\/")))
    html = os.path.join(VT, "review", f"round_r{a.round}.html")
    open(html, "w", encoding="utf-8", newline="\n").write(page)
    st["picked"] = sorted(picked | {str(x["t"]) for x in items})
    st.setdefault("rounds", {})[str(a.round)] = {"picked_at": time.strftime("%Y-%m-%d %H:%M"), "items": len(items),
                                                 "model": model, "auto_bad": len(auto_bad)}
    save_state(st)
    print(f"挑了 {len(items)} 条（私聊 {sum(x['kind'] != '群聊' for x in items)}、群聊 {sum(x['kind'] == '群聊' for x in items)}；"
          f"候选 {len(cand)}）、自动反例 {len(auto_bad)} 句 → {out_dir}\n标注页 {html}（发布成 Artifact：capabilities db + user）")


if __name__ == "__main__":
    main()
