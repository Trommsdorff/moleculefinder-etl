"""levonorgestrel, 2026-11-21: a live fetch reached the export guard as a cache hit, and a real
upstream LD50 removal would have stopped the weekly run. Two fixes, tested here:

* the liveness fix: the Toxicity answer ``stage_fetch`` fetched live is still live when
  ``stage_transform`` reads it back (``freshness.carried``), and only then;
* the hold: an LD50 a LIVE answer stops reporting keeps its shipped value until the removal is seen
  again on a live fetch at least 7 days later (``transform/ld50_hold.py``), and a cache hit is still
  refused by the guard.

The PUG-View records below are cut from PubChem's real answers for CID 13109 (saved 2026-11-21):
the 2026-10-21 answer carried HSDB record 3595 "NORGESTREL" with four LD50 rows; the 2026-11-21
answer carries only HSDB 6483 "LEVONORGESTREL" (no LD50) and T3DB's line, which no shape reads.
"""
from __future__ import annotations

import json

from moleculefinder_etl import freshness, pipeline
from moleculefinder_etl.load import snapshot_guard
from moleculefinder_etl.sources import cache, pubchem
from moleculefinder_etl.transform import ld50_hold, toxicity

CID = 13109


def _info(ref: int, text: str) -> dict:
    return {"ReferenceNumber": ref, "Value": {"StringWithMarkup": [{"String": text}]}}


def _record(with_hsdb_3595: bool) -> dict:
    refs = [{"ReferenceNumber": 58, "SourceName": "Hazardous Substances Data Bank (HSDB)", "SourceID": "6483",
             "Name": "LEVONORGESTREL"},
            {"ReferenceNumber": 107, "SourceName": "Toxin and Toxin Target Database (T3DB)",
             "SourceID": "Compound::T3D4749", "Name": "Levonorgestrel"}]
    values = [{"TOCHeading": "Toxicity Data", "Information": [_info(107, "LD50 >5000 mg/kg (orally in rats)")]}]
    if with_hsdb_3595:
        refs.append({"ReferenceNumber": 70, "SourceName": "Hazardous Substances Data Bank (HSDB)",
                     "SourceID": "3595", "Name": "NORGESTREL"})
        values.append({"TOCHeading": "Non-Human Toxicity Values", "Information": [
            _info(70, "LD50 Rat oral 5010 mg/kg"), _info(70, "LD50 Rat ip 11,200 mg/kg"),
            _info(70, "LD50 Mouse ip 7300 mg/kg"), _info(70, "LD50 Mouse oral 5010 mg/kg")]})
    return {"Record": {"RecordNumber": CID, "RecordTitle": "Levonorgestrel", "Reference": refs, "Section": [
        {"TOCHeading": "Toxicity", "Section": [{"TOCHeading": "Toxicological Information", "Section": [
            {"TOCHeading": "Toxicity Data and Values", "Section": values}]}]}]}}


OCTOBER, TODAY = _record(True), _record(False)


def _shipped() -> dict:
    """levonorgestrel's record as it shipped (data/snapshots/molecules/levonorgestrel.json)."""
    rows = toxicity.parse_ld50(OCTOBER)
    best = toxicity.primary_ld50(rows, "levonorgestrel")
    return {"slug": "levonorgestrel", "cid": CID, "toxicity": rows, "ld50_mg_per_kg": best["value_num"],
            "ld50_species": best["species"], "ld50_route": best["route"]}


# ── what changed upstream, and why nothing parses ───────────────────────────
def test_the_shipped_rows_came_from_hsdb_3595_and_todays_answer_has_none():
    assert [(r["species"], r["route"], r["value_num"]) for r in toxicity.parse_ld50(OCTOBER)] == [
        ("rat", "oral", 5010.0), ("mouse", "oral", 5010.0), ("mouse", "other", 7300.0), ("rat", "other", 11200.0)]
    assert toxicity.parse_ld50(TODAY) == []
    assert toxicity.parse_ld50(TODAY, gate=False) == []          # not a wording the parser skips


# ── the liveness fix ────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, body):
        self.status_code, self._body = 200, body

    def json(self):
        return self._body

    def raise_for_status(self):
        return None


def _fake_pubchem(monkeypatch, tmp_path, body):
    calls: list[tuple] = []

    def get(url, params=None, timeout=None):
        calls.append((url, (params or {}).get("heading")))
        return _Resp(body if (params or {}).get("heading") == "Toxicity" else None)

    monkeypatch.setattr(pubchem, "RAW_CACHE", tmp_path)
    monkeypatch.setattr(pubchem, "_throttle", lambda: None)
    monkeypatch.setattr(pubchem._session, "get", get)
    monkeypatch.setattr(freshness, "PATH", tmp_path / "freshness.json")
    monkeypatch.setattr(ld50_hold, "HELD_FILE", tmp_path / "ld50_held.json")
    monkeypatch.delenv("MFETL_INPUTS", raising=False)
    return calls


