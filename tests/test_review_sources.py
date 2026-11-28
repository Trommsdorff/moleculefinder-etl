"""Trust review 4, the source check (moleculefinder_etl/review/sources.py; brief ../TRUST-5-SOURCE-CHECK-PROMPT.md).

For each check a case that must be found and one that must not: a label with every package ended, a discontinued
application, a link answering 404, a "Request Access" page treated as not read rather than as fine, a value with no
kind. The request budget is honoured, one request per address, the date seed, the Tuesday rule. All offline: the
network is a fake transport.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from pathlib import Path

import pytest

from moleculefinder_etl.review import sources as S
from moleculefinder_etl.transform import relationships

ROOT = Path(__file__).resolve().parents[1]
TODAY = "20261128"


class Fake:
    """A transport: url -> (status, body, headers). Counts every call."""

    def __init__(self, answers: dict):
        self.answers, self.calls = answers, []

    def __call__(self, url, method, headers):
        self.calls.append((method, url, dict(headers)))
        st, body, h = self.answers.get(url, (404, b"", {}))
        return S.Resp(st, h, body if isinstance(body, bytes) else body.encode())


def net(answers: dict, **kw) -> S.Net:
    return S.Net(Fake(answers), sleep=lambda s: None, **kw)


# ── the network ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_one_request_per_address_per_run():
    n = net({"https://x.org/a": (200, b"ok", {})})
    assert n.get("https://x.org/a").status == 200 and n.get("https://x.org/a").status == 200
    assert len(n.transport.calls) == 1 and n.report()["x.org"]["requests"] == 1


def test_the_budget_is_honoured_and_an_address_past_it_is_not_read():
    n = net({f"https://x.org/{i}": (200, b"ok", {}) for i in range(5)}, budget={"x.org": 2})
    got = [n.get(f"https://x.org/{i}") for i in range(5)]
    assert len(n.transport.calls) == 2                               # the third request is never made
    assert [bool(r.why) for r in got] == [False, False, True, True, True]
    assert "budget" in got[2].why
    rep = n.report()["x.org"]
    assert rep["requests"] == 2 and rep["not_made_budget"] == 3


def test_each_host_keeps_its_pace():
    slept = []
    t = [0.0]
    n = S.Net(Fake({}), sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)), clock=lambda: t[0])
    for i in range(3):
        n.get(f"https://pubchem.ncbi.nlm.nih.gov/x/{i}")
    assert len(slept) == 2 and all(abs(s - 0.25) < 1e-9 for s in slept)   # 4 a second: under PubChem's 5 and 400 a minute


def test_the_user_agent_is_named():
    assert S.USER_AGENT.startswith("MoleculeFinder-trust-review/") and "moleculefinder.com" in S.USER_AGENT
    assert "@" not in S.USER_AGENT                                      # no one's address


def test_a_data_file_is_asked_conditionally_from_the_reviews_own_cache(tmp_path):
    url = "https://www.fda.gov/media/89850/download"
    n = net({url: (200, b"zipbytes", {"last-modified": "Fri, 27 Nov 2026 14:16:20 GMT", "etag": '"e1"'})})
    body, how = S.conditional(n, url, tmp_path)
    assert body == b"zipbytes" and how.startswith("read")
    n2 = net({url: (304, b"", {})})
    body, how = S.conditional(n2, url, tmp_path)
    assert body == b"zipbytes" and "not modified" in how
    assert n2.transport.calls[0][2] == {"If-None-Match": '"e1"', "If-Modified-Since": "Fri, 27 Nov 2026 14:16:20 GMT"}
    assert str(tmp_path) != str(ROOT / "data" / "raw_cache") and S.DEFAULT_CACHE.name == "trust-sources-cache"


# ── the date seed and the Tuesday rule ──────────────────────────────────────────────────────────────────────────────
def test_the_date_seed_gives_the_same_sample_all_day_and_another_tomorrow():
    pool = [f"m{i}" for i in range(500)]
    a = S.seeded(pool, dt.date(2026, 11, 28), 20, "molecules")
    assert a == S.seeded(list(reversed(pool)), dt.date(2026, 11, 28), 20, "molecules")
    assert a != S.seeded(pool, dt.date(2026, 11, 29), 20, "molecules")
    assert len(a) == 20


def test_tuesday_reads_everything():
    assert S.is_full_read(dt.date(2026, 12, 1)) and not S.is_full_read(dt.date(2026, 11, 30))
    snap = S.load_snapshot(ROOT / "data" / "snapshots")
    mols, labs = S.choose(snap, dt.date(2026, 12, 1), full=True)
    assert len(mols) == len(snap["recs"]) and len(labs) == sum(1 for p in snap["products"].values() if S.is_dailymed(p))
    mols_d, labs_d = S.choose(snap, dt.date(2026, 11, 28), full=False)
    assert set(S.PINNED_MOLECULES) <= set(mols_d) and len(mols_d) <= len(S.PINNED_MOLECULES) + S.SAMPLE_MEDICINES + S.SAMPLE_OTHERS
    assert set(S.PINNED_LABELS) <= set(labs_d)


def test_every_pinned_entry_names_a_live_page_and_a_reason():
    snap = S.load_snapshot(ROOT / "data" / "snapshots")
    for s, why in S.PINNED_MOLECULES.items():
        assert s in snap["recs"] and len(why) > 20, s
    for s, why in S.PINNED_LABELS.items():
        assert S.is_dailymed(snap["products"][s]) and len(why) > 20, s


# ── check 2: labels ─────────────────────────────────────────────────────────────────────────────────────────────────
def spl(version: int, products: list[tuple[str, str, str]]) -> bytes:
    """An SPL with one product per (status, low, high)."""
    subj = "".join(
        f"<subject><manufacturedProduct><manufacturedProduct><name>P</name></manufacturedProduct>"
        f"<subjectOf><approval><code code='C73594' displayName='NDA'/></approval></subjectOf>"
        f"<subjectOf><marketingAct><statusCode code='{st}'/><effectiveTime><low value='{lo}'/>"
        + (f"<high value='{hi}'/>" if hi else "") + "</effectiveTime></marketingAct></subjectOf>"
        "</manufacturedProduct></subject>" for st, lo, hi in products)
    return (f"<document xmlns='urn:hl7-org:v3'><effectiveTime value='20240101'/><versionNumber value='{version}'/>"
            f"<component><structuredBody>{subj}</structuredBody></component></document>").encode()


def label(slug: str, setid: str, version: int = 3) -> dict:
    return {"slug": slug, "source": {"type": "dailymed", "setid": setid, "version": version, "effective": "20240101",
                                     "url": S.DAILYMED_PAGE.format(setid=setid)}}


A, B, C = ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "cccccccc-cccc-cccc-cccc-cccccccccccc")


def _classes(rv):
    return {(f["check"], f["shape"]): f for f in rv.findings}


def test_a_label_with_every_package_ended_is_found_at_once_and_one_still_marketed_is_not():
    rv = S.Review()
    labels = {"ended": label("ended", A), "live": label("live", B), "gone": label("gone", C)}
    resp = {A: S.Resp(200, {}, spl(3, [("completed", "2001", "20250101"), ("completed", "2001", "20261001")])),
            B: S.Resp(200, {}, spl(3, [("completed", "2001", "20250101"), ("active", "2001", "")])),
            C: S.Resp(404, {}, b"")}
    S.check_labels(rv, labels, resp, {}, TODAY, set())
    got = {(f["check"], f["subject"], f["shape"]) for f in rv.findings}
    assert ("gone", "ended", "every product on the label has ended") in got
    assert ("gone", "gone", "the set id no longer answers") in got
    assert not any(f["check"] == "gone" and f["subject"] == "live" for f in rv.findings)
    assert ("labels", "live", "some products on the label have ended") in got
    assert "gone" in S.IMMEDIATE


def test_a_package_whose_end_date_is_still_to_come_is_marketed_today():
    assert S.marketed_today({"status": "completed", "end": "20261231"}, TODAY)
    assert not S.marketed_today({"status": "completed", "end": "20261031"}, TODAY)
    assert not S.marketed_today({"status": "completed", "end": ""}, TODAY)
    assert S.marketed_today({"status": "active", "end": ""}, TODAY)


def test_a_newer_label_version_is_listed():
    rv = S.Review()
    S.check_labels(rv, {"x": label("x", A, version=3)}, {A: S.Resp(200, {}, spl(4, [("active", "2001", "")]))}, {}, TODAY, set())
    f = _classes(rv)[("labels", "the page cites an older version")]
    assert "version 3" in f["detail"] and "version 4" in f["detail"]


# ── check 3: approvals ──────────────────────────────────────────────────────────────────────────────────────────────
def fda_zip(rows: dict[str, list[str]]) -> bytes:
    """A Drugs@FDA data file: ApplNo -> the products' marketing status ids (1 Rx, 2 OTC, 3 Discontinued)."""
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("Applications.txt", "ApplNo\tApplType\tSponsorName\n" + "".join(f"{a}\tNDA\tX\n" for a in rows))
        z.writestr("MarketingStatus_Lookup.txt", "MarketingStatusID\tMarketingStatusDescription\n1\tPrescription\n2\t"
                   "Over-the-counter\n3\tDiscontinued\n")
        z.writestr("MarketingStatus.txt", "MarketingStatusID\tApplNo\tProductNo\n"
                   + "".join(f"{s}\t{a}\t{i:03d}\n" for a, ss in rows.items() for i, s in enumerate(ss, 1)))
    return b.getvalue()


