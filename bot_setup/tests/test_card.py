"""Offline tests for kaju_style/card.py (要点卡) + 它和训练包 train_lora.py 是否一字不差。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_card.py
"""

import ast
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kaju_core", "voice"))  # card.py 现在在 kaju_core\voice
import card  # noqa: E402

KIT = r"D:\JiashuBot\kaju_train_kit\scripts\train_lora.py"
failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


for stage, prompt in card.WRITE_SYSTEM.items():
    expect(f"writer {stage} permits feelings, wishes and uncertain guesses",
           all(word in prompt for word in ("感受", "愿望", "猜测")), True)
    expect(f"writer {stage} forbids invented past events", "不编造" in prompt and "发生" in prompt, True)
    expect(f"writer {stage} does not forbid all additions", "卡上没有的事不加" in prompt, False)

expect("card keeps specific feelings, wishes and uncertain guesses",
       all(word in card.EXTRACT for word in ("担心", "想念", "愿望", "猜测", "不确定")), True)
expect("card does not reduce all feelings to category", "心情和感受只放进 emotion" in card.EXTRACT, False)
expect("card keeps names identifying subject and action object",
       all(word in card.EXTRACT for word in ("主体", "动作对象", "称呼")), True)
expect("card does not discard all titles", "不要语气词、称呼、修饰和比喻" in card.EXTRACT, False)


# parse：词表外的情绪丢掉，空了就是"平常"；"无"当空；points 可以是字符串
c = card.parse('好的 {"reply_to": "帅不帅", "emotion": ["期待", "雀跃"], "attitude": "夸、分享", '
               '"points": "帅；也想剪", "ask": "无", "to": "无"}')
expect("parse emotion vocab", c["emotion"], ["期待"])
expect("parse attitude str", c["attitude"], ["夸", "分享"])
expect("parse points str", c["points"], ["帅", "也想剪"])
expect("parse none ask", c["ask"], "")
expect("parse bad emotion → 平常", card.parse('{"emotion": ["不是滋味"], "points": ["x"]}')["emotion"], ["平常"])
expect("parse no points → None", card.parse('{"emotion": ["开心"], "points": []}'), None)
expect("parse junk → None", card.parse("没有 JSON"), None)

text = card.render(c, "私聊", "兄长大人")
expect("render", text, "场合：私聊\n对象：兄长大人\n回哪句：帅不帅\n情绪：期待\n态度：夸、分享\n要点：帅；也想剪\n问：无")
expect("render no reply_to", card.render(dict(c, reply_to=""), "聊天", "对方").split("\n")[2], "情绪：期待")
expect("render to from extractor", card.render(dict(c, to="八奈见学姐"), "群聊").split("\n")[1], "对象：八奈见学姐")

expect("copy none", card.copy_ratio("帅我也想剪", text), 0.0)
expect("copy full", card.copy_ratio("佳树心里暖得不行", "要点：佳树心里暖得不行"), 1.0)
expect("copy ignores quotes", card.copy_ratio("那句「どうか教えてくれ」", "要点：歌词「どうか教えてくれ」"), 0.0)

expect("fix_formal", card.fix_formal("佳树陪着您呢", "佳树陪着兄长大人", "兄长大人"), "佳树陪着兄长大人呢")
expect("fix_formal group", card.fix_formal("学姐，您说的对", "说得对", "哆啦a梦学姐"), "学姐，哆啦a梦学姐说的对")
expect("fix_formal draft had it", card.fix_formal("您好", "您好呀", "兄长大人"), "您好")
expect("sane leak", card.sane("要点：在\n佳树在哦", "佳树在哦"), False)
expect("sane ok", card.sane("佳树在哦", "佳树在哦～"), True)
# 写手自己冒出繁体（2026-11-09 "今天也要上課"）：这一遍不算写好；原稿里本来就有的（作品名）不算
expect("trad chars", card.trad_chars("今天也要上課", "今天还有课要上"), "課")
expect("sane trad", card.sane("今天也要上課", "今天还有课要上呢"), False)
expect("sane trad in draft", card.sane("佳树看过入間人間的书", "入間人間写的那本佳树看过"), True)
expect("trad: simplified words ok", card.trad_chars("晚饭吃快餐了吗，著名的面馆"), "")

p = card.write_prompt(["兄长大人：好无聊"], "场合：私聊")
expect("write_prompt", p, "上下文：\n兄长大人：好无聊\n\n要点卡：\n场合：私聊")
expect("write_prompt no ctx", card.write_prompt([], "x").split("\n")[1], "（没有前文）")
expect("extract_prompt", card.extract_prompt(["a：b"], " 回复 ", "私聊", "兄长大人"), "【聊天】（私聊）\na：b\n\n【回复】（回给兄长大人）\n回复")

# 训练包里的系统提示和输入格式必须和线上一样
if os.path.exists(KIT):
    src = open(KIT, encoding="utf-8").read()
    tree = ast.parse(src)
    kit_system = next(ast.literal_eval(n.value) for n in tree.body
                      if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "SYSTEM")
    expect("kit SYSTEM == card.WRITE_SYSTEM", kit_system, card.WRITE_SYSTEM)
    ns = {}
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "prompt_of")
    exec(compile(ast.Module(body=[fn], type_ignores=[]), KIT, "exec"), ns)
    for ctx in (["兄长大人：好无聊", "佳树：嗯"], []):
        expect(f"kit prompt_of == write_prompt ({len(ctx)})", ns["prompt_of"]({"ctx": ctx, "card": "场合：私聊"}),
               card.write_prompt(ctx, "场合：私聊"))
else:
    print("skip kit check (no kaju_train_kit)")

print("ALL OK" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
