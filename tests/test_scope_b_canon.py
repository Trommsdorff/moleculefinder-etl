"""The Scope B everyday-core canon: build_scope_b_canon reads scope_b_core.csv and
becomes the canon *input* (each row stamped with its bucket), replacing the open
notability net for the everyday-core build. Also covers the parquet round-trip of the
Scope B fields so stage_transform can read them straight off the canon row.

Counts are asserted as "original core + the tranches on top" rather than one frozen
number, because catalog growth (build plan phase 4) adds a tagged block per tranche and
a bare `== 498` turns every future tranche into a test failure that says nothing.
"""
from __future__ import annotations

from moleculefinder_etl.transform import canon


# The everyday core as it shipped: 489 Scope B + 9 pungent/stinky board additions.
ORIGINAL_CORE = 498
# Catalog-growth tranches, newest last. Each is a `batch`-tagged block in the CSV.
TRANCHES = {"2026-09-A": 295}


def _csv_rows():
    import csv
    with canon.SCOPE_B_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_scope_b_csv_is_present_and_shaped():
    assert canon.SCOPE_B_CSV.exists(), "scope_b_core.csv must live in sources/seeds/"
    rows = canon._scope_b_rows()
    assert len(rows) == ORIGINAL_CORE + sum(TRANCHES.values())
    # Every row carries a bucket (the primary color/roam dimension).
    assert all(r["scope_bucket"] for r in rows)
    # Only buckets the label table knows: an unlabeled bucket ships an /in/ page titled
    # with a raw slug and colored --bucket-none.
    from moleculefinder_etl.transform.buckets import BUCKET_LABELS
    assert {r["scope_bucket"] for r in rows} <= set(BUCKET_LABELS)


def test_every_tranche_row_is_batch_tagged_and_the_core_is_not():
    """Provenance: a molecule must say which tranche it arrived in, and the original
    core must stay untagged, so a bad tranche can be found and lifted back out."""
    raw = _csv_rows()
    untagged = [r for r in raw if not (r.get("batch") or "").strip()]
    assert len(untagged) == ORIGINAL_CORE
    for name, count in TRANCHES.items():
        assert len([r for r in raw if (r.get("batch") or "").strip() == name]) == count
    # No CID appears twice, in either direction: a tranche must be de-duplicated against
    # the core before it is appended.
    cids = [r["pubchem_cid"] for r in raw if r["pubchem_cid"].strip()]
    assert len(cids) == len(set(cids))
    assert len({r["molecule"] for r in raw}) == len(raw)


def test_batch_rides_the_canon_row():
    rows = {r["enwiki_title"]: r for r in canon._scope_b_rows()}
    assert rows["Limonene"]["batch"] is None          # original core
    assert rows["Gabapentin"]["batch"] == "2026-09-A"  # tranche 1


def test_scope_b_hand_model_rows_get_synthetic_cids():
    rows = canon._scope_b_rows()
    hand = [r for r in rows if r["hand_model"]]
    real = [r for r in rows if not r["hand_model"]]
    assert len(hand) == 18, "18 hand-modeled macromolecules (collagen, starch, gluten...)"
    assert all(r["cid"] < 0 for r in hand)            # synthetic negatives
    assert all(r["cid"] > 0 for r in real)            # real PubChem CIDs
    # Synthetic CIDs match those the household YAML seed derives from the same names,
    # so the hand-model meta (family/bucket) resolves in stage_transform.
    seed_by_cid = {m["cid"]: m for m in canon.household_seed()}
    for r in hand:
        assert r["cid"] in seed_by_cid


def test_build_scope_b_canon_ranks_and_orders(monkeypatch):
    monkeypatch.setattr(canon, "_descriptions_cached", lambda cids: {})  # no network
    rows = canon.build_scope_b_canon()
    assert len(rows) == ORIGINAL_CORE + sum(TRANCHES.values())
    # Ranked by descending Wikipedia pageviews, build_order following the rank.
    assert all(rows[i]["pageviews"] >= rows[i + 1]["pageviews"] for i in range(len(rows) - 1))
    assert [r["build_order"] for r in rows] == list(range(len(rows)))
    assert all(r["tier"] == "marquee" for r in rows)    # curated ⇒ never truncated


def test_scope_bucket_survives_the_parquet_roundtrip(tmp_path):
    rows = [
        {"cid": 22311, "tier": "marquee", "build_order": 0, "has_common_name": True,
         "wikidata_qid": None, "enwiki_title": "Limonene", "summary": None, "pageviews": 1091998,
         "hand_model": False, "scope_bucket": "scent-aroma", "scope_family": "terpene",
         "is_otc": False, "dual_use": False},
        {"cid": -7, "tier": "marquee", "build_order": 1, "has_common_name": True,
         "wikidata_qid": None, "enwiki_title": "Starch", "summary": None, "pageviews": 0,
         "hand_model": True, "scope_bucket": "food-flavor", "scope_family": "polysaccharide",
         "is_otc": False, "dual_use": False},
    ]
    back = {int(r["cid"]): r for r in canon.read_parquet(canon.write_parquet(rows, tmp_path / "c.parquet"))}
    assert back[22311]["scope_bucket"] == "scent-aroma" and back[22311]["scope_family"] == "terpene"
    assert back[-7]["scope_bucket"] == "food-flavor" and bool(back[-7]["hand_model"]) is True
