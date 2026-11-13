"""Phase 5A (2026-11-12): drawing recipes beside the structure recipe. Parts of a molecule,
comparison pairs and repeat units.

All three rest on one rule: **nothing redraws a shipped structure.** The shipped drawing
(``structure_svg``) is a stored artifact, laid out by whichever machine and RDKit release drew it
(``structures`` docstring). A highlight is a small layer under that drawing, placed at atom
positions read from the drawing itself (``svg_geometry.read_positions``, proven per drawing); the
second molecule of a pair is drawn new, in the first molecule's frame; a repeat unit is a new
drawing of a curated fragment for a polymer that has no structure. Each output has its own recipe
version and reuse key; a current key is carried forward byte for byte, a palette change repaints
(never redraws) the new drawings, and only a version bump draws again. The reasons and the
numbers: ``docs/DRAWING-RECIPES.md``.

Parts (``structure_parts`` on a molecule record). Found by rule, never by atom number: SMARTS in
``sources/seeds/structure_parts.yaml`` (the default set is the /in hubs' functional groups,
``categories.FUNCTIONAL_GROUPS``, plus the ring system; most specific first; at most three a
molecule). A molecule can carry curated parts instead, with a label and a sentence each.

Pairs (``compare_drawings.json``). For each /vs pair the largest common core (RDKit's MCS) is
found. The first molecule keeps its shipped drawing; the second is laid out with its core atoms
pinned to the first drawing's positions and drawn at the first drawing's scale, then moved so the
core atoms land on the same pixels. A small difference is highlighted on both. Thresholds:
``ALIGN_MIN_ATOMS``, ``ALIGN_MIN_SHARE``, ``HIGHLIGHT_MAX_ATOMS``.

Repeat units (``structure_repeat_unit`` on a hand-modelled polymer's record). A curated two-unit
SMILES (``sources/seeds/repeat_units.yaml``), drawn with the linkage highlighted.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from pathlib import Path

import yaml

from . import structures, svg_geometry
from .categories import FUNCTIONAL_GROUPS

log = logging.getLogger("mfetl")

SEEDS_DIR = Path(__file__).resolve().parent.parent / "sources" / "seeds"
PARTS_YAML = SEEDS_DIR / "structure_parts.yaml"
COMPARE_YAML = SEEDS_DIR / "compare_drawings.yaml"
REPEAT_YAML = SEEDS_DIR / "repeat_units.yaml"

# Bump a version when anything that decides its output changes (a threshold, the layer's look,
# the matching). Every output of that recipe is then made again on the next run.
PARTS_RECIPE = "2026-11-12.1"
PAIRS_RECIPE = "2026-11-12.1"
REPEAT_RECIPE = "2026-11-12.1"

# The one amber: the site's --found (web app/globals.css), the colour of the chain and of every
# comparison highlight in the approved mockups. A layer is drawn under the molecule, at this
# opacity, so the atom labels and bonds above it stay their own colours.
AMBER = "#E9A23B"
HIGHLIGHT_OPACITY = 0.55
# The band's width, as a share of the drawing's bond length, held between a floor (a 400-atom
# peptide drawn at 8 px a bond still shows its part) and a ceiling (ethanol, drawn at 146 px a
# bond, does not turn into a blob).
HIGHLIGHT_WIDTH = (0.4, 3.0, 24.0)

# Pairs. Align on the common core when it has at least ALIGN_MIN_ATOMS heavy atoms (three fix an
# orientation; fewer is a bond, not a shape) and at least ALIGN_MIN_SHARE of the larger molecule's
# heavy atoms (two big molecules sharing one benzene ring are not "the same skeleton", and turning
# one to match the other's ring would say they are). Highlight when the atoms outside the core,
# both sides together, number 1 to HIGHLIGHT_MAX_ATOMS: a methyl, a hydroxyl, an ethyl, a chlorine;
# past that the difference is a second structure, not a group, and the eye reads it unaided.
ALIGN_MIN_ATOMS = 3
ALIGN_MIN_SHARE = 0.4
HIGHLIGHT_MAX_ATOMS = 4
# Molecules past this many heavy atoms (the large peptides) are not searched for a common core: in
# a 400 by 300 frame their drawings are a texture, not a shape to line up, and the search can run
# for minutes. A size rule, not a timeout, so the answer never depends on the machine's speed.
ALIGN_MAX_ATOMS = 120
# A backstop only: no catalog pair under ALIGN_MAX_ATOMS comes near it (the slowest takes under a
# second). A pair that hits it shows its shipped drawings, and the log says so.
MCS_TIMEOUT = 60
# The shipped canvas. The second drawing is laid out on a larger one, so a molecule bigger than
# the first never shrinks to fit; when it reaches past the first's canvas, the pair carries a
# shared `frame` (a viewBox) that both drawings are shown in, the first drawing's paths untouched.
CANVAS = (400, 300)
FRAME_PAD = (20.0, 15.0)        # RDKit's own padding at 400 by 300 (5 percent a side)
# Every core atom of the second drawing must land within this of the first's (the proof).
ALIGN_TOLERANCE_PX = 1.0

_HEADER = "<!-- END OF HEADER -->\n"
_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")


# ── Keys ─────────────────────────────────────────────────────────────────────────────────────
def _sha(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def geometry_sha(svg: str) -> str:
    """A drawing's fingerprint without its colours: a palette repaint does not change it, any
    moved coordinate does. A highlight layer rests on the geometry only."""
    return _sha(_COLOUR.sub("", svg))


# ── The layer ────────────────────────────────────────────────────────────────────────────────
def _w(scale_px: float | None) -> float:
    share, lo, hi = HIGHLIGHT_WIDTH
    return round(min(max(share * (scale_px or 60.0), lo), hi), 1)


def layer(pos: dict[int, tuple[float, float]], atoms: list[int], bonds: list[tuple[int, int]],
          scale_px: float | None, cls: str = "mf-part") -> str:
    """One amber path: a band along each bond and a dot on each atom (a zero-length segment with
    a round cap), in the drawing's own pixels. One path, so overlaps never darken."""
    def p(i):
        x, y = pos[i]
        return f"{x:.1f},{y:.1f}"
    d = "".join(f"M{p(a)}L{p(b)}" for a, b in bonds) + "".join(f"M{p(a)}h0" for a in atoms)
    return (f"<path class='{cls}' d='{d}' style='fill:none;stroke:{AMBER};"
            f"stroke-width:{_w(scale_px)}px;stroke-linecap:round;stroke-linejoin:round;"
            f"stroke-opacity:{HIGHLIGHT_OPACITY}' />")


