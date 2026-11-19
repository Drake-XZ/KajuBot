"""gemsig：空文字补空格；没签名的 function_call 补占位签名（daitu 改写成文字），有真签名的不动；装上 / 卸下。"""
import asyncio
import os
import sys
import types

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins"))

from kaju_basics import gemsig  # noqa: E402

fails = []


def expect(name, got, want):
    if got != want:
        fails.append(name)
        print(f"FAIL {name}: {got!r} != {want!r}")


P = lambda **kw: types.SimpleNamespace(**{"function_call": None, "function_response": None, "text": None,
                                          "thought_signature": None, "inline_data": None, "file_data": None, **kw})
C = lambda role, *parts: types.SimpleNamespace(role=role, parts=list(parts))
FC = lambda name: types.SimpleNamespace(name=name, args={"q": "x"})
FR = lambda name: types.SimpleNamespace(name=name, response={"content": "没找到"})
T = lambda text: P(text=text)

# 别家：补签名、空文字补空格
bare = P(function_call=FC("search"))
signed = P(function_call=FC("search"), thought_signature=b"real")
text = T("hi")
blank = T("")
user_fc = P(function_call=FC("search"))  # user 那一方不该有，有也不动
contents = [C("user", text), C("model", blank, bare, signed), C("user", P(function_response=FR("search")), user_fc)]
got = gemsig.fix(contents)
expect("别家：补了一个签名、一处空文字", (got["signed"], got["blank"], got["texted"]), (1, 1, 0))
expect("没签名的补上", bare.thought_signature, gemsig.SKIP_SIG)
expect("真签名不动", signed.thought_signature, b"real")
expect("空文字补成空格", blank.text, " ")
expect("文字不动", (text.text, text.thought_signature), ("hi", None))
expect("user 不动", user_fc.thought_signature, None)
expect("老接口 fill 还在", gemsig.fill([C("model", P(function_call=FC("a")))]), 1)

# daitu：没签名的调用和它的结果都改成文字，有真签名的那一对照旧
mk = lambda s: T(s)
c_model = C("model", P(function_call=FC("search")), P(function_call=FC("diary"), thought_signature=b"real"))
c_user = C("user", P(function_response=FR("search")), P(function_response=FR("diary")))
got = gemsig.fix([C("user", T("在吗")), c_model, c_user], as_text=True, make_text=mk)
expect("daitu：改成文字 1 个", got["texted"], 1)
expect("daitu：调用变成文字", c_model.parts[0].text.startswith("[调用了工具 search"), True)
expect("daitu：真签名的调用照旧", c_model.parts[1].function_call.name, "diary")
expect("daitu：对应的结果变成文字", c_user.parts[0].text.startswith("[工具 search 的结果]"), True)
expect("daitu：真签名那次的结果照旧", c_user.parts[1].function_response.name, "diary")
expect("看 api_base 认 daitu", gemsig._as_text_for(types.SimpleNamespace(api_base="https://api.daitu.cc")), True)
expect("别家不改成文字", gemsig._as_text_for(types.SimpleNamespace(api_base="https://www.bb-api.com")), False)


class Prov:
    api_base = "https://www.bb-api.com"

    async def _prepare_conversation(self, payloads):
        return [C("model", P(function_call=FC("x")))]


expect("装上", gemsig.install(cls=Prov), True)
expect("再装一次不套两层", gemsig.install(cls=Prov), True)
out = asyncio.run(Prov()._prepare_conversation({}))
expect("装上后补签名", out[0].parts[0].thought_signature, gemsig.SKIP_SIG)
gemsig.uninstall(cls=Prov)
out = asyncio.run(Prov()._prepare_conversation({}))
expect("卸下后照原样", out[0].parts[0].thought_signature, None)
expect("卸干净", gemsig.ORIG in Prov.__dict__, False)

print("FAILED:", ", ".join(fails) if fails else "none")
sys.exit(1 if fails else 0)
