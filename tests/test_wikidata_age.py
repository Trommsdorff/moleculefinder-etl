"""A changed Wikidata value ships only once it is 7 days old (trust run 8, 2026-10-26).

2026-10-25 13:37 UTC: an anonymous edit set propane's (Q131189) English label to "priest", and the
next morning's weekly run would have titled the page "Propane (Priest)". ``transform/wikidata_age.py``
holds a changed value until the item already carried it at the cutoff (now minus 7 days). These tests
replay the day with the real values, the network replaced by the item as each revision had it.
"""
from __future__ import annotations

import json

import pytest

from moleculefinder_etl import pipeline
from moleculefinder_etl.sources import wikidata
from moleculefinder_etl.transform import assemble, canon, wikidata_age
from tests.fixtures import canon_row, fetched

CID, QID = 6334, "Q131189"
NOW = "2026-10-26T12:00:00Z"                  # Monday's run
ALIASES = ["dimethyl methane", "n-propane", "propyl hydride", "CH3-CH2-CH3", "E944", "R-290",
           "CARE-40", "HC-290"]
SHIPPED = {"qid": QID, "desc": "chemical compound, commonly used as a fuel", "label": "propane",
           "aliases": ALIASES}
VANDAL = {**SHIPPED, "label": "priest"}       # revision 2560697164


def _item(entry: dict, *, revid=2558488008, timestamp="2026-10-18T18:46:35Z", p662=(str(CID),)):
    """The item as ``wikidata.entity_as_of`` returns it."""
    return {"revid": revid, "timestamp": timestamp, "desc": entry["desc"], "label": entry["label"],
            "aliases": list(entry["aliases"]), "p662": list(p662)}


@pytest.fixture
def wd(tmp_path, monkeypatch):
    """Wikidata replaced by a dict of items as they stood at the cutoff; every request recorded."""
    monkeypatch.setattr(wikidata_age, "AGEING_CACHE", tmp_path / "wikidata" / "ageing.json")
    monkeypatch.delenv("MFETL_INPUTS", raising=False)
    state = {"as_of": {}, "modified": {}, "calls": []}

    def info(qids):
        state["calls"].append(("info", sorted(qids)))
        return {q: {"modified": state["modified"].get(q, "2026-10-25T13:37:28Z"), "lastrevid": 1}
                for q in qids}

    def as_of(qid, when):
        state["calls"].append(("as_of", qid, when))
        return state["as_of"].get(qid)

    monkeypatch.setattr(wikidata_age.wikidata, "entity_info", info)
    monkeypatch.setattr(wikidata_age.wikidata, "entity_as_of", as_of)
    return state


def _age(fresh: dict, shipped: dict | None = SHIPPED, at: str = NOW):
    return wikidata_age.age_entries({CID: {**fresh, "fetched_at": at, "live": True}},
                                    {CID: shipped} if shipped else {}, at=at)


# ── the four cases of the ruling ────────────────────────────────────────────
def test_a_fresh_edit_is_held_and_the_shipped_value_stands(wd):
    wd["as_of"][QID] = _item(SHIPPED)          # at the cutoff the label was still "propane"
    out, held = _age(VANDAL)
    assert out[CID]["label"] == "propane"
    assert out[CID]["aliases"] == ALIASES and out[CID]["desc"] == SHIPPED["desc"]
    assert held == [{"cid": CID, "qid": QID, "field": "label", "shipped": "propane", "held": "priest",
                     "modified": "2026-10-25T13:37:28Z", "cutoff": "2026-10-19T12:00:00Z"}]
    # One batched info request and one revision read for the one changed item, at the cutoff.
    assert wd["calls"] == [("info", [QID]), ("as_of", QID, "2026-10-19T12:00:00Z")]


def test_an_edit_eight_days_old_ships(wd):
    # Next week the vandal label (if nobody reverted it) has stood since before the cutoff.
    wd["as_of"][QID] = _item(VANDAL, revid=2560697164, timestamp="2026-10-25T13:37:28Z")
    out, held = _age(VANDAL, at="2026-11-02T13:38:00Z")
    assert out[CID]["label"] == "priest" and held == []


