"""Drawing truth: trust review 3 (`mfetl review drawings`; brief ../TRUST-2-DRAWING-TRUTH-PROMPT.md, 2026-11-27).

Between 2026-11-15 and 2026-11-27, 18 live pages were found by hand to carry a drawing that was not true: lattices drawn
as molecules, a mixture drawn as a molecule, metals drawn floating beside the atoms they are bonded to. This review
makes a machine look at EVERY drawing every day, so the next one is found the day it appears.

READ-ONLY. It reads the built snapshot (``data/snapshots``), the seeds and the live site (check 9 only), makes no
PubChem request, draws nothing and writes nothing but its report: ``<out>/drawings-<date>.md`` and ``.json``, the
heartbeat ``<out>/drawings-last-run.json`` and, for a class seen on two consecutive runs, one line in ``<out>/QUEUE.md``.
It never blocks, stops or changes the weekly refresh, the news job or a deploy. Exit 0 when it ran, whatever it
found; non-zero only when it could not run.

Each finding belongs to a CLASS, named by the fact, the surface and the shape ("metal floating / structure drawing /
an s-block ion beside an anion"). Every count states its denominator; a live page it could not read is "not read",
never 0. The checks, as the brief numbers them:

 1. atoms        the structure each drawing is drawn from has the record's formula and charge (a repeat unit is a
                 fragment of a chain by design and is named, not checked); and the drawing itself shows that
                 structure: every bond the SVG draws is a bond of it, and every atom of it is drawn.
 2. metal        a metal or metalloid drawn with no bond, beside a piece holding atoms that could bond it, with no
                 ``metal_bonds`` entry, not on an allowlist that covers it.
 3. lattice      no C-H skeleton, a neutral bonded piece holding a metal or metalloid (or the record's family is
                 inorganic or mineral), no ``structure_none`` or ``metal_bonds`` entry, not allowlisted.
 4. fragments    every drawing of more than one piece is classified: a salt (its ions, or its acid and base written
                 neutral), a hydrate or solvate, a mixture or polymer (PubChem's pieces standing in for something that
                 is not one molecule), or unexplained. The last two are findings unless allowlisted.
 5. survey       every record the extended-solids survey's scope rule catches is classified (drawings_rulings.yaml).
 6. seeds        every structure_none, structure_display (sugar and metal bonds), repeat_units and structure_parts
                 entry names a record that exists and passes its own build-time check, and the snapshot carries what
                 the seed makes today.
 7. stereo       a record that specifies centres whose drawing shows none; a drawing that shows a centre the record
                 does not specify without ``stereo_from``; fewer marks than the drawn structure specifies.
 8. 3D           a 3D model on a page with no drawing, a panel or a metal-bonds drawing; a model compound whose
                 connectivity is not the drawing's (the sugars' rule; models pinned in drawings_rulings.yaml).
 9. live         a pinned set (one page of each drawing kind, each seed entry, with reasons) plus 40 molecule pages
                 sampled by a seed made from the date: the drawing served is byte for byte the snapshot's, a page
                 with no drawing serves none, the 3D control matches the record, the notes line is the seed's.
10. parts        every part layer's atoms and bonds exist in its drawing, its marks sit on those atoms in the SVG, and
                 its rule lights the same atoms today (a curated part's ``expect`` included).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html as htmllib
import json
import math
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "data" / "snapshots"
RULINGS = Path(__file__).with_name("drawings_rulings.yaml")
DEFAULT_OUT = ROOT.parent / "trust-reports"
SITE = "https://moleculefinder.com"
SAMPLE = 40
SAMPLES_SHOWN = 10
USER_AGENT = "MoleculeFinder-trust-review/1 (+https://moleculefinder.com/about)"
FETCH_SECONDS = 60
FETCH_PAUSE = 0.5                       # between two page reads: a polite pace for a daily read of ~70 pages

# The survey's scope rule (scripts/extended_solids_review.py, 2026-11-26; tests hold the two equal).
METALS = {
    "Li", "Be", "Na", "Mg", "Al", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Cs", "Ba", "La", "Ce",
    "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir",
    "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cf", "B", "Si",
    "As", "Te",
}
EXTRA = {"bicarbonate", "dimenhydrinate", "povidone-iodine"}
S_BLOCK = {"Li", "Na", "K", "Rb", "Cs", "Fr", "Be", "Mg", "Ca", "Sr", "Ba", "Ra"}
DONORS = {"N", "O", "S", "Se", "P", "F", "Cl", "Br", "I"}
LATTICE_FAMILIES = ("inorganic", "mineral")
# A polymer record (check 4, one piece): its family, or its summary naming it a polymer or polysaccharide.
POLYMER_FAMILIES = ("polymer", "polysaccharide")
POLYMER_WORDS = re.compile(r"\b(polymers?|polysaccharides?)\b", re.IGNORECASE)

# fact -> (check number, heading, the recommended fix a queue item carries)
FACTS = {
    "atoms": (1, "Atoms", ("Compare the drawn structure with the record's formula and charge; a wrong drawing changes "
                          "only by a display structure or a deliberate recipe version, on a branch.")),
    "metal floating": (2, "Metal floating", ("Rule per record: draw the metal's bonds (structure_display.yaml "
                                            "metal_bonds) or allowlist it with the ruling's date and reason.")),
    "lattice as molecule": (3, "Lattice as molecule", ("Rule per record: the no-structure panel (structure_none.yaml) "
                                                      "or the discrete-inorganic allowlist, with the reason.")),
    "fragments": (4, "Fragments", ("Rule per record: a repeat unit or the panel for a mixture or polymer, or an "
                                  "allowlist entry with its reason.")),
    "classification": (5, "Classification", ("Classify the record in drawings_rulings.yaml `survey` (Cowork reads "
                                            "the chemistry).")),
    "seed": (6, "Seeds", ("Fix the seed entry or the record it names on a branch: the build would stop on it, or the "
                         "snapshot no longer carries what the seed makes.")),
    "stereo": (7, "Stereo", ("Compare the drawing's wedges with the record's stereocentres; a display structure "
                            "with `stereo_from`, or a redraw on a branch.")),
    "3D": (8, "3D against 2D", ("Set the page's 3D model off, or pin the model compound in drawings_rulings.yaml "
                               "`models` after reading it.")),
    "live": (9, "Live equals built", ("Compare the live page with the snapshot main holds: a deploy that did not "
                                     "go out, or a page that renders the drawing differently.")),
    "part layer": (10, "Part layers", ("Remake the part layer on a branch (the drawing guard lists it), or correct "
                                      "the seed's rule or expect.")),
}

_BOND_PATH = re.compile(r"<path class='bond-(\d+) atom-(\d+) atom-(\d+)' d='([^']*)'[^>]*?style='([^']*)'")
_ATOM_MARK = re.compile(r"class='atom-(\d+)'")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")
_RECT_BG = re.compile(r"<rect\b[^>]*#[Ff]{6}[^>]*>(?:\s*</rect>)?")     # the web's panelSvg / stripBg
_HEADER = "<!-- END OF HEADER -->\n"                                   # the web's composeLayer (lib/drawings.ts)
_FORMULA_PART = re.compile(r"([A-Z][a-z]?)(\d*)")
_CHARGE_END = re.compile(r"([+-])(\d*)$")
_VISIBLE_DROP = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


# ── reading ─────────────────────────────────────────────────────────────────────────────────────
def mol_of(smiles: str | None):
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")
    return Chem.MolFromSmiles(smiles) if smiles else None


def formula_counts(formula: str | None) -> tuple[Counter, int] | None:
    """(element counts, charge) of a formula in any order, with PubChem's and RDKit's trailing charge ("CHO3-" is
    O3 and 1-, "O4S-2" is 2-)."""
    if not formula:
        return None
    f = formula.replace(" ", "")
    charge = 0
    m = _CHARGE_END.search(f)
    if m:
        n = int(m.group(2) or 1)
        charge = n if m.group(1) == "+" else -n
        f = f[: m.start()]
    counts: Counter = Counter()
    for el, n in _FORMULA_PART.findall(f):
        counts[el] += int(n or 1)
    return counts, charge


def mol_counts(mol) -> tuple[Counter, int]:
    from rdkit import Chem
    from rdkit.Chem.rdMolDescriptors import CalcMolFormula

    counts, _ = formula_counts(CalcMolFormula(mol))
    return counts, Chem.GetFormalCharge(mol)


def svg_bonds(svg: str) -> dict[int, list[tuple[int, int, str, str]]]:
    """Bond index -> [(atom i, atom j, d, style)] for every path RDKit drew for that bond."""
    out: dict[int, list] = defaultdict(list)
    for m in _BOND_PATH.finditer(svg or ""):
        out[int(m.group(1))].append((int(m.group(2)), int(m.group(3)), m.group(4), m.group(5)))
    return out


def drawing_problems(svg: str, mol) -> list[str]:
    """Why the SVG does not draw ``mol``: a bond it draws that the structure lacks or names differently, a bond of
    the structure it does not draw, an atom it does not draw. Hydrogens RDKit adds to show stereo (an index past the
    structure's atoms) are allowed, each bonded to an atom of the structure."""
    from rdkit import Chem

    n, nb = mol.GetNumAtoms(), mol.GetNumBonds()
    out, drawn_pairs, seen_atoms = [], set(), set()
    chiral = any(a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED for a in mol.GetAtoms())
    extra: Counter = Counter()
    for k, paths in svg_bonds(svg).items():
        i, j = paths[0][0], paths[0][1]
        if i >= n or j >= n:
            if min(i, j) >= n:
                out.append(f"bond-{k} joins two atoms the structure does not have ({i}, {j})")
            elif not chiral:
                out.append(f"bond-{k} draws an atom ({max(i, j)}) the structure does not have, and it has no "
                           f"stereocentre a drawn hydrogen would show")
            extra[max(i, j)] += 1
            seen_atoms.add(min(i, j))
            continue
        seen_atoms |= {i, j}
        drawn_pairs.add((min(i, j), max(i, j)))
        if k >= nb:
            out.append(f"bond-{k} ({i}-{j}) is not a bond of the structure ({nb} bonds)")
            continue
        b = mol.GetBondWithIdx(k)
        if {b.GetBeginAtomIdx(), b.GetEndAtomIdx()} != {i, j}:
            out.append(f"bond-{k} joins {i}-{j}; the structure's bond {k} joins "
                       f"{b.GetBeginAtomIdx()}-{b.GetEndAtomIdx()}")
    want = {(min(b.GetBeginAtomIdx(), b.GetEndAtomIdx()), max(b.GetBeginAtomIdx(), b.GetEndAtomIdx()))
            for b in mol.GetBonds()}
    for a, b in sorted(want - drawn_pairs):
        out.append(f"the bond {mol.GetAtomWithIdx(a).GetSymbol()}{a}-{mol.GetAtomWithIdx(b).GetSymbol()}{b} "
                   f"is not drawn")
    out += [f"atom {e} (a drawn hydrogen) has {c} bonds" for e, c in sorted(extra.items()) if c > 1]
    seen_atoms |= {int(x) for x in _ATOM_MARK.findall(svg or "") if int(x) < n}
    for a in range(n):
        if a not in seen_atoms:
            out.append(f"atom {a} ({mol.GetAtomWithIdx(a).GetSymbol()}) is not drawn")
    return out


def bonded_in_svg(svg: str) -> set[int]:
    return {x for paths in svg_bonds(svg).values() for i, j, _, _ in paths for x in (i, j)}


def stereo_marks(svg: str, mol) -> int:
    """How many bonds the SVG draws as a wedge (filled) or a hash (three or more thin strokes), dative arrows
    (which RDKit fills too) left out."""
    from rdkit import Chem

    n = 0
    for k, paths in svg_bonds(svg).items():
        if k < mol.GetNumBonds() and mol.GetBondWithIdx(k).GetBondType() == Chem.BondType.DATIVE:
            continue
        if any(not st.startswith("fill:none") for _, _, _, st in paths) or len(paths) >= 3 and all("stroke-width:1.0px" in st for _, _, _, st in paths):
            n += 1
    return n


def specified_centres(mol) -> tuple[int, int]:
    """(specified, all) tetrahedral stereocentres."""
    from rdkit import Chem

    cs = Chem.FindMolChiralCenters(mol, includeUnassigned=True, useLegacyImplementation=False)
    return sum(1 for _, c in cs if c != "?"), len(cs)


def connectivity(mol) -> str:
    from rdkit import Chem

    m = Chem.Mol(mol)
    Chem.RemoveStereochemistry(m)
    return Chem.MolToSmiles(m)


def panel(svg: str) -> str:
    return _RECT_BG.sub("", svg or "")


def compose(svg: str, layer: str | None) -> str:
    at = svg.find(_HEADER)
    if not layer or at < 0:
        return svg
    i = at + len(_HEADER)
    return svg[:i] + layer + "\n" + svg[i:]


def visible_text(page: str) -> str:
    return " ".join(htmllib.unescape(_TAG.sub(" ", _VISIBLE_DROP.sub(" ", page))).split())


def norm(s: str | None) -> str:
    return " ".join(str(s or "").split())


def has_3d_control(page: str) -> bool:
    return 'aria-label="Structure view"' in page


# ── the survey's scope rule ─────────────────────────────────────────────────────────────────────
def in_scope(r: dict) -> bool:
    if r.get("scope_family") == "element":
        return False
    smi = r.get("isomeric_smiles") or ""
    m = mol_of(smi)
    if m is not None:
        els = {a.GetSymbol() for a in m.GetAtoms()}
        charged = any(a.GetFormalCharge() for a in m.GetAtoms())
        if "C" not in els or els & METALS or (len(smi.split(".")) > 1 and charged):
            return True
    return r.get("scope_family") in LATTICE_FAMILIES


# ── the run's findings ──────────────────────────────────────────────────────────────────────────
class Review:
    def __init__(self, rulings: dict):
        self.rulings = rulings
        self.findings: list[dict] = []
        self.denoms: dict[tuple[str, str], tuple[int, str]] = {}
        self.covered: dict[str, list[tuple[str, str, str]]] = defaultdict(list)   # ruling -> (fact, slug, shape)
        self.classified: dict[str, Counter] = {}
        self.notes: list[str] = []

    def denom(self, fact: str, surface: str, n: int, noun: str) -> None:
        self.denoms[(fact, surface)] = (n, noun)

    def allowed(self, slug: str, fact: str) -> str | None:
        for name, rule in (self.rulings.get("allow") or {}).items():
            if fact in (rule.get("covers") or []) and slug in (rule.get("records") or {}):
                return name
        return None

    def find(self, fact: str, surface: str, shape: str, slug: str, detail: str = "", *,
             allow_fact: str | None = None) -> None:
        ruling = self.allowed(slug, allow_fact) if allow_fact else None
        if ruling:
            self.covered[ruling].append((fact, slug, shape))
            return
        self.findings.append({"fact": fact, "surface": surface, "shape": shape, "slug": slug, "detail": detail})


def load_records(snap: Path) -> dict[str, dict]:
    recs = {p.stem: json.loads(p.read_text()) for p in sorted((snap / "molecules").glob("*.json"))}
    if not recs:
        raise FileNotFoundError(f"no molecule records under {snap / 'molecules'}")
    return recs


def _seeds():
    from ..transform import assemble, drawings

    return {
        "none": assemble._none_seed(),
        "display": assemble._display_seed(),
        "metal": assemble._metal_bonds_seed(),
        "units": drawings.load_repeat_seed(),
        "parts": drawings.load_parts_seed(),
        "notes": assemble._notes_seed(),          # the drawing-findings pass (2026-11-27): a true drawing's note
    }


# ── checks 1 to 4 and 7: every structure drawing ────────────────────────────────────────────────
def check_drawings(rv: Review, recs: dict, seeds: dict, pairs: dict) -> None:
    from rdkit import Chem

    from ..transform import structures

    drawn = {s: r for s, r in recs.items() if r.get("structure_svg")}
    units = {s: r for s, r in recs.items() if r.get("structure_repeat_unit")}
    rv.denom("atoms", "structure drawing", len(drawn), "drawings")
    rv.denom("atoms", "repeat unit", len(units), "repeat units")
    rv.denom("metal floating", "structure drawing", len(drawn), "drawings")
    rv.denom("lattice as molecule", "structure drawing", len(drawn), "drawings")
    rv.denom("stereo", "structure drawing", len(drawn), "drawings")
    multi = 0
    kinds: Counter = Counter()
    for slug, r in drawn.items():
        smi = structures.drawn_smiles(r)
        mol = mol_of(smi)
        svg = r["structure_svg"]
        if mol is None:
            rv.find("atoms", "structure drawing", "the drawn structure does not parse", slug, smi or "no SMILES")
            continue
        # 1. the drawing is drawn from this structure (its key), shows it, and it is the record's formula and charge
        if r.get("structure_svg_key") != structures.svg_key(smi):
            rv.find("atoms", "structure drawing", "the drawing's key is not its structure's", slug,
                    "structure_svg_key is not svg_key(drawn SMILES): the drawing may not be of this structure")
        probs = drawing_problems(svg, mol)
        if probs:
            rv.find("atoms", "structure drawing", "the SVG does not draw the structure", slug, "; ".join(probs[:4]))
        want = formula_counts(r.get("molecular_formula"))
        got = mol_counts(mol)
        if want is None:
            rv.find("atoms", "structure drawing", "the record has no formula to compare", slug)
        elif got != want:
            rv.find("atoms", "structure drawing", "the drawn structure is not the record's formula and charge", slug,
                    f"drawn {_fmt(got)}, record {r.get('molecular_formula')}")
        fc = (r.get("descriptors") or {}).get("formal_charge")
        if fc is not None and fc != got[1]:
            rv.find("atoms", "structure drawing", "the drawn charge is not the record's", slug,
                    f"drawn {got[1]:+d}, record formal_charge {fc:+d}")
        frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False)
        metal_entry = slug in seeds["metal"]
        # 2. a metal drawn floating
        bonded = bonded_in_svg(svg)
        for a in mol.GetAtoms():
            if a.GetSymbol() not in METALS or a.GetDegree() or a.GetIdx() in bonded or len(frags) < 2:
                continue
            others = [x for x in mol.GetAtoms() if x.GetIdx() != a.GetIdx()
                      and (x.GetSymbol() in DONORS or (x.GetSymbol() == "C" and x.GetFormalCharge() < 0))]
            if not others or metal_entry:
                continue
            shape = ("an s-block ion beside an anion" if a.GetSymbol() in S_BLOCK
                     else "a metal or metalloid beside atoms it could bond")
            rv.find("metal floating", "structure drawing", shape, slug,
                    f"{a.GetSymbol()}{a.GetFormalCharge():+d} drawn with no bond", allow_fact="metal-floating")
            break
        # 3. a lattice drawn as a molecule
        if r.get("scope_family") != "element" and not metal_entry:
            ch = any(x.GetSymbol() == "C" and x.GetTotalNumHs() > 0 for x in mol.GetAtoms())
            neutral_bonded = [f for f in frags if Chem.GetFormalCharge(f) == 0 and f.GetNumBonds() > 0]
            metal_cov = any(x.GetSymbol() in METALS and x.GetDegree() > 0 for f in neutral_bonded for x in f.GetAtoms())
            fam = r.get("scope_family") in LATTICE_FAMILIES
            if not ch and neutral_bonded and (metal_cov or fam):
                shape = ("a metal or metalloid drawn with covalent bonds" if metal_cov
                         else "an inorganic or mineral record drawn as a molecule")
                rv.find("lattice as molecule", "structure drawing", shape, slug,
                        " + ".join(Chem.MolToSmiles(f) for f in neutral_bonded)[:120], allow_fact="lattice")
        # 4. fragments
        if len(frags) > 1:
            multi += 1
            kind = fragment_kind(frags, r)
            kinds[kind] += 1
            if kind in ("a mixture or polymer", "unexplained"):
                rv.find("fragments", "structure drawing", kind, slug,
                        " . ".join(Chem.MolToSmiles(f) for f in frags)[:160], allow_fact="fragments")
        elif r.get("scope_family") in POLYMER_FAMILIES or POLYMER_WORDS.search(r.get("summary") or ""):
            # PubChem's record of a polymer is a monomer or a short piece; drawn alone it reads as the molecule.
            radicals = sum(x.GetNumRadicalElectrons() for x in mol.GetAtoms())
            rv.find("fragments", "structure drawing (one piece)", "a polymer record drawn as one molecule",
                    slug, f"family {r.get('scope_family')}, summary \"{r.get('summary')}\", {mol.GetNumHeavyAtoms()} "
                    f"heavy atoms" + (f", {radicals} unpaired electron(s) drawn" if radicals else ""),
                    allow_fact="fragments")
        # 7. stereo
        check_stereo(rv, slug, r, mol, svg, seeds)
    rv.denom("fragments", "structure drawing", multi, "drawings of more than one piece")
    rv.denom("fragments", "structure drawing (one piece)", len(drawn) - multi, "drawings of one piece")
    rv.classified["fragments"] = kinds
    # 1. repeat units: a fragment of a chain by design (named, not formula-checked); the SVG must draw the unit
    for slug, r in units.items():
        u = r["structure_repeat_unit"]
        mol = mol_of(u.get("smiles"))
        if mol is None:
            rv.find("atoms", "repeat unit", "the unit's SMILES does not parse", slug)
            continue
        probs = drawing_problems(u.get("svg") or "", mol)
        if probs:
            rv.find("atoms", "repeat unit", "the SVG does not draw the unit", slug, "; ".join(probs[:4]))
    rv.notes.append("Repeat units are fragments of a chain by design and are not held to the record's formula: "
                    + ", ".join(sorted(units)) + ".")
    # 1. a pair's second drawing (compare_drawings.json b_svg) draws the second molecule's structure
    with_b = {k: p for k, p in pairs.items() if p.get("b_svg")}
    rv.denom("atoms", "pair drawing", len(with_b), "pair drawings")
    for key, p in with_b.items():
        b = recs.get(p.get("b"))
        mol = mol_of(structures.drawn_smiles(b)) if b else None
        if mol is None:
            rv.find("atoms", "pair drawing", "the pair's second molecule is missing or does not parse", key)
            continue
        probs = drawing_problems(p["b_svg"], mol)
        if probs:
            rv.find("atoms", "pair drawing", "the SVG does not draw the second molecule", key, "; ".join(probs[:4]))


