"""QLoRA 训练"重说层"：上下文 + AI 草稿 → 真人/佳树会说的话。

阶段一（像真人）：python -I train_lora.py --stage 1 --base models/Qwen3-4B-Instruct-2507 --out runs/stage1
                    再 --merge runs/stage1 --base ... --merged models/stage1-merged（CPU 上合并，阶段一从此冻结）
阶段二（像佳树）：python -I train_lora.py --stage 2 --base models/stage1-merged --out runs/stage2 （掺 30% 阶段一数据防遗忘）
                    再 --merge runs/stage2 --base models/stage1-merged --merged models/final
"""
import argparse
import json
import math
import os
import random
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SYSTEM = {
    1: ("你是改写器：把 AI 聊天草稿改成真人在 QQ 上会发的样子。长短、用词、挑什么说都像真人："
        "该短就短，客套、解释、总结对方、多余的追问都删掉；不加草稿里没有的事。只输出改好的回复。"),
    2: ("你是改写器：把草稿改成温水佳树（《败犬女主太多了！》里温水和彦的妹妹）在 QQ 上会说的样子，同时像真人："
        "自称佳树，称呼和草稿一致；该短就短，客套和多余的解释删掉；不加草稿里没有的事。只输出改好的回复。"),
}


def prompt_of(sample):
    ctx = "\n".join(sample.get("ctx") or [])
    return f"上下文：\n{ctx}\n\n草稿：\n{sample['draft']}"


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def build_data(stage, rng):
    s1 = load(os.path.join(ROOT, "data", "stage1.jsonl"))
    if stage == 1:
        rows = [(1, s) for s in s1] + [(1, s) for s in s1 if s["src"] == "owner"]  # 他的话权重 ×2
    else:
        s2 = load(os.path.join(ROOT, "data", "stage2.jsonl"))
        replay = rng.sample(s1, min(len(s1), int(len(s2) * 2 * 0.3 / 0.7)))  # 两轮佳树数据里约 30% 是复习
        rows = [(2, s) for s in s2] * 2 + [(1, s) for s in replay]
    rng.shuffle(rows)
    n_eval = max(40, len(rows) // 30)
    return rows[n_eval:], rows[:n_eval]


def encode(tok, mode, sample, max_len):
    msgs = [{"role": "system", "content": SYSTEM[mode]}, {"role": "user", "content": prompt_of(sample)}]
    head = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    full = head + sample["target"].strip() + tok.eos_token
    h_ids = tok(head, add_special_tokens=False)["input_ids"]
    f_ids = tok(full, add_special_tokens=False)["input_ids"][:max_len]
    labels = [-100] * min(len(h_ids), len(f_ids)) + f_ids[len(h_ids):]
    return {"input_ids": f_ids, "labels": labels[:len(f_ids)]}


def train(a):
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    rng = random.Random(7 + a.stage)
    tok = AutoTokenizer.from_pretrained(a.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tr, ev = build_data(a.stage, rng)
    tr_enc = [encode(tok, m, s, a.max_len) for m, s in tr]
    ev_enc = [encode(tok, m, s, a.max_len) for m, s in ev]
    tr_enc = [e for e in tr_enc if any(x != -100 for x in e["labels"])]
    print(f"stage {a.stage}: train {len(tr_enc)}, eval {len(ev_enc)}, "
          f"max tokens {max(len(e['input_ids']) for e in tr_enc)}", flush=True)

    model = AutoModelForCausalLM.from_pretrained(
        a.base, device_map={"": 0}, torch_dtype=torch.bfloat16,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                               bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True))
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(
        r=a.rank, lora_alpha=a.rank * 2, lora_dropout=0.05, task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    model.print_trainable_parameters()

    def batches(data, bs, shuffle):
        idx = list(range(len(data)))
        if shuffle:
            rng.shuffle(idx)
        # 按长度分桶，少填充
        idx = sorted(idx, key=lambda i: len(data[i]["input_ids"])) if not shuffle else idx
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
            out = model(input_ids=ids, attention_mask=att, labels=lab)
            tot += out.loss.item(); n += 1
        model.train()
        return tot / max(1, n)

    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)
    steps_per_epoch = math.ceil(len(tr_enc) / a.bs / a.accum)
    total = steps_per_epoch * a.epochs
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / 20) * max(0.05, 1 - s / max(1, total)))
    print(f"eval loss before: {evaluate():.3f}  ({total} optimizer steps)", flush=True)
    model.train()
    step, t0 = 0, time.time()
    for ep in range(a.epochs):
        run = 0.0
        for k, (ids, lab, att) in enumerate(batches(tr_enc, a.bs, True)):
            loss = model(input_ids=ids, attention_mask=att, labels=lab).loss / a.accum
            loss.backward()
            run += loss.item()
            if (k + 1) % a.accum == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step(); sched.step(); opt.zero_grad()
                step += 1
                if step % 20 == 0:
                    print(f"  ep {ep + 1} step {step}/{total} loss {run / 20:.3f} lr {sched.get_last_lr()[0]:.2e} "
                          f"{(time.time() - t0) / 60:.1f} min", flush=True)
                    run = 0.0
        print(f"epoch {ep + 1} eval loss {evaluate():.3f}", flush=True)
    os.makedirs(a.out, exist_ok=True)
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    json.dump({"stage": a.stage, "base": a.base, "train": len(tr_enc), "eval": len(ev_enc)},
              open(os.path.join(a.out, "run.json"), "w"))
    print("saved", a.out)


def merge(a):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model = AutoModelForCausalLM.from_pretrained(a.base, torch_dtype=torch.bfloat16, device_map={"": "cpu"})
    model = PeftModel.from_pretrained(model, a.merge).merge_and_unload()
    model.save_pretrained(a.merged, safe_serialization=True, max_shard_size="4GB")
    AutoTokenizer.from_pretrained(a.base).save_pretrained(a.merged)
    print("merged ->", a.merged)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, choices=[1, 2])
    ap.add_argument("--base", required=True)
    ap.add_argument("--out")
    ap.add_argument("--merge")
    ap.add_argument("--merged")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--bs", type=int, default=4)
    ap.add_argument("--accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--max_len", type=int, default=512)
    a = ap.parse_args()
    merge(a) if a.merge else train(a)