def med(slug: str, application: str | None = None, **kw) -> dict:
    r = {"slug": slug, "scope_bucket": "prescription-medicine",
         "medicine_status": {"status": "prescription", "otc": [], "prescription": []}}
    if application:
        r["approval"] = {"regulator": "US Food and Drug Administration", "register": "Drugs@FDA", "application": application}
    r.update(kw)
    return r


def test_a_discontinued_application_is_found_and_a_current_one_is_not():
    fda = S.parse_fda_status(fda_zip({"012345": ["3", "3"], "054321": ["3", "1"]}))
    recs = {"gone-drug": med("gone-drug", "NDA 012345"), "kept-drug": med("kept-drug", "NDA 054321")}
    rv = S.Review()
    S.check_approvals(rv, recs, sorted(recs), fda, [], {}, set(), {}, TODAY, {})
    got = {(f["check"], f["subject"], f["shape"]) for f in rv.findings}
    assert ("approvals", "gone-drug", "a basis is discontinued") in got
    assert ("unauthorised", "gone-drug", "no basis is current") in got            # its only basis: at once
    assert not any(f["subject"] == "kept-drug" for f in rv.findings)
    assert "unauthorised" in S.IMMEDIATE


def test_a_basis_that_cannot_be_read_is_not_read_never_no_authorisation():
    recs = {"uk-drug": med("uk-drug", approval={"regulator": "MHRA", "register": "MHRA Products", "source": "https://products.mhra.gov.uk/x"})}
    rv = S.Review()
    S.check_approvals(rv, recs, sorted(recs), None, None, {}, set(), {}, TODAY, {})
    assert not rv.findings
    assert any(u["check"] == "unauthorised" and u["subject"] == "uk-drug" for u in rv.unread)