def _fmt(c: tuple[Counter, int]) -> str:
    counts, charge = c
    order = sorted(counts, key=lambda e: (e != "C", e != "H" if "C" in counts else False, e))
    s = "".join(f"{e}{counts[e] if counts[e] > 1 else ''}" for e in order)
    return s + (f"{'+' if charge > 0 else '-'}{abs(charge) if abs(charge) > 1 else ''}" if charge else "")


_BASIC_N = None
_ACID = None


def fragment_kind(frags, rec: dict) -> str:
    """A salt (every piece but water charged, or a neutral acid and a neutral base), a hydrate or solvate (water
    beside one piece or a salt), a mixture or polymer (two or more neutral pieces with carbon, not an acid and a
    base), or unexplained."""
    from rdkit import Chem

    global _BASIC_N, _ACID
    if _BASIC_N is None:
        _BASIC_N = Chem.MolFromSmarts("[NX3;!$(N-[C,S,P]=[O,S,N]);!$(N-a);!$([N]#*)]")
        _ACID = Chem.MolFromSmarts("[$([CX3](=O)[OX2H1]),$([SX4](=O)(=O)[OX2H1]),$([NX3H1](C=O)C=O),"
                                   "$([nH]),$([NH1]1C(=O)**C1=O),$([Cl,Br,I;H1])]")
    water = [f for f in frags if Chem.MolToSmiles(f) == "O"]
    rest = [f for f in frags if Chem.MolToSmiles(f) != "O"]
    if water and len(rest) <= 1:
        return "a hydrate or solvate"
    if rest and all(Chem.GetFormalCharge(f) != 0 for f in rest):
        return "a hydrate or solvate" if water else "a salt"
    neutral = [f for f in rest if Chem.GetFormalCharge(f) == 0]
    if len(neutral) == len(rest) == 2:
        base = {i for i, f in enumerate(neutral) if f.HasSubstructMatch(_BASIC_N)}
        acid = {i for i, f in enumerate(neutral) if f.HasSubstructMatch(_ACID)}
        if any(a != b for a in acid for b in base):
            return "a salt"
    if len(neutral) == len(rest) and len(rest) >= 2 and all(
            any(a.GetSymbol() == "C" for a in f.GetAtoms()) for f in rest):
        return "a mixture or polymer"
    return "unexplained"


