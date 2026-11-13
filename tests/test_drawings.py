"""Phase 5A (2026-11-12): the drawing engine's proofs, over every shipped drawing.

transform/svg_geometry.py reads where each atom sits in a shipped drawing; transform/drawings.py
builds the parts, the aligned pairs and the repeat units on top. What these tests hold:

- every shipped drawing with a bond has proven atom positions, except four named ones;
- read from the SVG alone, the positions agree with RDKit's own wherever this machine redraws the
  shipped drawing byte for byte (the only place the truth can be had independently);
- with its highlight layer removed, every part drawing is the shipped drawing, path for path, and
  each dot sits where the shipped drawing's own lines put its atom;
- every aligned pair puts its common-core atoms on the same pixels in both drawings, read back
  from the two SVGs' bytes;
- no output carries black, and every colour is a band colour or the one amber;
- a run whose keys are current never reads, lays out or draws anything (the two-machine proof:
  the Linux weekly run carries every output untouched), and a palette change repaints;
- no shipped drawing has moved except with its own key (the manifest taken before phase 5A);
- starch's repeat unit is alpha-1,4 and cellulose's beta-1,4, and nothing else differs.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path

import pytest

pytest.importorskip("rdkit")

from rdkit import Chem

from moleculefinder_etl.transform import drawings as D
from moleculefinder_etl.transform import structures as S
from moleculefinder_etl.transform import svg_geometry as G

ROOT = Path(__file__).resolve().parent.parent
SNAP = ROOT / "data" / "snapshots"
MANIFEST = Path(__file__).parent / "fixtures" / "shipped-drawings-2026-11-12.json"

# Bonded drawings with no proven positions on this machine: not reproduced by this RDKit, and the
# reading's own proof does not close (anchors off by 7.5 to 9 px, or a glyph count that differs).
# They keep their shipped drawing and carry no highlight. A new one here fails this test on purpose.
UNPROVEN = {"aldosterone", "chitosan", "insulin", "inulin"}


def _records() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((SNAP / "molecules").glob("*.json"))]


@pytest.fixture(scope="module")
def records():
    return _records()


@pytest.fixture(scope="module")
def by_slug(records):
    return {r["slug"]: r for r in records}


@pytest.fixture(scope="module")
def pairs():
    return json.loads((SNAP / "compare_drawings.json").read_text())


@pytest.fixture(scope="module")
def sweep(records):
    """One pass over every shipped drawing: the proven reading (or the failure), and, where this
    machine draws the SMILES exactly as shipped, the reading from the SVG alone against RDKit."""
    out = {}
    for r in records:
        svg, smi = r.get("structure_svg"), r.get("isomeric_smiles")
        if not svg:
            continue
        mol = Chem.MolFromSmiles(smi)
        row = {"bonded": mol.GetNumBonds() > 0}
        try:
            row["reading"] = G.read_positions(svg, mol)
        except G.UnreadableDrawing:
            row["reading"] = None
        fresh, d = S.draw(Chem.Mol(mol))
        if fresh == svg and row["bonded"]:
            try:
                alone = G.read_positions(svg, mol, use_identical=False)
            except G.UnreadableDrawing:
                row["alone_failed"] = True
            else:
                iso = {a.GetIdx() for a in mol.GetAtoms() if a.GetDegree() == 0}
                row["error"] = max(math.dist(alone.pos[i], (d.GetDrawCoords(i).x, d.GetDrawCoords(i).y))
                                   for i in alone.pos if i not in iso)
        out[r["slug"]] = row
    return out


# ── Positions ────────────────────────────────────────────────────────────────────────────────
def test_every_bonded_drawing_has_proven_positions_but_four(sweep):
    unproven = {s for s, row in sweep.items() if row["bonded"] and row["reading"] is None}
    assert unproven == UNPROVEN
    assert len(sweep) == 896
    methods = {}
    for row in sweep.values():
        if row["reading"]:
            methods[row["reading"].method] = methods.get(row["reading"].method, 0) + 1
    # every proof within its tolerance
    assert all(row["reading"].difference <= G.REDRAW_TOLERANCE
               for row in sweep.values() if row["reading"])
    assert sum(methods.values()) >= 880


# Drawings this machine reproduces byte for byte (so proven that way) whose reading from the SVG
# alone does not prove itself: inorganic centres drawn with long or crossing bonds (cisplatin,
# permanganate, silica, the siloxane of simeticone, sucralfate's aluminium) and liraglutide's
# close-contact layout. Wherever the reading does prove itself, it is right (the test below).
READ_ALONE_FAILS = {"cisplatin", "liraglutide", "potassium-permanganate", "silicon-dioxide",
                    "simeticone", "sucralfate"}


def test_the_reading_alone_agrees_with_rdkit_wherever_the_truth_is_known(sweep):
    assert {s for s, row in sweep.items() if row.get("alone_failed")} == READ_ALONE_FAILS
    errors = {s: row["error"] for s, row in sweep.items() if "error" in row}
    assert len(errors) >= 390               # 397 on 2026-11-12 (rdkit 2026.09.1, this Mac)
    worst = max(errors.items(), key=lambda kv: kv[1])
    assert worst[1] <= 0.25, worst          # 0.15 px on 2026-11-12


def test_a_lone_ion_is_never_lit_and_a_saltless_reading_needs_no_bond():
    mol = Chem.MolFromSmiles("[Na+].[Cl-]")
    assert D.find_parts(mol, "x", D.load_parts_seed()) == []


# ── Parts ────────────────────────────────────────────────────────────────────────────────────
def _dots(layer_svg: str) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for x, y in re.findall(r"M(-?[\d.]+),(-?[\d.]+)h0", layer_svg)]


def test_every_part_layer_removed_gives_the_shipped_drawing_path_for_path(records):
    seen = 0
    for r in records:
        sp = r.get("structure_parts")
        if not sp:
            continue
        shipped = G.parse_svg(r["structure_svg"])
        for p in sp["parts"]:
            composed = D.compose(r["structure_svg"], p["layer"])
            assert D.strip(composed, p["layer"]) == r["structure_svg"]
            paths = G.parse_svg(composed)
            assert len(paths) == len(shipped) + 1 and paths[0].cls == "mf-part"
            assert [(x.cls, x.d, x.style) for x in paths[1:]] == [(x.cls, x.d, x.style) for x in shipped]
            seen += 1
    assert seen > 1500


def test_every_dot_sits_where_the_shipped_lines_put_its_atom(records):
    """Independent of the redraw: an unlabelled atom is the point its bond lines meet in the
    shipped SVG itself; every part dot on such an atom must be on it."""
    checked = 0
    for r in records:
        sp = r.get("structure_parts")
        if not sp or not sp["parts"]:
            continue
        mol = Chem.MolFromSmiles(r["isomeric_smiles"])
        exact = G.exact_points(r["structure_svg"], G.drawing_mol(mol, r["structure_svg"]))
        for p in sp["parts"]:
            for a, (x, y) in zip(p["atoms"], _dots(p["layer"])):
                if a in exact:
                    assert math.dist((x, y), exact[a]) <= 0.5, (r["slug"], p["id"], a)
                    checked += 1
    assert checked > 5000


def test_caffeine_has_its_three_curated_parts(by_slug):
    caf = by_slug["caffeine"]
    parts = {p["id"]: p for p in caf["structure_parts"]["parts"]}
    assert list(parts) == ["xanthine-core", "methyl-groups", "carbonyl-oxygens"]
    mol = Chem.MolFromSmiles(caf["isomeric_smiles"])
    sym = lambda ids: sorted(mol.GetAtomWithIdx(i).GetSymbol() for i in ids)
    assert sym(parts["xanthine-core"]["atoms"]) == ["C"] * 5 + ["N"] * 4
    assert sym(parts["methyl-groups"]["atoms"]) == ["C"] * 3
    assert len(parts["methyl-groups"]["bonds"]) == 3
    assert sym(parts["carbonyl-oxygens"]["atoms"]) == ["O", "O"]
    assert parts["xanthine-core"]["label"] == "The xanthine core"
    assert all(p["confidence"] == "from_source" and p["sentence"] and p["layer"] for p in parts.values())


def test_a_curated_part_that_no_longer_matches_stops_the_build():
    seed = copy.deepcopy(D.load_parts_seed())
    seed["molecules"]["caffeine"]["parts"][1]["expect"] = {"matches": 4}
    with pytest.raises(D.DrawingSeedError, match="methyl-groups"):
        D.find_parts(Chem.MolFromSmiles("CN1C=NC2=C1C(=O)N(C(=O)N2C)C"), "caffeine", seed)


def test_default_parts_are_capped_and_never_the_whole_molecule(records):
    for r in records:
        sp = r.get("structure_parts")
        if not sp or not sp["parts"]:
            continue
        assert len(sp["parts"]) <= 3
        mol = Chem.MolFromSmiles(r["isomeric_smiles"])
        heavy = {a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() > 1 and a.GetDegree() > 0}
        for p in sp["parts"]:
            assert not set(p["atoms"]) >= heavy or r["slug"] == "caffeine", (r["slug"], p["id"])


def test_an_unproven_drawing_is_recorded_so_no_machine_tries_again(by_slug):
    for slug in UNPROVEN:
        sp = by_slug[slug]["structure_parts"]
        assert sp["parts"] == [] and sp["unread"] and sp["key"]


# ── Pairs ────────────────────────────────────────────────────────────────────────────────────
def _glyphs(svg: str, n: int) -> dict[int, list[tuple[float, float]]]:
    out: dict[int, list[tuple[float, float]]] = {}
    for p in G.parse_svg(svg):
        if p.cls and p.cls.startswith("atom-") and "Q" in p.commands:
            i = int(p.cls.split()[0][5:])
            if i < n:
                out.setdefault(i, []).extend(pt for sp in p.subpaths for pt in sp)
    return out


def test_every_aligned_pair_puts_the_core_on_the_same_pixels(by_slug, pairs):
    """Read back from the two drawings' own bytes, with no estimate: a skeleton carbon is where its
    lines meet in each SVG; a heteroatom's label is the same glyphs at the same place."""
    n_pairs = checked = core_total = 0
    for slug, p in pairs["pairs"].items():
        if p["mode"] != "aligned":
            continue
        a, b = by_slug[p["a"]], by_slug[p["b"]]
        ma, mb = Chem.MolFromSmiles(a["isomeric_smiles"]), Chem.MolFromSmiles(b["isomeric_smiles"])
        ea = G.exact_points(a["structure_svg"], G.drawing_mol(ma, a["structure_svg"]))
        eb = G.exact_points(p["b_svg"], G.drawing_mol(mb, p["b_svg"]))
        ga, gb = _glyphs(a["structure_svg"], ma.GetNumAtoms()), _glyphs(p["b_svg"], mb.GetNumAtoms())
        for i, j in p["core_map"]:
            core_total += 1
            if i in ea and j in eb:
                assert math.dist(ea[i], eb[j]) <= D.ALIGN_TOLERANCE_PX, (slug, i, j)
                checked += 1
            elif i in ga and j in gb and len(ga[i]) == len(gb[j]):
                assert max(math.dist(u, v) for u, v in zip(ga[i], gb[j])) <= D.ALIGN_TOLERANCE_PX, (slug, i, j)
                checked += 1
        n_pairs += 1
    assert n_pairs == 75
    assert checked >= 0.9 * core_total, (checked, core_total)


