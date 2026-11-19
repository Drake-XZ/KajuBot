import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("prepare_curated_v4.py")


class CuratedDataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.base = self.root / "base"
        self.base.mkdir()
        for stage in (1, 2):
            (self.base / f"stage{stage}.jsonl").write_text(
                json.dumps({"src": "old", "id": str(stage), "n": 0, "ctx": [],
                            "card": "旧卡", "target": f"旧答案{stage}"}, ensure_ascii=False) + "\n",
                encoding="utf-8")
        self.rows = [
            {"id": "one", "group": "day1", "split": "train", "kind": "说说", "to": "",
             "ctx": ["可公开素材"], "card": "场合：说说\n对象：无\n要点：素材", "target": "训练答案"},
            {"id": "two", "group": "day2", "split": "test", "kind": "群聊", "to": "学姐",
             "ctx": ["学姐：问候"], "card": "场合：群聊\n对象：学姐\n要点：回答", "target": "测试答案",
             "draft": "原稿", "extracted_card": "抽出的卡"},
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def run_prepare(self):
        source = self.root / "curated.jsonl"
        source.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in self.rows), encoding="utf-8")
        return subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "--input", str(source), "--base", str(self.base),
                               "--output", str(self.root / "new")], capture_output=True, text=True, encoding="utf-8")

    def test_train_and_holdout_stay_separate_without_overwriting_original(self):
        result = self.run_prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        stage2 = [json.loads(x) for x in (self.root / "new" / "stage2.jsonl").read_text(encoding="utf-8").splitlines()]
        holdout = [json.loads(x) for x in (self.root / "new" / "holdout.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([x["target"] for x in stage2], ["旧答案2", "训练答案"])
        self.assertEqual([x["target"] for x in holdout], ["测试答案"])
        self.assertEqual(holdout[0]["draft"], "原稿")
        self.assertEqual(holdout[0]["extracted_card"], "抽出的卡")
        self.assertNotIn("训练答案", (self.base / "stage2.jsonl").read_text(encoding="utf-8"))

    def test_rejects_same_conversation_across_splits(self):
        self.rows[1]["group"] = "day1"
        result = self.run_prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("同一组不能同时用于训练和测试", result.stderr)
        self.assertFalse((self.root / "new").exists())

    def test_rejects_holdout_answer_already_in_base(self):
        self.rows[1]["target"] = "旧答案1"
        result = self.run_prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("测试答案已存在于旧训练数据中", result.stderr)
        self.assertFalse((self.root / "new").exists())


if __name__ == "__main__":
    unittest.main()