def check_stereo(rv: Review, slug: str, r: dict, mol, svg: str, seeds: dict) -> None:
    drawn_spec, _ = specified_centres(mol)
    marks = stereo_marks(svg, mol)
    rec_mol = mol_of(r.get("isomeric_smiles"))
    rec_spec = specified_centres(rec_mol)[0] if rec_mol is not None else drawn_spec
    if rec_spec and not marks:
        rv.find("stereo", "structure drawing", "the record specifies centres the drawing shows none of", slug,
                f"{rec_spec} specified, no wedge or hash drawn")
    elif marks < drawn_spec:
        rv.find("stereo", "structure drawing", "fewer stereo marks than specified centres", slug,
                f"{drawn_spec} specified, {marks} marked")
    if drawn_spec > rec_spec and "stereo_from" not in (seeds["metal"].get(slug) or {}):
        rv.find("stereo", "structure drawing", "a centre drawn that the record does not specify", slug,
                f"drawn {drawn_spec}, record {rec_spec}, no stereo_from")
    if drawn_spec < rec_spec:
        rv.find("stereo", "structure drawing", "a centre the record specifies is not in the drawn structure", slug,
                f"drawn {drawn_spec}, record {rec_spec}")
    if marks and not drawn_spec:
        rv.find("stereo", "structure drawing", "a wedge drawn on a structure with no specified centre", slug,
                f"{marks} marked")


