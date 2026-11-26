"""Write the extended-solids review page (moleculefinder-web/docs/design/extended-solids-review-2026-11.html) and its
screenshots beside it (docs/design/extended-solids-review-2026-11/*.jpg).

    ./.venv/bin/python3 scripts/extended_solids_review.py <shots-dir> <facts.json>

<shots-dir> holds PNG screenshots (Lighthouse full-page captures of local production builds, keys blanked) named
before-<slug>-<w>.png (a build of main) and after-<slug>-<w>.png (this branch), w = 1440 or 390; they are written
beside the page as JPEG. <facts.json> holds the session's check results. Everything else is read from the committed
snapshot, the seeds and `git show main:` (the drawings that leave).

The survey: every record that is not an element and whose PubChem structure has no carbon, or a metal or metalloid
atom, or more than one fragment with a charge, or whose family is inorganic or mineral, plus EXTRA (three the rule
cannot see). Each is in exactly one group of SURVEY; the script stops if the snapshot holds an in-scope record the
survey does not classify, or the survey names one the rule does not reach.
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
from rdkit import Chem

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT.parent / "moleculefinder-web"
NAME = "extended-solids-review-2026-11"
OUT = WEB / "docs" / "design" / f"{NAME}.html"
SHOTS_OUT = WEB / "docs" / "design" / NAME
SNAP = ROOT / "data" / "snapshots"
SEEDS = ROOT / "moleculefinder_etl" / "sources" / "seeds"

# Metals and the metalloids B, Si, As, Te.
METALS = {
    "Li", "Be", "Na", "Mg", "Al", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Cs", "Ba", "La", "Ce",
    "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir",
    "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cf", "B", "Si",
    "As", "Te"
}
EXTRA = {"bicarbonate", "dimenhydrinate", "povidone-iodine"}

# group: a = extended solid, b = salt of a discrete organic ion, c = discrete inorganic molecule, d = unclear / other.
# kind (group a only): done | built | false (drawn as a molecule with bonds the solid lacks) | ions (a lattice of
# simple ions, drawn as its ions) | anion (a lattice with a polyatomic inorganic anion, drawn as its ions) |
# hand (hand-modelled, already no drawing).
# rec: the recommendation; line: the panel line proposed (group a, "false" only).
A = "a"


def row(g: str, why: str, rec: str, kind: str | None = None, line: str | None = None) -> dict:
    return {"g": g, "why": why, "rec": rec, "kind": kind, "line": line}


SURVEY: dict[str, dict] = {
    # ── (a) extended solids ──
    "titanium-dioxide": row(g=A, kind="done", why="Rutile and anatase: a lattice of TiO6 octahedra. Drawn with nothing since 2026-11-15 (your ruling).", rec="As it is."),
    "silicon-dioxide": row(g=A, kind="built", why="A network of SiO4 tetrahedra sharing every corner (quartz, and the glassy and amorphous silicas). PubChem's O=[Si]=O drew a molecule with two Si=O double bonds and a 3D model of it.", rec="Built on this branch: the panel."),
    "zinc-oxide": row(g=A, kind="built", why="Wurtzite: every zinc among four oxygens. PubChem's O=[Zn] drew a diatomic Zn=O molecule.", rec="Built on this branch: the panel."),
    "calcium-oxide": row(g=A, kind="false", why="Quicklime: a rock-salt lattice of Ca2+ and O2- ions, each among six of the other. Drawn as a Ca=O molecule (O=[Ca]).", rec="The panel.",
                          line="a crystal lattice of calcium and oxygen ions with no single molecule, each calcium among six oxygens; its formula, CaO, gives the ratio, one calcium to each oxygen."),
    "magnesium-oxide": row(g=A, kind="false", why="Periclase: a rock-salt lattice of Mg2+ and O2-, each among six of the other. Drawn as a Mg=O molecule (O=[Mg]).", rec="The panel.",
                            line="a crystal lattice of magnesium and oxygen ions with no single molecule, each magnesium among six oxygens; its formula, MgO, gives the ratio, one magnesium to each oxygen."),
    "silicon-carbide": row(g=A, kind="false", why="A covalent network like diamond's, each silicon bonded to four carbons and each carbon to four silicons. Drawn as a charged Si triple-bond C molecule ([C-]#[Si+]).", rec="The panel.",
                            line="a network of silicon and carbon with no single molecule, each silicon bonded to four carbons and each carbon to four silicons; its formula, SiC, gives the ratio, one silicon to each carbon."),
    "tungsten-carbide": row(g=A, kind="false", why="A hexagonal lattice, each carbon among six tungstens and each tungsten among six carbons. Drawn as a charged W triple-bond C molecule ([C-]#[W+]).", rec="The panel.",
                             line="a crystal lattice of tungsten and carbon with no single molecule, each carbon among six tungstens; its formula, WC, gives the ratio, one tungsten to each carbon."),
    **{s: row(g=A, kind="ions", why=w, rec="Keep the drawing: the ions it shows are the ones in the crystal (and in solution).") for s, w in {
        "sodium-chloride": "Rock-salt lattice of Na+ and Cl-; drawn as the two ions, no bond.",
        "potassium-chloride": "Rock-salt lattice of K+ and Cl-; drawn as the two ions.",
        "potassium-iodide": "Rock-salt lattice of K+ and I-; drawn as the two ions.",
        "sodium-iodide": "Rock-salt lattice of Na+ and I-; drawn as the two ions.",
        "sodium-fluoride": "Rock-salt lattice of Na+ and F-; drawn as the two ions.",
        "calcium-chloride": "Ionic lattice of Ca2+ and Cl-; drawn as one Ca2+ and two Cl-.",
        "magnesium-chloride": "Layered ionic lattice of Mg2+ and Cl-; drawn as the three ions.",
        "ammonium-chloride": "Ionic lattice of NH4+ and Cl-; drawn as the two ions.",
        "aluminium-oxide": "Corundum, an ionic and partly covalent lattice; drawn as two Al3+ and three O2- ions.",
        "aluminium-hydroxide": "Gibbsite, layers of Al(OH)6 octahedra; drawn as Al3+ and three OH-.",
        "calcium-hydroxide": "Portlandite, a layered lattice; drawn as Ca2+ and two OH-.",
        "magnesium-hydroxide": "Brucite, a layered lattice; drawn as Mg2+ and two OH-.",
        "sodium-hydroxide": "Ionic lattice of Na+ and OH-; drawn as the two ions.",
        "potassium-hydroxide": "Ionic lattice of K+ and OH-; drawn as the two ions.",
    }.items()},
    **{s: row(g=A, kind="anion", why=w, rec="Keep the drawing: the anion is a real unit and is drawn right; the cations sit beside it, as in sodium benzoate.") for s, w in {
        "calcium-carbonate": "Calcite or aragonite: Ca2+ and carbonate ions; drawn as Ca2+ and CO3 2-.",
        "magnesium-carbonate": "Magnesite: Mg2+ and carbonate; drawn as the ions.",
        "sodium-carbonate": "Na+ and carbonate; drawn as the ions (it has a part layer).",
        "sodium-bicarbonate": "Na+ and hydrogen carbonate; drawn as the ions (it has a part layer).",
        "potassium-bicarbonate": "K+ and hydrogen carbonate; drawn as the ions.",
        "ammonium-bicarbonate": "NH4+ and hydrogen carbonate; drawn as the ions.",
        "ammonium-carbonate": "NH4+ and carbonate; drawn as the ions.",
        "copper-ii-sulfate": "Cu2+ and sulfate (the blue crystal is the pentahydrate); drawn as the ions.",
        "iron-ii-sulfate": "Fe2+ and sulfate; drawn as the ions.",
        "magnesium-sulfate": "Mg2+ and sulfate (Epsom salt is the heptahydrate); drawn as the ions.",
        "zinc-sulfate": "Zn2+ and sulfate; drawn as the ions.",
        "dicalcium-phosphate": "Ca2+ and hydrogen phosphate; drawn as the ions.",
        "tricalcium-phosphate": "Ca2+ and phosphate; drawn as three Ca2+ and two PO4 3-.",
        "dipotassium-phosphate": "K+ and hydrogen phosphate; drawn as the ions.",
        "disodium-phosphate": "Na+ and hydrogen phosphate; drawn as the ions.",
        "monosodium-phosphate": "Na+ and dihydrogen phosphate; drawn as the ions.",
        "potassium-nitrate": "K+ and nitrate; drawn as the ions.",
        "sodium-nitrate": "Na+ and nitrate; drawn as the ions.",
        "sodium-nitrite": "Na+ and nitrite; drawn as the ions.",
        "potassium-permanganate": "K+ and the permanganate ion MnO4-; drawn as the ions.",
        "sodium-hypochlorite": "Na+ and hypochlorite (sold as a solution, bleach); drawn as the ions.",
        "sodium-bisulfite": "Na+ and hydrogen sulfite; drawn as the ions.",
        "sodium-sulfite": "Na+ and sulfite; drawn as the ions.",
        "sodium-metabisulfite": "Na+ and the disulfite ion S2O5 2-; drawn as the ions.",
        "sodium-monofluorophosphate": "Na+ and the monofluorophosphate ion PO3F 2-; drawn as the ions.",
        "borax": "Na+ and the tetraborate ion, a discrete B4O5(OH)4 cage; drawn as the ions (it has a part layer).",
    }.items()},
    "sodium-ferrocyanide": row(g=A, kind="anion", why="Na+ and the ferrocyanide ion [Fe(CN)6]4-, a discrete complex; but drawn as Fe2+ and six loose cyanide ions, as if the cyanides were free.",
                                rec="Keep it as ions, but redraw the complex ion with its six Fe to C bonds: a separate change (a display structure), not the panel."),
    **{s: row(g=A, kind="hand", why=w, rec="As it is: hand-modelled, already drawn with nothing.") for s, w in {
        "aluminum-chlorohydrate": "A basic aluminium chloride, a mix of polymeric Al-O-OH clusters; no PubChem structure.",
        "aluminum-sesquichlorohydrate": "A basic aluminium chloride; no PubChem structure.",
        "aluminum-zirconium-octachlorohydrex-gly": "Aluminium and zirconium chlorohydrate clusters with glycine; no PubChem structure.",
        "aluminum-zirconium-tetrachlorohydrex-gly": "Aluminium and zirconium chlorohydrate clusters with glycine; no PubChem structure.",
        "aluminum-zirconium-trichlorohydrex-gly": "Aluminium and zirconium chlorohydrate clusters with glycine; no PubChem structure.",
    }.items()},
    # ── (b) salts of discrete organic ions: the drawing of the ions is right and stays ──
    **{s: row(g="b", why=w, rec="Keep.") for s, w in {
        "acesulfame-potassium": "The acesulfame anion and K+.",
        "allura-red-ac": "A sulfonated azo dye anion and Na+.",
        "amaranth-dye": "A sulfonated azo dye anion and Na+.",
        "brilliant-blue-fcf": "A sulfonated triarylmethane dye anion and Na+.",
        "indigo-carmine": "The disulfonated indigo anion and Na+.",
        "ponceau-4r": "A sulfonated azo dye anion and Na+.",
        "sunset-yellow-fcf": "A sulfonated azo dye anion and Na+.",
        "tartrazine": "A sulfonated pyrazolone azo dye anion and Na+.",
        "calcium-acetate": "Acetate anions and Ca2+.",
        "calcium-beta-hydroxy-beta-methylbutyrate": "HMB anions and Ca2+.",
        "calcium-citrate": "Citrate anions and Ca2+.",
        "calcium-gluconate": "Gluconate anions and Ca2+.",
        "calcium-oxalate": "Oxalate, a discrete organic anion, and Ca2+ (also the mineral of kidney stones; the anion carries the structure).",
        "magnesium-citrate": "Citrate anion and Mg2+.",
        "magnesium-glycinate": "Glycinate anions and Mg2+ (a chelate, drawn as ions).",
        "magnesium-l-threonate": "Threonate anions and Mg2+.",
        "magnesium-stearate": "Stearate anions and Mg2+.",
        "lithium-orotate": "The orotate anion and Li+.",
        "monosodium-glutamate": "The glutamate anion and Na+.",
        "potassium-bitartrate": "Hydrogen tartrate and K+.",
        "potassium-citrate": "Citrate and K+.",
        "potassium-sodium-tartrate": "Tartrate, K+ and Na+, with its four waters.",
        "potassium-sorbate": "The sorbate anion and K+.",
        "sodium-acetate": "Acetate and Na+.",
        "sodium-benzoate": "The benzoate anion and Na+ (the brief's own example).",
        "sodium-lauryl-sulfate": "The dodecyl sulfate anion and Na+.",
        "sodium-thiopental": "The thiopental anion and Na+.",
        "trisodium-citrate": "Citrate and Na+.",
        "cyclamate": "The cyclamate anion and Na+.",
        "disodium-inosinate": "The inosinate anion and Na+.",
        "docusate": "The docusate anion and Na+.",
        "metamizole": "The metamizole anion and Na+.",
        "choline-chloride": "The choline cation and Cl-.",
        "hyoscine-butylbromide": "A quaternary ammonium drug cation and Br-.",
        "ipratropium-bromide": "A quaternary ammonium drug cation and Br-.",
        "methylene-blue": "The methylene blue cation and Cl-.",
        "dimenhydrinate": "A salt of two organic ions, diphenhydramine and 8-chlorotheophylline (PubChem draws both neutral).",
    }.items()},
    # ── (c) discrete inorganic molecules, rightly drawn ──
    **{s: row(g="c", why=w, rec="Keep.") for s, w in {
        "water": "H2O, a molecule (ice is a lattice of whole molecules).",
        "ammonia": "NH3, a molecule.",
        "carbon-dioxide": "CO2, a molecule (dry ice is a crystal of whole molecules).",
        "carbon-monoxide": "CO, a molecule.",
        "hydrogen-peroxide": "H2O2, a molecule.",
        "hydrogen-sulfide": "H2S, a molecule.",
        "hypochlorous-acid": "HOCl, a molecule.",
        "iodine": "I2, a molecule (solid iodine is a crystal of I2 molecules).",
        "nitric-oxide": "NO, a molecule (a radical).",
        "nitrous-oxide": "N2O, a molecule.",
        "ozone": "O3, a molecule.",
        "sulfur-dioxide": "SO2, a molecule.",
        "sulfuric-acid": "H2SO4, a molecule.",
        "phosphoric-acid": "H3PO4, a molecule.",
        "boric-acid": "B(OH)3, a molecule (its crystal is layers of molecules held by hydrogen bonds).",
        "bicarbonate": "The HCO3- ion itself, as it is in blood: a discrete ion, rightly drawn.",
    }.items()},
    # ── (d) unclear or another kind of problem ──
    "stannous-fluoride": row(g="d", why="SnF2 is a molecule in the gas; the solid is built of Sn4F8 rings; in toothpaste it is dissolved. F-Sn-F is the usual formula drawing.", rec="Keep."),
    "simeticone": row(g="d", why="A mixture, polydimethylsiloxane with 4 to 7% silica. PubChem draws a short siloxane plus the same O=[Si]=O molecule silicon dioxide had.",
                       rec="The panel, with the oxides (a mixture has no single structure).",
                       line="a mixture of polydimethylsiloxane, a silicone oil, and finely divided silica, with no single molecule."),
    "povidone-iodine": row(g="d", why="Iodine held by a polymer (povidone); PubChem draws one vinylpyrrolidone unit and I2.", rec="Keep for now; a polymer, not a lattice (a repeat unit would be the later fix)."),
    "bismuth-subsalicylate": row(g="d", why="A coordination polymer in the solid (layers of bismuth oxide and salicylate); drawn as one Bi salicylate ring.", rec="Keep: the drawing is the usual formula unit."),
    "sucralfate": row(g="d", why="Sucrose octasulfate with basic aluminium hydroxide, an amorphous complex; drawn as the sucrose octasulfate with Al(OH) groups.", rec="Keep."),
    **{s: row(g="d", why=w, rec="Keep for now; a later redraw with the metal bonded (a display structure) if you want it, cisplatin first.") for s, w in {
        "cisplatin": "A discrete square-planar complex, Pt bonded to two Cl and two NH3; PubChem's SMILES leaves the two NH3 unbonded, so the drawing shows them floating.",
        "chlorophyll-a": "A discrete molecule, Mg bonded inside the ring; drawn with the Mg2+ apart.",
        "cyanocobalamin": "A discrete molecule, Co bonded in the corrin ring; drawn with Co3+ and the cyanide apart.",
        "hydroxocobalamin": "A discrete molecule, Co bonded in the corrin ring; drawn with the Co3+ apart.",
        "methylcobalamin": "A discrete molecule, Co bonded to a methyl in the corrin ring; drawn with Co3+ and CH3- apart.",
        "vitamin-b12": "A discrete molecule (cyanocobalamin); drawn with Co3+ and the cyanide apart.",
        "chromium-iii-picolinate": "A discrete complex, Cr bonded to three picolinates; drawn as Cr3+ and three loose picolinate ions.",
        "thiomersal": "A discrete molecule with an Hg to S bond; drawn as ethylmercury, thiosalicylate and Na+ apart.",
    }.items()},
}
GROUPS = {"a": "Extended solids (a lattice or network, no discrete molecule)",
          "b": "Salts of a discrete organic ion (drawing the ions is right)",
          "c": "Discrete inorganic molecules (rightly drawn)",
          "d": "Unclear, or another kind of problem"}
KINDS = {"done": "done", "built": "built on this branch", "false": "drawn as a molecule with bonds the solid lacks",
         "ions": "a lattice of simple ions, drawn as its ions", "anion": "a lattice with a polyatomic anion, drawn as its ions",
         "hand": "hand-modelled, no drawing"}


# The computed descriptors the molecule page prints under Properties (app/m/[slug]/page.tsx), in its own words.
SHOWN = {"tpsa": "polar surface area", "h_bond_donors": "H-bond donors", "h_bond_acceptors": "H-bond acceptors",
         "rotatable_bonds": "rotatable bonds", "complexity": "complexity"}


def e(s) -> str:
    return html.escape(str(s), quote=True)


def rec(slug: str) -> dict:
    return json.loads((SNAP / "molecules" / f"{slug}.json").read_text())


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def in_scope(r: dict) -> bool:
    if r.get("scope_family") == "element":
        return False
    smi = r.get("isomeric_smiles") or ""
    m = Chem.MolFromSmiles(smi) if smi else None
    if m is not None:
        els = {a.GetSymbol() for a in m.GetAtoms()}
        charged = any(a.GetFormalCharge() for a in m.GetAtoms())
        if "C" not in els or els & METALS or (len(smi.split(".")) > 1 and charged):
            return True
    return r.get("scope_family") in ("inorganic", "mineral")


def svg_inline(svg: str | None) -> str:
    if not svg:
        return '<span class="muted">none</span>'
    svg = re.sub(r"<\?xml[^>]*\?>", "", svg).strip()
    svg = re.sub(r"width='[^']*'", "width='120'", svg, count=1)
    svg = re.sub(r"height='[^']*'", "height='90'", svg, count=1)
    return f'<span class="svg">{svg}</span>'


def jpg(shots: Path, name: str, top: int | None = None) -> str | None:
    """The capture as JPEG beside the page (the 1440 ones at half size: still readable, a third of the bytes); with
    `top`, only the first `top` pixels of the capture (the heading and the structure panel)."""
    p = shots / f"{name}.png"
    if not p.exists():
        # A capture that is not in <shots-dir> keeps the JPEG already beside the page (the "before" pictures are taken
        # once, from main; the deploy's amendments retook only the "after" ones).
        kept = SHOTS_OUT / f"{name}{'-top' if top else ''}.jpg"
        return f"{NAME}/{kept.name}" if kept.exists() else None
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
    records = {p.stem: json.loads(p.read_text()) for p in sorted((SNAP / "molecules").glob("*.json"))}
    scope = {s for s, r in records.items() if in_scope(r)} | EXTRA
    missing, extra = scope - set(SURVEY), set(SURVEY) - scope
    if missing or extra:
        raise SystemExit(f"survey and scope disagree: unclassified {sorted(missing)}, outside the rule {sorted(extra)}")
    elements = sum(1 for r in records.values() if r.get("scope_family") == "element")

    comparisons = json.loads((SNAP / "comparisons.json").read_text())
    pair_draw = json.loads((SNAP / "compare_drawings.json").read_text())["pairs"]
    doors = (SNAP / "doors.json").read_text()
    weeks = {w["slug"]: w["week"] for w in yaml.safe_load((SEEDS / "featured.yaml").read_text())["weeks"]}
    cards: dict[str, set[str]] = {}
    for s, r in records.items():
        for ed in r.get("edges") or []:
            cards.setdefault(ed["neighbor_slug"], set()).add(s)
        for kind in (r.get("trails") or {}).values():
            for t in kind:
                cards.setdefault(t.get("to"), set()).add(s)
    main_rec = {s: json.loads(git("show", f"main:data/snapshots/molecules/{s}.json")) for s in ("silicon-dioxide", "zinc-oxide")}

    def facts_of(slug: str) -> dict:
        r = main_rec.get(slug) or records[slug]
        d = {SHOWN[k]: v for k, v in (r.get("descriptors") or {}).items() if k in SHOWN and v is not None}
        pairs = sorted(k for k, c in comparisons.items() if slug in (c.get("a"), c.get("b")))
        return {"svg": r.get("structure_svg"), "has_3d": bool(r.get("has_3d")),
                "parts": len((r.get("structure_parts") or {}).get("parts") or []), "desc": d, "pairs": pairs,
                "pair_drawings": [p for p in pairs if p in pair_draw], "week": weeks.get(slug),
                "door": f'"{slug}"' in doors, "cards": len(cards.get(slug, set()) - {slug})}

    by_group = {g: sorted((s for s in SURVEY if SURVEY[s]["g"] == g), key=lambda s: records[s]["title"].lower())
                for g in GROUPS}
    a_kind = {k: [s for s in by_group["a"] if SURVEY[s]["kind"] == k] for k in KINDS}

    h: list[str] = []
    w = h.append
    w("""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Extended solids review</title><style>
