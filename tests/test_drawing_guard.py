"""The drawing guard (2026-11-13): every drawing a run would ship, against what shipped.

Found at the phase 5 deploy: the weekly run held its data PR only if caffeine's parts, the home
page's pair or one framed pair moved; any other part layer, pair drawing or repeat unit could change
on the Linux runner and merge unseen. ``transform/drawing_guard.py`` now compares every
``structure_svg``, every part layer, every pair in ``compare_drawings.json`` and every repeat unit
with the shipped snapshot, and ``pipeline._preflight`` stops the run (before the load, before the
export) on a change nothing explains. What these tests hold, both directions:

- the shipped snapshot against itself carries every drawing: Monday's exact lines, nothing listed;
- a changed output under an unchanged key stops the export and names the entry and what differs
  (a part layer, a pair drawing, a structure drawing, a repeat unit);
- a key that moved with no input moving (the realistic Linux shape) stops, unless the build says a
  drawing seed changed on purpose;
- a new molecule, a new pair, and an entry whose key moved with its input (a SMILES, a recipe or
  palette version, the drawing it sits on, a seed's words) pass and are listed by name;
- the refusal comes before the database and writes nothing; the summary and the report carry it;
- the weekly workflow puts the block on the summary page, in the all-clear and the alarm, and never
  sets the seed flag.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from moleculefinder_etl import pipeline
from moleculefinder_etl.config import Settings
from moleculefinder_etl.load import snapshot_export, snapshot_guard, supabase_loader
from moleculefinder_etl.transform import (
    claims,
    doors,
    drawings,
    featured,
    relationships,
    structures,
)
from moleculefinder_etl.transform import drawing_guard as DG

ROOT = Path(__file__).resolve().parent.parent
SNAP = ROOT / "data" / "snapshots"
WORKFLOW = ROOT / ".github" / "workflows" / "etl.yml"

# What a weekly run on the committed snapshot must report: every drawing carried, nothing made.
# (Monday 2026-11-16's acceptance on main reads 718 and 193; phase 8's tertiary amine rule, with its
# data, makes it 719 carried and 192 with no part: trimethylamine gains its first part.)
MONDAY = [
    "structure drawings: 896 carried, 0 repainted, 0 drawn, 19 with no drawing",
    "structure parts: 719 carried, 0 made, 192 with no part, 4 drawings unreadable",
    ("compare drawings: 147 pairs (aligned 44, aligned+highlight 30, shipped 72, shipped+highlight 1); "
    "147 carried, 0 repainted, 0 made"),
    "repeat units: 2 (2 carried, 0 repainted, 0 drawn this run)",
]

SMALL = ["caffeine", "theobromine", "isotretinoin", "tretinoin", "sodium-bicarbonate", "sodium-carbonate",
         "starch", "cellulose", "aldosterone"]
SMALL_PAIRS = ["caffeine-vs-theobromine", "isotretinoin-vs-tretinoin",
               "sodium-bicarbonate-vs-sodium-carbonate", "starch-vs-cellulose"]


def _load(slug: str) -> dict:
    return json.loads((SNAP / "molecules" / f"{slug}.json").read_text())


def _all_pairs() -> dict:
    return json.loads((SNAP / "compare_drawings.json").read_text())


def _plant(directory: Path, records: list[dict], pairs: dict | None) -> None:
    mol = directory / "molecules"
    mol.mkdir(parents=True, exist_ok=True)
    for f in mol.glob("*.json"):
        f.unlink()
    for r in records:
        (mol / f"{r['slug']}.json").write_text(json.dumps(r, ensure_ascii=False))
    path = directory / "compare_drawings.json"
    if pairs is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(json.dumps(pairs, ensure_ascii=False))


@pytest.fixture
def world(tmp_path):
    """Nine shipped molecules and four shipped pairs, copied from the committed snapshot into a
    shipped snapshot of their own, and a deep copy of them as this run's output, to change."""
    recs = [_load(s) for s in SMALL]
    allp = _all_pairs()
    pairs = {**{k: v for k, v in allp.items() if k != "pairs"},
             "pairs": {s: allp["pairs"][s] for s in SMALL_PAIRS}}
    shipped = tmp_path / "shipped"
    _plant(shipped, recs, pairs)
    new = copy.deepcopy(recs)
    w = SimpleNamespace(dir=shipped, recs=new, pairs=copy.deepcopy(pairs),
                        shipped_recs=recs, shipped_pairs=pairs)
    w.by = lambda slug: next(r for r in new if r["slug"] == slug)
    w.check = lambda **k: DG.check(w.recs, w.pairs, w.dir, allow_seeds=k.get("allow_seeds", False))
    return w