def test_caffeine_and_theobromine_one_methyl_apart(by_slug, pairs):
    p = pairs["pairs"]["caffeine-vs-theobromine"]
    assert (p["mode"], p["highlight"], p["core"], p["caption"]) == ("aligned", True, 13, "One methyl group apart.")
    caf = Chem.MolFromSmiles(by_slug["caffeine"]["isomeric_smiles"])
    theo = Chem.MolFromSmiles(by_slug["theobromine"]["isomeric_smiles"])
    assert sorted(caf.GetAtomWithIdx(i).GetSymbol() for i in p["a_atoms"]) == ["C", "N"]
    assert [theo.GetAtomWithIdx(j).GetSymbol() for j in p["b_atoms"]] == ["N"]
    assert theo.GetAtomWithIdx(p["b_atoms"][0]).GetTotalNumHs() == 1
    core = dict(map(tuple, p["core_map"]))
    assert all(caf.GetAtomWithIdx(i).IsInRing() == theo.GetAtomWithIdx(j).IsInRing() for i, j in core.items())
    assert sum(caf.GetAtomWithIdx(i).IsInRing() for i in core) == 9   # both ring systems, superimposed
    assert p["frame"] is None


def test_the_pair_counts(pairs):
    modes = {}
    for p in pairs["pairs"].values():
        k = p["mode"] + ("+highlight" if p["highlight"] else "")
        modes[k] = modes.get(k, 0) + 1
    assert len(pairs["pairs"]) == 147
    assert modes == {"aligned+highlight": 24, "aligned": 51, "shipped": 72}