def compose(svg: str, layer_svg: str) -> str:
    """The drawing with ``layer_svg`` under it: inserted after RDKit's header, before any path."""
    i = svg.index(_HEADER) + len(_HEADER)
    return svg[:i] + layer_svg + "\n" + svg[i:]


def strip(composed: str, layer_svg: str) -> str:
    """``compose`` undone: the drawing exactly as it was."""
    return composed.replace(layer_svg + "\n", "", 1)


# ── Parts ────────────────────────────────────────────────────────────────────────────────────
class DrawingSeedError(ValueError):
    pass


def load_parts_seed(path: Path = PARTS_YAML) -> dict:
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    return data or {}


def _ring_system(mol) -> tuple[list[int], list[tuple[int, int]]]:
    """The largest ring system: rings that share an atom, joined; its atoms and ring bonds."""
    rings = [set(r) for r in mol.GetRingInfo().AtomRings()]
    systems: list[set[int]] = []
    for r in rings:
        joined = [s for s in systems if s & r]
        for s in joined:
            systems.remove(s)
            r = r | s
        systems.append(r)
    if not systems:
        return [], []
    best = max(systems, key=lambda s: (len(s), -min(s)))
    bonds = [(b.GetBeginAtomIdx(), b.GetEndAtomIdx()) for b in mol.GetBonds()
             if b.IsInRing() and b.GetBeginAtomIdx() in best and b.GetEndAtomIdx() in best]
    return sorted(best), sorted(tuple(sorted(b)) for b in bonds)


def _match(mol, spec: dict) -> tuple[list[int], list[tuple[int, int]], int]:
    """(atoms, bonds, number of matches) a part spec lights in ``mol``."""
    from rdkit import Chem

    if spec.get("rule") == "ring-system":
        atoms, bonds = _ring_system(mol)
        return atoms, bonds, 1 if atoms else 0
    smarts = spec.get("smarts") or FUNCTIONAL_GROUPS.get(spec.get("group", ""))
    q = Chem.MolFromSmarts(smarts) if smarts else None
    if q is None:
        raise DrawingSeedError(f"part {spec.get('id')!r}: no usable SMARTS")
    light = spec.get("light")
    touching = spec.get("bonds", "within") == "touching"
    atoms: set[int] = set()
    bonds: set[tuple[int, int]] = set()
    matches = mol.GetSubstructMatches(q, uniquify=True, maxMatches=10000)
    for m in matches:
        lit = {m[k] for k in light} if light is not None else set(m)
        atoms |= lit
        for qb in q.GetBonds():
            a, b = m[qb.GetBeginAtomIdx()], m[qb.GetEndAtomIdx()]
            if (a in lit and b in lit) or (touching and (a in lit or b in lit)):
                bonds.add(tuple(sorted((a, b))))
    return sorted(atoms), sorted(bonds), len(matches)


def _isolated(mol) -> set[int]:
    return {a.GetIdx() for a in mol.GetAtoms() if a.GetDegree() == 0}


def find_parts(mol, slug: str, seed: dict) -> list[dict]:
    """The parts a molecule shows, found by rule (see the module docstring). Raises
    ``DrawingSeedError`` when a curated part no longer matches what it says it matches."""
    curated = (seed.get("molecules") or {}).get(slug)
    iso = _isolated(mol)
    heavy = {a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() > 1} - iso
    out: list[dict] = []
    if curated:
        for spec in curated.get("parts") or []:
            atoms, bonds, n = _match(mol, spec)
            atoms = [a for a in atoms if a not in iso]
            exp = spec.get("expect") or {}
            if not atoms or ("matches" in exp and n != exp["matches"]) \
                    or ("atoms" in exp and len(atoms) != exp["atoms"]):
                raise DrawingSeedError(
                    f"{slug}: curated part {spec.get('id')!r} expects {exp or 'a match'}, "
                    f"finds {n} match(es) lighting {len(atoms)} atom(s); read the part again")
            out.append(_part(spec, atoms, bonds, curated=True))
        return out
    chosen: set[int] = set()
    for spec in seed.get("defaults") or []:
        if len(out) >= int(seed.get("max_parts", 3)):
            break
        atoms, bonds, n = _match(mol, spec)
        atoms = [a for a in atoms if a not in iso]
        bonds = [b for b in bonds if b[0] not in iso and b[1] not in iso]
        if not atoms or set(atoms) >= heavy or set(atoms) <= chosen:
            continue
        chosen |= set(atoms)
        out.append(_part(spec, atoms, bonds, curated=False))
    return out


def _part(spec: dict, atoms, bonds, *, curated: bool) -> dict:
    return {
        "id": spec["id"],
        "rule": spec.get("rule") or (f"group:{spec['group']}" if spec.get("group") else "smarts"),
        "label": spec.get("label"),
        "sentence": spec.get("sentence"),
        "from": spec.get("from"),
        "atoms": list(atoms),
        "bonds": [list(b) for b in bonds],
        "confidence": "from_source" if curated else "computed",
        "source": "MoleculeFinder curated" if curated else "MoleculeFinder rule (RDKit SMARTS)",
    }