def _nudge(svg: str) -> str:
    """The same drawing with one coordinate moved by a tenth of a pixel."""
    i = svg.index("<path class='bond-0")
    j = svg.index("M ", i) + 2
    k = svg.index(",", j)
    return svg[:j] + f"{float(svg[j:k]) + 0.1:.1f}" + svg[k:]


# ── The shipped snapshot against itself: Monday ─────────────────────────────────────────────────
def test_monday_the_shipped_snapshot_carries_every_drawing():
    """The committed snapshot as this run's output: every drawing carried, nothing listed. These
    four lines are what Monday 2026-11-16's summary page must show."""
    by_cid, pairs = DG.shipped(SNAP)
    v = DG.check([by_cid[c] for c in sorted(by_cid)], pairs, SNAP, allow_seeds=False)
    assert v.lines == MONDAY
    assert v.made == [] and v.stops == [] and not v.stopped
    assert v.text().splitlines() == [*MONDAY, "made or remade this run: none"]
    assert "**Made or remade this run: none.**" in v.markdown()


def test_the_guard_counts_in_the_recipes_own_words(caplog):
    """The parts and pairs lines are the recipes' own log lines, character for character, on the
    carry Monday makes (the 5A replay), so the summary page says what the step log says."""
    pytest.importorskip("rdkit")
    records = [json.loads(p.read_text()) for p in sorted((SNAP / "molecules").glob("*.json"))]
    pairs = _all_pairs()
    prior = {r["cid"]: r for r in records}
    fresh = [{k: v for k, v in r.items() if k not in ("structure_parts", "structure_repeat_unit")}
             for r in records]
    caplog.set_level("INFO", logger="mfetl")
    drawings.attach_structure_parts(fresh, prior)
    made = drawings.attach_repeat_units(fresh, prior)
    again = drawings.compile_compare_drawings(fresh, json.loads((SNAP / "comparisons.json").read_text()),
                                              prior=pairs)
    logged = [r.getMessage().strip() for r in caplog.records]
    v = DG.check(fresh, again, SNAP, allow_seeds=False)
    assert v.lines[1] in logged and v.lines[2] in logged
    assert "repeat units: 2 (0 drawn this run)" in logged and made == 0
    assert v.lines == MONDAY and v.made == []


def test_the_guard_never_reads_lays_out_or_draws(monkeypatch):
    """It compares bytes only: with every platform-dependent call made to raise, it still runs.
    So it can change no output, on any machine."""
    pytest.importorskip("rdkit")
    import rdkit.Chem.rdDepictor as dep

    from moleculefinder_etl.transform import svg_geometry

    def boom(*a, **k):
        raise AssertionError("the guard made a drawing")
    for mod, name in ((svg_geometry, "read_positions"), (structures, "draw"), (structures, "svg_for"),
                      (structures, "recolour"), (drawings, "_core"), (drawings, "draw_pair"),
                      (drawings, "draw_repeat_unit"), (drawings, "find_parts"), (dep, "Compute2DCoords")):
        monkeypatch.setattr(mod, name, boom)
    by_cid, pairs = DG.shipped(SNAP)
    assert DG.check([by_cid[c] for c in sorted(by_cid)], pairs, SNAP, allow_seeds=False).lines == MONDAY


