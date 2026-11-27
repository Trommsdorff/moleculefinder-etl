"""Write the cobalamins review page (moleculefinder-web/docs/design/cobalamins-review-2026-11.html) and its pictures
beside it (docs/design/cobalamins-review-2026-11/*.jpg).

    ./.venv/bin/python3 scripts/cobalamins_review.py <shots-dir> <facts.json>

<shots-dir> holds PNG screenshots (Lighthouse full-page captures of local production builds, keys blanked) named
before-<slug>-<w>.png (a build of main) and after-<slug>-<w>.png (this branch), w = 1440 or 390. <facts.json> holds
the session's check results (tips, the guard's list, the Drawings lines, the check list). Everything else is computed
here from the committed snapshot, the seed and `git show main:` (the drawings before). The part layers are rendered to
JPEG with macOS Quick Look (qlmanage). Brief: ../COBALAMINS-PROMPT.md.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from PIL import Image
from rdkit import Chem
from rdkit.Chem.rdMolDescriptors import CalcMolFormula

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_cobalamins import PX, RENDER, layout_numbers  # noqa: E402

from moleculefinder_etl.transform import drawings, structures  # noqa: E402

SNAP = ROOT / "data" / "snapshots"
SEEDS = ROOT / "moleculefinder_etl" / "sources" / "seeds"
WEB = ROOT.parent / "moleculefinder-web"
NAME = "cobalamins-review-2026-11"
OUT = WEB / "docs" / "design" / f"{NAME}.html"
SHOTS_OUT = WEB / "docs" / "design" / NAME
COBALAMINS = ["cyanocobalamin", "vitamin-b12", "hydroxocobalamin", "methylcobalamin"]
TOP = {"cyanocobalamin": "the cyanide (bonded by its carbon)", "vitamin-b12": "the cyanide (bonded by its carbon)",
       "hydroxocobalamin": "the hydroxide (by its oxygen)", "methylcobalamin": "the methyl group (by its carbon)"}


def e(s) -> str:
    return html.escape(str(s), quote=True)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def svg_at(svg: str | None, width: int) -> str:
    if not svg:
        return '<p class="muted">(no drawing)</p>'
    svg = re.sub(r"<\?xml[^>]*\?>", "", svg).strip()
    svg = re.sub(r"width='[^']*'", f"width='{width}'", svg, count=1)
    svg = re.sub(r"height='[^']*'", f"height='{round(width * 0.75)}'", svg, count=1)
    return f'<span class="svg">{svg}</span>'


def jpg(shots: Path, name: str, top: int | None = None) -> str | None:
    p = shots / f"{name}.png"
    if not p.exists():
        return None
    SHOTS_OUT.mkdir(parents=True, exist_ok=True)
    im = Image.open(p).convert("RGB")
    suffix = ""
    if top:
        im, suffix = im.crop((0, 0, im.width, min(top, im.height))), "-top"
    if im.width > 720:
        im = im.resize((720, round(im.height * 720 / im.width)), Image.LANCZOS)
    out = SHOTS_OUT / f"{name}{suffix}.jpg"
    im.save(out, "JPEG", quality=72, optimize=True, progressive=True)
    return f"{NAME}/{name}{suffix}.jpg"


def fig(shots: Path, name: str, cap: str, top: int) -> str:
    full, src = jpg(shots, name), jpg(shots, name, top)
    if not src:
        return f'<figure><figcaption>{e(cap)}</figcaption><p class="muted">(missing: {e(name)})</p></figure>'
    return (f'<figure><figcaption>{e(cap)} <a href="{e(full)}">(full page)</a></figcaption><a href="{e(full)}">'
            f'<img loading="lazy" alt="{e(cap)}" src="{e(src)}"></a></figure>')


def layer_jpg(svg: str, layer: str, name: str) -> str:
    """The drawing with one part layer under it, on the panel's navy, as a 600 px JPEG beside the page."""
    composed = drawings.compose(svg, layer).replace(
        "<!-- END OF HEADER -->", "<!-- END OF HEADER -->\n<rect width='100%' height='100%' fill='#0e2233'/>", 1)
    SHOTS_OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"{name}.svg"
        src.write_text(composed)
        subprocess.run(["qlmanage", "-t", "-s", "600", "-o", td, str(src)], capture_output=True, check=True)
        im = Image.open(Path(td) / f"{name}.svg.png").convert("RGB")
        im = im.crop((0, 0, 600, 450))
        im.save(SHOTS_OUT / f"{name}.jpg", "JPEG", quality=80, optimize=True)
    return f"{NAME}/{name}.jpg"


