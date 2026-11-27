"""The drawing-findings pass (2026-11-27): what the drawing-truth review's first run found (trust-reports/
drawings-2026-11-27.md), fixed on Cowork's rulings, Garrett's word. Brief: ../TRUST-2B-DRAWING-FINDINGS-PROMPT.md.
Every remake is deliberate and the drawing guard LISTS it.

A. Magnesium glycinate is redrawn as the chelate it is (structure_display.yaml metal_bonds); the 31 other salts of an
   organic ion stay drawn as their ions (the review's salts-as-ions list, tests/test_review_drawings.py).
B. Six polymers drawn as if one small molecule get a repeat unit in place of PubChem's drawing (repeat_units.yaml
   `replaces`), each derived here from a catalog molecule or a stated rule, stereo included.
C. Butylated hydroxyanisole and ivermectin keep their two-compound drawing with a note (structure_notes.yaml); ABS is
   redrawn as its three chain units (the separate-units variant). Shellac is held (its record's chain acid is C15,
   not shellac's aleuritic acid), so it is neither noted nor allowlisted.

The values PubChem gave the records before the pass (main's snapshot, ebde934) are pinned in
tests/fixtures/drawing-findings-before-2026-11-27.json.
"""
from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem.rdMolDescriptors import CalcMolFormula

from moleculefinder_etl.transform import assemble, claims, drawings, structures
from moleculefinder_etl.transform import drawing_guard as DG
from tests.test_drawings import _glucosyl_units

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "data" / "snapshots"
BEFORE = json.loads((ROOT / "tests" / "fixtures" / "drawing-findings-before-2026-11-27.json").read_text())
CLAIM_WORDS = re.compile(r"\b(only|first|most|leading|largest|world's|never|always)\b", re.IGNORECASE)
POLYMERS = ("chitin", "hyaluronic-acid", "glycogen", "maltodextrin", "inulin", "poly-methyl-methacrylate")
UNITS = POLYMERS + ("acrylonitrile-butadiene-styrene",)


def _rec(slug):
    return json.loads((SNAP / "molecules" / f"{slug}.json").read_text())


@pytest.fixture(scope="module")
def by_slug():
    return {p.stem: json.loads(p.read_text()) for p in (SNAP / "molecules").glob("*.json")}


def _seed(slug):
    return drawings.load_repeat_seed()[slug]


def _plain(smiles):
    """The SMILES without its CXSMILES block (a stored layout and the `*` labels)."""
    return smiles.split(" |")[0]


def _canon(smiles):
    return Chem.MolToSmiles(Chem.MolFromSmiles(smiles))


def _edit(mol, pattern, keep_as):
    """Each match of ``pattern`` (its first atom bonded to the ring, kept in place) turned into ``keep_as`` by
    changing that first atom's element and deleting the rest of the match: the ring carbon keeps its neighbours in
    the same order, so its stereo tag means what it meant. (RDKit's ReplaceSubstructs re-adds the atom and can flip
    the parity.)"""
    rw = Chem.RWMol(mol)
    gone = []
    for m in mol.GetSubstructMatches(Chem.MolFromSmarts(pattern)):
        head = rw.GetAtomWithIdx(m[0])
        head.SetAtomicNum({"OH": 8, "CH2OH": 6}[keep_as])
        head.SetNoImplicit(False)
        head.SetNumExplicitHs(0)
        gone += list(m[1:])
    for i in sorted(set(gone), reverse=True):
        rw.RemoveAtom(i)
    out = rw.GetMol()
    Chem.SanitizeMol(out)
    return out


# ── A. magnesium glycinate ───────────────────────────────────────────────────────────────────────────────────────
def test_magnesium_glycinate_is_drawn_from_its_checked_display_structure():
    r = _rec("magnesium-glycinate")
    before = BEFORE["records"]["magnesium-glycinate"]
    assert r["isomeric_smiles"] == before["isomeric_smiles"] == "C(C(=O)[O-])N.C(C(=O)[O-])N.[Mg+2]"
    assert r["molecular_formula"] == "C4H8MgN2O4"      # two glycinates per magnesium, as the curated line says
    assert "two glycine" in r["why_it_matters"]["text"]
    d = r["structure_display"]
    assert d["kind"] == "metal_bonds" and d["metal"] == "Mg" and r["has_3d"] is False
    assert r["structure_svg_key"] == structures.svg_key(d["smiles"])
    assert d == assemble.metal_bonds_for("magnesium-glycinate", r["isomeric_smiles"])