# ── A changed output under an unchanged key stops, naming the entry ─────────────────────────────
def test_a_changed_part_layer_under_an_unchanged_key_stops_and_names_it(world):
    part = world.by("caffeine")["structure_parts"]["parts"][1]
    part["layer"] = part["layer"].replace("M", "M0", 1)
    v = world.check()
    assert v.stops == [("caffeine (structure parts): changed under an unchanged key "
                       "(parts[methyl-groups].layer)")]
    with pytest.raises(DG.DrawingChanged, match=r"caffeine \(structure parts\)"):
        DG.enforce(v)


def test_a_changed_pair_drawing_under_an_unchanged_key_stops_and_names_it(world):
    pair = world.pairs["pairs"]["caffeine-vs-theobromine"]
    pair["b_svg"] = _nudge(pair["b_svg"])
    v = world.check()
    assert v.stops == ["caffeine-vs-theobromine (compare drawing): changed under an unchanged key (b_svg)"]
    assert v.text().startswith("STOPPED: 1 drawing(s) changed with nothing to explain it")
    assert "caffeine-vs-theobromine (compare drawing)" in v.markdown()


@pytest.mark.parametrize("what", ["structure drawing", "repeat unit", "pair caption", "unread parts"])
def test_every_other_output_changed_under_its_key_stops_too(world, what):
    if what == "structure drawing":
        rec = world.by("theobromine")
        rec["structure_svg"] = _nudge(rec["structure_svg"])
        want = ["theobromine (structure drawing): changed under an unchanged key (structure_svg)",
                ("theobromine (structure parts): kept under an unchanged key although its drawing moved "
                "(the key covers them, so its layers would sit on the wrong atoms)")]
    elif what == "repeat unit":
        unit = world.by("starch")["structure_repeat_unit"]
        unit["svg"] = _nudge(unit["svg"])       # not a repaint: the palette did not move
        want = ["starch (repeat unit): changed under an unchanged key (svg)"]
    elif what == "pair caption":
        world.pairs["pairs"]["caffeine-vs-theobromine"]["caption"] = "One methyl group apart, roughly."
        want = ["caffeine-vs-theobromine (compare drawing): changed under an unchanged key (caption)"]
    else:
        world.by("aldosterone")["structure_parts"]["unread"] = "read on another machine"
        want = ["aldosterone (structure parts): changed under an unchanged key (unread)"]
    assert world.check().stops == want


# ── A new entry, and a key that moved with its input, pass and are listed ───────────────────────
def test_a_new_molecule_and_a_new_pair_pass_and_are_listed(world):
    shipped = [r for r in world.shipped_recs if r["slug"] != "theobromine"]
    pairs = copy.deepcopy(world.shipped_pairs)
    del pairs["pairs"]["caffeine-vs-theobromine"]
    _plant(world.dir, shipped, pairs)
    v = world.check()
    assert not v.stopped
    assert v.made == ["theobromine (structure drawing): new, a new molecule",
                      "theobromine (structure parts): new, a new molecule",
                      "caffeine-vs-theobromine (compare drawing): new, a new pair"]
    assert v.lines[0] == "structure drawings: 6 carried, 0 repainted, 1 drawn, 2 with no drawing"
    assert v.lines[1] == "structure parts: 5 carried, 1 made, 2 with no part, 1 drawings unreadable"
    assert "3 carried, 0 repainted, 1 made" in v.lines[2]


def test_a_corrected_smiles_passes_and_lists_everything_it_remade(world):
    """caffeine's SMILES corrected upstream: its drawing, its parts and its pair are all made again,
    and each says why."""
    rec, other = world.by("caffeine"), _load("theophylline")
    rec["isomeric_smiles"] = other["isomeric_smiles"]
    rec["structure_svg"], rec["structure_svg_key"] = other["structure_svg"], other["structure_svg_key"]
    rec["structure_parts"] = copy.deepcopy(other["structure_parts"])
    world.pairs["pairs"]["caffeine-vs-theobromine"]["key"] = "0" * 16
    v = world.check()
    assert not v.stopped
    assert v.made == ["caffeine (structure drawing): redrawn, its SMILES changed",
                      "caffeine (structure parts): remade, its SMILES changed, its drawing changed",
                      ("caffeine-vs-theobromine (compare drawing): remade, caffeine's SMILES changed, "
                      "caffeine's drawing changed")]


