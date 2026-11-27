"""Write the wrong-drawings review page (moleculefinder-web/docs/design/wrong-drawings-review-2026-11.html) and its
screenshots beside it (docs/design/wrong-drawings-review-2026-11/*.jpg, plus the cobalamin prototype as an SVG).

    ./.venv/bin/python3 scripts/wrong_drawings_review.py <shots-dir> <facts.json>

<shots-dir> holds PNG screenshots (Lighthouse full-page captures of local production builds, keys blanked) named
before-<slug>-<w>.png (a build of main) and after-<slug>-<w>.png (this branch), w = 1440 or 390, and the optional
cobalamin-prototype.svg. <facts.json> holds the session's check results. Everything else is read from the committed
snapshot, the seeds and `git show main:` (the drawings before). Brief: ../EXTENDED-SOLIDS-2-PROMPT.md.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "data" / "snapshots"
SEEDS = ROOT / "moleculefinder_etl" / "sources" / "seeds"
WEB = ROOT.parent / "moleculefinder-web"
NAME = "wrong-drawings-review-2026-11"
OUT = WEB / "docs" / "design" / f"{NAME}.html"
SHOTS_OUT = WEB / "docs" / "design" / NAME

LATTICES = ["calcium-oxide", "magnesium-oxide", "silicon-carbide", "tungsten-carbide"]
METALS = ["cisplatin", "sodium-ferrocyanide", "chromium-iii-picolinate", "thiomersal", "chlorophyll-a"]
COBALAMINS = ["cyanocobalamin", "vitamin-b12", "hydroxocobalamin", "methylcobalamin"]
ALL = [*LATTICES, "simeticone", *METALS, *COBALAMINS]


def e(s) -> str:
    return html.escape(str(s), quote=True)


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def svg_at(svg: str | None, width: int) -> str:
    """A drawing inline at `width` px (its viewBox kept), on the panel's navy."""
    if not svg:
        return '<p class="muted">(no drawing)</p>'
    svg = re.sub(r"<\?xml[^>]*\?>", "", svg).strip()
    h = round(width * 0.75)
    svg = re.sub(r"width='[^']*'", f"width='{width}'", svg, count=1)
    svg = re.sub(r"height='[^']*'", f"height='{h}'", svg, count=1)
    return f'<span class="svg">{svg}</span>'


def jpg(shots: Path, name: str, top: int | None = None) -> str | None:
    """The capture as JPEG beside the page (the 1440 ones at half size); with `top`, only the first `top` pixels."""
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