def _transform_read(tmp_path):
    """What stage_transform does: read the answer back and carry the fetch stage's liveness."""
    return freshness.carried(freshness.load(tmp_path / "freshness.json"), freshness.TOXICITY, CID,
                             pubchem.pug_view_dated(CID, "Toxicity"))


def test_an_answer_the_fetch_stage_fetched_live_is_live_in_the_transform(tmp_path, monkeypatch):
    """The bug: the warm-up fetched it live, the transform read the file back as a cache hit, and the
    guard reported 'cache hit written <today>' for a fetch made minutes earlier in the same run."""
    _fake_pubchem(monkeypatch, tmp_path, TODAY)
    pipeline._warm_annotations([CID])
    assert pubchem.pug_view_dated(CID, "Toxicity").live is False      # the raw read back: a hit
    assert _transform_read(tmp_path).live is True                    # what the guard now sees


def test_an_answer_the_fetch_stage_read_off_the_disk_stays_a_cache_hit(tmp_path, monkeypatch):
    calls = _fake_pubchem(monkeypatch, tmp_path, TODAY)
    pipeline._warm_annotations([CID])                                # run 1: live
    pipeline._warm_annotations([CID])                                # run 2: fresh in cache, no request
    assert [c for c in calls if c[1] == "Toxicity"] == [(f"{pubchem.PUBCHEM_VIEW}/data/compound/{CID}/JSON", "Toxicity")]
    assert _transform_read(tmp_path).live is False
    assert "cache hit written" in freshness.describe(freshness.load(tmp_path / "freshness.json"),
                                                    freshness.TOXICITY, CID)


def test_a_recorded_live_fetch_does_not_launder_a_different_entry():
    e = cache.Entry(TODAY, "2026-11-21T18:01:10Z", live=False)
    stale = {"toxicity": {str(CID): {"fetched_at": "2026-11-14T08:00:00Z", "live": True}}}
    assert freshness.carried(stale, freshness.TOXICITY, CID, e).live is False
    assert freshness.carried({}, freshness.TOXICITY, CID, e).live is False


def test_a_held_molecule_is_asked_again_whatever_the_cache_age(tmp_path, monkeypatch):
    calls = _fake_pubchem(monkeypatch, tmp_path, TODAY)
    pipeline._warm_annotations([CID])
    ld50_hold.write_held([{"kind": "held", "slug": "levonorgestrel", "cid": CID, "ld50_mg_per_kg": 5010.0,
                           "since": "2026-11-21", "seen": "2026-11-21"}])
    pipeline._warm_annotations([CID])
    assert len([c for c in calls if c[1] == "Toxicity"]) == 2
    assert _transform_read(tmp_path).live is True


def test_a_pinned_build_never_asks_again_for_a_held_molecule(tmp_path, monkeypatch):
    calls = _fake_pubchem(monkeypatch, tmp_path, TODAY)
    pipeline._warm_annotations([CID])
    ld50_hold.write_held([{"kind": "held", "slug": "levonorgestrel", "cid": CID, "ld50_mg_per_kg": 5010.0,
                           "since": "2026-11-21", "seen": "2026-11-21"}])
    monkeypatch.setenv("MFETL_INPUTS", "pinned")
    pipeline._warm_annotations([CID])
    assert len([c for c in calls if c[1] == "Toxicity"]) == 1


# ── the hold ────────────────────────────────────────────────────────────────
def _decide(live: bool, day: str, previous: dict | None, answer: dict = TODAY):
    return ld50_hold.decide(CID, toxicity.parse_ld50(answer), _shipped(), live=live,
                            fetched_at=f"{day}T08:12:00Z", previous=previous)


def _guard(rows: list[dict], live: bool, day: str) -> list[dict]:
    """The export guard over the record these rows assemble to."""
    best = toxicity.primary_ld50(rows, "levonorgestrel")
    new = {"slug": "levonorgestrel", "cid": CID, "ld50_mg_per_kg": best["value_num"] if best else None}
    fresh = {"toxicity": {str(CID): {"fetched_at": f"{day}T08:12:00Z", "live": live}}}
    return snapshot_guard._regressions([new], {"levonorgestrel": _shipped()}, fresh)


