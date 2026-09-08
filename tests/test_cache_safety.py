"""A stale cache must not be able to ship worse data than the snapshot already holds.

On 2026-09-08 this machine's ``data/raw_cache`` predated a Wikidata refresh. ``mfetl all``
read it, could not tell a cache hit from a fetch, and wrote 26 molecules backwards into the
snapshot it shipped: 22 ``wikidata_qid`` replaced by bulk-batch items, 11 ``summary`` back
to the placeholder "chemical compound", and omeprazole's oral LD50 nulled. The weekly loop
fetched fresh and corrected all 26 within four minutes, but nothing in the run had refused
the bad write.

Two mechanisms, tested here:

* ``sources.cache`` — every entry records when it was fetched, and the derived sources
  (Wikidata, PUG-View) stop hitting once an entry is older than its expiry. An entry
  written before dates existed is unknown-age, and unknown age is never fresh.
* ``load.snapshot_guard`` — the backstop. ``replay`` below is the real incident, with the
  real values, and it must not be exportable.
"""
from __future__ import annotations

import json

import pytest

from moleculefinder_etl import freshness
from moleculefinder_etl.load import snapshot_export, snapshot_guard
from moleculefinder_etl.load.snapshot_guard import SnapshotRegression
from moleculefinder_etl.sources import cache

DAY = 86400


def _stamp(days_ago: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(cache.STAMP)


# ── The envelope ────────────────────────────────────────────────────────────
def test_a_cache_entry_records_when_it_was_fetched():
    e = cache.unwrap(cache.wrap({"desc": "amino acid"}))
    assert e.value == {"desc": "amino acid"} and cache.parse(e.fetched_at) is not None


def test_an_undated_entry_is_never_fresh():
    """The entries that caused the incident are exactly the ones whose age nobody knew."""
    legacy = cache.unwrap({"desc": "chemical compound"})       # written before the envelope
    assert legacy.fetched_at is None
    assert not cache.is_fresh(legacy.fetched_at, max_age_days=365)


def test_an_entry_expires():
    assert cache.is_fresh(_stamp(6), max_age_days=7)
    assert not cache.is_fresh(_stamp(8), max_age_days=7)


def test_a_zero_expiry_disables_the_cache():
    assert not cache.is_fresh(cache.now(), max_age_days=0)


def test_read_json_is_a_miss_once_the_entry_is_stale(tmp_path):
    path = tmp_path / "descriptions.json"
    cache.write_json(path, {"qid": "Q218642"}, fetched_at=_stamp(30))
    assert cache.read_json(path, max_age_days=7) is None            # expired -> refetch
    assert cache.read_json(path, max_age_days=60).value == {"qid": "Q218642"}


def test_a_live_fetch_is_marked_live_and_a_hit_is_not(tmp_path):
    path = tmp_path / "4594-Toxicity.json"
    assert cache.write_json(path, {"Record": {}}).live is True
    assert cache.read_json(path, max_age_days=7).live is False


def test_a_legacy_file_reads_back_and_is_treated_as_stale(tmp_path):
    """Migration: the old shape is adopted, not crashed on, and not reused."""
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"Record": {"Section": []}}))
    assert cache.read_json(path, max_age_days=365) is None
    assert cache.unwrap(json.loads(path.read_text())).value == {"Record": {"Section": []}}