def test_a_molecule_with_no_authorisation_and_no_recorded_exception_is_still_a_finding():
    fda = S.parse_fda_status(fda_zip({"099999": ["3"]}))
    recs = {"phenazopyridine": med("phenazopyridine", "NDA 099999"), "lookalike": med("lookalike", "NDA 099999")}
    ex = {"phenazopyridine": {"ruled": "2026-11-28", "by": "Garrett", "why": "a ruling"}}
    rv = S.Review()
    out = S.check_approvals(rv, recs, sorted(recs), fda, [], {}, set(), {}, TODAY, ex)
    unauth = {f["subject"] for f in rv.findings if f["check"] == "unauthorised"}
    assert unauth == {"lookalike"}                                  # the exception is listed, never the class
    assert "phenazopyridine" in out["exceptions"]


def test_a_record_with_no_basis_at_all_is_its_own_class_not_the_alarm():
    rv = S.Review()
    S.check_approvals(rv, {"x": med("x")}, ["x"], None, None, {}, set(), {}, TODAY, {})
    assert [(f["check"], f["shape"]) for f in rv.findings] == [("approvals", "the record names no basis to check")]


def test_the_ruled_exceptions_are_read_from_one_place():
    ex = relationships.ruled_exceptions()
    assert set(ex) == {"phenibut", "flunitrazepam", "phenazopyridine"}
    assert ex["phenazopyridine"]["marketed"] == "unapproved"
    assert ex["phenazopyridine"]["label"]["category"] == "unapproved drug other"
    assert all(e["ruled"] and e["by"].startswith("Garrett") for e in ex.values())
    src = (ROOT / "moleculefinder_etl" / "review" / "sources.py").read_text()
    assert "relationships.ruled_exceptions()" in src and "approvals.yaml" not in src.split("def run(")[1].split("def main(")[0]


def test_an_exceptions_label_must_still_say_unapproved():
    lab = {"setid": A, "category": "unapproved drug other"}
    ex = {"phenazopyridine": {"ruled": "2026-11-28", "by": "Garrett", "why": "x", "marketed": "unapproved", "label": lab}}
    rec = med("phenazopyridine")
    rec["medicine_status"] = {"status": "unapproved", "otc": [], "prescription": []}
    for cat, found in (("unapproved drug other", False), ("NDA", True)):
        facts = {A: {"version": 15, "products": [{"name": "Pyridium", "category": cat, "status": "active", "end": ""}]}}
        rv = S.Review()
        S.check_approvals(rv, {"phenazopyridine": rec}, ["phenazopyridine"], None, None, facts, set(), {}, TODAY, ex)
        assert any(f["shape"] == "the label no longer says what the line says" for f in rv.findings) is found, cat


