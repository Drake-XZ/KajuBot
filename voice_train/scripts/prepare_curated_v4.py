"""Combine approved examples with an existing v4 dataset without changing it.

Input is UTF-8 JSONL. Each row has id, group, split (train/test), kind, to,
ctx, card and target. Group identifies one conversation/day across variants.
The test split remains outside training and can be used for blind evaluation.
"""
import argparse
import json
import shutil
from pathlib import Path


def read_rows(path):
    with path.open(encoding="utf-8-sig") as f:
        return [json.loads(line) for line in f if line.strip()]


def normalized(text):
    return "".join(text.split())


def prepare(source, base, output):
    samples = read_rows(source)
    if not samples:
        raise ValueError("没有可导入的数据")
    base_rows = [read_rows(base / f"stage{stage}.jsonl") for stage in (1, 2)]
    old_targets = {normalized(r["target"]) for rows in base_rows for r in rows}
    ids, groups, answers = set(), {}, {}
    for row in samples:
        if not isinstance(row, dict):
            raise ValueError("每条数据都要是一个 JSON 对象")
        for field in ("id", "group", "split", "kind", "card", "target"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"缺少或无效的字段：{field}")
        if not isinstance(row.get("to"), str) or not isinstance(row.get("ctx"), list) or not all(
                isinstance(item, str) for item in row["ctx"]):
            raise ValueError("to 应为文字，ctx 应为文字列表")
        if row["split"] not in ("train", "test") or row["kind"] not in ("私聊", "群聊", "说说"):
            raise ValueError("split 或 kind 不在允许的范围")
        if f"场合：{row['kind']}" not in row["card"].splitlines():
            raise ValueError("卡片中的场合与 kind 不一致")
        if row["id"] in ids:
            raise ValueError("样本 id 重复")
        ids.add(row["id"])
        if row["group"] in groups and groups[row["group"]] != row["split"]:
            raise ValueError("同一组不能同时用于训练和测试")
        groups[row["group"]] = row["split"]
        target = normalized(row["target"])
        if target in answers and answers[target] != row["split"]:
            raise ValueError("相同答案不能同时用于训练和测试")
        answers[target] = row["split"]
        if row["split"] == "test" and target in old_targets:
            raise ValueError("测试答案已存在于旧训练数据中")
    if set(groups.values()) != {"train", "test"}:
        raise ValueError("需要训练和测试两组数据")

    output.mkdir(parents=False, exist_ok=False)
    shutil.copyfile(base / "stage1.jsonl", output / "stage1.jsonl")
    with (output / "stage2.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for row in base_rows[1]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        for row in samples:
            if row["split"] == "train":
                training = {k: row[k] for k in ("id", "group", "ctx", "card", "target")}
                training.update(src="curated", n=0)
                f.write(json.dumps(training, ensure_ascii=False) + "\n")
    with (output / "holdout.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for row in samples:
            if row["split"] == "test":
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="尚不存在的新目录")
    args = parser.parse_args()
    prepare(args.input, args.base, args.output)
    print("已生成独立训练数据和留出集：", args.output)


if __name__ == "__main__":
    main()