def test_held_on_first_sight_of_a_live_removal():
    rows, e = _decide(True, "2026-11-23", None)
    assert rows == _shipped()["toxicity"]                            # assembled exactly as shipped
    assert e["kind"] == "held" and e["since"] == "2026-11-23" and e["first"]
    assert _guard(rows, True, "2026-11-23") == []
    line = ld50_hold.report_line(e)
    assert line.startswith("levonorgestrel: LD50 5,010 mg/kg (rat, oral) held.") and "2026-11-30" in line


def test_still_held_before_seven_days():
    prev = {"cid": CID, "since": "2026-11-23", "seen": "2026-11-23"}
    rows, e = _decide(True, "2026-11-29", prev)
    assert rows == _shipped()["toxicity"] and e["kind"] == "held" and e["since"] == "2026-11-23"
    assert e["seen"] == "2026-11-29" and not e["first"]


def test_released_after_seven_days_and_the_guard_lets_it_go():
    prev = {"cid": CID, "since": "2026-11-23", "seen": "2026-11-23"}
    rows, e = _decide(True, "2026-11-30", prev)
    assert rows == [] and e["kind"] == "released"
    assert "RELEASED" in ld50_hold.report_line(e)
    assert _guard(rows, True, "2026-11-30") == []                    # live: the guard allows it


def test_a_value_that_comes_back_resets_the_clock():
    prev = {"cid": CID, "since": "2026-11-23", "seen": "2026-11-23"}
    rows, e = _decide(True, "2026-11-27", prev, answer=OCTOBER)
    assert e["kind"] == "back" and toxicity.primary_ld50(rows)["value_num"] == 5010.0
    # gone again later: a NEW hold from that day, not a release on the old clock
    rows, e = _decide(True, "2026-11-30", None)
    assert e["kind"] == "held" and e["since"] == "2026-11-30" and rows == _shipped()["toxicity"]


def test_a_cache_hit_is_still_refused():
    rows, e = _decide(False, "2026-11-23", None)
    assert e is None and rows == []
    found = _guard(rows, False, "2026-11-23")
    assert [(f["slug"], f["field"]) for f in found] == [("levonorgestrel", "ld50_mg_per_kg")]
    assert "cache hit written" in found[0]["why"]


def test_a_cache_hit_keeps_a_hold_and_never_releases_it():
    prev = {"cid": CID, "since": "2026-11-23", "seen": "2026-11-23"}
    rows, e = _decide(False, "2026-12-15", prev)
    assert rows == _shipped()["toxicity"] and e["kind"] == "held"
    assert (e["since"], e["seen"]) == ("2026-11-23", "2026-11-23")   # the clock did not move
    assert "clock did not move" in ld50_hold.report_line(e)


def test_nothing_to_hold_when_nothing_shipped_or_the_value_stays():
    assert ld50_hold.decide(CID, [], None, live=True, fetched_at="2026-11-23T00:00:00Z", previous=None) == ([], None)
    rows = toxicity.parse_ld50(OCTOBER)
    assert ld50_hold.decide(CID, rows, _shipped(), live=True, fetched_at="2026-11-23T00:00:00Z",
                            previous=None) == (rows, None)


def test_the_held_file_lists_only_holds_and_is_stable(tmp_path):
    _, held = _decide(True, "2026-11-23", None)
    _, released = ld50_hold.decide(CID + 1, [], {**_shipped(), "slug": "norethisterone", "cid": CID + 1},
                                   live=True, fetched_at="2026-11-30T00:00:00Z",
                                   previous={"since": "2026-11-23"})
    path = ld50_hold.write_held([released, held], tmp_path / "held.json")
    first = path.read_text()
    assert json.loads(first) == [{"slug": "levonorgestrel", "cid": CID, "ld50_mg_per_kg": 5010.0, "species": "rat",
                                  "route": "oral", "since": "2026-11-23", "seen": "2026-11-23"}]
    assert ld50_hold.read_held(path)[CID]["since"] == "2026-11-23"
    ld50_hold.write_held([held, released], path)
    assert path.read_text() == first


def test_report_lines_carry_no_dashes():
    prev = {"cid": CID, "since": "2026-11-23", "seen": "2026-11-23"}
    events = [_decide(True, "2026-11-23", None)[1], _decide(True, "2026-11-30", prev)[1],
              _decide(False, "2026-11-25", prev)[1], _decide(True, "2026-11-25", prev, answer=OCTOBER)[1]]
    for e in events:
        line = ld50_hold.report_line(e)
        assert "—" not in line and "–" not in line
