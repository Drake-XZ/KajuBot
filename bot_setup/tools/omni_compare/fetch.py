r"""对比小测试第 1 步：把选好的视频重新下载下来（用她平时看视频的同一套下载代码），放到 media\。
    <venv>\Scripts\python.exe -I fetch.py
"""
import asyncio, importlib, json, os, shutil, sys, tempfile

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(SETUP, "tests", "stubs"))
sys.path.insert(0, os.path.join(SETUP, "plugins"))
sys.path.insert(0, SETUP)
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from astrbot.api.star import Context  # noqa: E402

describe = importlib.import_module("kaju_basics.describe")
douyin = importlib.import_module("kaju_platforms.douyin.douyin")
CORE = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
MEDIA = os.path.join(HERE, "media")
SAMPLES = json.load(open(os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else "samples.json"), encoding="utf-8"))


class _Keeper:
    """她那个常驻、登录着的浏览器已经开着：只告诉下载代码它在哪（不新开、不关它，用完只关标签页）。"""
    profile = "keeper"

    async def ensure(self, headless=True, url=""):
        k = json.load(open("D:/JiashuBot/kaju_data/accounts/douyin_login.json", encoding="utf-8")).get("keeper") or {}
        return f"http://127.0.0.1:{int(k['port'])}"


async def main():
    douyin.KEEPER = _Keeper()
    cfg = json.load(open(os.path.join(CORE, "data", "config", "astrbot_plugin_kaju_basics_config.json"),
                         encoding="utf-8-sig")).get("media", {})
    d = describe.Describer(Context({}), lambda: cfg)
    for s in SAMPLES:
        out = os.path.join(MEDIA, s["id"] + s["ext"])
        if os.path.exists(out) or not s.get("url"):
            continue
        try:
            if "bilibili" in s["url"]:
                info = await d.bili_info(s["url"])
                path = await d._bili_download(info)
            else:
                tmp = tempfile.mkdtemp()
                got = await douyin.fetch(s["url"], tmp, timeout=40, max_mb=80, profile="keeper")
                path = got.get("video")
                if not path:
                    raise RuntimeError(got.get("skip") or "没有视频")
            shutil.copy(path, out)
            print("ok ", s["id"], round(os.path.getsize(out) / 1e6, 1), "MB")
        except Exception as e:  # noqa: BLE001
            print("FAIL", s["id"], type(e).__name__, e)

asyncio.run(main())