def test_a_reverted_edit_never_reaches_the_site(wd):
    wd["as_of"][QID] = _item(SHIPPED)
    out, held = _age(VANDAL)                    # this week: held
    assert out[CID]["label"] == "propane" and len(held) == 1
    wd["calls"].clear()
    out, held = _age(SHIPPED, at="2026-10-28T09:00:00Z")    # reverted on Wikidata two days later
    assert out[CID]["label"] == "propane" and held == []
    assert wd["calls"] == []                    # nothing changed, so nothing is asked


def test_a_new_molecule_takes_wikidatas_current_value(wd):
    out, held = _age(VANDAL, shipped=None)
    assert out[CID]["label"] == "priest" and held == []
    assert wd["calls"] == []


def test_a_cid_with_no_entry_this_run_is_left_alone(wd):
    out, held = wikidata_age.age_entries({CID: None}, {CID: SHIPPED}, at=NOW)
    assert out == {CID: None} and held == [] and wd["calls"] == []


# ── per field, not per item ─────────────────────────────────────────────────
def test_each_field_ages_on_its_own(wd):
    # An alias added three weeks ago that this run is the first to see, plus today's vandal label:
    # the alias was on the item at the cutoff, so it ships; the label was not, so it is held.
    aliases = [*ALIASES, "propyl"]
    wd["as_of"][QID] = _item({**SHIPPED, "aliases": aliases})
    out, held = _age({**VANDAL, "aliases": aliases})
    assert out[CID]["aliases"] == aliases and out[CID]["label"] == "propane"
    assert [h["field"] for h in held] == ["label"]


def test_an_item_created_after_the_cutoff_holds_every_change(wd):
    wd["as_of"][QID] = None                     # no revision that old
    out, held = _age({**VANDAL, "desc": "a new description"})
    assert (out[CID]["label"], out[CID]["desc"]) == ("propane", SHIPPED["desc"])
    assert sorted(h["field"] for h in held) == ["description", "label"]


# ── the item itself ─────────────────────────────────────────────────────────
OTHER = {"qid": "Q999", "desc": "a shadow item", "label": "propane gas", "aliases": []}


def test_a_new_item_taking_the_cid_is_held_until_its_link_is_old(wd):
    wd["as_of"]["Q999"] = _item(OTHER, p662=())          # P662 added to it since the cutoff
    out, held = _age(OTHER)
    assert {k: out[CID][k] for k in ("qid", *wikidata_age.FIELDS)} == SHIPPED
    assert [h["field"] for h in held] == ["item", "description", "label", "aliases"]
    assert held[0]["shipped"] == QID and held[0]["held"] == "Q999"


def test_a_new_item_whose_link_and_values_are_old_ships(wd):
    wd["as_of"]["Q999"] = _item(OTHER)
    out, held = _age(OTHER)
    assert out[CID]["qid"] == "Q999" and held == []


def test_a_cid_losing_its_item_is_held_until_the_removal_is_old(wd):
    gone = {"qid": None, "desc": None, "label": None, "aliases": []}
    wd["as_of"][QID] = _item(SHIPPED)                    # still linked at the cutoff
    out, held = _age(gone)
    assert out[CID]["qid"] == QID and out[CID]["label"] == "propane" and held
    wd["as_of"][QID] = _item(SHIPPED, p662=())           # unlinked before the cutoff
    out, held = _age(gone)
    assert out[CID]["qid"] is None and held == []


# ── the placeholder guard still works ───────────────────────────────────────
DCP_CID, DCP_QID, DCP_SHIPPED = 24441, "Q414619", "chemical compound CaHPO₄"
DCP_PROPS = {"CID": DCP_CID, "MolecularFormula": "CaHPO4", "MolecularWeight": "136.06",
             "SMILES": "OP(=O)([O-])[O-].[Ca+2]", "ConnectivitySMILES": "OP(=O)([O-])[O-].[Ca+2]",
             "InChIKey": "FUFJGUQYACFECW-UHFFFAOYSA-L"}


def _dcp(entry: dict, prior=None) -> dict:
    row = canon_row(DCP_CID, "Dicalcium phosphate")
    canon._apply_wikidata(row, entry)
    return assemble.assemble_record(row, fetched(DCP_PROPS), set(), prior=prior)