def test_the_magnesium_holds_each_glycinate_by_its_nitrogen_and_one_oxygen():
    mol = Chem.MolFromSmiles(_rec("magnesium-glycinate")["structure_display"]["smiles"])
    mg = next(a for a in mol.GetAtoms() if a.GetSymbol() == "Mg")
    bonds = {(n.GetSymbol(), str(mol.GetBondBetweenAtoms(mg.GetIdx(), n.GetIdx()).GetBondType()))
             for n in mg.GetNeighbors()}
    assert sorted(n.GetSymbol() for n in mg.GetNeighbors()) == ["N", "N", "O", "O"]
    # the shipped rule: plain to the oxygen charged in the record, a dative arrow from the neutral nitrogen
    assert bonds == {("N", "DATIVE"), ("O", "SINGLE")}
    assert all(a.GetFormalCharge() == 0 for a in mol.GetAtoms())
    # two five-membered rings through the magnesium: Mg-N-C-C-O
    # dative bonds are not ring bonds to RDKit, so walk each ring: Mg, N, C, C, O back to Mg
    five = []
    for n in (x for x in mg.GetNeighbors() if x.GetSymbol() == "N"):
        c = next(x for x in n.GetNeighbors() if x.GetSymbol() == "C")
        cc = next(x for x in c.GetNeighbors() if x.GetIdx() != n.GetIdx())
        o = next(x for x in cc.GetNeighbors() if x.GetSymbol() == "O" and mol.GetBondBetweenAtoms(x.GetIdx(), mg.GetIdx()))
        five.append({mg.GetIdx(), n.GetIdx(), c.GetIdx(), cc.GetIdx(), o.GetIdx()})
    assert len(five) == 2 and len(five[0] & five[1]) == 1
    assert CalcMolFormula(mol) == "C4H8MgN2O4"


def test_deleting_the_four_bonds_gives_back_pubchems_pieces_and_a_wrong_entry_fails():
    e = assemble._metal_bonds_seed()["magnesium-glycinate"]
    rec = BEFORE["records"]["magnesium-glycinate"]["isomeric_smiles"]
    ok = structures.metal_bonds_problems(e["smiles"], rec, "Mg", e["bonded"], e["charges"])
    assert ok == []
    # only one glycinate chelated (the other by its oxygen alone): three bonds, not four
    one = "O=C1[O][Mg]([O]C(=O)C[NH2])<-[NH2]C1"
    assert structures.metal_bonds_problems(one, rec, "Mg", e["bonded"], e["charges"]) != []
    # bonded by both oxygens of a carboxylate and not the nitrogen
    wrong = "O=C1[O][Mg]2([O]C(=O)C[NH2]->2)[O]C1C[NH2]"
    assert structures.metal_bonds_problems(wrong, rec, "Mg", e["bonded"], e["charges"]) != []


def test_the_two_rings_are_laid_out_symmetric_about_the_magnesium():
    """The stored layout: every atom of one ring has its twin at the opposite point through the magnesium (the
    second ring the first turned half a turn), and every bond is the same length."""
    mol = Chem.MolFromSmiles(_rec("magnesium-glycinate")["structure_display"]["smiles"])
    c = mol.GetConformer()
    p = {a.GetIdx(): (c.GetAtomPosition(a.GetIdx()).x, c.GetAtomPosition(a.GetIdx()).y) for a in mol.GetAtoms()}
    mg = next(a.GetIdx() for a in mol.GetAtoms() if a.GetSymbol() == "Mg")
    assert p[mg] == (0.0, 0.0)
    for a in mol.GetAtoms():
        if a.GetIdx() == mg:
            continue
        twin = [b for b in mol.GetAtoms() if b.GetSymbol() == a.GetSymbol() and b.GetIdx() != a.GetIdx()
                and math.dist(p[b.GetIdx()], (-p[a.GetIdx()][0], -p[a.GetIdx()][1])) < 0.01]
        assert len(twin) == 1, a.GetIdx()
    lengths = [math.dist(p[b.GetBeginAtomIdx()], p[b.GetEndAtomIdx()]) for b in mol.GetBonds()]
    assert max(lengths) - min(lengths) < 0.01