# ── check 1: links ──────────────────────────────────────────────────────────────────────────────────────────────────
def page(*hrefs: str) -> str:
    return "<html><body><main>" + "".join(f"<a href='{h}'>x</a>" for h in hrefs) + "</main></body></html>"


def test_a_link_answering_404_is_found_one_answering_is_not_and_a_request_access_page_is_not_read():
    ok, dead = "https://hcis.example.gov/", "https://gone.example.org/x"
    ecfr = "https://www.ecfr.gov/current/title-29/section-1910.1200"
    blocked = "https://blocked.example.org/"
    answers = {ok: (200, "<title>HCIS</title>", {}), dead: (404, "", {}),
               blocked: (200, "<html><title>Request Access</title></html>", {}),
               ecfr: (200, "<html><title>Request Access</title></html>", {}),
               "https://www.ecfr.gov/api/versioner/v1/versions/title-29.json?section=1910.1200":
                   (200, json.dumps({"content_versions": [{"removed": False}]}), {})}
    rv = S.Review()
    S.check_citations(rv, net(answers), {"/about/methodology": page(ok, dead, blocked, ecfr)})
    by = {f["subject"]: f for f in rv.findings}
    assert by[dead]["shape"] == "the link does not answer"
    assert ok not in by and ecfr not in by                          # eCFR answered through its own API
    assert blocked not in by and any(u["subject"] == blocked and "Request Access" in u["why"] for u in rv.unread)
    assert rv.compared[("links", "a citation on a method page")] == 3   # the blocked one is not counted as checked


def test_pubchem_and_wikidata_addresses_are_checked_through_their_own_data():
    recs = {"good": {"slug": "good", "cid": 1, "molecular_formula": "H2O", "molecular_weight": 18.015, "title": "Water",
                     "synonyms": ["Water"]},
            "lost": {"slug": "lost", "cid": 2, "molecular_formula": "CO2", "molecular_weight": 44.009, "title": "Carbon dioxide"}}
    rv = S.Review()
    S.check_props(rv, recs, {1: {"CID": 1, "MolecularFormula": "H2O", "MolecularWeight": "18.015", "Title": "Water"},
                             2: {"CID": 2}}, {})
    assert {(f["subject"], f["shape"]) for f in rv.findings} == {("lost", "the record no longer answers")}
    rv = S.Review()
    wd = {"a": {"slug": "a", "wikidata_qid": "Q1"}, "b": {"slug": "b", "wikidata_qid": "Q2"}}
    S.check_wikidata(rv, wd, {"Q1": {"id": "Q1"}, "Q2": {"id": "Q2", "missing": ""}}, {}, set(), dt.datetime.now(dt.UTC))
    assert [(f["subject"], f["shape"]) for f in rv.findings] == [("b", "the item no longer exists")]


# ── check 4: values ─────────────────────────────────────────────────────────────────────────────────────────────────
def _tox(*rows: str) -> bytes:
    return json.dumps({"Record": {"Reference": [{"ReferenceNumber": 1, "SourceName": "Hazardous Substances Data Bank (HSDB)"}],
                                  "Section": [{"Information": [{"ReferenceNumber": 1, "Value": {"StringWithMarkup": [
                                      {"String": r} for r in rows]}}]}]}}).encode()


def test_an_ld50_gone_upstream_is_found_and_said_to_be_held_when_the_hold_holds_it():
    r = {"slug": "levonorgestrel", "cid": 13109, "ld50_mg_per_kg": 5010.0, "ld50_species": "rat", "ld50_route": "oral"}
    rv = S.Review()
    S.check_ld50(rv, "levonorgestrel", r, S.Resp(200, {}, _tox("nothing here")), {"levonorgestrel": {"since": "2026-11-23"}})
    f = rv.findings[0]
    assert f["shape"] == "the LD50 the page shows is no longer on the record" and "the LD50 hold holds it since 2026-11-23" in f["detail"]
    rv = S.Review()
    S.check_ld50(rv, "x", r, S.Resp(200, {}, _tox("LD50 Rat oral 5010 mg/kg")), {})
    assert not rv.findings