def test_a_new_recipe_version_passes_and_is_listed(world):
    """A recipe bump committed on purpose: the stored recipe moves with the key."""
    parts = world.by("theobromine")["structure_parts"]
    parts["recipe"], parts["key"] = "2026-11-20.1", "1" * 16
    pair = world.pairs["pairs"]["sodium-bicarbonate-vs-sodium-carbonate"]
    pair["recipe"], pair["key"] = "2026-11-20.1", "2" * 16
    unit = world.by("cellulose")["structure_repeat_unit"]
    unit["recipe"], unit["key"] = "2026-11-20.1", "3" * 16
    v = world.check()
    assert not v.stopped
    assert v.made == [
        "theobromine (structure parts): remade, the parts recipe moved from 2026-11-12.1 to 2026-11-20.1",
        "cellulose (repeat unit): redrawn, the repeat-unit recipe moved from 2026-11-12.1 to 2026-11-20.1",
        ("sodium-bicarbonate-vs-sodium-carbonate (compare drawing): remade, the pairs recipe moved from "
        "2026-11-12.1 to 2026-11-20.1")]


def test_a_palette_change_repaints_passes_and_is_listed_and_a_moved_repaint_stops(world):
    """Shipped in trust run 6's palette (sodium in Jmol's untuned #AB5CF2): the current palette
    repaints the pair's second drawing and the drawing of sodium bicarbonate. A 'repaint' that also
    moved a coordinate is not one."""
    na = structures.CPK_HEX[11].upper()
    shipped = copy.deepcopy(world.shipped_recs)
    pairs = copy.deepcopy(world.shipped_pairs)
    entry = pairs["pairs"]["sodium-bicarbonate-vs-sodium-carbonate"]
    entry["b_svg"], entry["palette"] = entry["b_svg"].replace(na, "#AB5CF2"), "2026-10-25.1"
    soda = next(r for r in shipped if r["slug"] == "sodium-bicarbonate")
    soda["structure_svg"] = soda["structure_svg"].replace(na, "#AB5CF2")
    soda["structure_svg_key"] = structures.svg_key(soda["isomeric_smiles"], recipe="2026-10-25.1")
    _plant(world.dir, shipped, pairs)
    v = world.check()
    assert not v.stopped
    assert v.made == [
        ("sodium-bicarbonate (structure drawing): repainted, the structure recipe moved from 2026-10-25.1 "
        "to 2026-10-25.2"),
        ("sodium-bicarbonate-vs-sodium-carbonate (compare drawing): repainted, the palette moved from "
        "2026-10-25.1 to 2026-10-25.2")]
    assert "1 repainted" in v.lines[0] and "1 repainted" in v.lines[2]

    pair = world.pairs["pairs"]["sodium-bicarbonate-vs-sodium-carbonate"]
    pair["b_svg"] = _nudge(pair["b_svg"])
    assert world.check().stops == [("sodium-bicarbonate-vs-sodium-carbonate (compare drawing): changed "
                                   "under an unchanged key (palette, b_svg)")]


