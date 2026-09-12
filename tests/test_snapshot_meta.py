"""The snapshot date behind "Data refreshed" moves when the data moves, and only then.

The web shows it on every molecule page (feedback triage MF-9). A date stamped on every run
would change a committed file every week, which would open a data PR, spend a Vercel build and
deploy the site to say nothing new: the churn run 3 removed. So a run that exports identical
content must leave meta.json, and therefore the whole snapshot, byte-identical.
"""
from __future__ import annotations

import json

from moleculefinder_etl import freshness
from moleculefinder_etl.load import snapshot_export


def _records() -> list[dict]:
    return [
        {"cid": 2519, "slug": "caffeine", "title": "Caffeine", "wikidata_qid": "Q60235",
         "summary": "central nervous system stimulant", "ld50_mg_per_kg": 192.0,
         "molecular_formula": "C8H10N4O2", "synonyms": []},
        {"cid": 5429, "slug": "theobromine", "title": "Theobromine", "wikidata_qid": "Q407118",
         "summary": "bitter alkaloid of the cacao plant", "ld50_mg_per_kg": 950.0,
         "molecular_formula": "C7H8N4O2", "synonyms": []},
    ]


def _meta(tmp_path) -> dict:
    return json.loads((tmp_path / snapshot_export.META).read_text())


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    monkeypatch.setattr(freshness, "load", lambda path=None: {})


def test_a_first_export_stamps_the_date(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    snapshot_export.export(_records(), {}, today="2026-09-12")
    assert _meta(tmp_path) == {"refreshed": "2026-09-12"}


def test_an_unchanged_export_keeps_the_date_and_every_byte(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    snapshot_export.export(_records(), {}, today="2026-09-12")
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*.json")}

    snapshot_export.export(_records(), {}, today="2026-09-19")      # a quiet week

    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*.json")}
    assert after == before
    assert _meta(tmp_path) == {"refreshed": "2026-09-12"}


def test_a_changed_record_moves_the_date(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    snapshot_export.export(_records(), {}, today="2026-09-12")
    recs = _records()
    recs[0]["synonyms"] = ["Caffeine", "Guaranine"]
    snapshot_export.export(recs, {}, today="2026-09-14")
    assert _meta(tmp_path) == {"refreshed": "2026-09-14"}


def test_a_removed_molecule_moves_the_date(tmp_path, monkeypatch):
    """A pruned file is a content change even when every written file is unchanged."""
    _setup(tmp_path, monkeypatch)
    snapshot_export.export(_records(), {}, today="2026-09-12")
    snapshot_export.export(_records()[:1], {}, today="2026-09-14")
    assert _meta(tmp_path) == {"refreshed": "2026-09-14"}
    assert not (tmp_path / "molecules" / "theobromine.json").exists()


def test_a_snapshot_from_before_the_date_existed_gets_one(tmp_path, monkeypatch):
    """The first run after this change: identical content, but no meta.json yet."""
    _setup(tmp_path, monkeypatch)
    snapshot_export.export(_records(), {}, today="2026-09-12")
    (tmp_path / snapshot_export.META).unlink()
    snapshot_export.export(_records(), {}, today="2026-09-19")
    assert _meta(tmp_path) == {"refreshed": "2026-09-19"}


def test_a_corrupt_meta_file_is_replaced_not_crashed_on(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    snapshot_export.export(_records(), {}, today="2026-09-12")
    (tmp_path / snapshot_export.META).write_text("{not json")
    snapshot_export.export(_records(), {}, today="2026-09-19")
    assert _meta(tmp_path) == {"refreshed": "2026-09-19"}
