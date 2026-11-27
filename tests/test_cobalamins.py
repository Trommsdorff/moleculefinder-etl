"""The cobalamins pass (2026-11-26; brief ../COBALAMINS-PROMPT.md, Cowork's rulings). Cyanocobalamin, vitamin B12,
hydroxocobalamin and methylcobalamin are drawn with their cobalt bonded (seeds/structure_display.yaml `metal_bonds`),
one skeleton laid out once by hand (scripts/cobalamin_layout.py) and shared by all four drawings.

Ruling 4, the check, proven on each of the four and failed on purpose:
  (a) formula and overall charge are the record's;
  (b) the cobalt is bonded to exactly the six named atoms (four corrin nitrogens, the benzimidazole's free nitrogen,
      the top group's first atom);
  (c) deleting those six bonds gives back the record's own pieces;
  (d) every centre the record specifies is the drawing's; a centre it leaves open is drawn only from hydroxocobalamin's
      record (stereo_from), on hydroxocobalamin's skeleton;
  (e) a double-bond geometry the record gives goes unmarked only inside a ring of eight atoms or fewer that the cobalt
      closes, and only when the record's geometry is the one that ring forces.
The layout is judged on the shipped SVG itself (positions read from it and proven), at the 400 x 300 drawing and at
the sizes the molecule page shows it.
"""
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import pytest
import yaml
from rdkit import Chem
from rdkit.Chem.rdMolDescriptors import CalcMolFormula

from moleculefinder_etl.config import SEEDS_DIR
from moleculefinder_etl.transform import assemble, claims, drawings, structures
from moleculefinder_etl.transform import svg_geometry as G

SNAP = Path(__file__).resolve().parents[1] / "data" / "snapshots"
COBALAMINS = ("cyanocobalamin", "vitamin-b12", "hydroxocobalamin", "methylcobalamin")
CIDS = {"cyanocobalamin": 16212801, "vitamin-b12": 184933, "hydroxocobalamin": 163191904, "methylcobalamin": 6436232}
TOP_ATOM = {"cyanocobalamin": "C", "vitamin-b12": "C", "hydroxocobalamin": "O", "methylcobalamin": "C"}
# (record's specified carbon centres, centres drawn, drawn from hydroxocobalamin's record)
CENTRES = {"hydroxocobalamin": (14, 14, 0), "cyanocobalamin": (13, 14, 1), "vitamin-b12": (0, 14, 14),
           "methylcobalamin": (0, 14, 14)}
# the corrin's meso double bonds whose geometry the record gives (none in the reference or vitamin B12's record)
GEOMETRIES = {"hydroxocobalamin": 0, "cyanocobalamin": 3, "vitamin-b12": 0, "methylcobalamin": 3}
CLAIM_WORDS = ("only", "first", "most", "leading", "largest", "world's", "never", "always")


def _rec(slug):
    return json.loads((SNAP / "molecules" / f"{slug}.json").read_text())


def _seed():
    return yaml.safe_load((SEEDS_DIR / "structure_display.yaml").read_text())["metal_bonds"]


def _problems(slug, display=None, *, reference=True, **over):
    e = {**_seed()[slug], **over}
    ref = _seed()["hydroxocobalamin"]
    return structures.metal_bonds_problems(
        display or e["smiles"], _rec(slug)["isomeric_smiles"], "Co", e["bonded"], e.get("charges") or [],
        top=e.get("top"), reference=(ref["smiles"], ref["top"]) if reference and "stereo_from" in e else None)


def _co(m):
    return next(a.GetIdx() for a in m.GetAtoms() if a.GetSymbol() == "Co")