def main() -> None:
    shots, facts = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text())
    now = {s: json.loads((SNAP / "molecules" / f"{s}.json").read_text()) for s in ALL}
    was = {s: json.loads(git("show", f"main:data/snapshots/molecules/{s}.json")) for s in ALL}
    none_seed = yaml.safe_load((SEEDS / "structure_none.yaml").read_text())["molecules"]
    metal_seed = yaml.safe_load((SEEDS / "structure_display.yaml").read_text())["metal_bonds"]
    unit_seed = yaml.safe_load((SEEDS / "repeat_units.yaml").read_text())["units"]["simeticone"]
    title = {s: now[s]["title"] for s in ALL}

    h: list[str] = []
    w = h.append
    w("""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wrong drawings review</title><style>
:root { --bg:#0e2233; --panel:#132c40; --ink:#e6f0f7; --muted:#9db3c4; --accent:#7fc4e8; --amber:#e9a23b; --line:#24445c; --del:#ff7a72; --ins:#8fd982; }
@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) { --bg:#f6f8fa; --panel:#fff; --ink:#132433; --muted:#4d6475; --accent:#1d6fa3; --amber:#a5620a; --line:#d4dde4; --del:#b42318; --ins:#1a7f37; } }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:1180px; margin:0 auto; padding:24px 16px 80px; }
h1 { font:700 30px/1.2 ui-monospace,Menlo,monospace; margin:8px 0 4px; }
h2 { margin:44px 0 10px; padding-top:14px; border-top:1px solid var(--line); font-size:22px; }
h3 { margin:26px 0 6px; font-size:18px; } code { font:13px ui-monospace,Menlo,monospace; color:var(--muted); word-break:break-all; }
.box { background:var(--panel); border:1px solid var(--line); border-left:4px solid var(--amber); border-radius:6px; padding:14px 18px; margin:14px 0; }
.box h3 { margin-top:6px; } .rec { color:var(--accent); font-weight:600; }
table { border-collapse:collapse; width:100%; font-size:14px; margin:8px 0; } td,th { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
th { color:var(--muted); font-weight:600; }
.two { display:grid; grid-template-columns:1fr 1fr; gap:14px; align-items:start; margin:10px 0; }
figure { margin:0; } figcaption { font-size:13px; color:var(--muted); margin-bottom:4px; }
img { width:100%; height:auto; border:1px solid var(--line); border-radius:4px; display:block; }
.svg svg { background:#0e2233; border-radius:4px; display:block; max-width:100%; height:auto; }
.big { overflow-x:auto; margin:10px 0; }
.muted { color:var(--muted); } ul { padding-left:20px; } li { margin:4px 0; } .scroll { overflow-x:auto; }
pre { white-space:pre-wrap; font:13px/1.5 ui-monospace,Menlo,monospace; background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:10px 12px; }
@media (max-width:800px) { .two { grid-template-columns:1fr; } }
</style></head><body><main>""")
    w(f"<p><code>moleculefinder-web/docs/design/{NAME}.html</code> · built 2026-11-26 on <code>wrong-drawings-2026-11</code> "
      f"in both repos (ETL <code>{e(facts['etl_tip'])}</code>, web <code>{e(facts['web_tip'])}</code>) · "
      f"<b>{e(facts.get('status') or 'built, not merged, not pushed, not deployed')}</b>.</p>")
    w("<h1>Wrong drawings</h1>")
    w("<p>Your word of 2026-11-26 on decisions (2) and (5) of the extended-solids review: fix the live pages whose "
      "drawing is wrong. <b>Built here: 10 of the 14 pages.</b> Four solids drawn as molecules that do not exist get the "
      "&ldquo;No single structure&rdquo; panel; simeticone is drawn as two units of its silicone chain; five metal "
      "compounds are drawn with the metal bonded to its partners, as the real molecule is. <b>Stopped: the four "
      "cobalamins</b> (vitamin B12 and its three forms), for the reasons in the last section, with a recommendation. "
      "Every title, description and H1 is unchanged.</p>")

    # ── Needs you ──
    w("<h2>Needs you</h2>")
    w('<div class="box"><h3>1. The ten pages as built</h3><p>Pictures below, before and after, at 1440 and 390, and each new '
      'metal drawing large on its own so every bond can be checked.</p><p class="rec">Recommended: approve, then a deploy '
      'brief.</p></div>')
    w('<div class="box"><h3>2. The cobalamins: a separate, smaller pass</h3><p>See the last section: a readable flat '
      'drawing needs a hand layout, and two of the four records carry no stereochemistry for the drawing to follow.</p>'
      '<p class="rec">Recommended: a cobalamin-only pass that draws one cobalamin skeleton by hand (coordinates in the '
      'SMILES, as cisplatin\'s are), uses cyanocobalamin\'s stereo for vitamin B12 (the same compound, proven by '
      'InChIKey), and asks you whether methylcobalamin may take the same stereo (PubChem\'s record of it has none).</p>'
      '</div>')

    # ── Summary ──
    w("<h2>The 14 pages at a glance</h2><div class='scroll'><table><tr><th>Page</th><th>Before</th><th>After</th>"
      "<th>3D model</th><th>Part layers</th><th>/vs pairs</th></tr>")
    for s in ALL:
        a, b = was[s], now[s]
        if s in LATTICES:
            after = "the panel"
        elif s == "simeticone":
            after = "two units of the chain"
        elif s in METALS:
            after = f"drawn with the {metal_seed[s]['metal']} bonds"
        else:
            after = "unchanged (stopped)"
        parts_a = [p["label"] for p in (a.get("structure_parts") or {}).get("parts") or []]
        parts_b = [p["label"] for p in (b.get("structure_parts") or {}).get("parts") or []]
        if parts_a and not parts_b:
            pl = f"{len(parts_a)} dropped"
        elif parts_a:
            pl = (f"remade from the new drawing: {', '.join(parts_b)}" if a.get("structure_svg") != b.get("structure_svg")
                  else f"unchanged: {', '.join(parts_b)}")
        else:
            pl = "none (none before)"
        three = ("removed (it showed PubChem's model of the false [C-]#[Si+] molecule)" if a.get("has_3d") and not b.get("has_3d")
                 else "none (none before)" if not a.get("has_3d") else "kept")
        w(f"<tr><td><b>{e(title[s])}</b><br><code>/m/{e(s)}</code></td><td>{'PubChem drawing' if a.get('structure_svg') else 'none'}</td>"
          f"<td>{e(after)}</td><td>{e(three)}</td><td>{e(pl)}</td><td>none</td></tr>")
    w("</table></div><p class='muted'>None of the 14 is in a /vs pair or a pair drawing, a door's facts, or a door's "
      "links. Chlorophyll a is booked for week 25 (Monday 2027-06-21); it stays drawable, so the week stands.</p>")

    # ── A ──
    w("<h2>A. Four more &ldquo;No single structure&rdquo; panels</h2>")
    w("<p>Same treatment as silicon dioxide and zinc oxide: no drawing, no 3D, no computed descriptors (polar surface "
      "area, hydrogen-bond counts, rotatable bonds, complexity: PubChem computes them from the false molecule). Formula, "
      "weight, SMILES and identifiers stay PubChem's.</p><table><tr><th>Page</th><th>What the panel now says</th>"
      "<th>Formula shown</th><th>&ldquo;Also called&rdquo;</th></tr>")
    for s in LATTICES:
        f = none_seed[s].get("formula")
        shown = (f"{f} (conventional form; PubChem lists {now[s]['molecular_formula']})" if f
                 else f"{now[s]['molecular_formula']} (as PubChem writes it)")
        names = ", ".join(now[s]["display_synonyms"] or []) or "(empty, as before)"
        w(f"<tr><td><b>{e(title[s])}</b></td><td>{e(title[s])} is {e(now[s]['structure_none']['line'])}</td>"
          f"<td>{e(shown)}</td><td>{e(names)}</td></tr>")
    w("</table><p><b>Names dropped:</b> none of the four pages showed a name of the false molecule, so no visible name "
      "leaves. Calcium oxide's &ldquo;calcium monoxide&rdquo; and silicon carbide's &ldquo;carbon silicide&rdquo; and "
      "&ldquo;silicon monocarbide&rdquo; are compositional names (like &ldquo;silicon dioxide&rdquo;), not names of a "
      "molecule, so they stay. Tungsten carbide's two synonyms &ldquo;methanidylidynetungsten(1+)&rdquo; and "
      "&ldquo;methanidylidynetungstenylium&rdquo; name the false WC molecule; they were not on its line (the line is "
      "empty) and are now in <code>drop_names</code> so they never reach it. Everyday and mineral names (quicklime, "
      "magnesia, carborundum) stay.</p>")
    for width, top in ((1440, 900), (390, 1300)):
        w(f"<h3>At {width} px: the top of each page</h3>")
        for s in LATTICES:
            w(f"<div class='two'>{fig(shots, f'before-{s}-{width}', f'{title[s]}, before', top)}"
              f"{fig(shots, f'after-{s}-{width}', f'{title[s]}, after', top)}</div>")

    # ── B ──
    u = now["simeticone"]["structure_repeat_unit"]
    w("<h2>B. Simeticone: a repeat unit in place of PubChem's drawing</h2>")
    w(f"<p>PubChem's record (CID 6433516) is a short three-silicon siloxane plus a lone O=Si=O molecule, which describes "
      f"neither the polymer nor the mixture. As with carboxymethyl cellulose, the page now shows two units of the chain, "
      f"<code>{e(u['smiles'])}</code>, the siloxane (Si&ndash;O&ndash;Si) linkage marked in amber, and the record drops "
      f"what PubChem computed from that structure: formula, weight, SMILES, InChI, the computed descriptors, and so its "
      f"place on the biggest and lightest boards (904 to 903 each); the silica is not drawn.</p>")
    w(f"<p><b>The line under the unit:</b> &ldquo;{e(u['line'])}&rdquo;<br><b>Why it replaces PubChem's drawing:</b> "
      f"&ldquo;{e(u['replaces'])}&rdquo;</p><p><b>The silica share is left out.</b> The figure (4.0 to 7.0 percent) is "
      f"the USP monograph's, which the licence rule does not let us display; no registered source states it.</p>")
    w(f"<div class='big'>{svg_at(u['svg'], 900)}</div><p class='muted'>The unit as drawn (900 px), without its amber "
      f"layer; the page puts the layer under the Si&ndash;O&ndash;Si bonds.</p>")
    for width, top in ((1440, 900), (390, 1300)):
        w(f"<div class='two'>{fig(shots, f'before-simeticone-{width}', f'Simeticone at {width}, before', top)}"
          f"{fig(shots, f'after-simeticone-{width}', f'Simeticone at {width}, after', top)}</div>")

    # ── C ──
    w("<h2>C. Five metal compounds drawn with their bonds</h2>")
    w("<p>PubChem's one-line structure keeps the metal apart, so each page drew it floating beside its partners. Each "
      "now has a display structure the drawing is drawn from (as the sugars' rings are); nothing else on the record "
      "moves. <b>The build checks every entry, every week</b>, and stops if one fails: the display structure has the "
      "record's formula and charge; the metal is bonded to exactly the atoms the entry names (a cyanide bonded by its "
      "nitrogen fails); and deleting the metal's bonds gives back PubChem's own pieces, every stereocentre included, "
      "with charges moved only as the entry lists. <b>The bonds, one rule for all five:</b> a partner that PubChem "
      "writes with a negative charge shares a plain line with the metal (the two charges cancel); a neutral partner "
      "gives a dative bond, drawn as an arrow to the metal. That is the textbook convention, and it is why "
      "chlorophyll's magnesium has two lines and two arrows. <b>No 3D model:</b> none of the five had one before "
      "(PubChem serves none), and none is added.</p>")
    for s in METALS:
        m = metal_seed[s]
        d = now[s]["structure_display"]
        ch = ", ".join(f"{c['element']} {c['record']:+d} to {c['drawn']:+d}" for c in m.get("charges") or []) or "none"
        w(f"<h3>{e(title[s])}</h3><p><b>The line in Sources and notes:</b> &ldquo;{e(d['line'])}&rdquo;<br>"
          f"<b>Where the SMILES came from:</b> {e(' '.join(m['from'].split()))}<br><b>Charges moved:</b> {e(ch)}<br>"
          f"<b>What the check proved:</b> {e(facts['checks'].get(s, 'the record’s own pieces, stereo included, charges as listed'))}<br>"
          f"<b>Part layers:</b> {e(', '.join(p['label'] for p in (now[s].get('structure_parts') or {}).get('parts') or []) or 'none')}</p>")
        w(f"<div class='big'>{svg_at(now[s]['structure_svg'], 960)}</div>")
        w(f"<details><summary>The drawing before (PubChem's one-line structure)</summary><div class='big'>"
          f"{svg_at(was[s]['structure_svg'], 480)}</div></details>")
        for width, top in ((1440, 900), (390, 1300)):
            w(f"<div class='two'>{fig(shots, f'before-{s}-{width}', f'{title[s]} at {width}, before', top)}"
              f"{fig(shots, f'after-{s}-{width}', f'{title[s]} at {width}, after', top)}</div>")
    w(f"<div class='box'><h3>Cisplatin's corner test</h3><p>{e(facts['cisplatin_corners'])}</p></div>")

    # ── Cobalamins ──
    w("<h2>Stopped: the four cobalamins</h2>")
    w("<p>Cyanocobalamin, vitamin B12, hydroxocobalamin and methylcobalamin keep their live drawings. Three problems, "
      "each a reason to stop rather than ship a drawing that is not done:</p><ul>"
      "<li><b>The layout.</b> In the real molecule the cobalt sits in the plane of the corrin ring with one group above "
      "and the benzimidazole below. A flat drawing cannot do that without one bond crossing the ring: the nucleotide loop "
      "runs from the corrin's side chain back to the cobalt. RDKit's own layout overlaps the rings badly (it does not "
      "treat a bond to a metal as a ring bond). The best layout built here (the live corrin, cobalt at its centre, the "
      "cyanide inside the ring, the nucleotide moved so its bond crosses the ring rim once) is below. It is close, but "
      "RDKit still flags a close contact (the small red square) at one ring junction's hydrogen, and the flag comes and "
      "goes with the third decimal of the coordinates, so it is not stable enough to ship.</li>"
      "<li><b>The stereo of two records.</b> PubChem's vitamin B12 record (CID 184933) and methylcobalamin record (CID "
      "6436232) carry no stereocentres at all, while cyanocobalamin's (CID 16212801) and hydroxocobalamin's carry them. "
      "&ldquo;The same drawing&rdquo; for vitamin B12 and cyanocobalamin means drawing stereo B12's record does not "
      "state; the check would have to allow that from cyanocobalamin's record (the same skeleton, proven by the first "
      "block of the InChIKey). Methylcobalamin has no such partner in the catalog.</li>"
      "<li><b>The corrin's double bonds.</b> Cyanocobalamin's record fixes the geometry of the corrin's double bonds. "
      "Once the cobalt is bonded, each sits in a six-membered ring, where RDKit drops a double bond's geometry, so the "
      "check needs one more rule (the record's geometry must be the one the ring forces) before it can hold them.</li></ul>")
    proto = shots / "cobalamin-prototype.svg"
    if proto.exists():
        SHOTS_OUT.mkdir(parents=True, exist_ok=True)
        shutil.copy(proto, SHOTS_OUT / proto.name)
        w(f"<div class='big'>{svg_at(proto.read_text(), 960)}</div><p class='muted'>Cyanocobalamin, the best prototype "
          f"(not shipped): cobalt bonded to the four corrin nitrogens, the cyanide carbon and the benzimidazole nitrogen; "
          f"the one crossing is the cobalt&ndash;benzimidazole bond over the ring rim.</p>")
    for s in COBALAMINS:
        w(f"<div class='two'>{fig(shots, f'after-{s}-1440', f'{title[s]} at 1440, live and unchanged', 900)}"
          f"{fig(shots, f'after-{s}-390', f'{title[s]} at 390, live and unchanged', 1300)}</div>")

    # ── Guard and checks ──
    w("<h2>The drawing guard's list (exactly this pass)</h2>")
    w(f"<pre>{e(facts['guard'])}</pre><p><b>Drawings lines</b> (the weekly run's summary):</p><pre>{e(facts['drawings'])}</pre>")
    w("<h2>Checks</h2><ul>" + "".join(f"<li>{e(c)}</li>" for c in facts["check_list"]) + "</ul>")
    w("</main></body></html>")
    OUT.write_text("\n".join(h))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
