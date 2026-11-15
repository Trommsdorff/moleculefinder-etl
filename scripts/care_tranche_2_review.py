"""Write the 2026-12-care tranche's review page (moleculefinder-web/docs/design/care-tranche-2-review-2026-11.html),
one self-contained file.

    ./.venv/bin/python3 scripts/care_tranche_2_review.py <shots-dir> <facts.json> <main.json> <branch.json>

<shots-dir> holds the JPEG screenshots (Lighthouse full-page captures of local production builds, keys blanked);
<facts.json> the session's check results; <main.json> and <branch.json> the frozen-text extracts of the two builds.
Everything else is read from the committed snapshot, the seeds and the web repo's frozen-text record.
"""
from __future__ import annotations

import base64
import html
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT.parent / "moleculefinder-web"
OUT = WEB / "docs" / "design" / "care-tranche-2-review-2026-11.html"
SNAP = ROOT / "data" / "snapshots"
SEEDS = ROOT / "moleculefinder_etl" / "sources" / "seeds"
NEW = ["titanium-dioxide", "octinoxate", "oxybenzone"]
SUF = " · MoleculeFinder"

BASIS = {
    "titanium-dioxide": (
        "Refractive index at 589 nm: rutile 2.61 (ordinary ray) and 2.90 (extraordinary), anatase 2.55 and 2.49, diamond "
        "2.42 (CRC Handbook of Chemistry and Physics, optical properties of crystals), so both pigment forms bend light more "
        "strongly than diamond. Grains of about 0.2 to 0.3 micrometres scatter all visible wavelengths about equally, which is "
        "why the powder looks white rather than coloured (Mie scattering; the standard account of white pigments). On a tablet "
        "it is the opacifier in film coatings, hiding the core's colour and shielding a light-sensitive drug (pharmaceutical "
        "excipient handbooks, Handbook of Pharmaceutical Excipients, titanium dioxide). Its band gap (rutile about 3.0 eV, "
        "about 410 nm; anatase about 3.2 eV, about 385 nm) means it absorbs UVB and the shorter UVA, and passes visible "
        "light; it is listed as a sunscreen active in M020.10(o). No claim word."),
    "octinoxate": (
        "PubChem CID 5355130, 2-ethylhexyl (E)-3-(4-methoxyphenyl)prop-2-enoate: the 2-ethylhexyl ester of "
        "4-methoxycinnamic acid. Absorption maximum about 311 nm, UVB (Shaath, Photochem. Photobiol. Sci. 2010, 9, 464). In "
        "sunlight the trans (E) form isomerises in part to the cis (Z) form, which absorbs less strongly, so the filter loses "
        "protection over time (Pattanaargson et al., Photochem. Photobiol. 2004, 79, 207; Huong et al., J. Photochem. "
        "Photobiol. A 2008). No claim word."),
    "oxybenzone": (
        "PubChem CID 4632, 2-hydroxy-4-methoxybenzophenone, known as benzophenone-3. Two absorption maxima, about 288 nm "
        "(UVB) and 325 nm (UVA2, short-wave UVA) (Shaath 2010). The phenol OH and the ketone C=O beside it share a hydrogen "
        "bond; after absorbing UV the proton moves to the oxygen of the C=O and back, and the energy leaves as heat "
        "(excited-state intramolecular proton transfer: Baker et al., J. Phys. Chem. Lett. 2015, 6, 1363). No claim word."),
}


def e(s) -> str:
    return html.escape(str(s), quote=True)


def img(shots: Path, name: str, cap: str) -> str:
    p = shots / f"{name}.jpg"
    if not p.exists():
        return f'<figure><figcaption>{e(cap)}</figcaption><p class="muted">(missing: {e(name)})</p></figure>'
    data = base64.b64encode(p.read_bytes()).decode()
    return (f'<figure><figcaption>{e(cap)}</figcaption><img loading="lazy" alt="{e(cap)}" '
            f'src="data:image/jpeg;base64,{data}"></figure>')


def rec(slug: str) -> dict:
    return json.loads((SNAP / "molecules" / f"{slug}.json").read_text())


def sha(cwd: Path) -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def ba(before, after) -> str:
    if before == after:
        return e(after)
    return f"<del>{e(before)}</del><br><ins>{e(after)}</ins>"