# ── Readings, cached for the run ─────────────────────────────────────────────────────────────
_READINGS: dict[str, svg_geometry.Reading | None] = {}


def reading_for(rec: dict):
    """The proven atom positions of a record's shipped drawing, or None (no drawing, or one whose
    positions no proof holds for; ``svg_geometry.read_positions``). Cached by drawing."""
    from rdkit import Chem

    svg, smi = rec.get("structure_svg"), rec.get("isomeric_smiles")
    if not svg or not smi:
        return None
    k = _sha(geometry_sha(svg), smi)
    if k not in _READINGS:
        try:
            _READINGS[k] = svg_geometry.read_positions(svg, Chem.MolFromSmiles(smi))
        except (svg_geometry.UnreadableDrawing, ValueError) as e:
            log.warning("  drawings: %s's shipped drawing has no proven atom positions (%s); "
                        "it gets no highlight", rec.get("slug"), e)
            _READINGS[k] = None
    return _READINGS[k]


def parts_key(rec: dict, parts: list[dict]) -> str:
    return _sha(PARTS_RECIPE, geometry_sha(rec["structure_svg"]), rec["isomeric_smiles"],
                json.dumps(parts, sort_keys=True, ensure_ascii=False))


def attach_structure_parts(records: list[dict], prior: dict[int, dict] | None = None,
                           seed: dict | None = None) -> dict[str, int]:
    """``structure_parts`` on every record with a shipped drawing: {key, recipe, parts: [...,
    with ``layer``]}, or None when no rule lights anything. A drawing with no proven positions
    gets {key, recipe, parts: [], unread: why} (the web shows no part). A record whose prior key is
    current keeps its prior field byte for byte; only a changed drawing, rule or recipe makes a
    layer again, so a run on another machine never reads a shipped drawing at all."""
    from rdkit import Chem

    seed = load_parts_seed() if seed is None else seed
    prior = prior or {}
    counts = {"carried": 0, "made": 0, "none": 0, "unreadable": 0}
    for rec in records:
        svg, smi = rec.get("structure_svg"), rec.get("isomeric_smiles")
        if not svg or not smi:
            rec["structure_parts"] = None
            counts["none"] += 1
            continue
        parts = find_parts(Chem.MolFromSmiles(smi), rec["slug"], seed)
        if not parts:
            rec["structure_parts"] = None
            counts["none"] += 1
            continue
        key = parts_key(rec, parts)
        old = (prior.get(rec.get("cid")) or {}).get("structure_parts")
        if old and old.get("key") == key:
            rec["structure_parts"] = old
            counts["unreadable" if old.get("unread") else "carried"] += 1
            continue
        rd = reading_for(rec)
        if rd is None:
            # Recorded under its key like any other result, so the next run carries it instead of
            # trying again: a run on another machine (whose RDKit might happen to redraw this one
            # byte for byte) must not quietly start highlighting it.
            rec["structure_parts"] = {"key": key, "recipe": PARTS_RECIPE, "parts": [],
                                      "unread": "the shipped drawing's atom positions are not proven"}
            counts["unreadable"] += 1
            continue
        for p in parts:
            p["layer"] = layer(rd.pos, p["atoms"], [tuple(b) for b in p["bonds"]], rd.scale_px)
        rec["structure_parts"] = {"key": key, "recipe": PARTS_RECIPE, "parts": parts}
        counts["made"] += 1
    log.info("  structure parts: %d carried, %d made, %d with no part, %d drawings unreadable",
             counts["carried"], counts["made"], counts["none"], counts["unreadable"])
    return counts


# ── Pairs ────────────────────────────────────────────────────────────────────────────────────
def load_compare_seed(path: Path = COMPARE_YAML) -> dict:
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    return data or {}


def _translate(svg: str, dx: float, dy: float) -> str:
    """Every coordinate of every path moved by (dx, dy), written as RDKit writes them."""
    def move_d(m: re.Match) -> str:
        n = [0]

        def num(t: re.Match) -> str:
            v = float(t.group(0)) + (dx if n[0] % 2 == 0 else dy)
            n[0] += 1
            return f"{v:.1f}"
        return " d='" + re.sub(r"-?\d+(?:\.\d+)?", num, m.group(1)) + "'"
    return re.sub(r" d='([^']*)'", move_d, svg)


def _core(ma, mb):
    """(atom map a->b over the largest common core, or None, and why)."""
    from rdkit import Chem
    from rdkit.Chem import rdFMCS

    res = rdFMCS.FindMCS([ma, mb], atomCompare=rdFMCS.AtomCompare.CompareElements,
                         bondCompare=rdFMCS.BondCompare.CompareOrder, ringMatchesRingOnly=True,
                         completeRingsOnly=True, matchChiralTag=False, timeout=MCS_TIMEOUT)
    if res.canceled:
        return None, f"the common-core search ran past {MCS_TIMEOUT} s"
    if not res.numAtoms:
        return None, "no common core"
    q = Chem.MolFromSmarts(res.smartsString)
    qa = ma.GetSubstructMatch(q)
    if not qa:
        return None, "the core does not map back onto the first molecule"
    # Of the ways the core maps onto the second molecule, the one whose atoms keep the most of the
    # first molecule's neighbour counts: the difference then sits on as few atoms as it can.
    best, best_score = None, None
    for qb in mb.GetSubstructMatches(q, uniquify=False, maxMatches=500, useChirality=False):
        score = sum(ma.GetAtomWithIdx(i).GetDegree() != mb.GetAtomWithIdx(j).GetDegree()
                    for i, j in zip(qa, qb))
        if best_score is None or score < best_score:
            best, best_score = qb, score
    if best is None:
        return None, "the core does not map onto the second molecule"
    return dict(zip(qa, best)), ""


