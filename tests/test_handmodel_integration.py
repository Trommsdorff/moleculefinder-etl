"""Integration: a mixed record set (real molecule + hand-modeled macromolecules) must
survive the full downstream — similarity edges, leaderboards, snapshot export and the
roam layout — without a crash and without a fabricated structure leaking onto a board.
"""
from __future__ import annotations

import json

from moleculefinder_etl.transform import assemble, leaderboards, roam_layout
from moleculefinder_etl.load import snapshot_export


def _mixed_records():
    caffeine = assemble.assemble_record(
        {"cid": 2519, "tier": "marquee", "enwiki_title": "Caffeine", "pageviews": 49000},
        {"props": {"SMILES": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
                   "MolecularFormula": "C8H10N4O2", "MolecularWeight": "194.19"},
         "synonyms": ["Caffeine"], "curated": None,
         "toxicity": [{"endpoint": "LD50", "species": "rat", "route": "oral",
                       "value_num": 192.0, "unit": "mg/kg", "confidence": "from_source"}],
         "ghs": None}, set())
    collagen = assemble.assemble_handmodel(
        {"cid": -101, "tier": "marquee", "enwiki_title": "Collagen", "pageviews": 51000, "summary": None},
        {"name": "Collagen", "bucket": "body-endogenous", "family": "protein"}, set())
    starch = assemble.assemble_handmodel(
        {"cid": -102, "tier": "marquee", "enwiki_title": "Starch", "pageviews": 40000, "summary": None},
        {"name": "Starch", "bucket": "food-flavor", "family": "polysaccharide"}, set())
    recs = [caffeine, collagen, starch]
    assemble.attach_edges(recs)
    return recs


def test_handmodel_absent_from_every_leaderboard():
    recs = _mixed_records()
    for board in leaderboards.BOARDS:
        entries = leaderboards.rank(board, recs)["entries"]
        slugs = {e["slug"] for e in entries}
        assert "collagen" not in slugs and "starch" not in slugs, f"macromolecule leaked onto {board}"
    # the real molecule still ranks where it has data (caffeine has an LD50)
    assert any(e["slug"] == "caffeine" for e in leaderboards.rank("deadliest", recs)["entries"])


def test_snapshot_export_writes_structureless_pages(tmp_path, monkeypatch):
    recs = _mixed_records()
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    boards = {slug: leaderboards.rank(slug, recs) for slug in leaderboards.BOARDS}
    snapshot_export.export(recs, boards)

    collagen = json.loads((tmp_path / "molecules" / "collagen.json").read_text())
    assert collagen["hand_model"] is True and collagen["macromolecule"] is True
    assert collagen["structure_svg"] is None and collagen["molecular_formula"] is None
    assert collagen["scope_bucket"] == "body-endogenous"

    # the search index entry exists and simply has a null formula (no crash, no fake value)
    index = json.loads((tmp_path / "index.json").read_text())
    entry = next(e for e in index if e["slug"] == "collagen")
    assert entry["formula"] is None
    # roam map baked without error
    assert (tmp_path / "roam.json").exists()


def test_roam_layout_survives_handmodel():
    recs = _mixed_records()
    roam = roam_layout.build_roam(recs)   # must not raise on family=None / edge-less nodes
    assert roam is not None