def test_a_caption_needs_a_highlighted_pair(records):
    comps = json.loads((SNAP / "comparisons.json").read_text())
    one = {"ethanol-vs-methanol": comps["ethanol-vs-methanol"]}
    with pytest.raises(D.DrawingSeedError, match="caption"):
        D.compile_compare_drawings(records, one, seed={"captions": {"ethanol-vs-methanol": "One carbon apart."}})


# ── Repeat units ─────────────────────────────────────────────────────────────────────────────
def _glucosyl_units(by_slug):
    """The alpha-glucosyl unit, cut from the catalog's own maltose (PubChem's 4-O-alpha-D-
    glucopyranosyl-D-glucose) with the next ring's carbon as any atom, as a chiral pattern; and
    its inverse at the anomeric carbon, the beta unit. A CIP label cannot be the test: a `*` end
    and the neighbouring ring both move the priorities."""
    m = Chem.MolFromSmiles(by_slug["maltose"]["isomeric_smiles"])
    acetal = [a for a in m.GetAtoms() if a.GetSymbol() == "C" and a.IsInRing()
              and sum(n.GetSymbol() == "O" for n in a.GetNeighbors()) == 2]
    link = next(a for a in acetal if all(n.GetDegree() == 2 for n in a.GetNeighbors()
                                     if n.GetSymbol() == "O"))
    ring = next(set(r) for r in m.GetRingInfo().AtomRings() if link.GetIdx() in r)
    other = next(set(r) for r in m.GetRingInfo().AtomRings() if link.GetIdx() not in r)
    o1 = next(n for n in link.GetNeighbors() if n.GetIdx() not in ring)
    c4 = next(n for n in o1.GetNeighbors() if n.GetIdx() != link.GetIdx())
    unit = set(ring) | {o1.GetIdx(), c4.GetIdx()}
    for i in list(ring):
        for n in m.GetAtomWithIdx(i).GetNeighbors():
            if n.GetIdx() not in other:
                unit.add(n.GetIdx())
                unit |= {x.GetIdx() for x in n.GetNeighbors() if x.GetSymbol() == "O"}
    rw = Chem.RWMol(m)
    rw.GetAtomWithIdx(c4.GetIdx()).SetAtomicNum(0)          # the next ring's carbon: any atom
    rw.GetAtomWithIdx(c4.GetIdx()).SetNoImplicit(True)
    rw.GetAtomWithIdx(c4.GetIdx()).SetNumExplicitHs(0)
    alpha = Chem.MolFragmentToSmiles(rw, atomsToUse=sorted(unit), isomericSmiles=True)
    inv = Chem.RWMol(Chem.MolFromSmiles(alpha))
    next(a for a in inv.GetAtoms() if a.GetSymbol() == "C" and a.IsInRing()
     and sum(n.GetSymbol() == "O" for n in a.GetNeighbors()) == 2).InvertChirality()
    return Chem.MolFromSmarts(alpha), Chem.MolFromSmarts(Chem.MolToSmiles(inv))


