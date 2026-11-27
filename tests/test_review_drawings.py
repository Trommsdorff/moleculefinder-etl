"""The drawing-truth review (trust review 3, moleculefinder_etl/review/drawings.py; brief
../TRUST-2-DRAWING-TRUTH-PROMPT.md, 2026-11-27).

For each check, a small fixture that must be found and one that must not. Then the allowlists (every entry names an
existing record and carries a reason; each list is one ruling with its date), the survey copied verbatim from the
extended-solids generator, the date seed (the same sample all day, a different one the next), the queue (a class on
two consecutive runs is queued once), the report's first line, the exit codes, and that the review reads only: no
network offline, nothing written outside its report folder.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import socket
from pathlib import Path

import pytest
import yaml
from rdkit import Chem
from rdkit.Chem.rdMolDescriptors import CalcMolFormula

from moleculefinder_etl import cli
from moleculefinder_etl.review import drawings as D
from moleculefinder_etl.transform import structures

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "data" / "snapshots"
RULINGS = yaml.safe_load(D.RULINGS.read_text())
NO_SEEDS = {"none": {}, "display": {}, "metal": {}, "units": {}, "parts": {"defaults": [], "molecules": {}}}


def _survey_script():
    spec = importlib.util.spec_from_file_location("esr", ROOT / "scripts" / "extended_solids_review.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def rec(slug: str, smiles: str, *, drawn: str | None = None, family: str = "other", **kw) -> dict:
    """A record as the snapshot carries it, its drawing drawn here from ``drawn`` (default: its own SMILES)."""
    d = drawn or smiles
    m = Chem.MolFromSmiles(smiles)
    r = {"slug": slug, "cid": abs(hash(slug)) % 10**6, "title": slug, "isomeric_smiles": smiles,
         "molecular_formula": CalcMolFormula(m), "descriptors": {"formal_charge": Chem.GetFormalCharge(m)},
         "structure_svg": structures.svg_for(d), "structure_svg_key": structures.svg_key(d),
         "scope_family": family, "summary": None, "has_3d": True, "structure_parts": None,
         "structure_repeat_unit": None}
    r.update(kw)
    return r


def review(recs: dict, rulings: dict | None = None, seeds: dict | None = None) -> D.Review:
    rv = D.Review(RULINGS if rulings is None else rulings)
    D.check_drawings(rv, recs, seeds or NO_SEEDS, {})
    return rv


def shapes(rv: D.Review, fact: str) -> dict[str, str]:
    return {f["slug"]: f["shape"] for f in rv.findings if f["fact"] == fact}


# ── 1. atoms ─────────────────────────────────────────────────────────────────────────────────────
def test_atoms_finds_a_drawing_of_another_structure_and_a_wrong_formula():
    good = rec("ethanol", "CCO")
    other = rec("methanol", "CO", drawn="CCO")                       # the SVG is ethanol's
    other["structure_svg_key"] = structures.svg_key("CO")             # a key that lies
    wrong = rec("propanol", "CCCO", molecular_formula="C3H9O")
    charge = rec("acetate", "CC(=O)[O-]", descriptors={"formal_charge": 0})
    found = shapes(review({r["slug"]: r for r in (good, other, wrong, charge)}), "atoms")
    assert "ethanol" not in found
    assert found["methanol"] == "the SVG does not draw the structure"
    assert found["propanol"] == "the drawn structure is not the record's formula and charge"
    assert found["acetate"] == "the drawn charge is not the record's"


def test_atoms_reads_pubchem_and_rdkit_charges():
    assert D.formula_counts("C66H100NO49-") == ({"C": 66, "H": 100, "N": 1, "O": 49}, -1)
    assert D.formula_counts("O4S-2") == ({"O": 4, "S": 1}, -2)
    assert D.formula_counts("C7H16NO2+")[1] == 1
    assert D.formula_counts("O2Si") == D.formula_counts("SiO2")


def test_a_repeat_unit_is_held_to_its_own_drawing_not_the_formula():
    u = rec("polyfoo", "CC")
    u.update(structure_svg=None, structure_svg_key=None, molecular_formula=None,
             structure_repeat_unit={"smiles": "*CC*", "svg": structures.svg_for("*CC*")})
    bad = rec("polybar", "CC")
    bad.update(structure_svg=None, structure_svg_key=None,
               structure_repeat_unit={"smiles": "*CCC*", "svg": structures.svg_for("*CC*")})
    rv = D.Review(RULINGS)
    D.check_drawings(rv, {"polyfoo": u, "polybar": bad}, NO_SEEDS, {})
    assert shapes(rv, "atoms") == {"polybar": "the SVG does not draw the unit"}


# ── 2. metal floating ────────────────────────────────────────────────────────────────────────────
def test_metal_floating_finds_a_metal_beside_a_ligand_and_spares_an_allowlisted_salt():
    loose = rec("platinum-thing", "N.N.Cl[Pt]Cl.[Cu+2]")             # a Cu2+ with no bond, NH3 beside it
    salt = rec("sodium-chloride", "[Na+].[Cl-]")                       # ruling 3
    na = rec("sodium-foo", "CC(=O)[O-].[Na+]")                          # no ruling: found, s-block shape
    plain = rec("benzene", "c1ccccc1")
    rv = review({r["slug"]: r for r in (loose, salt, na, plain)})
    found = shapes(rv, "metal floating")
    assert found == {"platinum-thing": "a metal or metalloid beside atoms it could bond",
                     "sodium-foo": "an s-block ion beside an anion"}
    assert ("metal floating", "sodium-chloride", "an s-block ion beside an anion") in rv.covered["salts-as-ions"]


def test_a_metal_bonds_entry_is_not_metal_floating():
    r = rec("cisplatin-like", "N.N.Cl[Pt]Cl.[Fe+2]")
    seeds = {**NO_SEEDS, "metal": {"cisplatin-like": {}}}
    assert shapes(review({"cisplatin-like": r}, seeds=seeds), "metal floating") == {}


# ── 3. lattice as molecule ───────────────────────────────────────────────────────────────────────
def test_lattice_finds_a_metal_oxide_drawn_as_a_molecule_and_spares_water():
    quick = rec("quicklime", "O=[Ca]", family="inorganic")
    co2 = rec("carbon-dioxide", "O=C=O", family="inorganic")            # discrete-inorganic allowlist
    methane = rec("methane", "C", family="alkane")
    rv = review({r["slug"]: r for r in (quick, co2, methane)})
    assert shapes(rv, "lattice as molecule") == {"quicklime": "a metal or metalloid drawn with covalent bonds"}
    assert [c[1] for c in rv.covered["discrete-inorganic"]] == ["carbon-dioxide"]


def test_a_charged_polyatomic_ion_is_not_a_lattice():
    r = rec("permanganate-thing", "[O-][Mn](=O)(=O)=O.[K+]", family="inorganic")
    assert shapes(review({"permanganate-thing": r}), "lattice as molecule") == {}


# ── 4. fragments ─────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("smiles,kind", [
    ("[Na+].[Cl-]", "a salt"),
    ("CC(=O)[O-].CC(=O)[O-].[Ca+2]", "a salt"),
    ("CN1C2=C(C(=O)N(C1=O)C)NC(=N2)Cl.CN(C)CCOC(C1=CC=CC=C1)C2=CC=CC=C2", "a salt"),   # dimenhydrinate
    ("C1=CC=C2C(=C1)C(=O)O[Bi]O2.O", "a hydrate or solvate"),
    ("[C@@H]([C@H](C(=O)[O-])O)(C(=O)[O-])O.O.O.[Na+].[K+]", "a hydrate or solvate"),
    ("C=CC=C.C=CC#N.C=CC1=CC=CC=C1", "a mixture or polymer"),
    ("C=CN1CCCC1=O.II", "unexplained"),
])
def test_fragments_are_classified(smiles, kind):
    m = Chem.MolFromSmiles(smiles)
    assert D.fragment_kind(Chem.GetMolFrags(m, asMols=True, sanitizeFrags=False), {}) == kind


def test_fragments_finds_a_mixture_and_spares_a_salt_and_an_allowlisted_record():
    mix = rec("abs-plastic", "C=CC=C.C=CC#N.C=CC1=CC=CC=C1")
    salt = rec("sodium-acetate", "CC(=O)[O-].[Na+]")
    kept = rec("povidone-iodine", "C=CN1CCCC1=O.II")                     # ruling: kept as drawn
    rv = review({r["slug"]: r for r in (mix, salt, kept)})
    assert shapes(rv, "fragments") == {"abs-plastic": "a mixture or polymer"}
    assert [c[1] for c in rv.covered["kept-as-drawn"]] == ["povidone-iodine"]


def test_a_polymer_record_drawn_as_one_molecule_is_found():
    pmma = rec("pmma", "C[C](C)C(=O)OC", family="polymer")
    glyc = rec("glycogen-like", "OCC1OC(O)C(O)C(O)C1O", family="sugar", summary="polysaccharide")
    sugar = rec("glucose-like", "OCC1OC(O)C(O)C(O)C1O", family="sugar", summary="a sugar")
    fat = rec("ala", "CCC=CCC=CCC(=O)O", summary="omega-3 polyunsaturated fatty acid")
    found = shapes(review({r["slug"]: r for r in (pmma, glyc, sugar, fat)}), "fragments")
    assert found == {"pmma": "a polymer record drawn as one molecule",
                     "glycogen-like": "a polymer record drawn as one molecule"}


# ── 5. classification ────────────────────────────────────────────────────────────────────────────
def test_an_in_scope_record_missing_from_the_survey_is_found():
    rulings = {**RULINGS, "survey": {"sodium-chloride": {"group": "a", "kind": "ions", "why": "x"}}}
    recs = {"sodium-chloride": rec("sodium-chloride", "[Na+].[Cl-]", family="inorganic"),
            "lithium-oxide": rec("lithium-oxide", "[Li+].[Li+].[O-2]", family="inorganic"),
            "ethanol": rec("ethanol", "CCO", family="alcohol")}
    rv = D.Review(rulings)
    D.check_classification(rv, recs)
    assert shapes(rv, "classification") == {"lithium-oxide": "in the scope rule, not classified"}


def test_the_survey_is_the_generators_and_the_scope_rule_is_its():
    m = _survey_script()
    assert D.METALS == m.METALS and D.EXTRA == m.EXTRA
    assert {s: (v["group"], v.get("kind")) for s, v in RULINGS["survey"].items()} == \
        {s: (v["g"], v["kind"]) for s, v in m.SURVEY.items()}
    assert {s: v["why"] for s, v in RULINGS["survey"].items()} == {s: v["why"] for s, v in m.SURVEY.items()}
    recs = D.load_records(SNAP)
    assert {s for s, r in recs.items() if D.in_scope(r)} == {s for s, r in recs.items() if m.in_scope(r)}


# ── 6. seeds ─────────────────────────────────────────────────────────────────────────────────────
def test_the_seeds_hold_today_and_a_missing_or_stale_record_is_found():
    recs = D.load_records(SNAP)
    seeds = D._seeds()
    rv = D.Review(RULINGS)
    D.check_seeds(rv, recs, seeds)
    assert rv.findings == []
    gone = dict(recs)
    del gone["cisplatin"]
    stale = json.loads(json.dumps(recs["fructose"]))
    stale["structure_display"]["smiles"] = "OCC1OC(O)(CO)C(O)C1O"
    gone["fructose"] = stale
    rv = D.Review(RULINGS)
    D.check_seeds(rv, gone, seeds)
    assert shapes(rv, "seed") == {"cisplatin": "names a record that does not exist",
                                  "fructose": "the snapshot does not carry what the seed makes"}


def test_a_seed_that_fails_its_build_check_is_found(monkeypatch):
    recs = D.load_records(SNAP)
    seeds = D._seeds()
    from moleculefinder_etl.transform import assemble
    bad = {**assemble._none_seed(), "zinc-oxide": {"line": "a lattice — of zinc", "basis": "x"}}
    monkeypatch.setattr(assemble, "_none_seed", lambda: bad)
    rv = D.Review(RULINGS)
    D.check_seeds(rv, recs, {**seeds, "none": bad})
    assert shapes(rv, "seed")["zinc-oxide"] == "fails its build-time check"


def test_a_repeat_unit_seed_whose_linkage_stopped_matching_is_found():
    r = D.load_records(SNAP)["starch"]
    spec = {**D._seeds()["units"]["starch"], "linkages": 2}
    assert any("linkage pattern matches 1 times, expected 2" in p for p in D.repeat_unit_problems("starch", spec, r))
    assert D.repeat_unit_problems("starch", D._seeds()["units"]["starch"], r) == []


# ── 7. stereo ────────────────────────────────────────────────────────────────────────────────────
def test_stereo_finds_a_drawing_without_the_records_centres_and_one_with_centres_it_lacks():
    flat = rec("flat", "C[C@@H](O)CC", structure_display={"smiles": "CC(O)CC"}, drawn="CC(O)CC")
    extra = rec("extra", "CC(O)CC", structure_display={"smiles": "C[C@@H](O)CC"}, drawn="C[C@@H](O)CC")
    fine = rec("fine", "C[C@@H](O)CC")
    rv = review({r["slug"]: r for r in (flat, extra, fine)})
    found = {(f["slug"], f["shape"]) for f in rv.findings if f["fact"] == "stereo"}
    assert ("flat", "the record specifies centres the drawing shows none of") in found
    assert ("extra", "a centre drawn that the record does not specify") in found
    assert not {s for s, _ in found} & {"fine"}


def test_a_borrowed_stereo_is_allowed_only_with_stereo_from():
    extra = rec("b12-like", "CC(O)CC", structure_display={"smiles": "C[C@@H](O)CC"}, drawn="C[C@@H](O)CC")
    seeds = {**NO_SEEDS, "metal": {"b12-like": {"stereo_from": "ref"}}}
    assert shapes(review({"b12-like": extra}, seeds=seeds), "stereo") == {}


# ── 8. 3D against 2D ─────────────────────────────────────────────────────────────────────────────
def test_3d_on_a_panel_page_or_with_another_models_connectivity_is_found():
    panel = rec("lattice", "O=[Ti]=O", structure_none={"line": "x"})
    ring = rec("sugar", "OCC(O)C(O)C(O)C(=O)CO", structure_display={"smiles": "OCC1OC(O)(CO)C(O)C1O",
                                                                     "model_cid": 439709, "has_3d": True},
               drawn="OCC1OC(O)(CO)C(O)C1O")
    wrong = rec("sugar2", "OCC(O)C(O)C(O)C(=O)CO", structure_display={"smiles": "OCC1OC(O)C(O)C(O)C1O",
                                                                      "model_cid": 439709, "has_3d": True},
                drawn="OCC1OC(O)C(O)C(O)C1O")
    unpinned = rec("sugar3", "OCC(O)C(O)C(O)C(=O)CO", structure_display={"smiles": "OCC1OC(O)(CO)C(O)C1O",
                                                                        "model_cid": 1, "has_3d": True},
                   drawn="OCC1OC(O)(CO)C(O)C1O")
    plain = rec("ethanol", "CCO")
    rv = D.Review(RULINGS)
    D.check_3d(rv, {r["slug"]: r for r in (panel, ring, wrong, unpinned, plain)}, NO_SEEDS)
    assert shapes(rv, "3D") == {"lattice": "a 3D model on a no-structure panel page",
                                "sugar2": "the model compound's connectivity is not the drawing's",
                                "sugar3": "the model compound is not pinned"}


# ── 9. live equals built ─────────────────────────────────────────────────────────────────────────
def _page(r: dict, *, svg: str | None = None, three_d: bool = True, line: str | None = None) -> str:
    body = f'<div class="v3__2d">{D.panel(svg if svg is not None else r["structure_svg"])}</div>' \
        if r.get("structure_svg") else '<p>No single structure</p>'
    control = '<div role="tablist" aria-label="Structure view"></div>' if three_d else ""
    return f"<html><body>{control}{body}<p>{line or ''}</p></body></html>"


def test_live_finds_a_served_drawing_that_is_not_the_snapshots_and_counts_a_page_it_could_not_read():
    recs = D.load_records(SNAP)
    seeds = D._seeds()
    rv = D.Review(RULINGS)
    caffeine = recs["caffeine"]
    other = recs["theobromine"]["structure_svg"]

    def fetch(url):
        slug = url.rsplit("/", 1)[1]
        assert url.startswith("https://moleculefinder.com/m/")
        if slug == "caffeine":
            return 200, _page(caffeine, svg=other)
        if slug == "cisplatin":
            raise OSError("connection reset")
        r = recs[slug]
        sl = D.seed_line(slug, seeds)
        disp = r.get("structure_display") or {}
        three = bool(r.get("structure_svg")) and r.get("has_3d") is not False and disp.get("has_3d") is not False
        page = _page(r, three_d=three, line=sl[1] if sl else None)
        u = r.get("structure_repeat_unit")
        if u:
            page += D.compose(D.panel(u["svg"]), u.get("layer"))
        return 200, page

    lv = D.check_live(rv, recs, seeds, dt.date(2026, 11, 27), fetch=fetch, pause=0)
    assert shapes(rv, "live") == {"caffeine": "the drawing served is not the snapshot's"}
    assert [x["slug"] for x in lv["not_read"]] == ["cisplatin"]
    assert len(lv["read"]) == len(lv["pinned"]) + len(lv["sampled"]) - 1
    assert rv.denoms[("live", "page (live)")][0] == len(lv["read"])


def test_live_finds_a_drawing_on_a_panel_page_a_wrong_3d_control_and_a_line_that_is_not_the_seeds():
    recs = D.load_records(SNAP)
    seeds = D._seeds()
    sio2 = recs["silicon-dioxide"]
    page = '<div class="v3__2d"><svg></svg></div><div aria-label="Structure view"></div><p>a lattice</p>'
    got = {s for s, _ in D.live_problems(sio2, page, seeds)}
    assert got == {"a drawing is served on a page with none", "the 3D control does not match the record",
                   "the notes line is not the seed's"}
    cis = recs["cisplatin"]
    ok = _page(cis, three_d=False, line=D.seed_line("cisplatin", seeds)[1])
    assert D.live_problems(cis, ok, seeds) == []


def test_every_seed_entry_is_pinned_with_a_reason():
    recs = D.load_records(SNAP)
    seeds = D._seeds()
    pinned = D.pinned_pages(D.Review(RULINGS), recs, seeds)
    for table in ("none", "display", "metal", "units"):
        assert set(seeds[table]) <= set(pinned)
    assert all(len(why) > 20 for why in pinned.values())
    assert set(RULINGS["pinned"]) <= set(recs)


def test_the_date_seed_gives_the_same_sample_all_day_and_another_the_next():
    recs = D.load_records(SNAP)
    day = dt.date(2026, 11, 27)
    a, b = D.sample_pages(recs, set(), day), D.sample_pages(recs, set(), day)
    c = D.sample_pages(recs, set(), day + dt.timedelta(days=1))
    assert a == b and a != c and len(a) == D.SAMPLE == len(set(a))
    assert not set(D.sample_pages(recs, {"caffeine"}, day)) & {"caffeine"}


# ── 10. part layers ──────────────────────────────────────────────────────────────────────────────
def test_parts_find_a_misplaced_mark_a_missing_atom_and_a_rule_that_moved():
    recs = D.load_records(SNAP)
    seeds = D._seeds()
    caf = json.loads(json.dumps(recs["caffeine"]))
    rv = D.Review(RULINGS)
    D.check_parts(rv, {"caffeine": caf}, seeds)
    assert rv.findings == []
    moved = json.loads(json.dumps(caf))
    p = moved["structure_parts"]["parts"][1]
    dots, _ = D.layer_marks(p["layer"])
    x, y = dots[0]
    p["layer"] = p["layer"].replace(f"M{x:.1f},{y:.1f}h0", f"M{x + 60:.1f},{y:.1f}h0", 1)
    beyond = json.loads(json.dumps(caf))
    beyond["structure_parts"]["parts"][2]["atoms"][0] = 99
    rule = json.loads(json.dumps(caf))
    rule["structure_parts"]["parts"][2]["atoms"] = [7]
    for r, shape in ((moved, "a mark sits away from its atom in the drawing"),
                     (beyond, "lights an atom or bond the drawing does not have"),
                     (rule, "its marks are not its atoms and bonds")):
        rv = D.Review(RULINGS)
        D.check_parts(rv, {"caffeine": r}, seeds)
        assert shape in {f["shape"] for f in rv.findings}, shape


def test_parts_find_a_curated_part_whose_expect_fails():
    recs = D.load_records(SNAP)
    seeds = json.loads(json.dumps(D._seeds()["parts"]))
    seeds["molecules"]["caffeine"]["parts"][1]["expect"] = {"matches": 4}
    rv = D.Review(RULINGS)
    D.check_parts(rv, {"caffeine": recs["caffeine"]}, {**D._seeds(), "parts": seeds})
    assert {f["shape"] for f in rv.findings} == {"a curated part no longer matches its expect"}


# The survey's group b records with no metal to float (an organic cation beside a halide, or methylene blue): the
# metal-floating check never finds them, so ruling A of 2026-11-27 did not name them.
GROUP_B_NOT_FOUND = {"choline-chloride", "dimenhydrinate", "hyoscine-butylbromide", "ipratropium-bromide",
                     "methylene-blue"}


# ── the allowlists ───────────────────────────────────────────────────────────────────────────────
def test_every_allowlist_entry_names_an_existing_record_and_carries_a_reason():
    recs = D.load_records(SNAP)
    allow = RULINGS["allow"]
    assert {k: len(v["records"]) for k, v in allow.items()} == \
        {"salts-as-ions": 72, "kept-as-drawn": 6, "discrete-inorganic": 16}
    for name, rule in allow.items():
        assert isinstance(rule["date"], dt.date) and rule["by"].strip() and rule["what"].strip(), name
        assert set(rule["covers"]) <= {"metal-floating", "lattice", "fragments"}, name
        later = {r["date"]: r for r in rule.get("later") or []}
        for r in later.values():
            assert isinstance(r["date"], dt.date) and r["by"].strip() and r["what"].strip(), name
        for slug, why in rule["records"].items():
            assert slug in recs, f"{name}: {slug} is not a record"
            if isinstance(why, dict):            # a later ruling's entry: its reason and that ruling's date
                assert why["date"] in later, f"{name}: {slug} names a date no ruling on the list has"
                why = why["reason"]
            assert isinstance(why, str) and len(why.strip()) > 10, f"{name}: {slug} has no reason"


def test_the_allowlists_hold_only_the_two_rulings():
    """Ruling 3 (the 41 salts drawn as ions), the four kept as drawn, and the survey's group c; nothing else."""
    s = RULINGS["survey"]
    salts = RULINGS["allow"]["salts-as-ions"]["records"]
    first = {k for k, v in salts.items() if isinstance(v, str)}
    later = {k for k, v in salts.items() if isinstance(v, dict)}
    assert first == {k for k, v in s.items() if v["group"] == "a" and v.get("kind") in ("ions", "anion")}
    # Ruling A of 2026-11-27: the survey's group b found floating on the first run, all but the one chelate (magnesium
    # glycinate, redrawn with its bonds) and the reason the brief gave, word for word.
    assert later == {k for k, v in s.items() if v["group"] == "b"} - GROUP_B_NOT_FOUND - {"magnesium-glycinate"}
    assert len(later) == 31
    assert {v["reason"] for v in salts.values() if isinstance(v, dict)} == \
        {"an ionic salt of a discrete organic ion, drawn as its ions"}
    kept = RULINGS["allow"]["kept-as-drawn"]["records"]
    assert set(kept) == {"stannous-fluoride", "sucralfate", "bismuth-subsalicylate", "povidone-iodine",
                         "butylated-hydroxyanisole", "ivermectin"}
    assert "shellac" not in kept          # held: its record's chain acid is not shellac's (see the yaml)
    assert set(RULINGS["allow"]["discrete-inorganic"]["records"]) == {k for k, v in s.items() if v["group"] == "c"}


