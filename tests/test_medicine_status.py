"""One rule for "over the counter", "prescription" or both (trust 3C, 2026-11-27; transform/medicine_status.py)."""
import json
from pathlib import Path

import pytest

from moleculefinder_etl.review import facts
from moleculefinder_etl.sources import dailymed
from moleculefinder_etl.transform import medicine_status as MS
from moleculefinder_etl.transform import relationships

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "data" / "snapshots" / "molecules"
rec = lambda slug: json.loads((SNAP / f"{slug}.json").read_text())

OTC_LIC = {"register": "Drugs@FDA", "application": "NDA 000001", "source": "https://www.accessdata.fda.gov/x",
           "basis": "Marketed today (over-the-counter) under NDA 000001 in the Drugs@FDA data files.", "read": "2026-10-21"}
RX_LIC = {**OTC_LIC, "basis": "Marketed today (prescription) under NDA 000001 in the Drugs@FDA data files."}
OTC_DOC, RX_DOC = "HUMAN OTC DRUG LABEL", "HUMAN PRESCRIPTION DRUG LABEL"


def label(slug, doc, setid="00000000-0000-0000-0000-000000000001"):
    return {"slug": slug, "name": slug.title(), "source": {"type": "dailymed", "setid": setid, "doc_type": doc,
                                                              "version": 3, "url": "https://dailymed.nlm.nih.gov/x"}}


def mkt(category, status="active"):
    return lambda setid, version: [{"product": "P", "category": category, "application": "", "status": status}]


def med(bucket="prescription-medicine", approval=None, actives=()):
    return {"slug": "x", "title": "X", "scope_bucket": bucket, "approval": approval,
            "products": [{"slug": s, "role": "active"} for s in actives]}


def run(records, labels, marketing, listed=(), uses_only=(), tmp_path=None, bases=""):
    path = (tmp_path / "status_bases.yaml") if tmp_path else Path("/nonexistent")
    if tmp_path:
        path.write_text(bases)
    return MS.attach(records, labels, marketing, set(listed), set(uses_only), path=path)


def test_the_three_outcomes_and_the_unsettled(tmp_path):
    a = med(approval=RX_LIC)
    b = med("otc-medicine", approval=OTC_LIC)
    c = {**med(approval=RX_LIC, actives=["brand"]), "slug": "c"}
    d = {**med("otc-medicine", approval={"register": "MHRA Products", "regulator": "MHRA", "basis": "Listed"}), "slug": "d"}
    b["slug"] = "b"
    run([a, b, c, d], [label("brand", OTC_DOC)], mkt("OTC MONOGRAPH DRUG"), tmp_path=tmp_path)
    assert (a["medicine_status"]["status"], b["medicine_status"]["status"], c["medicine_status"]["status"]) == \
        ("prescription", "otc", "both")
    assert c["is_otc"] is True and a["is_otc"] is False
    assert d["medicine_status"]["status"] == "otc" and d["medicine_status"]["unsettled"]   # its group's line stands
    assert MS.decide([], []) is None


def test_an_unapproved_prescription_label_does_not_make_the_both_ways_line(tmp_path):
    m = med("otc-medicine", approval=OTC_LIC, actives=["rxbrand"])
    run([m], [label("rxbrand", RX_DOC)], mkt("UNAPPROVED DRUG OTHER"), tmp_path=tmp_path)
    assert m["medicine_status"]["status"] == "otc" and m["medicine_status"]["prescription"] == []
    # nor does a label whose marketing has ended, nor one whose marketing was never read
    for marketing in (mkt("NDA", status="completed"), lambda s, v: None):
        m = med("otc-medicine", approval=OTC_LIC, actives=["rxbrand"])
        run([m], [label("rxbrand", RX_DOC)], marketing, tmp_path=tmp_path)
        assert m["medicine_status"]["status"] == "otc"
    # an OTC monograph is not a prescription authorisation either
    m = med("otc-medicine", approval=OTC_LIC, actives=["rxbrand"])
    run([m], [label("rxbrand", RX_DOC)], mkt("OTC MONOGRAPH DRUG"), tmp_path=tmp_path)
    assert m["medicine_status"]["status"] == "otc"


def test_an_otc_list_entry_with_no_basis_fails_the_build(tmp_path):
    m = med("otc-medicine", approval=RX_LIC)
    with pytest.raises(MS.StatusError, match="no over-the-counter basis.*x"):
        run([m], [], mkt("NDA"), listed=["x"], tmp_path=tmp_path)
    # recorded from the primary source, it holds
    m = med("otc-medicine", approval=RX_LIC)
    run([m], [], mkt("NDA"), listed=["x"], tmp_path=tmp_path, bases=(
        "x:\n  otc:\n    - {kind: application, application: NDA 012345, product: P, status: Over-the-counter, read: '2026-11-27'}\n"))
    assert m["medicine_status"]["status"] == "both" and m["is_otc"] is True
    # listed for its use only, it makes no claim, and is_otc is false
    m = med("otc-medicine", approval=RX_LIC)
    run([m], [], mkt("NDA"), uses_only=["x"], tmp_path=tmp_path)
    assert m["medicine_status"]["status"] == "prescription" and m["is_otc"] is False