# ── the four, drawn from their checked display structures ────────────────────────────────────────────────────────
@pytest.mark.parametrize("slug", COBALAMINS)
def test_each_cobalamin_is_drawn_from_its_checked_display_structure(slug):
    r, e = _rec(slug), _seed()[slug]
    d = r["structure_display"]
    assert d["kind"] == "metal_bonds" and d["metal"] == "Co" and d["smiles"] == e["smiles"]
    assert r["cid"] == CIDS[slug] and r["has_3d"] is False and d["has_3d"] is False
    assert r["structure_svg_key"] == structures.svg_key(d["smiles"]) and structures.drawn_smiles(r) == d["smiles"]
    assert structures.svg_for(d["smiles"]) == r["structure_svg"]
    assert set(d) == {"kind", "smiles", "metal", "has_3d", "line", "confidence", "source"}   # top, stereo_from stay
    assert r["isomeric_smiles"] != d["smiles"] and "." in r["isomeric_smiles"]              # the record is PubChem's
    assert _problems(slug) == []


@pytest.mark.parametrize("slug", COBALAMINS)
def test_a_formula_and_charge_are_the_records(slug):
    d, r = Chem.MolFromSmiles(_seed()[slug]["smiles"]), Chem.MolFromSmiles(_rec(slug)["isomeric_smiles"])
    assert CalcMolFormula(d) == CalcMolFormula(r) and Chem.GetFormalCharge(d) == Chem.GetFormalCharge(r) == 0


@pytest.mark.parametrize("slug", COBALAMINS)
def test_b_the_cobalt_is_bonded_to_exactly_the_six_named_atoms(slug):
    m = Chem.MolFromSmiles(_seed()[slug]["smiles"])
    co = m.GetAtomWithIdx(_co(m))
    nbs = list(co.GetNeighbors())
    assert len(nbs) == 6 and co.GetFormalCharge() == 1
    corrin = [n for n in nbs if n.GetSymbol() == "N" and not n.GetIsAromatic()]
    bzm = [n for n in nbs if n.GetSymbol() == "N" and n.GetIsAromatic()]
    top = [n for n in nbs if n not in corrin and n not in bzm]
    assert len(corrin) == 4 and len(bzm) == 1 and len(top) == 1
    assert top[0].GetSymbol() == TOP_ATOM[slug] and top[0].GetFormalCharge() == 0
    # the benzimidazole's free nitrogen, not the one bonded to the ribose
    assert not any(x.GetSymbol() == "C" and not x.GetIsAromatic() for x in bzm[0].GetNeighbors())
    if slug in ("cyanocobalamin", "vitamin-b12"):
        assert any(b.GetBondType() == Chem.BondType.TRIPLE and b.GetOtherAtom(top[0]).GetSymbol() == "N"
                   for b in top[0].GetBonds())                     # the cyanide's carbon
    # bond style: the negative partners (the ring's N- and the top group) plain, the neutral ones dative arrows
    kinds = {n.GetIdx(): m.GetBondBetweenAtoms(co.GetIdx(), n.GetIdx()).GetBondType() for n in nbs}
    assert sorted(str(k) for k in kinds.values()) == ["DATIVE"] * 4 + ["SINGLE"] * 2
    assert kinds[top[0].GetIdx()] == Chem.BondType.SINGLE and kinds[bzm[0].GetIdx()] == Chem.BondType.DATIVE


@pytest.mark.parametrize("slug", COBALAMINS)
def test_c_deleting_the_six_bonds_gives_back_the_records_own_pieces(slug):
    m = Chem.RWMol(Chem.MolFromSmiles(_seed()[slug]["smiles"]))
    co = _co(m)
    for a in m.GetAtoms():
        a.SetNumExplicitHs(a.GetTotalNumHs())
        a.SetNoImplicit(True)
    for n in [x.GetIdx() for x in m.GetAtomWithIdx(co).GetNeighbors()]:
        if m.GetBondBetweenAtoms(co, n).GetBondType() == Chem.BondType.SINGLE:
            m.GetAtomWithIdx(n).SetFormalCharge(m.GetAtomWithIdx(n).GetFormalCharge() - 1)
            m.GetAtomWithIdx(co).SetFormalCharge(m.GetAtomWithIdx(co).GetFormalCharge() + 1)
        m.RemoveBond(co, n)
    pieces = m.GetMol()
    Chem.SanitizeMol(pieces)
    r = Chem.MolFromSmiles(_rec(slug)["isomeric_smiles"])
    def flat(x):                                                  # stereo is (d) and (e)
        return Chem.MolToSmiles(x, isomericSmiles=False)
    assert flat(pieces) == flat(r)
    assert len(Chem.GetMolFrags(pieces)) == len(Chem.GetMolFrags(r)) == 3   # the ring, the top group, Co3+