def main() -> None:
    shots, facts = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text())
    main_x, branch_x = json.loads(Path(sys.argv[3]).read_text()), json.loads(Path(sys.argv[4]).read_text())
    frozen = json.loads((WEB / "scripts" / "frozen-text-care-tranche-2.json").read_text())
    products = {p["slug"]: p for p in json.loads((SNAP / "products.json").read_text())["products"]}
    hubs = yaml.safe_load((SEEDS / "product_hubs.yaml").read_text())
    h: list[str] = []
    w = h.append
    w("""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Care tranche 2 review</title><style>
:root { --bg:#0e2233; --panel:#132c40; --ink:#e6f0f7; --muted:#9db3c4; --accent:#7fc4e8; --amber:#e9a23b; --line:#24445c; --del:#ff7a72; --ins:#8fd982; }
@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) { --bg:#f6f8fa; --panel:#fff; --ink:#132433; --muted:#4d6475; --accent:#1d6fa3; --amber:#a5620a; --line:#d4dde4; --del:#b42318; --ins:#1a7f37; } }
:root[data-theme="dark"] { --bg:#0e2233; --panel:#132c40; --ink:#e6f0f7; --muted:#9db3c4; --accent:#7fc4e8; --amber:#e9a23b; --line:#24445c; --del:#ff7a72; --ins:#8fd982; }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:1180px; margin:0 auto; padding:24px 16px 80px; }
h1 { font:700 30px/1.2 ui-monospace,Menlo,monospace; margin:8px 0 4px; }
h2 { margin:44px 0 10px; padding-top:14px; border-top:1px solid var(--line); font-size:22px; }
h3 { margin:26px 0 6px; font-size:18px; } code { font:13px ui-monospace,Menlo,monospace; color:var(--muted); }
.box { background:var(--panel); border:1px solid var(--line); border-left:4px solid var(--amber); border-radius:6px; padding:14px 18px; margin:14px 0; }
.box h3 { margin-top:6px; } .rec { color:var(--accent); font-weight:600; }
table { border-collapse:collapse; width:100%; font-size:14px; margin:8px 0; } td,th { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
th { color:var(--muted); font-weight:600; }
.ba { display:grid; grid-template-columns:1fr 1fr; gap:14px; align-items:start; margin:10px 0; }
.wn { display:grid; grid-template-columns:3fr 1fr; gap:14px; align-items:start; margin:10px 0; }
figure { margin:0; } figcaption { font-size:13px; color:var(--muted); margin-bottom:4px; }
img { width:100%; height:auto; border:1px solid var(--line); border-radius:4px; display:block; }
.muted { color:var(--muted); } ul { padding-left:20px; } li { margin:4px 0; } .scroll { overflow-x:auto; }
del { color:var(--del); } ins { color:var(--ins); text-decoration:none; }
details { margin:8px 0; } summary { cursor:pointer; color:var(--accent); }
@media (max-width:700px) { .ba, .wn { grid-template-columns:1fr; } }
</style></head><body><main>""")
    w(f"<p><code>moleculefinder-web/docs/design/care-tranche-2-review-2026-11.html</code> · built 2026-11-15 on "
      f"<code>care-tranche-2-2026-11</code> in both repos (ETL <code>{e(sha(ROOT))}</code>, web <code>{e(sha(WEB))}</code>) · "
      f"<b>not deployed; waiting for your approval of this page</b>.</p>")
    w("<h1>The 2026-12-care tranche</h1>")
    w("<p>Three molecules join the catalog (926 to 929): <b>titanium dioxide</b>, <b>octinoxate</b> and <b>oxybenzone</b>, "
      "each a sunscreen active the FDA's sunscreen monograph permits today. Titanium dioxide is also the white pigment on "
      "150 of our live label pages, so linking it moves many pages' counts and descriptions; every one is recorded below. "
      "Carboxymethyl cellulose stops showing what PubChem computed from its two-fragment record, and the eleven product "
      "lists get a shorter description. Every screenshot is from a local production build with the database keys "
      "blanked: <i>before</i> is today's <code>main</code> (what is live), <i>after</i> is this branch.</p>")

    # ── Needs Garrett ────────────────────────────────────────────────────────────────────────────────
    w("<h2>Needs you (six decisions, each with a recommendation)</h2>")
    n_label = sum(1 for p in frozen if p.startswith("whats-in/"))
    n_label_title = sum(1 for p in frozen if p.startswith("whats-in/") and "title" in frozen[p])
    n_in = sum(1 for p in frozen if p.startswith("in/"))
    titles = sum(1 for v in frozen.values() if "title" in v)
    descs = sum(1 for v in frozen.values() if "description" in v)
    lost = facts["lost_closing_sentence"]
    w(f"""<div class="box"><h3>1. Accept the {len(frozen)} live pages whose title or description moves</h3>
<p>An allowed, recorded exception to the frozen-text rule, as in phase 3B. {n_label} label pages ({n_label_title} also
move the molecule count in their title; the other {n_label - n_label_title} have titles too long to carry a count, so
only the description moves), {n_in} <code>/in</code> lists (counts, and the eleven product lists' new clause), the home
page and <code>/whats-in</code> (counts). In all, {titles} titles and {descs} descriptions. <b>No title passes 65
characters</b> (the longest is exactly 65) and <b>no title loses its count</b>. On {len(lost)} label pages the longer
list of names leaves no room under 160 characters for phase 3A's closing sentence "Each matched by FDA code to its
molecule page.", so it drops ({e(", ".join(lost))}); Vancocin, newly passing, carries it.
Every field before and after: the table further down, and <code>scripts/frozen-text-care-tranche-2.json</code>.</p>
<p class="rec">Recommend: accept as recorded.</p></div>""")
    w("""<div class="box"><h3>2. Titanium dioxide has no drawing: the no-structure panel with one line</h3>
<p>It is an extended solid. In rutile and anatase every titanium sits among six oxygens and every oxygen among three
titaniums; there is no TiO<sub>2</sub> molecule. PubChem's titanium dioxide record (CID 26042) carries the SMILES
<code>O=[Ti]=O</code>, and the drawing recipe would draw that as a lone molecule with two double bonds, a species known
only as a gas, so that drawing would not be true. The FDA's own code is filed under a different PubChem record (CID 162651,
<code>[O-2].[O-2].[Ti+4]</code>, three loose ions, the way table salt is drawn), but that record's PubChem title, CAS
number and Wikidata item all belong to another oxide (trititanium oxide), so it is not a record to build the page on.
The page shows the "No single structure" panel: <i>"Titanium dioxide is a crystal lattice of titanium and oxygen with no
single molecule; its formula, TiO2, gives the ratio, one titanium to every two oxygens."</i> Its formula and weight stay
(those of one formula unit); no 3D model, and (found on the screenshots, fixed) none of PubChem's computed descriptors,
which describe the gas-phase molecule.</p>
<p><b>The same question, not changed here:</b> two live lattices are drawn as molecules, silicon dioxide
(<code>O=[Si]=O</code>) and zinc oxide (<code>O=[Zn]</code>); zinc oxide sits next to titanium dioxide on the sunscreen
list. Live drawings are never redrawn silently.</p>
<p class="rec">Recommend: approve the panel as built; and queue silicon dioxide and zinc oxide for the same panel as one
reviewed change in a later pass (the drawing guard lists each removal). The alternative is the FDA record's three ions
drawn as a formula unit.</p></div>""")
    w(f"""<div class="box"><h3>3. Found: a "greater than" LD50 is shown as an exact number, on {facts['gt_ld50_total']} pages</h3>
<p>PubChem's text for titanium dioxide says <i>"LD50 Rat oral &gt; 10,000 mg/kg"</i>; the page says <b>10,000 mg/kg</b>.
The LD50 parser drops a leading "&gt;" (<code>transform/toxicity.py</code>, <code>_NUM</code>), so a lower bound reads as a
measurement. Not new: {facts['gt_ld50_live']} live molecule pages already show one this way
({e(", ".join(facts['gt_ld50_slugs']))}), plus titanium dioxide and octinoxate ("&gt; 8 g/kg", mouse) here.</p>
<p class="rec">Recommend: a separate small reviewed fix that keeps the qualifier and prints "more than 10,000 mg/kg"
(the LD50 line and the FAQ answer on those pages move; no title). Not done here because it moves live pages this tranche
was not asked to touch.</p></div>""")
    w("""<div class="box"><h3>4. Carboxymethyl cellulose is still in the family "Sugars"</h3>
<p>Everything PubChem's two-fragment record gave it is gone (below). One leftover is not from that record: the canon
row has filed it under family <i>sugar</i> since the Scope B rebuild (hand-set in September), so its page says "Family:
Sugars" and it counts on the sugars list. It is a polysaccharide derivative, as cellulose and starch (family
<i>Polysaccharides</i>) are.</p>
<p class="rec">Recommend: move it to Polysaccharides with the next tranche (the two lists' counts move by one each).</p></div>""")
    w("""<div class="box"><h3>5. The paint list names the element titanium for the white pigment</h3>
<p>"Paint and solvent" lists <i>titanium</i> with the note "Added as titanium dioxide, the white pigment." (the October
forms ruling kept the two apart). Now that titanium dioxide has its own page, the entry could point to it.</p>
<p class="rec">Recommend: replace titanium with titanium dioxide on that list in the next tranche (same count; the list's
description would name titanium dioxide). Not done here: the brief named only the label-backed lists.</p></div>""")
    w("""<div class="box"><h3>6. Four names kept off the new pages' name lines, and one Wikidata row marked</h3>
<p>Added to <code>synonym_do_not_use.yaml</code>: <i>titanium peroxide</i> (a Wikidata alias, but a peroxide has an
oxygen to oxygen bond and titanium dioxide has none), <i>Flamenco</i> (a line of pearlescent pigments), <i>rutile</i>
(the mineral, one crystal form, as "fused quartz" was kept off silicon dioxide) and bare <i>Parsol</i> (a family of filter
trade names; Parsol 1789 is avobenzone; "Parsol MCX", octinoxate's own, stays). The raw materials' own trade names stay,
as Heliophan and Escalol do (titanium dioxide: titania, Hombitan, Tiofine, Tioxide; oxybenzone: Anuvex, Ongrostab HMB).
Wikidata lists titanium dioxide among M&amp;M's materials, so that live page gains it; marked Added, "The white the maker
adds to the shell."</p>
<p class="rec">Recommend: accept.</p></div>""")

    # ── The three molecules ─────────────────────────────────────────────────────────────────────────
    w("<h2>The three molecule pages</h2>")
    w("<p>Approval, checked 2026-11-15 on the FDA's OTC Monographs@FDA portal: § M020.10 of the sunscreen monograph M020, "
      "as amended by Final Administrative Order OTC000039 (issued 2026-06-10, corrected 2026-08-10), lists "
      "<i>(i) Octinoxate up to 7.5 percent</i>, <i>(l) Oxybenzone up to 6 percent</i> and <i>(o) Titanium dioxide up to 25 "
      "percent</i> (read from the order's PDF). The portal's news list and the OTC000008 order page show one later order "
      "on M020, OTC000008-1 (Federal Register 2026-09-11), which removed only aminobenzoic acid (PABA) and trolamine "
      "salicylate. Nothing newer is posted (latest news 2026-10-23, unrelated). So all three hold a current authorisation "
      "under the approved-medicine rule (an FDA OTC monograph counts). No regulator's action is used in any line.</p>")
    for slug in NEW:
        r = rec(slug)
        a = r["approval"]
        w(f"<h3>{e(r['title'])} <code>/m/{slug}</code> · PubChem CID {r['cid']} · Wikidata {e(r['wikidata_qid'])}</h3>")
        w(f"<p><b>Its line (also its description, {len(r['description'])} characters):</b> {e(r['description'])}</p>")
        w(f"<p><b>Basis:</b> {e(BASIS[slug])}</p>")
        w(f"<p><b>Approval record:</b> {e(a['regulator'])}, {e(a['product'])}. {e(a['basis'])} "
          f"<a href=\"{e(a['source'])}\">The order</a>.</p>")
        lists = [hubs[k]["name"] for k in hubs if any(m["slug"] == slug for m in hubs[k].get("molecules") or [])]
        labels = sorted(p["name"] for p in products.values() for m in p["molecules"] if m["slug"] == slug)
        ld = f"{r['ld50_mg_per_kg']:,.0f} mg/kg ({r['ld50_species']}, {r['ld50_route']})" if r.get("ld50_mg_per_kg") else "none"
        ghs = r.get("ghs") or {}
        w(f"<p><b>Lists:</b> {e(', '.join(lists))}, each marked Added. <b>Product pages:</b> {len(labels)}"
          f"{' (' + e(', '.join(labels)) + ')' if len(labels) < 8 else ''}. <b>Molecule page safety, as on every molecule "
          f"page:</b> LD50 {e(ld)}; hazard label {e(ghs.get('signal_word') or 'none')}, "
          f"{e(', '.join(f'{c} {t}' for c, t in (ghs.get('h_wording') or {}).items()))} (reported, ECHA via PubChem). "
          f"Product pages show neither. <b>Also called:</b> {e(', '.join(r.get('display_synonyms') or []) or 'none')}.</p>")
        if slug == "titanium-dioxide":
            w("<p><b>Drawing:</b> none; the no-structure panel (decision 2).</p>")
        else:
            parts = [p.get("label") for p in (r.get("structure_parts") or {}).get("parts", [])] \
                if isinstance(r.get("structure_parts"), dict) else []
            w(f"<p><b>Drawing:</b> new, by the current recipe; the drawing guard lists it and its part layer "
              f"({e(', '.join(x for x in parts if x)) or 'parts'}) as new. Octinoxate is drawn trans, as its line says."
              if slug == "octinoxate" else
              "<p><b>Drawing:</b> new, by the current recipe; the drawing guard lists it and its part layer as new. The OH "
              "sits beside the C=O, the hydrogen bond the line describes.")
            w("</p>")
        w(f'<div class="wn">{img(shots, f"after-m_{slug}-1440", f"{r["title"]} at 1440 px")}'
          f'{img(shots, f"after-m_{slug}-390", f"{r["title"]} at 390 px")}</div>')
    w("<p class='muted'>Cetaphil Sheer Mineral Stick SPF 50 lists titanium dioxide as an active with no strength on our "
      "page: its label's own line reads \"Titianium Dioxide 6%\" (misspelt), so the line does not pair with the "
      "ingredient. Left as the label has it.</p>")

    # ── NyQuil and a sunscreen ─────────────────────────────────────────────────────────────────────
    w("<h2>NyQuil, and one sunscreen label, before and after</h2>")
    nq = frozen["whats-in/vicks-nyquil-intense-flu-liquicaps"]
    dq = frozen["whats-in/vicks-dayquil-severe-cold-and-flu"]
    w(f"""<p><b>"does nyquil contain tio2?"</b> We hold three Vicks NyQuil and DayQuil labels. <b>Vicks NyQuil Intense Flu
LiquiCaps</b> and <b>Vicks DayQuil Severe Cold and Flu</b> list titanium dioxide (FDA code 15FIX9V2JP) as an inactive
ingredient; the Vicks DayQuil and NyQuil Kids Honey syrup does not. Today the LiquiCaps page shows it as plain text under
"Also on the label". After this tranche it is a linked row, <i>Titanium dioxide, O2Ti, Inactive ingredient</i>, which
opens the titanium dioxide page; that page lists NyQuil among its {facts['tio2_medicines']} medicines and its panel says
"TiO2" in words. So a searcher lands on a page that answers yes, with the label as the source. The descriptions name it
only in the count: NyQuil {ba(nq['description']['before'], nq['description']['after'])}; DayQuil
{ba(dq['description']['before'], dq['description']['after'])}. Neither title moves (both too long to carry a count).</p>""")
    for slug, nm in [("vicks-nyquil-intense-flu-liquicaps", "NyQuil Intense Flu LiquiCaps"),
                     ("blue-lizard-sport-spf-50", "Blue Lizard Sport SPF 50 (titanium dioxide 8% now its linked active)")]:
        w(f"<h3>{e(nm)}</h3>")
        for wd in ("1440", "390"):
            w(f'<div class="ba">{img(shots, f"before-whats-in_{slug}-{wd}", f"Before, {wd} px")}'
              f'{img(shots, f"after-whats-in_{slug}-{wd}", f"After, {wd} px")}</div>')

    # ── Every changed label page ───────────────────────────────────────────────────────────────────
    w(f"<h2>Every page whose title or description moves ({len(frozen)})</h2>")
    w("<p>Before is live (<code>main</code>), after is this branch. The OpenGraph and Twitter descriptions move with the "
      "meta description, character for character; all three are recorded.</p>")
    for label, test in [("Label and product pages", lambda p: p.startswith("whats-in/")),
                        ("Lists, the home page and /whats-in", lambda p: not p.startswith("whats-in/"))]:
        rows = [p for p in sorted(frozen) if test(p)]
        w(f"<details{' open' if label.startswith('Lists') else ''}><summary>{e(label)} ({len(rows)})</summary>"
          "<div class='scroll'><table><tr><th>Page</th><th>Title</th><th>Description</th></tr>")
        for p in rows:
            f = frozen[p]
            t = f.get("title") or {"before": main_x[p]["title"], "after": branch_x[p]["title"]}
            d = f.get("description") or {"before": main_x[p]["description"], "after": branch_x[p]["description"]}
            w(f"<tr><td><code>/{e(p if p != 'index' else '')}</code></td><td>{ba(t['before'].removesuffix(SUF), t['after'].removesuffix(SUF))}"
              f"</td><td>{ba(d['before'], d['after'])}</td></tr>")
        w("</table></div></details>")

    # ── Newly passing ──────────────────────────────────────────────────────────────────────────────
    v = products["vancocin"]
    w("<h2>Label pages that newly pass the gate (429 to 430)</h2>")
    w(f"<p><b>Vancocin</b> <code>/whats-in/vancocin</code>: {e(branch_x['whats-in/vancocin']['title'].removesuffix(SUF))}. "
      f"{e(', '.join(m['title'] + ' (' + m['role'] + ')' for m in v['molecules']))}: titanium dioxide is its third. "
      f"Description: <i>{e(branch_x['whats-in/vancocin']['description'])}</i> (the label template joins two other "
      "molecules with a comma, not \"and\"; every live label with exactly two reads the same way, so it is left as is). "
      "The 45 labels still failing include none "
      "that titanium dioxide, octinoxate or oxybenzone would lift.</p>")

    # ── CMC ────────────────────────────────────────────────────────────────────────────────────────
    w("<h2>Carboxymethyl cellulose, before and after (your decision 5)</h2>")
    w(f"""<p>PubChem's record CID 24748 is two small molecules (open-chain glucose and acetic acid), not the polymer. Since
phase 3B the page draws the polymer's repeat unit; now everything computed from that record's structure goes too:
<b>formula</b> C8H16O8, <b>weight</b> 240.21 g/mol, the <b>SMILES</b>, InChI and InChIKey, the <b>computed
descriptors</b> (polar surface area 156, six H-bond donors and the rest), all three <b>functional groups</b> (Aldehydes,
which was false; Alcohols and Carboxylic acids, true of CMC only by coincidence of the fragments), its <b>similar
molecules</b> (fructose, allulose, gluconic acid, sorbitol and four more: neighbours of open-chain glucose, so "Keep
exploring" leaves the page and CMC leaves those eight molecules' lists), and its places on the <b>lightest and biggest
boards</b> (ranks {facts['cmc_lightest']} and {facts['cmc_biggest']} by the fragments' weight). <b>In their place</b> the page shows what cellulose's does: the
repeat-unit drawing with its caption, "Where you encounter it", and under Properties only its groups and its PubChem and
Wikidata links. Kept: its title (<i>Carboxymethyl cellulose: formula, structure &amp; chemistry</i>, character for
character, your ruling), its line, its names, its CID link, its label pages. Its structured data now calls it a chemical
substance, not a molecular entity. No comparison page has it. The list counts move: Aldehydes 18 to 17, Alcohols 254 to
253, Carboxylic Acids 163 to 162 (in the table above). One leftover, decision 4.</p>""")
    for wd in ("1440", "390"):
        w(f'<div class="ba">{img(shots, f"before-m_carboxymethyl-cellulose-{wd}", f"Before, {wd} px")}'
          f'{img(shots, f"after-m_carboxymethyl-cellulose-{wd}", f"After, {wd} px")}</div>')

    # ── The eleven lists ───────────────────────────────────────────────────────────────────────────
    w("<h2>The eleven product-list descriptions, before and after</h2>")
    w("<p>One reviewed change to the shared template (<code>lib/seo.ts</code>, the product clause): \"A curated product "
      "membership: each molecule is listed because it is a documented ingredient of the thing named, not because a model "
      "guessed.\" (141 characters) becomes <b>\"A curated list of documented ingredients.\"</b> (41). The longest lead, "
      "deodorant's three long salt names, is 151 characters, so the clause had to be 49 or under; the shortest lead needs "
      "29 or more. It claims no completeness. All eleven now fit 100 to 200 (before, 208 to 292).</p>"
      "<table><tr><th>List</th><th>Description</th><th>Length</th></tr>")
    for p in sorted(x for x in frozen if x.startswith("in/") and frozen[x]["description"]["after"].endswith(
            "A curated list of documented ingredients.")):
        d = frozen[p]["description"]
        w(f"<tr><td><code>/{e(p)}</code></td><td>{ba(d['before'], d['after'])}</td><td>{len(d['before'])} to {len(d['after'])}</td></tr>")
    w("</table>")

    # ── Checks ─────────────────────────────────────────────────────────────────────────────────────
    w("<h2>Checks</h2><ul>")
    for line in facts["checks"]:
        w(f"<li>{line}</li>")
    w("</ul></main></body></html>")
    OUT.write_text("\n".join(h), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
