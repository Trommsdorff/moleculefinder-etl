"""Write the drawing-findings review page (moleculefinder-web/docs/design/drawing-findings-review-2026-11.html) and its
pictures beside it (docs/design/drawing-findings-review-2026-11/*.jpg).

    ./.venv/bin/python3 scripts/drawing_findings_review.py <shots-dir> <facts.json> <indexnow.txt>

<shots-dir> holds PNG screenshots (Lighthouse full-page captures) named before-<slug>-<w>.png (the live site, which is
main's drawings) and after-<slug>-<w>.png (a local production build of this branch, keys blanked), w = 1440 or 390.
<facts.json> holds the session's check results; <indexnow.txt> the IndexNow dry run's changed paths, one a line.
Everything else is computed here from the committed snapshot, the seeds, `git show main:` (the drawings and notes
before) and the web repo's scripts/frozen-text-drawing-findings.json. Brief: ../TRUST-2B-DRAWING-FINDINGS-PROMPT.md.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from moleculefinder_etl.transform import drawings

SNAP = ROOT / "data" / "snapshots"
WEB = ROOT.parent / "moleculefinder-web"
NAME = "drawing-findings-review-2026-11"
OUT = WEB / "docs" / "design" / f"{NAME}.html"
SHOTS_OUT = WEB / "docs" / "design" / NAME
EIGHT = ["magnesium-glycinate", "chitin", "hyaluronic-acid", "glycogen", "maltodextrin", "inulin",
         "poly-methyl-methacrylate", "acrylonitrile-butadiene-styrene"]
MIXTURES = ["butylated-hydroxyanisole", "ivermectin", "shellac"]
DERIVED = {
    "magnesium-glycinate": "Written by hand from PubChem's record (CID 84645, two glycinate ions and Mg2+): a plain bond "
    "from one oxygen of each carboxylate, a dative arrow from each amine nitrogen. The build's check: the record's formula "
    "(C4H8MgN2O4) and charge (0); the magnesium bonded to exactly the two NH2 nitrogens and one carboxylate oxygen of "
    "each glycinate; deleting the four bonds gives back PubChem's three pieces, charges moved only on Mg (2+ to 0) and "
    "the two oxygens (1- to 0). Tested: two five-membered rings Mg-O-C(=O)-C-N; one glycinate bonded by its oxygen "
    "alone, or by both oxygens, fails; the stored layout is point-symmetric through the magnesium, every bond the same "
    "length. Two glycinates per magnesium: the record's formula and its own line (\"bound to two glycine molecules\").",
    "chitin": "Cellulose's unit with the hydroxyl on each unit's carbon 2 replaced by an acetamido group. Tested by "
    "turning each acetamido nitrogen back into the hydroxyl oxygen in place (so carbon 2 keeps its neighbours and its "
    "stereo tag means what it meant): the result is cellulose's unit exactly, stereo included.",
    "hyaluronic-acid": "beta-D-glucuronic acid (cellulose's beta-glucose with its CH2OH oxidised to COOH) joined 1->3 to "
    "N-acetyl-D-glucosamine (chitin's unit), both chain ends open (the glucuronic acid's carbon 4 and the "
    "N-acetylglucosamine's carbon 1, the two halves of the beta-1,4 joint). Tested: with the acetamido turned back to OH "
    "and the COOH to CH2OH, both rings match the beta-D-glucopyranose pattern, stereo included, the alpha one none; the "
    "middle joint runs from an anomeric carbon to the ring carbon next to the one carrying the nitrogen (carbon 3).",
    "glycogen": "Starch's unit (two alpha-D-glucose joined 1->4) with a third alpha-D-glucose joined 1->6 to carbon 6 "
    "of the first, its own carbon 4 open (a branch is a chain that carries on). Tested: the alpha-glucosyl pattern cut "
    "from the catalog's maltose matches all three units, the beta one none; cutting the branch off at the 1,6 joint gives "
    "starch's unit exactly, stereo included.",
    "maltodextrin": "Starch's own unit, character for character, labelled as a short chain. Its drawing is starch's.",
    "inulin": "Two beta-D-fructofuranose units joined 2->1. The fructofuranosyl unit is cut from the catalog's sucrose "
    "(its fructose half); it matches both units, stereo included, and its mirror at the anomeric carbon matches neither.",
    "poly-methyl-methacrylate": "The brief's SMILES, *CC(C)(C(=O)OC)CC(C)(C(=O)OC)*. The marked bond joins one unit's "
    "quaternary carbon to the next unit's CH2, the bond formed when the next monomer's double bond opens. Tested: no "
    "radical, no C=C, no stereocentre; cutting the marked bond leaves two identical units, each methyl methacrylate "
    "with its double bond opened.",
    "acrylonitrile-butadiene-styrene": "The brief's three units, *CC(C#N)*, *CC=CC* and *CC(c1ccccc1)*, side by side "
    "with no joint and no amber: the named variant separate-units. Its check (drawings.unit_monomers), at every build: "
    "each unit with its two chain ends taken off and its double bond put back is a monomer, and the three are exactly "
    "`monomers`, PubChem's own record of ABS (C=CC=C.C=CC#N.C=CC1=CC=CC=C1), which assemble holds equal to the record "
    "before it drops it. Tested against that record; a unit with a double bond in the wrong place, a missing unit, a "
    "unit that is not a vinyl or 1,4 diene unit, a marked linkage or other monomers all fail. (A 1,2 butadiene unit, "
    "*CC(C=C)*, also opens back to butadiene, as it should.)",
}


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


def rec(slug: str) -> dict:
    return json.loads((SNAP / "molecules" / f"{slug}.json").read_text())


def before(slug: str) -> dict:
    return json.loads(git("show", f"main:data/snapshots/molecules/{slug}.json"))


def new_drawing(slug: str) -> tuple[str, str]:
    r = rec(slug)
    if r.get("structure_repeat_unit"):
        u = r["structure_repeat_unit"]
        return (drawings.compose(u["svg"], u["layer"]) if u.get("layer") else u["svg"]), "repeat unit"
    return r["structure_svg"], "structure drawing (metal_bonds display structure)"


def main() -> None:
    shots, facts_path, idx_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    facts = json.loads(facts_path.read_text())
    changed = [x.strip() for x in idx_path.read_text().splitlines() if x.strip()]
    frozen = json.loads((WEB / "scripts" / "frozen-text-drawing-findings.json").read_text())["pages"]
    parts = []
    w = parts.append
    w(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Drawing findings review, 2026-11</title>
<style>
:root {{ --bg:#0e2233; --panel:#132c40; --ink:#e6f0f7; --muted:#9db3c4; --accent:#7fc4e8; --amber:#e9a23b; --line:#24445c; }}
@media (prefers-color-scheme: light) {{ :root:not([data-theme="dark"]) {{ --bg:#f6f8fa; --panel:#fff; --ink:#132433; --muted:#4d6475; --accent:#1d6fa3; --amber:#a5620a; --line:#d4dde4; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 system-ui,-apple-system,sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:24px 20px 80px; }}
h1 {{ font-family:ui-monospace,Menlo,monospace; font-size:28px; }} h2 {{ margin-top:48px; border-top:1px solid var(--line); padding-top:24px; }}
.muted {{ color:var(--muted); }} a {{ color:var(--accent); }}
.box {{ background:var(--panel); border:1px solid var(--line); border-left:4px solid var(--amber); border-radius:6px; padding:14px 18px; margin:14px 0; }}
.big {{ background:#0e2233; border-radius:6px; padding:12px; margin:12px 0; overflow-x:auto; }}
.svg svg {{ background:#0e2233; border-radius:4px; display:block; }}
.row {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; align-items:start; }}
figure {{ margin:0; }} figure img {{ width:100%; border:1px solid var(--line); border-radius:4px; }}
figcaption {{ font-size:13px; color:var(--muted); margin-bottom:6px; }}
table {{ border-collapse:collapse; width:100%; font-size:14px; }} td, th {{ border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }}
code, .mono {{ font-family:ui-monospace,Menlo,monospace; font-size:13px; }}
pre {{ white-space:pre-wrap; font:13px/1.5 ui-monospace,Menlo,monospace; background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:10px 12px; }}
</style></head><body><main>
<h1>Drawing findings, 2026-11</h1>
<p class="muted">Brief <code>TRUST-2B-DRAWING-FINDINGS-PROMPT.md</code> (Cowork's rulings, Garrett's word, 2026-11-27): what the
drawing-truth review's first run found (<code>trust-reports/drawings-2026-11-27.md</code>, 42 records in 3 classes). Built on
branch <code>drawing-findings-2026-11</code> in both repos. <b>Not merged, not pushed, not deployed.</b> ETL {e(facts['tips']['etl'])};
web {e(facts['tips']['web'])}.</p>
""")
    # ── the stops first
    rows = "".join(f"<tr><td><code>{e(p)}</code></td><td>{e(f)}</td><td>{e(json.dumps(v['before'], ensure_ascii=False)[:220])}</td>"
                   f"<td>{e(json.dumps(v['after'], ensure_ascii=False)[:220])}</td></tr>"
                   for p, fs in frozen.items() for f, v in fs.items() if f in ("title", "description", "faq"))
    w(f"""<h2>Stopped: what needs a ruling before a deploy</h2>
<div class="box"><b>1. Frozen text moves (38 fields on 11 pages).</b> Following the carboxymethyl cellulose and simeticone
precedent, the six polymers and ABS drop everything PubChem computed from the stand-in molecule, including the functional
groups, elements and weight their hub and board memberships come from. So six hub <b>titles</b> lose a count
(Alcohols 253 to 248, Ethers 224 to 219, Amides 148 to 146, Aromatics 390 to 389, Carboxylic Acids 162 to 161, Esters 91 to 90),
those hubs' and /in/element-nitrogen's (477 to 474) and /in/over-1000-g-mol's (28 to 27) descriptions move with them,
/best/biggest's description names a new leader (Inulin at 6,179 g/mol, the weight of one 38-sugar chain, gives way to Insulin
at 5,808), hyaluronic acid's description loses the stand-in's formula ("Hyaluronic acid (C28H44N2O23, 777 g/mol) is a compound
..." becomes "Hyaluronic acid is a compound ..."), and glucose vs glycogen loses its frozen FAQ "Is Glucose bigger than
Glycogen?" (glycogen no longer has a weight). Per the brief I stopped here: nothing is allowed in
<code>frozen-text.mjs</code>; every before and after is in <code>scripts/frozen-text-drawing-findings.json</code>, and the
web's /vs frozen-strings test is red on the build for that one FAQ.
<br><b>Recommendation:</b> accept them as a recorded exception, as the care tranche's hub counts were: each is the truth
replacing a number taken from a molecule that is not the substance (the 2026-12-08 read is unaffected for the molecule
pages, whose titles do not move). <b>Alternative</b> if counts must hold until after 2026-12-08: a small mechanism that takes
the functional groups and elements from the repeat unit (each unit carries the same groups the stand-in did), which keeps
every hub count; the board description, hyaluronic acid's description and the glycogen FAQ would still move.
Also, the pair text of glucose vs glycogen (not frozen) still says "glycogen's listed formula and weight represent a fragment";
it needs a rewrite if the change is accepted. Not edited here.</div>
<details><summary>The titles, descriptions and FAQ before and after (og and twitter copies follow the description)</summary>
<table><tr><th>page</th><th>field</th><th>before</th><th>after</th></tr>{rows}</table></details>
<div class="box"><b>2. Shellac: held, not allowlisted and not noted.</b> The ruling says the two drawn pieces are acids shellac
is built from. The record's first piece is shellolic acid's skeleton (C15H20O6, PubChem names it
(2R,6S,7R,10S)-10-hydroxy-6-(hydroxymethyl)-6-methyltricyclo[5.3.1.0<sup>1,5</sup>]undec-8-ene-2,8-dicarboxylic acid), but the
second is <b>9,10,15-trihydroxypentadecanoic acid</b> (C15H30O5), not shellac's main acid, aleuritic acid
(9,10,16-trihydroxyhexadecanoic acid, C16H32O5): one carbon short. The line "two of the acids shellac is built from" would not
be true of it. <b>Recommendation:</b> a line that names what the record draws: "The drawing shows the two acids PubChem's record
gives for it, shellolic acid and 9,10,15-trihydroxypentadecanoic acid, not a molecule of shellac; shellac's main acid, aleuritic
acid, has one carbon more than the second." Or draw nothing (the panel). The review keeps finding it until a ruling.</div>
<div class="box"><b>3. Smaller points to read.</b> (a) Magnesium glycinate's part layer (the amine on both nitrogens) is dropped:
the amine pattern <code>[NX3;H2,H1]</code> does not match a nitrogen that also bonds the magnesium. The page loses the "amine"
chip; the /in/amines hub still lists it (it reads PubChem's structure). (b) RDKit draws two small dots under the "Mg": it counts the
two dative bonds in magnesium's valence and gives it two radical electrons. Chlorophyll a's live drawing has the same two dots;
the shipped rule is kept here, and a fix would be a deliberate recipe change that touches chlorophyll a too. (c) ABS's three
units sit small in the 4:3 panel at 1440 (a row is wide and short); a tighter row is a layout-only change if wanted.
(d) Sodium hyaluronate (UNII YSE9PPT4TH) reached hyaluronic acid by the InChIKey the record no longer carries; it is ruled a form
in <code>unii_aliases.yaml</code>, so CeraVe Hydrating Mineral Sunscreen SPF 30 and EltaMD UV Clear keep the link (only the match
kind moves, skeleton to alias). (e) Unrelated, already live: magnesium glycinate's "Also called" ends "Magnesium diglyci.",
a truncated name.</div>
""")
    # ── the eight drawings
    w("<h2>The eight new drawings</h2>")
    for slug in EIGHT:
        r, b = rec(slug), before(slug)
        svg, _ = new_drawing(slug)
        u = r.get("structure_repeat_unit") or {}
        line = u.get("line") or (r.get("structure_display") or {}).get("line")
        w(f'<h3 id="{e(slug)}">{e(r["title"])} <span class="muted mono">/m/{e(slug)}</span></h3>')
        w(f'<div class="big">{svg_at(svg, 960)}</div>')
        if u:
            ks = [u.get("linkage")] + [a["linkage"] for a in u.get("also") or []]
            ks = [k for k in ks if k]
            w(f'<p><b>{e(u["label"])}</b>; {("linkage" + ("s" if len(ks) > 1 else "") + " marked in amber: " + ", ".join(ks)) if ks else "no linkage marked (separate units)"}; '
              f'units {u["units"]}. <span class="muted">Replaces:</span> {e(u["replaces"])}</p>')
        w(f'<p><span class="muted">The page\'s new line:</span> {e(line)}</p>')
        w(f'<p class="muted">How it was derived and tested: {e(DERIVED[slug])}</p>')
        w(f'<details><summary>Before: the drawing PubChem\'s record gave (live today)</summary><div class="big">{svg_at(b.get("structure_svg"), 600)}</div>'
          f'<p class="mono muted">{e((b.get("isomeric_smiles") or "")[:400])}</p></details>')
        w('<div class="row">' + "".join(fig(shots, f"{t}-{slug}-{px}", f"{t.title()}, {px} px", 1100 if px == 1440 else 1500)
                                        for t in ("before", "after") for px in (1440, 390)) + "</div>")
    # ── the mixtures
    w("<h2>The three kept mixtures' notes</h2><table><tr><th>record</th><th>before (the 2D drawing's note)</th><th>after</th></tr>")
    for slug in MIXTURES:
        r = rec(slug)
        after = (r.get("structure_note") or {}).get("line")
        w(f'<tr><td>{e(r["title"])}</td><td class="muted">no note: "PubChem structure, drawn by RDKit" only</td>'
          f'<td>{e(after) if after else "<i>held, unchanged (see stop 2)</i>"}</td></tr>')
    w("</table><p class=\"muted\">BHA and ivermectin also join the review's <code>kept-as-drawn</code> list (dated 2026-11-27). "
      "Ivermectin's proportions are the FDA label's (DailyMed, public domain: Stromectol, \"at least 90% ... and less than 10% ...\").</p>")
    # ── A, the allowlist
    rulings = yaml.safe_load((ROOT / "moleculefinder_etl" / "review" / "drawings_rulings.yaml").read_text())
    salts = sorted(k for k, v in rulings["allow"]["salts-as-ions"]["records"].items() if isinstance(v, dict))
    w(f"<h2>A. The 31 salts kept as their ions</h2><p>Added to <code>salts-as-ions</code> under a <code>later:</code> ruling dated "
      f"2026-11-27, each with the reason \"an ionic salt of a discrete organic ion, drawn as its ions\": {e(', '.join(salts))}.</p>")
    # ── the guard and the checks
    guard = []
    for s in ("chitin", "hyaluronic-acid", "glycogen", "maltodextrin", "inulin", "poly-methyl-methacrylate",
              "acrylonitrile-butadiene-styrene"):
        guard += [f"{s} (structure drawing): removed, replaced by its repeat unit (repeat_units.yaml `replaces`), a deliberate remake",
                  f"{s} (structure parts): dropped, its SMILES changed, its drawing was replaced by its repeat unit",
                  f"{s} (repeat unit): new, added in repeat_units.yaml"]
    guard += ["magnesium-glycinate (structure drawing): redrawn, its display structure changed (metal_bonds: drawn with the Mg bonds)",
              "magnesium-glycinate (structure parts): dropped, its display structure changed, its drawing changed",
              "glucose-vs-glycogen (compare drawing): remade, glycogen's SMILES changed",
              "maltodextrin-vs-starch (compare drawing): remade, maltodextrin's SMILES changed, maltodextrin's drawing changed"]
    w(f"<h2>The drawing guard's list (25, nothing stopped)</h2><pre>{e(chr(10).join(guard))}</pre>"
      f"<p><b>Drawings before</b> (main): {e(facts['drawings_before'])}.<br><b>After</b> (the next weekly run): {e(facts['drawings_after'])}.</p>"
      "<p class=\"muted\">The two /vs pairs are now shipped with no pair drawing (one side has none), as maltodextrin vs starch "
      "already was; no door names a drawing of the eight and no week books one.</p>")
    w("<h2>Checks</h2><ul>" + "".join(f"<li>{e(c)}</li>" for c in facts["checks"]) + "</ul>")
    w(f"<h2>IndexNow dry run: {len(changed)} changed</h2><p class=\"mono\">{e(' '.join(changed))}</p>")
    w("</main></body></html>")
    OUT.write_text("\n".join(parts))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB), pictures in {SHOTS_OUT}")


if __name__ == "__main__":
    main()
