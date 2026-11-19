"""Offline tests for reading text files sent to her (kaju_basics docs.py + Describer.document + describe_media).

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_docs.py
    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_docs.py --live   # 真模型：读后笔记 + 她读完的回复 + 情绪判断（只打印）
"""

import asyncio
import importlib
import json
import os
import sys
import tempfile
import zipfile

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, PLUGINS)
sys.path.insert(0, os.path.dirname(os.path.abspath(PLUGINS)))  # 源码里的 kaju_core
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.message_components import File, Plain, Reply  # noqa: E402
from astrbot.api.provider import LLMResponse, ProviderRequest  # noqa: E402
from astrbot.api.star import Context  # noqa: E402
from astrbot.core.agent.message import TextPart  # noqa: E402

docs = importlib.import_module("kaju_core.senses.docs")
kb = importlib.import_module("kaju_basics.main")
failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


TMP = tempfile.mkdtemp()


def put(name, data: bytes | str) -> str:
    path = os.path.join(TMP, name)
    with open(path, "wb") as f:
        f.write(data.encode("utf-8") if isinstance(data, str) else data)
    return path


def make_pdf(path, lines):
    """A tiny valid one-page PDF with ASCII text (Helvetica), xref offsets computed."""
    stream = "BT /F1 12 Tf 72 720 Td " + " ".join(f"({ln}) Tj 0 -16 Td" for ln in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    with open(path, "wb") as f:
        f.write(out)


# ------------------------------------------------------------------ docs.py
expect("kind txt", docs.doc_kind("小说第三章.TXT"), "text")
expect("kind srt", docs.doc_kind("a.srt"), "text")
expect("kind docx/pdf/epub/html", [docs.doc_kind(n) for n in ("a.docx", "b.pdf", "c.epub", "d.htm")],
       ["docx", "pdf", "epub", "html"])
expect("kind unknown", [docs.doc_kind(n) for n in ("a.zip", "b.doc", "c.exe", "")], [None, None, None, None])

story = "第一章\r\n\r\n\r\n\r\n小八每天都去车站等主人。\u3000\u3000\n雨下了十年。"
expect("utf8 bom", docs.read(put("u.txt", b"\xef\xbb\xbf" + story.encode("utf-8")), "text")[0],
       "第一章\n\n小八每天都去车站等主人。\n雨下了十年。")
expect("gbk (记事本)", docs.read(put("g.txt", story.encode("gbk")), "text")[0].splitlines()[-1], "雨下了十年。")
expect("html", docs.read(put("p.html", "<html><head><title>t</title><style>x{}</style></head><body><p>你好</p>"
                                       "<script>alert(1)</script><p>世界</p></body></html>"), "html")[0], "你好\n世界")

import docx  # noqa: E402

d = docx.Document()
d.add_paragraph("致佳树的一封信")
d.add_paragraph("谢谢你一直陪着我。")
t = d.add_table(rows=1, cols=2)
t.rows[0].cells[0].text, t.rows[0].cells[1].text = "日期", "10月31日"
d.save(os.path.join(TMP, "letter.docx"))
expect("docx", docs.read(os.path.join(TMP, "letter.docx"), "docx")[0], "致佳树的一封信\n谢谢你一直陪着我。\n日期 | 10月31日")

make_pdf(os.path.join(TMP, "a.pdf"), ["Hello Kaju", "The end."])
text, info = docs.read(os.path.join(TMP, "a.pdf"), "pdf")
expect("pdf", ("Hello Kaju" in text, "The end." in text, info), (True, True, "共 1 页"))
make_pdf(os.path.join(TMP, "scan.pdf"), [])
expect("pdf no text", docs.read(os.path.join(TMP, "scan.pdf"), "pdf")[0], "")

with zipfile.ZipFile(os.path.join(TMP, "book.epub"), "w") as z:
    z.writestr("mimetype", "application/epub+zip")
    z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
               '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
    z.writestr("OEBPS/content.opf", '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf"><manifest>'
               '<item id="c2" href="text/b.xhtml" media-type="application/xhtml+xml"/>'
               '<item id="c1" href="text/z.xhtml" media-type="application/xhtml+xml"/></manifest>'
               '<spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>')
    z.writestr("OEBPS/text/z.xhtml", "<html><body><h1>第一章</h1><p>开始</p></body></html>")
    z.writestr("OEBPS/text/b.xhtml", "<html><body><h1>第二章</h1><p>结局</p></body></html>")
expect("epub spine order", docs.read(os.path.join(TMP, "book.epub"), "epub")[0], "第一章\n开始\n第二章\n结局")

long = "".join(f"第{i}段。" for i in range(2000))
c = docs.clip(long, 100)
expect("clip keeps head+tail", (c.startswith("第0段"), c.endswith("第1999段。"), "中间省略约" in c), (True, True, True))
expect("clip short untouched", docs.clip("短", 100), "短")
expect("excerpt", docs.excerpt("一  二\n三四五六", 4), "一 二 …")


# ------------------------------------------------------------------ Describer.document + describe_media
class FakeProvider:
    provider_config = {"id": "ds"}


class FakeGcc:
    def __init__(self): self.lines = []

    async def handle_message(self, event):
        self.lines.append("".join(c.text for c in event.get_messages() if isinstance(c, Plain)))


def make(answer: "str | Exception" = "这是一篇小说。读后笔记……「我等你」"):
    gcc = FakeGcc()
    ctx = Context({"timezone": "Asia/Shanghai", "provider_ltm_settings": {"group_icl_enable": True}})
    ctx.stars = [type("Meta", (), {"star_cls": type("S", (), {"group_chat_context": gcc})()})()]
    ctx.providers = {"ds": FakeProvider()}
    calls = []

    async def llm_generate(chat_provider_id, prompt, system_prompt=None):
        calls.append(prompt)
        if isinstance(answer, Exception):
            raise answer
        return LLMResponse(answer)

    ctx.llm_generate = llm_generate
    return kb.KajuBasics(ctx, {"media": {"doc_direct_chars": 200, "doc_group_excerpt": 10}}), gcc, calls


async def plugin_tests():
    b, gcc, calls = make()
    short = File(name="短.txt", file=put("short.txt", "佳树，生日快乐！"))
    out = await b._describer.document(short, AstrMessageEvent())
    expect("short doc full text", out, "约 8 字，全文：\n佳树，生日快乐！")
    expect("short doc no llm", calls, [])

    novel = File(name="小说.txt", file=put("novel.txt", "开头：她在车站等他。" + "等待。" * 300 + "结尾：信寄出的那天，战争结束了。"))
    out = await b._describer.document(novel, AstrMessageEvent())
    expect("long doc digest", ("读后笔记：\n这是一篇小说" in out, "开头原文：开头：她在车站等他" in out,
                               "结尾原文：…" in out and "战争结束了" in out), (True, True, True))
    expect("digest prompt has text+name", ("《小说.txt》" in calls[0], "战争结束了" in calls[0]), (True, True))
    await b._describer.document(novel, AstrMessageEvent())
    expect("doc cached", len(calls), 1)

    b2, _, _ = make(answer=RuntimeError("超时"))
    out = await b2._describer.document(File(name="小说.txt", file=put("novel2.txt", "甲" * 150 + "乙" * 150)), AstrMessageEvent())
    expect("digest fails → head+tail", ("只看了开头和结尾" in out, out.rstrip().endswith("乙")), (True, True))
    out = await b._describer.document(File(name="a.zip", file=put("a.zip", b"PK")), AstrMessageEvent())
    expect("unsupported", out.startswith("没读成：这种文件佳树打不开"), True)
    out = await b._describer.document(File(name="scan.pdf", file=os.path.join(TMP, "scan.pdf")), AstrMessageEvent())
    expect("scanned pdf", out.startswith("没读成：打开了，但里面读不出文字"), True)
    out = await b._describer.document(File(name="gone.txt", file=os.path.join(TMP, "nope.txt")), AstrMessageEvent())
    expect("missing file", out.startswith("没读成：文件没能下载下来"), True)

    # 私聊直接发文件：AstrBot 的 [File Attachment …] 换成读到的内容，系统提示里说明
    ev = AstrMessageEvent(messages=[short])
    req = ProviderRequest("SYS")
    req.extra_user_content_parts.append(TextPart("[File Attachment: name 短.txt, path x]"))
    await b.describe_media(ev, req)
    texts = [p.text for p in req.extra_user_content_parts]
    expect("direct file replaced", texts, ["[File: 短.txt] 约 8 字，全文：\n佳树，生日快乐！"])
    expect("doc note", "【关于文件】" in req.system_prompt, True)
    # 引用一个文件问她
    ev = AstrMessageEvent(group="1", text="这个你看看", messages=[Reply(chain=[short]), Plain("这个你看看")])
    req = ProviderRequest("SYS")
    req.extra_user_content_parts.append(TextPart("[File Attachment in quoted message: name 短.txt, path x]"))
    await b.describe_media(ev, req)
    expect("quoted file replaced", [p.text for p in req.extra_user_content_parts],
           ["[File in quoted message: 短.txt] 约 8 字，全文：\n佳树，生日快乐！"])
    # 没有文件：不动
    req = ProviderRequest("SYS")
    await b.describe_media(AstrMessageEvent(text="你好", messages=[Plain("你好")]), req)
    expect("no file untouched", (req.system_prompt, req.extra_user_content_parts), ("SYS", []))
    # 群聊记录：文件名 + 开头几句
    ev = AstrMessageEvent(group="1", messages=[novel])
    await gcc.handle_message(ev)
    expect("group excerpt", gcc.lines[-1], " [File: 小说.txt，开头：开头：她在车站等他。…]")
    ev = AstrMessageEvent(group="1", messages=[File(name="a.zip", file=put("b.zip", b"PK"))])
    await gcc.handle_message(ev)
    expect("group unknown file name only", gcc.lines[-1], " [File: a.zip]")
    b_off = kb.KajuBasics(Context(), {"media": {"doc": False}})
    req = ProviderRequest("SYS")
    req.extra_user_content_parts.append(TextPart("[File Attachment: name 短.txt, path x]"))
    await b_off.describe_media(AstrMessageEvent(messages=[short]), req)
    expect("doc off untouched", req.extra_user_content_parts[0].text, "[File Attachment: name 短.txt, path x]")


asyncio.run(plugin_tests())


# ------------------------------------------------------------------ live
async def live():
    """真模型：给一篇短篇小说写读后笔记 → 她用真人设读完回复 → 情绪判断（只打印）。"""
    from openai import AsyncOpenAI

    appraise = importlib.import_module("kaju_core.heart.appraise")
    core = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
    cfg = json.load(open(os.path.join(core, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = src.get("key") or src.get("api_key")
    cli = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"])

    async def chat(system, user):
        r = await cli.chat.completions.create(model="deepseek-flash", messages=[
            {"role": "system", "content": system}, {"role": "user", "content": user}])
        return r.choices[0].message.content.strip()

    parts = ["阿禾是镇上的邮差。每天傍晚，他都会在老槐树下多停一会儿，因为住在树边的林婆婆总会问他：今天有我儿子的信吗？",
             "林婆婆的儿子十年前去了南方打工，起初每月一封信，后来变成每年一封，再后来就没有了。",
             "阿禾知道，镇上的人都说她儿子早就不在了。可他每次都说：快了，路上耽搁了。"] + \
            [f"那年秋天的第{i}天，阿禾照例经过老槐树，林婆婆坐在门口，手里织着一件永远织不完的毛衣，问他同样的问题。" for i in range(1, 60)] + \
            ["冬至那天，阿禾终于从邮局的旧信堆里翻出一封信，信封发黄，邮戳是九年前的。是她儿子写的，只有一句：妈，等我回家过年。",
             "他跑到老槐树下，门开着，屋里很安静。邻居说，林婆婆前一晚走了，走的时候手里还攥着那件毛衣。",
             "阿禾把信放在她的门槛上，站了很久。那天镇上下了第一场雪。"]
    text = "\n".join(parts)
    describe = importlib.import_module("kaju_basics.describe")
    digest = await chat(describe.DOC_SYSTEM,
                        describe.DOC_DIGEST_PROMPT.format(name="邮差.txt", note="", limit=1200, text=text))
    print(f"=== 读后笔记（原文 {len(text)} 字）\n{digest}\n")
    persona = open(os.path.join(os.environ.get("KAJU_DATA") or r"D:\JiashuBot\kaju_data", "self", "persona", "persona.txt"), encoding="utf-8").read()
    user = ("[发言人：晴川（QQ 111111111）] 给你看个故事\n[File: 邮差.txt] 约 %d 字，已经读完了。读后笔记：\n%s\n\n"
            "<system_reminder>%s</system_reminder>") % (len(text), digest, kb.DOC_NOTE)
    replies = await asyncio.gather(*(chat(persona, user) for _ in range(3)))
    for r in replies:
        print("佳树：", r.replace("\n", " / "))
    prompt = appraise.build_prompt(who="晴川", is_owner=True, level="", place="私聊",
                                   context=f"[File: 邮差.txt] 读后笔记：{digest[:500]}", said="给你看个故事", reply=replies[0])
    print("\n=== 情绪判断\n", appraise.parse(await chat(appraise.system_prompt(), prompt)))


if "--live" in sys.argv:
    asyncio.run(live())
print("ALL OK" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