def test_an_aged_edit_to_the_placeholder_still_keeps_the_shipped_summary(wd):
    shipped = {"qid": DCP_QID, "desc": DCP_SHIPPED, "label": "dicalcium phosphate", "aliases": []}
    edited = {**shipped, "desc": "chemical compound"}
    wd["as_of"][DCP_QID] = _item(edited)                 # the 2026-09-25 edit, long aged
    out, held = wikidata_age.age_entries({DCP_CID: edited}, {DCP_CID: shipped}, at=NOW)
    assert out[DCP_CID]["desc"] == "chemical compound" and held == []    # the age rule lets it by
    rec = _dcp(out[DCP_CID], prior=_dcp(shipped))
    assert rec["summary"] == DCP_SHIPPED                 # and the Sep 28 carry still keeps the text


def test_a_fresh_edit_to_the_placeholder_is_held_before_the_carry_is_needed(wd):
    shipped = {"qid": DCP_QID, "desc": DCP_SHIPPED, "label": "dicalcium phosphate", "aliases": []}
    wd["as_of"][DCP_QID] = _item(shipped)
    out, held = wikidata_age.age_entries({DCP_CID: {**shipped, "desc": "chemical compound"}},
                                         {DCP_CID: shipped}, at=NOW)
    assert out[DCP_CID]["desc"] == DCP_SHIPPED and [h["field"] for h in held] == ["description"]


# ── failures, pinned builds, the cache ──────────────────────────────────────
def test_a_failed_read_fails_the_run(wd, monkeypatch):
    def boom(qids):
        raise ConnectionError("wikidata.org unreachable")
    monkeypatch.setattr(wikidata_age.wikidata, "entity_info", boom)
    monkeypatch.delenv("MFETL_ALLOW_STALE_WIKIDATA", raising=False)
    with pytest.raises(wikidata.WikidataQueryError, match="ConnectionError"):
        _age(VANDAL)


def test_the_stale_override_holds_every_change_instead(wd, monkeypatch):
    def boom(qids):
        raise ConnectionError("wikidata.org unreachable")
    monkeypatch.setattr(wikidata_age.wikidata, "entity_info", boom)
    monkeypatch.setenv("MFETL_ALLOW_STALE_WIKIDATA", "1")
    out, held = _age(VANDAL)
    assert out[CID]["label"] == "propane" and held[0]["modified"] is None


def test_a_pinned_build_reuses_the_weekly_runs_answers(wd, monkeypatch):
    wd["as_of"][QID] = _item(SHIPPED)
    _, first = _age(VANDAL)                     # the weekly run (no mode) asks and caches
    wd["calls"].clear()
    wd["as_of"][QID] = _item(VANDAL)            # a week on, Wikidata would answer differently
    monkeypatch.setenv("MFETL_INPUTS", "pinned")
    _, again = _age(VANDAL, at="2026-11-03T00:00:00Z")
    assert again == first and wd["calls"] == []  # same holds, no request
    monkeypatch.delenv("MFETL_INPUTS")
    _, later = _age(VANDAL, at="2026-11-03T00:00:00Z")      # the weekly run asks again
    assert later == [] and wd["calls"]


def test_the_cache_is_an_entries_map_the_inputs_manifest_hashes_per_entry(wd):
    wd["as_of"][QID] = _item(SHIPPED)
    _age(VANDAL)
    from moleculefinder_etl import inputs
    manifest = inputs.manifest(wikidata_age.AGEING_CACHE.parent.parent)
    assert list(manifest["wikidata/ageing.json"]["entries"]) == [QID]


# ── the canon build, end to end on a real parquet ───────────────────────────
def test_the_canon_build_carries_the_shipped_label_into_the_new_parquet(wd, tmp_path, monkeypatch):
    rows = [r for r in canon._scope_b_rows() if r["cid"] == CID]
    assert rows, "propane is in the Scope B core"
    shipped_parquet = tmp_path / "canon.parquet"
    canon.write_parquet([{**rows[0], "wikidata_qid": QID, "summary": SHIPPED["desc"],
                          "wikidata_label": "propane", "wikidata_aliases": ALIASES}], shipped_parquet)
    monkeypatch.setattr(canon, "_scope_b_rows", lambda: [dict(rows[0])])
    monkeypatch.setattr(canon, "_descriptions_cached",
                        lambda cids: {CID: {**VANDAL, "fetched_at": NOW, "live": True}})
    wd["as_of"][QID] = _item(SHIPPED)
    held: list = []
    built = canon.build_scope_b_canon(held=held, shipped=wikidata_age.read_shipped(shipped_parquet))
    assert built[0]["wikidata_label"] == "propane" and built[0]["wikidata_aliases"] == ALIASES
    assert [h["held"] for h in held] == ["priest"]
    rec = assemble.assemble_record(built[0], fetched({"CID": CID, "SMILES": "CCC"}), set())
    assert "priest" not in json.dumps(rec).lower()


