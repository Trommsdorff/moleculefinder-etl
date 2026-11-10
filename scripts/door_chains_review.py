#!/usr/bin/env python3
"""Write the door chains review page (build plan everyday chemistry 2026-11, phase 4).

Reads the compiled data/snapshots/doors.json, the seeds' new writing (transform/doors.door_strings) and the
record scripts/door_chains_2026_11.yaml (the basis for every new string, Garrett's rulings, the line fixes and the checks), and writes one
self-contained page for Garrett:

    ../moleculefinder-web/docs/design/door-chains-review-2026-11.html

    ./.venv/bin/python3 scripts/door_chains_review.py

It refuses to write when a new string has no basis in the record, or the record names a string the seeds no
longer have, so the page can never show writing nobody has accounted for. Run it after `mfetl all`.
"""
from __future__ import annotations

import json
import sys
from html import escape
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from moleculefinder_etl.transform import doors

SNAP = ROOT / "data" / "snapshots"
RECORD = ROOT / "scripts" / "door_chains_2026_11.yaml"
OUT = ROOT.parent / "moleculefinder-web" / "docs" / "design" / "door-chains-review-2026-11.html"

PRESENCE = {"natural": "Naturally present", "added": "Added by the maker", "body": "Made by your body"}
FORMED = {"fermentation": "Formed by fermentation"}
SOURCES = {s["key"]: s for s in json.loads((SNAP / "sources.json").read_text())["sources"]}
MOLS: dict[str, dict] = {}


def mol(slug):
    if slug not in MOLS:
        MOLS[slug] = json.loads((SNAP / "molecules" / f"{slug}.json").read_text())
    return MOLS[slug]


def e(s) -> str:
    return escape(str(s or ""))


def mark_html(presence, lst, absent=None) -> str:
    if presence is None:
        why = f" {e(absent['text'])}" if absent else ""
        return f'<span class="mark mark--none">No mark</span><span class="from">New writing, Sources and notes:{why}</span>'
    v = presence["value"]
    if v == "formed":
        w = presence.get("formed_when")
        word = FORMED.get(w, f"Formed when {w}")
    elif v == "none":
        word = "No mark"
    else:
        word = PRESENCE[v]
    where = f"from our {e(lst['name'])} list" if lst and lst["kind"] == "hub" else f"from {e(lst['name'])}" if lst else ""
    if presence.get("rule") == "label":
        where = f"{where} (a label row: added by rule)"
    note = f' · "{e(presence["note"])}"' if presence.get("note") else ""
    return f'<span class="mark mark--{e(v)}">{word}</span><span class="from">{where}{note}</span>'


def source_html(t) -> str:
    if not t:
        return ""
    if t.get("new"):
        return '<span class="tag tag--new">New writing</span>'
    r = t["ref"]
    k = r["kind"]
    if k == "why":
        what = f"why-it-matters line of {e(mol(r['molecule'])['title'])}"
    elif k == "sentence":
        what = f'comparison notes, /vs/{e(r["pair"])}, the sentence starting "{e(r["starts"])}"'
    elif k == "answer":
        what = f"answer line of /vs/{e(r['pair'])} (its live description)"
    elif k == "editorial":
        what = f'editorial of {e(mol(r["molecule"])["title"])}, the sentence starting "{e(r["starts"])}"'
    elif k == "product_pair":
        what = f"answer line of /whats-in/{e(r['pair'])} (label facts)"
    elif k == "board":
        what = f"first sentence of the /best/{e(r['board'])} board's description"
    elif k == "world":
        what = f"blurb of the {e(r['world'])} world"
    elif k == "title":
        what = "the molecule's title"
    else:
        what = e(k)
    pinned = " · pinned" if r.get("pinned") else " · not pinned (the list page's own line)" if r.get("pinned") is False else ""
    return f'<span class="tag">Quoted: {what}{pinned}</span>'


def number_html(n) -> str:
    if not n:
        return ""
    if n["kind"] == "editorial":
        how = f"Editorial: the amount on our {e(n['list']['name'])} list"
    elif n["kind"] == "label":
        per = f" ({e(n['per'])})" if n.get("per") else ""
        how = f"From the {e(n['product'])} label on DailyMed{per}"
    else:
        src = SOURCES.get(n.get("source"), {}).get("name", n.get("source"))
        how = f"Measured relative sweetness, source: {e(src)}"
    return f'<div class="num"><b>{e(n["text"])}</b><span class="from">{how}</span></div>'


