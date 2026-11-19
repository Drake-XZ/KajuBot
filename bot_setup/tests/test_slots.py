"""每项工作一格模型（kaju_core/slots.py，2026-11-18）：格子空着用主模型；填了按顺序；learner / fast 空着用 utils；
AstrBody.slot_model / _fallbacks 先用格子里的、最后接主模型。"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "stubs"), str(HERE.parent)]

from kaju_core import slots  # noqa: E402


class Slots(unittest.TestCase):
    def test_table(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "model_slots.json")
            self.assertEqual(slots.providers("utils", p), [])  # 没有文件 = 用主模型
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"slots": {"utils": ["a", "b"], "fast": [], "memory": ["m"]}}, f)
            self.assertEqual(slots.providers("utils", p), ["a", "b"])
            self.assertEqual(slots.providers("fast", p), ["a", "b"])  # 空着回退 utils
            self.assertEqual(slots.providers("learner", p), ["a", "b"])
            self.assertEqual(slots.providers("memory", p), ["m"])
            self.assertEqual(slots.providers("emoji", p), [])
            self.assertEqual(slots.slot_rest("a", p), ["b"])
            self.assertEqual(slots.slot_rest("zzz", p), [])


class AstrBodySlots(unittest.TestCase):
    def test_slot_model_and_fallbacks(self):
        import kaju_astr
        provs = {"main", "back", "a", "b"}
        ctx = SimpleNamespace(
            get_provider_by_id=lambda x: object() if x in provs else None,
            get_config=lambda: {"agent_runner": {"config": {"model": {"provider_id": "main", "fallback_provider_ids": ["back"]}}}},
        )
        body = kaju_astr.AstrBody(ctx)

        async def model_id(model="", who=""):
            return model or "main"
        body.model_id = model_id
        real = slots.table
        try:
            slots.table = lambda path="": {}
            self.assertEqual(asyncio.run(body.slot_model("utils")), "main")  # 格子空着：主模型，和原来一样
            self.assertEqual(body._fallbacks("main"), ["back"])
            slots.table = lambda path="": {"utils": ["gone", "a", "b"]}
            self.assertEqual(asyncio.run(body.slot_model("utils")), "a")  # 不在的跳过
            self.assertEqual(asyncio.run(body.slot_model("utils", "b")), "b")  # 插件自己填了就用它
            self.assertEqual(body._fallbacks("a"), ["b", "main", "back"])  # 格子里后面的，再接主模型
            self.assertEqual(body._fallbacks("b"), ["main", "back"])
            self.assertEqual(body._fallbacks("other"), [])
        finally:
            slots.table = real


if __name__ == "__main__":
    unittest.main(verbosity=2)
