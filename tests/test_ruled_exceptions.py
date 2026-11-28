"""Ruled exceptions to the approved-medicine rule, and the status rule's fourth outcome (brief
../TRUST-5-SOURCE-CHECK-PROMPT.md, section D; Garrett, 2026-11-28).

Phenazopyridine has no marketing authorisation from any regulator the rule names; its one DailyMed label, Pyridium, is
an unapproved drug's. The page stays, as a ruled exception like phenibut and flunitrazepam, and says so: "Sold in the
United States without FDA approval." The exceptions are recorded in ONE place (approvals.yaml `exception:`), read by
relationships.ruled_exceptions(), and the status rule, the one-fact review and the source review all read them there.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from moleculefinder_etl.config import SEEDS_DIR
from moleculefinder_etl.review import facts
from moleculefinder_etl.transform import medicine_status as MS
from moleculefinder_etl.transform import relationships

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "data" / "snapshots" / "molecules"
PYRIDIUM = "165d01d4-a9f7-2293-e054-00144ff8d46c"


def rec(slug):
    return json.loads((SNAP / f"{slug}.json").read_text())


def label(slug, setid, doc="HUMAN PRESCRIPTION DRUG LABEL"):
    return {"slug": slug, "name": slug.title(), "source": {"type": "dailymed", "setid": setid, "doc_type": doc, "version": 15,
                                                              "url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"}}


def molecule(slug, actives):
    return {"slug": slug, "title": slug.title(), "scope_bucket": "otc-medicine", "approval": None, "is_otc": True,
            "products": [{"slug": s, "role": "active"} for s in actives]}


def mkt(category):
    return lambda setid, version: [{"product": "P", "category": category, "application": "", "status": "active"}]


def attach(records, labels, marketing, tmp_path, exceptions):
    ap = tmp_path / "approvals.yaml"
    ap.write_text(yaml.safe_dump(exceptions))
    bases = tmp_path / "status_bases.yaml"
    bases.write_text("")
    mp = pytest.MonkeyPatch()
    mp.setattr(relationships, "APPROVALS_YAML", ap)
    try:
        return MS.attach(records, labels, marketing, set(), set(), path=bases)
    finally:
        mp.undo()


EXC = {"phenazopyridine": {"exception": {
    "ruled": "2026-11-28", "by": "Garrett", "why": "a ruling", "marketed": "unapproved",
    "label": {"product": "Pyridium", "setid": PYRIDIUM, "version": 15, "category": "unapproved drug other", "read": "2026-11-28"}}}}


def test_the_exceptions_live_in_one_place():
    ex = relationships.ruled_exceptions()
    assert set(ex) == {"phenibut", "flunitrazepam", "phenazopyridine"}
    assert ex["phenibut"]["ruled"] == ex["flunitrazepam"]["ruled"] == "2026-10-18"
    assert ex["phenazopyridine"]["ruled"] == "2026-11-28" and ex["phenazopyridine"]["label"]["setid"] == PYRIDIUM
    unsettled = yaml.safe_load((SEEDS_DIR / "status_bases.yaml").read_text())["unsettled"]
    assert "phenazopyridine" not in unsettled                     # one place, not two
    # the status rule and the one-fact review read the exceptions through the one reader
    for f in (ROOT / "moleculefinder_etl" / "transform" / "medicine_status.py", ROOT / "moleculefinder_etl" / "review" / "facts.py"):
        assert "relationships.ruled_exceptions()" in f.read_text(), f.name


def test_an_exception_is_not_a_licence_record():
    assert "phenazopyridine" not in relationships.load_approvals()
    recs = [{"slug": s} for s in {*relationships._approvals_raw(), "phenazopyridine"}]
    relationships.attach_approvals(recs)
    by = {r["slug"]: r for r in recs}
    assert "approval" not in by["phenazopyridine"]
    assert "exception" not in by["phenibut"]["approval"] and "exception" not in by["flunitrazepam"]["approval"]


def test_a_malformed_exception_stops_the_build(tmp_path, monkeypatch):
    bad = tmp_path / "approvals.yaml"
    bad.write_text(yaml.safe_dump({"x": {"exception": {"ruled": "soon", "by": "Garrett", "why": "w", "marketed": "unapproved"}}}))
    monkeypatch.setattr(relationships, "APPROVALS_YAML", bad)
    with pytest.raises(SystemExit) as e:
        relationships.ruled_exceptions()
    assert "ruled must be YYYY-MM-DD" in str(e.value) and "names its label" in str(e.value)


def test_the_fourth_outcome_for_a_recorded_exception(tmp_path):
    m = molecule("phenazopyridine", ["pyridium"])
    report = attach([m], [label("pyridium", PYRIDIUM)], mkt("UNAPPROVED DRUG OTHER"), tmp_path, EXC)
    st = m["medicine_status"]
    assert st["status"] == "unapproved" and st["otc"] == [] and st["prescription"] == []
    assert st["exception"]["label"] == {"kind": "label", "register": "DailyMed", "product": "Pyridium", "slug": "pyridium",
                                        "setid": PYRIDIUM, "version": 15, "category": "unapproved drug other",
                                        "source": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={PYRIDIUM}"}
    assert "unsettled" not in st and m["is_otc"] is True          # is_otc left as it is
    assert report["status"]["phenazopyridine"] == "unapproved" and not report["unsettled"]


def test_the_fourth_outcome_only_for_a_recorded_exception(tmp_path):
    other = molecule("lookalike", ["other-label"])
    attach([other], [label("other-label", "11111111-1111-1111-1111-111111111111")], mkt("UNAPPROVED DRUG OTHER"), tmp_path, EXC)
    assert other["medicine_status"]["status"] == "otc" and other["medicine_status"]["unsettled"]   # its group's line


def test_a_label_that_no_longer_says_unapproved_falls_back_and_never_stops_the_build(tmp_path):
    m = molecule("phenazopyridine", ["pyridium"])
    report = attach([m], [label("pyridium", PYRIDIUM)], mkt("NDA"), tmp_path, EXC)
    assert m["medicine_status"]["status"] != "unapproved" and m["medicine_status"].get("unsettled")
    assert report["exceptions"]["phenazopyridine"].startswith("NOT APPLIED")


def test_the_committed_record_carries_the_fourth_line_and_the_labels_own_words():
    r = rec("phenazopyridine")
    st = r["medicine_status"]
    assert st["status"] == "unapproved"
    assert st["exception"]["label"]["category"] == "unapproved drug other"
    assert st["exception"]["label"]["setid"] == PYRIDIUM
    assert facts.record_status(r) == "unapproved"
    for slug in ("phenibut", "flunitrazepam"):                     # their pages are unchanged by the exception's record
        assert rec(slug)["medicine_status"]["status"] == "prescription" and rec(slug)["medicine_status"]["unsettled"]


def test_the_review_does_not_accept_the_fourth_line_without_a_recorded_exception():
    r = {**rec("phenazopyridine"), "slug": "not-an-exception"}
    assert facts.record_status(r) != "unapproved"