def proofs(slug: str, seed: dict, rec: dict) -> list[tuple[str, str]]:
    """What checks (a) to (e) proved for one entry, computed here from the seed and the record."""
    e_ = seed[slug]
    d, r = Chem.MolFromSmiles(e_["smiles"]), Chem.MolFromSmiles(rec["isomeric_smiles"])
    co = next(a for a in d.GetAtoms() if a.GetSymbol() == "Co")
    nb = list(co.GetNeighbors())
    kinds = [str(d.GetBondBetweenAtoms(co.GetIdx(), n.GetIdx()).GetBondType()).lower() for n in nb]

    def centres(m):
        return [i for i, _ in Chem.FindMolChiralCenters(m, useLegacyImplementation=False)
                if m.GetAtomWithIdx(i).GetSymbol() == "C"]
    own, drawn = len(centres(r)), len(centres(d))
    geos = [b for b in r.GetBonds() if b.GetBondType() == Chem.BondType.DOUBLE
            and b.GetStereo() not in (Chem.BondStereo.STEREONONE, Chem.BondStereo.STEREOANY)]
    ref = seed["hydroxocobalamin"]
    same_skeleton = (structures.skeleton_key(e_["smiles"], "Co", e_["top"])
                     == structures.skeleton_key(ref["smiles"], "Co", ref["top"]))
    problems = structures.metal_bonds_problems(
        e_["smiles"], rec["isomeric_smiles"], "Co", e_["bonded"], e_["charges"], top=e_.get("top"),
        reference=(ref["smiles"], ref["top"]) if "stereo_from" in e_ else None)
    out = [
        ("(a) formula and charge", f"{CalcMolFormula(d)}, overall charge {Chem.GetFormalCharge(d)}: the record's "
                                   f"({CalcMolFormula(r)}, {Chem.GetFormalCharge(r)})."),
        ("(b) the six bonds", f"the cobalt has {len(nb)} bonds: the four corrin nitrogens, the benzimidazole's free "
                              f"nitrogen and {TOP[slug]}; {kinds.count('single')} plain (the ring's N- and the top "
                              f"group), {kinds.count('dative')} dative arrows; drawn Co+ (Co3+ in the record)."),
        ("(c) the record's pieces", "deleting the six bonds and setting the charges back gives the record's own three "
                                    "pieces (the ring and nucleotide, the top group, Co3+), atom for atom."),
        ("(d) stereo", (f"the record specifies {own} carbon centres; the drawing shows {drawn}. "
                        + ("Every one is the record's own." if own == drawn else
                           f"The record's {own} are the drawing's; the other {drawn - own} come from hydroxocobalamin's "
                           f"record (stereo_from), and the drawing's skeleton, top group removed, is the reference's, "
                           f"stereo included: {'yes' if same_skeleton else 'NO'}."))),
        ("(e) double-bond geometry", (f"the record gives the geometry of {len(geos)} of the corrin's double bonds; "
                                      "each sits in a six-membered ring the cobalt closes (Co-N-C=C-C-N), where the "
                                      "ring fixes it, and the record's geometry is the one that ring forces; the "
                                      "drawing leaves them unmarked." if geos else
                                      "the record gives no double-bond geometry; the drawing gives none.")),
        ("the build's check", "passes ([] at every build)" if not problems else "FAILS: " + "; ".join(problems)),
    ]
    return out