# ── check 5: the survey's classification is total ───────────────────────────────────────────────
def check_classification(rv: Review, recs: dict) -> None:
    survey = rv.rulings.get("survey") or {}
    scope = {s for s, r in recs.items() if in_scope(r)} | (EXTRA & set(recs))
    rv.denom("classification", "survey", len(scope), "records the survey's scope rule catches")
    for s in sorted(scope - set(survey)):
        rv.find("classification", "survey", "in the scope rule, not classified", s,
                f"family {recs[s].get('scope_family')}, SMILES {recs[s].get('isomeric_smiles')}"[:160])
    for s in sorted(set(survey) - set(recs)):
        rv.find("classification", "survey", "classified, not in the catalog", s)
    outside = sorted((set(survey) & set(recs)) - scope)
    if outside:
        rv.notes.append("Classified by the survey but outside its scope rule today (not a finding): "
                        + ", ".join(outside) + ".")
    rv.classified["survey"] = Counter(survey[s]["group"] for s in scope & set(survey))


# ── check 6: the seeds still true ───────────────────────────────────────────────────────────────
def check_seeds(rv: Review, recs: dict, seeds: dict) -> None:
    from ..transform import assemble, structures

    n = sum(len(seeds.get(k) or {}) for k in ("none", "display", "metal", "units", "notes")) \
        + len(seeds["parts"].get("molecules") or {})
    rv.denom("seed", "seed entry", n, "seed entries")

    def build_check(fn, *a):
        try:
            return fn(*a), None
        except SystemExit as e:                      # the build's own refusal
            return None, str(e)
        except Exception as e:                       # noqa: BLE001 (a seed that crashes its check is a finding)
            return None, f"{type(e).__name__}: {e}"

    for slug in seeds["none"]:
        r = recs.get(slug)
        if not r:
            rv.find("seed", "structure_none.yaml", "names a record that does not exist", slug)
            continue
        got, err = build_check(assemble.structure_none_for, slug, r.get("molecular_formula"))
        if err:
            rv.find("seed", "structure_none.yaml", "fails its build-time check", slug, err[:200])
        elif (r.get("structure_none") or {}).get("line") != got["line"] or \
                (r.get("structure_none") or {}).get("formula") != got.get("formula"):
            rv.find("seed", "structure_none.yaml", "the snapshot does not carry what the seed makes", slug)
        if r.get("structure_svg") or r.get("has_3d"):
            rv.find("seed", "structure_none.yaml", "the record still has a drawing or a 3D model", slug)
    for kind, table in (("structure_display.yaml molecules", seeds["display"]),
                        ("structure_display.yaml metal_bonds", seeds["metal"])):
        for slug in table:
            r = recs.get(slug)
            if not r:
                rv.find("seed", kind, "names a record that does not exist", slug)
                continue
            got, err = build_check(assemble.structure_display_for, slug, r.get("isomeric_smiles"))
            if err:
                rv.find("seed", kind, "fails its build-time check", slug, err[:200])
                continue
            have = r.get("structure_display") or {}
            if have.get("smiles") != got["smiles"] or norm(have.get("line")) != norm(got["line"]):
                rv.find("seed", kind, "the snapshot does not carry what the seed makes", slug)
            elif r.get("structure_svg") and r.get("structure_svg_key") != structures.svg_key(got["smiles"]):
                rv.find("seed", kind, "the drawing is not drawn from the display structure", slug)
    units = seeds["units"]
    for slug, spec in units.items():
        r = recs.get(slug)
        if not r:
            rv.find("seed", "repeat_units.yaml", "names a record that does not exist", slug)
            continue
        problems = repeat_unit_problems(slug, spec, r)
        for p in problems:
            rv.find("seed", "repeat_units.yaml", p, slug)
    for slug in (seeds.get("notes") or {}):
        r = recs.get(slug)
        if not r:
            rv.find("seed", "structure_notes.yaml", "names a record that does not exist", slug)
            continue
        got, err = build_check(assemble.structure_note_for, slug, bool(r.get("structure_svg")),
                               r.get("structure_display"))
        if err:
            rv.find("seed", "structure_notes.yaml", "fails its build-time check", slug, err[:200])
        elif norm((r.get("structure_note") or {}).get("line")) != norm(got["line"]):
            rv.find("seed", "structure_notes.yaml", "the snapshot does not carry what the seed makes", slug)
    for slug in (seeds["parts"].get("molecules") or {}):
        if slug not in recs:
            rv.find("seed", "structure_parts.yaml", "names a record that does not exist", slug)
    # The other way: a record carrying a seed's field the seed no longer has.
    for slug, r in recs.items():
        if r.get("structure_none") and slug not in seeds["none"]:
            rv.find("seed", "structure_none.yaml", "the record carries a panel the seed no longer names", slug)
        if r.get("structure_display") and slug not in seeds["display"] and slug not in seeds["metal"]:
            rv.find("seed", "structure_display.yaml", "the record carries a display structure the seed no longer "
                    "names", slug)
        if r.get("structure_repeat_unit") and slug not in units:
            rv.find("seed", "repeat_units.yaml", "the record carries a repeat unit the seed no longer names", slug)
        if r.get("structure_note") and slug not in (seeds.get("notes") or {}):
            rv.find("seed", "structure_notes.yaml", "the record carries a note the seed no longer names", slug)


