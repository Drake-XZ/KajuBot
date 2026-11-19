"""The merge must never write into an existing model directory."""
import subprocess
import sys
import tempfile
from pathlib import Path
import json

import torch
from safetensors.torch import load_file, save_file


def test_existing_output_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "existing-model"
        output.mkdir()
        marker = output / "model.safetensors"
        marker.write_bytes(b"existing model")
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("merge_stream.py")),
                                 str(Path(tmp) / "base"), str(output), str(Path(tmp) / "adapter")],
                                capture_output=True)
        assert result.returncode != 0 and b"FileExistsError" in result.stderr
        assert marker.read_bytes() == b"existing model"


def test_new_output_merges_both_adapters():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = root / "base"
        base.mkdir()
        key = "model.layers.0.self_attn.q_proj.weight"
        save_file({key: torch.tensor([[1.0]], dtype=torch.bfloat16)}, base / "model.safetensors")
        (base / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {key: "model.safetensors"}}))
        stem = "base_model.model.model.layers.0.self_attn.q_proj"
        adapters = []
        for idx, delta in enumerate((2.0, 3.0)):
            adapter = root / f"adapter{idx}"
            adapter.mkdir()
            (adapter / "adapter_config.json").write_text(json.dumps({"lora_alpha": 1, "r": 1}))
            save_file({stem + ".lora_A.weight": torch.tensor([[1.0]]),
                       stem + ".lora_B.weight": torch.tensor([[delta]])}, adapter / "adapter_model.safetensors")
            adapters.append(str(adapter))
        output = root / "merged"
        subprocess.run([sys.executable, str(Path(__file__).with_name("merge_stream.py")), str(base), str(output),
                        *adapters], check=True, capture_output=True)
        assert load_file(output / "model.safetensors")[key].item() == 6.0


if __name__ == "__main__":
    test_existing_output_is_rejected()
    test_new_output_merges_both_adapters()
    print("merge output safety passed")
