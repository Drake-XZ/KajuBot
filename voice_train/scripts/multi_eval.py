"""多选一盲评页：每题几个系统的回复打乱成 甲乙丙丁，选最好的一个（或差不多 / 都不好），可给每个候选打标记、写备注。

    python -I multi_eval.py page  IN.jsonl --out 新目录      → review.html + key.json（投完票再看 key）
    python -I multi_eval.py summary VOTES.json KEY.json      → 每个系统赢几题、被标了什么

IN.jsonl 每行：{"id", "kind", "to", "ctx": [...], "cands": {系统名: {"text": "最后发出去的话", ...}}}
页面不联网、不发任何消息；票先存在页面里（能用浏览器存储就顺便存一份），点"下载结果"存成 votes.json。
"""
import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

LABELS = "甲乙丙丁戊己"
FLAGS = ["不自然", "AI味", "编了没说过的事", "叫错人", "太长"]

PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>佳树回复盲选</title>
<style>
:root{--bg:#faf8f9;--fg:#2b2328;--muted:#7a6d74;--card:#fff;--line:#e6dde2;--me:#e8f3ff;--her:#fff0f5;--pick:#d6336c;--ok:#2f9e44}
@media (prefers-color-scheme:dark){:root{--bg:#1d191b;--fg:#eee6ea;--muted:#a99aa2;--card:#272124;--line:#3a3135;--me:#1f2d3d;--her:#3a2330;--pick:#f06595;--ok:#69db7c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,"Microsoft YaHei",sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:8px 0}.top{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);z-index:2;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.q{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:16px 0}
.meta{color:var(--muted);font-size:13px}.ctx{margin:8px 0 12px;padding-left:10px;border-left:3px solid var(--line)}
.ctx div{margin:2px 0}.cands{display:grid;gap:10px}
.c{border:2px solid var(--line);border-radius:10px;padding:10px;cursor:pointer}.c.sel{border-color:var(--pick)}
.c b{color:var(--pick);margin-right:6px}.bub{background:var(--her);border-radius:8px;padding:4px 8px;margin:4px 0;display:inline-block}
.flags{margin-top:6px;font-size:13px;color:var(--muted)}.flags label{margin-right:10px;white-space:nowrap;cursor:pointer}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.row button{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;padding:6px 12px;cursor:pointer}
.row button.sel{border-color:var(--pick);color:var(--pick);font-weight:bold}
textarea{width:100%;margin-top:8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);padding:6px;font:inherit;min-height:2.4em}
#dl{background:var(--pick);color:#fff;border:0;border-radius:8px;padding:8px 14px;cursor:pointer}.done{color:var(--ok)}
</style></head><body><main>
<h1>佳树回复盲选</h1>
<p class="meta">每题是同一段聊天里，几个版本最后会发出去的话（顺序打乱）。选你最喜欢的一个；都差不多或都不好也可以选。
觉得某一条有毛病可以勾标记，想怎么改就写在备注里。投完点右上角"下载结果"，或者直接告诉 Claude 投完了。</p>
<div class="top"><span id="prog"></span><button id="dl" type="button">下载结果</button><span id="status" class="meta"></span></div>
<div id="list"></div></main>
<script id="items" type="application/json">__ITEMS__</script>
<script>
const items=JSON.parse(document.getElementById('items').textContent);
const FLAGS=__FLAGS__;
const KEY='kaju-multi:'+items.map(i=>i.id).join(',').length+':'+items.length;
var votes={};try{votes=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(votes))}catch(e){}prog()}
function prog(){const n=items.filter(i=>votes[i.id]&&votes[i.id].choice).length;document.getElementById('prog').innerHTML='已投 <b class="'+(n==items.length?'done':'')+'">'+n+'</b> / '+items.length}
function el(t,c,txt){const e=document.createElement(t);if(c)e.className=c;if(txt!=null)e.textContent=txt;return e}
function v(id){return votes[id]||(votes[id]={choice:'',flags:{},note:''})}
const list=document.getElementById('list');
items.forEach((it,n)=>{
  const q=el('section','q');q.appendChild(el('div','meta',(n+1)+'. '+it.kind+(it.to?' · 回给 '+it.to:'')));
  const ctx=el('div','ctx');(it.ctx||[]).forEach(l=>ctx.appendChild(el('div','',l)));q.appendChild(ctx);
  const cs=el('div','cands');const boxes={};
  it.cands.forEach(c=>{
    const box=el('div','c');const head=el('div');head.appendChild(el('b','',c.label));box.appendChild(head);
    c.text.split('\n').filter(s=>s.trim()).forEach(s=>{box.appendChild(el('div','bub',s))});
    const fl=el('div','flags');FLAGS.forEach(f=>{const lb=el('label');const cb=document.createElement('input');cb.type='checkbox';
      cb.checked=!!(v(it.id).flags[c.label]||[]).includes(f);
      cb.onclick=e=>{e.stopPropagation();const a=v(it.id).flags[c.label]=v(it.id).flags[c.label]||[];
        if(cb.checked){if(!a.includes(f))a.push(f)}else{a.splice(a.indexOf(f),1)}save()};
      lb.onclick=e=>e.stopPropagation();lb.appendChild(cb);lb.appendChild(document.createTextNode(f));fl.appendChild(lb)});
    box.appendChild(fl);box.onclick=()=>{v(it.id).choice=c.label;render();save()};boxes[c.label]=box;cs.appendChild(box)});
  q.appendChild(cs);
  const row=el('div','row');const bs={};[['same','都差不多'],['neither','都不好']].forEach(([k,t])=>{const b=el('button','',t);b.type='button';
    b.onclick=()=>{v(it.id).choice=k;render();save()};bs[k]=b;row.appendChild(b)});q.appendChild(row);
  const ta=document.createElement('textarea');ta.placeholder='备注（可选）：哪里不好、你会怎么说';ta.value=v(it.id).note||'';
  ta.oninput=()=>{v(it.id).note=ta.value;save()};q.appendChild(ta);
  function render(){const ch=v(it.id).choice;Object.entries(boxes).forEach(([k,b])=>b.classList.toggle('sel',k===ch));
    Object.entries(bs).forEach(([k,b])=>b.classList.toggle('sel',k===ch))}
  render();list.appendChild(q)});