def _difference(mol, core_atoms: set[int]) -> tuple[list[int], list[tuple[int, int]]]:
    """Atoms outside the core, the core atoms they hang on, and the bonds among those."""
    iso = _isolated(mol)
    extra = {a.GetIdx() for a in mol.GetAtoms()
             if a.GetIdx() not in core_atoms and a.GetIdx() not in iso and a.GetAtomicNum() > 1}
    hang = {n.GetIdx() for i in extra for n in mol.GetAtomWithIdx(i).GetNeighbors()
            if n.GetIdx() in core_atoms}
    lit = extra | hang
    bonds = sorted(tuple(sorted((b.GetBeginAtomIdx(), b.GetEndAtomIdx()))) for b in mol.GetBonds()
                   if b.GetBeginAtomIdx() in lit and b.GetEndAtomIdx() in lit
                   and (b.GetBeginAtomIdx() in extra or b.GetEndAtomIdx() in extra))
    return sorted(lit), bonds


def _frame(pts) -> tuple[float, float, float, float] | None:
    """The viewBox both drawings of a pair share: the shipped canvas, grown to hold the second
    drawing with RDKit's own padding; None when the shipped canvas already holds it."""
    w, h = CANVAS
    px, py = FRAME_PAD
    x0 = min([0.0] + [x - px for x, _ in pts])
    y0 = min([0.0] + [y - py for _, y in pts])
    x1 = max([float(w)] + [x + px for x, _ in pts])
    y1 = max([float(h)] + [y + py for _, y in pts])
    if (x0, y0, x1, y1) == (0.0, 0.0, float(w), float(h)):
        return None
    return (round(x0, 1), round(y0, 1), round(x1 - x0, 1), round(y1 - y0, 1))


def _with_frame(svg: str, frame) -> str:
    x, y, w, h = frame
    svg = re.sub(r"width='[^']*' height='[^']*' viewBox='[^']*'",
                 f"width='{w:g}px' height='{h:g}px' viewBox='{x:g} {y:g} {w:g} {h:g}'", svg, count=1)
    return svg


def pair_key(a: dict, b: dict, caption, override, stereo: dict | None = None) -> str:
    # A curated three-dimensional mark (phase 5B) joins the key only on a pair that has one, so
    # every other pair's key is what phase 5A made it.
    extra = [json.dumps(stereo, sort_keys=True, ensure_ascii=False)] if stereo else []
    return _sha(PAIRS_RECIPE, a["slug"], b["slug"], geometry_sha(a.get("structure_svg") or ""),
                a.get("isomeric_smiles"), b.get("isomeric_smiles"), caption, override, *extra)


def _heavy(mol) -> int:
    return sum(1 for a in mol.GetAtoms() if a.GetAtomicNum() > 1 and a.GetDegree() > 0)