@pytest.mark.parametrize("slug", COBALAMINS)
def test_d_stereo_the_records_centres_and_the_references_on_one_skeleton(slug):
    own, drawn, borrowed = CENTRES[slug]
    r = Chem.MolFromSmiles(_rec(slug)["isomeric_smiles"])
    d = Chem.MolFromSmiles(_seed()[slug]["smiles"])

    def carbon_centres(m):
        return [i for i, tag in Chem.FindMolChiralCenters(m, includeUnassigned=False, useLegacyImplementation=False)
                if m.GetAtomWithIdx(i).GetSymbol() == "C"]
    assert len(carbon_centres(r)) == own and len(carbon_centres(d)) == drawn
    # the phosphorus RDKit flags is specified by no record and drawn in none
    assert not [i for i, _ in Chem.FindMolChiralCenters(d, useLegacyImplementation=False)
                if d.GetAtomWithIdx(i).GetSymbol() == "P"]
    assert ("stereo_from" in _seed()[slug]) == (borrowed > 0)
    if borrowed:
        assert _seed()[slug]["stereo_from"] == "hydroxocobalamin"
        # without the reference, the borrowed centres fail
        assert any(f"{borrowed} stereocentre(s)" in p for p in _problems(slug, reference=False))
    # every drawing's skeleton, its top group removed, is the reference's, stereo included
    ref = _seed()["hydroxocobalamin"]
    e = _seed()[slug]
    assert structures.skeleton_key(e["smiles"], "Co", e["top"]) == structures.skeleton_key(ref["smiles"], "Co",
                                                                                           ref["top"])


def test_d_cyanocobalamins_own_centres_all_agree_with_the_reference():
    """Its 13 specified centres against hydroxocobalamin's record, atom for atom (the anomeric carbon is the 14th,
    which only the reference specifies)."""
    def skeleton(slug):
        r = Chem.MolFromSmiles(_rec(slug)["isomeric_smiles"])
        main = max(Chem.GetMolFrags(r), key=len)               # the ring and its nucleotide: no cobalt, no top group
        rw = Chem.RWMol(r)
        for i in sorted(set(range(r.GetNumAtoms())) - set(main), reverse=True):
            rw.RemoveAtom(i)
        return rw.GetMol()
    cy = skeleton("cyanocobalamin")
    hy = skeleton("hydroxocobalamin")
    cyc = dict(Chem.FindMolChiralCenters(cy, useLegacyImplementation=False))
    q = Chem.RWMol(cy)
    for b in q.GetBonds():
        b.SetBondType(Chem.BondType.SINGLE)
        b.SetStereo(Chem.BondStereo.STEREONONE)
    for a in q.GetAtoms():
        a.SetFormalCharge(0)
        a.SetIsAromatic(False)
    params = Chem.SubstructMatchParameters()
    params.useChirality = False
    hq = Chem.RWMol(hy)
    for b in hq.GetBonds():
        b.SetBondType(Chem.BondType.SINGLE)
    for a in hq.GetAtoms():
        a.SetFormalCharge(0)
        a.SetIsAromatic(False)
    hq.UpdatePropertyCache(False)
    q.UpdatePropertyCache(False)
    match = hq.GetSubstructMatch(q, params)
    assert len(match) == cy.GetNumAtoms()
    # compare each shared centre by its neighbours' arrangement (CIP-free): the same parity about mapped neighbours
    agree = 0
    for i in cyc:
        a, b = cy.GetAtomWithIdx(i), hy.GetAtomWithIdx(match[i])
        if b.GetChiralTag() == Chem.ChiralType.CHI_UNSPECIFIED:
            continue
        order_a = [match[n.GetIdx()] for n in a.GetNeighbors()]
        order_b = [n.GetIdx() for n in b.GetNeighbors()]
        perm = [order_b.index(x) for x in order_a]
        odd = sum(1 for x, y in itertools.combinations(range(len(perm)), 2) if perm[x] > perm[y]) % 2
        same_tag = a.GetChiralTag() == b.GetChiralTag()
        assert same_tag != bool(odd), f"centre {i} disagrees"
        agree += 1
    assert agree == 13


