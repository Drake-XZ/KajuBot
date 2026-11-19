"""Check that style reminders allow complete sentences and natural subjects."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 源码里的 kaju_core
from kaju_core.voice import rhythm  # noqa: E402


class NaturalStyleTests(unittest.TestCase):
    """2026-11-13 句子说短 / 说大白话 / 句尾语气那几条提醒删了，只剩聊天节奏的提醒。"""

    def test_rhythm_note_allows_complete_sentences(self):
        self.assertNotIn("一条消息基本就一句话", rhythm.NOTE)
        self.assertNotIn("话没说完就换行", rhythm.NOTE)


if __name__ == "__main__":
    unittest.main()