def draw_pair(a: dict, b: dict, stereo: dict | None = None) -> dict:
    """One pair's drawings (see the module docstring). ``mode`` "aligned" carries the second
    molecule's drawing in the first's frame (``b_svg``) and, where the difference is small, the
    layers that mark it on both; ``mode`` "shipped" means the page shows the two shipped
    drawings, and ``reason`` says why."""
    from rdkit import Chem
    from rdkit.Chem import rdDepictor
    from rdkit.Geometry import Point2D

    def shipped(reason: str, **kw) -> dict:
        return {"mode": "shipped", "reason": reason, "highlight": False, **kw}

    if not a.get("structure_svg") or not b.get("structure_svg"):
        return shipped("one of the two has no drawing")
    ma, mb = Chem.MolFromSmiles(a["isomeric_smiles"]), Chem.MolFromSmiles(b["isomeric_smiles"])
    if max(_heavy(ma), _heavy(mb)) > ALIGN_MAX_ATOMS:
        return shipped(f"too large to align ({max(_heavy(ma), _heavy(mb))} atoms; the rule "
                       f"stops at {ALIGN_MAX_ATOMS})")
    amap, why = _core(ma, mb)
    if amap is None:
        return shipped(why)
    # the core counted on bonded heavy atoms (a lone ion is never part of a shape)
    amap = {i: j for i, j in amap.items()
            if ma.GetAtomWithIdx(i).GetDegree() > 0 and ma.GetAtomWithIdx(i).GetAtomicNum() > 1}
    n_core, larger = len(amap), max(_heavy(ma), _heavy(mb))
    if n_core < ALIGN_MIN_ATOMS or n_core < ALIGN_MIN_SHARE * larger:
        return shipped(f"the common core, {n_core} of {larger} atoms, is too small to align on",
                       core=n_core)
    if stereo and stereo.get("drawings") == "shipped":
        return _stereo_mark_shipped(stereo, a, b, ma, mb, amap, n_core)
    rd = reading_for(a)
    if rd is None or not rd.scale_px:
        return shipped("the first drawing's atom positions are not proven", core=n_core)
    k = 1.5 / rd.scale_px
    coord_map = {j: Point2D(rd.pos[i][0] * k, -rd.pos[i][1] * k) for i, j in amap.items()}
    mb2 = Chem.Mol(mb)
    rdDepictor.Compute2DCoords(mb2, coordMap=coord_map, canonOrient=False)
    # Phase 5B: in a flat drawing the coordinates themselves say cis or trans, so pinning the second
    # molecule to the first's core can draw a double bond the wrong way round (tretinoin laid out
    # on isotretinoin came out cis). Then the pair shows its two shipped drawings.
    if not _double_bonds_kept(mb, mb2):
        if stereo:
            return _stereo_mark_shipped(stereo, a, b, ma, mb, amap, n_core)
        return shipped("aligning would draw a double bond of the second molecule the wrong way "
                       "round", core=n_core)
    big = (CANVAS[0] * 4, CANVAS[1] * 4)
    svg, d = structures.draw(mb2, *big, fixed_bond_px=rd.scale_px / 1.5, flag_close_contacts=False)
    drawn = {j: (d.GetDrawCoords(j).x, d.GetDrawCoords(j).y) for j in range(mb2.GetNumAtoms())}
    dx = sum(rd.pos[i][0] - drawn[j][0] for i, j in amap.items()) / n_core
    dy = sum(rd.pos[i][1] - drawn[j][1] for i, j in amap.items()) / n_core
    pos_b = {j: (x + dx, y + dy) for j, (x, y) in drawn.items()}
    off = max(math.dist(rd.pos[i], pos_b[j]) for i, j in amap.items())
    if off > ALIGN_TOLERANCE_PX:
        return shipped(f"the second molecule does not fit even a canvas four times the size "
                       f"(core off by {off:.1f} px)", core=n_core)
    b_svg = _translate(svg, dx, dy)
    pts = [pt for p in svg_geometry.parse_svg(b_svg) for sp in p.subpaths for pt in sp]
    frame = _frame(pts)
    b_svg = _with_frame(b_svg, frame or (0.0, 0.0, float(CANVAS[0]), float(CANVAS[1])))
    out = {"mode": "aligned", "reason": "", "core": n_core, "highlight": False,
           "core_map": sorted([i, j] for i, j in amap.items()),
           "frame": list(frame) if frame else None,
           "b_svg": b_svg, "a_layer": None, "b_layer": None}
    lit_a, bonds_a = _difference(ma, set(amap))
    lit_b, bonds_b = _difference(mb, set(amap.values()))
    n_extra = (len([i for i in lit_a if i not in amap])
               + len([j for j in lit_b if j not in amap.values()]))
    if stereo:
        return _stereo_mark(out, stereo, ma, mb, amap, n_extra, rd, pos_b)
    if not 1 <= n_extra <= HIGHLIGHT_MAX_ATOMS:
        out["reason"] = (f"aligned; {n_extra} atoms differ, " +
                         ("none to mark" if not n_extra else "too many to mark as one group"))
        return out
    # mark the same place on both: each side's own extra atoms and attachment points, plus the
    # core atoms the other side's attachment points map to
    inv = {j: i for i, j in amap.items()}
    lit_a = sorted(set(lit_a) | {inv[j] for j in lit_b if j in inv})
    lit_b = sorted(set(lit_b) | {amap[i] for i in lit_a if i in amap})
    out.update(highlight=True, extra_atoms=n_extra,
               a_atoms=lit_a, b_atoms=lit_b,
               a_layer=layer(rd.pos, lit_a, bonds_a, rd.scale_px, "mf-diff"),
               b_layer=layer(pos_b, lit_b, bonds_b, rd.scale_px, "mf-diff"))
    return out


def _stereo_mark(out: dict, spec: dict, ma, mb, amap: dict, n_extra: int, rd, pos_b,
                 scale_b: float | None = None) -> dict:
    """A curated mark for a pair whose two molecules have the same atoms and bonds and differ only
    in their three-dimensional arrangement (the common-core search ignores stereo, so it finds no
    difference to mark). The atoms are chosen by the seed's pattern, matched on both molecules,
    never by atom number; the build stops unless the pattern lights the same atoms on both sides
    of the core map, the expected number of times."""
    if n_extra:
        raise DrawingSeedError(f"a three-dimensional mark is for a pair whose atoms all match; "
                               f"{n_extra} atoms differ here")
    sides = []
    for mol in (ma, mb):
        atoms, bonds, n = _match(mol, spec)
        exp = (spec.get("expect") or {}).get("matches")
        if not atoms or (exp is not None and n != exp):
            raise DrawingSeedError(f"three-dimensional mark expects {exp} match(es), finds {n}")
        sides.append((atoms, bonds))
    (lit_a, bonds_a), (lit_b, bonds_b) = sides
    if sorted(amap[i] for i in lit_a) != lit_b:
        raise DrawingSeedError("the three-dimensional mark lights different atoms on the two sides")
    out.update(highlight=True, extra_atoms=0, stereo=True, a_atoms=lit_a, b_atoms=lit_b,
               reason="aligned; the same atoms, marked where their arrangement in space differs",
               a_layer=layer(rd.pos, lit_a, bonds_a, rd.scale_px, "mf-diff"),
               b_layer=layer(pos_b, lit_b, bonds_b, scale_b or rd.scale_px, "mf-diff"))
    return out


def _double_bonds_kept(mol, laid_out) -> bool:
    """True when the 2D coordinates of ``laid_out`` draw every stereo double bond of ``mol`` (cis or
    trans, E or Z) as ``mol`` declares it."""
    from rdkit import Chem

    want = Chem.Mol(mol)
    Chem.AssignStereochemistry(want, cleanIt=True, force=True)
    declared = {b.GetIdx(): b.GetStereo() for b in want.GetBonds()
                if b.GetBondType() == Chem.BondType.DOUBLE and b.GetStereo() != Chem.BondStereo.STEREONONE}
    if not declared:
        return True
    got = Chem.Mol(laid_out)
    for bd in got.GetBonds():
        if bd.GetBondType() == Chem.BondType.DOUBLE:
            bd.SetStereo(Chem.BondStereo.STEREONONE)
    Chem.DetectBondStereochemistry(got)
    Chem.AssignStereochemistry(got, cleanIt=True, force=True)
    return all(got.GetBondWithIdx(i).GetStereo() == s for i, s in declared.items())


