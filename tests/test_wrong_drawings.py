"""The wrong-drawings pass (2026-11-26; Garrett's word on decisions 2 and 5 of the extended-solids review). Brief:
../EXTENDED-SOLIDS-2-PROMPT.md. Three changes, each a deliberate remake the drawing guard LISTS:

A. calcium oxide, magnesium oxide, silicon carbide and tungsten carbide get the "No single structure" panel
   (seeds/structure_none.yaml), as titanium dioxide, silicon dioxide and zinc oxide have;
B. simeticone is drawn as a repeat unit in place of PubChem's drawing (seeds/repeat_units.yaml `replaces`), as
   carboxymethyl cellulose is;
C. five metal compounds are drawn with their metal's bonds (seeds/structure_display.yaml `metal_bonds`), the record
   otherwise PubChem's. The four cobalamins were stopped and reported, not drawn (the HISTORY record says why).
"""
from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path

import pytest
import yaml
from rdkit import Chem

from moleculefinder_etl.config import SEEDS_DIR
from moleculefinder_etl.transform import assemble, claims, drawings, structures
from moleculefinder_etl.transform import drawing_guard as DG

SNAP = Path(__file__).resolve().parents[1] / "data" / "snapshots"
CLAIM_WORDS = re.compile(r"\b(only|first|most|leading|largest|world's|never|always)\b", re.IGNORECASE)
LATTICES = {  # slug: (PubChem's formula, PubChem's SMILES, CID, the conventional formula shown, or None)
    "calcium-oxide": ("CaO", "O=[Ca]", 14778, None),
    "magnesium-oxide": ("MgO", "O=[Mg]", 14792, None),
    "silicon-carbide": ("CSi", "[C-]#[Si+]", 9863, "SiC"),
    "tungsten-carbide": ("CW", "[C-]#[W+]", 2724274, "WC"),
}
METALS = {  # slug: (metal, PubChem CID of the record)
    "cisplatin": ("Pt", 5460033), "sodium-ferrocyanide": ("Fe", 26129), "chromium-iii-picolinate": ("Cr", 151932),
    "thiomersal": ("Hg", 5908), "chlorophyll-a": ("Mg", 12085802),
}
COBALAMINS = ("cyanocobalamin", "vitamin-b12", "hydroxocobalamin", "methylcobalamin")


def _rec(slug):
    return json.loads((SNAP / "molecules" / f"{slug}.json").read_text())


def _seed(name):
    return yaml.safe_load((SEEDS_DIR / name).read_text())


# ── A. four more panels ──────────────────────────────────────────────────────────────────────────────────────────
def test_the_four_lattices_are_drawn_with_nothing_and_keep_their_formula_unit():
    for slug, (formula, smiles, cid, shown) in LATTICES.items():
        r = _rec(slug)
        assert r["cid"] == cid and r["molecular_formula"] == formula and r["isomeric_smiles"] == smiles, slug
        assert r["structure_svg"] is None and r["structure_svg_key"] is None and r["has_3d"] is False, slug
        assert not r.get("structure_parts") and not r.get("structure_repeat_unit"), slug
        assert all(v is None for k, v in r["descriptors"].items() if k != "confidence"), slug
        assert r["structure_none"] == assemble.structure_none_for(slug, formula)
        assert r["structure_none"].get("formula") == shown, slug


def test_the_four_lines_are_the_briefs_and_keep_the_house_rules():
    want = {
        "calcium-oxide": "a crystal lattice of calcium and oxygen ions with no single molecule, each calcium among six "
                         "oxygens; its formula, CaO, gives the ratio, one calcium to each oxygen.",
        "magnesium-oxide": "a crystal lattice of magnesium and oxygen ions with no single molecule, each magnesium "
                           "among six oxygens; its formula, MgO, gives the ratio, one magnesium to each oxygen.",
        "silicon-carbide": "a network of silicon and carbon with no single molecule, each silicon bonded to four "
                           "carbons and each carbon to four silicons; its formula, SiC, gives the ratio, one silicon "
                           "to each carbon.",
        "tungsten-carbide": "a crystal lattice of tungsten and carbon with no single molecule, each carbon among six "
                            "tungstens; its formula, WC, gives the ratio, one tungsten to each carbon.",
    }
    for slug, line in want.items():
        assert _rec(slug)["structure_none"]["line"] == line
        assert not CLAIM_WORDS.search(line) and "—" not in line and "–" not in line


def test_silicon_carbide_loses_its_3d_model_of_the_false_molecule():
    assert _rec("silicon-carbide")["has_3d"] is False