def test_the_pinned_models_are_the_display_seeds():
    seeds = D._seeds()
    assert {e["model_cid"] for e in seeds["display"].values()} == set(RULINGS["models"])


# ── the report, the queue, the exit codes ────────────────────────────────────────────────────────
def _report(out: Path, day: dt.date, slugs: list[str]) -> dict:
    rv = D.Review(RULINGS)
    rv.denom("fragments", "structure drawing", 86, "drawings of more than one piece")
    for s in slugs:
        rv.find("fragments", "structure drawing", "a mixture or polymer", s, "x")
    meta = {"time": "t", "commit": "c", "refreshed": "2026-11-23"}
    return D.write_report(out, day, rv, {s: {} for s in range(929)}, None, meta)


def test_a_class_seen_on_two_consecutive_runs_reaches_the_queue_once(tmp_path):
    d = dt.date(2026, 11, 27)
    first = _report(tmp_path, d, ["shellac"])
    assert first["queued_today"] == [] and not (tmp_path / "QUEUE.md").exists()
    second = _report(tmp_path, d + dt.timedelta(days=1), ["shellac", "ivermectin"])
    assert second["queued_today"] == ["fragments / structure drawing / a mixture or polymer"]
    c = second["classes"]["fragments / structure drawing / a mixture or polymer"]
    assert c["change"] == "+1" and c["added"] == ["ivermectin"] and c["of"] == 86
    third = _report(tmp_path, d + dt.timedelta(days=2), ["shellac"])
    assert third["queued_today"] == []
    q = (tmp_path / "QUEUE.md").read_text()
    assert q.count("<!-- drawings: fragments / structure drawing / a mixture or polymer -->") == 1
    assert q.count("\n- [ ] ") == 1 and "Recommended:" in q