def repeat_unit_problems(slug: str, spec: dict, r: dict) -> list[str]:
    """repeat_units.yaml's build-time checks (drawings.attach_repeat_units / repeat_unit_marks) without drawing: the
    linkage pattern and each further joint (`also`) match their counts, a group its count, a separate-units unit is
    its record's monomers opened into chains; and the snapshot carries exactly what the seed makes."""
    from ..transform import drawings

    mol = mol_of(spec.get("smiles"))
    if mol is None:
        return ["the unit's SMILES does not parse"]
    out = []
    try:
        _, _, marks = drawings.repeat_unit_marks(spec, mol)
    except drawings.DrawingSeedError as e:
        marks = None
        msg = str(e).replace("repeat unit linkage SMARTS matches", "the linkage pattern matches") \
            .replace("repeat unit group SMARTS matches", "the group pattern matches")
        out.append(f"fails its build-time check: {msg}")
    if r.get("structure_svg") and not spec.get("replaces"):
        out.append("fails its build-time check: the record has a structure and the unit does not `replace` it")
    if spec.get("replaces") and r.get("structure_svg"):
        out.append("the record kept its PubChem drawing although the unit replaces it")
    u = r.get("structure_repeat_unit") or {}
    if not u:
        out.append("the snapshot carries no repeat unit for it")
    elif u.get("key") != drawings.repeat_key(slug, spec) or u.get("smiles") != spec["smiles"]:
        out.append("the snapshot does not carry what the seed makes (its key or SMILES differs)")
    elif marks is not None and (sorted(u.get("linkage_atoms") or []) != sorted(marks["linkage_atoms"])
                                or (u.get("also") or []) != (marks.get("also") or [])):
        out.append("the shipped linkage atoms are not the pattern's")
    return out


# ── check 8: 3D against 2D ──────────────────────────────────────────────────────────────────────
def check_3d(rv: Review, recs: dict, seeds: dict) -> None:
    from ..transform import structures

    with3d = {s: r for s, r in recs.items() if r.get("has_3d")}
    rv.denom("3D", "3D model", len(with3d), "pages with a 3D model")
    models = {int(k): v for k, v in (rv.rulings.get("models") or {}).items()}
    for slug, r in with3d.items():
        d = r.get("structure_display") or {}
        if r.get("structure_none"):
            rv.find("3D", "3D model", "a 3D model on a no-structure panel page", slug)
        elif slug in seeds["metal"] or d.get("kind") == "metal_bonds":
            rv.find("3D", "3D model", "a 3D model on a metal-bonds page", slug)
        elif not r.get("structure_svg"):
            rv.find("3D", "3D model", "a 3D model on a page with no drawing", slug)
        elif d.get("model_cid"):
            m = models.get(int(d["model_cid"]))
            drawn = mol_of(structures.drawn_smiles(r))
            if not m:
                rv.find("3D", "3D model", "the model compound is not pinned", slug, f"model CID {d['model_cid']}")
            elif drawn is None or connectivity(mol_of(m["connectivity"])) != connectivity(drawn):
                rv.find("3D", "3D model", "the model compound's connectivity is not the drawing's", slug,
                        f"model CID {d['model_cid']}")
            if d.get("has_3d") is False:
                rv.find("3D", "3D model", "the record shows a 3D model its display structure says it has not", slug)
        elif structures.drawn_smiles(r) != r.get("isomeric_smiles"):
            rv.find("3D", "3D model", "the drawing is not the record's own structure, the model is", slug)