def test_also_called_keeps_the_everyday_names_and_never_the_false_molecules():
    # The display lines as they stand: everyday, mineral and compositional names only. Tungsten carbide's two
    # "methanidylidyne" names (the WC molecule that does not exist) are in drop_names; its line is empty anyway.
    assert _rec("calcium-oxide")["display_synonyms"] == ["caustic lime", "quicklime", "calx", "calcium monoxide"]
    assert _rec("magnesium-oxide")["display_synonyms"] == ["magnesia", "MgO", "Magmitt", "Animag"]
    assert _rec("silicon-carbide")["display_synonyms"] == ["carbon silicide", "Carborundum", "silicon monocarbide",
                                                          "SiC"]
    wc = _rec("tungsten-carbide")
    assert wc["display_synonyms"] == [] and "methanidylidynetungstenylium" in wc["synonyms"]
    assert assemble.structure_none_dropped_names("tungsten-carbide") == {
        "methanidylidynetungsten(1+)", "methanidylidynetungstenylium"}


def test_none_of_the_four_or_simeticone_is_in_a_pair_a_door_or_a_week():
    slugs = set(LATTICES) | {"simeticone"}
    comparisons = json.loads((SNAP / "comparisons.json").read_text())
    pairs = json.loads((SNAP / "compare_drawings.json").read_text())["pairs"]
    for slug in slugs:
        assert not any(slug in (c.get("a"), c.get("b")) for c in comparisons.values()), slug
        assert not any(slug in key.split("-vs-") for key in pairs), slug
    doors = json.dumps(json.loads((SNAP / "doors.json").read_text()))
    assert not any(f'"{s}"' in doors for s in slugs)
    assert not any(w.get("slug") in slugs for w in _seed("featured.yaml")["weeks"])


# ── B. simeticone ────────────────────────────────────────────────────────────────────────────────────────────────
def test_simeticone_is_drawn_as_its_repeat_unit_in_place_of_pubchems_drawing():
    r = _rec("simeticone")
    u = r["structure_repeat_unit"]
    assert r["structure_svg"] is None and r["cid"] == 6433516 and r["macromolecule"] is True
    assert u["label"] == "Two units of the chain" and u["linkage"] == "siloxane" and u["units"] == 2
    assert u["smiles"] == "*[Si](C)(C)O[Si](C)(C)O*" and "CID 6433516" in u["replaces"]
    assert u["line"] == ("Simeticone is polydimethylsiloxane, a silicone chain of alternating silicon and oxygen with "
                         "two methyl groups on each silicon, mixed with a small share of finely divided silica.")
    # everything PubChem derived from its record's structure goes, as for carboxymethyl cellulose
    for k in ("molecular_formula", "molecular_weight", "isomeric_smiles", "canonical_smiles", "inchi", "inchikey"):
        assert r[k] is None, k
    assert r["has_3d"] is False and all(v is None for k, v in r["descriptors"].items() if k != "confidence")


def test_the_unit_is_a_fragment_of_polydimethylsiloxane():
    spec = drawings.load_repeat_seed()["simeticone"]
    mol = Chem.MolFromSmiles(spec["smiles"])
    assert len(mol.GetSubstructMatches(Chem.MolFromSmarts(spec["linkage_smarts"]))) == spec["linkages"] == 1
    # the ends closed: join the two chain ends (each * to the atom across from it), giving a ring
    rw = Chem.RWMol(mol)
    stars = [a.GetIdx() for a in rw.GetAtoms() if a.GetAtomicNum() == 0]
    ends = [rw.GetAtomWithIdx(s).GetNeighbors()[0].GetIdx() for s in stars]
    rw.AddBond(ends[0], ends[1], Chem.BondType.SINGLE)
    for s in sorted(stars, reverse=True):
        rw.RemoveAtom(s)
    ring = rw.GetMol()
    Chem.SanitizeMol(ring)
    for a in ring.GetAtoms():
        nb = sorted(n.GetSymbol() for n in a.GetNeighbors())
        if a.GetSymbol() == "Si":   # every silicon carries two methyls and two oxygens
            assert nb == ["C", "C", "O", "O"] and all(n.GetTotalNumHs() == 3 for n in a.GetNeighbors()
                                                      if n.GetSymbol() == "C")
        elif a.GetSymbol() == "O":  # silicon and oxygen alternate
            assert nb == ["Si", "Si"]
    assert Chem.MolToSmiles(ring) == Chem.MolToSmiles(Chem.MolFromSmiles("C[Si]1(C)O[Si](C)(C)O1"))
    # and it is the repeat of a longer polydimethylsiloxane chain
    chain = Chem.MolFromSmiles("C[Si](C)(C)O[Si](C)(C)O[Si](C)(C)O[Si](C)(C)C")
    assert chain.HasSubstructMatch(Chem.MolFromSmarts("[Si](C)(C)O[Si](C)(C)O"))