def test_only_a_seeds_words_moving_passes_but_not_if_a_layer_moved_with_them(world):
    """A caption or a part sentence edited in its seed changes the key and nothing drawn. If a layer
    moved too, on an unchanged drawing, this machine read the drawing differently: a stop."""
    pair = world.pairs["pairs"]["caffeine-vs-theobromine"]
    pair["caption"], pair["key"] = "One methyl group apart, on a nitrogen.", "4" * 16
    parts = world.by("theobromine")["structure_parts"]
    parts["parts"][0]["sentence"] += " Edited."
    parts["key"] = "5" * 16
    v = world.check()
    assert not v.stopped
    assert v.made == [
        ("theobromine (structure parts): remade, only its words in structure_parts.yaml changed; every "
        "layer is as shipped"),
        ("caffeine-vs-theobromine (compare drawing): remade, only its caption in compare_drawings.yaml "
        "changed; both drawings are as shipped")]

    parts["parts"][0]["layer"] = parts["parts"][0]["layer"].replace("M", "M0", 1)
    v = world.check()
    pid = parts["parts"][0]["id"]
    assert v.stops == [(f"theobromine (structure parts): remade with its recipe, SMILES and drawing "
                       f"unchanged (parts[{pid}].sentence, parts[{pid}].layer differ): either this "
                       f"machine computes it differently, or structure_parts.yaml changed without its "
                       f"data being built and committed with it (build it on the Mac with "
                       f"MFETL_DRAWING_SEEDS_CHANGED=1 and commit the data)")]


# ── A key that moved with no input moving stops ─────────────────────────────────────────────────
def test_a_key_that_moves_with_nothing_moving_stops(world):
    """The realistic Linux shape: the parts key holds which atoms the patterns match, so a machine
    that matches differently makes the parts again with a new key and nothing else moving."""
    caf = world.by("caffeine")["structure_parts"]
    caf["key"] = "6" * 16
    theo = world.by("theobromine")["structure_parts"]
    theo["key"], theo["parts"] = "7" * 16, theo["parts"][:1]
    world.pairs["pairs"]["isotretinoin-vs-tretinoin"]["key"] = "8" * 16
    v = world.check()
    tail = (": either this machine computes it differently, or {} changed without its data being built "
            "and committed with it (build it on the Mac with MFETL_DRAWING_SEEDS_CHANGED=1 and commit "
            "the data)")
    ids = [p["id"] for p in world.shipped_recs[1]["structure_parts"]["parts"]]
    assert v.stops == [
        "caffeine (structure parts): remade with its recipe, SMILES and drawing unchanged (only the key "
        "moved)" + tail.format("structure_parts.yaml"),
        f"theobromine (structure parts): remade with its recipe, SMILES and drawing unchanged (parts "
        f"{ids} became {ids[:1]})" + tail.format("structure_parts.yaml"),
        "isotretinoin-vs-tretinoin (compare drawing): remade with its recipe, SMILES and drawing "
        "unchanged (only the key moved)" + tail.format("its entry in compare_drawings.yaml")]
    with pytest.raises(DG.DrawingChanged) as e:
        DG.enforce(v)
    for name in ("caffeine (structure parts)", "theobromine (structure parts)",
                 "isotretinoin-vs-tretinoin (compare drawing)"):
        assert name in str(e.value)


def test_a_part_set_gained_or_lost_with_nothing_moving_stops(world):
    world.by("caffeine")["structure_parts"] = None
    world.by("starch")["structure_parts"] = copy.deepcopy(world.by("theobromine")["structure_parts"])
    stops = world.check().stops
    assert [s.split(":")[0] for s in stops] == ["caffeine (structure parts)", "starch (structure parts)"]
    assert "dropped with its recipe, SMILES and drawing unchanged (it lost its parts)" in stops[0]
    assert "made with its recipe, SMILES and drawing unchanged (it gained parts)" in stops[1]


def test_a_drawing_seed_changed_on_purpose_passes_with_the_flag(world, monkeypatch):
    """A person who changed a seed's patterns builds on the Mac with the flag; the entries pass and
    each says so. The same run without it stops."""
    theo = world.by("theobromine")["structure_parts"]
    theo["key"], theo["parts"] = "7" * 16, theo["parts"][:1]
    assert world.check().stopped
    v = world.check(allow_seeds=True)
    assert not v.stopped and v.made[0].startswith(
        "theobromine (structure parts): remade, MFETL_DRAWING_SEEDS_CHANGED=1 (a drawing seed changed on "
        "purpose; here parts [")
    monkeypatch.setenv(DG.SEEDS_CHANGED_ENV, "1")
    assert not DG.check(world.recs, world.pairs, world.dir).stopped
    monkeypatch.setenv(DG.SEEDS_CHANGED_ENV, "0")
    assert DG.check(world.recs, world.pairs, world.dir).stopped


