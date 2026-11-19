"""偏好训练（2026-11-10）：接着某个 K（佳树口吻层）往下训，让它更偏向兄长大人选的、写的，少说他不要的。

    <voice_train venv>\\python -I train_pref.py --base <H 合并后的模型> --init-adapter <起点 K> --out <新目录>

三样损失一起算（数据 data\\prefs_v1，build_prefs.py 做的）：
  DPO   成对：同一份输入，兄长的写法概率往上、写手原来那句往下。
  KTO   单条：盲选里他选的往上、"都不好"的往下（两边卡片不一样、配不成对的票）。
  SFT   复习：照常学 stage2（原作台词 + 人工样本），防止为了压差的句子把照卡写、把佳树口吻忘了。
参考模型 = 训练开始时的自己（起点 K）：开训前把每句话的对数概率算一遍存下来，训练中只比"比起点变了多少"，
所以不用加载第二个模型，显存和平常训 K 一样。
每轮结束存一份 <out>\\epN，并在留出题上量：没见过的题里，模型是不是更偏向兄长的写法（metrics.json）。
"""
import argparse
import json
import math
import os
import random
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import train_writer as tw  # noqa: E402  (写手提示、编码、4bit 加载：和平常训练一字不差)

ROOT = tw.ROOT
LIVE = ("r4", "r5", "r6", "r7")  # 线上写手自己的句子配兄长改写：最对口，多看几遍


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--init-adapter", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefs", default=os.path.join(ROOT, "data", "prefs_v1"))
    ap.add_argument("--anchor", default=os.path.join(ROOT, "data", "layered_v1", "stage2.jsonl"))
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--pairs", type=int, default=8, help="每步几对")
    ap.add_argument("--kto", type=int, default=2, help="每步几条单条")
    ap.add_argument("--sft", type=int, default=8, help="每步几条复习")
    ap.add_argument("--sft-weight", type=float, default=1.0)
    ap.add_argument("--kto-weight", type=float, default=1.0)
    ap.add_argument("--live-repeat", type=int, default=3)
    ap.add_argument("--max_len", type=int, default=768)
    ap.add_argument("--max_steps", type=int, default=0)
    ap.add_argument("--dpop", type=float, default=0.0,
                    help="兄长那句的概率比起点低了多少，就从拉开的差距里扣掉多少倍（DPO-Positive）。0 = 普通 DPO。"
                         "p1 用普通 DPO：差距是拉开了，可两句的概率一起往下掉，没训过的题上兄长写法的损失 1.70→2.02")
    ap.add_argument("--eval-every", type=int, default=0, help="每多少步考一次留出题并存一份（s40、s80…）；0 = 只在每轮末")
    a = ap.parse_args()
    if os.path.exists(a.out):
        raise FileExistsError(f"{a.out} 已经有了，换个新目录")
    os.makedirs(a.out)
    logf = os.path.join(a.out, "train_log.txt")

    def log(msg):
        print(msg, flush=True)
        with open(logf, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")

    import torch
    import torch.nn.functional as F
    from peft import PeftModel, prepare_model_for_kbit_training
    from transformers import AutoTokenizer

    total_mem = torch.cuda.get_device_properties(0).total_memory
    torch.cuda.set_per_process_memory_fraction(min(0.93, (total_mem - 0.7 * 2**30) / total_mem))
    rng = random.Random(11)
    tok = AutoTokenizer.from_pretrained(a.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    def enc(row, text):
        return tw.encode(tok, 2, {"ctx": row["ctx"], "card": row["card"], "target": text}, a.max_len)

    def load_pairs(name):
        out = []
        for r in tw.load(os.path.join(a.prefs, name)):
            c, j = enc(r, r["chosen"]), enc(r, r["rejected"])
            if c and j:
                out.append({"row": r, "c": c, "r": j})
        return out

    def load_singles(name):
        out = []
        for r in tw.load(os.path.join(a.prefs, name)):
            e = enc(r, r["text"])
            if e:
                out.append({"row": r, "e": e, "good": r["label"] == "good"})
        return out

    dpo, held = load_pairs("dpo.jsonl"), load_pairs("heldout.jsonl")
    kto, ab7 = load_singles("kto.jsonl"), load_singles("ab7.jsonl")
    # 复习：人工样本全要，原作台词抽 600；另留 120 条原作台词不训，量"佳树口吻有没有被带偏"
    s2 = tw.load(a.anchor)
    novel = [s for s in s2 if s.get("src") != "curated"]
    rng.shuffle(novel)
    drift = [e for e in (tw.encode(tok, 2, s, a.max_len) for s in novel[:120]) if e]
    anchor = [e for e in (tw.encode(tok, 2, s, a.max_len) for s in
                          [s for s in s2 if s.get("src") == "curated"] + novel[120:720]) if e]
    log(f"成对 {len(dpo)}（线上那批 ×{a.live_repeat}），单条 {len(kto)}，复习 {len(anchor)}；"
        f"留出：成对 {len(held)}、ab7 {len(ab7)}、原作台词 {len(drift)}")

    model = tw.load_4bit(a.base)
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                            gradient_checkpointing_kwargs={"use_reentrant": False})
    model = PeftModel.from_pretrained(model, a.init_adapter, is_trainable=True)
    core = model.get_base_model()
    log(f"接着 {a.init_adapter} 训")

    def collate(encs):
        L = max(len(e["input_ids"]) for e in encs)
        ids = torch.full((len(encs), L), tok.pad_token_id)
        lab = torch.full((len(encs), L), -100)
        att = torch.zeros((len(encs), L), dtype=torch.long)
        for k, e in enumerate(encs):
            n = len(e["input_ids"])
            ids[k, :n] = torch.tensor(e["input_ids"])
            lab[k, :n] = torch.tensor(e["labels"])
            att[k, :n] = 1
        return ids.cuda(), lab.cuda(), att.cuda()

    def seq_logp(encs):
        """每句话整句的对数概率（只算回复那一段的 token，含结束符）和 token 数。"""
        ids, lab, att = collate(encs)
        # 只在回复那一段的位置上过输出层：整段都过的话 2×512×15 万词的概率表要占 2GB 多显存
        h = core.model(input_ids=ids, attention_mask=att).last_hidden_state[:, :-1]
        tgt = lab[:, 1:]
        pos = tgt != -100
        nll = F.cross_entropy(core.lm_head(h[pos]).float(), tgt[pos], reduction="none")
        row = pos.nonzero()[:, 0]
        return torch.zeros(len(encs), device=nll.device).index_add(0, row, -nll), pos.sum(1)

    @torch.no_grad()
    def score(encs, bs=4):
        model.eval()
        order = sorted(range(len(encs)), key=lambda i: len(encs[i]["input_ids"]))
        lp, n = [0.0] * len(encs), [0] * len(encs)
        for i in range(0, len(order), bs):
            idx = order[i:i + bs]
            a_, b_ = seq_logp([encs[j] for j in idx])
            for j, x, y in zip(idx, a_.tolist(), b_.tolist()):
                lp[j], n[j] = x, y
        model.train()
        return lp, n

    t0 = time.time()
    for group in (dpo, held):
        for key in ("c", "r"):
            lp, n = score([p[key] for p in group])
            for p, x, y in zip(group, lp, n):
                p["ref_" + key], p["n_" + key] = x, y
    for group in (kto, ab7):
        lp, n = score([s["e"] for s in group])
        for s, x, y in zip(group, lp, n):
            s["ref"], s["n"] = x, y
    log(f"起点的对数概率算好了（{(time.time() - t0) / 60:.1f} 分钟）")

    def evaluate(tag):
        lc, _ = score([p["c"] for p in held])
        lr, _ = score([p["r"] for p in held])
        # 每个 token 平均的对数概率来比（两句长短不一样，整句的会偏向短的）
        prefer = sum((x / p["n_c"]) > (y / p["n_r"]) for p, x, y in zip(held, lc, lr)) / len(held)
        margin = [(x - p["ref_c"]) - (y - p["ref_r"]) for p, x, y in zip(held, lc, lr)]
        moved = sum(m > 0 for m in margin) / len(held)
        by = {}
        for src in LIVE:
            ms = [m for p, m in zip(held, margin) if p["row"]["src"] == src]
            if ms:
                by[src] = round(sum(m > 0 for m in ms) / len(ms), 2)
        la, _ = score([s["e"] for s in ab7])
        d_good = [(x - s["ref"]) / s["n"] for s, x in zip(ab7, la) if s["good"]]
        d_bad = [(x - s["ref"]) / s["n"] for s, x in zip(ab7, la) if not s["good"]]
        up_c = sum((x - p["ref_c"]) / p["n_c"] for p, x in zip(held, lc)) / len(held)
        up_r = sum((y - p["ref_r"]) / p["n_r"] for p, y in zip(held, lr)) / len(held)
        ld, nd = score(drift)
        out = {"tag": tag, "偏向兄长写法": round(prefer, 3), "比起点更偏向": round(moved, 3),
               "平均拉开": round(sum(margin) / len(margin), 2), "各批": by,
               "兄长写法每字": round(up_c, 3), "写手原句每字": round(up_r, 3),
               "ab7他选的": round(sum(d_good) / max(1, len(d_good)), 3), "ab7都不好的": round(sum(d_bad) / max(1, len(d_bad)), 3),
               "原作台词损失": round(-sum(ld) / sum(nd), 4),
               "留出兄长写法损失": round(-sum(lc) / sum(p["n_c"] for p in held), 4)}
        log("留出题 " + json.dumps(out, ensure_ascii=False))
        return out

    metrics = [evaluate("起点")]
    train_pairs = [p for p in dpo for _ in range(a.live_repeat if p["row"]["src"] in LIVE else 1)]
    steps_per_epoch = math.ceil(len(train_pairs) / a.pairs)
    total = steps_per_epoch * a.epochs
    if a.max_steps:
        total = min(total, a.max_steps)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / 10) * max(0.1, 1 - s / max(1, total)))

    def cycle(data):
        while True:
            idx = list(range(len(data)))
            rng.shuffle(idx)
            for i in idx:
                yield data[i]

    kto_it, sft_it = cycle(kto), cycle(anchor)
    model.train()
    step, t0 = 0, time.time()
    agg = {"dpo": 0.0, "acc": 0.0, "kto": 0.0, "sft": 0.0, "n": 0}
    for ep in range(a.epochs):
        rng.shuffle(train_pairs)
        for i in range(0, len(train_pairs), a.pairs):
            chunk = train_pairs[i:i + a.pairs]
            for p in chunk:
                lp, _ = seq_logp([p["c"], p["r"]])
                m = (lp[0] - p["ref_c"]) - (lp[1] - p["ref_r"])
                pen = a.dpop * torch.relu(p["ref_c"] - lp[0]) if a.dpop else 0.0
                loss = -F.logsigmoid(a.beta * (m - pen)) / len(chunk)
                loss.backward()
                agg["dpo"] += loss.item()
                agg["acc"] += float(m.item() > 0) / len(chunk)
            for _ in range(a.kto):
                s = next(kto_it)
                lp, _ = seq_logp([s["e"]])
                r = lp[0] - s["ref"]
                loss = (1 - torch.sigmoid(a.beta * (r if s["good"] else -r))) * a.kto_weight / max(1, a.kto)
                loss.backward()
                agg["kto"] += loss.item()
            for j in range(0, a.sft, 2):
                lp, n = seq_logp([next(sft_it) for _ in range(min(2, a.sft - j))])
                loss = -lp.sum() / n.sum() * a.sft_weight / math.ceil(a.sft / 2)
                loss.backward()
                agg["sft"] += loss.item()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); opt.zero_grad()
            step += 1
            agg["n"] += 1
            if step % 10 == 0 or step == total or step in (1, 3):
                el, n = time.time() - t0, agg["n"]
                log(f"  第 {ep + 1} 轮 {step}/{total} 步  DPO {agg['dpo'] / n:.3f}（已拉开 {agg['acc'] / n:.0%}）  KTO {agg['kto'] / n:.3f}  "
                    f"复习 {agg['sft'] / n:.3f}  已用 {el / 60:.1f} 分钟，还要 {el / step * (total - step) / 60:.0f} 分钟  "
                    f"显存峰值 {torch.cuda.max_memory_allocated() / 2**30:.1f}GB")
                agg = {k: 0.0 if k != "n" else 0 for k in agg}
            if a.eval_every and step % a.eval_every == 0 and step < total:
                d = os.path.join(a.out, f"s{step}")
                model.save_pretrained(d)
                tok.save_pretrained(d)
                metrics.append(evaluate(f"第 {step} 步"))
                json.dump(metrics, open(os.path.join(a.out, "metrics.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            if step >= total:
                break
        d = os.path.join(a.out, f"ep{ep + 1}")
        model.save_pretrained(d)
        tok.save_pretrained(d)
        metrics.append(evaluate(f"第 {ep + 1} 轮"))
        json.dump(metrics, open(os.path.join(a.out, "metrics.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        if step >= total:
            break
    json.dump({"base": a.base, "init_adapter": a.init_adapter, "pairs": len(dpo), "kto": len(kto), "anchor": len(anchor),
               "lr": a.lr, "beta": a.beta, "epochs": a.epochs, "steps": step, "minutes": round((time.time() - t0) / 60, 1)},
              open(os.path.join(a.out, "run.json"), "w", encoding="utf-8"), ensure_ascii=False)
    log(f"完成，{step} 步，{(time.time() - t0) / 60:.1f} 分钟 → {a.out}")


if __name__ == "__main__":
    main()