@pytest.mark.parametrize("bad, why", [
    ("x:\n  otc:\n    - {kind: application, application: NDA 12345, product: P, status: Over-the-counter, read: '2026-11-27'}\n", "application must read"),
    ("x:\n  otc:\n    - {kind: application, application: NDA 012345, product: P, status: Prescription, read: '2026-11-27'}\n", "must be 'Over-the-counter'"),
    ("x:\n  otc:\n    - {kind: label, setid: nope, version: 1, product: P, category: NDA, status: active, read: '2026-11-27'}\n", "not a DailyMed set id"),
    ("x:\n  prescription:\n    - {kind: label, setid: 00000000-0000-0000-0000-000000000001, version: 1, product: P, category: OTC MONOGRAPH DRUG, status: active, read: '2026-11-27'}\n", "not a marketing authorisation"),
    ("x:\n  otc:\n    - {kind: application, application: NDA 012345, product: P, status: Over-the-counter, read: '2026-11-27', note: hi}\n", "unknown field"),
    ("y:\n  otc: []\n", "the catalog does not hold"),
])
def test_status_bases_refuses_a_bad_entry(tmp_path, bad, why):
    with pytest.raises(MS.StatusError, match=why):
        run([med()], [], mkt("NDA"), tmp_path=tmp_path, bases=bad)


def test_parse_marketing_reads_each_products_category_and_status():
    xml = b"""<document xmlns="urn:hl7-org:v3"><component><structuredBody><component><section><subject><manufacturedProduct>
      <manufacturedProduct><name>Pyridium</name></manufacturedProduct>
      <subjectOf><approval><id extension="unapproved drug other"/><code code="C73627" displayName="unapproved drug other"/></approval></subjectOf>
      <subjectOf><marketingAct><code code="C53292"/><statusCode code="active"/></marketingAct></subjectOf>
    </manufacturedProduct></subject></section></component></structuredBody></component></document>"""
    assert dailymed.parse_marketing(xml) == [{"product": "Pyridium", "category": "UNAPPROVED DRUG OTHER", "code": "C73627",
                                              "application": "unapproved drug other", "status": "active"}]


# ── the sixteen, by name, from the committed snapshot ────────────────────────────────────────────────────────────
def _apps(slug, side):
    return [e.get("application") for e in rec(slug)["medicine_status"][side] if e.get("application")]


def _labels(slug, side):
    return [e["product"] for e in rec(slug)["medicine_status"][side] if e["kind"] == "label"]


def test_the_four_stops_settled_from_the_primary_source():
    assert rec("azelastine")["medicine_status"]["status"] == "both"
    assert "NDA 213872" in _apps("azelastine", "otc") and _apps("azelastine", "prescription") == ["ANDA 077954"]
    assert rec("budesonide")["medicine_status"]["status"] == "both"
    assert _apps("budesonide", "otc") == ["NDA 020746"] and _apps("budesonide", "prescription") == ["NDA 020746"]
    assert rec("mometasone")["medicine_status"]["status"] == "both"
    assert _apps("mometasone", "otc") == ["NDA 215712"] and _apps("mometasone", "prescription") == ["NDA 021067"]
    lac = rec("lactulose")                         # no OTC basis anywhere: off the OTC list, prescription
    assert lac["medicine_status"]["status"] == "prescription" and lac["medicine_status"]["otc"] == []
    assert lac["is_otc"] is False
    listed, uses_only = relationships.otc_listed([lac])
    assert "lactulose" in uses_only and "lactulose" not in listed


@pytest.mark.parametrize("slug, otc, rx", [
    ("acetaminophen", "NDA 018337", "Percocet"),            # Percocet: ANDA 040330, marketed
    ("benzoyl-peroxide", "Proactiv Benzoyl Peroxide Wash", "NDA 214510"),
    ("bismuth-subsalicylate", "Pepto-Bismol", "ANDA 202584"),
    ("diphenhydramine", "Benadryl Allergy", "ANDA 080817"),
    ("esomeprazole", "NDA 204655", "NDA 021153"),
    ("meclizine", "Bonine", "NDA 010721"),
    ("naloxone", "NDA 208411", "Suboxone"),
    ("naproxen", "Aleve", "NDA 017581"),
    ("phenylephrine", "Sudafed PE Head Congestion plus Pain", "NDA 203826"),
    ("zinc-oxide", "Balmex Diaper Rash Cream", "NDA 021026"),
    ("triamcinolone-acetonide", "Nasacort Allergy 24HR", "NDA 012041"),
])
def test_the_twelve_said_one_side_and_the_record_holds_both(slug, otc, rx):
    r = rec(slug)
    assert r["medicine_status"]["status"] == "both", slug
    assert otc in _apps(slug, "otc") + _labels(slug, "otc")
    assert rx in _apps(slug, "prescription") + _labels(slug, "prescription")
    assert r["is_otc"] is True


def test_miconazole_stays_over_the_counter_its_prescription_label_is_no_longer_marketed():
    r = rec("miconazole")
    assert r["medicine_status"]["status"] == "otc" and r["medicine_status"]["prescription"] == []


def test_the_review_decides_the_line_by_the_same_rule():
    for slug in ("azelastine", "lactulose", "miconazole", "phenazopyridine", "acetaminophen"):
        r = rec(slug)
        assert facts.record_status(r) == r["medicine_status"]["status"], slug
    tampered = {**rec("miconazole")}
    tampered["medicine_status"] = {**tampered["medicine_status"], "status": "both"}
    assert facts.record_status(tampered) != "both"
