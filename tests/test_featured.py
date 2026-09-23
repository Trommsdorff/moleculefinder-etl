"""Molecule of the week: the seed is fenced like every curated seed, and the pick is a function
of the snapshot's own date.

Three promises are pinned here. The compiler fails the run, listing every problem, on anything
the seed must not do. The featured molecule is the entry for the ISO week of meta.json's
`refreshed` date and never of a clock, so the weekly CI run and a local run later the same week
agree. And the export keeps featured.json keyed to that date: a new week always changes the
snapshot (every Monday opens a data PR), a second run the same week changes nothing (the
heartbeat case).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from moleculefinder_etl import freshness, pipeline
from moleculefinder_etl.config import SNAPSHOTS
from moleculefinder_etl.load import snapshot_export
from moleculefinder_etl.transform import featured, relationships

ITEM_KEYS = {"week", "iso_year", "iso_week", "monday", "slug", "title", "formula", "line",
             "line_source", "confidence", "source"}


def _rec(i: int, **over) -> dict:
    base = {
        "cid": 1000 + i, "slug": f"m{i}", "title": f"Molecule {i}",
        "molecular_formula": f"C{i}H{2 * i}", "inchikey": f"SKELETON{i:06d}-UHFFFAOYSA-N",
        "structure_svg": "<svg/>", "hand_model": False, "macromolecule": False,
        "why_it_matters": {"text": f"Why molecule {i} matters to an ordinary reader."},
    }
    return {**base, **over}


def _catalog() -> list[dict]:
    return [_rec(i) for i in range(1, 60)]


def _entries(**hooks) -> list[dict]:
    return [{"week": w, "slug": f"m{w}", **({"hook": hooks[f"w{w}"]} if f"w{w}" in hooks else {})}
            for w in range(1, 54)]


def _fails(match: str, molecules=None, entries=None):
    with pytest.raises(SystemExit, match=match):
        featured.compile_queue(molecules or _catalog(), entries if entries is not None else _entries())


@pytest.fixture(autouse=True)
def _no_held_rows(monkeypatch):
    monkeypatch.setattr(featured, "_held_rows", lambda: [])


# ── the committed seed ───────────────────────────────────────────────────────
def _snapshot_records() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((SNAPSHOTS / "molecules").glob("*.json"))]


def test_the_committed_seed_compiles_against_the_committed_snapshot(monkeypatch):
    monkeypatch.undo()                       # the real deferred_rows.csv, not the stub
    queue = featured.compile_queue(_snapshot_records())
    assert sorted(queue) == list(range(1, 54))
    slugs = [q["slug"] for q in queue.values()]
    assert len(set(slugs)) == 53


def test_the_committed_seed_lists_each_week_once_in_order():
    weeks = [e["week"] for e in featured.load_featured()]
    assert weeks == list(range(1, 54))


# ── the fence: each rule fails loudly ─────────────────────────────────────────
def test_a_clean_seed_compiles():
    queue = featured.compile_queue(_catalog(), _entries(w5="A hook that is long enough to pass the floor."))
    assert queue[5] == {"slug": "m5", "hook": "A hook that is long enough to pass the floor."}
    assert queue[6] == {"slug": "m6", "hook": None}


def test_an_unknown_slug_fails():
    e = _entries()
    e[16]["slug"] = "no-such-molecule"
    _fails(r"week 17: unknown slug 'no-such-molecule'", entries=e)


def test_a_missing_week_fails():
    _fails(r"missing week\(s\): 17", entries=[x for x in _entries() if x["week"] != 17])


def test_a_week_listed_twice_fails():
    _fails(r"week 3: listed twice", entries=_entries() + [{"week": 3, "slug": "m55"}])


@pytest.mark.parametrize("bad", [0, 54, "3", 2.0, True, None])
def test_a_week_outside_1_to_53_fails(bad):
    _fails("week must be a whole number from 1 to 53", entries=_entries() + [{"week": bad, "slug": "m55"}])


def test_an_unknown_key_fails():
    e = _entries()
    e[0]["hok"] = "a typo for hook"
    _fails(r"unknown key\(s\) hok", entries=e)


def test_a_slug_twice_fails():
    e = _entries()
    e[20]["slug"] = "m3"
    _fails(r"week 21: 'm3' is already week 3", entries=e)


def test_a_molecule_that_appears_twice_in_the_catalog_fails():
    """estradiol and estradiol-medication: one skeleton, two pages. Neither may be featured."""
    mols = _catalog()
    mols[57]["inchikey"] = mols[2]["inchikey"].split("-")[0] + "-XXXXXXXXXX-N"     # m58 twins m3
    _fails(r"week 3: 'm3' appears twice in the catalog, it shares its structure skeleton with m58",
           molecules=mols)


def test_a_macromolecule_fails():
    mols = _catalog()
    mols[7].update(hand_model=True, macromolecule=True, structure_svg=None)
    _fails(r"week 8: 'm8' is a macromolecule or has no structure to draw", molecules=mols)


def test_a_molecule_without_a_why_it_matters_line_fails():
    mols = _catalog()
    mols[9]["why_it_matters"] = None
    _fails(r"week 10: 'm10' has no why_it_matters line", molecules=mols)


def test_a_held_row_fails_by_cid_and_by_name(monkeypatch):
    monkeypatch.setattr(featured, "_held_rows", lambda: [
        {"molecule": "Molecule 4", "pubchem_cid": "999999"},        # by name -> slug "molecule-4"
        {"molecule": "Xylazine", "pubchem_cid": str(1000 + 11)},     # by CID -> m11
    ])
    mols = _catalog()
    mols[3]["slug"] = "molecule-4"
    e = _entries()
    e[3]["slug"] = "molecule-4"
    with pytest.raises(SystemExit) as exc:
        featured.compile_queue(mols, e)
    assert "week 4: 'molecule-4' is held in deferred_rows.csv" in str(exc.value)
    assert "week 11: 'm11' is held in deferred_rows.csv" in str(exc.value)


@pytest.mark.parametrize("hook, why", [
    ("An em dash — in a hook that is otherwise long enough to pass.", "em-dash"),
    ("An en dash – in a hook that is otherwise long enough to pass.", "en-dash"),
    ("Too short.", "the rule is 40 to 170"),
    ("A" * 171 + ".", "the rule is 40 to 170"),
    ("Two lines are not one line,\nwhich the block cannot show.", "one line"),
    ("A hook that trails off without a full stop at the end", "full stop"),
    ("You should drink this every morning before breakfast, it helps.", "advice"),
    ("A hook that names a dose of 500 mg is dosing, not a story.", "advice"),
])
def test_a_bad_hook_fails(hook, why):
    _fails(f"week 5: .*{why}", entries=_entries(w5=hook))


def test_every_problem_is_listed_at_once():
    e = _entries(w9="Too short.")
    e[16]["slug"] = "no-such-molecule"
    with pytest.raises(SystemExit) as exc:
        featured.compile_queue(_catalog(), e)
    assert "week 17: unknown slug" in str(exc.value) and "week 9: the hook" in str(exc.value)


def test_no_seed_means_no_feature(monkeypatch, tmp_path):
    monkeypatch.setattr(featured, "FEATURED_YAML", tmp_path / "absent.yaml")
    assert featured.compile_queue(_catalog()) is None


# ── selection: the snapshot's date, never a clock ─────────────────────────────
def _queue(**hooks):
    return featured.compile_queue(_catalog(), _entries(**hooks))


def test_the_pick_is_the_iso_week_of_the_refreshed_date():
    out = featured.build_featured(_queue(), _catalog(), "2026-09-23")       # a Wednesday
    assert out["current"]["week"] == "2026-W39" and out["current"]["monday"] == "2026-09-21"
    assert out["current"]["slug"] == "m39"
    assert out["weeks"] == [out["current"]] and out["start"] == "2026-W39"


def test_a_monday_ci_run_and_a_sunday_local_run_agree():
    q, mols = _queue(), _catalog()
    monday = featured.build_featured(q, mols, "2026-10-05")
    sunday = featured.build_featured(q, mols, "2026-10-11")
    assert json.dumps(monday) == json.dumps(sunday)
    assert featured.build_featured(q, mols, "2026-10-12")["current"]["week"] == "2026-W42"


def test_the_clock_is_never_read(monkeypatch):
    class NoClock(dt.date):
        @classmethod
        def today(cls):
            raise AssertionError("build_featured read the clock")
    monkeypatch.setattr(featured, "date", NoClock)
    assert featured.build_featured(_queue(), _catalog(), "2026-11-26")["current"]["week"] == "2026-W48"


def test_the_history_runs_newest_first_across_week_53():
    out = featured.build_featured(_queue(), _catalog(), "2027-01-06")
    weeks = [i["week"] for i in out["weeks"]]
    assert weeks[:3] == ["2027-W01", "2026-W53", "2026-W52"] and weeks[-1] == "2026-W39"
    assert len(weeks) == 16
    assert out["weeks"][1]["monday"] == "2026-12-28" and out["weeks"][1]["slug"] == "m53"


def test_a_year_without_week_53_skips_it():
    weeks = [i["week"] for i in featured.build_featured(_queue(), _catalog(), "2028-01-05")["weeks"]]
    assert weeks[:2] == ["2028-W01", "2027-W52"] and "2027-W53" not in weeks


def test_a_date_before_the_start_week_gives_just_that_week():
    out = featured.build_featured(_queue(), _catalog(), "2026-09-12")
    assert [i["week"] for i in out["weeks"]] == ["2026-W37"]


def test_an_item_carries_the_hook_or_else_the_why_it_matters_line():
    q = _queue(w39="Pumpkin spice has no pumpkin in it, which surprises people.")
    out = featured.build_featured(q, _catalog(), "2026-09-29")
    w40, w39 = out["weeks"]
    assert set(w40) == ITEM_KEYS and set(w39) == ITEM_KEYS
    assert (w39["line"], w39["line_source"]) == ("Pumpkin spice has no pumpkin in it, which surprises people.", "hook")
    assert (w40["line"], w40["line_source"]) == ("Why molecule 40 matters to an ordinary reader.", "why_it_matters")
    assert (w40["title"], w40["formula"], w40["confidence"]) == ("Molecule 40", "C40H80", "from_source")


# ── the export keeps featured.json keyed to meta.json ─────────────────────────
@pytest.fixture
def snap(tmp_path, monkeypatch):
    root = tmp_path / "snapshots"
    root.mkdir()
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", root)
    monkeypatch.setattr(freshness, "load", lambda path=None: {})
    return root


def _export(recs, today, with_featured=True):
    builder = (lambda refreshed: featured.build_featured(_queue(), recs, refreshed)) if with_featured else None
    snapshot_export.export(recs, {}, featured=builder, today=today)


def _files(root: Path) -> dict:
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*.json")}


def _read(root: Path, name: str) -> dict:
    return json.loads((root / name).read_text())


def test_the_first_export_writes_this_weeks_pick(snap):
    _export(_catalog(), "2026-09-23")
    assert _read(snap, "meta.json") == {"refreshed": "2026-09-23"}
    assert _read(snap, "featured.json")["current"]["week"] == "2026-W39"


def test_a_second_run_in_the_same_week_changes_nothing(snap):
    """The heartbeat case: a dispatch later in the week with no data change."""
    _export(_catalog(), "2026-09-21")
    before = _files(snap)
    _export(_catalog(), "2026-09-26")
    assert _files(snap) == before


def test_a_new_week_changes_the_snapshot_even_when_no_data_did(snap):
    """Every Monday run now opens a data PR: featured.json and meta.json move, nothing else."""
    _export(_catalog(), "2026-09-23")
    before = _files(snap)
    _export(_catalog(), "2026-09-28")
    after = _files(snap)
    moved = {str(k) for k in after if after[k] != before.get(k)}
    assert moved == {"featured.json", "meta.json"}
    assert _read(snap, "meta.json") == {"refreshed": "2026-09-28"}
    data = _read(snap, "featured.json")
    assert data["current"]["week"] == "2026-W40" and [i["week"] for i in data["weeks"]] == ["2026-W40", "2026-W39"]


def test_featured_json_always_names_the_week_of_meta_json(snap):
    for day in ["2026-09-21", "2026-09-24", "2026-10-02", "2026-10-06", "2026-12-31", "2027-01-04"]:
        _export(_catalog(), day)
        refreshed = dt.date.fromisoformat(_read(snap, "meta.json")["refreshed"])
        y, w, _ = refreshed.isocalendar()
        assert _read(snap, "featured.json")["current"]["week"] == featured.iso_label(y, w)


def test_removing_the_seed_removes_the_file_and_moves_the_date(snap):
    _export(_catalog(), "2026-09-23")
    _export(_catalog(), "2026-09-25", with_featured=False)
    assert not (snap / "featured.json").exists()
    assert _read(snap, "meta.json") == {"refreshed": "2026-09-25"}


def test_a_bad_seed_stops_the_export_before_anything_is_written(snap, tmp_path, monkeypatch):
    molecules = tmp_path / "molecules-in.json"
    molecules.write_text(json.dumps(_catalog()))
    monkeypatch.setattr(pipeline, "MOLECULES", molecules)
    monkeypatch.setattr(relationships, "load_comparisons", lambda: {})
    monkeypatch.setattr(featured, "load_featured", lambda path=None: _entries()[:-1])    # no week 53
    (snap / "meta.json").write_text('{"refreshed": "2026-09-21"}')
    with pytest.raises(SystemExit, match="missing week"):
        pipeline.stage_export(None)
    assert sorted(p.name for p in snap.iterdir()) == ["meta.json"]


def test_the_offline_stage_rebuilds_the_file_for_the_stored_date(snap, monkeypatch):
    _export(_catalog(), "2026-09-21")
    (snap / "featured.json").unlink()
    monkeypatch.setattr(pipeline, "SNAPSHOTS", snap)
    monkeypatch.setattr(featured, "load_featured", lambda path=None: _entries())
    pipeline.stage_featured(None)
    assert _read(snap, "meta.json") == {"refreshed": "2026-09-21"}
    before = _files(snap)
    _export(_catalog(), "2026-09-24")                 # a real export later that week agrees
    assert _files(snap) == before