def test_magnesium_glycinates_line_follows_chromium_picolinates():
    line = _rec("magnesium-glycinate")["structure_display"]["line"]
    cr = assemble._metal_bonds_seed()["chromium-iii-picolinate"]["line"]
    assert line == ("Drawn with the magnesium bonded to the amine nitrogen and one carboxylate oxygen of each of its "
                    "two glycinates, two five-membered rings; PubChem's one-line structure leaves the magnesium apart.")
    assert " ".join(cr.split()).endswith("PubChem's one-line structure leaves the chromium apart.")
    assert not CLAIM_WORDS.search(line) and "—" not in line and "–" not in line


def test_magnesium_glycinates_amine_part_left_with_its_redraw():
    """The drawing guard lists it: the amine pattern ([NX3;H2,H1]) does not match a nitrogen bonded to the magnesium,
    so the record carries no part layer now (it had one, the amine on both nitrogens)."""
    assert BEFORE["records"]["magnesium-glycinate"]["parts"] == ["amine"]
    assert _rec("magnesium-glycinate").get("structure_parts") is None
    assert "amines" in [c["slug"] for c in _rec("magnesium-glycinate")["categories"]]   # the hub reads PubChem's


# ── B. the six repeat units and C4, ABS ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("slug", UNITS)
def test_each_unit_replaces_pubchems_drawing_as_carboxymethyl_cellulose_does(slug):
    r, before = _rec(slug), BEFORE["records"][slug]
    u = r["structure_repeat_unit"]
    assert r["cid"] == before["cid"] and r["title"] == before["title"]
    assert before["structure_svg_key"] and r["structure_svg"] is None and r["structure_svg_key"] is None
    assert r["macromolecule"] is True and r["has_3d"] is False and r.get("structure_parts") is None
    for k in ("molecular_formula", "molecular_weight", "isomeric_smiles", "canonical_smiles", "inchi", "inchikey"):
        assert r[k] is None, (slug, k)
    assert r["edges"] == [] and not [c for c in r["categories"] if c["kind"] in ("functional_group", "element", "size")]
    spec = _seed(slug)
    assert u["smiles"] == spec["smiles"] and u["key"] == drawings.repeat_key(slug, spec)
    assert f"CID {before['cid']}" in u["replaces"] and u["line"] and u["units"] == spec["units"]
    assert u["source"] == "MoleculeFinder curated"


@pytest.mark.parametrize("slug", UNITS)
def test_each_unit_and_line_keeps_the_house_rules(slug):
    spec = _seed(slug)
    for f in ("label", "line", "replaces"):
        text = " ".join(str(spec[f]).split())
        assert not CLAIM_WORDS.search(text) and "—" not in text and "–" not in text, (slug, f)
    line = " ".join(spec["line"].split())
    assert re.search(r"[Tt]he drawing shows", line), slug          # what the polymer is, and that this is a piece
    assert drawings.text_problems([(f"repeat.{slug}.{f}", " ".join(str(spec[f]).split()))
                                   for f in ("label", "line", "replaces")]) == []
    mol = Chem.MolFromSmiles(spec["smiles"])
    assert sum(a.GetNumRadicalElectrons() for a in mol.GetAtoms()) == 0
    # every chain end is a real `*` (atomic number 0, not a query atom), a stored layout or not
    assert all(not a.HasQuery() for a in mol.GetAtoms() if a.GetAtomicNum() == 0)


def test_chitin_is_celluloses_unit_with_an_acetamido_group_on_each_carbon_2():
    """Take the acetamido group (NH-CO-CH3) off each unit and put the hydroxyl back: cellulose's unit, stereo
    included (the configuration at carbon 2 does not move)."""
    ch = Chem.MolFromSmiles(_seed("chitin")["smiles"])
    back = _edit(ch, "[NX3H1]C(=O)[CH3]", "OH")
    assert Chem.MolToSmiles(back) == _canon(_seed("cellulose")["smiles"])
    assert len(ch.GetSubstructMatches(Chem.MolFromSmarts("[#6;R][NX3H1]C(=O)[CH3]"))) == 2
    assert _seed("chitin")["linkage"] == "beta-1,4"