@pytest.mark.parametrize("slug", COBALAMINS)
def test_e_the_corrins_geometry_sits_in_rings_the_cobalt_closes(slug):
    r = Chem.MolFromSmiles(_rec(slug)["isomeric_smiles"])
    stated = [b for b in r.GetBonds() if b.GetBondType() == Chem.BondType.DOUBLE
              and b.GetStereo() not in (Chem.BondStereo.STEREONONE, Chem.BondStereo.STEREOANY)]
    assert len(stated) == GEOMETRIES[slug]
    d = Chem.MolFromSmiles(_seed()[slug]["smiles"])
    assert not [b for b in d.GetBonds() if b.GetStereo() not in (Chem.BondStereo.STEREONONE,
                                                                 Chem.BondStereo.STEREOANY)]
    # the corrin's three meso double bonds each sit in a six-membered ring through the cobalt (Co-N-C=C-C-N); the
    # check itself (test_each_cobalamin_is_drawn...) proves the stated geometries map onto them and are the forced ones
    ok = 0
    for b in d.GetBonds():
        if b.GetBondType() == Chem.BondType.DOUBLE and b.GetBeginAtom().GetSymbol() == "C" \
                and b.GetEndAtom().GetSymbol() == "C" and not b.GetIsAromatic():
            ring = structures.metal_ring(d, b.GetBeginAtomIdx(), b.GetEndAtomIdx(), _co(d))
            if ring:
                assert len(ring) == 6
                ok += 1
    assert ok == 3                                          # the three meso double bonds


# ── each check fails on purpose ──────────────────────────────────────────────────────────────────────────────────
def _edit(slug, fn):
    m = Chem.RWMol(Chem.MolFromSmiles(_seed()[slug]["smiles"]))
    fn(m)
    out = m.GetMol()
    Chem.SanitizeMol(out)
    return Chem.MolToSmiles(out)


def test_a_cyanide_bonded_by_its_nitrogen_fails():
    def by_nitrogen(m):
        co = _co(m)
        c = next(x for x in m.GetAtomWithIdx(co).GetNeighbors() if x.GetSymbol() == "C")
        n = next(x for x in c.GetNeighbors() if x.GetSymbol() == "N")
        m.RemoveBond(co, c.GetIdx())
        m.AddBond(n.GetIdx(), co, Chem.BondType.DATIVE)
        c.SetFormalCharge(-1)
        m.GetAtomWithIdx(co).SetFormalCharge(2)
    for slug in ("cyanocobalamin", "vitamin-b12"):
        wrong = _edit(slug, by_nitrogen)
        probs = _problems(slug, wrong)
        assert any("[#6]#[#7] bonded to Co: 0" in p for p in probs), probs


def test_the_wrong_benzimidazole_nitrogen_fails():
    def wrong_n(m):
        co = _co(m)
        n3 = next(x for x in m.GetAtomWithIdx(co).GetNeighbors() if x.GetIsAromatic())
        n1 = next(x for x in m.GetAtoms() if x.GetSymbol() == "N" and x.GetIsAromatic() and x.GetIdx() != n3.GetIdx())
        m.RemoveBond(co, n3.GetIdx())
        m.AddBond(n1.GetIdx(), co, Chem.BondType.DATIVE)
    wrong = _edit("hydroxocobalamin", wrong_n)
    probs = _problems("hydroxocobalamin", wrong)
    assert any("bonded to Co: 0, expected 1" in p for p in probs), probs


