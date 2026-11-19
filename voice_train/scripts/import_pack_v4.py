r"""把第四版训练包（最后一次大训练，2026-11-12 借 5090 训的）带回来的写手导入 Ollama：
原模型 Qwen3-8B + H，再接 K 或 R（R = 偏好训练过的 K，二选一，不叠加）→ GGUF → Q4_K_M → ollama create。
不动线上配置，不删任何旧模型。

    （AstrBot 的 venv，要有 openai 包；Ollama 要先开着：local_vision\runtime.ps1 -Action Start）
    python -I scripts\import_pack_v4.py K R

名字：kaju-writer-p4-8b-k / kaju-writer-p4-8b-r（p4 = 第四版卡：没有「长短」、带心情一行）。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_learn as dl  # noqa: E402  (make_gguf：合并、转换、量化、导入)

SRC = os.path.join(dl.VT, "train_pack", "results_v4", "results", "8b-A")
OUT = os.path.join(dl.VT, "train_pack", "results_v4", "gguf")


def main():
    done = json.load(open(os.path.join(SRC, "done.json"), encoding="utf-8"))
    assert done["base_model"] == "Qwen/Qwen3-8B", done["base_model"]
    dl.BASE = os.path.join(dl.VT, "models", "Qwen3-8B")
    # 8B 训练时关着思考：模板里要带空的 <think></think>，否则写乱话（2026-11-11 教训）
    dl.TEMPLATE = os.path.join(dl.VT, "models", "kaju-writer-p3-8b.Modelfile")
    for top in [a for a in sys.argv[1:] if not a.startswith("--")]:
        adapters = [os.path.join(SRC, "H"), os.path.join(SRC, top)]
        name = f"kaju-writer-p4-8b-{top.lower()}"
        out = os.path.join(OUT, name)
        os.makedirs(out, exist_ok=True)
        log = os.path.join(out, "import.log")
        print(f"{name}：Qwen3-8B → H → {top}", flush=True)
        dl.make_gguf(name, out, adapters, log)
        print(f"{name} 导入好了", flush=True)


if __name__ == "__main__":
    main()