def text_block(t, cls="explain") -> str:
    if not t:
        return ""
    return f'<p class="{cls}">{e(t["text"])}</p>{source_html(t)}'


def basis_html(key: str, basis: dict, labels) -> str:
    if key in basis:
        return f'<div class="basis"><b>Basis.</b> {e(basis[key])}</div>'
    if key.endswith(tuple(labels)):
        return '<div class="basis basis--label">A label; states no fact.</div>'
    raise SystemExit(f"no basis for {key}")


def mol_line(m) -> str:
    return f'<span class="mname">{e(m["title"])}</span> <span class="mono">{e(m["formula"] or "no single formula")}</span>' + (
        "" if m["has_structure"] else ' <span class="tag tag--warn">no drawing yet (phase 5 repeat unit)</span>')


def requires_html(reqs) -> str:
    if not reqs:
        return ""
    return '<ul class="req">' + "".join(f"<li>✓ {e(r)}</li>" for r in reqs) + "</ul>"


def stop_html(slug, s, basis, labels) -> str:
    key = f"{slug}.stop{s['n']}"
    h = [f'<section class="stop"><div class="stop__n">{s["n"]}</div><div class="stop__body">',
         f'<h4>{e(s["heading"]["text"])} <span class="tag tag--new">New writing</span></h4>',
         basis_html(f"{key}.heading", basis, labels)]
    nav = s["nav"]
    h.append(f'<div class="meta">Nav label: <b>{e(nav["text"])}</b>{" (new)" if nav.get("new") else " (the title)"}</div>')
    if s.get("molecule"):
        h.append(f'<div class="lead">{mol_line(s["molecule"])}<div class="marks">'
                 f'{mark_html(s.get("presence"), s.get("presence_list"), s.get("presence_absent"))}</div></div>')
        if s.get("presence_absent"):
            h.append(basis_html(f"{key}.unmarked", basis, labels))
        h.append(text_block(s.get("text")))
        if s.get("note"):
            h.append(f'<div class="explain">{e(s["note"]["text"])} <span class="tag tag--new">New writing</span></div>'
                     + basis_html(f"{key}.note", basis, labels))
        h.append(number_html(s.get("number")))
    if s["labels"]:
        h.append('<table class="labels"><tr><th>Label</th><th>Active</th><th>Purpose (the label\'s words)</th><th>Strength</th></tr>')
        for r in s["labels"]:
            h.append(f'<tr><td>{e(r["name"])}</td><td>{e(r["listed_as"] or r["molecule"])}</td><td>{e(r["purpose"])}</td>'
                     f'<td>{e(r["strength"])}{" " + e(r["strength_per"]) if r.get("strength_per") else ""}</td></tr>')
        h.append('</table><div class="from">Every row read from the product\'s DailyMed label; the mark is "Added by the maker" by rule.</div>')
    if s["items"]:
        h.append('<div class="items">')
        for it in s["items"]:
            comp = (f'<div class="comp">Drawn with {mol_line(it["companion"])} '
                    f'{mark_html(it.get("companion_presence"), it.get("companion_list"))}</div>') if it.get("companion") else ""
            h.append(f'<div class="item">{mol_line(it["molecule"])}<div class="marks">'
                     f'{mark_html(it["presence"], it["presence_list"])}</div>{number_html(it.get("number"))}{comp}'
                     f'{text_block(it.get("text"), "small")}</div>')
        h.append("</div>")
    if s["more"]:
        h.append('<details class="more" open><summary>Read more (closed on the page)</summary>')
        for r in s["more"]:
            if "aside" in r:
                a = r["aside"]
                h.append(f'<div class="aside"><b>{e(a["heading"]["text"])}</b> <span class="tag tag--new">New writing</span>'
                         f'{basis_html(f"{key}.more{s["more"].index(r) + 1}.aside", basis, labels)}'
                         f'<div>{mol_line(a["molecule"])} {mark_html(a["presence"], a["presence_list"])}</div>'
                         f'{text_block(a["text"], "small")}</div>')
            else:
                h.append(text_block(r, "quote"))
        h.append("</details>")
    if s["links"]:
        h.append('<div class="links">Links: ' + " · ".join(f'<a href="https://moleculefinder.com{e(x["href"])}">{e(x["label"])}</a>'
                                                       for x in s["links"]) + "</div>")
    if s["requires"]:
        h.append('<div class="meta">Requires (the build stops if one fails):</div>' + requires_html(s["requires"]))
    h.append("</div></section>")
    return "".join(h)