def _count(smiles, q):
    return len(Chem.MolFromSmiles(smiles).GetSubstructMatches(q, useChirality=True))


def test_starch_is_alpha_and_cellulose_beta_and_nothing_else_differs(by_slug):
    alpha, beta = _glucosyl_units(by_slug)
    st, ce = (by_slug[s]["structure_repeat_unit"] for s in ("starch", "cellulose"))
    assert (_count(st["smiles"], alpha), _count(st["smiles"], beta)) == (2, 0)
    assert (_count(ce["smiles"], alpha), _count(ce["smiles"], beta)) == (0, 2)
    assert (st["linkage"], ce["linkage"]) == ("alpha-1,4", "beta-1,4")
    # the catalog's own amylose model (alpha-1,4, methyl ends) agrees with the pattern
    assert _count(by_slug["amylose"]["isomeric_smiles"], alpha) == 2
    flat = [Chem.MolToSmiles(Chem.MolFromSmiles(u["smiles"]), isomericSmiles=False) for u in (st, ce)]
    assert flat[0] == flat[1]
    for u in (st, ce):
        assert u["label"] == "Two units of the chain" and u["units"] == 2
        mol = Chem.MolFromSmiles(u["smiles"])
        assert sorted(mol.GetAtomWithIdx(i).GetSymbol() for i in u["linkage_atoms"]) == ["C", "C", "O"]
        assert u["layer"].startswith("<path class='mf-linkage'")
    assert not by_slug["starch"].get("structure_svg") and not by_slug["cellulose"].get("structure_svg")
    # one layout: every skeleton atom on the same pixel, so side by side only the linkage differs
    ex = [G.exact_points(u["svg"], G.drawing_mol(Chem.MolFromSmiles(u["smiles"]), u["svg"])) for u in (st, ce)]
    assert len(ex[0].keys() & ex[1].keys()) >= 10
    assert all(math.dist(ex[0][i], ex[1][i]) <= 0.1 for i in ex[0].keys() & ex[1].keys())