def test_one_flipped_centre_fails():
    # a centre the record specifies, turned (hydroxocobalamin, cyanocobalamin): the record's centres fail
    for slug in ("hydroxocobalamin", "cyanocobalamin"):
        smi = _seed()[slug]["smiles"]
        flipped = smi.replace("[C@@H]", "[C@H]", 1)
        assert flipped != smi
        assert any("stereocentres" in p for p in _problems(slug, flipped)), slug
    # a centre drawn from the reference, turned (vitamin B12, methylcobalamin): the skeleton is not the reference's
    for slug in ("vitamin-b12", "methylcobalamin"):
        smi = _seed()[slug]["smiles"]
        flipped = smi.replace("[C@@H]", "[C@H]", 1)
        assert any("not the reference's" in p for p in _problems(slug, flipped)), slug


def test_a_geometry_dropped_outside_a_ring_the_metal_closes_fails_and_inside_one_passes():
    bonded = [{"smarts": "[#7]", "count": 1}, {"smarts": "[#8]", "count": 1}]
    charges = [{"element": "Cu", "record": 1, "drawn": 0}, {"element": "N", "record": -1, "drawn": 0}]
    chelate = "[NH]1C=CC=[O]->[Cu]1"
    # inside the six-membered ring the copper closes, cis about the ring: unmarked in the drawing, allowed
    assert structures.metal_bonds_problems(chelate, "[NH-]/C=C\\C=O.[Cu+]", "Cu", bonded, charges) == []
    # the same ring, the record trans: not the geometry the ring forces
    probs = structures.metal_bonds_problems(chelate, "[NH-]/C=C/C=O.[Cu+]", "Cu", bonded, charges)
    assert any("not the one the ring Cu closes forces" in p for p in probs), probs
    # a geometry outside any ring the metal closes, dropped: fails
    probs = structures.metal_bonds_problems(chelate + ".CC=CC", "[NH-]/C=C\\C=O.[Cu+].C/C=C/C", "Cu", bonded, charges)
    assert any("outside any ring of eight atoms or fewer" in p for p in probs), probs
    # ... and kept, passes; turned, fails
    assert structures.metal_bonds_problems(chelate + ".C/C=C/C", "[NH-]/C=C\\C=O.[Cu+].C/C=C/C", "Cu", bonded,
                                           charges) == []
    assert structures.metal_bonds_problems(chelate + ".C/C=C\\C", "[NH-]/C=C\\C=O.[Cu+].C/C=C/C", "Cu", bonded,
                                           charges) != []


def test_stereo_from_without_its_fields_stops_the_build(monkeypatch):
    seed = assemble._metal_bonds_seed()
    bad = {k: v for k, v in seed["vitamin-b12"].items() if k != "top"}
    monkeypatch.setitem(seed, "vitamin-b12", bad)
    with pytest.raises(SystemExit, match="metal_bonds: vitamin-b12: stereo_from"):
        assemble.structure_display_for("vitamin-b12", _rec("vitamin-b12")["isomeric_smiles"])
    monkeypatch.setitem(seed, "vitamin-b12", {k: v for k, v in bad.items() if k != "stereo_from"})
    with pytest.raises(SystemExit, match="14 stereocentre"):
        assemble.structure_display_for("vitamin-b12", _rec("vitamin-b12")["isomeric_smiles"])
    # cyanocobalamin's drawing is not vitamin B12's: its record writes the corrin's double bonds elsewhere
    monkeypatch.setitem(seed, "vitamin-b12", seed["cyanocobalamin"])
    with pytest.raises(SystemExit, match="not the record's own pieces"):
        assemble.structure_display_for("vitamin-b12", _rec("vitamin-b12")["isomeric_smiles"])


# ── one skeleton, one layout ─────────────────────────────────────────────────────────────────────────────────────
def _coords(smiles):
    m = Chem.MolFromSmiles(smiles)
    c = m.GetConformer()
    return m, {i: (c.GetAtomPosition(i).x, c.GetAtomPosition(i).y) for i in range(m.GetNumAtoms())}