def test_the_silica_share_is_not_given_as_a_figure():
    # No source the licence rule allows states it (the USP monograph's 4.0 to 7.0 percent is not one).
    assert not re.search(r"\d", drawings.load_repeat_seed()["simeticone"]["line"])


# ── C. metal bonds ───────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("slug", sorted(METALS))
def test_each_metal_compound_is_drawn_from_its_checked_display_structure(slug):
    metal, cid = METALS[slug]
    r = _rec(slug)
    d = r["structure_display"]
    e = _seed("structure_display.yaml")["metal_bonds"][slug]
    assert d["kind"] == "metal_bonds" and d["metal"] == metal and d["smiles"] == e["smiles"]
    assert r["cid"] == cid and r["has_3d"] is False and d["has_3d"] is False
    assert r["structure_svg_key"] == structures.svg_key(d["smiles"]) and structures.drawn_smiles(r) == d["smiles"]
    assert structures.svg_for(d["smiles"]) == r["structure_svg"]     # drawn from it, here and now
    # the build-time proof, run again: the record's own pieces with the metal's bonds drawn in
    assert structures.metal_bonds_problems(e["smiles"], r["isomeric_smiles"], metal, e["bonded"],
                                           e.get("charges") or []) == []
    # nothing else on the record is the display structure's
    assert r["isomeric_smiles"] != d["smiles"] and "." in r["isomeric_smiles"]
    assert not CLAIM_WORDS.search(d["line"]) and "PubChem" in d["line"]


def test_the_metal_lines_are_in_the_claim_corpus():
    keys = {k for kind, k, _ in claims.corpus() if kind == "part"}
    for slug in METALS:
        assert f"display.{slug}.line" in keys


def test_a_cyanide_bonded_by_its_nitrogen_fails():
    rec = _rec("sodium-ferrocyanide")["isomeric_smiles"]
    wrong = "[C-]#N->[Fe+2](<-N#[C-])(<-N#[C-])(<-N#[C-])(<-N#[C-])<-N#[C-].[Na+].[Na+].[Na+].[Na+]"
    e = _seed("structure_display.yaml")["metal_bonds"]["sodium-ferrocyanide"]
    assert structures.metal_bonds_problems(wrong, rec, "Fe", e["bonded"], []) != []


def test_a_missing_bond_or_a_wrong_atom_fails():
    e = _seed("structure_display.yaml")["metal_bonds"]
    cis = _rec("cisplatin")["isomeric_smiles"]
    assert structures.metal_bonds_problems("[NH3]->[Pt]([Cl])[Cl].N", cis, "Pt", e["cisplatin"]["bonded"], [])
    # a chloride moved to the nitrogen: the formula holds, the pieces do not
    assert structures.metal_bonds_problems("Cl[NH2]->[Pt](<-[NH3])Cl.[H]", cis, "Pt", e["cisplatin"]["bonded"], [])
    # a charge change the entry does not list
    th = _rec("thiomersal")["isomeric_smiles"]
    assert structures.metal_bonds_problems(e["thiomersal"]["smiles"], th, "Hg", e["thiomersal"]["bonded"], [])
    # a stereocentre turned the other way
    chl = _rec("chlorophyll-a")["isomeric_smiles"]
    flipped = e["chlorophyll-a"]["smiles"].replace("[C@@H]", "[C@H]", 1)
    assert flipped != e["chlorophyll-a"]["smiles"]
    assert structures.metal_bonds_problems(flipped, chl, "Mg", e["chlorophyll-a"]["bonded"],
                                           e["chlorophyll-a"]["charges"])


def test_a_bad_entry_stops_the_build(monkeypatch):
    seed = assemble._metal_bonds_seed()
    monkeypatch.setitem(seed, "cisplatin", {**seed["cisplatin"], "charges": [{"element": "Pt", "record": 2,
                                                                               "drawn": 0}]})
    with pytest.raises(SystemExit, match="metal_bonds: cisplatin"):
        assemble.structure_display_for("cisplatin", _rec("cisplatin")["isomeric_smiles"])


def _label_centres(svg: str) -> dict[int, tuple[float, float]]:
    """Each labelled atom's position in a drawing: the centre of its label glyphs' points."""
    pts: dict[int, list[tuple[float, float]]] = {}
    for m in re.finditer(r"<path class='atom-(\d+)' d='([^']*)'", svg):
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", m.group(2))]
        pts.setdefault(int(m.group(1)), []).extend(zip(nums[0::2], nums[1::2]))
    return {i: (sum(x for x, _ in p) / len(p), sum(y for _, y in p) / len(p)) for i, p in pts.items()}