def test_hyaluronic_acid_is_glucuronic_acid_beta_1_3_to_n_acetylglucosamine(by_slug):
    """Reduce the glucuronic acid's COOH to CH2OH and swap the acetamido for OH: two beta-D-glucose units (the beta
    pattern cut from the catalog's maltose matches both, the alpha neither), joined from one anomeric carbon to the
    other unit's carbon 3; the chain carries on from the glucuronic acid's carbon 4 and the N-acetylglucosamine's
    carbon 1, the two beta-1,4 half-joints the unit marks at its ends."""
    alpha, beta = _glucosyl_units(by_slug)
    ha = Chem.MolFromSmiles(_seed("hyaluronic-acid")["smiles"])
    m = _edit(ha, "[NX3H1]C(=O)[CH3]", "OH")
    # the carboxyl carbon stays (as CH2), its C=O oxygen goes; the OH stays the OH of CH2OH
    m = _edit(m, "[CX3;$(C[OX2H1])]=[OX1]", "CH2OH")
    q = Chem.MolFromSmiles(Chem.MolToSmiles(m))
    assert len(q.GetSubstructMatches(beta, useChirality=True)) >= 1
    assert len(q.GetSubstructMatches(alpha, useChirality=True)) == 0
    # both rings are beta-D-glucose: each anomeric carbon and the ring with its four substituents (pattern below)
    ring = Chem.MolFromSmarts("[#8][C@@H]1O[C@H](CO)[C@@H]([#8])[C@H]([#8])[C@H]1O")
    assert len(q.GetSubstructMatches(ring, useChirality=True)) == 2
    # the internal joint runs from the glucuronic acid's anomeric carbon to the N-acetylglucosamine's carbon 3: the
    # ring carbon next to carbon 2 (which carries the nitrogen), itself next to the anomeric carbon (ring O beside it)
    joint = Chem.MolFromSmarts("[C;R]([O;R])-[O;!R]-[C;R]-[C;R]([N])-[C;R]([O;R])")
    assert len(ha.GetSubstructMatches(joint)) == 1
    u = _rec("hyaluronic-acid")["structure_repeat_unit"]
    assert (u["linkage"], [a["linkage"] for a in u["also"]]) == ("beta-1,3", ["beta-1,4"])
    assert [ha.GetAtomWithIdx(i).GetSymbol() for i in u["linkage_atoms"]] == ["C", "O", "C"]
    assert sorted(ha.GetAtomWithIdx(i).GetSymbol() for i in u["also"][0]["linkage_atoms"]) == ["C", "C", "O", "O"]
    assert "alternat" in u["label"]


def test_glycogen_is_starchs_unit_with_an_alpha_1_6_branch(by_slug):
    """Three alpha-D-glucose units (the alpha pattern cut from the catalog's maltose matches all three, the beta
    none); cut the branch off at the 1,6 joint and put the hydroxyl back on carbon 6: starch's unit, stereo
    included."""
    alpha, beta = _glucosyl_units(by_slug)
    g = Chem.MolFromSmiles(_seed("glycogen")["smiles"])
    assert len(g.GetSubstructMatches(alpha, useChirality=True)) == 3
    assert len(g.GetSubstructMatches(beta, useChirality=True)) == 0
    u = _rec("glycogen")["structure_repeat_unit"]
    c1, o6, c6 = (g.GetAtomWithIdx(i) for i in u["also"][0]["linkage_atoms"])
    assert {c1.GetSymbol(), o6.GetSymbol(), c6.GetSymbol()} == {"C", "O"}
    # the branch's anomeric carbon is the ring carbon of the three bonded to two oxygens
    anomeric = next(a for a in (c1, c6) if a.IsInRing())
    oxygen = next(a for a in (c1, o6, c6) if a.GetSymbol() == "O")
    rw = Chem.RWMol(g)
    rw.RemoveBond(anomeric.GetIdx(), oxygen.GetIdx())
    frags = Chem.GetMolFrags(rw.GetMol(), asMols=False)
    keep = next(f for f in frags if oxygen.GetIdx() in f)
    chain = Chem.MolFragmentToSmiles(rw.GetMol(), atomsToUse=list(keep), isomericSmiles=True)
    assert _canon(chain) == _canon(_seed("starch")["smiles"])
    assert (u["linkage"], u["also"][0]["linkage"], u["units"]) == ("alpha-1,4", "alpha-1,6", 3)


def test_maltodextrin_is_starchs_own_unit_labelled_as_a_short_chain():
    assert _seed("maltodextrin")["smiles"] == _seed("starch")["smiles"]
    assert _seed("maltodextrin")["label"] == "Two units of a short chain"
    line = " ".join(_seed("maltodextrin")["line"].split())
    assert "length of its chains, not the unit" in line
    assert _rec("maltodextrin")["structure_repeat_unit"]["svg"] == _rec("starch")["structure_repeat_unit"]["svg"]