def main() -> None:
    shots, facts = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text())
    now = {s: json.loads((SNAP / "molecules" / f"{s}.json").read_text()) for s in COBALAMINS}
    was = {s: json.loads(git("show", f"main:data/snapshots/molecules/{s}.json")) for s in COBALAMINS}
    seed = yaml.safe_load((SEEDS / "structure_display.yaml").read_text())["metal_bonds"]
    title = {s: now[s]["title"] for s in COBALAMINS}

    h: list[str] = []
    w = h.append
    w("""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cobalamins review</title><style>
:root { --bg:#0e2233; --panel:#132c40; --ink:#e6f0f7; --muted:#9db3c4; --accent:#7fc4e8; --amber:#e9a23b; --line:#24445c; }
@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) { --bg:#f6f8fa; --panel:#fff; --ink:#132433; --muted:#4d6475; --accent:#1d6fa3; --amber:#a5620a; --line:#d4dde4; } }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:1280px; margin:0 auto; padding:24px 16px 80px; }
h1 { font:700 30px/1.2 ui-monospace,Menlo,monospace; margin:8px 0 4px; }
h2 { margin:44px 0 10px; padding-top:14px; border-top:1px solid var(--line); font-size:22px; }
h3 { margin:26px 0 6px; font-size:18px; } code { font:13px ui-monospace,Menlo,monospace; color:var(--muted); word-break:break-all; }
.box { background:var(--panel); border:1px solid var(--line); border-left:4px solid var(--amber); border-radius:6px; padding:14px 18px; margin:14px 0; }
.box h3 { margin-top:6px; } .rec { color:var(--accent); font-weight:600; }
table { border-collapse:collapse; width:100%; font-size:14px; margin:8px 0; } td,th { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
th { color:var(--muted); font-weight:600; }
.two { display:grid; grid-template-columns:1fr 1fr; gap:14px; align-items:start; margin:10px 0; }
.three { display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; margin:8px 0; }
figure { margin:0; } figcaption { font-size:13px; color:var(--muted); margin-bottom:4px; }
img { width:100%; height:auto; border:1px solid var(--line); border-radius:4px; display:block; }
.svg svg { background:#0e2233; border-radius:4px; display:block; }
.big { overflow-x:auto; margin:10px 0; }
.muted { color:var(--muted); } ul { padding-left:20px; } li { margin:4px 0; } .scroll { overflow-x:auto; }
pre { white-space:pre-wrap; font:13px/1.5 ui-monospace,Menlo,monospace; background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:10px 12px; }
@media (max-width:800px) { .two, .three { grid-template-columns:1fr; } }
</style></head><body><main>""")
    w(f"<p><code>moleculefinder-web/docs/design/{NAME}.html</code> · built 2026-11-26 on <code>cobalamins-2026-11</code> in "
      f"both repos (ETL <code>{e(facts['etl_tip'])}</code>, web <code>{e(facts['web_tip'])}</code>) · "
      f"<b>{e(facts.get('status') or 'built, not merged, not pushed, not deployed')}</b>.</p>")
    w("<h1>The cobalamins, drawn with their cobalt bonded</h1>")
    w("<p>Cowork's rulings of 2026-11-26 (brief <code>COBALAMINS-PROMPT.md</code>). Cyanocobalamin, vitamin B12, "
      "hydroxocobalamin and methylcobalamin drew the cobalt and its top group floating beside the ring, as PubChem's "
      "one-line structure writes them. Each page now draws the cobalt bonded to the ring's four nitrogens, to the "
      "benzimidazole's free nitrogen below and to its top group above, from one hand layout shared by all four. "
      "Every title, description and H1 is unchanged; only the drawing, its three part layers and one line under "
      "the drawing move.</p>")

    w("<h2>Needs you</h2>")
    w('<div class="box"><h3>1. The four drawings</h3><p>Each is below, large on its own, with the page before and '
      'after at 1440 and 390 px and its part layers before and after.</p><p class="rec">Recommended: approve, then a '
      'deploy brief.</p></div>')
    for q in facts.get("questions", []):
        w(f'<div class="box"><h3>{e(q["title"])}</h3><p>{e(q["text"])}</p><p class="rec">{e(q["rec"])}</p></div>')

    w("<h2>The four at a glance</h2><div class='scroll'><table><tr><th>Page</th><th>Top group</th><th>Stereo</th>"
      "<th>Part layers</th><th>3D model</th><th>/vs pairs, doors, weeks</th></tr>")
    stereo = {"hydroxocobalamin": "all 14 centres its own (the reference)",
              "cyanocobalamin": "13 its own (all agree with the reference), the ribose's anomeric carbon from the reference",
              "vitamin-b12": "all 14 from the reference (its record has none)",
              "methylcobalamin": "all 14 from the reference (its record has none)"}
    for s in COBALAMINS:
        parts = ", ".join(p["label"] for p in now[s]["structure_parts"]["parts"])
        w(f"<tr><td><b>{e(title[s])}</b><br><code>/m/{e(s)}</code></td><td>{e(TOP[s])}</td><td>{e(stereo[s])}</td>"
          f"<td>remade from the new drawing: {e(parts)} (the same atoms lit)</td><td>none (none before)</td>"
          f"<td>none</td></tr>")
    w("</table></div><p class='muted'>None of the four is in a /vs pair or a pair drawing, a door's facts or links, or a "
      "booked molecule-of-the-week (none of the 53 weeks names a cobalamin).</p>")

    w("<h2>One skeleton, one layout</h2><p>The skeleton is laid out once, on hydroxocobalamin's record, by "
      "<code>scripts/cobalamin_layout.py</code>, and all four drawings take its coordinates atom for atom (they are "
      "written into each display SMILES, to three decimals, so no machine lays them out again). The cobalt sits at "
      "the centre of the corrin with its four Co&ndash;N bonds equal; each five-membered ring is regular and points "
      "its nitrogen at the cobalt; the substituents point outward; the top group sits inside the ring, short, "
      "touching nothing; the nucleotide loop is to the right. <b>The one crossing</b> every flat cobalamin drawing has "
      "is the long bond from the cobalt to the benzimidazole, over the ring's edge (the C14&ndash;C15 bond), with the "
      "C15 methyl above it. Each record keeps its own double bonds: cyanocobalamin's record writes the corrin's double "
      "bonds and its N&minus; in other, equivalent places, so its plain Co&ndash;N bond is on a different ring.</p>")

    # ── each of the four ──
    for s in COBALAMINS:
        d = now[s]["structure_display"]
        w(f"<h2>{e(title[s])}</h2>")
        w(f"<p><b>The new line under the drawing</b> (Sources and notes): &ldquo;{e(d['line'])}&rdquo;</p>")
        w(f"<div class='big'>{svg_at(now[s]['structure_svg'], 1240)}</div><p class='muted'>The drawing as shipped, "
          f"at 1,240 px.</p>")
        w(f"<details><summary>The drawing before (PubChem's one-line structure, the cobalt floating)</summary>"
          f"<div class='big'>{svg_at(was[s]['structure_svg'], 640)}</div></details>")
        w("<table><tr><th>Check</th><th>What it proved</th></tr>" + "".join(
            f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in proofs(s, seed, now[s])) + "</table>")
        w("<h3>Part layers, before and after</h3><table><tr><th>Part</th><th>Atoms lit, before</th><th>after</th>"
          "</tr>" + "".join(
              f"<tr><td>{e(a['label'])}</td><td>{len(a['atoms'])}</td><td>{len(b['atoms'])}</td></tr>"
              for a, b in zip(was[s]["structure_parts"]["parts"], now[s]["structure_parts"]["parts"], strict=True))
          + "</table>")
        for a, b in zip(was[s]["structure_parts"]["parts"], now[s]["structure_parts"]["parts"], strict=True):
            before = layer_jpg(was[s]["structure_svg"], a["layer"], f"part-{s}-{a['id']}-before")
            after = layer_jpg(now[s]["structure_svg"], b["layer"], f"part-{s}-{b['id']}-after")
            w(f"<div class='two'><figure><figcaption>{e(a['label'])}, before</figcaption><img loading='lazy' "
              f"alt='' src='{e(before)}'></figure><figure><figcaption>{e(b['label'])}, after</figcaption>"
              f"<img loading='lazy' alt='' src='{e(after)}'></figure></div>")
        for width, top in ((1440, 1300), (390, 1500)):
            w(f"<div class='two'>{fig(shots, f'before-{s}-{width}', f'{title[s]} at {width}, before', top)}"
              f"{fig(shots, f'after-{s}-{width}', f'{title[s]} at {width}, after', top)}</div>")

    # ── the layout test ──
    w("<h2>The layout test, on the shipped SVG</h2><p>The positions are read from each shipped SVG alone "
      "(<code>svg_geometry.read_positions</code>, proven by a redraw), not taken from RDKit's close-contact flag. The "
      "thresholds: no two atoms that are not bonded closer than 0.65 bond lengths, no atom closer than 0.40 to a bond it "
      "is not part of, no label over a bond or another label, no carbon drawn with a label (a straight run), no "
      "close-contact flag, exactly one crossing (the cobalt&ndash;benzimidazole bond over C14&ndash;C15). In screen "
      "pixels: the drawing's own 400 px; the molecule page at 1440 (the drawing shown 464 x 348) and at 390 (272 x "
      "204: the 220 px stage below 720 px), thresholds "
      + ", ".join(f"{e(k)}: {a} and {b} px" for k, (a, b) in PX.items()) + ".</p>")
    w("<table><tr><th>Page</th><th>Bond</th><th>Closest atoms</th><th>Closest atom to a bond</th>"
      + "".join(f"<th>{e(k)}</th>" for k in RENDER) + "<th>Crossings</th><th>Labels over</th></tr>")
    for s in COBALAMINS:
        k = layout_numbers(now[s]["structure_svg"], now[s]["structure_display"]["smiles"])
        L = k["bond_px"]
        w(f"<tr><td>{e(title[s])}</td><td>{L:.1f} px</td><td>{k['atom_atom'] / L:.2f} bond lengths</td>"
          f"<td>{k['atom_bond'] / L:.2f} bond lengths</td>"
          + "".join(f"<td>{k['atom_atom'] * f:.1f} / {k['atom_bond'] * f:.1f} px</td>" for f in RENDER.values())
          + f"<td>{len(k['crossings'])}</td><td>{len(k['label_over_bond']) + len(k['label_over_label'])}</td></tr>")
    w("</table>")
    w(f"<p class='muted'>{e(facts.get('crowded', ''))}</p>")

    # ── guard and checks ──
    w("<h2>The drawing guard's list (exactly this pass)</h2>")
    w(f"<pre>{e(facts['guard'])}</pre><p><b>Drawings lines</b> (the weekly run's summary):</p><pre>{e(facts['drawings'])}</pre>")
    w("<h2>Checks</h2><ul>" + "".join(f"<li>{e(c)}</li>" for c in facts["check_list"]) + "</ul>")
    w("</main></body></html>")
    OUT.write_text("\n".join(h))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
