"""Write the phase 3B review page (moleculefinder-web/docs/design/phase-3b-review-2026-11.html), one self-contained file.

    ./.venv/bin/python3 scripts/phase3b_review.py <shots-dir> <facts.json>

<shots-dir> holds the JPEG screenshots (Lighthouse full-page captures of a local production build, keys blanked);
<facts.json> the session's check results. Everything else is read from the committed snapshot and seeds.
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
OUT = WEB / "docs" / "design" / "phase-3b-review-2026-11.html"
SNAP = ROOT / "data" / "snapshots"
SEEDS = ROOT / "moleculefinder_etl" / "sources" / "seeds"

FILTERS = ["avobenzone", "homosalate", "octisalate", "octocrylene"]
FLUORIDES = ["stannous-fluoride", "sodium-monofluorophosphate"]
SALTS = ["aluminum-chlorohydrate", "aluminum-sesquichlorohydrate", "aluminum-zirconium-tetrachlorohydrex-gly",
         "aluminum-zirconium-octachlorohydrex-gly", "aluminum-zirconium-trichlorohydrex-gly"]
CARE = FILTERS + FLUORIDES + SALTS

# The basis for each new line, the way the copy sweep gave it: the source of each fact the line states.
BASIS = {
    "avobenzone": "UVA-I filter (M020 lists it as a sunscreen active). A 1,3-diketone that sits almost wholly as its "
                  "chelated enol, absorption maximum about 357 nm (Shaath, Photochem. Photobiol. Sci. 2010, 9, 464, table of "
                  "UV filters). Photolabile: UV light breaks it down over time (Kockler et al., J. Photochem. Photobiol. C 2012, "
                  "13, 91). Octocrylene is a standard photostabilizer for it (Lhiaubet-Vallet et al., Photochem. Photobiol. "
                  "2010, 86, 541; Bonda's US patents on octocrylene with avobenzone).",
    "homosalate": "PubChem CID 8362, (3,3,5-trimethylcyclohexyl) 2-hydroxybenzoate: salicylic acid esterified with "
                  "3,3,5-trimethylcyclohexanol. Absorption maximum about 306 nm, UVB (Shaath 2010). A liquid at room "
                  "temperature, used to dissolve crystalline filters such as avobenzone (Shaath 2010).",
    "octisalate": "PubChem CID 8364, 2-ethylhexyl 2-hydroxybenzoate (2-ethylhexanol is the eight-carbon alcohol). "
                  "Absorption maximum about 307 nm, UVB (Shaath 2010). The hydrogen bond between the phenol OH and the ester "
                  "C=O lets the excited molecule pass a proton across and back, returning the energy as heat (the standard "
                  "photophysics of salicylates, excited-state intramolecular proton transfer).",
    "octocrylene": "PubChem CID 22571, 2-ethylhexyl 2-cyano-3,3-diphenylacrylate. Absorption maximum about 303 nm, UVB "
                   "(Shaath 2010). It quenches avobenzone's excited (triplet) state before it can break apart, which is why it "
                   "steadies avobenzone (Lhiaubet-Vallet et al. 2010).",
    "stannous-fluoride": "PubChem CID 24550, SnF2. Procter and Gamble launched Crest in the 1950s (test market 1955, "
                         "national 1956) with stannous fluoride, from Joseph Muhler's work at Indiana University (company and "
                         "university histories). Fluoride from any of the three monograph fluorides is taken into enamel as "
                         "fluoridated apatite, which resists acid (standard dental chemistry). Tin(II) binds to tooth surfaces "
                         "and plaque bacteria, and extrinsic brown staining is its known effect (Ellingsen et al., Scand. J. "
                         "Dent. Res. 1982; Myers, reviews of stannous fluoride dentifrices).",
    "sodium-monofluorophosphate": "PubChem CID 24266, Na2PO3F: the fluorine is bonded to phosphorus, so it does not "
                                  "precipitate as calcium fluoride with a calcium carbonate (chalk) abrasive, as sodium "
                                  "fluoride does. Phosphatases in saliva and plaque split off the fluoride ion (standard dental "
                                  "chemistry; the reason chalk-based pastes use it).",
    "aluminum-chlorohydrate": "USP monograph Aluminum Chlorohydrate: a polymeric basic aluminum chloride with an "
                              "aluminum-to-chloride atomic ratio of 1.91:1 to 2.10:1, about two to one (nominally "
                              "Al2(OH)5Cl). In the sweat duct the salt meets sweat, its pH rises, and it polymerizes into an "
                              "aluminum hydroxide gel that plugs the duct (Quatrale et al., J. Soc. Cosmet. Chem. 1981; Laden "
                              "and Felger, Antiperspirants and Deodorants).",
    "aluminum-sesquichlorohydrate": "USP monograph Aluminum Sesquichlorohydrate: aluminum-to-chloride atomic ratio 1.26:1 "
                                    "to 1.90:1, nominally Al2(OH)4.5Cl1.5, one and a half chlorides for every two aluminum "
                                    "atoms against chlorohydrate's one (sesqui, Latin for one and a half). The same gel plug "
                                    "as aluminum chlorohydrate (Laden and Felger).",
    "aluminum-zirconium-tetrachlorohydrex-gly": "USP monograph Aluminum Zirconium Tetrachlorohydrex Gly: aluminum-to-"
                                                "zirconium atomic ratio 2.0:1 to 5.99:1, (aluminum plus zirconium)-to-chloride "
                                                "1.5:1 to 0.9:1, some water displaced by glycine. More chloride than the "
                                                "trichlorohydrex (2.1:1 to 1.51:1).",
    "aluminum-zirconium-trichlorohydrex-gly": "USP monograph Aluminum Zirconium Trichlorohydrex Gly: aluminum-to-zirconium "
                                              "2.0:1 to 5.99:1 (the tetrachlorohydrex's range), (aluminum plus zirconium)-to-"
                                              "chloride 2.1:1 to 1.51:1, so less chloride; glycine in place of some water.",
    "aluminum-zirconium-octachlorohydrex-gly": "USP monograph Aluminum Zirconium Octachlorohydrex Gly: aluminum-to-zirconium "
                                               "6.0:1 to 10.0:1, against the tetrachlorohydrex's 2.0:1 to 5.99:1; "
                                               "(aluminum plus zirconium)-to-chloride 1.5:1 to 0.9:1; glycine in place of "
                                               "some water.",
}
SALT_DUCT = ("Every salt line ends in the sweat duct: the five are the same class of active, and each forms the gel plug "
             "described for aluminum chlorohydrate.")


def e(s) -> str:
    return html.escape(str(s), quote=True)


def img(shots: Path, name: str, cap: str) -> str:
    p = shots / f"{name}.jpg"
    if not p.exists():
        return f'<figure><figcaption>{e(cap)}</figcaption><p class="muted">(missing: {e(name)})</p></figure>'
    data = base64.b64encode(p.read_bytes()).decode()
    return f'<figure><figcaption>{e(cap)}</figcaption><img loading="lazy" alt="{e(cap)}" src="data:image/jpeg;base64,{data}"></figure>'


def rec(slug: str) -> dict:
    return json.loads((SNAP / "molecules" / f"{slug}.json").read_text())


def main() -> None:
    shots, facts = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text())
    gate = facts["gate"]
    hubs = yaml.safe_load((SEEDS / "product_hubs.yaml").read_text())
    clp = yaml.safe_load((SEEDS / "hazard_statements.yaml").read_text())["eu_clp"]
    etl_sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    web_sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=WEB, capture_output=True, text=True, check=True).stdout.strip()
    h: list[str] = []
    w = h.append
    w("""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Phase 3B review</title><style>