def test_the_four_share_one_layout_and_differ_only_on_top():
    ref_m, ref_xy = _coords(_seed()["hydroxocobalamin"]["smiles"])
    ref_set = sorted((round(x, 3), round(y, 3), ref_m.GetAtomWithIdx(i).GetSymbol()) for i, (x, y) in ref_xy.items()
                     if ref_m.GetAtomWithIdx(i).GetSymbol() != "O" or (x, y) != ref_xy[_top_idx(ref_m)])
    for slug in COBALAMINS:
        m, xy = _coords(_seed()[slug]["smiles"])
        top = _top_atoms(m)
        here = sorted((round(x, 3), round(y, 3), m.GetAtomWithIdx(i).GetSymbol()) for i, (x, y) in xy.items()
                      if i not in top)
        assert here == ref_set, slug
        # the top group's first atom sits where the reference's hydroxide oxygen sits
        assert xy[_top_idx(m)] == ref_xy[_top_idx(ref_m)]
        # every coordinate written to three decimals at most
        tail = _seed()[slug]["smiles"].split("|(")[1]
        assert all(len(v.split(".")[1]) <= 3 for v in tail.replace(";", ",").split(",") if "." in v)


def _top_idx(m):
    co = _co(m)
    return next(x.GetIdx() for x in m.GetAtomWithIdx(co).GetNeighbors()
                if m.GetBondBetweenAtoms(co, x.GetIdx()).GetBondType() == Chem.BondType.SINGLE
                and not x.IsInRing())


def _top_atoms(m):
    t = _top_idx(m)
    return {t} | {x.GetIdx() for x in m.GetAtomWithIdx(t).GetNeighbors() if x.GetSymbol() != "Co"}


# ── the layout, judged on the shipped SVG ────────────────────────────────────────────────────────────────────────
ATOM_ATOM = 0.65      # bond lengths: any two atoms not bonded to each other
ATOM_BOND = 0.40      # bond lengths: any atom and a bond it is not part of
# The molecule page shows the 400 x 300 drawing in a stage 380 px tall with 16 px padding at desktop widths (464 x 348)
# and 220 px tall with 8 px padding at 720 px and below (272 x 204): moleculefinder-web app/globals.css, .meet
# .v3__stage. The thresholds in screen pixels at each, and at the drawing's own size.
RENDER = {"svg 400 px": 1.0, "page at 1440 px": 348 / 300, "page at 390 px": 204 / 300}
PX = {"svg 400 px": (13.0, 8.0), "page at 1440 px": (15.0, 9.5), "page at 390 px": (9.0, 5.5)}


def _seg_dist(p, a, b):
    (ax, ay), (bx, by), (px, py) = a, b, p
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _crosses(a, b, c, d):
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0


def _box_hits(box, a, b):
    x0, y0, x1, y1 = box
    if any(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for p in (a, b)):
        return True
    cs = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return any(_crosses(a, b, cs[i], cs[(i + 1) % 4]) for i in range(4))