document.getElementById('dl').onclick=()=>{const a=el('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(votes,null,1)],{type:'application/json'}));
  a.download='votes.json';a.click();document.getElementById('status').textContent='已下载 votes.json'};
prog();
</script></body></html>"""


def page(inp: Path, out: Path, seed: int = 13):
    if out.exists():
        sys.exit(f"输出目录已存在：{out}")
    rows = [json.loads(l) for l in inp.read_text(encoding="utf-8").splitlines() if l.strip()]
    rng = random.Random(seed)
    items, key = [], {}
    for r in rows:
        systems = list(r["cands"])
        rng.shuffle(systems)
        key[r["id"]] = {LABELS[i]: s for i, s in enumerate(systems)}
        items.append({"id": r["id"], "kind": r.get("kind", ""), "to": r.get("to", ""), "ctx": r.get("ctx", []),
                      "cands": [{"label": LABELS[i], "text": r["cands"][s]["text"]} for i, s in enumerate(systems)]})
    out.mkdir(parents=True)
    data = json.dumps(items, ensure_ascii=False).replace("<", "\\u003c")
    (out / "review.html").write_text(PAGE.replace("__ITEMS__", data).replace("__FLAGS__", json.dumps(FLAGS, ensure_ascii=False)),
                                     encoding="utf-8")
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"盲选页：{out / 'review.html'}（{len(items)} 题）；key.json 投完再看")


def summary(votes_p: Path, key_p: Path):
    votes = json.loads(votes_p.read_text(encoding="utf-8"))
    key = json.loads(key_p.read_text(encoding="utf-8"))
    wins, flags = Counter(), {}
    for i, v in votes.items():
        if i not in key:
            continue
        ch = v.get("choice")
        wins[key[i].get(ch, ch) if ch else "没投"] += 1
        for lab, fs in (v.get("flags") or {}).items():
            flags.setdefault(key[i][lab], Counter()).update(fs)
    print(json.dumps({"赢": dict(wins.most_common()), "被标记": {k: dict(c) for k, c in flags.items()},
                      "投了": sum(1 for v in votes.values() if v.get("choice")), "共": len(key)}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("page")
    p1.add_argument("inp", type=Path)
    p1.add_argument("--out", type=Path, required=True)
    p2 = sub.add_parser("summary")
    p2.add_argument("votes", type=Path)
    p2.add_argument("key", type=Path)
    a = ap.parse_args()
    page(a.inp, a.out) if a.cmd == "page" else summary(a.votes, a.key)
