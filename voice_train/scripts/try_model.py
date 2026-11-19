"""拿真实草稿试一下训练出来的重说层（transformers + peft，4-bit 加载）。

用法：python -I try_model.py --base models/Qwen3-4B-Instruct-2507 --adapter runs/stage1 --mode 1 --n 8
草稿取自盲选测试的 A 组（DeepSeek + 现在全部提醒）：scratchpad 的 ab_rewrite_out_full.json，或 --pairs 指定。
"""
import argparse
import json
import os
import random
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_lora import SYSTEM, prompt_of  # noqa: E402

DEFAULT = r"C:\Users\18525\AppData\Local\Temp\claude\D--JiashuBot\6e4549e3-02f2-40e8-92f9-919614b08c04\scratchpad\ab_rewrite_out_full.json"


def main():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter")
    ap.add_argument("--mode", type=int, default=1)
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--pairs", default=DEFAULT)
    ap.add_argument("--out")
    a = ap.parse_args()
    tok = AutoTokenizer.from_pretrained(a.base)
    model = AutoModelForCausalLM.from_pretrained(
        a.base, device_map={"": 0}, torch_dtype=torch.bfloat16,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                               bnb_4bit_compute_dtype=torch.bfloat16))
    if a.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, a.adapter)
    model.eval()
    rows = [r for r in json.load(open(a.pairs, encoding="utf-8")) if r["cond"] == "A" and r["k"] == 0]
    rows = random.Random(1).sample(rows, min(a.n, len(rows)))
    out = []
    for r in rows:
        ctx = [c.replace("\n", " / ")[:120] for c in r["ctx"][-3:]] + ["对方：" + r["now"][-150:].replace("\n", " / ")]
        s = {"ctx": ctx, "draft": r["raw"]}
        msgs = [{"role": "system", "content": SYSTEM[a.mode]}, {"role": "user", "content": prompt_of(s)}]
        ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt").to(0)
        with torch.no_grad():
            g = model.generate(ids, max_new_tokens=160, do_sample=True, temperature=0.7, top_p=0.9)
        new = tok.decode(g[0, ids.shape[1]:], skip_special_tokens=True).strip()
        print(f"[{r['kind']}{r['cut']}] 对方：{r['now'][-50:]!r}\n   草稿：{r['raw'].replace(chr(10), ' / ')}\n   重说：{new.replace(chr(10), ' / ')}\n", flush=True)
        out.append({"id": f"{r['kind']}{r['cut']}", "draft": r["raw"], "new": new})
    if a.out:
        json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


main()
