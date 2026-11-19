"""离线盲评。

fixed HOLDOUT --baseline MODEL --candidate MODEL --out 新目录
  从留出集 JSONL 的 ctx/card 生成两版回复（仅连接本机 Ollama）。
paired CANDIDATES --out 新目录
  接受其他离线流程生成的 JSONL，每条需 id、kind、ctx、baseline、candidate。
summary VOTES KEY
  汇总页面下载的投票和同目录的 key.json。

页面不发布消息；端到端评估须由调用方提供经过完整流程的最终候选。
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import random
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bot_setup' / 'kaju_core' / 'voice'))
import card  # noqa: E402
import rewrite  # noqa: E402


def blind(rows, seed=7):
    rng = random.Random(seed)
    page, key = [], {}
    for row in rows:
        ident = str(row['id'])
        if ident in key:
            raise ValueError(f'重复的题目编号：{ident}')
        order = ['baseline', 'candidate']
        rng.shuffle(order)
        key[ident] = dict(zip(('A', 'B'), order))
        page.append({'id': ident, 'kind': row['kind'], 'ctx': row.get('ctx', []),
                     'to': row.get('to', ''), 'A': row[order[0]], 'B': row[order[1]]})
    return page, key


def summarize(votes, key):
    wins = Counter()
    flags = {'baseline': Counter(), 'candidate': Counter()}
    for ident, vote in votes.items():
        if ident not in key:
            raise ValueError(f'投票编号不在答案表中：{ident}')
        choice = vote.get('choice', '')
        if choice in ('A', 'B'):
            wins[key[ident][choice]] += 1
        elif choice in ('same', 'neither'):
            wins[choice] += 1
        for side, labels in vote.get('flags', {}).items():
            if side not in ('A', 'B'):
                raise ValueError(f'未知选项：{side}')
            flags[key[ident][side]].update(set(labels))
    return {'wins': dict(wins), 'flags': {k: dict(v) for k, v in flags.items()},
            'voted': sum(bool(v.get('choice')) for v in votes.values()), 'total': len(key)}


def write_fixed(row, model):
    body = json.dumps({'model': model, 'temperature': 0.7, 'top_p': 0.9, 'max_tokens': 220,
                       'messages': [{'role': 'system', 'content': card.WRITE_SYSTEM[2]},
                                    {'role': 'user', 'content': card.write_prompt(row['ctx'], row['card'])}]},
                      ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request('http://127.0.0.1:11435/v1/chat/completions', body,
                                     {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.load(response)
    text = rewrite.clean_output(result['choices'][0]['message']['content'])
    if not text.strip():
        raise ValueError(f"题目 {row['id']} 的模型输出为空")
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    fixed = sub.add_parser('fixed')
    fixed.add_argument('input', type=Path)
    fixed.add_argument('--baseline', required=True)
    fixed.add_argument('--candidate', required=True)
    fixed.add_argument('--out', type=Path, required=True)
    paired = sub.add_parser('paired')
    paired.add_argument('input', type=Path)
    paired.add_argument('--out', type=Path, required=True)
    summary = sub.add_parser('summary')
    summary.add_argument('votes', type=Path)
    summary.add_argument('key', type=Path)
    args = parser.parse_args()
    if args.action == 'summary':
        print(json.dumps(summarize(json.loads(args.votes.read_text(encoding='utf-8')),
                                   json.loads(args.key.read_text(encoding='utf-8'))), ensure_ascii=False, indent=2))
        return
    if args.out.exists():
        raise FileExistsError(f'输出目录已存在，请换一个新目录：{args.out}')
    rows = [json.loads(line) for line in args.input.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    if not rows:
        raise ValueError('没有评测题目')
    if args.action == 'fixed':
        for model, name in ((args.baseline, 'baseline'), (args.candidate, 'candidate')):
            for n, row in enumerate(rows, 1):
                row[name] = write_fixed(row, model)
                print(f'{name}: {n}/{len(rows)}', flush=True)
    if any(not isinstance(row.get(k), str) or not row[k].strip() for row in rows for k in ('baseline', 'candidate')):
        raise ValueError('每个候选都必须有非空正文')
    page, key = blind(rows)
    template = (ROOT / 'voice_train' / 'review' / 'v4_eval.template.html').read_text(encoding='utf-8')
    data = json.dumps(page, ensure_ascii=False).replace('<', '\\u003c')
    args.out.mkdir(parents=True)
    (args.out / 'review.html').write_text(template.replace('__ITEMS__', data), encoding='utf-8')
    (args.out / 'key.json').write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'盲评页面：{args.out / "review.html"}')
    print('key.json 请在投票结束后再查看。')


if __name__ == '__main__':
    main()