# ── check 10: part layers ───────────────────────────────────────────────────────────────────────
def _segments(d: str) -> list[tuple[float, float, float, float]]:
    """A path of straight segments (RDKit writes 'M x,y L x,y'; a wedge 'M .. L .. L .. Z') as segments."""
    nums = [float(x) for x in _NUM.findall(d)]
    pts = list(zip(nums[0::2], nums[1::2]))
    return [(*pts[i], *pts[i + 1]) for i in range(len(pts) - 1)]


def atom_marks(svg: str) -> dict[int, list[tuple[float, float]]]:
    """Where the SVG puts each atom's bond ends: the start of each bond path drawn from it and the end of each drawn
    towards it (a labelled atom's bonds stop short of its label)."""
    out: dict[int, list] = defaultdict(list)
    for paths in svg_bonds(svg).values():
        for i, j, d, st in paths:
            nums = [float(x) for x in _NUM.findall(d)]
            if len(nums) < 4 or not st.startswith("fill:none"):
                continue
            out[i].append((nums[0], nums[1]))
            out[j].append((nums[-2], nums[-1]))
    return out


def layer_marks(layer: str) -> tuple[list[tuple[float, float]], int]:
    """(the dots, the number of bands) of a part layer: drawings.layer writes 'M a L b' per bond, 'M a h0' per atom."""
    d = re.search(r"\bd='([^']*)'", layer or "")
    if not d:
        return [], 0
    dots = [(float(x), float(y)) for x, y in re.findall(r"M(-?[\d.]+),(-?[\d.]+)h0", d.group(1))]
    bands = len(re.findall(r"M-?[\d.]+,-?[\d.]+L", d.group(1)))
    return dots, bands