def test_a_corrupt_entry_is_a_miss_not_a_crash(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json")
    assert cache.read_json(path, max_age_days=7) is None


# ── The 2026-09-08 regression, replayed ─────────────────────────────────────
def _shipped() -> list[dict]:
    """The four records as they were correct in the snapshot before the bad run."""
    return [
        {"cid": 5950, "slug": "alanine", "title": "Alanine", "wikidata_qid": "Q218642",
         "summary": "alpha-amino acid used in the biosynthesis of proteins",
         "ld50_mg_per_kg": None, "molecular_formula": "C3H7NO2", "synonyms": []},
        {"cid": 750, "slug": "glycine", "title": "Glycine", "wikidata_qid": "Q620730",
         "summary": "simplest amino acid, with a hydrogen atom as its side chain",
         "ld50_mg_per_kg": 7930.0, "molecular_formula": "C2H5NO2", "synonyms": []},
        {"cid": 1123, "slug": "taurine", "title": "Taurine", "wikidata_qid": "Q207051",
         "summary": "organic compound widely distributed in animal tissues",
         "ld50_mg_per_kg": None, "molecular_formula": "C2H7NO3S", "synonyms": []},
        {"cid": 4594, "slug": "omeprazole", "title": "Omeprazole", "wikidata_qid": "Q422210",
         "summary": "medication used in the treatment of gastroesophageal reflux disease",
         "ld50_mg_per_kg": 4000.0, "molecular_formula": "C17H19N3O3S", "synonyms": []},
    ]


def _regressed() -> list[dict]:
    """The same four as the stale cache rebuilt them: the actual values that shipped."""
    recs = {r["slug"]: dict(r) for r in _shipped()}
    recs["alanine"]["wikidata_qid"] = "Q106345485"          # a bulk-batch item
    recs["glycine"]["wikidata_qid"] = "Q106345678"
    recs["taurine"]["wikidata_qid"] = "Q106345481"
    recs["taurine"]["summary"] = "chemical compound"        # phase 1 exists to remove this
    recs["omeprazole"]["ld50_mg_per_kg"] = None             # PUG-View miss, cached
    return list(recs.values())


def _plant_prior(tmp_path) -> None:
    mol = tmp_path / "molecules"
    mol.mkdir(parents=True, exist_ok=True)
    for rec in _shipped():
        (mol / f"{rec['slug']}.json").write_text(json.dumps(rec))


def _cached(slugs_to_cids, days_ago: float = 9.0) -> dict:
    """A freshness map in which nothing was fetched live: every value is a cache hit."""
    stamp = _stamp(days_ago)
    return {source: {str(cid): {"fetched_at": stamp, "live": False} for cid in slugs_to_cids}
            for source in freshness.SOURCES}


CIDS = [5950, 750, 1123, 4594]


def test_the_2026_09_08_regression_is_rejected(tmp_path, monkeypatch):
    """The whole incident, replayed. Export must refuse, and refuse before writing."""
    monkeypatch.delenv(snapshot_guard.OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    _plant_prior(tmp_path)
    monkeypatch.setattr(freshness, "load", lambda path=None: _cached(CIDS))

    with pytest.raises(SnapshotRegression) as err:
        snapshot_export.export(_regressed(), {})

    message = str(err.value)
    # All 26 shapes are these three; every one of them is named.
    assert "alanine (wikidata_qid): 'Q218642' -> 'Q106345485'" in message
    assert "taurine (summary):" in message and "chemical compound" in message
    assert "omeprazole (ld50_mg_per_kg): 4000.0 -> None" in message
    assert "cache hit written" in message                    # says WHY, not just what

    # And nothing was written: the good snapshot is still on disk, whole.
    assert not (tmp_path / "index.json").exists()
    for rec in _shipped():
        on_disk = json.loads((tmp_path / "molecules" / f"{rec['slug']}.json").read_text())
        assert on_disk == rec


def test_the_same_change_is_allowed_when_the_fetch_is_live(tmp_path, monkeypatch):
    """The weekly CI run fetches fresh, so its corrections must sail through. This is the
    same diff as the test above; only the provenance of the values differs."""
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    _plant_prior(tmp_path)
    live = {source: {str(cid): {"fetched_at": cache.now(), "live": True} for cid in CIDS}
            for source in freshness.SOURCES}
    monkeypatch.setattr(freshness, "load", lambda path=None: live)

    snapshot_export.export(_regressed(), {})
    taurine = json.loads((tmp_path / "molecules" / "taurine.json").read_text())
    assert taurine["wikidata_qid"] == "Q106345481"


def test_the_override_ships_it_and_says_so(tmp_path, monkeypatch, caplog):
    """A pipeline change that drops values on purpose must remain shippable."""
    monkeypatch.setenv(snapshot_guard.OVERRIDE_ENV, "1")
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    _plant_prior(tmp_path)
    monkeypatch.setattr(freshness, "load", lambda path=None: _cached(CIDS))

    with caplog.at_level("WARNING"):
        snapshot_export.export(_regressed(), {})
    assert (tmp_path / "index.json").exists()
    assert "omeprazole" in caplog.text and snapshot_guard.OVERRIDE_ENV in caplog.text


# ── What is NOT a regression ────────────────────────────────────────────────
def test_filling_a_null_is_not_a_regression(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    _plant_prior(tmp_path)
    monkeypatch.setattr(freshness, "load", lambda path=None: _cached(CIDS))
    recs = {r["slug"]: dict(r) for r in _shipped()}
    recs["alanine"]["ld50_mg_per_kg"] = 4800.0          # gained a value
    recs["taurine"]["summary"] = "an organic compound found in bile"   # improved
    snapshot_export.export(list(recs.values()), {})
    assert (tmp_path / "molecules" / "alanine.json").exists()


def test_a_qid_filled_where_there_was_none_is_not_a_regression(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    prior = [dict(r, wikidata_qid=None) for r in _shipped()]
    mol = tmp_path / "molecules"
    mol.mkdir(parents=True)
    for rec in prior:
        (mol / f"{rec['slug']}.json").write_text(json.dumps(rec))
    monkeypatch.setattr(freshness, "load", lambda path=None: _cached(CIDS))
    snapshot_export.export(_shipped(), {})
    assert json.loads((mol / "alanine.json").read_text())["wikidata_qid"] == "Q218642"


def test_a_new_molecule_regresses_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    _plant_prior(tmp_path)
    monkeypatch.setattr(freshness, "load", lambda path=None: {})
    new = _shipped() + [{"cid": 999, "slug": "novelene", "title": "Novelene",
                         "wikidata_qid": None, "summary": "chemical compound",
                         "ld50_mg_per_kg": None, "molecular_formula": "C1", "synonyms": []}]
    snapshot_export.export(new, {})
    assert (tmp_path / "molecules" / "novelene.json").exists()


def test_a_first_export_has_nothing_to_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    monkeypatch.setattr(freshness, "load", lambda path=None: {})
    snapshot_export.export(_regressed(), {})
    assert (tmp_path / "index.json").exists()


# ── The freshness map ───────────────────────────────────────────────────────
def test_the_freshness_map_merges_across_stages(tmp_path):
    """seed records Wikidata, transform records PUG-View, and neither erases the other."""
    path = tmp_path / "freshness.json"
    freshness.merge({freshness.WIKIDATA: {5950: {"fetched_at": cache.now(), "live": True}}}, path)
    freshness.merge({freshness.TOXICITY: {4594: {"fetched_at": cache.now(), "live": False}}}, path)
    data = freshness.load(path)
    assert freshness.is_live(data, freshness.WIKIDATA, 5950)
    assert not freshness.is_live(data, freshness.TOXICITY, 4594)


def test_an_input_this_run_never_touched_counts_as_not_fresh():
    """A partial re-run must not be able to launder a stale value into the snapshot."""
    assert not freshness.is_live({}, freshness.WIKIDATA, 5950)
    assert "no fetch recorded" in freshness.describe({}, freshness.WIKIDATA, 5950)


# ── The wiring, offline ─────────────────────────────────────────────────────
def _redirect_caches(monkeypatch, tmp_path):
    """Point both derived caches at a temp dir (the constants are read at call time)."""
    from moleculefinder_etl.transform import canon
    from moleculefinder_etl.sources import pubchem
    monkeypatch.setattr(canon, "RAW_CACHE", tmp_path)
    monkeypatch.setattr(canon, "DESCRIPTIONS_CACHE", tmp_path / "wikidata" / "descriptions.json")
    monkeypatch.setattr(pubchem, "RAW_CACHE", tmp_path)
    monkeypatch.setattr(freshness, "PATH", tmp_path / "freshness.json")
    return canon, pubchem


def test_wikidata_descriptions_refetch_once_the_entry_expires(tmp_path, monkeypatch):
    canon, _ = _redirect_caches(monkeypatch, tmp_path)
    monkeypatch.setattr(canon, "WIKIDATA_CACHE_TTL_DAYS", 7)
    calls: list[list[int]] = []

    def fake(cids):
        calls.append(sorted(cids))
        return {c: {"desc": "amino acid", "qid": "Q218642"} for c in cids}

    monkeypatch.setattr(canon.wikidata, "descriptions_for_cids", fake)

    out = canon._descriptions_cached([5950])
    assert out[5950]["qid"] == "Q218642" and calls == [[5950]]

    canon._descriptions_cached([5950])                     # fresh -> no second query
    assert calls == [[5950]]

    # Age the entry past the window: the next run must ask again rather than trust it.
    path = tmp_path / "wikidata" / "descriptions.json"
    stored = json.loads(path.read_text())
    stored["entries"]["5950"]["fetched_at"] = _stamp(30)
    path.write_text(json.dumps(stored))
    canon._descriptions_cached([5950])
    assert calls == [[5950], [5950]]


def test_a_wikidata_cache_hit_is_recorded_as_not_live(tmp_path, monkeypatch):
    """The signal the guard runs on, produced by the real code path."""
    canon, _ = _redirect_caches(monkeypatch, tmp_path)
    monkeypatch.setattr(canon, "WIKIDATA_CACHE_TTL_DAYS", 7)
    monkeypatch.setattr(canon.wikidata, "descriptions_for_cids",
                        lambda cids: {c: {"desc": "d", "qid": "Q1"} for c in cids})

    canon._descriptions_cached([5950])
    assert freshness.is_live(freshness.load(tmp_path / "freshness.json"), freshness.WIKIDATA, 5950)

    canon._descriptions_cached([5950])                     # second run: served from disk
    assert not freshness.is_live(freshness.load(tmp_path / "freshness.json"),
                                 freshness.WIKIDATA, 5950)


def test_a_legacy_descriptions_file_is_refetched_not_reused(tmp_path, monkeypatch):
    """The exact migration: the undated map on this machine is read, then replaced."""
    canon, _ = _redirect_caches(monkeypatch, tmp_path)
    monkeypatch.setattr(canon, "WIKIDATA_CACHE_TTL_DAYS", 7)
    path = tmp_path / "wikidata" / "descriptions.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"5950": {"desc": "chemical compound", "qid": "Q106345485"}}))
    monkeypatch.setattr(canon.wikidata, "descriptions_for_cids",
                        lambda cids: {c: {"desc": "alpha-amino acid", "qid": "Q218642"} for c in cids})

    out = canon._descriptions_cached([5950])
    assert out[5950]["qid"] == "Q218642"                   # the bulk-batch value is gone
    assert json.loads(path.read_text())[cache.ENVELOPE_KEY] == cache.ENVELOPE_VERSION


def test_a_failed_wikidata_query_keeps_the_cache_and_marks_it_not_live(tmp_path, monkeypatch):
    """A network failure must not silently look like a fresh fetch to the guard."""
    canon, _ = _redirect_caches(monkeypatch, tmp_path)
    monkeypatch.setattr(canon, "WIKIDATA_CACHE_TTL_DAYS", 7)

    def boom(cids):
        raise RuntimeError("WDQS timeout")

    monkeypatch.setattr(canon.wikidata, "descriptions_for_cids", boom)
    canon._descriptions_cached([5950])
    assert not freshness.is_live(freshness.load(tmp_path / "freshness.json"),
                                 freshness.WIKIDATA, 5950)


def test_pug_view_expires_and_reports_liveness(tmp_path, monkeypatch):
    _, pubchem = _redirect_caches(monkeypatch, tmp_path)
    monkeypatch.setattr(pubchem, "PUGVIEW_CACHE_TTL_DAYS", 30)
    monkeypatch.setattr(pubchem, "_throttle", lambda: None)
    hits = {"n": 0}

    class Resp:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            hits["n"] += 1
            return {"Record": {"Section": []}}

    monkeypatch.setattr(pubchem._session, "get", lambda *a, **k: Resp())

    first = pubchem.pug_view_dated(4594, "Toxicity")
    assert first.live is True and hits["n"] == 1
    assert pubchem.pug_view_dated(4594, "Toxicity").live is False and hits["n"] == 1

    path = tmp_path / "pubchem" / "4594-Toxicity.json"
    stored = json.loads(path.read_text())
    stored["fetched_at"] = _stamp(40)
    path.write_text(json.dumps(stored))
    assert pubchem.pug_view_dated(4594, "Toxicity").live is True and hits["n"] == 2


def test_pug_view_keeps_its_plain_signature_for_existing_callers(tmp_path, monkeypatch):
    _, pubchem = _redirect_caches(monkeypatch, tmp_path)
    monkeypatch.setattr(pubchem, "PUGVIEW_CACHE_TTL_DAYS", 30)
    cache.write_json(tmp_path / "pubchem" / "4594-Toxicity.json", {"Record": {"x": 1}})
    assert pubchem.pug_view(4594, "Toxicity") == {"Record": {"x": 1}}


def test_the_pubchem_property_and_synonym_caches_are_left_alone(tmp_path, monkeypatch):
    """Explicitly pinned: a CID's formula and name list are what that CID IS, so those
    caches keep no date and never expire. Only the derived sources do."""
    from moleculefinder_etl import pipeline
    monkeypatch.setattr(pipeline, "RAW_CACHE", tmp_path)
    calls: list[list[int]] = []

    def fetch(miss):
        calls.append(list(miss))
        return {c: {"CID": c, "MolecularFormula": "C8H10N4O2"} for c in miss}

    assert pipeline._fetch_cached([2519], "props", fetch)[2519]["MolecularFormula"] == "C8H10N4O2"
    raw = json.loads((tmp_path / "pubchem" / "props-2519.json").read_text())
    assert cache.ENVELOPE_KEY not in raw                    # no envelope, no expiry
    pipeline._fetch_cached([2519], "props", fetch)
    assert len(calls) == 1                                  # still a permanent hit
