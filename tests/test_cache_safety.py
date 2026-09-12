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


def _regressed(*, placeholder: bool = True) -> list[dict]:
    """The same four as the stale cache rebuilt them: the actual values that shipped.

    ``placeholder=False`` leaves taurine's summary alone, for the tests about the two shapes
    a live fetch is allowed to change; the placeholder summary is refused whatever the
    provenance and has its own test below.
    """
    recs = {r["slug"]: dict(r) for r in _shipped()}
    recs["alanine"]["wikidata_qid"] = "Q106345485"          # a bulk-batch item
    recs["glycine"]["wikidata_qid"] = "Q106345678"
    recs["taurine"]["wikidata_qid"] = "Q106345481"
    if placeholder:
        recs["taurine"]["summary"] = "chemical compound"    # phase 1 exists to remove this
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
    """The weekly CI run fetches fresh, so its QID and LD50 corrections must sail through.
    This is the diff above minus the placeholder summary, which no provenance excuses
    (see the next test); only the provenance of the values differs."""
    monkeypatch.delenv(snapshot_guard.OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    _plant_prior(tmp_path)
    live = {source: {str(cid): {"fetched_at": cache.now(), "live": True} for cid in CIDS}
            for source in freshness.SOURCES}
    monkeypatch.setattr(freshness, "load", lambda path=None: live)

    snapshot_export.export(_regressed(placeholder=False), {})
    taurine = json.loads((tmp_path / "molecules" / "taurine.json").read_text())
    assert taurine["wikidata_qid"] == "Q106345481"
    omeprazole = json.loads((tmp_path / "molecules" / "omeprazole.json").read_text())
    assert omeprazole["ld50_mg_per_kg"] is None


def test_a_placeholder_summary_is_refused_even_when_the_fetch_is_live(tmp_path, monkeypatch):
    """Fresh is not the same as right. On 2026-09-09 a live WDQS query wanted to write
    "chemical compound" over fluorine, mercury and vasopressin, and the live-fetch rule would
    have let it through. The placeholder is refused whatever its provenance, including the
    capitalized, punctuated spelling."""
    monkeypatch.delenv(snapshot_guard.OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    _plant_prior(tmp_path)
    live = {source: {str(cid): {"fetched_at": cache.now(), "live": True} for cid in CIDS}
            for source in freshness.SOURCES}
    monkeypatch.setattr(freshness, "load", lambda path=None: live)
    recs = {r["slug"]: dict(r) for r in _shipped()}
    recs["taurine"]["summary"] = "Chemical compound."

    with pytest.raises(SnapshotRegression) as err:
        snapshot_export.export(list(recs.values()), {})

    message = str(err.value)
    assert "taurine (summary):" in message
    assert "fetched live" in message and "refused even when fetched live" in message
    assert not (tmp_path / "index.json").exists()                # nothing was written
    on_disk = json.loads((tmp_path / "molecules" / "taurine.json").read_text())
    assert on_disk["summary"] == "organic compound widely distributed in animal tissues"


def test_a_placeholder_summary_on_a_molecule_that_always_had_one_is_not_a_regression(tmp_path, monkeypatch):
    """The rule protects a real summary from being walked back, and nothing more: a record
    whose shipped summary was already the placeholder can keep it."""
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    prior = [dict(r, summary="chemical compound") if r["slug"] == "taurine" else r for r in _shipped()]
    mol = tmp_path / "molecules"
    mol.mkdir(parents=True)
    for rec in prior:
        (mol / f"{rec['slug']}.json").write_text(json.dumps(rec))
    monkeypatch.setattr(freshness, "load", lambda path=None: {})
    snapshot_export.export(prior, {})
    assert (tmp_path / "index.json").exists()


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


# ── The Wikidata query must not outgrow its own request ─────────────────────
# The descriptions query inlines one VALUES entry per CID, so its LENGTH is the size of the
# catalog. Sent as a GET it lives in the URL, and WDQS answers HTTP 414 URI Too Long above
# roughly 612 CIDs. The catalog passed that in run 2 (498 -> 788), so from 2026-09-09 every
# Wikidata refresh failed, logged one warning, and reported success. These pin the shape
# that cannot come back.

def _capture_request(monkeypatch):
    """Record the outgoing WDQS request instead of sending it."""
    from moleculefinder_etl.sources import wikidata
    seen: dict = {}

    class Resp:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"results": {"bindings": []}}

    def post(url, data=None, headers=None, timeout=None, **kw):
        seen.update(method="POST", url=url, body=data, headers=headers or {})
        return Resp()

    def get(url, params=None, headers=None, timeout=None, **kw):
        seen.update(method="GET", url=url, params=params or {}, headers=headers or {})
        return Resp()

    monkeypatch.setattr(wikidata.requests, "post", post)
    monkeypatch.setattr(wikidata.requests, "get", get)
    return wikidata, seen


def test_a_900_cid_query_is_built_as_a_post(monkeypatch):
    """The whole point: the query goes in the BODY, so its length has no URL ceiling."""
    wikidata, seen = _capture_request(monkeypatch)
    cids = list(range(1, 901))

    wikidata.descriptions_for_cids(cids)

    assert seen["method"] == "POST"
    query = seen["body"]["query"]
    assert "VALUES ?cid" in query
    assert '"1"' in query and '"900"' in query          # every CID made it into the body
    # 900 quoted values plus the template's own "en" language filter.
    assert query.count('"') == 900 * 2 + 2              # nothing dropped
    # And the URL carries none of it: the request line is the bare endpoint, which is
    # what makes the 414 unreachable. (The endpoint host is literally "query.wikidata.org",
    # so test the URL for equality, not for the absence of the word "query".)
    assert seen["url"] == wikidata.WDQS_ENDPOINT
    assert "params" not in seen
    assert len(query) > 4757                            # past where the GET form broke
    assert seen["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


def test_the_whole_catalog_would_have_broken_the_get_form(monkeypatch):
    """A guard on the reasoning, not just the code.

    Note what the ceiling is actually made of: CHARACTERS, not CIDs. The measured break was
    612 *real* CIDs, which are 4 to 8 digits each; 612 two-digit CIDs would have fit. So the
    invariant worth pinning is that a catalog-sized query in realistic CIDs exceeds the
    length at which the GET form was observed to fail.
    """
    wikidata, _ = _capture_request(monkeypatch)
    catalog = [2519 + i * 137 for i in range(770)]      # 770 CIDs of realistic magnitude
    query = wikidata.DESCRIPTIONS_BY_CID_SPARQL % " ".join(f'"{c}"' for c in catalog)
    assert len(query) > 4757                            # measured GET ceiling, at 612 CIDs


def test_an_empty_cid_list_sends_no_request(monkeypatch):
    wikidata, seen = _capture_request(monkeypatch)
    assert wikidata.descriptions_for_cids([]) == {}
    assert seen == {}


def test_a_failed_wikidata_query_fails_the_run(tmp_path, monkeypatch):
    """A silent skip is how the 414 stayed hidden for a whole deploy cycle."""
    from moleculefinder_etl.transform import canon
    from moleculefinder_etl.sources import wikidata
    canon_mod, _ = _redirect_caches(monkeypatch, tmp_path)
    monkeypatch.setattr(canon_mod, "WIKIDATA_CACHE_TTL_DAYS", 7)
    monkeypatch.delenv(canon.ALLOW_STALE_WIKIDATA_ENV, raising=False)

    def boom(cids):
        raise RuntimeError("414 Client Error: URI Too Long")

    monkeypatch.setattr(canon_mod.wikidata, "descriptions_for_cids", boom)
    with pytest.raises(wikidata.WikidataQueryError) as err:
        canon_mod._descriptions_cached([5950])
    message = str(err.value)
    assert "RuntimeError: 414 Client Error: URI Too Long" in message   # class AND message
    assert canon.ALLOW_STALE_WIKIDATA_ENV in message                   # says how to proceed


def test_the_stale_override_downgrades_it_to_a_warning(tmp_path, monkeypatch, caplog):
    """The old behaviour stays reachable for a deliberately offline run, and the values it
    keeps are still marked not-live, so the export guard still refuses a regression."""
    from moleculefinder_etl.transform import canon
    canon_mod, _ = _redirect_caches(monkeypatch, tmp_path)
    monkeypatch.setattr(canon_mod, "WIKIDATA_CACHE_TTL_DAYS", 7)
    monkeypatch.setenv(canon.ALLOW_STALE_WIKIDATA_ENV, "1")

    def boom(cids):
        raise RuntimeError("WDQS timeout")

    monkeypatch.setattr(canon_mod.wikidata, "descriptions_for_cids", boom)
    with caplog.at_level("WARNING"):
        canon_mod._descriptions_cached([5950])
    assert "RuntimeError: WDQS timeout" in caplog.text
    assert not freshness.is_live(freshness.load(tmp_path / "freshness.json"),
                                 freshness.WIKIDATA, 5950)


# ── One PubChem CID, several Wikidata items ─────────────────────────────────
# 70 of the catalog's 769 CIDs carry two items with the same P662: the element and its
# allotrope, the hormone and the compound. "First binding wins" therefore picked whatever
# order WDQS returned, and that order had already moved for 15 of them by 2026-09-09.

def test_a_real_description_beats_the_placeholder():
    """fluorine: Q650 'chemical element...' vs Q81978300 'chemical compound'."""
    from moleculefinder_etl.sources.wikidata import _choose_item
    chosen = _choose_item([("Q81978300", "chemical compound"),
                           ("Q650", "chemical element with symbol F and atomic number 9")])
    assert chosen["qid"] == "Q650"


def test_the_placeholder_loses_whichever_order_it_arrives_in():
    from moleculefinder_etl.sources.wikidata import _choose_item
    items = [("Q925", "chemical element with symbol Hg and atomic number 80"),
             ("Q6818555", "chemical compound")]
    assert _choose_item(items)["qid"] == _choose_item(list(reversed(items)))["qid"] == "Q925"


def test_the_older_item_wins_when_both_descriptions_are_real():
    """carbon: the element Q623, not the 'pure substance' item Q866179."""
    from moleculefinder_etl.sources.wikidata import _choose_item
    assert _choose_item([("Q866179", "pure substance"),
                         ("Q623", "chemical element with symbol C")])["qid"] == "Q623"


def test_qids_sort_numerically_not_as_strings():
    """The whole rule turns on this: as strings, 'Q6818555' < 'Q925'."""
    from moleculefinder_etl.sources.wikidata import _qid_sort_key
    assert _qid_sort_key("Q925") < _qid_sort_key("Q6818555")
    assert _qid_sort_key("Q674") < _qid_sort_key("Q106345485")   # the bulk-batch shape


def test_a_bulk_batch_item_never_wins_against_a_real_one():
    """The 2026-09-08 regression in miniature: Q106345xxx must not displace Q218642."""
    from moleculefinder_etl.sources.wikidata import _choose_item
    assert _choose_item([("Q106345485", "chemical compound"),
                         ("Q218642", "alpha-amino acid")])["qid"] == "Q218642"


def test_a_lone_placeholder_is_still_returned():
    """Where the placeholder is all Wikidata has, it is the answer; the description
    builder falls back to the curated line anyway."""
    from moleculefinder_etl.sources.wikidata import _choose_item
    assert _choose_item([("Q2462", "chemical compound")]) == {"qid": "Q2462", "desc": "chemical compound"}


def test_an_item_with_no_description_is_not_preferred_over_one_with_a_real_one():
    from moleculefinder_etl.sources.wikidata import _choose_item
    assert _choose_item([("Q1", None), ("Q9999", "a real description")])["qid"] == "Q9999"


def test_selection_is_stable_under_reordering(monkeypatch):
    """End to end through descriptions_for_cids: WDQS row order must not reach the record."""
    from moleculefinder_etl.sources import wikidata
    monkeypatch.setattr(wikidata, "names_for_qids", lambda qids: {})     # stay offline
    rows = [{"cid": "5462309", "compound": "http://www.wikidata.org/entity/Q457556",
             "desc": "allotrope of phosphorus"},
            {"cid": "5462309", "compound": "http://www.wikidata.org/entity/Q674",
             "desc": "chemical element with symbol P and atomic number 15"}]
    for order in (rows, list(reversed(rows))):
        monkeypatch.setattr(wikidata, "sparql", lambda *a, **k: order)
        out = wikidata.descriptions_for_cids([5462309])
        assert out[5462309]["qid"] == "Q674"
        assert out[5462309]["desc"].startswith("chemical element")