def bond_px(svg: str) -> float:
    """The drawing's median single-line bond length in pixels."""
    ls = sorted(math.dist(s[:2], s[2:]) for paths in svg_bonds(svg).values() if len(paths) == 1
                for i, j, d, st in paths if st.startswith("fill:none") for s in _segments(d)[:1])
    return ls[len(ls) // 2] if ls else 0.0


PART_SNAP = 0.75      # a dot sits within this share of a bond length of one of its atom's bond ends


def check_parts(rv: Review, recs: dict, seeds: dict) -> None:
    from ..transform import drawings, structures

    layers = sum(len((r.get("structure_parts") or {}).get("parts") or []) for r in recs.values())
    rv.denom("part layer", "part layer", layers, "part layers")
    for slug, r in recs.items():
        parts = (r.get("structure_parts") or {}).get("parts") or []
        if not parts:
            continue
        svg = r.get("structure_svg")
        mol = mol_of(structures.drawn_smiles(r))
        if not svg or mol is None:
            rv.find("part layer", "part layer", "a part layer on a record with no drawing", slug)
            continue
        n = mol.GetNumAtoms()
        marks = atom_marks(svg)
        scale = bond_px(svg) or 30.0
        for p in parts:
            pid = p.get("id")
            atoms, bonds = p.get("atoms") or [], [tuple(b) for b in p.get("bonds") or []]
            bad = [a for a in atoms if not (0 <= a < n)]
            nob = [b for b in bonds if not (max(b) < n and mol.GetBondBetweenAtoms(int(b[0]), int(b[1])))]
            if bad or nob:
                rv.find("part layer", "part layer", "lights an atom or bond the drawing does not have", slug,
                        f"{pid}: atoms {bad[:5]}, bonds {nob[:5]}")
                continue
            dots, bands = layer_marks(p.get("layer"))
            if len(dots) != len(atoms) or bands != len(bonds):
                rv.find("part layer", "part layer", "its marks are not its atoms and bonds", slug,
                        f"{pid}: {len(dots)} dots for {len(atoms)} atoms, {bands} bands for {len(bonds)} bonds")
                continue
            off = []
            for a, (x, y) in zip(atoms, dots):
                ends = marks.get(a)
                if ends and min(math.dist((x, y), e) for e in ends) > PART_SNAP * scale:
                    off.append(a)
            if off:
                rv.find("part layer", "part layer", "a mark sits away from its atom in the drawing", slug,
                        f"{pid}: atoms {off[:6]}")
        # the rule lights the same atoms today (a curated part's `expect` included)
        try:
            now = drawings.find_parts(mol, slug, seeds["parts"])
        except drawings.DrawingSeedError as e:
            rv.find("part layer", "part layer", "a curated part no longer matches its expect", slug, str(e)[:200])
            continue
        have = [(p.get("id"), sorted(p.get("atoms") or [])) for p in parts]
        want = [(p["id"], sorted(p["atoms"])) for p in now]
        if have != want:
            rv.find("part layer", "part layer", "the seed's rule no longer lights what the layer lights", slug,
                    f"shipped {[h[0] for h in have]}, rule {[w[0] for w in want]}")


# ── check 9: live equals built ──────────────────────────────────────────────────────────────────
def pinned_pages(rv: Review, recs: dict, seeds: dict) -> dict[str, str]:
    out = {}
    for slug, why in (rv.rulings.get("pinned") or {}).items():
        out[slug] = why
    for slug in seeds["none"]:
        out[slug] = "A no-structure panel (structure_none.yaml): no drawing, the panel's line."
    for slug in seeds["display"]:
        out[slug] = "A sugar drawn as its ring (structure_display.yaml): the drawing and its notes line."
    for slug in seeds["metal"]:
        out[slug] = "A metal drawn with its bonds (structure_display.yaml metal_bonds): the drawing, the line, no 3D."
    for slug in seeds["units"]:
        out[slug] = "A repeat unit (repeat_units.yaml): the unit's drawing and its words."
    for slug in seeds.get("notes") or {}:
        out[slug] = "A true drawing with its note (structure_notes.yaml): the drawing and the note's line."
    return {s: w for s, w in out.items() if s in recs}


def sample_pages(recs: dict, pinned: set, day: dt.date, k: int = SAMPLE) -> list[str]:
    """``k`` molecule pages outside the pinned set, drawn by a seed made from the date: the same list all day, a
    different one the next."""
    seed = int(hashlib.sha256(f"moleculefinder-drawings-{day.isoformat()}".encode()).hexdigest()[:16], 16)
    pool = sorted(set(recs) - pinned)
    return sorted(random.Random(seed).sample(pool, min(k, len(pool))))


def fetch_page(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=FETCH_SECONDS) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, ""
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise
            time.sleep(5)
    raise OSError("unreachable")


def seed_line(slug: str, seeds: dict) -> tuple[str, str] | None:
    """(which seed, the line the page must print) for a record a seed gives a notes line."""
    for kind, table in (("structure_none.yaml", seeds["none"]), ("structure_display.yaml", seeds["display"]),
                        ("structure_display.yaml metal_bonds", seeds["metal"]), ("repeat_units.yaml", seeds["units"]),
                        ("structure_notes.yaml", seeds.get("notes") or {})):
        e = table.get(slug) or {}
        if e.get("line"):
            return kind, norm(e["line"])
    return None


def live_problems(r: dict, page: str, seeds: dict) -> list[tuple[str, str]]:
    """(shape, detail) for each way the served page differs from the snapshot and the seeds."""
    out = []
    slug = r["slug"]
    svg = r.get("structure_svg")
    disp = r.get("structure_display") or {}
    shows_drawing = 'class="v3__2d"' in page
    if svg:
        if panel(svg) not in page:
            out.append(("the drawing served is not the snapshot's", "the snapshot's SVG is not in the page"))
        want3d = r.get("has_3d") is not False and disp.get("has_3d") is not False
        if has_3d_control(page) != want3d:
            out.append(("the 3D control does not match the record",
                        f"control {'shown' if has_3d_control(page) else 'missing'}, has_3d {r.get('has_3d')}"))
    else:
        if shows_drawing:
            out.append(("a drawing is served on a page with none", "class v3__2d on the page"))
        if has_3d_control(page):
            out.append(("the 3D control does not match the record", "a 3D control on a page with no drawing"))
    u = r.get("structure_repeat_unit")
    if u and u.get("svg") and compose(panel(u["svg"]), u.get("layer")) not in page:
        out.append(("the repeat unit served is not the snapshot's", "the composed unit SVG is not in the page"))
    sl = seed_line(slug, seeds)
    if sl and sl[1] not in visible_text(page):
        out.append(("the notes line is not the seed's", f"{sl[0]}'s line is not on the page"))
    return out


def check_live(rv: Review, recs: dict, seeds: dict, day: dt.date, fetch=fetch_page, site: str = SITE,
               pause: float = FETCH_PAUSE) -> dict:
    pinned = pinned_pages(rv, recs, seeds)
    sampled = sample_pages(recs, set(pinned), day)
    pages = [(s, "pinned", pinned[s]) for s in sorted(pinned)] + [(s, "sampled", "") for s in sampled]
    read, not_read = [], []
    for i, (slug, how, _) in enumerate(pages):
        url = f"{site}/m/{slug}"
        try:
            status, page = fetch(url)
        except Exception as e:                       # noqa: BLE001 (a page it cannot read is "not read", never 0)
            not_read.append({"slug": slug, "why": f"{type(e).__name__}: {e}"[:160]})
            continue
        finally:
            if pause and i < len(pages) - 1:
                time.sleep(pause)
        if status != 200 or not page:
            not_read.append({"slug": slug, "why": f"HTTP {status}"})
            continue
        read.append(slug)
        for shape, detail in live_problems(recs[slug], page, seeds):
            rv.find("live", "page (live)", shape, slug, detail)
    rv.denom("live", "page (live)", len(read), "pages read live")
    return {"pinned": pinned, "sampled": sampled, "read": read, "not_read": not_read,
            "seed": f"moleculefinder-drawings-{day.isoformat()}"}


# ── the report ──────────────────────────────────────────────────────────────────────────────────
def class_key(f: dict) -> str:
    return f"{f['fact']} / {f['surface']} / {f['shape']}"


def summarise(rv: Review) -> dict[str, dict]:
    classes: dict[str, dict] = {}
    for f in rv.findings:
        k = class_key(f)
        c = classes.setdefault(k, {"fact": f["fact"], "surface": f["surface"], "shape": f["shape"],
                                   "records": [], "details": {}})
        if f["slug"] not in c["records"]:
            c["records"].append(f["slug"])
            c["details"][f["slug"]] = f["detail"]
    for k, c in classes.items():
        n, noun = rv.denoms.get((c["fact"], c["surface"]), (None, "items"))
        c["count"], c["of"], c["noun"] = len(c["records"]), n, noun
    order = {f: FACTS[f][0] for f in FACTS}
    return dict(sorted(classes.items(), key=lambda kv: (order.get(kv[1]["fact"], 99), kv[0])))


def previous_report(out: Path, day: dt.date) -> dict | None:
    best = None
    for p in out.glob("drawings-*.json"):
        m = re.fullmatch(r"drawings-(\d{4}-\d\d-\d\d)\.json", p.name)
        if m and m.group(1) < day.isoformat() and (best is None or m.group(1) > best[0]):
            best = (m.group(1), p)
    if not best:
        return None
    try:
        return json.loads(best[1].read_text())
    except (OSError, ValueError):
        return None


def queue_new(out: Path, classes: dict, prev: dict | None, day: dt.date) -> list[str]:
    """Append each class present on this run and the one before to QUEUE.md, once (a marker per class)."""
    if not prev:
        return []
    q = out / "QUEUE.md"
    text = q.read_text() if q.exists() else ("# Trust reviews: the queue\n\nOne line per finding class seen on two "
                                             "consecutive runs, added once, the day it qualifies. Tick it when the "
                                             "fix is merged or a ruling covers it.\n\n")
    added = []
    for k, c in classes.items():
        marker = f"<!-- drawings: {k} -->"
        if k in (prev.get("classes") or {}) and marker not in text:
            line = (f"- [ ] {day.isoformat()} drawings: **{k}**: {c['count']} of {c['of']} {c['noun']} "
                    f"({', '.join(c['records'][:5])}{', ...' if c['count'] > 5 else ''}). "
                    f"Recommended: {FACTS[c['fact']][2]} {marker}")
            text += line + "\n"
            added.append(k)
    if added:
        q.write_text(text)
    return added


def etl_commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], check=False,
                              capture_output=True,
                              text=True, timeout=10).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def verdict_line(classes: dict, n_records: int, live: dict | None) -> str:
    recs = len({s for c in classes.values() for s in c["records"]})
    read = f"{len(live['read'])} pages read live" if live else "live pages not checked (--no-live)"
    nr = f"{len(live['not_read'])} pages not read" if live else "live pages not read: all"
    return (f"VERDICT: {len(classes)} finding class{'es' if len(classes) != 1 else ''} found ({recs} "
            f"record{'s' if recs != 1 else ''}); {n_records} records read; {read}; {nr}.")


