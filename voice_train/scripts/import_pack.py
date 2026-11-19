r"""把一键训练包带回来的写手（results\20261111-pack\results\<名字>）导入 Ollama：
按 done.json 的 merge_order 把适配器依次合进原模型 → GGUF → Q4_K_M → ollama create。不动线上配置，不删任何旧模型。

    venv\Scripts\python.exe -I scripts\import_pack.py 4b-A 4b-B          （K = 验证损失最低的那份）
    venv\Scripts\python.exe -I scripts\import_pack.py 4b-A --last        （K 换成训到最后一步的那份，名字多个 -last）

名字：kaju-writer-p3-4b-a 这样（p3 = 第三版格式"局面 / 要说到的 / 长短"的训练包）。
8B 需要本机先有 Qwen3-8B 原模型（voice_train\models\Qwen3-8B），没有就跳过并说明。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_learn as dl  # noqa: E402  (make_gguf：合并、转换、量化、导入)

PACK = os.path.join(dl.VT, "results", "20261111-pack", "results")
BASES = {"Qwen/Qwen3-4B-Instruct-2507": os.path.join(dl.VT, "models", "Qwen3-4B-Instruct-2507"),
         "Qwen/Qwen3-8B": os.path.join(dl.VT, "models", "Qwen3-8B")}


def main():
    last = "--last" in sys.argv
    for tag in [a for a in sys.argv[1:] if not a.startswith("--")]:
        src = os.path.join(PACK, tag)
        done = json.load(open(os.path.join(src, "done.json"), encoding="utf-8"))
        base = BASES[done["base_model"]]
        if not os.path.isdir(base):
            print(f"{tag}：本机没有 {done['base_model']}（{base}），跳过", flush=True)
            continue
        adapters = [os.path.join(src, "K-last" if (n == "K" and last) else n) for n in done["merge_order"]]
        name = f"kaju-writer-p3-{tag.lower()}" + ("-last" if last else "")
        out = os.path.join(dl.VT, "results", "20261111-pack", "gguf", name)
        os.makedirs(out, exist_ok=True)
        log = os.path.join(out, "import.log")
        dl.BASE = base  # make_gguf 用这个当原模型
        if done["base_model"] == "Qwen/Qwen3-8B":
            # 8B 带思考开关，训练时关着思考：助手开头后面多一段空的 <think></think>（train.py 的 chat_head）。
            # 模板里不带这段，写手会写出"句尾用上标点符号…"这类乱话（2026-11-11 第一次考试就是这么废掉的）。
            dl.TEMPLATE = os.path.join(dl.VT, "models", "kaju-writer-p3-8b.Modelfile")
        print(f"{tag} → {name}：{' → '.join(done['merge_order'])}，原模型 {os.path.basename(base)}", flush=True)
        dl.make_gguf(name, out, adapters, log)
        print(f"{name} 导入好了", flush=True)


if __name__ == "__main__":
    main()