:root { --bg:#0e2233; --panel:#132c40; --ink:#e6f0f7; --muted:#9db3c4; --accent:#7fc4e8; --amber:#e9a23b; --line:#24445c; }
@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) { --bg:#f6f8fa; --panel:#fff; --ink:#132433; --muted:#4d6475; --accent:#1d6fa3; --amber:#a5620a; --line:#d4dde4; } }
:root[data-theme="dark"] { --bg:#0e2233; --panel:#132c40; --ink:#e6f0f7; --muted:#9db3c4; --accent:#7fc4e8; --amber:#e9a23b; --line:#24445c; }
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
del { color:#ff7a72; } ins { color:#8fd982; text-decoration:none; }
details { margin:8px 0; } summary { cursor:pointer; color:var(--accent); }
@media (max-width:700px) { .ba, .wn { grid-template-columns:1fr; } }
</style></head><body><main>""")
    w(f"<p><code>moleculefinder-web/docs/design/phase-3b-review-2026-11.html</code> · built 2026-11-14 on "
      f"<code>care-tranche-2026-11</code> in both repos (ETL <code>{e(etl_sha)}</code>, web <code>{e(web_sha)}</code>) · "
      f"<b>not deployed; waiting for your approval of this page</b>.</p>")
    w("<h1>Phase 3B: the personal-care tranche</h1>")
    w(f"<p>Eleven molecules join the catalog (915 to 926): the four sunscreen filters, the two other toothpaste fluorides "
      f"and the five antiperspirant salts our labels name. With them, {len(gate['newly'])} more label pages pass the "
      f"three-molecule gate ({gate['old_passed']} to {gate['passed']} of {gate['seeded']}) and 17 live label pages now link "
      f"their active. Also here: the aquatic hazard codes take their words from the EU rules, and carboxymethyl cellulose is "
      f"drawn as its repeat unit. Every screenshot is from a local production build with the database keys blanked: "
      f"<i>before</i> from a build of <code>main</code>, <i>after</i> from this branch. I reviewed the chemistry for you; "
      f"the basis for each factual claim is given beside it.</p>")

    # ── needs Garrett ──
    w("<h2>What needs you (each with a recommendation)</h2>")
    for title, body in facts["decisions"]:
        w(f'<div class="box"><h3>{e(title)}</h3>{body}</div>')

    # ── the eleven ──
    w("<h2>The eleven new molecule pages</h2>")
    w("<p>Each page at 1440 px (left) and 390 px (right), then its line, the basis for every fact in it, its approval "
      "record (checked today against the FDA's own final order) and where it now turns up. Product pages show no "
      "pure-substance LD50 or hazard label (phase 10); the molecule pages show them as every molecule page does.</p>")
    for slug in CARE:
        r = rec(slug)
        a = r["approval"]
        w(f'<h3 id="{e(slug)}">{e(r["title"])} <code>/m/{e(slug)}</code></h3>')
        w(f'<div class="wn">{img(shots, f"after-{slug}-1440", "1440 px")}{img(shots, f"after-{slug}-390", "390 px")}</div>')
        w("<table>")
        w(f"<tr><th>Line (the page's introduction and description)</th><td>{e(r['why_it_matters']['text'])} "
          f"<span class='muted'>({len(r['description'])} characters)</span></td></tr>")
        w(f"<tr><th>Basis</th><td>{e(BASIS[slug])}{(' ' + e(SALT_DUCT)) if slug in SALTS else ''}</td></tr>")
        w(f"<tr><th>Approval record</th><td>{e(a['regulator'])}, {e(a['application'])} ({e(a['product'].split(', ', 1)[-1])}). "
          f"{e(a['basis'])} <a href='{e(a['source'])}'>The FDA's order</a>.</td></tr>")
        if r.get("structure_svg"):
            parts = (r.get("structure_parts") or {}).get("parts") or []
            pl = "; ".join(f"{p['label']}" for p in parts) or "none (an ionic salt: one or two atoms per ion, nothing to light)"
            w(f"<tr><th>Drawing and parts</th><td>Drawn from PubChem CID {r['cid']} by RDKit, new (the drawing guard lists "
              f"it as new). Parts by the default rules: {e(pl)}.</td></tr>")
        else:
            w("<tr><th>Drawing</th><td>No structure and no weight: a hand-modelled record. The panel reads "
              f"&ldquo;{e(r['title'])} is a mixture of related aluminum compounds, with no one formula. It has no single 2D "
              "or 3D structure, molecular weight or SMILES, so MoleculeFinder models it by hand.&rdquo;</td></tr>")
        g = r.get("ghs")
        if g:
            words = "; ".join(f"{c} {g.get('h_wording', {}).get(c, '(code alone)')}" for c in g["h_statements"])
            w(f"<tr><th>Hazard label (molecule page only)</th><td>{e(g.get('signal_word') or 'no signal word')}: {e(words)}. "
              f"From {e(', '.join(g['sources']))} through PubChem.</td></tr>")
        if r.get("ld50_mg_per_kg") is not None:
            w(f"<tr><th>LD50 (molecule page only)</th><td>{r['ld50_mg_per_kg']} mg/kg, {e(r['ld50_species'])}, "
              f"{e(r['ld50_route'])}</td></tr>")
        prods = r.get("products") or []
        lists = [c["name"] for c in r["categories"] if c["kind"] in ("product", "family", "bucket", "type", "use")]
        w(f"<tr><th>Where it turns up</th><td>{len(prods)} label page(s): "
          f"{e(', '.join(p['name'] for p in prods)) or 'none yet (see the gate below)'}. "
          f"Lists and groups: {e(', '.join(lists))}.</td></tr>")
        w("</table>")

    # ── lists ──
    w("<h2>The two new curated lists and the toothpaste additions</h2>")
    w("<p>Every entry carries a presence mark, Added (the maker adds it), with its note; the basis of each is that our "
      "DailyMed labels list it as the active (and the FDA's monograph for the class permits it). DailyMed label rows are "
      "Added by rule. A curated list never claims to be every molecule in the product.</p>")
    for key, title in (("sunscreen", "Sunscreen /in/sunscreen (new)"), ("deodorant", "Antiperspirant deodorant /in/deodorant (new)"),
                       ("toothpaste", "Toothpaste /in/toothpaste (two added)")):
        w(f"<h3>{e(title)}</h3><table><tr><th>Molecule</th><th>Mark</th><th>Note</th></tr>")
        for m in hubs[key]["molecules"]:
            new = key != "toothpaste" or m["slug"] in FLUORIDES
            w(f"<tr><td>{'<ins>' if new and key == 'toothpaste' else ''}{e(m['slug'])}{'</ins>' if new and key == 'toothpaste' else ''}</td>"
              f"<td>{e(m['presence'])}</td><td>{e(m['presence_note'])}</td></tr>")
        w("</table>")
    w(f'<div class="ba">{img(shots, "after-in-sunscreen-390", "/in/sunscreen, 390 px")}'
      f'{img(shots, "after-in-deodorant-390", "/in/deodorant, 390 px")}</div>')
    w(f'<div class="ba">{img(shots, "before-in-toothpaste-390", "/in/toothpaste before, 390 px")}'
      f'{img(shots, "after-in-toothpaste-390", "/in/toothpaste after, 390 px")}</div>')
    w(f"<p class='muted'>The two new list pages' descriptions are {e(facts['hub_desc'])}: decision 4 above.</p>")

    # ── label pages ──
    w("<h2>Three label pages, before and after</h2>")
    for slug, what in (("banana-boat-kids-clear-sunscreen-spf-65", "a sunscreen label: its four filters now link"),
                       ("colgate-total-active-prevention", "a toothpaste label: stannous fluoride now links"),
                       ("certain-dri", "a deodorant label: aluminum chlorohydrate now links")):
        w(f"<h3>/whats-in/{e(slug)}: {e(what)}</h3>")
        for wd in ("1440", "390"):
            w(f'<div class="ba">{img(shots, f"before-{slug}-{wd}", f"before, {wd} px")}'
              f'{img(shots, f"after-{slug}-{wd}", f"after, {wd} px")}</div>')

    # ── gate ──
    w("<h2>The gate: label pages that newly pass, and those that still fail</h2>")
    w(f"<p>{gate['old_passed']} of {gate['seeded']} seeded product pages passed before; {gate['passed']} pass now. "
      f"Newly passing ({len(gate['newly'])}), each because the new actives bring it to three or more of its molecules:</p><ul>")
    for s in gate["newly"]:
        w(f"<li><code>/whats-in/{e(s)}</code></li>")
    w("</ul><p>Personal-care label pages that still fail, with the gate's reason and the label's ingredients "
      "(none is held live; none was live):</p><table><tr><th>Page</th><th>Reason</th><th>Label ingredients</th></tr>")
    for f in gate["still"]:
        ing = ", ".join(n.title() for n, _ in f["ingredients"])
        w(f"<tr><td><code>{e(f['slug'])}</code></td><td>{e(f['reason'])}</td><td>{e(ing)}</td></tr>")
    w("</table><p class='muted'>Stearyl alcohol (an inactive, not in the catalog) is on four of these; it would bring Speed "
      "Stick Power and Suave to three. Desitin's actives are petrolatum and the other skin protectants. Nothing was "
      "added for them: they are not this tranche's.</p>")
    w("<h3>Live label pages whose active now links (17)</h3><p>Their titles and descriptions move: decision 1.</p>")

    # ── hazard words ──
    w("<h2>The aquatic hazard codes and their words</h2>")
    w("<p>The US standard (29 CFR 1910.1200, Appendix C) does not word the aquatic codes, which are outside OSHA's remit. "
      "The EU CLP Regulation does, for five of the eight: read from Regulation (EC) No 1272/2008, Annex III, Part 1, "
      "Table 1.2, English text (OJ L 353, 31.12.2008, through the EU Publications Office). Registry key <code>eu_clp</code>, "
      "class acknowledged (reuse authorised, source acknowledged, Commission Decision 2011/833/EU); shown with its "
      "attribution in Sources and notes and on /about/methodology; the label itself stays Reported.</p>")
    w("<table><tr><th>Code</th><th>Words (EU CLP, Annex III)</th><th>Hazard class and category</th><th>Live records</th></tr>")
    for code, v in clp.items():
        w(f"<tr><td>{e(code)}</td><td>{e(v['text'])}</td><td>{e(v['class'])}</td><td>{facts['clp_counts'].get(code, 0)}</td></tr>")
    w("</table>")
    w("<p><b>Stay codes (no allowed source words them):</b> H333 (acute toxicity, inhalation, category 5), H401 and H402 "
      "(acute aquatic categories 2 and 3). CLP does not adopt those categories, and the UN GHS text is UN copyright. "
      f"{facts['clp_records']} records gain words, {facts['clp_only']} of them words from CLP alone.</p>")
    w(f'<div class="ba">{img(shots, "after-homosalate-hazard-1440", "homosalate: H410 with its words (1440 px, the hazard section)")}'
      f'{img(shots, "after-about-methodology-390", "/about/methodology, 390 px")}</div>')

    # ── cmc ──
    w("<h2>Carboxymethyl cellulose, before and after</h2>")
    w("<p>Before: PubChem CID 24748's drawing, two small molecules (open-chain glucose and acetic acid), with three default "
      "parts on them. After: two beta-D-glucose units of the cellulose chain joined 1,4, with a carboxymethyl group "
      "(-CH2-COOH) on one unit's C6 oxygen; the linkage and the group are marked in amber; labelled &ldquo;Two units of the "
      "chain&rdquo;, with the line &ldquo;One carboxymethyl group is shown. How many the chain carries, on average per glucose "
      "unit, varies from one grade to another.&rdquo; Basis: the unit is cellulose's own (taken off the group it is cellulose's "
      "unit, stereo included, tested); the degree of substitution sets the grade (JECFA's specification for sodium "
      "carboxymethyl cellulose, INS 466, allows 0.20 to 1.50 groups per glucose unit). The drawing guard lists exactly: "
      "<code>carboxymethyl-cellulose (structure drawing): removed, replaced by its repeat unit (repeat_units.yaml "
      "`replaces`), a deliberate remake</code>; <code>(structure parts): dropped</code>; <code>(repeat unit): new</code>.</p>")
    for wd in ("1440", "390"):
        w(f'<div class="ba">{img(shots, f"before-cmc-{wd}", f"before, {wd} px")}{img(shots, f"after-cmc-{wd}", f"after, {wd} px")}</div>')
    w("<p><b>Its page text:</b> the line &ldquo;The thickener that stops ice cream growing crystals and keeps toothpaste "
      "from separating. It is cellulose made water-soluble.&rdquo; needs no word changed. Two things on the page still come "
      "from PubChem's two-fragment record: decision 5.</p>")

    # ── doors ──
    w("<h2>The three possible doors: what our data could support, and what it still lacks</h2>")
    w("<p>Not built (your ruling: a later decision). A door walks a numbered chain of four to six stops, each a molecule "
      "with a drawing, a presence mark, sentences from a comparison and, where it helps, curated parts.</p>")
    for title, body in facts["doors"]:
        w(f"<h3>{e(title)}</h3>{body}")

    # ── checks ──
    w("<h2>Checks</h2><table>")
    for k, v in facts["checks"]:
        w(f"<tr><th>{e(k)}</th><td>{v}</td></tr>")
    w("</table>")
    w("<details><summary>The 42 existing pages whose title or description changes, before and after</summary><div class='scroll'><table>"
      "<tr><th>Page</th><th>Field</th><th>Before</th><th>After</th></tr>")
    tr = json.loads((WEB / "scripts" / "frozen-text-phase-3b.json").read_text())
    for page, fields in sorted(tr.items()):
        for f in ("title", "description"):
            if f in fields:
                w(f"<tr><td><code>{e(page)}</code></td><td>{f}</td><td>{e(fields[f]['before'])}</td><td>{e(fields[f]['after'])}</td></tr>")
    w("</table></div><p class='muted'>The OpenGraph and Twitter descriptions move with the description, character for "
      "character.</p></details>")
    w("<details><summary>The 18 new pages' sweep</summary><div class='scroll'><table><tr><th>Page</th><th>Title</th><th>Phrase</th>"
      "<th>Description</th><th>Chars</th><th>Canonical, robots, dash, unique</th></tr>")
    for row in facts["sweep"]:
        w(f"<tr><td><code>{e(row['page'])}</code></td><td>{e(row['title'])}</td><td>{row['phrase_len']}</td>"
          f"<td>{e(row['desc'])}</td><td>{row['desc_len']}</td><td>{'ok' if row['canonical'] else 'MISSING'}, "
          f"{e(','.join(row['robots']) or 'index')}, {'DASH' if row['dash'] else 'no dash'}, "
          f"{'unique' if row['unique'] else 'DUPLICATE'}</td></tr>")
    w("</table></div></details>")
    w("</main></body></html>")
    OUT.write_text("\n".join(h), encoding="utf-8")
    print(OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()