def test_a_wikidata_change_the_age_rule_holds_is_not_a_surprise():
    r = {"x": {"slug": "x", "wikidata_qid": "Q1", "summary": "old words", "summary_source": "wikidata"}}
    now = dt.datetime(2026, 11, 28, tzinfo=dt.UTC)
    ent = {"Q1": {"id": "Q1", "modified": "2026-11-27T00:00:00Z", "descriptions": {"en": {"value": "new words"}}}}
    rv = S.Review()
    S.check_wikidata(rv, r, ent, {}, set(), now)
    assert rv.findings[0]["shape"] == "the description changed, held by the weekly run"
    ent["Q1"]["modified"] = "2026-10-01T00:00:00Z"
    rv = S.Review()
    S.check_wikidata(rv, r, ent, {}, set(), now)
    assert rv.findings[0]["shape"] == "the description changed"


# ── check 5: kinds and sources ──────────────────────────────────────────────────────────────────────────────────────
def test_a_value_with_no_kind_is_found_and_one_with_a_kind_is_not():
    good = {"slug": "g", "toxicity": [{"confidence": "from_source", "sources": ["hsdb"]}], "properties": []}
    bad = {"slug": "b", "toxicity": [{"sources": ["hsdb"]}], "properties": [{"key": "half_life_hours", "confidence": "guessed"}]}
    assert S.kind_problems(good) == []
    assert S.kind_problems(bad) == [("b.toxicity[0]", "no kind"), ("b.properties.half_life_hours", "kind 'guessed'")]


def test_a_blocked_or_unregistered_source_is_found():
    rv = S.Review()
    for key in ("drugbank", "nosuchsource", None, "pubchem"):
        S.check_source(rv, "x", "/m/x", f"x.{key}", key)
    assert [f["shape"] for f in rv.findings] == ["a value from a BLOCKED source", "a source the registry does not know",
                                                 "a value that cites no source"]


def test_every_value_in_the_committed_snapshot_has_its_kind_and_a_displayable_source():
    snap = S.load_snapshot(ROOT / "data" / "snapshots")
    rv = S.Review()
    S.check_kinds(rv, snap["recs"], snap["products"])
    assert rv.findings == []


def test_the_live_pages_lines_must_carry_their_chip_and_source():
    ok = ("<details class='srcnote'><summary>Sources and notes</summary><ul><li><b>Formula and weight</b>"
          "<span class='mf-chip mf-chip--computed'>computed</span><span class='srcnote__src'>PubChem</span></li></ul></details>"
          "<span class='kind kind--calculated'>Calculated</span>")
    rv = S.Review()
    S.check_page_kinds(rv, "x", {"molecular_formula": "H2O"}, f"<html><body><main>{ok}</main></body></html>")
    assert rv.findings == []
    rv = S.Review()
    S.check_page_kinds(rv, "x", {"molecular_formula": "H2O", "ld50_mg_per_kg": 1.0},
                       f"<html><body><main>{ok.replace('PubChem', '')}</main></body></html>")
    assert {f["shape"] for f in rv.findings} == {"a line with no chip or no named source",
                                                 "a value shown without its kind or its line"}


# ── the report and the queue ────────────────────────────────────────────────────────────────────────────────────────
def test_the_two_alarm_classes_queue_at_once_and_the_rest_on_two_runs(tmp_path):
    rv = S.Review()
    rv.check("gone", "a DailyMed label behind a live page", "xanax", "/whats-in/xanax", "every product on the label has ended")
    rv.check("labels", "a label's version", "zoloft", "/whats-in/zoloft", "the page cites an older version")
    classes = S.summarise(rv)
    added = S.queue(tmp_path, classes, None, dt.date(2026, 11, 28))
    assert len(added) == 1 and added[0].startswith("a live page rests on a label")
    added = S.queue(tmp_path, classes, {"classes": classes}, dt.date(2026, 11, 29))
    assert len(added) == 1 and added[0].startswith("a label's version")
    assert S.verdict_line(classes, 10, 5, 1, 7).startswith("VERDICT: A LIVE PAGE RESTS ON A SOURCE THAT HAS GONE (xanax)")


def test_the_review_only_reads():
    src = (ROOT / "moleculefinder_etl" / "review" / "sources.py").read_text()
    for word in ("write_json", "cache.write", "raw_cache\"", "SUPABASE", "requests.post", "method=\"POST\"", "git push"):
        assert word not in src, word
    with pytest.raises(RuntimeError):
        S._Session(net({})).request("POST", "https://zenodo.org/api/deposit")


def test_cli_names_the_review():
    cli = (ROOT / "moleculefinder_etl" / "cli.py").read_text()
    assert '"review", "sources"' in cli and "review_sources.main" in cli