def test_a_mark_on_the_second_shipped_drawing_stops_when_that_drawing_moves_under_it(world):
    """isotretinoin vs tretinoin marks tretinoin's SHIPPED drawing, which its key does not cover: a
    tretinoin redrawn by a structure recipe would leave the mark on the wrong pixels."""
    tre = world.by("tretinoin")
    tre["structure_svg"], tre["structure_svg_key"] = _nudge(tre["structure_svg"]), "9" * 40
    v = world.check()
    assert v.made == ["tretinoin (structure drawing): redrawn, the structure recipe moved (now 2026-10-25.2)"]
    assert v.stops == [("tretinoin (structure parts): kept under an unchanged key although its drawing moved "
                       "(the key covers them, so its layers would sit on the wrong atoms)"),
                       ("isotretinoin-vs-tretinoin (compare drawing): its mark sits on tretinoin's shipped "
                       "drawing, which moved while the pair's key did not (bump drawings.PAIRS_RECIPE to "
                       "make the pair again)")]


def test_a_molecule_that_leaves_takes_its_drawings_with_it(world):
    world.recs = [r for r in world.recs if r["slug"] != "starch"]
    del world.pairs["pairs"]["starch-vs-cellulose"]
    v = world.check()
    assert not v.stopped
    assert v.made == ["starch (repeat unit): removed, the molecule left the catalog",
                      "starch-vs-cellulose (compare drawing): removed, the pair left comparisons.yaml"]
    assert v.lines[3] == "repeat units: 1 (1 carried, 0 repainted, 0 drawn this run)"


# ── The refusal path: before the database, nothing written, reported ───────────────────────────
@pytest.fixture
def run(tmp_path, monkeypatch, world):
    """The pipeline over the small world: the shipped snapshot in SNAPSHOTS, this run's records
    staged, the compiles that need the whole catalog stubbed, the database a recorder."""
    from tests.test_guard_before_load import Database
    monkeypatch.delenv(snapshot_guard.OVERRIDE_ENV, raising=False)
    monkeypatch.delenv(DG.SEEDS_CHANGED_ENV, raising=False)
    for module in (pipeline, snapshot_export):
        monkeypatch.setattr(module, "SNAPSHOTS", world.dir)
    monkeypatch.setattr(pipeline, "MOLECULES", tmp_path / "molecules.json")
    monkeypatch.setattr(pipeline, "PRODUCTS_STAGED", tmp_path / "products.staged.json")
    monkeypatch.setattr(pipeline, "PRODUCT_PAIRS_STAGED", tmp_path / "product_pairs.staged.json")
    monkeypatch.setattr(relationships, "build_comparisons", lambda molecules: {})
    monkeypatch.setattr(featured, "compile_queue", lambda molecules: None)
    monkeypatch.setattr(doors, "compile_doors", lambda *a, **k: {"doors": []})
    monkeypatch.setattr(claims, "check_data_claims", lambda *a, **k: None)
    monkeypatch.setattr(drawings, "compile_compare_drawings", lambda *a, **k: world.pairs)
    db = Database()
    monkeypatch.setattr(supabase_loader, "get_client", db.client)
    for env in ("GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY", pipeline.DRAWINGS_REPORT_ENV):
        monkeypatch.delenv(env, raising=False)

    def stage():
        (tmp_path / "molecules.json").write_text(json.dumps(world.recs, ensure_ascii=False))
        return db
    stage.world = world
    return stage


def _tree(directory: Path) -> dict[str, str]:
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*")) if p.is_file()}


def _break_two(world) -> None:
    part = world.by("caffeine")["structure_parts"]["parts"][1]
    part["layer"] = part["layer"].replace("M", "M0", 1)
    pair = world.pairs["pairs"]["caffeine-vs-theobromine"]
    pair["b_svg"] = _nudge(pair["b_svg"])


