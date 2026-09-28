"""A Wikidata item edited down to the placeholder keeps the summary it shipped with.

2026-09-28, run 36422607328: on 2026-09-25 a Wikidata editor reset Q414619's English
description from "chemical compound CaHPO₄" to "chemical compound" (the formula became an
alias). The Monday run read it live and the export guard, which refuses a summary reverting to
the placeholder however fresh the fetch, failed the week over dicalcium phosphate, a field no
page shows. It would have failed every Monday after, since nothing changes the answer.

``assemble._carried_summary`` applies the guard's rule at assembly for that one shape (the SAME
item, now only the placeholder) and leaves every other shape to the guard. These tests replay the
day with the real values, end to end through the export, and pin what still stops the run.
"""
from __future__ import annotations

import json

import pytest

from moleculefinder_etl import freshness
from moleculefinder_etl.load import snapshot_export, snapshot_guard
from moleculefinder_etl.load.snapshot_guard import SnapshotRegression
from moleculefinder_etl.sources import cache, wikidata
from moleculefinder_etl.transform import assemble
from tests.fixtures import canon_row, fetched

CID, QID = 24441, "Q414619"
SHIPPED = "chemical compound CaHPO₄"            # Q414619's English description until 2026-09-25
DICALCIUM_PHOSPHATE = {
    "CID": CID, "MolecularFormula": "CaHPO4", "MolecularWeight": "136.06",
    "SMILES": "OP(=O)([O-])[O-].[Ca+2]", "ConnectivitySMILES": "OP(=O)([O-])[O-].[Ca+2]",
    "InChIKey": "FUFJGUQYACFECW-UHFFFAOYSA-L",
}


def _record(summary, *, qid=QID, prior=None) -> dict:
    row = canon_row(CID, "Dicalcium phosphate", qid=qid, summary=summary)
    return assemble.assemble_record(row, fetched(DICALCIUM_PHOSPHATE), set(), prior=prior)


def _live(monkeypatch) -> None:
    """The Sep 28 run fetched Wikidata live, so the guard's freshness clause cannot excuse it."""
    live = {source: {str(CID): {"fetched_at": cache.now(), "live": True}}
            for source in freshness.SOURCES}
    monkeypatch.setattr(freshness, "load", lambda path=None: live)


def _plant(tmp_path, rec) -> None:
    mol = tmp_path / "molecules"
    mol.mkdir(parents=True, exist_ok=True)
    (mol / f"{rec['slug']}.json").write_text(json.dumps(rec))


# ── assembly ────────────────────────────────────────────────────────────────
def test_the_same_item_edited_to_the_placeholder_keeps_its_shipped_summary(caplog):
    shipped = _record(SHIPPED)
    caplog.set_level("INFO", logger="mfetl")
    rec = _record("chemical compound", prior=shipped)
    assert rec["slug"] == "dicalcium-phosphate"
    assert rec["summary"] == SHIPPED
    assert rec["summary_source"] == shipped["summary_source"]      # still Wikidata's own text
    assert "dicalcium-phosphate" in caplog.text and QID in caplog.text   # the run log says so


def test_any_spelling_of_the_placeholder_counts():
    shipped = _record(SHIPPED)
    for spelling in ("Chemical compound.", " chemical compound ", "CHEMICAL COMPOUND"):
        assert _record(spelling, prior=shipped)["summary"] == SHIPPED


def test_a_real_new_description_replaces_the_shipped_one():
    """Only the placeholder is held back. Wikidata improving (or just rewording) a real
    description flows through like any other refresh."""
    rec = _record("calcium phosphate used as a dietary supplement and abrasive",
                  prior=_record(SHIPPED))
    assert rec["summary"] == "calcium phosphate used as a dietary supplement and abrasive"


def test_a_placeholder_from_a_different_item_is_left_to_the_guard():
    """One CID, two items, the placeholder one won: the 2026-09-09 shape. The old item's text
    must not be pinned onto a new QID, so the record carries the placeholder and the guard
    stops the run for a person (next section)."""
    rec = _record("chemical compound", qid="Q106345999", prior=_record(SHIPPED))
    assert rec["summary"] == "chemical compound"


def test_a_molecule_that_shipped_the_placeholder_keeps_getting_it():
    shipped = _record("chemical compound")
    assert _record("chemical compound", prior=shipped)["summary"] == "chemical compound"


def test_no_prior_takes_the_row_as_it_is():
    assert _record("chemical compound")["summary"] == "chemical compound"
    assert _record(None)["summary"] is None and _record(None)["summary_source"] is None


def test_a_row_without_a_qid_is_not_the_same_item():
    shipped = _record(SHIPPED, qid=None)
    assert _record("chemical compound", qid=None, prior=shipped)["summary"] == "chemical compound"


def test_one_placeholder_question_for_everyone():
    """Item selection, assembly and the guard ask the same predicate."""
    assert snapshot_guard._is_placeholder is wikidata.is_placeholder
    assert assemble.is_placeholder is wikidata.is_placeholder
    assert wikidata.is_placeholder("Chemical compound.")
    assert not wikidata.is_placeholder(SHIPPED)
    assert not wikidata.is_placeholder(None) and not wikidata.is_placeholder("")


# ── end to end: the Sep 28 export ───────────────────────────────────────────
def test_the_2026_09_28_run_exports(tmp_path, monkeypatch):
    """The exact run that failed: live Wikidata, the same item, the placeholder. It now
    exports, and the page keeps the summary it had."""
    monkeypatch.delenv(snapshot_guard.OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    shipped = _record(SHIPPED)
    _plant(tmp_path, shipped)
    _live(monkeypatch)

    snapshot_export.export([_record("chemical compound", prior=shipped)], {})
    on_disk = json.loads((tmp_path / "molecules" / "dicalcium-phosphate.json").read_text())
    assert on_disk["summary"] == SHIPPED


def test_without_the_carry_the_guard_fails_the_run_as_it_did(tmp_path, monkeypatch):
    """Load-bearing check: the same record built without its prior is what Sep 28 exported,
    and the guard refuses it with the line from the run's log."""
    monkeypatch.delenv(snapshot_guard.OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    _plant(tmp_path, _record(SHIPPED))
    _live(monkeypatch)

    with pytest.raises(SnapshotRegression) as err:
        snapshot_export.export([_record("chemical compound")], {})
    assert ("dicalcium-phosphate (summary): 'chemical compound CaHPO₄' -> 'chemical compound'"
            in str(err.value))


def test_a_different_item_with_the_placeholder_still_stops_the_run(tmp_path, monkeypatch):
    monkeypatch.delenv(snapshot_guard.OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    shipped = _record(SHIPPED)
    _plant(tmp_path, shipped)
    _live(monkeypatch)

    with pytest.raises(SnapshotRegression, match=r"dicalcium-phosphate \(summary\)"):
        snapshot_export.export([_record("chemical compound", qid="Q106345999", prior=shipped)], {})
    on_disk = json.loads((tmp_path / "molecules" / "dicalcium-phosphate.json").read_text())
    assert on_disk["summary"] == SHIPPED                       # nothing was written