def write_report(out: Path, day: dt.date, rv: Review, recs: dict, live: dict | None, meta: dict) -> dict:
    classes = summarise(rv)
    prev = previous_report(out, day)
    pc = (prev or {}).get("classes") or {}
    for k, c in classes.items():
        before = pc.get(k)
        c["change"] = ("first run" if prev is None else "new" if before is None
                       else f"{c['count'] - before['count']:+d}")
        if before:
            c["added"] = sorted(set(c["records"]) - set(before["records"]))
            c["left"] = sorted(set(before["records"]) - set(c["records"]))
    gone = sorted(set(pc) - set(classes)) if prev else []
    verdict = verdict_line(classes, len(recs), live)
    queued = queue_new(out, classes, prev, day)
    allow = rv.rulings.get("allow") or {}
    data = {
        "verdict": verdict, "date": day.isoformat(), "time": meta["time"], "etl_commit": meta["commit"],
        "snapshot_refreshed": meta["refreshed"], "records": len(recs),
        "classes": classes, "gone_since_last_run": gone, "previous_run": (prev or {}).get("date"),
        "denominators": {f"{f} / {s}": {"n": n, "of": noun} for (f, s), (n, noun) in rv.denoms.items()},
        "covered_by_rulings": {k: [{"fact": f, "slug": s, "shape": sh} for f, s, sh in v]
                               for k, v in rv.covered.items()},
        "allowlists": {k: len(v.get("records") or {}) for k, v in allow.items()},
        "classified": {k: dict(v) for k, v in rv.classified.items()},
        "live": live, "queued_today": queued, "notes": rv.notes,
    }
    md = render_md(data)
    (out / f"drawings-{day.isoformat()}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    (out / f"drawings-{day.isoformat()}.md").write_text(md)
    return data


def render_md(d: dict) -> str:
    L = [d["verdict"], "", f"# Drawing truth, {d['date']}", ""]
    w = L.append
    w(f"Trust review 3 (`mfetl review drawings`, ETL `moleculefinder_etl/review/drawings.py`), run {d['time']} "
      f"against the snapshot ETL `{d['etl_commit']}` holds (refreshed {d['snapshot_refreshed']}). Read-only: it "
      f"changed nothing. Previous run: {d['previous_run'] or 'none (this is the first)'}.")
    w("")
    w("## Findings, class by class")
    w("")
    if not d["classes"]:
        w("None.")
    for k, c in d["classes"].items():
        w(f"### {k}")
        w(f"- **{c['count']} of {c['of']} {c['noun']}**; since the last run: {c['change']}"
          + (f" (in: {', '.join(c['added'])})" if c.get("added") else "")
          + (f" (out: {', '.join(c['left'])})" if c.get("left") else ""))
        for s in c["records"][:SAMPLES_SHOWN]:
            det = c["details"].get(s)
            addr = f"{SITE}/m/{s}" if "-vs-" not in s else f"{SITE}/vs/{s}"
            w(f"  - {addr}" + (f": {det}" if det else ""))
        if c["count"] > SAMPLES_SHOWN:
            w(f"  - and {c['count'] - SAMPLES_SHOWN} more (the JSON lists every one)")
        w(f"- Recommended: {FACTS[c['fact']][2]}")
        w("")
    if d["gone_since_last_run"]:
        w("Classes found last run and not this run: " + "; ".join(d["gone_since_last_run"]) + ".")
        w("")
    if d["queued_today"]:
        w("Added to QUEUE.md today (seen on two consecutive runs): " + "; ".join(d["queued_today"]) + ".")
        w("")
    w("## What each check read")
    w("")
    w("| check | surface | read |")
    w("|---|---|---|")
    for key, v in d["denominators"].items():
        fact, surface = key.split(" / ", 1)
        w(f"| {FACTS[fact][0]}. {FACTS[fact][1]} | {surface} | {v['n']} {v['of']} |")
    w("")
    w("## Covered by a ruling (not findings)")
    w("")
    for name, size in d["allowlists"].items():
        hits = d["covered_by_rulings"].get(name, [])
        by_fact = Counter(h["fact"] for h in hits)
        w(f"- `{name}` ({size} records on the list): covered today "
          + (", ".join(f"{n} {f}" for f, n in sorted(by_fact.items())) or "nothing") + ".")
    w("")
    for kind, counts in d["classified"].items():
        w(f"Classified ({kind}): " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + ".")
    w("")
    lv = d["live"]
    if lv:
        w("## Pages read live")
        w("")
        w(f"{len(lv['read'])} read, {len(lv['not_read'])} not read, of {len(lv['pinned']) + len(lv['sampled'])} "
          f"({len(lv['pinned'])} pinned, {len(lv['sampled'])} sampled by the seed `{lv['seed']}`).")
        for x in lv["not_read"]:
            w(f"- NOT READ {SITE}/m/{x['slug']}: {x['why']}")
        w("")
        w("Pinned, each with its reason:")
        for s, why in sorted(lv["pinned"].items()):
            w(f"- `{s}`: {why}")
        w("")
        w("Sampled today: " + ", ".join(f"`{s}`" for s in lv["sampled"]) + ".")
        w("")
    for n in d["notes"]:
        w(f"Note: {n}")
    return "\n".join(L).rstrip() + "\n"


def heartbeat(out: Path, state: str, verdict: str, exit_code: int, report: str | None = None,
              reason: str | None = None) -> None:
    hb = {"time": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "state": state,
          "verdict": verdict, "exit": exit_code}
    if report:
        hb["report"] = report
    if reason:
        hb["reason"] = reason
    (out / "drawings-last-run.json").write_text(json.dumps(hb, indent=2) + "\n")


def run(snap: Path = SNAP, out: Path = DEFAULT_OUT, day: dt.date | None = None, live: bool = True,
        fetch=fetch_page, site: str = SITE, pause: float = FETCH_PAUSE, rulings_path: Path = RULINGS) -> dict:
    day = day or dt.date.today()
    rulings = yaml.safe_load(rulings_path.read_text())
    recs = load_records(snap)
    seeds = _seeds()
    pairs = json.loads((snap / "compare_drawings.json").read_text()).get("pairs") or {}
    meta = {"time": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "commit": etl_commit(),
            "refreshed": json.loads((snap / "meta.json").read_text()).get("refreshed")}
    rv = Review(rulings)
    check_drawings(rv, recs, seeds, pairs)
    check_classification(rv, recs)
    check_seeds(rv, recs, seeds)
    check_3d(rv, recs, seeds)
    check_parts(rv, recs, seeds)
    lv = check_live(rv, recs, seeds, day, fetch=fetch, site=site, pause=pause) if live else None
    out.mkdir(parents=True, exist_ok=True)
    return write_report(out, day, rv, recs, lv, meta)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mfetl review drawings", description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="the reports folder (default: ../trust-reports)")
    p.add_argument("--snapshot", type=Path, default=SNAP, help="the snapshot to read (default: this checkout's)")
    p.add_argument("--no-live", action="store_true", help="skip check 9 (the live site)")
    p.add_argument("--date", type=dt.date.fromisoformat, default=None, help="the run's date (default: today)")
    a = p.parse_args(argv)
    out = a.out
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"review drawings: could not run: the reports folder {out}: {e}", file=sys.stderr)
        return 2
    try:
        data = run(snap=a.snapshot, out=out, day=a.date, live=not a.no_live)
    except Exception as e:                          # noqa: BLE001 (could not run: say why, exit non-zero)
        why = f"{type(e).__name__}: {e}"
        heartbeat(out, "could not run", f"COULD NOT RUN: {why}"[:400], 2, reason=why[:400])
        print(f"review drawings: could not run: {why}", file=sys.stderr)
        return 2
    report = str(out / f"drawings-{data['date']}.md")
    heartbeat(out, "ran", data["verdict"], 0, report=report)
    print(data["verdict"])
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