def test_inulin_is_two_fructofuranose_units_cut_from_sucrose_joined_beta_2_1(by_slug):
    """The beta-D-fructofuranosyl unit cut from the catalog's sucrose (its fructose half, the glucose carbon made any
    atom) matches both units, stereo included; its mirror at the anomeric carbon (alpha) matches neither."""
    suc = Chem.MolFromSmiles(by_slug["sucrose"]["isomeric_smiles"])
    c2 = next(a for a in suc.GetAtoms() if a.GetSymbol() == "C" and a.IsInRing() and a.GetTotalNumHs() == 0)
    ring = next(set(r) for r in suc.GetRingInfo().AtomRings() if c2.GetIdx() in r)
    og = next(n for n in c2.GetNeighbors() if n.GetSymbol() == "O" and n.GetIdx() not in ring)
    glc = next(n for n in og.GetNeighbors() if n.GetIdx() != c2.GetIdx())
    keep, stack = set(), [c2.GetIdx()]
    while stack:
        i = stack.pop()
        if i in keep or i == glc.GetIdx():
            continue
        keep.add(i)
        stack += [n.GetIdx() for n in suc.GetAtomWithIdx(i).GetNeighbors()]
    rw = Chem.RWMol(suc)
    rw.GetAtomWithIdx(glc.GetIdx()).SetAtomicNum(0)
    rw.GetAtomWithIdx(glc.GetIdx()).SetNoImplicit(True)
    rw.GetAtomWithIdx(glc.GetIdx()).SetNumExplicitHs(0)
    fru = Chem.MolFragmentToSmiles(rw, atomsToUse=sorted(keep | {glc.GetIdx()}), isomericSmiles=True)
    # the CH2OH on carbon 1 carries the chain on in inulin: its oxygen may bond to any atom
    beta = Chem.MolFromSmarts(fru.replace("(CO)", "(C[O,$(O*)])", 1))
    inv = Chem.RWMol(Chem.MolFromSmiles(fru))
    next(a for a in inv.GetAtoms() if a.GetSymbol() == "C" and a.IsInRing() and a.GetTotalNumHs() == 0).InvertChirality()
    alpha = Chem.MolFromSmarts(Chem.MolToSmiles(inv).replace("(CO)", "(C[O,$(O*)])", 1))
    unit = Chem.MolFromSmiles(_plain(_seed("inulin")["smiles"]))
    assert len(unit.GetSubstructMatches(Chem.MolFromSmarts(fru), useChirality=True)) >= 1
    assert len(unit.GetSubstructMatches(beta, useChirality=True)) == 2
    assert len(unit.GetSubstructMatches(alpha, useChirality=True)) == 0
    # the joint: the anomeric carbon of one unit, through an oxygen, to the CH2 (carbon 1) of the next
    u = _rec("inulin")["structure_repeat_unit"]
    a, o, c = (unit.GetAtomWithIdx(i) for i in u["linkage_atoms"])
    assert sorted(x.GetSymbol() for x in (a, o, c)) == ["C", "C", "O"]
    assert u["linkage"] == "beta-2,1" and "one glucose" in u["line"]


def test_pmma_is_the_briefs_two_units_joined_where_the_double_bond_opened():
    spec = _seed("poly-methyl-methacrylate")
    assert _plain(spec["smiles"]) == "*CC(C)(C(=O)OC)CC(C)(C(=O)OC)*"
    mol = Chem.MolFromSmiles(spec["smiles"])
    assert not any(b.GetBondType() == Chem.BondType.DOUBLE and {b.GetBeginAtom().GetSymbol(),
                   b.GetEndAtom().GetSymbol()} == {"C"} for b in mol.GetBonds())
    assert not Chem.FindMolChiralCenters(mol, includeUnassigned=False)
    u = _rec("poly-methyl-methacrylate")["structure_repeat_unit"]
    a, b = u["linkage_atoms"]
    # cutting the marked bond leaves two identical units, each a methyl methacrylate with its double bond opened
    rw = Chem.RWMol(Chem.MolFromSmiles(_plain(spec["smiles"])))
    rw.RemoveBond(a, b)
    for i in (a, b):
        rw.AddAtom(Chem.Atom(0))
        rw.AddBond(i, rw.GetNumAtoms() - 1, Chem.BondType.SINGLE)
    pieces = Chem.MolToSmiles(rw.GetMol()).split(".")
    assert len(pieces) == 2 and pieces[0] == pieces[1]
    assert drawings.unit_monomers(pieces[0]) == [_canon("C=C(C)C(=O)OC")]
    assert u["linkage"] == "carbon-carbon"