def door_html(d, basis, labels) -> str:
    s = d["slug"]
    status = ("Live page, upgraded in place in phase 7" if d["live"]
              else f'Dark until phase 7; the home card links to <a href="https://moleculefinder.com{e(d["interim"]["href"])}">{e(d["interim"]["href"])}</a> until then')
    h = [(f'<section class="door" id="{e(s)}"><h2><span class="door__n">{d["order"]}</span>{e(d["name"]["text"])}'
          f' <span class="mono small">{e(d["href"])}</span></h2><p class="status">{status}</p>'),
         '<div class="grid2"><div class="box"><h3>Home card</h3>',
         f'<p class="card-line">{e(d["card"]["line"]["text"])}</p><span class="tag tag--new">New writing</span>',
         basis_html(f"{s}.card.line", basis, labels),
         f'<p class="meta">Link text: <b>{e(d["card"]["go"]["text"])}</b>, to {e(d["card"]["href"])}</p>',
         requires_html(d["card"]["requires"]), "</div>",
         '<div class="box"><h3>Title and lede</h3>',
         (f'<p class="title mono">{e(d["title"]["text"])}</p><p class="lede">{e(d["lede"]["text"])}</p>'
          '<span class="tag tag--new">New writing</span>'), basis_html(f"{s}.lede", basis, labels),
         requires_html(d["requires"])]
    if d["kind"] == "group":
        h.append(f'<p class="meta">Page title: <b>{e(d["page_title"]["text"])}</b> ({len(d["page_title"]["text"])})</p>'
                 + basis_html(f"{s}.page_title", basis, labels)
                 + f'<p class="meta">Description ({len(d["description"]["text"])}): {e(d["description"]["text"])}</p>'
                 + basis_html(f"{s}.description", basis, labels))
    else:
        h.append('<p class="meta">Page title and description: unchanged (the live page keeps its own).</p>')
    h.append("</div></div>")
    h.append('<h3>The stops, in order</h3>' + "".join(stop_html(s, st, basis, labels) for st in d["stops"]))
    if d["also"]:
        h.append('<h3>Also on the list</h3><div class="items">')
        for a in d["also"]:
            h.append(f'<div class="item">{mol_line(a["molecule"])}<div class="marks">{mark_html(a["presence"], a["presence_list"])}</div>'
                     f'{text_block(a["text"], "small")}</div>')
        h.append("</div>")
    else:
        h.append('<p class="meta">Also on the list: none left; the stops show every molecule on the list.</p>')
    h.append('<h3>Where next?</h3><div class="grid2">')
    for i, w in enumerate(d["where_next"], 1):
        body = text_block(w.get("text"), "small") if w.get("text") else (
            f'<p class="small">{e(w["line"]["text"])}</p><span class="tag tag--new">New writing</span>'
            + basis_html(f"{s}.next{i}.line", basis, labels))
        drawing = f' <span class="tag">pair drawing (phase 5): {e(w["pair_drawing"])}</span>' if w.get("pair_drawing") else ""
        mline = f'<div>{mol_line(w["molecule"])}</div>' if w.get("molecule") else ""
        h.append(f'<div class="box"><b>{e(w["go"]["text"])} →</b> <span class="mono small">{e(w["to"]["href"])}</span>{drawing}'
                 f'{mline}{body}{requires_html(w["requires"])}</div>')
    h.append("</div>")
    if d["members"]:
        h.append('<h3>Members: the labels and lists this page gathers</h3><p class="meta">Each gains one line back in phase 7, '
                 f'"Part of {e(d["name"]["text"])}".</p><ul class="members">'
                 + "".join(f'<li><a href="https://moleculefinder.com{e(m["href"])}">{e(m["label"])}</a> <span class="mono small">{e(m["href"])}</span></li>'
                           for m in d["members"]) + "</ul>")
    h.append(f'<p class="meta">Molecules on this door ({len(d["molecules"])}): {e(", ".join(mol(x)["title"] for x in d["molecules"]))}</p>')
    h.append("</section>")
    return "".join(h)


