r"""第 9 轮人格对子小试：佳树原句 / 平淡版 / 演过头版 并排看的页面 → data\rounds_v4\r9\pilot.html
用法：python -I -X utf8 scripts\page_r9_pilot.py
"""
import difflib
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VT = os.path.dirname(HERE)
sys.stdout.reconfigure(encoding="utf-8")
R7K = os.path.join(VT, "data", "rounds_v4", "r7k")
R9 = os.path.join(VT, "data", "rounds_v4", "r9")

# 我（Claude）逐条看过后的备注；“几乎一样”是程序算的
NOTES = {
    "al-n0": ("bad", "过头版加了原句没有的事（十四岁、等到十八岁）"),
    "novel-n390-1": ("bad", "过头版把“他（橘同学）”改成“聪兄长大人”，人换了"),
    "novel-n220-0": ("bad", "过头版把小权叫成“兄长大人小权”，人搞混了"),
    "al-n165": ("bad", "过头版把“小权去园艺社”改成“兄长大人去园艺社”，人换了"),
    "novel-n555-1": ("bad", "过头版把小权的修枝剪说成兄长大人的"),
    "gold-ab6-0": ("warn", "平淡版把两行并成一行了"),
    "g6-r4-r2-replay2-rc2-16": ("warn", "平淡版还留着“呢”"),
    "gold-ab10-1": ("warn", "平淡版还留着“嘛”"),
    "gold-c42-1": ("warn", "平淡版还留着“嘿嘿”"),
    "novel-n430-0": ("warn", "平淡版还留着“来，啊～”"),
}


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def lines(s):
    return "".join(f"<span class=ln>{html.escape(x.strip())}</span>" for x in s.split(" / ") if x.strip())


def my_row(m, key, cls, name):
    if not m or not m.get(key):
        return ""
    return f'<div class="row c"><span class="tag {cls}">{name}<small>Claude</small></span><div class=txt>{lines(m[key])}</div></div>'


