"""从 LCCC-base 训练集（680 万段，MIT）挑 v4 阶段一用的对话：最后一句当"真人说的话"，前面几句当上下文。

过滤：链接 / @ / 话题 / 转发抽奖广告、脏话、刷屏重复、太长的微博正文；短回复（≤6 字）最多占 25%。
用法：python -I pick_lccc_v4.py [--n 26000] → data/v4_lccc_pick.jsonl {id, ctx, target}
"""
import argparse
import gzip
import json
import os
import random
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "downloads", "lccc", "lccc_base_train.jsonl.gz")
OUT = os.path.join(ROOT, "data", "v4_lccc_pick.jsonl")

BAD = re.compile(r"https?|www|\.com|@|#|转发|微博|关注|粉丝|抽奖|求转|代购|淘宝|加我|私信|二维码|链接|点赞|楼主|沙发|"
                 r"傻逼|傻b|sb|草泥马|尼玛|你妈|妈的|操你|卧槽|我操|屌|逼|婊|鸡巴|日你|死全家|脑残|贱人|滚粗|去死|"
                 r"\d{6,}|[a-zA-Z]{12,}", re.I)
REPEAT = re.compile(r"(.)\1{5,}")
CJK = re.compile(r"[一-鿿]")


def despace(t: str) -> str:
    """LCCC is tokenized with spaces: drop them except between two latin/number tokens."""
    return re.sub(r"(?<![A-Za-z0-9]) | (?![A-Za-z0-9])", "", t.strip())


def ok_turn(t: str, max_len: int) -> bool:
    return (1 <= len(t) <= max_len and not BAD.search(t) and not REPEAT.search(t)
            and len(CJK.findall(t)) >= len(t) * 0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=26000)
    ap.add_argument("--seed", type=int, default=44)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    pool, seen, total, passed = [], set(), 0, 0
    keep = a.n * 3
    with gzip.open(SRC, "rt", encoding="utf-8") as f:
        for line in f:
            total += 1
            turns = [despace(t) for t in json.loads(line)]
            if not 2 <= len(turns) <= 8:
                continue
            *ctx, target = turns
            if not ok_turn(target, 60) or not all(ok_turn(t, 80) for t in ctx):
                continue
            if len(set(re.sub(r"\W", "", target))) < 2:  # 只有"哈哈哈"、标点
                continue
            key = target[:12]
            if key in seen:
                continue
            seen.add(key)
            passed += 1
            item = (ctx, target)
            if len(pool) < keep:  # 蓄水池抽样：每段被留下的机会一样
                pool.append(item)
            else:
                j = rng.randrange(passed)
                if j < keep:
                    pool[j] = item
            if total % 1000000 == 0:
                print(f"  看了 {total} 段，合格 {passed}")
    rng.shuffle(pool)
    # 多轮的优先（上下文更像聊天），短回复限 25%
    pool.sort(key=lambda x: -min(len(x[0]), 3) + rng.random() * 1.5)
    short_cap, short, out = int(a.n * 0.25), 0, []
    for ctx, target in pool:
        if len(target) <= 6:
            if short >= short_cap:
                continue
            short += 1
        out.append((ctx, target))
        if len(out) >= a.n:
            break
    rng.shuffle(out)
    roles = lambda n: ["对方" if (n - i) % 2 else "我" for i in range(n)]  # noqa: E731  最后一句前面那句是"对方"
    with open(OUT, "w", encoding="utf-8") as f:
        for i, (ctx, target) in enumerate(out):
            lab = [f"{r}：{t}" for r, t in zip(roles(len(ctx)), ctx)]
            f.write(json.dumps({"id": f"l{i + 1}", "ctx": lab[-6:], "target": target}, ensure_ascii=False) + "\n")
    turns = [len(c) + 1 for c, _ in out]
    print(f"共 {total} 段，合格 {passed}，写出 {len(out)} -> {OUT}")
    print(f"  轮数：2 轮 {turns.count(2)}，3 轮 {turns.count(3)}，4 轮以上 {sum(t >= 4 for t in turns)}；短回复 {short}")
    lens = sorted(len(t) for _, t in out)
    print(f"  回复长度 中位 {lens[len(lens) // 2]}，90% {lens[int(len(lens) * .9)]}")


if __name__ == "__main__":
    main()