def test_the_starch_unit_is_the_catalogs_own_maltose(by_slug):
    """Starch's fragment with hydrogen for `*` is maltose, stereo included (its reducing end set)."""
    st = by_slug["starch"]["structure_repeat_unit"]["smiles"]
    mine = Chem.MolFromSmiles(st.replace("*", "[H]"))
    maltose = Chem.MolFromSmiles(by_slug["maltose"]["isomeric_smiles"])
    assert mine.HasSubstructMatch(maltose, useChirality=True)


# ── Colours ──────────────────────────────────────────────────────────────────────────────────
ALLOWED = {h.upper() for h in S.CPK_HEX.values()} | {S.FALLBACK_HEX.upper(), D.AMBER.upper()}


def _colours(svg: str) -> set[str]:
    return {h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}", svg)}


def test_no_black_and_only_band_colours_plus_the_amber(records, pairs):
    outputs = []
    for r in records:
        outputs += [p["layer"] for p in (r.get("structure_parts") or {}).get("parts") or []]
        u = r.get("structure_repeat_unit")
        if u:
            outputs += [u["svg"], u["layer"]]
    for p in pairs["pairs"].values():
        outputs += [x for x in (p.get("b_svg"), p.get("a_layer"), p.get("b_layer")) if x]
    assert len(outputs) > 1500
    for out in outputs:
        found = _colours(out)
        assert "#000000" not in found and found <= ALLOWED, found - ALLOWED
        assert all(S.in_band(h) for h in found - {D.AMBER.upper()})