def test_abs_units_are_the_records_own_monomers_opened_into_chains():
    spec = _seed("acrylonitrile-butadiene-styrene")
    pubchem = BEFORE["records"]["acrylonitrile-butadiene-styrene"]["isomeric_smiles"]
    assert pubchem == "C=CC=C.C=CC#N.C=CC1=CC=CC=C1"
    assert drawings.canonical_pieces(spec["monomers"]) == drawings.canonical_pieces(pubchem)
    assert drawings.unit_monomers(spec["smiles"]) == drawings.canonical_pieces(pubchem)
    assert _plain(spec["smiles"]) == "*CC(C#N)*.*CC=CC*.*CC(c1ccccc1)*"
    u = _rec("acrylonitrile-butadiene-styrene")["structure_repeat_unit"]
    assert u["variant"] == "separate-units" and u["layer"] is None and u["linkage"] is None
    assert u["linkage_atoms"] == [] and u["units"] == 3
    assert u["label"] == "The three units its chains are built from"
    assert " ".join(spec["line"].split()) == (
        "ABS has no single repeat unit: chains of styrene and acrylonitrile units are grafted onto, and blended with, a "
        "rubber made of butadiene units; the drawing shows the three units.")
    # no order implied: the three sit side by side, left to right, none bonded to another
    assert len(Chem.GetMolFrags(Chem.MolFromSmiles(spec["smiles"]))) == 3
    assert "mf-linkage" not in u["svg"]


def test_the_separate_units_check_fails_a_wrong_unit():
    good = dict(_seed("acrylonitrile-butadiene-styrene"))
    drawings.repeat_unit_marks(good, Chem.MolFromSmiles(good["smiles"]))
    # (a butadiene unit joined 1,2, *CC(C=C)*, opens back to butadiene too, as it should: it is a butadiene unit)
    for smiles in ("*CC(C#N)*.*C=CCC*.*CC(c1ccccc1)*",      # a double bond in the wrong place
                   "*CC(C#N)*.*CC=CC*",                      # a unit missing
                   "*CC(C#N)C*.*CC=CC*.*CC(c1ccccc1)*"):     # ends that are not a vinyl unit's
        bad = {**good, "smiles": smiles}
        with pytest.raises(drawings.DrawingSeedError):
            drawings.repeat_unit_marks(bad, Chem.MolFromSmiles(smiles))
    with pytest.raises(drawings.DrawingSeedError):
        drawings.repeat_unit_marks({**good, "linkage_smarts": "[#6]-[#6]", "linkage": "x"},
                                   Chem.MolFromSmiles(good["smiles"]))
    with pytest.raises(drawings.DrawingSeedError):
        drawings.repeat_unit_marks({**good, "monomers": "C=CC=C.C=CC#N.C=CC1=CC=CC=C1C"},
                                   Chem.MolFromSmiles(good["smiles"]))


def test_the_build_stops_if_pubchems_abs_record_is_no_longer_the_three_monomers():
    assemble._check_unit_monomers("acrylonitrile-butadiene-styrene", "C=CC=C.C=CC#N.C=CC1=CC=CC=C1")
    with pytest.raises(SystemExit, match="monomers"):
        assemble._check_unit_monomers("acrylonitrile-butadiene-styrene", "C=CC=C.C=CC#N")


def test_a_second_joint_must_match_its_count_and_not_overlap_the_first():
    spec = dict(_seed("glycogen"))
    mol = Chem.MolFromSmiles(spec["smiles"])
    with pytest.raises(drawings.DrawingSeedError, match="alpha-1,6"):
        drawings.repeat_unit_marks({**spec, "also": [{**spec["also"][0], "linkages": 2}]}, mol)
    with pytest.raises(drawings.DrawingSeedError, match="overlaps"):
        drawings.repeat_unit_marks({**spec, "also": [{"linkage": "x", "linkage_smarts": "[#6;R]-[#8;!R]-[#6;R]"}]},
                                   mol)
    with pytest.raises(drawings.DrawingSeedError, match="variant"):
        drawings.repeat_unit_marks({**spec, "variant": "branched"}, mol)


