"""（本机版，2026-11-07 起日常自学用：比训练包里的多了 --init-adapter 接着训、--replay-ratio）
QLoRA 训练"写手"（v4）：上下文 + 要点卡 → 真人/佳树会说的话。由 run_train.ps1 调用，一般不用手动跑。

v4 起不再看 AI 草稿改写：线上 DeepSeek 只出要点卡（关键词），句子全由这个模型写，没有现成的句子可抄。
阶段一（说人话）：--stage 1 --base models/Qwen3-4B-Instruct-2507 --out output/stage1_adapter
                  --merge output/stage1_adapter --base models/Qwen3-4B-Instruct-2507 --merged models/stage1-merged
                  （合并进模型，阶段一从此冻结）。数据：LCCC 真人聊天 + 兄长大人自己的私聊
阶段二（像佳树）：--stage 2 --base models/stage1-merged --out output/stage2_adapter（掺约 30% 阶段一数据防遗忘）。
                  数据：原作佳树台词（每句 2 张卡）+ 兄长大人挑过改过的回复（每条 3 张卡）
"""
import argparse
import json
import math
import os
import random
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "output", "train_log.txt")

# 和机器人里 kaju_style/card.py 的 WRITE_SYSTEM 一字不差（线上就用这两句）
SYSTEM = {
    1: ("你是写手：照要点卡写出真人在聊天里会发的回复。忠实表达卡上的要点，不编造已经发生的事、做过的事或别人说过的话；"
        "可以结合上下文表达自己的感受、愿望和有依据但不确定的猜测。长短、用词、语气像真人随手打的字。只输出回复。"),
    2: ("你是写手：照要点卡写出温水佳树（《败犬女主太多了！》里温水和彦的妹妹）会说的话。忠实表达卡上的要点，"
        "不编造已经发生的事、做过的事或别人说过的话；可以结合上下文表达自己的感受、愿望和有依据但不确定的猜测。"
        "自称佳树，按场合自然使用对象的称呼，不说\"你\"；像她平时说话，也像真人随手打的字。只输出回复。"),
}


REPLAY_RATIO = 0.3