def main():
    rows = {(r["id"], r["src"]): r for r in jl(os.path.join(R7K, "k_data", "stage2.jsonl"))}
    ps = [d for d in jl(os.path.join(R9, "pairs.jsonl")) if d.get("flat")]
    mine = {d["id"]: d for d in jl(os.path.join(R9, "pairs_claude.jsonl"))} if os.path.exists(os.path.join(R9, "pairs_claude.jsonl")) else {}
    my_ratio = sorted(len(m["flat"]) / max(1, len(rows[(d["id"], d["src"])]["target"])) for d in ps if (m := mine.get(d["id"])) and m.get("flat"))
    g_ratio = sorted(len(d["flat"]) / max(1, len(rows[(d["id"], d["src"])]["target"])) for d in ps)
    n_skip = sum(1 for m in mine.values() if m.get("skip"))
    src_name = {"novel": "原作", "curated": "兄长认可（新）", "curated_old": "兄长认可（旧）"}
    cards, n_same, n_bad, n_warn = [], 0, 0, 0
    for i, d in enumerate(ps, 1):
        r = rows[(d["id"], d["src"])]
        flags = []
        ratio = difflib.SequenceMatcher(None, r["target"], d["flat"]).ratio()
        if ratio >= 0.85:
            flags.append(("warn", f"平淡版和原句几乎一样（相似 {ratio:.2f}），这对没用，全量时去掉"))
            n_same += 1
        if d["id"] in NOTES:
            flags.append(NOTES[d["id"]])
        n_bad += any(k == "bad" for k, _ in flags)
        n_warn += any(k == "warn" for k, _ in flags) and not any(k == "bad" for k, _ in flags)
        kind = "bad" if any(k == "bad" for k, _ in flags) else ("warn" if flags else "ok")
        ctx = " ／ ".join(html.escape(x) for x in (r.get("ctx") or [])[-2:])
        fl = "".join(f"<li class={k}>{html.escape(t)}</li>" for k, t in flags)
        cards.append(f"""<article class="pair {kind}" data-kind="{kind}">
<header><span class=no>{i:02d}</span><span class=src>{src_name.get(d['src'], d['src'])}</span></header>
<p class=ctx>{ctx}</p>
<div class=row><span class="tag k">佳树</span><div class=txt>{lines(r['target'])}</div></div>
<div class="row g"><span class="tag f">平淡<small>Gemini</small></span><div class=txt>{lines(d['flat'])}</div></div>
{my_row(mine.get(d['id']), 'flat', 'f', '平淡')}
<div class="row g"><span class="tag o">过头<small>Gemini</small></span><div class=txt>{lines(d['over'])}</div></div>
{my_row(mine.get(d['id']), 'over', 'o', '过头')}
{f'<ul class=flags>{fl}</ul>' if fl else ''}
{f'<p class=skip>Claude 跳过：{html.escape(mine[d["id"]]["skip"])}</p>' if mine.get(d['id'], {}).get('skip') else ''}
</article>""")
    page = f"""<title>人格对子小试</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
/* 一列卡片，每对三行（佳树 / 平淡 / 过头）上下对齐，方便一眼比 */
:root {{
  --bg: #f6f5f8; --card: #ffffff; --fg: #24212b; --mute: #6b6676; --line: #e2dfe8;
  --k: #b0456a; --f: #5d6b7a; --o: #b9772a; --bad: #c23b3b; --warn: #a2780f; --okc: #2f7a4f;
  --sans: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #17151b; --card: #211e27; --fg: #ece9f1; --mute: #a49fae; --line: #34303c;
  --k: #e588a8; --f: #9fb0c2; --o: #e3a861; --bad: #f07b7b; --warn: #e2c05a; --okc: #6fc496; color-scheme: dark }} }}
:root[data-theme="dark"] {{
  --bg: #17151b; --card: #211e27; --fg: #ece9f1; --mute: #a49fae; --line: #34303c;
  --k: #e588a8; --f: #9fb0c2; --o: #e3a861; --bad: #f07b7b; --warn: #e2c05a; --okc: #6fc496; color-scheme: dark }}
body {{ background: var(--bg); color: var(--fg); font-family: var(--sans); line-height: 1.65;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 28px 60px; }}
main {{ max-width: 860px; margin: 0 auto; display: grid; gap: 14px; }}
h1 {{ font-size: 1.45rem; margin: 0; text-wrap: balance; }}
.lead {{ color: var(--mute); margin: 0; }}
.sum {{ display: flex; flex-wrap: wrap; gap: 8px 18px; font-size: .92rem; }}
.sum b {{ font-variant-numeric: tabular-nums; }}
.how {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px 16px; font-size: .92rem; }}
.how p {{ margin: 4px 0; }}
.bar {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.bar button {{ font: inherit; font-size: .88rem; border: 1px solid var(--line); background: var(--card); color: var(--fg);
  border-radius: 999px; padding: 4px 12px; cursor: pointer; }}
.bar button[aria-pressed="true"] {{ border-color: var(--fg); font-weight: 600; }}
.bar button:focus-visible {{ outline: 2px solid var(--k); outline-offset: 2px; }}
.pair {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px 16px; display: grid; gap: 6px; min-width: 0; }}
.pair.bad {{ border-left: 3px solid var(--bad); }}
.pair.warn {{ border-left: 3px solid var(--warn); }}
.pair header {{ display: flex; gap: 10px; align-items: baseline; font-size: .8rem; color: var(--mute); }}
.no {{ font-variant-numeric: tabular-nums; font-weight: 600; }}
.ctx {{ margin: 0 0 4px; font-size: .84rem; color: var(--mute); }}
.row {{ display: grid; grid-template-columns: 4.6em 1fr; gap: 10px; align-items: start; }}
.tag {{ font-size: .78rem; font-weight: 600; letter-spacing: .05em; padding-top: 2px; display: grid; line-height: 1.3; }}
.tag small {{ font-weight: 400; font-size: .7rem; color: var(--mute); letter-spacing: 0; }}
.row.c .txt {{ font-weight: 500; }}
.row.g .txt {{ color: var(--mute); }}
.skip {{ margin: 4px 0 0; font-size: .85rem; color: var(--mute); }}
.tag.k {{ color: var(--k); }} .tag.f {{ color: var(--f); }} .tag.o {{ color: var(--o); }}
.txt {{ min-width: 0; display: grid; gap: 2px; }}
.ln {{ display: block; }}
.flags {{ margin: 4px 0 0; padding-left: 1.1em; font-size: .85rem; }}
.flags .bad {{ color: var(--bad); }} .flags .warn {{ color: var(--warn); }}
</style>
<main>
<h1>人格对子小试</h1>
<p class=lead>第 9 轮的训练材料样子：同一个意思，佳树真说的那句当“好的”，平淡版和过头版当“差的”。训练只学两者之间的差别。
每对下面 Gemini 写的和 Claude 重写的上下放着比；红黄标记是 Gemini 那版的毛病。</p>
<div class=sum><span>共 <b>{len(ps)}</b> 对</span><span>花了约 <b>0.15</b> 元（全量约 1400 对 ≈ 7 元）</span>
<span>Gemini 有问题 <b>{n_bad}</b>、小毛病 <b>{n_warn}</b>、平淡版和原句几乎一样 <b>{n_same}</b></span>
<span>平淡版长短 / 原句（中位）：Gemini <b>{g_ratio[len(g_ratio) // 2]:.2f}</b>、Claude <b>{(my_ratio[len(my_ratio) // 2] if my_ratio else 0):.2f}</b></span>
<span>Claude 写了 <b>{len(mine) - n_skip}</b> 对、跳过 <b>{n_skip}</b> 对</span></div>
<div class=how>
<p><b style="color:var(--k)">佳树</b>：原作原句或兄长认可过的话（这是训练要学的）。</p>
<p><b style="color:var(--f)">平淡</b>：同样的意思和事实，普通人的说法——要看的是“只少了人格、没少意思”。</p>
<p><b style="color:var(--o)">过头</b>：同样的意思，但满屏“佳树”“兄长大人”、撒娇堆太满，用来治 r8 反复自称的毛病。</p>
</div>
<div class=bar role=group aria-label="筛选">
<button type=button id=f-all data-f=all aria-pressed=true>全部</button>
<button type=button id=f-flag data-f=flag aria-pressed=false>只看有标记的</button>
<button type=button id=f-ok data-f=ok aria-pressed=false>只看没问题的</button>
</div>
{''.join(cards)}
</main>
<script>
document.querySelectorAll('.bar button').forEach(b => b.addEventListener('click', () => {{
  document.querySelectorAll('.bar button').forEach(x => x.setAttribute('aria-pressed', x === b));
  const f = b.dataset.f;
  document.querySelectorAll('.pair').forEach(p => {{
    const k = p.dataset.kind;
    p.hidden = f === 'flag' ? k === 'ok' : f === 'ok' ? k !== 'ok' : false;
  }});
}}));
</script>
"""
    out = os.path.join(R9, "pilot.html")
    open(out, "w", encoding="utf-8").write(page)
    print(out, len(ps), "bad", n_bad, "warn", n_warn, "same", n_same)


if __name__ == "__main__":
    main()
