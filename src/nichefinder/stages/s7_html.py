"""Standalone HTML leaderboard: filterable, sortable table of all scored niches with expandable passports.

Output: reports/leaderboard.html - one self-contained file (inline CSS and JS, no external requests, system fonts).
Inputs: data/out/score_final.csv, supply_deep.csv, niches.yaml, reports/passports/<id>.md (s6_passports);
optional path_to_goal.csv (s6_ceiling), offsearch.csv (S8), reddit_voice*.csv and ru_reviews_verdict.csv (S10),
overrides (notes).
Blocks computed from data: top niches by score, top niches by path-to-goal grade, verdict counts.
"""
from __future__ import annotations

import argparse
import csv
import html as _html
import json
import re

from nichefinder import niches as nf_niches
from nichefinder.workspace import Workspace

SUMMARY = "Self-contained HTML leaderboard with expandable passports"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

SIDE = {"b2c": "B2C", "prosumer": "Prosumer", "b2b-smb": "B2B-SMB", "b2b-mid": "B2B-mid"}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rows(path, key):
    if not path.is_file():
        return {}
    return {r[key]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


# ---- minimal Markdown -> HTML (headings, tables, quotes, lists, bold/italic/code) ----

def _inline(s: str) -> str:
    s = _html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])_([^_]+)_(?![\w*])", r"<i>\1</i>", s)
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", s)