# ── the report ──────────────────────────────────────────────────────────────
def test_held_values_are_reported_one_line_each_and_committed(wd, tmp_path, monkeypatch):
    wd["as_of"][QID] = _item(SHIPPED)
    _, held = _age(VANDAL)
    monkeypatch.setattr(wikidata_age, "HELD_FILE", tmp_path / "wikidata_held.json")
    monkeypatch.setattr(pipeline, "_prior_snapshot", lambda: {CID: {"slug": "propane"}})
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    pipeline._report_held(held)
    line = ('propane: label held, shipped "propane", Wikidata now "priest", '
            'item Q131189 modified 2026-10-25T13:37:28Z')
    assert line in summary.read_text() and "Wikidata changes held (1)" in summary.read_text()
    assert json.loads((tmp_path / "wikidata_held.json").read_text()) == [
        {"slug": "propane", "cid": CID, "qid": QID, "field": "label", "shipped": "propane",
         "held": "priest", "modified": "2026-10-25T13:37:28Z"}]
    pipeline._report_held([])
    assert json.loads((tmp_path / "wikidata_held.json").read_text()) == []


# ── the two reads, on Wikidata's own response shapes ────────────────────────
class _Resp:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def test_entity_as_of_reads_the_revision_content(monkeypatch):
    content = {"labels": {"en": {"language": "en", "value": "propane"}},
               "descriptions": {"en": {"language": "en", "value": SHIPPED["desc"]}},
               "aliases": {"en": [{"language": "en", "value": a} for a in ALIASES]},
               "claims": {"P662": [{"rank": "normal", "mainsnak": {"datavalue": {"value": "6334"}}},
                                   {"rank": "deprecated", "mainsnak": {"datavalue": {"value": "1"}}}]}}
    seen = {}

    def get(url, params, headers, timeout):
        seen.update(params)
        return _Resp({"query": {"pages": [{"title": QID, "revisions": [
            {"revid": 2558488008, "timestamp": "2026-10-18T18:46:35Z",
             "slots": {"main": {"content": json.dumps(content)}}}]}]}})
    monkeypatch.setattr(wikidata.requests, "get", get)
    got = wikidata.entity_as_of(QID, "2026-10-19T12:00:00Z")
    assert got == _item(SHIPPED)
    assert (seen["rvstart"], seen["rvdir"], seen["rvlimit"]) == ("2026-10-19T12:00:00Z", "older", 1)


def test_entity_as_of_handles_empty_maps_and_no_old_revision(monkeypatch):
    bodies = iter([
        {"query": {"pages": [{"title": QID, "revisions": [{"revid": 1, "timestamp": "t", "slots": {
            "main": {"content": json.dumps({"labels": [], "descriptions": [], "aliases": [],
                                            "claims": []})}}}]}]}},
        {"query": {"pages": [{"title": QID}]}},                     # created after the cutoff
        {"query": {"pages": [{"title": "Q0", "missing": True}]}},
    ])
    monkeypatch.setattr(wikidata.requests, "get", lambda *a, **k: _Resp(next(bodies)))
    assert wikidata.entity_as_of(QID, NOW) == {"revid": 1, "timestamp": "t", "desc": None,
                                               "label": None, "aliases": [], "p662": []}
    assert wikidata.entity_as_of(QID, NOW) is None
    assert wikidata.entity_as_of("Q0", NOW) is None


def test_entity_info_batches_fifty_and_follows_redirects(monkeypatch):
    seen = []

    def get(url, params, headers, timeout):
        ids = params["ids"].split("|")
        seen.append(len(ids))
        ents = {q: {"modified": "m", "lastrevid": 1} for q in ids if q != "Q7"}
        if "Q7" in ids:
            ents["Q9999"] = {"modified": "r", "lastrevid": 2, "redirects": {"from": "Q7", "to": "Q9999"}}
        return _Resp({"entities": ents})
    monkeypatch.setattr(wikidata.requests, "get", get)
    out = wikidata.entity_info([f"Q{i}" for i in range(1, 61)])
    assert seen == [50, 10] and out["Q7"] == {"modified": "r", "lastrevid": 2} and len(out) == 60