def test_the_reports_first_line_is_its_verdict(tmp_path):
    data = _report(tmp_path, dt.date(2026, 11, 27), ["shellac", "ivermectin"])
    md = (tmp_path / "drawings-2026-11-27.md").read_text()
    assert md.splitlines()[0] == data["verdict"]
    assert data["verdict"].startswith("VERDICT: 1 finding class found (2 records); 929 records read;")
    assert "2 of 86 drawings of more than one piece" in md
    assert "—" not in md and "–" not in md


def test_it_runs_offline_on_the_real_snapshot_reads_only_and_exits_0(tmp_path, monkeypatch):
    def tree():
        h = hashlib.sha256()
        for p in sorted(SNAP.rglob("*")):
            if p.is_file():
                h.update(p.name.encode() + p.read_bytes())
        return h.hexdigest()

    before = tree()

    def no_network(*a, **k):
        raise AssertionError("the offline review opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    assert D.main(["--no-live", "--out", str(tmp_path), "--date", "2026-11-27"]) == 0
    assert tree() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == \
        ["drawings-2026-11-27.json", "drawings-2026-11-27.md", "drawings-last-run.json"]
    hb = json.loads((tmp_path / "drawings-last-run.json").read_text())
    assert hb["state"] == "ran" and hb["exit"] == 0 and hb["verdict"].startswith("VERDICT:")


def test_it_exits_non_zero_only_when_it_could_not_run(tmp_path):
    assert D.main(["--no-live", "--out", str(tmp_path), "--snapshot", str(tmp_path / "nowhere")]) == 2
    hb = json.loads((tmp_path / "drawings-last-run.json").read_text())
    assert hb["state"] == "could not run" and hb["exit"] == 2


def test_mfetl_review_drawings_reaches_the_review(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(D, "main", lambda argv: seen.append(argv) or 0)
    assert cli.main(["review", "drawings", "--no-live", "--out", str(tmp_path)]) == 0
    assert seen == [["--no-live", "--out", str(tmp_path)]]
