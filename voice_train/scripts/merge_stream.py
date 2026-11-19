"""逐个分片合并 LoRA：基础模型 + 阶段一 adapter（四舍五入到 bf16）+ 阶段二 adapter（再四舍五入到 bf16）。

和训练时一样的顺序：阶段二是在"阶段一合并后存成 bf16"的模型上训练的，所以这里也先合并阶段一、存成 bf16，再加阶段二。
一次只读一个 safetensors 分片（约 4GB），内存不够 16GB 也能做。
用法：python -I merge_stream.py BASE_DIR OUT_DIR ADAPTER1 [ADAPTER2 ...]
"""
import json
import os
import shutil
import sys

import torch
from safetensors import safe_open
from safetensors.torch import load_file, save_file

base, out, adapters = sys.argv[1], sys.argv[2], sys.argv[3:]
os.makedirs(out, exist_ok=False)

deltas = []  # per adapter: {base_key: (A, B, scale)}
for ad in adapters:
    cfg = json.load(open(os.path.join(ad, "adapter_config.json"), encoding="utf-8"))
    assert not cfg.get("use_rslora") and not cfg.get("use_dora"), "only plain LoRA supported"
    scale = cfg["lora_alpha"] / cfg["r"]
    w = load_file(os.path.join(ad, "adapter_model.safetensors"))
    pairs = {}
    for k, v in w.items():
        if ".lora_A." not in k:
            continue
        stem = k.split(".lora_A.")[0]  # base_model.model.model.layers.0.self_attn.q_proj
        bkey = stem.replace("base_model.model.", "", 1) + ".weight"
        B = w[stem + ".lora_B.weight"]
        pairs[bkey] = (v, B, scale)
    extra = [k for k in w if ".lora_" not in k]
    assert not extra, f"adapter has non-LoRA weights: {extra[:3]}"
    print(f"{os.path.basename(ad)}: {len(pairs)} LoRA pairs, scale {scale}", flush=True)
    deltas.append(pairs)

index_path = os.path.join(base, "model.safetensors.index.json")
index = json.load(open(index_path, encoding="utf-8"))
shards = sorted(set(index["weight_map"].values()))
touched = 0
for shard in shards:
    tensors = {}
    with safe_open(os.path.join(base, shard), framework="pt") as f:
        meta = f.metadata()
        for key in f.keys():
            t = f.get_tensor(key)
            for pairs in deltas:
                if key in pairs:
                    A, B, s = pairs[key]
                    t = (t.float() + s * (B.float() @ A.float())).to(torch.bfloat16)
                    touched += 1
            tensors[key] = t.contiguous()
    save_file(tensors, os.path.join(out, shard), metadata=meta or {"format": "pt"})
    print(f"wrote {shard} ({len(tensors)} tensors)", flush=True)
    del tensors

expected = sum(len(p) for p in deltas)
assert touched == expected, f"applied {touched} of {expected} LoRA deltas"
for name in os.listdir(base):
    if not name.endswith(".safetensors") and os.path.isfile(os.path.join(base, name)):
        shutil.copy2(os.path.join(base, name), os.path.join(out, name))
print(f"merged {touched} deltas -> {out}")
