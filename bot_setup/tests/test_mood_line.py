"""写手的“心情”那一行（kaju_core.heart.mood_line）：格式和 2026-11-16 晚的“合并重复项”。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_mood_line.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kaju_core.heart.mood_line import mood_line, normalize  # noqa: E402

C = {"src": "content"}


class MoodLineTest(unittest.TestCase):
    def test_basic(self):
        snap = {"mood": {"joy": 0.67, "energy": 0.67, "stress": 0.1, "warm": 0.55},
                "recent": [{"emo": "吃醋", "i": 2}, {"emo": "开心", "i": 1}, {"emo": "感动", "i": 2, **C}],
                "threads": [{"emo": "委屈", "c": 1.4, "kind": "person"}]}
        self.assertEqual(mood_line(snap), "心情：开心6 精神6 紧绷1 亲近5｜刚才：吃醋2 开心1 感动2(看的东西)｜心事：委屈1.4")
        self.assertEqual(mood_line(None), "")
        self.assertEqual(mood_line({"mood": {"joy": 0, "energy": 0, "stress": 0, "warm": 0}}), "心情：开心0 精神0 紧绷0 亲近0")

    def test_merge_reading_day(self):
        """读小说那天：一段一件事，挨着的一样的合成“×次数”；心事同种同来路的合成，取最重的。"""
        snap = {"mood": {"joy": 0.03, "energy": 0.3, "stress": 0.97, "warm": 0.9},
                "recent": [{"emo": "难过", "i": 2, **C}] * 6,
                "threads": [{"emo": "感动", "c": 0.5, "kind": "content"}, {"emo": "感动", "c": 1.1, "kind": "content"},
                            {"emo": "难过", "c": 1.6, "kind": "content"}, {"emo": "担心", "c": 2.3, "kind": "content"},
                            {"emo": "难过", "c": 2.4, "kind": "content"}, {"emo": "难过", "c": 0.05, "kind": "content"}]}
        self.assertEqual(mood_line(snap), "心情：开心0 精神3 紧绷9 亲近8｜刚才：难过2×6(看的东西)｜心事：感动1.1×2(看的东西) 难过2.4×2(看的东西) 担心2.3(看的东西)")

    def test_merge_keeps_order(self):
        """不挨着的照旧分开；强度不同、来路不同都不算一样。"""
        snap = {"mood": {"joy": 0.5, "energy": 0.5, "stress": 0.5, "warm": 0.5},
                "recent": [{"emo": "开心", "i": 1}, {"emo": "开心", "i": 2}, {"emo": "开心", "i": 2},
                           {"emo": "生气", "i": 2}, {"emo": "生气", "i": 3}, {"emo": "生气", "i": 2}],
                "threads": [{"emo": "生气", "c": 1.8, "kind": "person"}, {"emo": "生气", "c": 3.0, "kind": "content"}]}
        self.assertEqual(mood_line(snap), "心情：开心4 精神4 紧绷4 亲近4｜刚才：开心1 开心2×2 生气2 生气3 生气2｜心事：生气1.8 生气3.0(看的东西)")

    def test_last_six_before_merge(self):
        """还是只看最近 6 件，再合并（和原来取的事一样）。"""
        snap = {"mood": {"joy": 0.5, "energy": 0.5, "stress": 0.5, "warm": 0.5},
                "recent": [{"emo": "开心", "i": 1}] * 3 + [{"emo": "担心", "i": 2, **C}] * 6}
        self.assertEqual(mood_line(snap), "心情：开心4 精神4 紧绷4 亲近4｜刚才：担心2×6(看的东西)")

    def test_normalize_old_lines(self):
        """旧格式（合并以前存下的卡）转成新的：和对同一份读数直接调 mood_line 一样；别的行、已经是新格式的不动。"""
        old = ("心情：开心0 精神3 紧绷9 亲近8｜刚才：担心2(看的东西) 担心2(看的东西) 害怕3(看的东西) 难过3(看的东西) 害怕3(看的东西) 难过2(看的东西)"
               "｜心事：感动0.7(看的东西) 感动1.5(看的东西) 难过2.0(看的东西) 担心2.9(看的东西) 害怕3.0(看的东西) 难过3.0(看的东西) 难过2.6(看的东西)")
        new = ("心情：开心0 精神3 紧绷9 亲近8｜刚才：担心2×2(看的东西) 害怕3(看的东西) 难过3(看的东西) 害怕3(看的东西) 难过2(看的东西)"
               "｜心事：感动1.5×2(看的东西) 难过3.0×3(看的东西) 担心2.9(看的东西) 害怕3.0(看的东西)")
        card = "场合：私聊\n对象：兄长大人\n局面：…\n要说到的：无\n" + old
        self.assertEqual(normalize(card), "场合：私聊\n对象：兄长大人\n局面：…\n要说到的：无\n" + new)
        self.assertEqual(normalize(new), new)  # 再转一遍不变
        self.assertEqual(normalize("心情：开心6 精神6 紧绷1 亲近5"), "心情：开心6 精神6 紧绷1 亲近5")
        self.assertEqual(normalize("心情：开心1 精神1 紧绷1 亲近1｜刚才：开心1 开心2 开心2 生气2 生气3 生气2｜心事：生气1.8 生气3.0"),
                         "心情：开心1 精神1 紧绷1 亲近1｜刚才：开心1 开心2×2 生气2 生气3 生气2｜心事：生气3.0×2")
        self.assertEqual(normalize("没有心情行"), "没有心情行")
        snap = {"mood": {"joy": 0.5, "energy": 0.5, "stress": 0.5, "warm": 0.5},
                "recent": [{"emo": "难过", "i": 2, "src": "content"}] * 4 + [{"emo": "开心", "i": 1}],
                "threads": [{"emo": "难过", "c": 1.64, "kind": "content"}, {"emo": "难过", "c": 2.38, "kind": "content"}]}
        old_style = "心情：开心4 精神4 紧绷4 亲近4｜刚才：" + " ".join(["难过2(看的东西)"] * 4 + ["开心1"]) + "｜心事：难过1.6(看的东西) 难过2.4(看的东西)"
        self.assertEqual(normalize(old_style), mood_line(snap))


if __name__ == "__main__":
    unittest.main()
