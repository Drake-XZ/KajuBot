import json, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\JiashuBot\voice_train\scripts")
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from train_lora import encode

base = r"D:\JiashuBot\voice_train\models\Qwen3-4B-Instruct-2507"
tok = AutoTokenizer.from_pretrained(base)
q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
model = AutoModelForCausalLM.from_pretrained(base, device_map={"": 0}, dtype=torch.bfloat16, quantization_config=q)
model.eval()
rows = [json.loads(l) for l in open(r"D:\JiashuBot\voice_train\data\stage1.jsonl", encoding="utf-8")][:6]
for s in rows:
    e = encode(tok, 1, s, 512)
    ids = torch.tensor([e["input_ids"]]).cuda()
    lab = torch.tensor([e["labels"]]).cuda()
    with torch.no_grad():
        out = model(input_ids=ids, labels=lab)
    print(f"loss {out.loss.item():.2f}  target {s['target'][:30]!r}", flush=True)
# batched with padding, like train_lora.batches
B = [encode(tok, 1, s, 512) for s in rows]
L = max(len(b["input_ids"]) for b in B)
ids = torch.full((len(B), L), tok.pad_token_id); lab = torch.full((len(B), L), -100); att = torch.zeros((len(B), L), dtype=torch.long)
for k, b in enumerate(B):
    n = len(b["input_ids"]); ids[k, :n] = torch.tensor(b["input_ids"]); lab[k, :n] = torch.tensor(b["labels"]); att[k, :n] = 1
with torch.no_grad():
    out = model(input_ids=ids.cuda(), attention_mask=att.cuda(), labels=lab.cuda())
print("batched loss", round(out.loss.item(), 2))
print("mem GB", round(torch.cuda.max_memory_allocated() / 1e9, 2))