def log(msg):
    print(msg, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def prompt_of(sample):
    """和 card.write_prompt 一样。"""
    ctx = "\n".join(sample.get("ctx") or []) or "（没有前文）"
    return f"上下文：\n{ctx}\n\n要点卡：\n{sample['card']}"


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def build_data(stage, rng, data_dir=None, curated_repeat=1):
    if curated_repeat < 1:
        raise ValueError("人工样本采样倍数至少为 1")
    data_dir = data_dir or os.path.join(ROOT, "data")
    s1 = load(os.path.join(data_dir, "stage1.jsonl"))
    if stage == 1:
        rows = [(1, s) for s in s1]
    else:
        s2 = load(os.path.join(data_dir, "stage2.jsonl"))  # 同一句话已经有 2～3 张不同的卡，不用再重复
        r = REPLAY_RATIO
        replay = rng.sample(s1, min(len(s1), int(len(s2) * r / (1 - r)))) if r > 0 else []  # 默认约 30% 是阶段一的复习
        rows = [(2, s) for s in s2] + [(1, s) for s in replay]
    # 有对话分组的数据按组分，其余仍按原始句子分。
    def key(mode, sample):
        return ("group", sample["group"]) if sample.get("group") else ("sample", str(mode), sample["src"], sample["id"])
    keys = sorted({key(m, s) for m, s in rows})
    rng.shuffle(keys)
    n_eval = max(40, len(keys) // 30)
    ev_keys = set(keys[:n_eval])
    tr = [r for r in rows if key(*r) not in ev_keys]
    ev = [r for r in rows if key(*r) in ev_keys]
    tr += [r for r in tr if r[1]["src"] == "curated"] * (curated_repeat - 1)
    rng.shuffle(tr)
    return tr, ev


def encode(tok, mode, sample, max_len):
    msgs = [{"role": "system", "content": SYSTEM[mode]}, {"role": "user", "content": prompt_of(sample)}]
    head = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    full = head + sample["target"].strip() + tok.eos_token
    h_ids = tok(head, add_special_tokens=False)["input_ids"]
    f_ids = tok(full, add_special_tokens=False)["input_ids"]
    if len(f_ids) > max_len or len(f_ids) <= len(h_ids):
        return None
    labels = [-100] * min(len(h_ids), len(f_ids)) + f_ids[len(h_ids):]
    return {"input_ids": f_ids, "labels": labels[:len(f_ids)]}


def load_4bit(base):
    import torch
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig
    return AutoModelForCausalLM.from_pretrained(
        base, device_map={"": 0}, torch_dtype=torch.bfloat16,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                               bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True))


def train(a):
    if a.data_dir and (not a.out or os.path.exists(a.out)):
        raise FileExistsError("输出目录已存在或未指定，请使用新的 --out")
    if a.curated_repeat < 1:
        raise ValueError("人工样本采样倍数至少为 1")
    # 第二版卡片（data\layered_v2，2026-11-09）的数据目录里带着自己的写手系统提示；没有就用上面原来那两句
    sys_path = os.path.join(a.data_dir or os.path.join(ROOT, "data"), "system.json")
    if os.path.exists(sys_path):
        SYSTEM.update({int(k): v for k, v in json.load(open(sys_path, encoding="utf-8")).items()})
        log(f"写手系统提示用 {sys_path}")
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoTokenizer

    # Windows 显存不够时会悄悄借用内存、慢几十倍：限住上限，超了就直接报"显存不够"，让外面换小批量重试
    total_mem = torch.cuda.get_device_properties(0).total_memory
    torch.cuda.set_per_process_memory_fraction(min(0.93, (total_mem - 0.7 * 2**30) / total_mem))
    rng = random.Random(7 + a.stage)
    tok = AutoTokenizer.from_pretrained(a.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tr, ev = build_data(a.stage, rng, a.data_dir, a.curated_repeat)
    tr_enc = [encode(tok, m, s, a.max_len) for m, s in tr]
    ev_enc = [encode(tok, m, s, a.max_len) for m, s in ev]
    tr_enc = [e for e in tr_enc if e is not None]
    ev_enc = [e for e in ev_enc if e is not None]
    log(f"因超过长度或缺少答案，跳过训练 {len(tr) - len(tr_enc)} 条、验证 {len(ev) - len(ev_enc)} 条")
    if not tr_enc or not ev_enc:
        raise ValueError("训练或验证数据为空，请检查数据及 max_len")
    log(f"阶段 {a.stage}：人工样本采样 {a.curated_repeat} 倍，训练 {len(tr_enc)} 条，验证 {len(ev_enc)} 条，最长 {max(len(e['input_ids']) for e in tr_enc)} token，"
        f"batch {a.bs}×{a.accum}")

    model = load_4bit(a.base)
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                            gradient_checkpointing_kwargs={"use_reentrant": False})
    layers = parse_layers(a.layers)
    if a.init_adapter:
        # 日常自学：接着上一轮的适配器往下训（层范围、rank 都沿用它自己的配置）
        from peft import PeftModel
        cfg = json.load(open(os.path.join(a.init_adapter, "adapter_config.json"), encoding="utf-8"))
        have = cfg.get("layers_to_transform")
        if layers and have and sorted(have) != layers:
            raise ValueError(f"--layers {a.layers} 和上一轮适配器的层 {have} 对不上")
        model = PeftModel.from_pretrained(model, a.init_adapter, is_trainable=True)
        log(f"接着 {a.init_adapter} 训（层 {have or '全部'}）")
    else:
        extra = {"layers_to_transform": layers, "layers_pattern": "layers"} if layers else {}
        log(f"只训第 {a.layers} 层（共 {len(layers)} 层）" if layers else "训全部层")
        model = get_peft_model(model, LoraConfig(
            r=a.rank, lora_alpha=a.rank * 2, lora_dropout=0.05, task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"], **extra))

    def batches(data, bs, shuffle):
        idx = list(range(len(data)))
        if shuffle:
            rng.shuffle(idx)
        else:
            idx.sort(key=lambda i: len(data[i]["input_ids"]))
        for i in range(0, len(idx), bs):
            chunk = [data[j] for j in idx[i:i + bs]]
            L = max(len(c["input_ids"]) for c in chunk)
            ids = torch.full((len(chunk), L), tok.pad_token_id)
            lab = torch.full((len(chunk), L), -100)
            att = torch.zeros((len(chunk), L), dtype=torch.long)
            for k, c in enumerate(chunk):
                n = len(c["input_ids"])
                ids[k, :n] = torch.tensor(c["input_ids"])
                lab[k, :n] = torch.tensor(c["labels"])
                att[k, :n] = 1
            yield ids.cuda(), lab.cuda(), att.cuda()

    @torch.no_grad()
    def evaluate():
        model.eval()
        tot, n = 0.0, 0
        for ids, lab, att in batches(ev_enc, a.bs, False):
            tot += model(input_ids=ids, attention_mask=att, labels=lab).loss.item()
            n += 1
        model.train()
        return tot / max(1, n)

    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)
    total = math.ceil(len(tr_enc) / a.bs / a.accum) * a.epochs
    if a.max_steps:
        total = min(total, a.max_steps)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / 20) * max(0.05, 1 - s / max(1, total)))
    log(f"训练前验证损失 {evaluate():.3f}（共 {total} 步）")
    model.train()
    step, t0, run, k = 0, time.time(), 0.0, 0
    done = False
    for ep in range(a.epochs):
        for ids, lab, att in batches(tr_enc, a.bs, True):
            loss = model(input_ids=ids, attention_mask=att, labels=lab).loss / a.accum
            loss.backward()
            run += loss.item()
            k += 1
            if k % a.accum:
                continue
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); opt.zero_grad()
            step += 1
            if step % 10 == 0 or step == total or step in (1, 3):
                el = time.time() - t0
                log(f"  第 {ep + 1} 轮 {step}/{total} 步  损失 {run / max(1, min(10, step)):.3f}  已用 {el / 60:.1f} 分钟，"
                    f"预计还要 {el / step * (total - step) / 60:.0f} 分钟  显存峰值 {torch.cuda.max_memory_allocated() / 2**30:.1f}GB")
                run = 0.0
            if step >= total:
                done = True
                break
        log(f"第 {ep + 1} 轮结束，验证损失 {evaluate():.3f}")
        if done:
            break
    os.makedirs(a.out, exist_ok=True)
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    json.dump({"stage": a.stage, "base": os.path.basename(a.base), "train": len(tr_enc), "eval": len(ev_enc),
               "curated_repeat": a.curated_repeat, "data_dir": a.data_dir, "layers": a.layers or "all", "rank": a.rank,
               "init_adapter": a.init_adapter or None, "lr": a.lr,
               "steps": step, "minutes": round((time.time() - t0) / 60, 1)},
              open(os.path.join(a.out, "run.json"), "w", encoding="utf-8"), ensure_ascii=False)
    log(f"阶段 {a.stage} 保存到 {a.out}")