def layout_numbers(svg: str, smiles: str) -> dict:
    mol = Chem.MolFromSmiles(smiles)
    rd = G.read_positions(svg, mol, use_identical=False)        # from the SVG alone, proven by a redraw
    dm = G.drawing_mol(mol, svg)
    pos, L = rd.pos, rd.scale_px
    n = dm.GetNumAtoms()
    bonds = [(b.GetBeginAtomIdx(), b.GetEndAtomIdx()) for b in dm.GetBonds()]
    aa = min(math.dist(pos[i], pos[j]) for i, j in itertools.combinations(range(n), 2)
             if dm.GetBondBetweenAtoms(i, j) is None)
    ab = min(_seg_dist(pos[k], pos[i], pos[j]) for k in range(n) for i, j in bonds if k not in (i, j))
    crossings = [((i, j), (k, l)) for (i, j), (k, l) in itertools.combinations(bonds, 2)
                 if len({i, j, k, l}) == 4 and _crosses(pos[i], pos[j], pos[k], pos[l])]
    bd, labels = G._bonds_and_labels(G.parse_svg(svg), 10 ** 6)
    boxes = {}
    for i, ps in labels.items():
        pts = [p for path in ps for sp in path.subpaths for p in sp]
        boxes[i] = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
    label_over_bond = [(i, (b.a, b.b)) for i, box in boxes.items() for b in bd.values() if i not in (b.a, b.b)
                       and any(_box_hits(box, s, e) for s, e in [*b.lines, *(
                           zip(b.polygon, [*b.polygon[1:], b.polygon[0]]) if b.polygon else [])])]
    label_over_label = [(i, j) for (i, p), (j, q) in itertools.combinations(boxes.items(), 2)
                        if p[0] < q[2] and q[0] < p[2] and p[1] < q[3] and q[1] < p[3]]
    carbon_labels = [i for i in labels if i < n and dm.GetAtomWithIdx(i).GetSymbol() == "C"]
    return {"method": rd.method, "bond_px": L, "atom_atom": aa, "atom_bond": ab, "crossings": crossings,
            "label_over_bond": label_over_bond, "label_over_label": label_over_label,
            "carbon_labels": carbon_labels, "contact_flag": "#FF0000" in svg, "mol": dm}


@pytest.mark.parametrize("slug", COBALAMINS)
def test_the_shipped_drawing_is_readable(slug):
    r = _rec(slug)
    k = layout_numbers(r["structure_svg"], r["structure_display"]["smiles"])
    assert k["method"] == "read"                                 # the positions are the SVG's own, proven
    L = k["bond_px"]
    assert k["atom_atom"] >= ATOM_ATOM * L and k["atom_bond"] >= ATOM_BOND * L, (k["atom_atom"] / L,
                                                                                k["atom_bond"] / L)
    for where, s in RENDER.items():
        aa, ab = PX[where]
        assert k["atom_atom"] * s >= aa and k["atom_bond"] * s >= ab, (where, k["atom_atom"] * s, k["atom_bond"] * s)
    assert not k["label_over_bond"] and not k["label_over_label"] and not k["carbon_labels"]
    assert not k["contact_flag"]
    # exactly one crossing: the bond from the cobalt to the benzimidazole over the ring's C14-C15 bond
    assert len(k["crossings"]) == 1
    (i, j), (p, q) = k["crossings"][0]
    dm = k["mol"]
    long_bond = {i, j} if dm.GetAtomWithIdx(i).GetSymbol() == "Co" or dm.GetAtomWithIdx(j).GetSymbol() == "Co" \
        else {p, q}
    rim = {p, q} if long_bond == {i, j} else {i, j}
    co = next(x for x in long_bond if dm.GetAtomWithIdx(x).GetSymbol() == "Co")
    n3 = next(x for x in long_bond if x != co)
    assert dm.GetAtomWithIdx(n3).GetIsAromatic() and dm.GetAtomWithIdx(n3).GetSymbol() == "N"
    a, b = (dm.GetAtomWithIdx(x) for x in rim)
    assert a.GetSymbol() == b.GetSymbol() == "C"
    assert dm.GetBondBetweenAtoms(*rim).GetBondTypeAsDouble() in (1.0, 2.0)
    # one end the meso carbon (C15: in no five-membered ring), the other a ring C carbon (C14)
    ri = dm.GetRingInfo()
    assert sorted(any(len(x) == 5 and at.GetIdx() in x and co not in x for x in ri.AtomRings()) for at in (a, b)) \
        == [False, True]


def test_the_layout_test_fails_a_crowded_drawing():
    """The same reading on the earlier prototype's kind of drawing: RDKit's own layout of the bonded molecule."""
    smi = _seed()["hydroxocobalamin"]["smiles"].split(" |")[0]
    svg = structures.svg_for(smi)
    k = layout_numbers(svg, smi)
    bad = (len(k["crossings"]) != 1 or k["label_over_bond"] or k["label_over_label"] or k["contact_flag"]
           or k["atom_atom"] < ATOM_ATOM * k["bond_px"] or k["atom_bond"] < ATOM_BOND * k["bond_px"])
    assert bad


