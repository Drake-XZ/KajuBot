"""回复器看到的长前文（kaju_core.voice.longctx，2026-11-17 第 7 轮为写手做的，11-21 起给回复器用）。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_longctx.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kaju_core.voice import longctx as L  # noqa: E402


class LongCtxTest(unittest.TestCase):
    def test_format_with_time_and_day(self):
        items = [("2026-11-14", "23:50", "兄长大人", "晚安"), ("2026-11-14", "23:51", "佳树", "兄长大人晚安\n明天见"),
                 ("2026-11-15", "09:02", "兄长大人", "早")]
        self.assertEqual(L.format_lines(items), ["【11-14】", "23:50 兄长大人：晚安", "23:51 佳树：兄长大人晚安 / 明天见",
                                                 "【11-15】", "09:02 兄长大人：早"])

    def test_clean_numbers_links_paths(self):
        out = L.format_lines([(None, None, "兄长大人", "@555(777777777) 看这个 https://b23.tv/abc 好看"),
                              (None, None, "兄长大人", "[File Attachment: name a.png, path C:\\Users\\x\\a.png]")])
        self.assertEqual(out, ["兄长大人：@555 看这个 [链接] 好看", "兄长大人：[文件 a.png]"])

    def test_trim_keeps_day_line(self):
        lines = ["【11-14】", "23:50 兄长大人：晚安", "【11-15】", "09:02 兄长大人：早", "09:03 佳树：早呀"]
        self.assertEqual(L.trim(lines, max_lines=2), ["【11-15】", "09:02 兄长大人：早", "09:03 佳树：早呀"])
        self.assertEqual(L.trim(lines, max_lines=3), lines)
        self.assertEqual(L.trim(["【11-15】", "09:02 a：" + "长" * 60, "09:03 b：短"], max_chars=30), ["【11-15】", "09:03 b：短"])
        self.assertEqual(L.trim(["对方：一", "我：二"], max_lines=1), ["我：二"])

    def test_no_time_sources(self):
        self.assertEqual(L.format_lines([(None, None, "对方", "真的吗？"), (None, None, "我", "真的")]), ["对方：真的吗？", "我：真的"])

    def test_caps(self):
        items = [("2026-11-15", f"10:{i:02d}", "兄长大人", f"第{i}句") for i in range(30)]
        out = L.format_lines(items)
        self.assertEqual(out[0], "【11-15】")
        self.assertEqual(len(out) - 1, L.MAX_LINES)
        self.assertTrue(out[-1].endswith("第29句"))
        long = [("2026-11-15", "10:00", "兄长大人", "长" * 150)] * 20
        out = L.format_lines(long)
        self.assertLessEqual(sum(len(x) for x in out), L.MAX_CHARS + 200)
        self.assertEqual(L.format_lines([]), [])

    def test_from_log(self):
        recs = [{"d": "2026-11-15", "t": "21:30", "u": "111111111", "n": "晴川", "x": "读完了吗"},
                {"d": "2026-11-15", "t": "21:31", "u": "self", "n": "佳树", "x": "读完啦"},
                {"d": "2026-11-15", "t": "21:32", "u": "111111111", "n": "晴川", "x": ""}]
        title = lambda uid, name: "兄长大人" if uid == "111111111" else name  # noqa: E731
        out = L.from_log(recs, title, current=("2026-11-15", "21:36", "兄长大人", "感想呢？"))
        self.assertEqual(out, ["【11-15】", "21:30 兄长大人：读完了吗", "21:31 佳树：读完啦", "21:36 兄长大人：感想呢？"])


class LiveTest(unittest.TestCase):
    """mind.StyleMind._long_ctx：线上从 kaju_life 记录拿长前文，最后一行是对方这一句（含引用）。"""

    def _fake(self, recs):
        import datetime as dt
        import types
        from kaju_core.voice.mind import StyleMind
        diary = types.SimpleNamespace(recent=lambda chat, n: [r for r in recs if r["c"] == chat][-n:])
        body = types.SimpleNamespace(find=lambda name: types.SimpleNamespace(diary=diary))
        me = types.SimpleNamespace(body=body, _tz=dt.timezone(dt.timedelta(hours=8)), _ctx_end=StyleMind._ctx_end)
        return lambda ev, cur: StyleMind._long_ctx(me, ev, lambda uid, name: "兄长大人" if uid == "1" else name, "兄长大人", cur)

    def _ev(self, gid, sender, text):
        import types
        return types.SimpleNamespace(get_group_id=lambda: gid, get_sender_id=lambda: sender, message_str=text)

    def test_private_with_current_in_log(self):
        recs = [{"d": "2026-11-15", "t": "21:30", "c": "p1", "u": "1", "n": "光风", "x": "读完了吗"},
                {"d": "2026-11-15", "t": "21:31", "c": "p1", "u": "self", "n": "佳树", "x": "读完啦"},
                {"d": "2026-11-15", "t": "21:31", "c": "g9", "u": "7", "n": "路人", "x": "别的群"},
                {"d": "2026-11-16", "t": "09:00", "c": "p1", "u": "1", "n": "光风", "x": "感想呢"}]
        out = self._fake(recs)(self._ev(None, "1", "感想呢"), "感想呢（引用佳树：读完啦）")
        self.assertEqual(out, ["【11-15】", "21:30 兄长大人：读完了吗", "21:31 佳树：读完啦", "【11-16】",
                               "09:00 兄长大人：感想呢（引用佳树：读完啦）"])

    def test_burst_not_doubled(self):
        """连发合并的几条只在最后一行出现一次（11-17 16:33 线上：一条条一遍、合并的又一遍）。"""
        recs = [{"d": "2026-11-17", "t": "16:20", "c": "p1", "u": "self", "n": "佳树", "x": "兄长大人加油"},
                {"d": "2026-11-17", "t": "16:33", "c": "p1", "u": "1", "n": "光风", "x": "我考完回来了"},
                {"d": "2026-11-17", "t": "16:33", "c": "p1", "u": "1", "n": "光风", "x": "有点难呢"},
                {"d": "2026-11-17", "t": "16:33", "c": "p1", "u": "1", "n": "光风", "x": "有点担心会不会挂"}]
        merged = "我考完回来了\n有点难呢\n有点担心会不会挂"
        out = self._fake(recs)(self._ev(None, "1", merged), merged.replace("\n", " / "))
        self.assertEqual(out, ["【11-17】", "16:20 佳树：兄长大人加油", "16:33 兄长大人：我考完回来了 / 有点难呢 / 有点担心会不会挂"])

    def test_group_not_in_log_and_empty(self):
        recs = [{"d": "2026-11-15", "t": "20:00", "c": "g9", "u": "7", "n": "路人", "x": "在吗"}]
        out = self._fake(recs)(self._ev(9, "1", "佳树在吗"), "佳树在吗")
        self.assertEqual(out[:2], ["【11-15】", "20:00 路人：在吗"])
        self.assertTrue(out[-1].endswith(" 兄长大人：佳树在吗"))
        self.assertIsNone(self._fake([])(self._ev(None, "1", "x"), "x"))


if __name__ == "__main__":
    unittest.main()