CSS = r"""
:root{--bg:#0e2233;--panel:#132b40;--panel2:#0b1b29;--ink:#e8f1f7;--ink-2:#bcd0de;--muted:#8fa8ba;--line:#24425a;
--cyan:#7fc4e8;--amber:#e9a23b;--green:#5fc28a;--violet:#b48ef0;--warn:#e9a23b}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--ink)}
body{font:17px/1.55 -apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:28px 16px 80px}
h1,.mono,.title{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
h1{font-size:30px;margin:8px 0 6px}h2{font-size:24px;margin:0 0 4px;display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
h3{font-size:18px;margin:26px 0 10px;color:var(--cyan)}h4{font-size:18px;margin:0 0 6px}
a{color:var(--cyan)}.small{font-size:14px}.meta{color:var(--muted);font-size:15px;margin:6px 0}
.lede,.card-line{font-size:18px}.title{font-size:20px;margin:0 0 6px}
.box,.door,.need{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:16px}
.door{margin:34px 0;padding:22px}.door__n,.stop__n{display:inline-grid;place-items:center;width:30px;height:30px;border-radius:50%;
background:var(--amber);color:#1b1206;font-weight:700;font-size:15px;flex:none}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:760px){.grid2{grid-template-columns:1fr}}
.stop{display:flex;gap:14px;border-top:1px solid var(--line);padding:16px 0}.stop__body{flex:1;min-width:0}
.lead{margin:6px 0}.mname{font-family:ui-monospace,Menlo,monospace;font-weight:700}
.marks{margin:4px 0}.mark{display:inline-block;font-size:14px;padding:1px 8px;border-radius:4px;margin-right:8px;font-weight:600}
.mark--natural{background:#1f4a35;color:#bff0d3}.mark--added{background:#4a3a1a;color:#ffe2ad}.mark--body{background:#2d2f55;color:#d6d8ff}
.mark--formed{background:#4a2b20;color:#ffd0bd}.mark--none{background:#33404b;color:#cfd8df}
.from{color:var(--muted);font-size:14px}.explain{margin:8px 0 2px}.quote{margin:10px 0 2px;border-left:3px solid var(--line);padding-left:10px}
.tag{display:inline-block;font-size:13px;color:var(--ink-2);background:var(--panel2);border:1px solid var(--line);border-radius:4px;padding:0 6px;margin:2px 0}
.tag--new{color:#1b1206;background:var(--amber);border-color:var(--amber);font-weight:700}.tag--warn{color:var(--amber)}
.basis{font-size:14px;color:var(--ink-2);background:var(--panel2);border-radius:4px;padding:6px 10px;margin:6px 0}
.basis--label{color:var(--muted)}.num b{color:var(--amber);font-family:ui-monospace,Menlo,monospace;margin-right:8px}
.items{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(300px,100%),1fr));gap:10px;margin:8px 0}
.item{background:var(--panel2);border:1px solid var(--line);border-radius:4px;padding:10px}
.item p.small{margin:6px 0 2px}.comp{font-size:14px;margin:4px 0}
table.labels{border-collapse:collapse;width:100%;margin:8px 0;font-size:15px}table.labels th,table.labels td{border:1px solid var(--line);padding:5px 8px;text-align:left}
table.labels th{color:var(--muted);font-weight:600}
.req{list-style:none;padding:0;margin:4px 0;font-size:14px;color:#bff0d3}.links{font-size:15px;margin:8px 0}
details.more{margin:10px 0}details.more summary{cursor:pointer;color:var(--cyan)}
.aside{background:var(--panel2);border-radius:4px;padding:10px;margin:10px 0}
.need{margin:12px 0;border-left:4px solid var(--amber)}.need h3{margin:0 0 6px;color:var(--ink)}.rec{color:#bff0d3}
table.plain{border-collapse:collapse;width:100%;font-size:15px}table.plain td,table.plain th{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
nav.toc a{margin-right:14px;display:inline-block}
.mono,.from,.tag,a{overflow-wrap:anywhere}.stop__body,.box,.item,.need{min-width:0}
@media(max-width:640px){.door{padding:14px}table.plain,table.labels{display:block;overflow-x:auto}.stop{gap:10px}}
"""


