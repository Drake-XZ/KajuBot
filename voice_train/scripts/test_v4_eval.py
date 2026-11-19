import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


PATH = pathlib.Path(__file__).with_name('v4_eval.py')


class BlindEvalTest(unittest.TestCase):
    def test_blind_page_hides_key_and_original_draft(self):
        self.assertTrue(PATH.exists(), '离线盲评工具尚未创建')
        spec = importlib.util.spec_from_file_location('v4_eval', PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rows = [{'id': 'one', 'kind': '群聊', 'ctx': ['学姐：明天见'], 'to': '学姐',
                 'draft': '原稿秘密', 'card': '固定卡秘密',
                 'baseline': '旧版结果', 'candidate': '新版结果'}]
        page, key = module.blind(rows, seed=7)
        self.assertEqual({'旧版结果', '新版结果'}, {page[0]['A'], page[0]['B']})
        self.assertEqual({'baseline', 'candidate'}, set(key['one'].values()))
        self.assertNotIn('draft', page[0])
        self.assertNotIn('card', page[0])
        self.assertNotIn('baseline', str(page))
        self.assertNotIn('candidate', str(page))

    def test_summary_counts_flags_by_real_model(self):
        self.assertTrue(PATH.exists(), '离线盲评工具尚未创建')
        spec = importlib.util.spec_from_file_location('v4_eval', PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.summarize({'one': {'choice': 'A', 'flags': {'A': ['称呼'], 'B': ['事实/指代']}}},
                                  {'one': {'A': 'candidate', 'B': 'baseline'}})
        self.assertEqual(result['wins']['candidate'], 1)
        self.assertEqual(result['flags']['candidate']['称呼'], 1)
        self.assertEqual(result['flags']['baseline']['事实/指代'], 1)

    def test_paired_cli_blinds_html_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            source = root / 'input.jsonl'
            source.write_text(json.dumps({'id': '1', 'kind': '说说', 'ctx': ['素材'],
                                          'baseline': '旧稿', 'candidate': '</script>新稿',
                                          'draft': '不要公开的草稿'}, ensure_ascii=False), encoding='utf-8')
            command = [sys.executable, str(PATH), 'paired', str(source), '--out', str(root / 'out')]
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            page = (root / 'out' / 'review.html').read_text(encoding='utf-8')
            self.assertNotIn('不要公开的草稿', page)
            self.assertNotIn('</script>新稿', page)
            self.assertIn('\\u003c/script>新稿', page)
            again = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(again.returncode, 0)


if __name__ == '__main__':
    unittest.main()
