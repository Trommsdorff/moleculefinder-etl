#!/usr/bin/env python3
"""Write the phase 5 review page (build plan everyday chemistry, phase 5B, 2026-11-12).

    ./.venv/bin/python3 scripts/phase5_review.py [--shots DIR]

Reads the committed snapshot (data/snapshots) and the drawing seeds, and writes one self-contained page,
../moleculefinder-web/docs/design/phase-5-review-2026-11.html, in the site's own look. Every drawing on it is the
shipped composition: the molecule's own drawing with the amber layer under it (drawings.compose), a pair in its
shared frame, exactly what the site will show. The home page screenshots come from `--shots` (PNG or WebP files
named home-1440.* and home-390.*, taken from a local production build), embedded as data URIs.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from moleculefinder_etl.transform import drawings as D

SNAP = ROOT / "data" / "snapshots"
OUT = ROOT.parent / "moleculefinder-web" / "docs" / "design" / "phase-5-review-2026-11.html"
E = html.escape

MOLS = {json.loads(p.read_text())["slug"]: json.loads(p.read_text()) for p in (SNAP / "molecules").glob("*.json")}
PAIRS = json.loads((SNAP / "compare_drawings.json").read_text())["pairs"]
COMPS = json.loads((SNAP / "comparisons.json").read_text())
SEED = D.load_parts_seed()
CSEED = D.load_compare_seed()


def heavy(slug: str) -> int:
    from rdkit import Chem
    m = Chem.MolFromSmiles(MOLS[slug]["isomeric_smiles"])
    return sum(1 for a in m.GetAtoms() if a.GetAtomicNum() > 1)


def svg(s: str | None) -> str:
    if not s:
        return "<p class='note'>No drawing.</p>"
    return s[s.index("<svg"):] if "<svg" in s else s


def fig(drawing: str | None, cap: str, sub: str = "") -> str:
    return (f"<figure><div class='stage'>{svg(drawing)}</div><figcaption>{E(cap)}"
            + (f"<span>{E(sub)}</span>" if sub else "") + "</figcaption></figure>")


def pair_figs(slug: str) -> tuple[str, str]:
    p = PAIRS[slug]
    a, b = MOLS[p["a"]], MOLS[p["b"]]
    if p["mode"] == "aligned":
        a_svg = D.compose(a["structure_svg"], p["a_layer"]) if p.get("a_layer") else a["structure_svg"]
        if p.get("frame"):
            a_svg = D._with_frame(a_svg, p["frame"])
        b_svg = D.compose(p["b_svg"], p["b_layer"]) if p.get("b_layer") else p["b_svg"]
    else:
        a_svg = D.compose(a["structure_svg"], p["a_layer"]) if p.get("a_layer") else a["structure_svg"]
        b_svg = D.compose(b["structure_svg"], p["b_layer"]) if p.get("b_layer") else b["structure_svg"]
    return fig(a_svg, a["title"]), fig(b_svg, b["title"])


def pair_block(slug: str, note: str = "") -> str:
    p = PAIRS[slug]
    fa, fb = pair_figs(slug)
    cap = f"<p class='cap'>{E(p['caption'])}</p>" if p.get("caption") else ""
    how = "curated" if slug in (CSEED.get("curated") or {}) else "by rule"
    meta = (f"<p class='note'><code>/vs/{slug}</code> · core {p.get('core')} atoms"
            + (f" · {p.get('extra_atoms')} atoms differ" if p.get("highlight") and not p.get("stereo") else "")
            + (f" · caption {how}" if p.get("caption") else "")
            + (f" · shared frame {p['frame']}" if p.get("frame") else "") + "</p>")
    answer = COMPS.get(slug, {}).get("answer")
    ans = f"<p class='note'>Its answer line: {E(answer)}</p>" if answer and p.get("stereo") else ""
    extra = f"<p class='note'>{E(note)}</p>" if note else ""
    return f"<div class='pairbox'><div class='two'>{fa}{fb}</div>{cap}{meta}{ans}{extra}</div>"


def part_fig(slug: str, part: dict) -> str:
    m = MOLS[slug]
    return fig(D.compose(m["structure_svg"], part["layer"]), m["title"])


def shot(dirpath: Path | None, name: str) -> str:
    if not dirpath:
        return "<p class='note'>(screenshot not supplied)</p>"
    for ext, mime in (("webp", "image/webp"), ("png", "image/png"), ("jpg", "image/jpeg")):
        f = dirpath / f"{name}.{ext}"
        if f.exists():
            return f"<img alt='{E(name)}' src='data:{mime};base64,{base64.b64encode(f.read_bytes()).decode()}'>"
    return "<p class='note'>(screenshot missing)</p>"


STYLE = """
:root{--bg:#0e2233;--deep:#09161e;--panel:#12314a;--line:#244a63;--ink:#dbe9f2;--ink2:#b4cddd;--muted:#86a7bd;--accent:#7fc4e8;--amber:#e9a23b;
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;--mono:ui-monospace,"SF Mono",Menlo,monospace}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){--bg:#f6f8fa;--deep:#eef2f5;--panel:#ffffff;--line:#cdd8e0;--ink:#0e2233;--ink2:#2c4658;--muted:#557086;--accent:#1f6f9e;--amber:#9a5d00}}
:root[data-theme="dark"]{--bg:#0e2233;--deep:#09161e;--panel:#12314a;--line:#244a63;--ink:#dbe9f2;--ink2:#b4cddd;--muted:#86a7bd;--accent:#7fc4e8;--amber:#e9a23b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 var(--sans)}
main{max-width:1200px;margin:0 auto;padding:28px 16px 80px}
h1{font:650 34px/1.15 var(--mono);margin:0 0 .4rem}
h2{font:650 24px/1.25 var(--sans);margin:2.4rem 0 .8rem;padding-top:1rem;border-top:1px solid var(--line)}
h3{font:600 18px/1.3 var(--sans);margin:1.6rem 0 .5rem}
p,li{color:var(--ink2)}
a{color:var(--accent)}
.lede{font-size:18px}
.box{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:14px 18px;margin:12px 0}
.box b{color:var(--ink)}
.need{border-left:4px solid var(--amber)}
.rec{color:var(--amber);font-weight:600}
.note{font-size:14px;color:var(--muted);margin:4px 0}
.cap{font:600 16px/1.4 var(--sans);color:var(--ink);margin:8px 0 2px}
figure{margin:0}
.stage{background:#0e2233;border:1px solid #244a63;border-radius:4px;padding:6px;
 background-image:linear-gradient(#16334a 1px,transparent 1px),linear-gradient(90deg,#16334a 1px,transparent 1px);background-size:24px 24px}
.stage svg{width:100%;height:auto;max-height:260px;display:block}
figcaption{font:600 14px/1.3 var(--mono);color:var(--ink);margin:6px 0 0}
figcaption span{display:block;font:400 13px/1.4 var(--sans);color:var(--muted)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.pairbox{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:12px;margin:12px 0}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.rule{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:12px;margin:14px 0}
.rule h3{margin:0 0 4px}
.part{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:12px}
.part h4{font:600 16px/1.3 var(--sans);margin:8px 0 2px;color:var(--ink)}
.polymer .stage svg{max-height:420px}
table{border-collapse:collapse;width:100%;font-size:15px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}
.tablewrap{overflow-x:auto}
code{font:14px var(--mono);color:var(--ink)}
.shots{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,1fr);gap:14px;align-items:start}
.shots img{width:100%;height:auto;display:block;border:1px solid var(--line);border-radius:4px}
.amber{color:var(--amber);font-weight:600}
@media (max-width:760px){.two,.grid,.grid2,.shots{grid-template-columns:1fr}h1{font-size:26px}}
"""

STOP_ORDER = ["caffeine", "adenosine", "theobromine", "acetaminophen", "ibuprofen", "dextromethorphan", "doxylamine",
              "menthol", "camphor", "ethanol", "maltol", "furaneol", "sucrose", "aspartame", "sucralose", "stevioside",
              "xylitol", "erythritol", "sodium-bicarbonate", "sodium-carbonate", "ascorbic-acid", "citric-acid",
              "limonene"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", type=Path)
    ap.add_argument("--checks", type=Path, help="an HTML fragment with the check results")
    args = ap.parse_args()

    with_parts = [s for s, m in MOLS.items() if (m.get("structure_parts") or {}).get("parts")]
    n_parts = sum(len(MOLS[s]["structure_parts"]["parts"]) for s in with_parts)
    highlighted = sorted(s for s, p in PAIRS.items() if p.get("highlight") and not p.get("stereo"))
    stereo = sorted(s for s, p in PAIRS.items() if p.get("stereo"))
    plain = sorted(s for s, p in PAIRS.items() if p["mode"] == "aligned" and not p.get("highlight"))
    n_shipped = sum(1 for p in PAIRS.values() if p["mode"] == "shipped" and not p.get("highlight"))
    sample = [plain[round(i * (len(plain) - 1) / 11)] for i in range(12)]
    curated = CSEED.get("curated") or {}

    out = [(f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width,initial-scale=1'><title>Phase 5 review</title><style>{STYLE}</style>"
            "</head><body><main>")]
    out.append("<h1>Phase 5 review</h1>")
    out.append(
        "<p class='lede'>The drawing recipes' content and their first place on the site, built on branch "
        "<code>drawing-recipes-2026-11</code> in both repos on 12 November 2026 (phase 5B, on top of phase 5A's engine). "
        "Every part now has a label and a sentence; every highlighted comparison has a caption; the pairs that differ "
        "only in their arrangement in space are marked; vitamin C's line says apes and monkeys; and the home page's "
        "Compare two molecules card shows the aligned caffeine and theobromine pair with the amber mark. Nothing else "
        "on the site shows parts, pairs or repeat units yet (the door pages, phase 7; the molecule page, phase 8; the "
        "comparison page, phase 9). Every drawing below is the site's own: the molecule's shipped drawing with the "
        "amber layer under it. <b>Nothing is deployed.</b></p>")

    out.append("<h2 id='needs'>What needs you</h2><ol style='list-style:none;padding:0'>")
    needs = [
        ("1. The new writing.",
         (f"{len(SEED['defaults'])} rule labels and sentences, the door-chain molecules' {sum(len(MOLS[s]['structure_parts']['parts']) for s in STOP_ORDER if s != 'caffeine')} "
         f"curated parts and {len(PAIRS) and sum(1 for p in PAIRS.values() if p.get('caption'))} pair captions, all below. "
         "Each sentence is standard chemistry or a value the site already publishes, with its basis under it; none "
         "carries a claim word, a dash, an advice word or a completeness phrase (the build checks). "
         "<span class='rec'>Recommendation: approve, correcting any line you would word differently.</span>")),
        ("2. The two salt pairs stay aligned with nothing marked.",
         ("Calcium carbonate vs sodium bicarbonate and sodium bicarbonate vs sodium carbonate line up on the carbonate. "
         "Their difference is the ions and one hydrogen; a lone ion is never lit, so there is nothing to mark and no "
         "caption. The alternative is to hold them to their two shipped drawings. "
         "<span class='rec'>Recommendation: keep them aligned; the carbonate in one orientation still reads better.</span>")),
        ("3. Seven door-chain molecules have no parts, on purpose.",
         ("Ammonia, hydrogen peroxide, sodium hypochlorite and sodium hydroxide are one or two atoms, or ions that are "
         "never lit, so the whole molecule is the part; gluten has no structure; starch and cellulose show their "
         "two-unit chain instead. <span class='rec'>Recommendation: leave them without parts.</span>")),
    ]
    for t, body in needs:
        out.append(f"<li class='box need'><b>{E(t)}</b> {body}</li>")
    out.append("</ol>")

    out.append("<h2 id='numbers'>In numbers</h2><div class='box'><ul>"
               f"<li><b>{len(SEED['defaults'])}</b> default rules, every one with a label and a sentence; "
               f"<b>{len(with_parts)}</b> molecules show parts ({n_parts} parts in all), "
               f"<b>{sum(1 for s in with_parts if MOLS[s]['structure_parts']['parts'][0]['confidence'] == 'from_source')}</b> "
               "of them with curated parts (caffeine and the door chains' stop molecules).</li>"
               f"<li><b>{len(PAIRS)}</b> comparison pairs: <b>{len(highlighted) + len(stereo)}</b> highlighted "
               f"({len(highlighted)} where the atoms differ, {len(stereo)} where only the arrangement in space "
               f"differs), {len(plain)} aligned with nothing marked, "
               f"{n_shipped} as their two shipped drawings with nothing marked. Every "
               f"highlighted pair has a caption: {len(highlighted) + len(stereo) - len(curated)} written by the rule "
               f"from the computed difference, {len(curated)} curated.</li>"
               "<li><b>0</b> shipped structure drawings changed: all 896 byte for byte as live.</li></ul></div>")

    out.append("<h2 id='home'>The home page: Compare two molecules</h2>"
               "<p>From a local production build (database keys blanked), headless Brave, at 1440 and 390 px wide. The "
               "card is in More ways in: caffeine keeps its own drawing, theobromine is drawn on the same nine ring "
               "atoms in the same orientation, and the amber under each marks the one place they differ: caffeine's "
               "third methyl group and its nitrogen, theobromine's N-H nitrogen.</p>")
    out.append(f"<div class='shots'><figure>{shot(args.shots, 'home-1440')}<figcaption>1440 px</figcaption></figure>"
               f"<figure>{shot(args.shots, 'home-390')}<figcaption>390 px</figcaption></figure></div>")
    out.append("<h3>The card's two drawings, larger</h3>" + pair_block("caffeine-vs-theobromine"))

    out.append("<h2 id='pairs'>Every highlighted pair</h2><p>Each pair in its shared frame, the amber under both "
               "drawings, and its caption. A caption marked <i>by rule</i> is generated from the computed difference "
               "(the build's test holds it to the rule's text); a <i>curated</i> one is written by hand where the rule "
               "cannot say it truthfully, the reason beside it.</p>")
    for s in highlighted:
        out.append(pair_block(s, ("Curated: " + curated[s]) if s in curated else ""))

    out.append("<h2 id='stereo'>The pairs that differ only in their arrangement in space</h2><p>The common-core search "
               "ignores three-dimensional arrangement, so these seven pairs showed no mark. Each now carries a curated "
               "mark, chosen by a pattern in the seed that must light the same atoms on both molecules (never atom "
               "numbers). Five are one mirror-image form against the mix of both (the mix is drawn with no wedge at the "
               "marked carbon or sulfur); methylphenidate's mix spans two neighbouring carbons; isotretinoin and "
               "tretinoin differ at one double bond, and they are shown as their two shipped drawings (laid out on "
               "isotretinoin's core, tretinoin's own drawing would have come out cis, so the build now refuses any "
               "such layout), each marked from its own atom positions; betamethasone and dexamethasone at one methyl group, which points "
               "up in one and down in the other. The two salt pairs also have no differing atoms, but their "
               "difference is the ions (question 2).</p>")
    for s in stereo:
        out.append(pair_block(s))

    out.append("<h2 id='aligned'>Twelve aligned pairs with no mark</h2><p>Spread evenly through the "
               f"{len(plain)}: the core lines up, and the difference is too large to mark as one group, or (the two "
               "salt pairs) only ions. They show no caption.</p>")
    for s in sample:
        out.append(pair_block(s, PAIRS[s]["reason"]))

    out.append("<h2 id='rules'>Every default rule</h2><p>Tried in this order, most specific first; a molecule shows at "
               "most three parts. The label is the button, the sentence is shown when the part is lit, and the same "
               "sentence is reused on every molecule the rule matches, so each is written to be true of all of them. "
               "Three examples each, the best-known first.</p>")
    users: dict[str, list[str]] = {}
    for s, m in MOLS.items():
        for p in (m.get("structure_parts") or {}).get("parts") or []:
            if p["confidence"] == "computed":
                users.setdefault(p["id"], []).append(s)
    for spec in SEED["defaults"]:
        # examples a reader can see at this size: drawings of up to 60 heavy atoms, best known first
        ex = sorted((s for s in users.get(spec["id"], []) if heavy(s) <= 60),
                    key=lambda s: -(MOLS[s].get("pageviews_monthly") or 0))
        figs = "".join(part_fig(s, next(p for p in MOLS[s]["structure_parts"]["parts"] if p["id"] == spec["id"]))
                       for s in ex[:3])
        how = (f"<code>{E(spec.get('smarts') or 'group:' + spec.get('group', '') if not spec.get('rule') else 'rule: ' + spec['rule'])}</code>")
        out.append(f"<div class='rule'><h3>{E(spec['label'])}</h3><p>{E(' '.join(spec['sentence'].split()))}</p>"
                   f"<p class='note'>Basis: {E(spec['from'])} · shown on {len(users.get(spec['id'], []))} molecules · {how}</p>"
                   f"<div class='grid'>{figs}</div></div>")

    out.append("<h2 id='curated'>Curated parts: the door chains' molecules</h2><p>The molecules the six door pages "
               "lead with, plus the paired molecules of the two-molecule stops. Caffeine's three are the approved "
               "mockup's, unchanged. Each part: the drawing with that part lit, its label, its sentence and its basis.</p>")
    for s in STOP_ORDER:
        m = MOLS[s]
        cards = []
        for p in m["structure_parts"]["parts"]:
            cards.append(f"<div class='part'>{part_fig(s, p)}<h4>{E(p['label'])}</h4><p>{E(' '.join(p['sentence'].split()))}</p>"
                         f"<p class='note'>Basis: {E(' '.join((p.get('from') or '').split()))}</p></div>")
        out.append(f"<h3>{E(m['title'])}</h3><div class='grid'>{''.join(cards)}</div>")

    st, ce = MOLS["starch"]["structure_repeat_unit"], MOLS["cellulose"]["structure_repeat_unit"]
    out.append("<h2 id='polymers'>Starch and cellulose: two units of the chain</h2>")
    out.append("<p>Both drawings share one layout to the pixel (tested), so the joint is the only thing that moves. The "
               "amber marks the joint: carbon 1 of the left-hand glucose, the bridging oxygen, and carbon 4 of the "
               "right-hand glucose. The <code>*</code> at each end marks where the chain carries on.</p>")
    out.append(f"<div class='grid2 polymer'>{fig(D.compose(st['svg'], st['layer']), 'Starch', st['label'] + ', ' + st['linkage'])}"
               f"{fig(D.compose(ce['svg'], ce['layer']), 'Cellulose', ce['label'] + ', ' + ce['linkage'])}</div>")
    out.append(
        "<div class='box'><p><b>How to read the wedges and hashes.</b> A solid wedge is a bond coming toward you, out of "
        "the plane of the ring; a hashed wedge is a bond going away from you, behind it; the narrow end sits on the ring "
        "carbon that owns the stereocentre. The reference on each ring is the CH<sub>2</sub>OH on carbon 5: in both "
        "drawings it is on a solid wedge, toward you.</p><ul>"
        "<li><b>At the joint, carbon 1 to the bridging oxygen</b> (the anomeric carbon of the left-hand glucose): "
        "<span class='amber'>hashed in starch</span>, so that oxygen is on the face of the ring opposite the "
        "CH<sub>2</sub>OH: the alpha linkage (axial in the chair, down in a Haworth drawing). "
        "<span class='amber'>A solid wedge in cellulose</span>: the oxygen is on the same face as the "
        "CH<sub>2</sub>OH: the beta linkage (equatorial, up in a Haworth drawing). This is the one bond that differs "
        "between the two joints.</li>"
        "<li><b>At the joint, carbon 4 to the bridging oxygen</b> (the right-hand glucose): hashed in both. Carbon 4 is "
        "the same in starch and cellulose.</li>"
        "<li><b>At the right-hand chain end,</b> carbon 1 of the right glucose to its oxygen (the next joint along the "
        "chain): hashed in starch, a solid wedge in cellulose, the same alpha against beta, repeating along the "
        "chain.</li>"
        "<li><b>The other ring bonds</b> are the same in both and are glucose's own pattern: carbon 2's O-H hashed, "
        "carbon 3's O-H a solid wedge, carbon 4's oxygen hashed, carbon 5's CH<sub>2</sub>OH a solid wedge.</li></ul>"
        "<p class='note'>Proven in the build, not read off the picture: the alpha-glucosyl unit cut from the catalog's "
        "own maltose matches both units of starch and neither of cellulose, and its inverse at carbon 1 the reverse; "
        "starch with hydrogen for each <code>*</code> is that maltose, stereo included. A flat skeletal drawing is not a "
        "chair, so the wedges give each group's face of the ring, not its axial or equatorial position; the chair "
        "words above are what alpha and beta mean for D-glucose.</p></div>")

    out.append("<h2 id='rules-fixed'>The rules corrected, and why</h2><div class='tablewrap'><table><tr><th>Rule</th><th>Change</th></tr>")
    fixes = [
        ("Epoxide (new, before ether)", "Scopolamine's three-membered C-O-C ring read as an ether. Now an epoxide; ether skips three-membered rings."),
        ("Barbiturate ring (new, first)", "Pentobarbital's, amobarbital's, phenobarbital's and secobarbital's ring read as a plain amide."),
        ("Imide, urea (new, before amide)", "A nitrogen between two C=O groups (phenytoin, buspirone, the xanthines' ring) or a C=O between two nitrogens (carbamazepine, biotin) read as an amide. Amide now skips an imide's nitrogen."),
        ("Carbamate (new, before ester)", "N-C(=O)-O read as an ester on 12 molecules (eszopiclone, meprobamate, methocarbamol, carisoprodol, linezolid, loratadine...). Ester now skips carbamates and carbonates."),
        ("Lactone (new, before ester)", "A ring ester is named as one (vitamin C, nepetalactone, the macrolides); ester now means the open-chain kind."),
        ("Sulfonamide, guanidine (new, before amine)", "SO2-NH2 (celecoxib, furosemide, hydrochlorothiazide and nine more) and C(=N)(N)N (creatine, clonidine) read as amines. Amine now skips both."),
        ("Acetal, hemiacetal (new, before ether)", "A sugar's linking carbon, two oxygens on one carbon, read as two ethers (sucrose, the glycosides, amylose). Ether now skips an acetal carbon."),
        ("Aldehyde (narrowed)", "Formic acid's and benfotiamine's formamide H-C(=O) read as an aldehyde; the C=O carbon may no longer carry an O or N."),
        ("Phenol (narrowed)", "Maltol's O-H, on a pyranone ring RDKit calls aromatic, read as a phenol; the O-H must sit on a benzene ring."),
        ("Halogen (narrowed)", "Bleach's and cisplatin's chlorine read as an organic halogen; the halogen must be bonded to carbon."),
        ("Benzene ring and ring system", "A benzene ring fused to another ring now belongs to the ring system, so the ring system never repeats the benzene ring part (indoles, benzodiazepines, the steroids' aromatic ring)."),
    ]
    for a, b in fixes:
        out.append(f"<tr><td>{E(a)}</td><td>{E(b)}</td></tr>")
    out.append("</table></div><p class='note'>None of this changes a hub: the /in pages keep their own patterns "
               "(categories.FUNCTIONAL_GROUPS); a part that needs a narrower pattern carries its own.</p>")

    if args.checks and args.checks.exists():
        out.append("<h2 id='checks'>Checks</h2>" + args.checks.read_text())
    out.append("</main></body></html>")
    OUT.write_text("\n".join(out))
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
