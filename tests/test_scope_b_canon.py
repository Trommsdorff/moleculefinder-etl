"""The Scope B everyday-core canon: build_scope_b_canon reads scope_b_core.csv and
becomes the canon *input* (each of the 489 stamped with its bucket), replacing the
open notability net for the everyday-core build. Also covers the parquet round-trip of
the Scope B fields so stage_transform can read them straight off the canon row.
"""
from __future__ import annotations

from moleculefinder_etl.transform import canon


def test_scope_b_csv_is_present_and_shaped():
    assert canon.SCOPE_B_CSV.exists(), "scope_b_core.csv must live in sources/seeds/"
    rows = canon._scope_b_rows()
    # 489 everyday core + 9 pungent/stinky compounds added for the spiciest + Most pungent boards.
    assert len(rows) == 498, "the everyday core is 489 + 9 pungent/stinky additions = 498"
    # Every row carries a bucket (the primary color/roam dimension).
    assert all(r["scope_bucket"] for r in rows)
    # The 8 Scope B buckets, nothing else.
    from moleculefinder_etl.transform.buckets import BUCKET_LABELS
    assert {r["scope_bucket"] for r in rows} <= set(BUCKET_LABELS)


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
    assert len(rows) == 498
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
