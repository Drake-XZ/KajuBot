"""Tests for tools/memes.py.

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_memes.py          offline: fake plugin server on a temp dir
    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_memes.py --live   real plugin (bot must be running):
        works only inside temporary categories zz-test-* of 佳树表情包 and removes them + its trash entries afterwards
Exit code 0 = all passed.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
LIVE = "--live" in sys.argv
HERE = Path(__file__).resolve().parent
tmp = Path(tempfile.mkdtemp())

if not LIVE:
    os.environ["MEMES_TEST_DIR"] = str(tmp)
    root = tmp / "meme_manager"
    for pack in ("kaju_memes", "other"):
        (root / "packs" / pack / "memes" / "happy").mkdir(parents=True)
        (root / "packs" / pack / "memes_data.json").write_text(json.dumps({"happy": "开心"}, ensure_ascii=False), encoding="utf-8")
    (root / "registry.json").write_text(json.dumps({"installed_packs": [{"id": "kaju_memes", "name": "佳树表情包"}, {"id": "other", "name": "别的"}]}), encoding="utf-8")
    (root / "selection_rules.json").write_text(json.dumps({"rules": [{"scope": "default", "pack_ids": ["kaju_memes", "other"]}]}), encoding="utf-8")

    class Fake(BaseHTTPRequestHandler):
        """Just enough of AstrBot login + meme_manager routes, doing the same file operations as the plugin."""

        def log_message(self, *a):
            pass

        def reply(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.reply(200, {})

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            path = self.path
            if path == "/api/auth/login":
                return self.reply(200, {"status": "ok", "data": {"token": "t"}})
            assert self.headers.get("Authorization") == "Bearer t"
            route = path.removeprefix("/api/plug/meme_manager/")
            if route.startswith("emoji/add/"):
                from urllib.parse import unquote
                _, _, pack, cat = route.split("/")
                pack, cat = unquote(pack), unquote(cat)
                boundary = self.headers["Content-Type"].split("boundary=")[1].encode()
                part = raw.split(b"--" + boundary)[1]
                head, _, content = part.partition(b"\r\n\r\n")
                content = content[:-2]
                name = head.split(b'filename="')[1].split(b'"')[0].decode()
                d = root / "packs" / pack / "memes" / cat
                d.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256(content).hexdigest()
                for f in d.iterdir():
                    if hashlib.sha256(f.read_bytes()).hexdigest() == h:
                        return self.reply(409, {"code": "duplicate_emoji", "message": "dup"})
                target, n = d / name, 1
                while target.exists():
                    target = d / f"{Path(name).stem}_{n}{Path(name).suffix}"
                    n += 1
                target.write_bytes(content)
                return self.reply(201, {"filename": target.name})
            data = json.loads(raw)
            pack = data["managed_pack_id"]
            memes = root / "packs" / pack / "memes"
            mpath = root / "packs" / pack / "memes_data.json"
            mapping = json.loads(mpath.read_text(encoding="utf-8"))
            if route == "emoji/batch_copy":
                copied = []
                for f in data["image_files"]:
                    src, dst = memes / data["source_category"] / f, memes / data["target_category"] / f
                    dst.parent.mkdir(exist_ok=True)
                    if src.is_file() and not dst.exists():
                        shutil.copy2(src, dst)
                        copied.append(f)
                return self.reply(200, {"copied_count": len(copied)})
            if route == "emoji/batch_delete":
                miss = 0
                for f in data["image_files"]:
                    p = memes / data["category"] / f
                    if p.is_file():
                        p.unlink()
                    else:
                        miss += 1
                return self.reply(200, {"missing_count": miss})
            if route == "category/restore":
                mapping[data["category"]] = data["description"]
                (memes / data["category"]).mkdir(exist_ok=True)
            elif route == "category/update_description":
                mapping[data["tag"]] = data["description"]
            elif route == "category/rename":
                mapping[data["new_name"]] = mapping.pop(data["old_name"])
                (memes / data["old_name"]).rename(memes / data["new_name"])
            elif route == "category/delete":
                mapping.pop(data["category"], None)
                shutil.rmtree(memes / data["category"], ignore_errors=True)
            else:
                return self.reply(404, {"message": "no route"})
            mpath.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
            return self.reply(200, {})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["MEMES_TEST_BASE"] = f"http://127.0.0.1:{server.server_address[1]}"

sys.path.insert(0, str(HERE.parent / "tools"))
import memes  # noqa: E402

failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


def ok(res, label):
    if not res["ok"]:
        failures.append(label)
        print(f"FAIL {label}: {res.get('error')}")
    return res


def png(seed: int) -> Path:
    """A tiny valid PNG whose bytes depend on seed (the real plugin accepts any image bytes)."""
    import struct
    import zlib

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + b"".join(bytes([(seed * 37 + x * 11 + y) % 256, (seed * 7) % 256, (x * y + seed) % 256]) for x in range(8)) for y in range(8))
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    p = tmp / f"测试图{seed}.png"
    p.write_bytes(data)
    return p


PACK = "kaju_memes"
A, B, C = ("zz-test-a", "zz-test-b", "zz-test-c") if LIVE else ("happy", "sad", "shy")
my_trash: set[str] = set()


def inv():
    r = ok(memes.cmd_inventory(), "inventory")
    my_trash.update(t["id"] for t in r["trash"] if t["pack"] == PACK and set(t["cats"]) <= {A, B, C, "zz-test-d"})
    return r


def items_in(cat):
    p = next(p for p in inv()["packs"] if p["id"] == PACK)
    return [i for i in p["items"] if cat in i["cats"]]


def run(*ops):
    return ok(memes.run_ops(list(ops)), f"ops {[o['op'] for o in ops]}")


try:
    if LIVE:
        run({"op": "cat_create", "pack": PACK, "cat": A, "desc": "测试分类A（马上删）"},
            {"op": "cat_create", "pack": PACK, "cat": B, "desc": "测试分类B（马上删）"})
    else:
        run({"op": "cat_create", "pack": PACK, "cat": B, "desc": "难过"})
    before = len(items_in(A))
    img1, img2 = png(1), png(2)
    r = run({"op": "add", "pack": PACK, "cat": A, "paths": [str(img1), str(img2), str(img1)]})
    expect("add: 2 new + 1 duplicate", (r["results"][-1]["added"], r["results"][-1]["dup"], r["results"][-1]["fail"]), (2, 1, []))
    got = items_in(A)
    expect("2 new items in A", len(got) - before, 2)
    sha1 = hashlib.sha256(img1.read_bytes()).hexdigest()
    sha2 = hashlib.sha256(img2.read_bytes()).hexdigest()
    it1 = next(i for i in got if i["sha"] == sha1)
    it2 = next(i for i in got if i["sha"] == sha2)

    # one picture, two categories → one item with two cats
    run({"op": "set_cats", "pack": PACK, "items": [it1], "add": [B], "remove": []})
    it1 = next(i for i in items_in(A) if i["sha"] == sha1)
    expect("it1 in A+B", sorted(it1["cats"]), sorted([A, B]))

    # removing one of two categories keeps the picture, nothing in trash
    trash0 = len(inv()["trash"])
    run({"op": "set_cats", "pack": PACK, "items": [it1], "add": [], "remove": [A]})
    it1 = next(i for p in inv()["packs"] if p["id"] == PACK for i in p["items"] if i["sha"] == sha1)
    expect("it1 only B", list(it1["cats"]), [B])
    expect("no trash for partial remove", len(inv()["trash"]), trash0)

    # move = keep only the target; brand-new target category gets created
    run({"op": "move", "pack": PACK, "items": [it1], "to": C})
    it1 = next(i for p in inv()["packs"] if p["id"] == PACK for i in p["items"] if i["sha"] == sha1)
    expect("it1 moved to C", list(it1["cats"]), [C])
    expect("C created in config", C in memes.pack_mapping(memes.ROOT / "packs" / PACK), True)

    # removing the last category = trash (recoverable)
    run({"op": "set_cats", "pack": PACK, "items": [it1], "add": [], "remove": [C]})
    t = [x for x in inv()["trash"] if x["sha"] == sha1]
    expect("it1 in trash", len(t), 1)
    expect("trash remembers cats", list(t[0]["cats"]), [C])
    expect("it1 gone from pack", [i for p in inv()["packs"] if p["id"] == PACK for i in p["items"] if i["sha"] == sha1], [])

    # delete it2 (in A) → trash; restore both → back where they were
    it2 = next(i for i in items_in(A) if i["sha"] == sha2)
    run({"op": "set_cats", "pack": PACK, "items": [it2], "add": [B], "remove": []})
    it2 = next(i for i in items_in(A) if i["sha"] == sha2)
    run({"op": "trash", "pack": PACK, "items": [it2]})
    tr = {x["sha"]: x for x in inv()["trash"] if x["sha"] in (sha1, sha2)}
    expect("it2 trash cats", sorted(tr[sha2]["cats"]), sorted([A, B]))
    expect("it2 gone", [i for i in items_in(A) + items_in(B) if i["sha"] == sha2], [])
    if LIVE:
        # restoring into a category that no longer exists must recreate it
        run({"op": "cat_delete", "pack": PACK, "cat": C})
    run({"op": "restore", "ids": [tr[sha1]["id"], tr[sha2]["id"]]})
    p = next(p for p in inv()["packs"] if p["id"] == PACK)
    back = {i["sha"]: sorted(i["cats"]) for i in p["items"] if i["sha"] in (sha1, sha2)}
    expect("restored", back, {sha1: [C], sha2: sorted([A, B])})
    expect("trash emptied", [x for x in inv()["trash"] if x["sha"] in (sha1, sha2)], [])

    # rename + description + deleting a category: only-there pictures go to trash, shared ones just lose it
    run({"op": "cat_rename", "pack": PACK, "cat": C, "new": "zz-test-d"},
        {"op": "cat_desc", "pack": PACK, "cat": "zz-test-d", "desc": "改过的描述"})
    mapping = memes.pack_mapping(memes.ROOT / "packs" / PACK)
    expect("renamed", ("zz-test-d" in mapping, C in mapping, mapping.get("zz-test-d")), (True, False, "改过的描述"))
    run({"op": "cat_delete", "pack": PACK, "cat": "zz-test-d"}, {"op": "cat_delete", "pack": PACK, "cat": B})
    tr = [x for x in inv()["trash"] if x["sha"] in (sha1, sha2)]
    expect("cat_delete trashed only-there pic", [(x["sha"], list(x["cats"])) for x in tr], [(sha1, ["zz-test-d"])])
    expect("shared pic kept in A", [list(i["cats"]) for i in items_in(A) if i["sha"] == sha2], [[A]])

    if not LIVE:
        # shared categories across packs: one usage = the matching dirs in every pack, changed together
        OTHER = "other"
        run({"op": "shared_create", "cat": "zz-sh", "desc": "共用说明"})
        expect("shared create lands in primary", "zz-sh" in memes.pack_mapping(memes.ROOT / "packs" / PACK), True)
        run({"op": "add", "pack": OTHER, "cat": "happy", "paths": [str(png(7))]})
        sha7 = hashlib.sha256(png(7).read_bytes()).hexdigest()
        o7 = next(i for p in inv()["packs"] if p["id"] == OTHER for i in p["items"] if i["sha"] == sha7)
        run({"op": "set_cats", "pack": OTHER, "items": [o7], "add": ["zz-sh"], "remove": [], "descs": {"zz-sh": "共用说明"}})
        expect("other pack got the category with the shared desc", memes.pack_mapping(memes.ROOT / "packs" / OTHER).get("zz-sh"), "共用说明")
        row = next(r for r in inv()["shared"] if r["key"] == "zz-sh")
        expect("shared members", sorted(row["members"]), sorted([PACK, OTHER]))
        run({"op": "shared_rename", "cat": "zz-sh", "new": "zz-sh2"}, {"op": "shared_desc", "cat": "zz-sh2", "desc": "新说明"})
        expect("renamed in both", [memes.pack_mapping(memes.ROOT / "packs" / p).get("zz-sh2") for p in (PACK, OTHER)], ["新说明", "新说明"])
        o7 = next(i for p in inv()["packs"] if p["id"] == OTHER for i in p["items"] if i["sha"] == sha7)
        expect("item shared keys", o7["shared"], ["happy", "zz-sh2"])
        run({"op": "shared_delete", "cat": "zz-sh2"})
        expect("deleted in both", [("zz-sh2" in memes.pack_mapping(memes.ROOT / "packs" / p)) for p in (PACK, OTHER)], [False, False])
        o7 = next(i for p in inv()["packs"] if p["id"] == OTHER for i in p["items"] if i["sha"] == sha7)
        expect("shared item kept its other category", list(o7["cats"]), ["happy"])
        run({"op": "cat_create", "pack": OTHER, "cat": "taken", "desc": "x"})
        bad = memes.run_ops([{"op": "shared_rename", "cat": "happy", "new": "taken"}])
        expect("rename onto a name one of its packs already has is refused", bad["ok"], False)
        expect("nothing renamed when refused", "happy" in memes.pack_mapping(memes.ROOT / "packs" / PACK), True)

    # errors are reported, later ops still run
    r = memes.run_ops([{"op": "cat_create", "pack": PACK, "cat": "a/b"}, {"op": "purge", "ids": [tr[0]["id"]]}])
    expect("bad name error", (r["ok"], r["results"][0]["ok"], r["results"][1]["ok"]), (False, False, True))
    expect("purged", [x for x in inv()["trash"] if x["sha"] == sha1], [])
finally:
    if LIVE:
        cleanup = []
        p = next(p for p in memes.cmd_inventory()["packs"] if p["id"] == PACK)
        for c in p["cats"]:
            if c["key"].startswith("zz-test"):
                cleanup.append({"op": "cat_delete", "pack": PACK, "cat": c["key"]})
        r = memes.run_ops(cleanup)
        leftover = [x["id"] for x in memes.read_trash() if x["pack"] == PACK and all(k.startswith("zz-test") for k in x["cats"])]
        memes.run_ops([{"op": "purge", "ids": leftover}])
        left = [c["key"] for c in next(p for p in memes.cmd_inventory()["packs"] if p["id"] == PACK)["cats"] if c["key"].startswith("zz-test")]
        print("live cleanup:", r["ok"], r.get("error"), "purged", len(leftover), "left cats", left)
    shutil.rmtree(tmp, ignore_errors=True)

print("memes tests" + (" (live)" if LIVE else "") + ":", "ALL PASSED" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