def test_a_stop_comes_before_the_database(run):
    from tests.test_guard_before_load import CREDS
    _break_two(run.world)
    db = run()
    with pytest.raises(DG.DrawingChanged, match=r"caffeine \(structure parts\)"):
        pipeline.stage_load(CREDS)
    assert db.requests == [] and db.clients == 0


def test_a_stop_writes_nothing_and_the_shipped_snapshot_stands(run):
    _break_two(run.world)
    run()
    before = _tree(run.world.dir)
    with pytest.raises(DG.DrawingChanged) as e:
        pipeline.stage_export(Settings(None, None))
    assert "caffeine (structure parts)" in str(e.value)
    assert "caffeine-vs-theobromine (compare drawing)" in str(e.value)
    assert _tree(run.world.dir) == before


def test_a_stop_is_on_the_summary_page_the_report_and_the_annotations(run, tmp_path, monkeypatch, capsys):
    _break_two(run.world)
    run()
    summary, report = tmp_path / "step-summary.md", tmp_path / "drawings.json"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv(pipeline.DRAWINGS_REPORT_ENV, str(report))
    with pytest.raises(DG.DrawingChanged):
        pipeline.stage_load(Settings("https://project.supabase.co", "sb_secret_test"))
    page = summary.read_text()
    assert "**STOPPED (2): changed with nothing to explain it." in page
    assert "- caffeine (structure parts): changed under an unchanged key (parts[methyl-groups].layer)" in page
    assert "- caffeine-vs-theobromine (compare drawing): changed under an unchanged key (b_svg)" in page
    out = json.loads(report.read_text())
    assert out["stopped"] is True and out["text"].startswith("STOPPED: 2 drawing(s)")
    assert capsys.readouterr().out.count("::error title=Drawing changed with nothing to explain it::") == 2


def test_a_clean_run_reports_once_on_the_summary_page_and_always_in_the_report(run, tmp_path, monkeypatch):
    run()
    summary, report = tmp_path / "step-summary.md", tmp_path / "drawings.json"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv(pipeline.DRAWINGS_REPORT_ENV, str(report))
    pipeline._preflight(run.world.recs)                     # the load's call: the report only
    assert not summary.exists()
    assert json.loads(report.read_text())["stopped"] is False
    pipeline._preflight(run.world.recs, guard=False)        # the export's call: the summary page
    page = summary.read_text()
    assert page.startswith("### Drawings\n")
    assert "- structure parts: 6 carried, 0 made, 2 with no part, 1 drawings unreadable" in page
    assert "**Made or remade this run: none.**" in page
    assert json.loads(report.read_text())["text"].endswith("made or remade this run: none")


# ── The weekly workflow ─────────────────────────────────────────────────────────────────────────
def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _envs(node):
    if isinstance(node, dict):
        if isinstance(node.get("env"), dict):
            yield node["env"]
        for v in node.values():
            yield from _envs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _envs(v)


def test_the_weekly_workflow_carries_the_drawings_everywhere_and_never_the_seed_flag():
    wf = _workflow()
    run = wf["jobs"]["run"]
    steps = run["steps"]
    names = [s.get("name") or s.get("run") or s.get("uses") for s in steps]
    mfetl = steps[names.index("mfetl all --target 10000")]
    assert "name" not in mfetl          # the step keeps its name, "Run mfetl all --target 10000"
    assert mfetl["env"]["MFETL_DRAWINGS_REPORT"] == "${{ runner.temp }}/drawings.json"
    count = steps[names.index("Count drawings")]
    assert count["id"] == "drawings" and count["if"] == "always()"
    assert count["env"]["REPORT"] == mfetl["env"]["MFETL_DRAWINGS_REPORT"]
    assert names.index("mfetl all --target 10000") < names.index("Count drawings") < names.index("commit snapshot")
    assert run["outputs"]["drawings"] == "${{ steps.drawings.outputs.summary }}"
    for job in ("all-clear", "alarm"):
        step = next(s for s in wf["jobs"][job]["steps"] if "DRAWINGS" in (s.get("env") or {}))
        assert step["env"]["DRAWINGS"] == "${{ needs.run.outputs.drawings }}"
        assert "${DRAWINGS:-unknown}" in step["run"]
    alarm = wf["jobs"]["alarm"]["steps"][0]["run"]
    assert alarm.count("${DRAWINGS:-unknown}") == 3       # summary, "Failed again" comment, new issue
    for env in _envs(wf):
        assert DG.SEEDS_CHANGED_ENV not in env
    assert DG.SEEDS_CHANGED_ENV not in json.dumps(wf)


