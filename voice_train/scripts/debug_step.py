"""一步训练，定位崩溃：python -X faulthandler -I debug_step.py [bs] [reentrant 0/1] [ckpt 0/1]"""
import json, sys, faulthandler
faulthandler.enable()
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\JiashuBot\voice_train\scripts")
import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from train_lora import encode

bs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
reentrant = sys.argv[2] == "1" if len(sys.argv) > 2 else False
ckpt = sys.argv[3] == "1" if len(sys.argv) > 3 else True
base = r"D:\JiashuBot\voice_train\models\Qwen3-4B-Instruct-2507"
tok = AutoTokenizer.from_pretrained(base)
q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
model = AutoModelForCausalLM.from_pretrained(base, device_map={"": 0}, dtype=torch.bfloat16, quantization_config=q)
print("loaded", flush=True)
model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=ckpt,
                                        gradient_checkpointing_kwargs={"use_reentrant": reentrant})
model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, task_type="CAUSAL_LM",
                                         target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
print("peft ok", flush=True)
rows = [json.loads(l) for l in open(r"D:\JiashuBot\voice_train\data\stage1.jsonl", encoding="utf-8")][:bs]
B = [encode(tok, 1, s, 512) for s in rows]
L = max(len(b["input_ids"]) for b in B)
ids = torch.full((len(B), L), tok.pad_token_id); lab = torch.full((len(B), L), -100); att = torch.zeros((len(B), L), dtype=torch.long)
for k, b in enumerate(B):
    n = len(b["input_ids"]); ids[k, :n] = torch.tensor(b["input_ids"]); lab[k, :n] = torch.tensor(b["labels"]); att[k, :n] = 1
model.train()
print("forward...", flush=True)
loss = model(input_ids=ids.cuda(), attention_mask=att.cuda(), labels=lab.cuda()).loss
print("loss", loss.item(), "backward...", flush=True)
loss.backward()
print("backward ok; peak GB", round(torch.cuda.max_memory_allocated() / 1e9, 2), flush=True)
opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=1e-4)
opt.step()
print("step ok", flush=True)