:root { --bg:#0e2233; --panel:#132c40; --ink:#e6f0f7; --muted:#9db3c4; --accent:#7fc4e8; --amber:#e9a23b; --line:#24445c; --del:#ff7a72; --ins:#8fd982; }
@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) { --bg:#f6f8fa; --panel:#fff; --ink:#132433; --muted:#4d6475; --accent:#1d6fa3; --amber:#a5620a; --line:#d4dde4; --del:#b42318; --ins:#1a7f37; } }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:1180px; margin:0 auto; padding:24px 16px 80px; }
h1 { font:700 30px/1.2 ui-monospace,Menlo,monospace; margin:8px 0 4px; }
h2 { margin:44px 0 10px; padding-top:14px; border-top:1px solid var(--line); font-size:22px; }
h3 { margin:26px 0 6px; font-size:18px; } code { font:13px ui-monospace,Menlo,monospace; color:var(--muted); }
.box { background:var(--panel); border:1px solid var(--line); border-left:4px solid var(--amber); border-radius:6px; padding:14px 18px; margin:14px 0; }
.box h3 { margin-top:6px; } .rec { color:var(--accent); font-weight:600; }
table { border-collapse:collapse; width:100%; font-size:14px; margin:8px 0; } td,th { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
th { color:var(--muted); font-weight:600; }
.two { display:grid; grid-template-columns:1fr 1fr; gap:14px; align-items:start; margin:10px 0; }
.five { display:grid; grid-template-columns:repeat(5,1fr); gap:12px; align-items:start; margin:10px 0; }
figure { margin:0; } figcaption { font-size:13px; color:var(--muted); margin-bottom:4px; }
img { width:100%; height:auto; border:1px solid var(--line); border-radius:4px; display:block; }
.svg svg { background:#0e2233; border-radius:4px; display:block; }
.muted { color:var(--muted); } ul { padding-left:20px; } li { margin:4px 0; } .scroll { overflow-x:auto; }
del { color:var(--del); } ins { color:var(--ins); text-decoration:none; }
details { margin:8px 0; } summary { cursor:pointer; color:var(--accent); }
@media (max-width:800px) { .two, .five { grid-template-columns:1fr 1fr; } }
</style></head><body><main>""")
    w(f"<p><code>moleculefinder-web/docs/design/{NAME}.html</code> · built 2026-11-26 on <code>extended-solids-2026-11</code> "
      f"in both repos (ETL <code>{e(facts['etl_tip'])}</code>, web <code>{e(facts['web_tip'])}</code>) · "
      f"<b>{facts.get('status') or 'not merged, not pushed, not deployed; waiting for your rulings below'}</b>.</p>")
    w("<h1>Extended solids</h1>")
    w("<p>Some entries in the catalog are not molecules: they are solids built as one endless lattice or network, with no "
      "small molecule anywhere in them. PubChem still gives each a one-line structure, and our recipe draws whatever that "
      "line says, so a few of them appear as small molecules that do not exist in the solid. You ruled on 2026-11-15 that "
      "titanium dioxide gets the &ldquo;No single structure&rdquo; panel and that silicon dioxide and zinc oxide follow. "
      "<b>This branch does those two</b>, exactly as titanium dioxide was done, and surveys every other inorganic or "
      "salt-like entry so you can rule once on the rest. Nothing else is changed yet.</p>")

    # ── Decisions ──
    w("<h2>Needs you (five decisions, each with a recommendation)</h2>")
    false_list = ", ".join(records[s]["title"] for s in a_kind["false"])
    keep_n = len(a_kind["ions"]) + len(a_kind["anion"])
    w('<div class="box"><h3>1. Silicon dioxide and zinc oxide as built</h3>'
      "<p>Each loses its drawing (and silicon dioxide its 3D model of an O=Si=O molecule) and its computed descriptors "
      "(polar surface area, hydrogen-bond counts, complexity: PubChem computes them from the same fictitious molecule), and "
      "gains the panel with one sentence. Formula, weight, SMILES, LD50, hazard label, lists and labels are unchanged. No "
      "title or description moves.</p><p class=\"rec\">Recommended: approve as built.</p></div>")
    w(f'<div class="box"><h3>2. The other solids drawn as false molecules: {e(false_list)}, and simeticone</h3>'
      f"<p>These four are drawn with bonds the solid does not have (a Ca=O or Mg=O double bond, a Si or W triple bond to "
      f"carbon). Simeticone is a mixture whose drawing contains the same O=Si=O silica molecule. Each would get the panel "
      f"with the line proposed in the table below, in one reviewed change with its own review page.</p>"
      f'<p class="rec">Recommended: yes, all five, as the next change.</p></div>')
    w(f'<div class="box"><h3>3. The {keep_n} ionic salts drawn as their ions (sodium chloride, calcium carbonate and the like)</h3>'
      "<p>These are lattices too, but their drawings show only the ions, with no bond between them, which is how chemists "
      "draw an ionic compound (and how the ions are when dissolved). Where the anion is a real unit (carbonate, sulfate, "
      "phosphate, nitrate, permanganate) the drawing shows it correctly, just as sodium benzoate's does. The panel would "
      "remove the only picture these pages have and say less. Sodium ferrocyanide is the one exception within the group: "
      "its iron is drawn apart from its six cyanides.</p>"
      '<p class="rec">Recommended: keep all of them as they are. Separately, and later, redraw sodium ferrocyanide\'s '
      "complex ion with its bonds (a display structure, not the panel).</p></div>")
    w('<div class="box"><h3>4. Molecule of the week, week 22 (Monday 2027-05-31, sunscreen season)</h3>'
      "<p>Zinc oxide was booked for that week, and the week's compiler takes only a molecule it can draw, so the build "
      "stops unless the week changes. This branch gives the week to <b>avobenzone</b> (it has a drawing and is booked for "
      "no other week) with the hook: &ldquo;Sunscreen season: avobenzone filters long-wave UVA, and sunscreens pair it with "
      "a second filter that keeps sunlight from breaking it down.&rdquo; The week has not run, so no archive page or RSS "
      "item moves.</p><p class=\"rec\">Recommended: approve avobenzone and the hook.</p></div>")
    w('<div class="box"><h3>5. Metals drawn apart from the atoms they are bonded to (not lattices)</h3>'
      "<p>Eight discrete molecules are drawn with their metal floating free because PubChem's one-line structure leaves the "
      "metal bonds out: cisplatin (its two NH3), chlorophyll a, four cobalamin (vitamin B12) records, chromium picolinate "
      "and thiomersal. These are real molecules, so the panel is wrong for them; the fix is a drawing with the bonds in "
      "(the display-structure mechanism used for the sugars in phase 3A).</p>"
      '<p class="rec">Recommended: not now; queue a small redraw pass, cisplatin first (the one a chemist would notice).'
      "</p></div>")
    w("<p class=\"muted\">One small web change rides with this branch: the panel's &ldquo;Class&rdquo; line printed zinc oxide's "
      "family code <code>otc</code> as &ldquo;Otc&rdquo;; it now reads &ldquo;OTC&rdquo;. Titanium dioxide's "
      "&ldquo;Inorganic&rdquo; is unchanged.</p>")

    # ── The two pages ──
    w("<h2>The two pages, beside titanium dioxide's</h2>")
    w("<p>Local production builds, database keys blanked. <i>Before</i> is <code>main</code> (what is live), <i>after</i> "
      "is this branch. Click any picture for the full page.</p>")
    w("<h3>At 1440 px: the top of each page</h3>")
    for s in ("silicon-dioxide", "zinc-oxide"):
        w('<div class="two">')
        w(fig(shots, f"before-{s}-1440", f"{records[s]['title']}, before", 640))
        w(fig(shots, f"after-{s}-1440", f"{records[s]['title']}, after", 640))
        w("</div>")
    w('<div class="two">')
    w(fig(shots, "after-titanium-dioxide-1440", "Titanium dioxide, live since 2026-11-15, for comparison", 640))
    w("</div>")
    w("<h3>At 390 px: the top of each page</h3>")
    w('<div class="five">')
    for s in ("silicon-dioxide", "zinc-oxide"):
        w(fig(shots, f"before-{s}-390", f"{records[s]['title']}, before", 1150))
        w(fig(shots, f"after-{s}-390", f"{records[s]['title']}, after", 1150))
    w(fig(shots, "after-titanium-dioxide-390", "Titanium dioxide (live)", 1150))
    w("</div>")
    # ── The deploy's two amendments (2026-11-26) ──
    if facts.get("amendments"):
        am = facts["amendments"]
        w("<h2>Two amendments for the deploy (2026-11-26)</h2>")
        w("<p>From the review of the pictures above: the formula line read PubChem's alphabetical order (O2Si) while the panel "
          "beside it says SiO2, and silicon dioxide's &ldquo;Also called&rdquo; named the one molecule that does not exist. "
          "Both are fixed on the three no-structure pages. The pictures above are the amended pages.</p>")
        w("<table><tr><th>Page</th><th>Formula line before</th><th>after</th><th>Also called before</th><th>after</th></tr>")
        for s in ("silicon-dioxide", "zinc-oxide", "titanium-dioxide"):
            a = am[s]
            w(f"<tr><td>/m/{e(s)}</td><td>{e(a['formula_before'])}</td><td><b>{e(a['formula_after'])}</b></td>"
              f"<td>{e(a['names_before'])}</td><td><b>{e(a['names_after'])}</b></td></tr>")
        w("</table>")
        for line in am["notes"]:
            w(f"<p>{line}</p>")

    w("<h3>What moved on the two pages (from the built HTML, text compared line by line)</h3><table><tr><th>Page</th><th>Leaves</th><th>Arrives</th></tr>")
    for s in ("silicon-dioxide", "zinc-oxide"):
        f = facts_of(s)
        leaves = ["the 2D drawing" + (" and the 3D model (&ldquo;Turn it in your hands&rdquo;, 3D / 2D)" if f["has_3d"] else "")]
        leaves.append("descriptors: " + ", ".join(f"{e(k)} {e(v)}" for k, v in f["desc"].items()))
        w(f"<tr><td>/m/{e(s)}</td><td>{'<br>'.join(leaves)}</td><td>&ldquo;No single structure&rdquo;: <b>{e(records[s]['title'])}</b> "
          f"is {e(records[s]['structure_none']['line'])}<br>Class {e('OTC' if s == 'zinc-oxide' else 'Mineral')} (Editorial)</td></tr>")
    w("</table>")
    w("<p>Drawings that leave (from <code>main</code>):</p><p>"
      + " ".join(f"{e(records[s]['title'])} {svg_inline(main_rec[s]['structure_svg'])}" for s in ("silicon-dioxide", "zinc-oxide"))
      + "</p>")
    w("<p>Neither molecule is in any /vs pair or pair drawing, on any door page, or in the home page's pair; neither had a "
      "part layer. Zinc oxide's week 22 is decision 4.</p>")

    # ── Checks ──
    w("<h2>Checks</h2><ul>")
    for line in facts["checks"]:
        w(f"<li>{line}</li>")
    w("</ul>")

    # ── Survey ──
    counts = {g: len(by_group[g]) for g in GROUPS}
    w(f"<h2>The survey: {len(SURVEY)} inorganic or salt-like entries</h2>")
    w(f"<p>Every record that is not an element ({elements} elements are left as they are) and whose PubChem structure has "
      f"no carbon, a metal or metalloid atom, or more than one piece with a charge, or whose family is inorganic or "
      f"mineral; plus bicarbonate, dimenhydrinate and povidone-iodine, which that rule cannot see. A test-like check in "
      f"the generator stops if the catalog holds one the survey does not classify. Counts: "
      + "; ".join(f"({g}) {counts[g]}" for g in GROUPS) + ".</p>")
    w("<p>&ldquo;Would lose&rdquo; is what the molecule page loses if it gets the panel: its drawing, its 3D model when it "
      "has one, its part layer, and the computed descriptors shown under Properties. &ldquo;Elsewhere&rdquo; is every other "
      "page that shows its drawing: /vs pairs (each would show &ldquo;No single structure&rdquo; on that side, as "
      "comparisons with hand-modelled molecules do), pair drawings, door pages, a molecule-of-the-week booking, and the "
      "number of other molecule pages that show it as a small card in &ldquo;Explore&rdquo; (the card keeps its name and "
      "formula and loses its thumbnail).</p>")
    for g, title in GROUPS.items():
        w(f"<h3>({g}) {e(title)}: {counts[g]}</h3><div class=\"scroll\"><table>")
        if g == "a":
            w("<tr><th>Entry</th><th>Kind</th><th>Drawing today</th><th>Why</th><th>Would lose / elsewhere</th><th>Recommendation</th></tr>")
            order = [s for k in KINDS for s in a_kind[k]]
            for s in order:
                x, f = SURVEY[s], facts_of(s)
                lose = []
                if f["svg"]:
                    lose.append("drawing" + (", 3D model" if f["has_3d"] else "") + (f", {f['parts']} part(s)" if f["parts"] else ""))
                if f["desc"]:
                    lose.append("descriptors: " + ", ".join(f["desc"]))
                where = []
                if f["pairs"]:
                    where.append("/vs: " + ", ".join(f["pairs"]) + (f" (pair drawing: {', '.join(f['pair_drawings'])})" if f["pair_drawings"] else ""))
                if f["door"]:
                    where.append("a door page")
                if f["week"]:
                    where.append(f"molecule of the week {f['week']}")
                if f["cards"]:
                    where.append(f"a card on {f['cards']} other page(s)")
                recline = e(x["rec"]) + (f"<br><span class=\"muted\">Proposed line: {e(records[s]['title'])} is {e(x['line'])}</span>" if x.get("line") else "")
                w(f"<tr><td><b>{e(records[s]['title'])}</b><br><code>{e(records[s].get('isomeric_smiles') or 'no SMILES')}</code></td>"
                  f"<td>{e(KINDS[x['kind']])}</td><td>{svg_inline(f['svg'])}</td><td>{e(x['why'])}</td>"
                  f"<td>{'; '.join(e(v) for v in lose) or '<span class=muted>nothing</span>'}"
                  f"{'<br><span class=muted>Elsewhere: ' + e('; '.join(where)) + '</span>' if where else ''}</td><td>{recline}</td></tr>")
        else:
            w("<tr><th>Entry</th><th>Drawing today</th><th>Why</th><th>Recommendation</th></tr>")
            for s in by_group[g]:
                x, f = SURVEY[s], facts_of(s)
                recline = e(x["rec"]) + (f"<br><span class=\"muted\">Proposed line: {e(records[s]['title'])} is {e(x['line'])}</span>" if x.get("line") else "")
                w(f"<tr><td><b>{e(records[s]['title'])}</b></td><td>{svg_inline(f['svg'])}</td><td>{e(x['why'])}</td><td>{recline}</td></tr>")
        w("</table></div>")
    w("<p class=\"muted\">Generated by <code>moleculefinder-etl/scripts/extended_solids_review.py</code>.</p></main></body></html>")
    OUT.write_text("\n".join(h))
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes); screenshots {sum(p.stat().st_size for p in SHOTS_OUT.glob('*.jpg')):,} bytes; "
          f"groups " + ", ".join(f"{g} {counts[g]}" for g in GROUPS) + "; a: "
          + ", ".join(f"{k} {len(v)}" for k, v in a_kind.items()))


if __name__ == "__main__":
    main()