def _stereo_mark_shipped(spec: dict, a: dict, b: dict, ma, mb, amap: dict, n_core: int) -> dict:
    """The three-dimensional mark on the two SHIPPED drawings, each layer placed from that drawing's
    own proven reading: for a pair that cannot be aligned without drawing a double bond the wrong way
    round (isotretinoin and tretinoin)."""
    ra, rb = reading_for(a), reading_for(b)
    if ra is None or rb is None:
        raise DrawingSeedError("a three-dimensional mark on the shipped drawings needs both drawings' "
                               "atom positions proven")
    out = {"mode": "shipped", "core": n_core, "core_map": sorted([i, j] for i, j in amap.items()),
           "frame": None, "b_svg": None}
    out = _stereo_mark(out, spec, ma, mb, amap, 0, ra, rb.pos, scale_b=rb.scale_px)
    out["reason"] = ("the two shipped drawings (aligning them would draw a double bond the wrong way "
                     "round); the same atoms, marked where their arrangement in space differs")
    return out


# ── Captions by rule ─────────────────────────────────────────────────────────────────────────
# What a highlighted pair's caption says, generated from the computed difference wherever a rule
# can say it truthfully (tests/test_drawings.py holds every caption the seed does not list as
# curated to this function's text). Substructure facts only: no layout, so any machine agrees.
_NUMBER = {1: "One", 2: "Two", 3: "Three", 4: "Four"}
_HALOGEN = {9: "fluorine", 17: "chlorine", 35: "bromine", 53: "iodine"}


def _fragments(mol, core: set[int]) -> list[tuple[list[int], int, int]]:
    """Connected groups of atoms outside the core: (atoms, the core atom they hang on, the order
    of that bond). None when a group hangs on two core atoms (a ring difference, not a group)."""
    iso = _isolated(mol)
    extra = {a.GetIdx() for a in mol.GetAtoms()
             if a.GetIdx() not in core and a.GetIdx() not in iso and a.GetAtomicNum() > 1}
    out, seen = [], set()
    for start in sorted(extra):
        if start in seen:
            continue
        comp, stack = set(), [start]
        while stack:
            i = stack.pop()
            if i in comp:
                continue
            comp.add(i)
            stack += [n.GetIdx() for n in mol.GetAtomWithIdx(i).GetNeighbors() if n.GetIdx() in extra]
        seen |= comp
        links = [(n.GetIdx(), mol.GetBondBetweenAtoms(i, n.GetIdx()).GetBondTypeAsDouble())
                 for i in comp for n in mol.GetAtomWithIdx(i).GetNeighbors() if n.GetIdx() in core]
        if len(links) != 1:
            return None
        out.append((sorted(comp), links[0][0], links[0][1]))
    return out


def _name(mol, atoms: list[int], attach: int, order: float) -> str | None:
    if len(atoms) == 1:
        at = mol.GetAtomWithIdx(atoms[0])
        if at.GetAtomicNum() in _HALOGEN:
            return _HALOGEN[at.GetAtomicNum()]
        if at.GetAtomicNum() == 6 and at.GetTotalNumHs() == 3:
            return "methyl group"
        if at.GetAtomicNum() == 8 and order == 1 and at.GetTotalNumHs() == 1:
            return "hydroxyl group"
        if at.GetAtomicNum() == 8 and order == 2:
            c = mol.GetAtomWithIdx(attach)
            if sum(n.GetAtomicNum() == 6 for n in c.GetNeighbors()) == 2:
                return "ketone"
        return None
    from rdkit import Chem
    smi = Chem.MolFragmentToSmiles(mol, atomsToUse=atoms, canonical=True, isomericSmiles=False)
    return {"CC": "ethyl group", "CCO": "ethoxy group", "CC=O": "acetyl group"}.get(smi)


def _mid(title: str) -> str:
    """A molecule's title inside a sentence: "Isopropyl alcohol" -> "isopropyl alcohol"; an
    acronym or a name with a capital after its first letter stays as it is."""
    return title[0].lower() + title[1:] if title[1:2].islower() and title[1:].islower() else title


def _cap(s: str) -> str:
    return s[0].upper() + s[1:]


def _a(noun: str) -> str:
    return ("an " if noun[0] in "aeiou" else "a ") + noun


def _chain(mol, atoms: list[int]) -> bool:
    return all(mol.GetAtomWithIdx(i).GetAtomicNum() == 6 and not mol.GetAtomWithIdx(i).IsInRing()
               and mol.GetAtomWithIdx(i).GetHybridization().name == "SP3" for i in atoms)