def test_the_four_existing_units_did_not_move():
    """The new fields and the shared marking code change nothing for starch, cellulose, carboxymethyl cellulose and
    simeticone: their keys, drawings and layers are what shipped, and their marks are the same atoms today."""
    for slug in ("starch", "cellulose", "carboxymethyl-cellulose", "simeticone"):
        spec, u = _seed(slug), _rec(slug)["structure_repeat_unit"]
        assert u["key"] == drawings.repeat_key(slug, spec)
        _, _, marks = drawings.repeat_unit_marks(spec, Chem.MolFromSmiles(spec["smiles"]))
        assert marks["linkage_atoms"] == u["linkage_atoms"] and "also" not in u and "variant" not in u
        assert marks.get("group_atoms") == u.get("group_atoms")


def test_hyaluronic_acids_label_ingredient_keeps_its_link_by_code():
    """Sodium hyaluronate (UNII YSE9PPT4TH) reached hyaluronic acid by the skeleton rule through the record's
    InChIKey, which the record no longer carries; the code is ruled a form (unii_aliases.yaml), so the two label pages
    keep their link."""
    prods = {p["slug"]: p for p in json.loads((SNAP / "products.json").read_text())["products"]}
    for slug in ("cerave-hydrating-mineral-sunscreen-spf-30", "eltamd-uv-clear"):
        row = next(m for m in prods[slug]["molecules"] if m.get("slug") == "hyaluronic-acid")
        assert row["match"] == "alias"


# ── C. the mixtures' notes ───────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("slug", ["butylated-hydroxyanisole", "ivermectin"])
def test_the_kept_mixtures_carry_their_note_and_keep_their_drawing(slug):
    r, before = _rec(slug), BEFORE["records"][slug]
    assert r["structure_svg_key"] == before["structure_svg_key"] and r["isomeric_smiles"] == before["isomeric_smiles"]
    assert len(before["isomeric_smiles"].split(".")) == 2
    assert r["structure_note"] == assemble.structure_note_for(slug, True, None)
    line = r["structure_note"]["line"]
    assert line.startswith("The drawing shows both of its")
    assert not CLAIM_WORDS.search(line) and "—" not in line and "–" not in line
    assert ("part", f"note.{slug}.line", line) in claims.corpus()


def test_ivermectins_note_names_the_two_and_gives_the_labels_proportions():
    line = _rec("ivermectin")["structure_note"]["line"]
    assert "B1a" in line and "B1b" in line and "sec-butyl" in line and "isopropyl" in line
    assert "at least 90 percent B1a and less than 10 percent B1b" in line and "Stromectol" in line
    pieces = [CalcMolFormula(Chem.MolFromSmiles(s)) for s in BEFORE["records"]["ivermectin"]["isomeric_smiles"].split(".")]
    assert sorted(pieces) == ["C47H72O14", "C48H74O14"]          # one carbon (and its two hydrogens) apart


def test_bhas_two_drawn_pieces_are_the_two_isomers_its_note_names():
    a, b = BEFORE["records"]["butylated-hydroxyanisole"]["isomeric_smiles"].split(".")
    ma, mb = Chem.MolFromSmiles(a), Chem.MolFromSmiles(b)
    assert CalcMolFormula(ma) == CalcMolFormula(mb) == "C11H16O2" and _canon(a) != _canon(b)
    next_to_oh = Chem.MolFromSmarts("[OH]c:c[C](C)(C)C")
    next_to_ome = Chem.MolFromSmarts("[CH3]Oc:c[C](C)(C)C")
    assert sorted((m.HasSubstructMatch(next_to_oh), m.HasSubstructMatch(next_to_ome)) for m in (ma, mb)) == \
        [(False, True), (True, False)]


def test_a_note_needs_a_drawing_and_no_display_structure():
    with pytest.raises(SystemExit, match="no drawing"):
        assemble.structure_note_for("ivermectin", False, None)
    with pytest.raises(SystemExit, match="display structure"):
        assemble.structure_note_for("ivermectin", True, {"line": "x"})
    assert assemble.structure_note_for("caffeine", True, None) is None