def main() -> None:
    record = yaml.safe_load(RECORD.read_text())
    basis, labels = record["basis"], record["label_suffixes"]
    keys = {k for k, _ in doors.door_strings()}
    missing = sorted(k for k in keys if k not in basis and not k.endswith(tuple(labels)))
    stale = sorted(set(basis) - keys)
    if missing or stale:
        raise SystemExit(f"the record and the seeds disagree: no basis for {missing}; basis for no string {stale}")
    data = json.loads((SNAP / "doors.json").read_text())
    wid = {f.stem: json.loads(f.read_text()).get("what_it_does") for f in (SNAP / "molecules").glob("*.json")}
    wid = {k: v for k, v in sorted(wid.items()) if v}
    meta = json.loads((SNAP / "meta.json").read_text())

    rulings = "".join(f'<div class="need"><h3>{i}. {e(n["title"])}</h3><p>{e(n["asked"])}</p>'
                      f'<p class="rec"><b>Your ruling:</b> {e(n["ruling"])}</p></div>'
                      for i, n in enumerate(record["rulings"], 1))
    fixes = "".join(f'<div class="need"><h3>{i}. {e(f["title"])}</h3><p><b>Was:</b> {e(f["was"])}</p>'
                    f'<p class="rec"><b>Now:</b> {e(f["now"])}</p><p class="meta">{e(f["note"])}</p></div>'
                    for i, f in enumerate(record["fixes"], 1))
    changes = "".join(f"<li><b>{e(c['door'])}:</b> {e(c['text'])}</li>" for c in record["changes"])
    checks = "".join(f"<li>{e(c)}</li>" for c in record["checks"])
    cards = "".join(f'<tr><td>{d["order"]}. {e(d["name"]["text"])}</td><td>{"Live: its own page" if d["live"] else "Dark until phase 7"}</td>'
                    f'<td class="mono">{e(d["card"]["href"])}</td><td class="mono">{e(d["href"])}</td></tr>' for d in data["doors"])
    wid_rows = "".join(f'<tr><td>{e(mol(s)["title"])}</td><td>{"".join(f"<p>{e(x["text"])} <span class=\'tag\'>/vs/{e(x["pair"])}</span></p>" for x in v["sentences"])}</td>'
                       f'<td>{e(v["illustration"] or "none")}</td></tr>' for s, v in wid.items())
    toc = "".join(f'<a href="#{e(d["slug"])}">{d["order"]}. {e(d["name"]["text"])}</a>' for d in data["doors"])
    body = f"""
<main class="wrap">
<h1>The six door chains: review</h1>
<p class="meta">Build plan everyday chemistry, phase 4, built 2026-11-10 on branches <span class="mono">door-seeds-2026-11</span>
(ETL and web). Snapshot data date {e(meta["refreshed"])}. <b>Approved by Garrett on 2026-11-10 with the rulings below; this page
shows the final chains as deployed.</b> Nothing on the doors is visible yet: they render from phase 7.</p>
<p>How to read it. Every door is a hand seed of <b>references</b>: what a reader will see at each stop is quoted from a line
MoleculeFinder already publishes (a molecule's why-it-matters line, a sentence of our comparison notes, an answer line, a label's
own words), and each quote is pinned, so the build stops if that line ever changes. The only new writing is marked
<span class="tag tag--new">New writing</span>, with its basis under it. Marks are read from phase 1's presence seeds, never written
here. "Requires" lines are facts the build checks on every run, including Monday's: if a label stops listing a molecule, the run
stops, names the door and the fact, and the live site keeps last week's data.</p>
<nav class="toc">{toc}</nav>

<h2 style="margin-top:28px">Your rulings on the seven questions ({len(record["rulings"])})</h2>
{rulings}

<h2 style="margin-top:28px">Four lines the doors quote, fixed (live copy)</h2>
{fixes}

<h2 style="margin-top:28px">Your ruling, recorded: the web phases deploy one at a time</h2>
<p>Phase 6 (foundations, navigation, home page, search) deploys on its own, then phases 7, 8 and 9 each when built, checked and
approved; phases 3 and 5 slot in alongside; phase 10 shrinks to the removals and the budget. So the three new group pages stay
dark until phase 7, and the home page's six cards need somewhere to link on the day phase 6 goes live. doors.json carries it:</p>
<table class="plain"><tr><th>Door card</th><th>On phase 6's day</th><th>Card links to</th><th>Its own page (from phase 7)</th></tr>{cards}</table>

<h2 style="margin-top:28px">What changed from the plan's table, and why</h2>
<ul>{changes}</ul>

{"".join(door_html(d, basis, labels) for d in data["doors"])}

<section class="door"><h2>What it does ({len(wid)} molecules)</h2>
<p class="meta">{e(record["what_it_does_note"])}</p>
<table class="plain"><tr><th>Molecule</th><th>Sentences</th><th>Illustration</th></tr>{wid_rows}</table></section>

<section class="door"><h2>Checks</h2>
<ul>{checks}</ul></section>
</main>"""
    html = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Door chains review</title><style>{CSS}</style></head><body>{body}</body></html>')
    for bad in ("—", "–"):
        if bad in html:
            raise SystemExit("a dash in the review page")
    OUT.write_text(html)
    print(f"wrote {OUT} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