def parse_layers(spec):
    """"0-23" / "24-35" / "0-11,24-35" → [层号]；不填 = 全部层。"""
    if not spec:
        return None
    out = []
    for part in str(spec).split(","):
        lo, _, hi = part.strip().partition("-")
        out += list(range(int(lo), int(hi or lo) + 1))
    return sorted(set(out))


def merge(a):
    if os.path.exists(a.merged):
        raise FileExistsError(f"合并目标已存在，不覆盖：{a.merged}（换一个新目录名）")
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    log("在内存里合并阶段一（要几分钟，内存会占用 10GB 左右）")
    model = AutoModelForCausalLM.from_pretrained(a.base, torch_dtype=torch.bfloat16, device_map={"": "cpu"},
                                                 low_cpu_mem_usage=True)
    model = PeftModel.from_pretrained(model, a.merge).merge_and_unload()
    tmp = a.merged + ".tmp"
    model.save_pretrained(tmp, safe_serialization=True, max_shard_size="4GB")
    AutoTokenizer.from_pretrained(a.base).save_pretrained(tmp)
    if os.path.exists(a.merged):
        import shutil
        shutil.rmtree(a.merged)
    os.replace(tmp, a.merged)
    log(f"合并完成 -> {a.merged}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, choices=[1, 2])
    ap.add_argument("--base", required=True)
    ap.add_argument("--out")
    ap.add_argument("--data-dir", help="独立训练数据目录，使用时 --out 必须为新目录")
    ap.add_argument("--curated-repeat", type=int, default=1, help="仅对训练部分的人工样本重复采样，默认 1 倍")
    ap.add_argument("--merge")
    ap.add_argument("--merged")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--bs", type=int, default=4)
    ap.add_argument("--accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--max_len", type=int, default=512)
    ap.add_argument("--max_steps", type=int, default=0, help="只跑这么多步（试跑用）")
    ap.add_argument("--layers", default="", help='只训这些层，如 "0-23"（说人话）或 "24-35"（佳树口吻）；不填 = 全部层')
    ap.add_argument("--init-adapter", default="", help="接着这个适配器继续训（日常自学用）；不填 = 新建")
    ap.add_argument("--replay-ratio", type=float, default=0.3, help="阶段二里阶段一数据的复习比例")
    a = ap.parse_args()
    REPLAY_RATIO = a.replay_ratio
    merge(a) if a.merge else train(a)