def test_shellac_is_held_and_untouched():
    """The record's two pieces: shellolic acid's skeleton (C15H20O6) and 9,10,15-trihydroxypentadecanoic acid
    (C15H30O5), which is not aleuritic acid (9,10,16-trihydroxyhexadecanoic acid, C16H32O5), shellac's main acid. The
    ruling's line ("two of the acids shellac is built from") would not be true of the second, so shellac waits."""
    before = BEFORE["records"]["shellac"]
    f = sorted(CalcMolFormula(Chem.MolFromSmiles(s)) for s in before["isomeric_smiles"].split("."))
    assert f == ["C15H20O6", "C15H30O5"]
    r = _rec("shellac")
    assert r["structure_svg_key"] == before["structure_svg_key"] and "structure_note" not in r
    assert "shellac" not in assemble._notes_seed()


# ── the drawing guard's list ─────────────────────────────────────────────────────────────────────────────────────
def test_the_guard_lists_exactly_the_passs_changes(tmp_path):
    """Against a shipped snapshot shaped as main was before this pass (the fixture's keys and SMILES), the guard lists
    magnesium glycinate's redraw and its dropped part set, the seven drawings replaced by their units with their part
    sets and seven new units, and the two pairs remade; it stops nothing."""
    shipped = tmp_path / "snapshots"
    shutil.copytree(SNAP / "molecules", shipped / "molecules")
    cd = json.loads((SNAP / "compare_drawings.json").read_text())
    for k, v in BEFORE["pairs"].items():
        cd["pairs"][k] = {**cd["pairs"][k], **v}
    (shipped / "compare_drawings.json").write_text(json.dumps(cd))
    for slug in (*UNITS, "magnesium-glycinate"):
        p = shipped / "molecules" / f"{slug}.json"
        r, b = json.loads(p.read_text()), BEFORE["records"][slug]
        r["structure_svg"], r["structure_svg_key"] = "<svg/>", b["structure_svg_key"]
        r["isomeric_smiles"] = b["isomeric_smiles"]
        r.pop("structure_display", None)
        r["structure_repeat_unit"] = None
        r["structure_parts"] = {"recipe": drawings.PARTS_RECIPE, "key": b["parts_key"], "parts": [], "unread": False}
        p.write_text(json.dumps(r))
    by_cid, pairs = DG.shipped(SNAP)
    v = DG.check([by_cid[c] for c in sorted(by_cid)], pairs, shipped, allow_seeds=False)
    assert v.stops == []
    replaced = "removed, replaced by its repeat unit (repeat_units.yaml `replaces`), a deliberate remake"
    want = {f"{s} (structure drawing): {replaced}" for s in UNITS}
    want |= {f"{s} (repeat unit): new, added in repeat_units.yaml" for s in UNITS}
    want |= {(f"{s} (structure parts): dropped, its SMILES changed, its drawing was replaced by its repeat unit "
              f"(repeat_units.yaml `replaces`)") for s in UNITS}
    mg = "structure_display.yaml metal_bonds: drawn with the Mg bonds"
    want |= {f"magnesium-glycinate (structure drawing): redrawn, its display structure changed ({mg})",
             f"magnesium-glycinate (structure parts): dropped, its display structure changed ({mg}), its drawing changed",
             "glucose-vs-glycogen (compare drawing): remade, glycogen's SMILES changed",
             "maltodextrin-vs-starch (compare drawing): remade, maltodextrin's SMILES changed, maltodextrin's drawing changed"}
    assert set(v.made) == want and len(v.made) == len(want) == 25


def test_the_pairs_the_pass_touches_and_nothing_booked():
    """Two /vs pairs hold one of the eight: glucose vs glycogen and maltodextrin vs starch (both now shipped with no
    pair drawing, as one side has none); no door names a drawing of theirs and no week books one."""
    cd = json.loads((SNAP / "compare_drawings.json").read_text())["pairs"]
    eight = set(UNITS) | {"magnesium-glycinate"}
    touched = {k for k, p in cd.items() if {p["a"], p["b"]} & eight}
    assert touched == {"glucose-vs-glycogen", "maltodextrin-vs-starch"}
    for k in touched:
        assert cd[k]["mode"] == "shipped" and cd[k]["reason"] == "one of the two has no drawing"
    featured = json.loads((SNAP / "featured.json").read_text())
    assert not eight & set(re.findall(r'"slug": "([a-z0-9-]+)"', json.dumps(featured)))