def caption_rule(a: dict, b: dict, entry: dict) -> str | None:
    """The caption a rule can write for a highlighted pair, or None when no rule says it truthfully
    (the seed then carries a curated one). Reads the two records and the pair's core map only."""
    from rdkit import Chem

    if not entry.get("highlight") or entry.get("stereo"):
        return None
    ma, mb = Chem.MolFromSmiles(a["isomeric_smiles"]), Chem.MolFromSmiles(b["isomeric_smiles"])
    amap = {i: j for i, j in entry["core_map"]}
    inv = {j: i for i, j in amap.items()}
    fa, fb = _fragments(ma, set(amap)), _fragments(mb, set(inv))
    if fa is None or fb is None:
        return None
    ta, tb = _mid(a["title"]), _mid(b["title"])
    # a group on each side at the same core atom: one replaces the other
    swaps, only_a, only_b = [], list(fa), list(fb)
    for f in fa:
        g = next((g for g in fb if g[1] == amap.get(f[1])), None)
        if g:
            swaps.append((f, g))
            only_a.remove(f)
            only_b.remove(g)
    sites = len(swaps) + len(only_a) + len(only_b)
    if sites == 1 and swaps:
        (f, g), = swaps
        x, y = _name(ma, *f), _name(mb, *g)
        return f"{_cap(ta)} has {_a(x)} where {tb} has {_a(y)}." if x and y else None
    if sites == 1:
        mol, other, (atoms, at, order), m2 = ((ma, mb, only_a[0], amap) if only_a
                                             else (mb, ma, only_b[0], inv))
        end = other.GetAtomWithIdx(m2[at])
        if _chain(mol, atoms) and end.GetAtomicNum() == 6 and end.GetDegree() == 1:
            n = len(atoms)
            return f"{_NUMBER[n]} carbon{'s' if n > 1 else ''} longer." if n in _NUMBER else None
        x = _name(mol, atoms, at, order)
        if x in _HALOGEN.values():
            t1, t2 = (ta, tb) if only_a else (tb, ta)
            return f"{_cap(t1)} has {_a(x)} where {t2} has a hydrogen."
        return f"One {x} apart." if x else None
    if swaps or sites not in _NUMBER:
        return None
    sides = []
    for mol, frags, title in ((ma, only_a, ta), (mb, only_b, tb)):
        names = [_name(mol, *f) for f in frags]
        if None in names:
            return None
        if names:
            sides.append(" and ".join(_a(n) for n in names) + f" on {title}")
    return f"{_NUMBER[sites]} differences: " + ", and ".join(sides) + "."


def compile_compare_drawings(molecules: list[dict], comparisons: dict[str, dict],
                             prior: dict | None = None, seed: dict | None = None) -> dict:
    """``compare_drawings.json``: one entry per /vs pair, carried by key (see ``pair_key``)."""
    seed = load_compare_seed() if seed is None else seed
    by_slug = {m["slug"]: m for m in molecules}
    captions = seed.get("captions") or {}
    overrides = seed.get("shipped") or {}
    stereo_marks = seed.get("stereo") or {}
    from .relationships import load_comparisons
    seeded = {k.replace("/", "-vs-") for k in load_comparisons()}
    unknown = sorted((set(captions) | set(overrides) | set(stereo_marks)
                      | set(seed.get("curated") or {})) - seeded)
    if unknown:
        raise DrawingSeedError(f"compare_drawings.yaml names pairs comparisons.yaml does not: {unknown}")
    old = (prior or {}).get("pairs") or {}
    pairs: dict[str, dict] = {}
    counts = {"carried": 0, "made": 0, "repainted": 0}
    for slug in sorted(comparisons):
        c = comparisons[slug]
        a, b = by_slug[c["a"]], by_slug[c["b"]]
        caption, override = captions.get(slug), overrides.get(slug)
        stereo = stereo_marks.get(slug)
        key = pair_key(a, b, caption, override, stereo)
        prev = old.get(slug)
        if prev and prev.get("key") == key:
            entry = dict(prev)
            if entry.get("b_svg") and entry.get("palette") != structures.RECIPE_VERSION:
                entry["b_svg"] = structures.recolour(entry["b_svg"], b["isomeric_smiles"])
                entry["palette"] = structures.RECIPE_VERSION
                counts["repainted"] += 1
            else:
                counts["carried"] += 1
            pairs[slug] = entry
            continue
        if override:
            body = {"mode": "shipped", "reason": f"held to the shipped drawings: {override}",
                    "highlight": False}
        else:
            try:
                body = draw_pair(a, b, stereo)
            except DrawingSeedError as e:
                raise DrawingSeedError(f"{slug}: {e}") from None
            if stereo and not body.get("stereo"):
                raise DrawingSeedError(f"{slug}: a three-dimensional mark found no pair to mark; "
                                       f"this one is {body['mode']} ({body['reason']})")
        if caption and not body.get("highlight"):
            raise DrawingSeedError(f"{slug}: a caption ({caption!r}) needs a highlighted pair; "
                                   f"this one is {body['mode']} ({body['reason']})")
        pairs[slug] = {"key": key, "recipe": PAIRS_RECIPE,
                       "palette": structures.RECIPE_VERSION if body.get("b_svg") else None,
                       "a": a["slug"], "b": b["slug"], "caption": caption, **body,
                       "confidence": "computed", "source": "MoleculeFinder rule (RDKit MCS)"}
        counts["made"] += 1
    modes: dict[str, int] = {}
    for p in pairs.values():
        modes[p["mode"] + ("+highlight" if p.get("highlight") else "")] = \
            modes.get(p["mode"] + ("+highlight" if p.get("highlight") else ""), 0) + 1
    log.info("  compare drawings: %d pairs (%s); %d carried, %d repainted, %d made",
             len(pairs), ", ".join(f"{k} {v}" for k, v in sorted(modes.items())),
             counts["carried"], counts["repainted"], counts["made"])
    return {"recipe": PAIRS_RECIPE,
            "thresholds": {"align_min_atoms": ALIGN_MIN_ATOMS, "align_min_share": ALIGN_MIN_SHARE,
                           "highlight_max_atoms": HIGHLIGHT_MAX_ATOMS},
            "pairs": pairs}


# ── Repeat units ─────────────────────────────────────────────────────────────────────────────
def load_repeat_seed(path: Path = REPEAT_YAML) -> dict:
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    return (data or {}).get("units") or {}


