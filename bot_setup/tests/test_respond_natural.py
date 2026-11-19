"""Reminders must permit the care and reply style in the owner's examples."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 源码里的 kaju_core
from kaju_core.voice import respond  # noqa: E402


class RespondNaturalTests(unittest.TestCase):
    def test_care_for_tired_speaker_can_name_their_feelings(self):
        note = respond.build_note("今天好累，陪我聊聊", [], "兄长大人")
        self.assertIn("不确定的语气", note)
        self.assertIn("尊重对方的请求", note)
        self.assertNotIn("别把 TA 的情绪说出来", note)
        self.assertNotIn("不是拿 TA 当主语", note)

    def test_gentle_care_is_not_flagged_as_commentary(self):
        self.assertFalse(respond.is_commentary("兄长大人今天应该很累了吧，先好好休息吧"))
        self.assertFalse(respond.is_commentary("兄长大人好像累坏了，佳树陪着呢"))


if __name__ == "__main__":
    unittest.main()