def test_cisplatin_is_drawn_cis_in_the_finished_picture():
    """The two chlorides on adjacent corners and the two ammonia on adjacent corners, read from the shipped SVG's own
    coordinates (opposite corners would be transplatin, a different compound)."""
    r = _rec("cisplatin")
    mol = Chem.MolFromSmiles(r["structure_display"]["smiles"])
    at = _label_centres(r["structure_svg"])
    pt = next(a.GetIdx() for a in mol.GetAtoms() if a.GetSymbol() == "Pt")
    cl = [a.GetIdx() for a in mol.GetAtoms() if a.GetSymbol() == "Cl"]
    n = [a.GetIdx() for a in mol.GetAtoms() if a.GetSymbol() == "N"]

    def angle(i, j):
        (px, py), (ax, ay), (bx, by) = at[pt], at[i], at[j]
        a1, a2 = math.atan2(ay - py, ax - px), math.atan2(by - py, bx - px)
        d = abs(math.degrees(a1 - a2)) % 360
        return min(d, 360 - d)

    assert 60 < angle(*cl) < 120 and 60 < angle(*n) < 120          # adjacent corners: about 90 degrees
    assert all(angle(c, x) > 60 for c in cl for x in n)
    # transplatin, drawn the same way, fails the same reading
    trans = "[NH3]->[Pt](<-[NH3])([Cl])[Cl] |(-1.061,-1.061,;0,0,;1.061,1.061,;-1.061,1.061,;1.061,-1.061,)|"
    tsvg = structures.svg_for(trans)
    at = _label_centres(tsvg)
    assert angle(*cl) > 150


def test_the_cobalamins_were_not_drawn_in_this_pass():
    seed = _seed("structure_display.yaml")["metal_bonds"]
    for slug in COBALAMINS:
        assert slug not in seed and "structure_display" not in _rec(slug), slug


# ── the guard lists exactly this pass's changes ─────────────────────────────────────────────────────────────────
def test_the_guard_lists_exactly_the_passs_changes(tmp_path):
    """Against a shipped snapshot shaped as main was before this pass (each of the ten with a drawing, the five metal
    compounds with no display structure, simeticone with its PubChem SMILES and no repeat unit), the guard lists the
    four removals, simeticone's remake, the five redraws and their three part sets, and stops nothing."""
    shipped = tmp_path / "snapshots"
    shutil.copytree(SNAP / "molecules", shipped / "molecules")
    shutil.copy(SNAP / "compare_drawings.json", shipped / "compare_drawings.json")
    for slug in [*LATTICES, *METALS, "simeticone"]:
        p = shipped / "molecules" / f"{slug}.json"
        r = json.loads(p.read_text())
        r["structure_svg"], r["structure_svg_key"] = "<svg/>", "shipped-key"
        r.pop("structure_display", None)
        if r.get("structure_parts"):
            r["structure_parts"] = {**r["structure_parts"], "key": "shipped-parts-key"}
        if slug == "simeticone":
            r["isomeric_smiles"] = "CO[Si](C)(C)O[Si](C)(C)C.O=[Si]=O"
            r["structure_repeat_unit"] = None
        p.write_text(json.dumps(r))
    by_cid, pairs = DG.shipped(SNAP)
    v = DG.check([by_cid[c] for c in sorted(by_cid)], pairs, shipped, allow_seeds=False)
    assert v.stops == []
    removed = "removed, it no longer has a drawing"

    def redrawn(slug, metal):
        return (f"{slug} (structure drawing): redrawn, its display structure changed "
                f"(structure_display.yaml metal_bonds: drawn with the {metal} bonds)")

    def parts(slug, metal):
        return (f"{slug} (structure parts): remade, its display structure changed "
                f"(structure_display.yaml metal_bonds: drawn with the {metal} bonds), its drawing changed")

    want = {f"{s} (structure drawing): {removed}" for s in LATTICES}
    want |= {("simeticone (structure drawing): removed, replaced by its repeat unit (repeat_units.yaml `replaces`), "
              "a deliberate remake"), "simeticone (repeat unit): new, added in repeat_units.yaml"}
    want |= {redrawn(s, m) for s, (m, _) in METALS.items()}
    want |= {parts(s, METALS[s][0]) for s in ("thiomersal", "chlorophyll-a", "chromium-iii-picolinate")}
    assert set(v.made) == want and len(v.made) == len(want) == 14