def draw_repeat_unit(spec: dict) -> dict:
    from rdkit import Chem

    mol = Chem.MolFromSmiles(spec["smiles"])
    if mol is None:
        raise DrawingSeedError(f"repeat unit SMILES does not parse: {spec['smiles']}")
    svg, d = structures.draw(Chem.Mol(mol), flag_close_contacts=False)
    pos = {i: (d.GetDrawCoords(i).x, d.GetDrawCoords(i).y) for i in range(mol.GetNumAtoms())}
    atoms, bonds, n = _match(mol, {"id": "linkage", "smarts": spec["linkage_smarts"]})
    if n != int(spec.get("linkages", 1)):
        raise DrawingSeedError(f"repeat unit linkage SMARTS matches {n} times, expected "
                               f"{spec.get('linkages', 1)}")
    scale = svg_geometry.bond_px(mol, pos)
    return {"svg": svg, "layer": layer(pos, atoms, bonds, scale, "mf-linkage"),
            "linkage_atoms": atoms}


def repeat_key(slug: str, spec: dict) -> str:
    return _sha(REPEAT_RECIPE, slug, json.dumps(spec, sort_keys=True, ensure_ascii=False))


def attach_repeat_units(records: list[dict], prior: dict[int, dict] | None = None,
                        units: dict | None = None) -> int:
    """``structure_repeat_unit`` on each record the seed names (hand-modelled polymers only)."""
    units = load_repeat_seed() if units is None else units
    by_slug = {r["slug"]: r for r in records}
    missing = sorted(set(units) - set(by_slug))
    if missing:
        raise DrawingSeedError(f"repeat_units.yaml names molecules not in the catalog: {missing}")
    for slug in units:
        if by_slug[slug].get("structure_svg"):
            raise DrawingSeedError(f"{slug} has a structure; a repeat unit is for a polymer with none")
    prior = prior or {}
    made = 0
    for rec in records:
        spec = units.get(rec["slug"])
        if not spec:
            rec["structure_repeat_unit"] = None
            continue
        key = repeat_key(rec["slug"], spec)
        old = (prior.get(rec.get("cid")) or {}).get("structure_repeat_unit")
        if old and old.get("key") == key:
            entry = dict(old)
            if entry.get("palette") != structures.RECIPE_VERSION:
                entry["svg"] = structures.recolour(entry["svg"], spec["smiles"])
                entry["palette"] = structures.RECIPE_VERSION
            rec["structure_repeat_unit"] = entry
            continue
        drawn = draw_repeat_unit(spec)
        rec["structure_repeat_unit"] = {
            "key": key, "recipe": REPEAT_RECIPE, "palette": structures.RECIPE_VERSION,
            "smiles": spec["smiles"], "label": spec["label"], "linkage": spec["linkage"],
            "units": int(spec.get("units", 2)), "svg": drawn["svg"], "layer": drawn["layer"],
            "linkage_atoms": drawn["linkage_atoms"],
            "confidence": "from_source", "source": "MoleculeFinder curated",
        }
        made += 1
    log.info("  repeat units: %d (%d drawn this run)", len(units), made)
    return made


# House rules for the drawing seeds' text, the same as a door's (transform/doors.py; the web's
# lib/copy-rules.ts): no em or en dash, no advice or dosing word, no completeness phrase, no LD50,
# no "inferred"; plus lengths, and a sentence or caption ends with a full stop. The claim rule is
# claims.check_lines (kind `part`).
TEXT_LENGTHS = {"label": (6, 40), "sentence": (30, 280), "from": (10, 240), "caption": (15, 110)}


def text_problems(items: list[tuple[str, str]] | None = None) -> list[str]:
    from .doors import ADVICE, COMPLETENESS, DASH, NEW_WRITING_ADVICE
    out = []
    for key, text in (strings() if items is None else items):
        kind = "caption" if key.startswith("caption.") else key.rsplit(".", 1)[-1]
        if DASH.search(text):
            out.append(f"{key}: an em or en dash: {text!r}")
        if ADVICE.search(text) or any(re.search(p, text, re.IGNORECASE) for p in NEW_WRITING_ADVICE):
            out.append(f"{key}: reads as advice or dosing: {text!r}")
        low = text.lower()
        if any(p in low for p in COMPLETENESS) or "ld50" in low or "inferred" in low:
            out.append(f"{key}: a completeness phrase, an LD50 or 'inferred': {text!r}")
        lo, hi = TEXT_LENGTHS.get(kind, (1, 240))
        if not lo <= len(text) <= hi:
            out.append(f"{key}: {len(text)} characters, outside {lo} to {hi}: {text!r}")
        if kind in ("sentence", "caption") and not text.endswith("."):
            out.append(f"{key}: does not end with a full stop: {text!r}")
    return out


def check_text() -> None:
    problems = text_problems()
    if problems:
        raise DrawingSeedError("drawing seed text breaks a house rule:\n  " + "\n  ".join(problems))


def strings(parts: Path = PARTS_YAML, compare: Path = COMPARE_YAML,
            repeat: Path = REPEAT_YAML) -> list[tuple[str, str]]:
    """The new writing in the drawing seeds, as (key, text), for the claim rule (kind ``part``):
    part labels, sentences and source notes, pair captions, repeat unit labels."""
    out: list[tuple[str, str]] = []
    seed = load_parts_seed(parts)
    for scope, specs in [("default", seed.get("defaults") or [])] + [
            (slug, (m or {}).get("parts") or []) for slug, m in (seed.get("molecules") or {}).items()]:
        for s in specs:
            for f in ("label", "sentence", "from"):
                if isinstance(s.get(f), str) and s[f].strip():
                    out.append((f"{scope}.{s['id']}.{f}", " ".join(s[f].split())))
    for pair, cap in (load_compare_seed(compare).get("captions") or {}).items():
        out.append((f"caption.{pair}", " ".join(cap.split())))
    for slug, u in load_repeat_seed(repeat).items():
        out.append((f"repeat.{slug}.label", " ".join(u["label"].split())))
    return out