# ── parts, lines, pairs, doors, weeks ────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("slug", COBALAMINS)
def test_the_three_part_layers_are_remade_from_the_new_drawing_with_the_same_atoms(slug):
    sp = _rec(slug)["structure_parts"]
    assert sp["recipe"] == drawings.PARTS_RECIPE and not sp.get("unread")
    got = [(p["id"], p["label"], len(p["atoms"]), len(p["bonds"])) for p in sp["parts"]]
    assert got == [("amide", "The amide group", 28, 21), ("phosphate", "The phosphate group", 5, 4),
                   ("alcohol", "The hydroxyl group", 4, 2)]
    for p in sp["parts"]:
        assert drawings.compose(_rec(slug)["structure_svg"], p["layer"]) != _rec(slug)["structure_svg"]


@pytest.mark.parametrize("slug", COBALAMINS)
def test_each_line_says_what_the_brief_says(slug):
    line = _rec(slug)["structure_display"]["line"]
    grp = {"cyanocobalamin": "the cyanide", "vitamin-b12": "the cyanide", "hydroxocobalamin": "the hydroxide",
           "methylcobalamin": "the methyl group"}[slug]
    assert line.startswith(f"Drawn with the cobalt bonded to the four nitrogens of the ring, to {grp} above the ring "
                           "and to the benzimidazole nitrogen below it, which PubChem's one-line structure leaves apart")
    assert "The + written on the cobalt is formal bookkeeping; the cobalt itself is cobalt(III)." in line
    no_stereo = ("PubChem's record of it carries no stereochemistry; the wedges shown are those of hydroxocobalamin's "
                 "record, which shares this skeleton.")
    assert (no_stereo in line) == (slug in ("vitamin-b12", "methylcobalamin"))
    assert ("one ribose carbon" in line) == (slug == "cyanocobalamin")
    assert "—" not in line and "–" not in line
    assert not any(f" {w} " in f" {line.lower()} " for w in CLAIM_WORDS)
    keys = {k for kind, k, _ in claims.corpus() if kind == "part"}
    assert f"display.{slug}.line" in keys


def test_cyanocobalamins_drawing_shows_a_wedge_on_the_anomeric_carbon():
    """Its line names the one ribose carbon, so the drawing must show a wedge there."""
    r = _rec("cyanocobalamin")
    m = Chem.MolFromSmiles(r["structure_display"]["smiles"])
    anomeric = next(a.GetIdx() for a in m.GetAtoms() if a.GetSymbol() == "C" and not a.GetIsAromatic()
                    and any(x.GetSymbol() == "N" and x.GetIsAromatic() for x in a.GetNeighbors())
                    and any(x.GetSymbol() == "O" and x.IsInRing() for x in a.GetNeighbors()))
    assert m.GetAtomWithIdx(anomeric).GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED
    bonds, _ = G._bonds_and_labels(G.parse_svg(r["structure_svg"]), 10 ** 6)
    wedges = [bd for bd in bonds.values() if anomeric in (bd.a, bd.b) and (bd.polygon or len(bd.lines) >= 3)]
    assert len(wedges) == 1                                   # a solid or hashed wedge at the anomeric carbon


def test_none_of_the_four_is_in_a_pair_a_door_or_a_week():
    pairs = json.loads((SNAP / "compare_drawings.json").read_text())
    text = json.dumps(pairs) + (SNAP / "comparisons.json").read_text() + (SNAP / "doors.json").read_text()
    weeks = yaml.safe_load((SEEDS_DIR / "featured.yaml").read_text())["weeks"]
    for slug in COBALAMINS:
        assert f'"{slug}"' not in text and f"{slug}-vs-" not in text and f"-vs-{slug}" not in text, slug
        assert slug not in {w["slug"] for w in weeks}