def _shell(script: str, tmp_path: Path, **env) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-e", "-c", script], check=False, cwd=tmp_path, capture_output=True, text=True,
                          env={**os.environ, **env})


def test_the_count_step_reads_the_report_or_says_unknown(tmp_path):
    step = next(s for s in _workflow()["jobs"]["run"]["steps"] if s.get("name") == "Count drawings")
    out, report = tmp_path / "github_output", tmp_path / "drawings.json"
    text = "\n".join([*MONDAY, "made or remade this run: none"])
    report.write_text(json.dumps({"stopped": False, "text": text}))
    out.write_text("")
    proc = _shell(step["run"], tmp_path, GITHUB_OUTPUT=str(out), REPORT=str(report))
    assert proc.returncode == 0, proc.stderr
    assert out.read_text() == f"summary<<MFETL_DRAWINGS_END\n{text}\nMFETL_DRAWINGS_END\n"
    report.unlink()
    out.write_text("")
    proc = _shell(step["run"], tmp_path, GITHUB_OUTPUT=str(out), REPORT=str(report))
    assert proc.returncode == 0
    assert out.read_text() == ("summary<<MFETL_DRAWINGS_END\nunknown: the run failed before the drawing "
                               "guard ran\nMFETL_DRAWINGS_END\n")


FAKE_GH = """#!/bin/bash
# Records every call (all its arguments, newlines kept); `issue list` answers FAKE_GH_LIST.
{ printf 'CALL'; printf ' [%s]' "$@"; printf '\\n'; } >> "$FAKE_GH_LOG"
case "$1 $2" in
  "issue list") printf '%s' "$FAKE_GH_LIST"; exit 0 ;;
esac
exit 0
"""


def test_the_all_clear_and_the_alarm_carry_the_drawings(tmp_path):
    wf = _workflow()
    drawn = "\n".join([*MONDAY, "made or remade this run: none"])
    summary = tmp_path / "summary.md"
    step = next(s for s in wf["jobs"]["all-clear"]["steps"] if s.get("name") == "Summary")
    proc = _shell(step["run"], tmp_path, GITHUB_STEP_SUMMARY=str(summary), HELD="0", PRODUCTS_HELD="0",
                  DRAWINGS=drawn)
    assert proc.returncode == 0, proc.stderr
    assert f"```\n{drawn}\n```\n" in summary.read_text()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH)
    (bin_dir / "gh").chmod(0o755)
    stopped = "STOPPED: 1 drawing(s) changed with nothing to explain it; nothing was exported\n- x (structure parts): y"
    alarm = wf["jobs"]["alarm"]["steps"][0]["run"]
    for listed, verb in (("", "issue create"), ("12", "issue comment")):
        log = tmp_path / f"gh-{verb.split()[1]}.log"
        summary.write_text("")
        proc = _shell(alarm, tmp_path, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", FAKE_GH_LOG=str(log),
                      FAKE_GH_LIST=listed, GITHUB_STEP_SUMMARY=str(summary), RUN="https://example.invalid/run",
                      HELD="0", PRODUCTS_HELD="0", DRAWINGS=stopped)
        assert proc.returncode == 0, proc.stderr
        assert f"```\n{stopped}\n```" in summary.read_text()
        call = next(c for c in log.read_text().split("CALL ")[1:] if c.startswith(f"[{verb.split()[0]}] [{verb.split()[1]}]"))
        assert f"```\n{stopped}\n```" in call