# ── Keys, carry-forward, repaint: the two-machine proof ──────────────────────────────────────
def test_a_run_with_current_keys_never_reads_lays_out_or_draws(records, pairs, monkeypatch):
    """What Monday's Linux run does: every key current, so every output carried byte for byte and
    no platform-dependent call made (no reading, no layout, no drawing, no common-core search)."""
    def boom(*a, **k):
        raise AssertionError("a carried output was made again")
    monkeypatch.setattr(G, "read_positions", boom)
    monkeypatch.setattr(S, "draw", boom)
    monkeypatch.setattr(D, "_core", boom)
    monkeypatch.setattr(D, "draw_repeat_unit", boom)
    import rdkit.Chem.rdDepictor as dep
    monkeypatch.setattr(dep, "Compute2DCoords", boom)
    D._READINGS.clear()
    prior = {r["cid"]: r for r in records}
    fresh = [{k: v for k, v in r.items() if k not in ("structure_parts", "structure_repeat_unit")}
             for r in records]
    D.attach_structure_parts(fresh, prior)
    D.attach_repeat_units(fresh, prior)
    for a, b in zip(fresh, records):
        assert a.get("structure_parts") == b.get("structure_parts"), a["slug"]
        assert a.get("structure_repeat_unit") == b.get("structure_repeat_unit"), a["slug"]
    comps = json.loads((SNAP / "comparisons.json").read_text())
    again = D.compile_compare_drawings(records, comps, prior=pairs)
    assert json.dumps(again, ensure_ascii=False) == json.dumps(pairs, ensure_ascii=False)


def test_a_palette_change_repaints_the_new_drawings_and_moves_nothing(records, pairs, by_slug):
    """sodium bicarbonate vs sodium carbonate draws sodium; pretend it was drawn in trust run 6's
    palette (Jmol's untuned Na, recipe 2026-10-25.1): the carry repaints it, coordinates untouched."""
    slug = "sodium-bicarbonate-vs-sodium-carbonate"
    old = copy.deepcopy(pairs)
    entry = old["pairs"][slug]
    now = S.CPK_HEX[11].upper()
    assert now in entry["b_svg"]
    entry["b_svg"] = entry["b_svg"].replace(now, "#AB5CF2")
    entry["palette"] = "2026-10-25.1"
    comps = json.loads((SNAP / "comparisons.json").read_text())
    again = D.compile_compare_drawings(records, {slug: comps[slug]}, prior=old)
    assert again["pairs"][slug] == pairs["pairs"][slug]


def test_a_layer_rests_on_the_drawing_geometry_not_its_colours(by_slug):
    caf = by_slug["caffeine"]
    repainted = caf["structure_svg"].replace(S.CPK_HEX[8].upper(), "#123456")
    assert D.geometry_sha(repainted) == D.geometry_sha(caf["structure_svg"])
    moved = caf["structure_svg"].replace("363.7,207.0", "363.8,207.0")
    assert D.geometry_sha(moved) != D.geometry_sha(caf["structure_svg"])


def test_no_shipped_drawing_moved_without_its_own_key(records):
    """The manifest of every structure_svg as shipped before phase 5A (key, sha256). A drawing may
    change only when its key does (a new recipe or a new SMILES), never as a side effect."""
    manifest = json.loads(MANIFEST.read_text())
    for r in records:
        if r["slug"] in manifest and r.get("structure_svg"):
            key, sha = manifest[r["slug"]]
            if r["structure_svg_key"] == key:
                assert hashlib.sha256(r["structure_svg"].encode()).hexdigest() == sha, r["slug"]


def test_making_from_scratch_is_deterministic(records):
    """The recipes, run twice from nothing on one machine, give the same bytes (the pinned build's
    own check, twice byte-identical, rests on this)."""
    sample = [r for r in records if r["slug"] in {"caffeine", "aspirin", "testosterone", "glucose"}]
    outs = []
    for _ in range(2):
        D._READINGS.clear()
        fresh = [{k: v for k, v in r.items() if k != "structure_parts"} for r in sample]
        D.attach_structure_parts(fresh, {})
        outs.append(json.dumps([r["structure_parts"] for r in fresh]))
    assert outs[0] == outs[1]
    assert json.loads(outs[0]) == [r["structure_parts"] for r in sample]