def md_to_html(md: str) -> str:
    out: list[str] = []
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|"):
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append(lines[i])
                i += 1
            cells = lambda r: [c.strip() for c in r.strip().strip("|").split("|")]  # noqa: E731
            head, body = cells(block[0]), block[2:]
            t = ["<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead><tbody>"]
            for r in body:
                t.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells(r)) + "</tr>")
            out.append("".join(t) + "</tbody></table>")
            continue
        if ln.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{_inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        m = re.match(r"(#{1,3}) (.*)", ln)
        if m:
            k = len(m.group(1))
            out.append(f"<h{k}>{_inline(m.group(2))}</h{k}>")
        elif ln.startswith("> "):
            out.append(f"<blockquote>{_inline(ln[2:])}</blockquote>")
        elif ln.strip():
            out.append(f"<p>{_inline(ln.rstrip())}</p>")
        i += 1
    return "\n".join(out)


def run(ws: Workspace, args: argparse.Namespace) -> None:
    niches = {x["id"]: x for x in nf_niches.load_niches(ws)}
    manual = nf_niches.overrides(ws)
    sc_path = ws.out("score_final.csv")
    if not sc_path.is_file():
        raise SystemExit(f"{sc_path} not found - run s6_score first")
    score = list(csv.DictReader(open(sc_path, encoding="utf-8")))
    supply = _rows(ws.out("supply_deep.csv"), "niche_id")
    off = _rows(ws.out("offsearch.csv"), "niche_id")
    ptg = _rows(ws.out("path_to_goal.csv"), "niche_id")
    rvoice = _rows(ws.out("reddit_voice.csv"), "niche_id")
    rllm = _rows(ws.out("reddit_voice_llm.csv"), "niche_id")
    qverd = _rows(ws.out("ru_reviews_verdict.csv"), "niche_id")
    try:
        from nichefinder.stages.s10_reddit_report import reddit_verdict
    except ImportError:
        reddit_verdict = None

    rows = []
    for s in score:
        nid = s["niche_id"]
        x, sp, m = niches[nid], supply[nid], manual.get(nid) or {}
        pp = ws.report(f"passports/{nid}.md")
        md = md_to_html(pp.read_text(encoding="utf-8")) if pp.is_file() else ""
        price = ""
        if num(sp["b2c_median_monthly"]):
            price = f"${num(sp['b2c_median_monthly']):.0f}/mo"
        elif num(sp["b2c_median_yearly"]):
            price = f"${num(sp['b2c_median_yearly']):.0f}/yr"
        elif num(sp["b2b_median_monthly"]):
            price = f"${num(sp['b2b_median_monthly']):.0f}/mo"
        pg = ptg.get(nid) or {}
        o = off.get(nid) or {}
        row = {
            "id": nid, "name": x.get("name", nid), "who": x.get("who", ""), "side": SIDE.get(x["side"], x["side"]), "geo": x["geo"], "tier": s["tier"],
            "verdict": s["verdict"], "score": num(s["score"]), "demand": num(s["demand_us"]), "demand2023": num(sp["demand_2023"]),
            "cpc": num(s["cpc"]), "kp": s["trend_kp"], "gt": s["trend_gt"], "src": s["supply_src"], "manual": "S5:manual" in s["flags"],
            "players": num(s["supply_players"]), "top1": num(s["supply_top1_share"]), "top1name": s["supply_top1"],
            "price": price, "gates": s["gates_failed"], "flags": s["flags"], "note": s.get("verdict_note") or m.get("verdict_note", ""), "md": md,
            "yt": o.get("yt_verdict", ""), "gp": num(o.get("gp_us_installs")),
            "rv": "", "rvt": "",
            "qv": (qverd.get(nid) or {}).get("verdict", ""), "qvt": (qverd.get(nid) or {}).get("reason", ""),
            "grade": pg.get("grade", ""), "poslow": pg.get("position_low", ""), "sharelow": num(pg.get("share_low")),
            "ticket": pg.get("ticket_tier", ""), "fit": num(pg.get("founder_fit")),
            "ptgt": (f"needs {int(float(pg['payers_low'])):,} payers at ${float(pg['price_month']):.0f}/mo = {float(pg['share_low']):.0%} of the niche ({pg['size_proxy']}); fit {pg['founder_fit']}/3" if pg.get("share_low") else ""),
        }
        rows.append(row)
        if reddit_verdict and nid in rvoice:   # S10 buyer voice: verdict by rule (s10_reddit_report.reddit_verdict)
            v, l = rvoice[nid], rllm.get(nid)
            row["rv"], why = reddit_verdict(v, l)
            row["rvt"] = f"{why}; {int(v['posts']):,} posts, {int(v['comments']):,} comments; brand voice: {v['brand_top3'] or '—'}"

    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("green", "yellow", "red")}
    n_a = sum(1 for r in rows if r["grade"] == "A")
    sides = sorted({r["side"] for r in rows})
    tiers = sorted({r["tier"] for r in rows})
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    page = (PAGE.replace("__DATA__", data).replace("__G__", str(counts["green"])).replace("__Y__", str(counts["yellow"]))
            .replace("__R__", str(counts["red"])).replace("__N__", str(len(rows))).replace("__A__", str(n_a))
            .replace("__SIDES__", json.dumps(sides)).replace("__TIERS__", json.dumps(tiers))
            .replace("__MIN__", str(ws.setting("verdict.green_min_score", 70))))
    dest = ws.report("leaderboard.html")
    dest.write_text(page, encoding="utf-8")
    print("->", dest, len(page) // 1024, "KB")


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Niche Finder leaderboard</title>
<style>
:root{--bg:#F5F6F2;--panel:#FFFFFF;--ink:#1A2320;--ink2:#56605C;--ink3:#8A938F;--line:#DDE2DC;--accent:#0E6B5F;--green:#1E7F5C;--green-bg:#E3F3EA;--yellow:#9A6A0B;--yellow-bg:#FBF0D3;--red:#A6392B;--red-bg:#F8E1DC;--hover:#EEF1EC;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--sans:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}
@media (prefers-color-scheme: dark){:root{--bg:#151A18;--panel:#1D2321;--ink:#E8ECE9;--ink2:#A9B2AD;--ink3:#737C78;--line:#2C3431;--accent:#6CC3B2;--green:#6CCB9B;--green-bg:#1B3328;--yellow:#E3B85A;--yellow-bg:#3A2F14;--red:#E8836F;--red-bg:#3D211C;--hover:#242B28}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.45;padding:28px 20px 60px}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:28px;font-weight:700;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--ink2);margin:0 0 18px;max-width:75ch}
.funnel{display:flex;flex-wrap:wrap;align-items:stretch;margin:0 0 22px;border:1px solid var(--line);border-radius:10px;background:var(--panel);overflow:hidden}
.funnel div{flex:1 1 140px;padding:10px 14px;border-right:1px solid var(--line)}
.funnel div:last-child{border-right:0}
.funnel b{display:block;font-family:var(--mono);font-size:20px;font-weight:600}
.funnel span{color:var(--ink2);font-size:13px}
.box{margin:0 0 22px;padding:14px 16px;background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px}
.box h2{margin:0 0 8px;font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--accent)}
.box ol{margin:0;padding-left:22px}
.box li{margin:4px 0}
.box li a{color:var(--ink);font-weight:600;text-decoration:none;border-bottom:1px dotted var(--ink3)}
.box li span{color:var(--ink2)}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 12px}
.chip{border:1px solid var(--line);background:var(--panel);color:var(--ink2);border-radius:999px;padding:5px 12px;font:inherit;font-size:14px;cursor:pointer}
.chip[aria-pressed="true"]{border-color:var(--accent);color:var(--accent);font-weight:600}
.chip .n{font-family:var(--mono);font-size:12px;margin-left:4px}
.filters input{margin-left:auto;font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);min-width:200px}
.tblwrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--panel)}
table{border-collapse:collapse;width:100%;min-width:960px}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink2);font-weight:600;cursor:pointer;white-space:nowrap;position:sticky;top:0;background:var(--panel);z-index:1}
th[data-dir]::after{content:" \2193";color:var(--accent)}
th[data-dir="asc"]::after{content:" \2191"}
td.num{font-family:var(--mono);font-size:13px;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
th.num{text-align:right}
tr.row{cursor:pointer}
tr.row:hover td,tr.row[aria-expanded="true"] td{background:var(--hover)}
.name{font-weight:600}
.id{display:block;color:var(--ink3);font-family:var(--mono);font-size:11px}
.v{display:inline-block;padding:2px 8px;border-radius:6px;font-size:12px;font-weight:600;white-space:nowrap}
.v.green{background:var(--green-bg);color:var(--green)}.v.yellow{background:var(--yellow-bg);color:var(--yellow)}.v.red{background:var(--red-bg);color:var(--red)}
.tag{display:inline-block;font-family:var(--mono);font-size:11px;color:var(--ink2);border:1px solid var(--line);border-radius:4px;padding:0 5px;margin:1px 2px 1px 0}
tr.detail td{background:var(--bg);padding:0}
.pass{padding:16px 22px 22px;max-width:100ch;font-size:14.5px}
.pass h1{font-size:20px;margin:0 0 6px}
.pass h2{font-size:15px;margin:18px 0 6px;color:var(--accent);text-transform:uppercase;letter-spacing:.05em}
.pass table{min-width:0;font-size:13px;margin:8px 0}
.pass th,.pass td{padding:5px 8px;position:static;cursor:default;border:1px solid var(--line)}
.pass blockquote{margin:10px 0;padding:8px 14px;border-left:3px solid var(--accent);background:var(--panel);border-radius:0 6px 6px 0}
.pass code{font-family:var(--mono);font-size:12.5px;background:var(--hover);padding:0 4px;border-radius:3px}
.foot{color:var(--ink3);font-size:13px;margin-top:22px;max-width:85ch}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (max-width:640px){body{padding-inline:16px}.filters input{margin-left:0;width:100%}}
</style></head><body>
<div class="wrap">
<h1>Niche Finder leaderboard</h1>
<p class="sub">Every scored niche with its verdict, score components, supply, pricing and path-to-goal grade. Click a row to open the niche passport.</p>
<div class="funnel">
<div><b>__N__</b><span>scored niches</span></div>
<div><b>__G__ · __Y__ · __R__</b><span>green · yellow · red</span></div>
<div><b>__A__</b><span>path-to-goal grade A</span></div>
</div>
<div class="box" id="boxScore"><h2>Top by score (not red)</h2><ol id="topScore"></ol></div>
<div class="box" id="boxPtg" style="border-left-color:var(--yellow)"><h2 style="color:var(--yellow)">Top by path-to-goal grade (A and B)</h2><ol id="topPtg"></ol></div>
<div class="filters" id="filters"></div>
<div class="tblwrap"><table id="t">
<thead><tr>
<th data-k="score" class="num">Score</th><th data-k="name">Niche</th><th data-k="verdict">Verdict</th><th data-k="grade">Path</th><th data-k="sharelow" class="num">Share for goal</th><th data-k="ticket">Ticket</th><th data-k="fit" class="num">Fit</th><th data-k="side">Type</th>
<th data-k="demand" class="num">Demand/mo</th><th data-k="demand2023" class="num">2023</th><th data-k="cpc" class="num">CPC</th>
<th data-k="kp">KP</th><th data-k="gt">Trends</th><th data-k="yt">YouTube</th><th data-k="rv">Reddit</th><th data-k="qv">RU reviews</th><th data-k="players" class="num">Players</th><th data-k="top1" class="num">Top-1</th><th data-k="price">Price</th><th data-k="gp" class="num">Android</th><th>Gates / flags</th>
</tr></thead><tbody id="tb"></tbody></table></div>
<p class="foot">Score = demand 30 + growth 20 + fragmentation 25 + deals 15 + switching 10, times a trend adjustment; percentiles are taken within a segment (B2C + prosumer / B2B). Verdict: red when a gate fails (G3 platform risk, G5 feasibility, S5 supply concentration); otherwise green at score &ge; __MIN__, else yellow; a manual override in config/overrides.yaml wins. Path: A/B/B-/C grade from the share of the niche's payers needed for your goal, the ticket tier and founder fit. Players: apps with &ge; 1k ratings (App Store) or products with &ge; 100 reviews (Capterra / Shopify), excluding horizontal tools. Top-1: leader's share of ratings/reviews. 2023: clean base-year demand. YouTube: interest trend on YouTube search. Android: total installs of relevant Google Play apps. Reddit: buyer-voice verdict (S10). RU reviews: verdict from Russian App Store, Google Play and Startpack reviews of the niche's leading products (S10).</p>
</div>
<script>
const DATA=__DATA__;
const SIDES=__SIDES__, TIERS=__TIERS__;
const V={green:'🟢 green',yellow:'🟡 yellow',red:'🔴 red'};
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=(v,d=0)=>v==null?'—':v.toLocaleString('en-US',{maximumFractionDigits:d});
const pct=v=>v==null?'—':Math.round(v*100)+'%';
const GRADES=['A','B','B-','C',''];
const state={verdict:new Set(['green','yellow','red']),side:new Set(SIDES),tier:new Set(TIERS),grade:new Set(GRADES),q:'',k:'score',dir:'desc',open:null};
const GR={A:'var(--green)',B:'var(--accent)','B-':'var(--yellow)',C:'var(--red)'};
function chips(){
  const mk=(f,v,label,on=true)=>`<button class="chip" data-f="${f}" data-v="${esc(v)}" aria-pressed="${on}">${label}</button>`;
  const cnt=v=>DATA.filter(r=>r.verdict===v).length;
  let h=['green','yellow','red'].map(v=>mk('verdict',v,V[v]+`<span class="n">${cnt(v)}</span>`)).join('');
  h+='<span style="width:8px"></span>'+SIDES.map(s=>mk('side',s,esc(s))).join('');
  h+='<span style="width:8px"></span>'+TIERS.map(t=>mk('tier',t,'tier '+esc(t))).join('');
  if(DATA.some(r=>r.grade)){h+='<span style="width:8px"></span>'+['A','B','B-','C'].map(g=>mk('grade',g,'path '+g)).join('')+mk('grade','','no grade');}
  h+='<input id="q" type="search" placeholder="search by name / id" aria-label="Search">';
  document.getElementById('filters').innerHTML=h;
}
function lists(){
  const li=r=>`<li><a href="#" data-open="${esc(r.id)}">${esc(r.name)}</a> <span>— score ${fmt(r.score)}, ${V[r.verdict]}${r.grade&&r.grade!=='—'?', path '+esc(r.grade):''}${r.note?'; '+esc(r.note):''}</span></li>`;
  document.getElementById('topScore').innerHTML=DATA.filter(r=>r.verdict!=='red').sort((a,b)=>b.score-a.score).slice(0,5).map(li).join('');
  const g=DATA.filter(r=>r.grade==='A'||r.grade==='B').sort((a,b)=>a.grade.localeCompare(b.grade)||b.score-a.score).slice(0,8);
  if(!g.length)document.getElementById('boxPtg').style.display='none';
  document.getElementById('topPtg').innerHTML=g.map(r=>`<li><b style="color:${GR[r.grade]}">${esc(r.grade)}</b> <a href="#" data-open="${esc(r.id)}">${esc(r.name)}</a> <span>— ${esc(r.poslow)}, ticket ${esc(r.ticket||'—')}, fit ${r.fit==null?'—':r.fit}/3; ${esc(r.ptgt)}</span></li>`).join('');
}
function render(){
  const tb=document.getElementById('tb');
  let rows=DATA.filter(r=>state.verdict.has(r.verdict)&&state.side.has(r.side)&&state.tier.has(r.tier)&&state.grade.has(r.grade==='—'?'':r.grade)&&(!state.q||(r.name+' '+r.id+' '+r.who).toLowerCase().includes(state.q)));
  const k=state.k, sgn=state.dir==='desc'?-1:1;
  rows.sort((a,b)=>{const x=a[k],y=b[k];if(x==null&&y==null)return 0;if(x==null)return 1;if(y==null)return -1;return (typeof x==='number'?x-y:String(x).localeCompare(String(y)))*sgn;});
  tb.innerHTML=rows.map(r=>{
    const sup=r.manual?'manual':(r.src==='na'?'—':fmt(r.players));
    const top1=r.manual||r.src==='na'?'—':pct(r.top1);
    const tags=[...(r.gates?r.gates.split(';'):[]),...(r.flags?r.flags.split(';'):[])].filter(Boolean).map(t=>`<span class="tag">${esc(t)}</span>`).join('');
    return `<tr class="row" data-id="${esc(r.id)}" tabindex="0" aria-expanded="${state.open===r.id}">
<td class="num">${fmt(r.score,1)}</td><td><span class="name">${esc(r.name)}</span><span class="id">${esc(r.id)} · ${esc(r.tier)} · ${esc(r.geo)}</span></td>
<td><span class="v ${r.verdict}" title="${esc(r.note)}">${V[r.verdict]}</span></td><td title="${esc(r.ptgt)}">${r.grade&&r.grade!=='—'?`<b style="color:${GR[r.grade]||'var(--ink2)'}">${esc(r.grade)}</b>`:(r.grade==='—'?'excl.':'—')}</td><td class="num" title="${esc(r.poslow)}">${r.sharelow==null?'—':(r.sharelow>2?'>200%':pct(r.sharelow))}</td><td>${esc(r.ticket||'—')}</td><td class="num">${r.fit==null?'—':r.fit}</td><td>${esc(r.side)}</td><td class="num">${fmt(r.demand)}</td><td class="num">${fmt(r.demand2023)}</td><td class="num">${r.cpc==null?'—':'$'+fmt(r.cpc,r.cpc<10?1:0)}</td>
<td>${esc(r.kp||'—')}</td><td>${r.gt==='NA'?'—':esc(r.gt)}</td><td>${!r.yt||r.yt==='NA'?'—':esc(r.yt)}</td><td title="${esc(r.rvt)}">${esc(r.rv||'—')}</td><td title="${esc(r.qvt)}">${esc(r.qv||'—')}</td><td class="num" title="${esc(r.src)}">${sup}</td><td class="num" title="${esc(r.top1name||'')}">${top1}</td><td>${esc(r.price||'—')}</td><td class="num">${r.gp?(r.gp>=1e6?fmt(r.gp/1e6,1)+' M':fmt(r.gp/1e3,0)+' k'):'—'}</td><td>${tags}</td></tr>`+
(state.open===r.id?`<tr class="detail"><td colspan="21"><div class="pass">${r.md||'<p>No passport found. Run s6_passports.</p>'}</div></td></tr>`:'');
  }).join('');
  document.querySelectorAll('th[data-k]').forEach(th=>{th.removeAttribute('data-dir');if(th.dataset.k===state.k)th.dataset.dir=state.dir;});
}
chips();lists();
document.getElementById('filters').addEventListener('click',e=>{const b=e.target.closest('.chip');if(!b)return;const set=state[b.dataset.f];const on=b.getAttribute('aria-pressed')==='true';if(on)set.delete(b.dataset.v);else set.add(b.dataset.v);b.setAttribute('aria-pressed',String(!on));render();});
document.getElementById('filters').addEventListener('input',e=>{if(e.target.id==='q'){state.q=e.target.value.trim().toLowerCase();render();}});
document.querySelector('thead').addEventListener('click',e=>{const th=e.target.closest('th[data-k]');if(!th)return;if(state.k===th.dataset.k)state.dir=state.dir==='desc'?'asc':'desc';else{state.k=th.dataset.k;state.dir=['name','side','verdict','ticket'].includes(th.dataset.k)?'asc':'desc';}render();});
function toggle(id){state.open=state.open===id?null:id;render();if(state.open){const el=document.querySelector(`tr.row[data-id="${id}"]`);el&&el.scrollIntoView({block:'start',behavior:'smooth'});}}
document.getElementById('tb').addEventListener('click',e=>{const tr=e.target.closest('tr.row');if(tr)toggle(tr.dataset.id);});
document.getElementById('tb').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){const tr=e.target.closest('tr.row');if(tr){e.preventDefault();toggle(tr.dataset.id);}}});
for(const id of ['topScore','topPtg'])document.getElementById(id).addEventListener('click',e=>{const a=e.target.closest('a[data-open]');if(!a)return;e.preventDefault();state.verdict=new Set(['green','yellow','red']);state.side=new Set(SIDES);state.tier=new Set(TIERS);state.grade=new Set(GRADES);state.q='';chips();toggle(a.dataset.open);});
render();
</script></body></html>
"""
