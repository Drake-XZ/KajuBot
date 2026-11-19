"""Offline tests for tools/persona.py — works on a temp copy of data_v4.db, never touches the real one.

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_persona.py
Exit code 0 = all passed.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
import persona  # noqa: E402

failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


tmp = Path(tempfile.mkdtemp())
shutil.copy(persona.DB, tmp / "data_v4.db")
persona.DB = tmp / "data_v4.db"
persona.BACKUP = tmp / "backup"
persona.MASTER = tmp / "master"
if persona.FACTS.exists():
    shutil.copy(persona.FACTS, tmp / "self_facts.json")
persona.FACTS = tmp / "self_facts.json"
persona.online = lambda: False

orig = persona.cmd_get()
expect("get ok", orig["ok"], True)
expect("get offline", orig["online"], False)
p0 = orig["persona"]
expect("prompt non-empty", bool(p0["system_prompt"].strip()), True)
expect("dialogs even", len(p0["begin_dialogs"]) % 2, 0)
expect("offline tool list has plugin tools", "save_meme" in [t["name"] for t in orig["tools"]], True)

# --- validation
for label, bad in [
    ("empty prompt", {"system_prompt": "  \n"}),
    ("odd dialogs", {"begin_dialogs": ["a", "b", "c"]}),
    ("blank dialog cell", {"begin_dialogs": ["a", " "]}),
    ("nothing", {"skills": []}),
]:
    try:
        persona.validate(bad)
        failures.append(label)
        print(f"FAIL {label}: no error")
    except persona.PersonaError:
        pass

# --- unchanged save is a no-op (no backup)
r = persona.cmd_save({"system_prompt": p0["system_prompt"], "tools": p0["tools"],
                      "custom_error_message": p0["custom_error_message"]})
expect("noop changed", r["changed"], [])
expect("noop no backup", persona.cmd_history()["items"], [])
expect("noop still makes the master", persona.master_read()["system_prompt"], p0["system_prompt"])

# --- real save: CRLF normalised, tools sorted, backup holds the old version, copy file written
new_prompt = p0["system_prompt"] + "\r\n7. 测试新加的一条"
r = persona.cmd_save({
    "system_prompt": new_prompt,
    "begin_dialogs": ["你好", "兄长大人好！\r\n今天也要加油"],
    "tools": ["save_meme", "post_qzone", "save_meme"],
    "custom_error_message": "  ",
})
expect("save ok", r["ok"], True)
expect("save changed", sorted(r["changed"]), sorted(["system_prompt", "begin_dialogs", "tools", "custom_error_message"]))
now = persona.db_read()
expect("prompt saved with LF", now["system_prompt"], p0["system_prompt"] + "\n7. 测试新加的一条")
expect("dialogs saved", now["begin_dialogs"], ["你好", "兄长大人好！\n今天也要加油"])
expect("tools saved sorted+dedup", now["tools"], ["post_qzone", "save_meme"])
expect("blank error msg -> NULL", now["custom_error_message"], None)
expect("master text", (persona.MASTER / "persona.txt").read_text(encoding="utf-8"), now["system_prompt"])
expect("master json", {k: persona.master_read()[k] for k in ("system_prompt", "begin_dialogs", "tools")},
       {k: now[k] for k in ("system_prompt", "begin_dialogs", "tools")})
hist = persona.cmd_history()["items"]
expect("one backup", len(hist), 1)
old = persona.cmd_show(hist[0]["file"])["persona"]
expect("backup = old prompt", old["system_prompt"], p0["system_prompt"])
expect("backup = old dialogs", old["begin_dialogs"], p0["begin_dialogs"])
expect("backup = old tools", old["tools"], p0["tools"])

# --- tools back to "all" (null), and restoring the backup brings everything back
r = persona.cmd_save({**{k: old[k] for k in persona.FIELDS}})
now = persona.db_read()
expect("restore prompt", now["system_prompt"], p0["system_prompt"])
expect("restore tools null", now["tools"], p0["tools"])
expect("restore dialogs", now["begin_dialogs"], p0["begin_dialogs"])
expect("restore error msg", now["custom_error_message"], p0["custom_error_message"] or None)
expect("two backups", len(persona.cmd_history()["items"]), 2)

# --- 关于自己：写进 kaju_life 的文件（不碰数据库），空白收一收，备份里有旧清单
facts0 = persona.cmd_get()["persona"]["self_facts"]
expect("facts loaded", len(facts0) > 0, True)
db_before = persona.db_read()["updated_at"]
new_facts = [{"fact": "  佳树喜欢\n测试 ", "kind": " 喜好 "}, *facts0[1:], {"fact": "佳树新加的一条", "kind": ""}]
r = persona.cmd_save({"self_facts": new_facts})
expect("facts changed", r["changed"], ["self_facts"])
on_disk = json.loads(persona.FACTS.read_text(encoding="utf-8"))
expect("facts cleaned", on_disk[0], {"fact": "佳树喜欢 测试", "kind": "喜好"})
expect("facts count", len(on_disk), len(facts0) + 1)
expect("facts-only save leaves db alone", persona.db_read()["updated_at"], db_before)
expect("returned facts", r["persona"]["self_facts"], on_disk)
hist = persona.cmd_history()["items"]
expect("facts backup count", hist[0]["facts"], len(facts0))
expect("facts backup content", persona.cmd_show(hist[0]["file"])["persona"]["self_facts"], facts0)
r = persona.cmd_save({"self_facts": facts0})
expect("facts restored", json.loads(persona.FACTS.read_text(encoding="utf-8")), facts0)
for label, bad in [("facts not list", {"self_facts": "x"}),
                   ("facts duplicate", {"self_facts": [{"fact": "一样"}, {"fact": " 一样"}]})]:
    try:
        persona.validate(bad)
        failures.append(label)
        print(f"FAIL {label}: no error")
    except persona.PersonaError:
        pass
expect("old backups have no facts", persona._normalize({"system_prompt": "x"})["self_facts"], None)

# --- 正本 → AstrBot（sync）、AstrBot → 正本（export）
m = json.loads((persona.MASTER / "persona.json").read_text(encoding="utf-8"))
m["custom_error_message"] = "正本里改的"
(persona.MASTER / "persona.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
r = persona.cmd_sync()
expect("sync changed", (r["ok"], r["changed"]), (True, ["custom_error_message"]))
expect("sync wrote db", persona.db_read()["custom_error_message"], "正本里改的")
persona.db_write({"custom_error_message": "面板里改的"})
r = persona.cmd_export()
expect("export", (r["ok"], persona.master_read()["custom_error_message"]), (True, "面板里改的"))
expect("export keeps prompt", (persona.MASTER / "persona.txt").read_text(encoding="utf-8"), persona.db_read()["system_prompt"])
persona.cmd_save({"custom_error_message": p0["custom_error_message"]})
shutil.rmtree(persona.MASTER)
try:
    persona.cmd_sync()
    failures.append("sync without master")
except persona.PersonaError:
    pass

# --- show refuses paths outside the backup folder
try:
    persona.cmd_show("..\\..\\data_v4.db")
    failures.append("show traversal")
except persona.PersonaError:
    pass

# --- CLI round trip through files
out = tmp / "out.json"
inp = tmp / "in.json"
inp.write_text(json.dumps({"custom_error_message": "唔…再说一遍？"}, ensure_ascii=False), encoding="utf-8-sig")
code = persona.main(["save", "--in", str(inp), "--out", str(out)])
res = json.loads(out.read_text(encoding="utf-8"))
expect("cli exit", code, 0)
expect("cli changed", res["changed"], ["custom_error_message"])
code = persona.main(["save", "--in", str(tmp / "missing.json"), "--out", str(out)])
expect("cli error exit", code, 1)
expect("cli error json", json.loads(out.read_text(encoding="utf-8"))["ok"], False)

shutil.rmtree(tmp, ignore_errors=True)
print("persona tests:", "ALL PASSED" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
