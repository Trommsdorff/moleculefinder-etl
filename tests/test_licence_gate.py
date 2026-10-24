"""The source-licence rule (2026-10-23): every source has a licence class, `may_display` is
derived from it, only displayable sources reach the snapshot, and the committed snapshot is
checked value by value."""
import json

import pytest

from moleculefinder_etl.config import SNAPSHOTS
from moleculefinder_etl.load import snapshot_export
from moleculefinder_etl.sources import registry
from moleculefinder_etl.sources.registry import LicenceRuleError
from moleculefinder_etl.transform import assemble, licence_gate
from moleculefinder_etl.transform.ghs import parse_ghs
from moleculefinder_etl.transform.toxicity import parse_ld50
from tests.fixtures import CAFFEINE_PROPS, canon_row, fetched, ghs_record, tox_record

HSDB = "Hazardous Substances Data Bank (HSDB)"
T3DB = "Toxin and Toxin Target Database (T3DB)"
ECHA = "European Chemicals Agency (ECHA)"
NITE = "NITE-CMC"


def _two_source_record(items: list[tuple[str, str]], heading="Non-Human Toxicity Values") -> dict:
    """A PUG-View record whose items each cite their own source: [(source name, string)]."""
    names = sorted({n for n, _ in items})
    refs = {n: i + 1 for i, n in enumerate(names)}
    return {"Record": {
        "Reference": [{"ReferenceNumber": refs[n], "SourceName": n} for n in names],
        "Section": [{"TOCHeading": heading, "Information": [
            {"ReferenceNumber": refs[n], "Value": {"StringWithMarkup": [{"String": s}]}} for n, s in items]}]}}


# ── the registry ────────────────────────────────────────────────────────────
def test_every_source_has_a_known_licence_class_and_display_follows_from_it():
    for key, s in registry.SOURCES.items():
        assert s.get("licence_class") in registry.LICENCE_CLASSES, key
        assert registry.may_display(key) is registry.LICENCE_CLASSES[s["licence_class"]][0]


def test_attribution_classes_carry_their_attribution_line():
    for key, s in registry.SOURCES.items():
        if registry.may_display(key) and registry.LICENCE_CLASSES[s["licence_class"]][1]:
            assert s.get("attribution"), f"{key} may be displayed only with attribution; it has none"


@pytest.mark.parametrize("key,shown", [
    ("hsdb", True), ("pubchem", True), ("wikidata", True), ("curated", True), ("echa", True),
    ("hcis", True), ("eu_clp", True), ("mhra", True), ("ema", True),
    ("t3db", False), ("nite", False), ("cas_registry", False), ("not-a-source", False), (None, False),
])
def test_may_display(key, shown):
    assert registry.may_display(key) is shown


def test_blocked_sources_are_never_displayable():
    for key in registry.BLOCKED:
        assert not registry.may_display(key)


def test_the_database_rows_keep_the_source_tables_columns():
    cols = {"key", "name", "license", "license_url", "homepage", "commercial_ok", "attribution_required"}
    assert all(set(r) == cols for r in registry.source_rows())


# ── the parsers keep only displayable sources ───────────────────────────────
def test_an_ld50_only_t3db_reports_never_reaches_the_rows():
    withheld = []
    rows = parse_ld50(_two_source_record([(T3DB, "LD50: 1944 mg/kg (Oral, Rat) (T14)"),
                                          (HSDB, "LD50 Rat oral 2400 mg/kg")]), withheld=withheld)
    assert [(r["value_num"], r["sources"]) for r in rows] == [(2400.0, ["hsdb"])]
    assert withheld == [{"species": "rat", "route": "oral", "value_num": 1944.0, "sources": [T3DB]}]


def test_a_row_both_sources_report_keeps_only_the_displayable_one():
    rows = parse_ld50(_two_source_record([(T3DB, "LD50: 192 mg/kg (Oral, Rat)"),
                                          (HSDB, "LD50 Rat oral 192 mg/kg")]))
    assert [(r["value_num"], r["sources"]) for r in rows] == [(192.0, ["hsdb"])]


def test_an_unregistered_or_unnamed_source_fails_closed():
    assert parse_ld50(tox_record(["LD50 Rat oral 192 mg/kg"], source="Some New Depositor")) == []
    assert parse_ld50(tox_record(["LD50 Rat oral 192 mg/kg"], source=None)) == []


def test_the_dataset_tracer_still_sees_every_source():
    rows = parse_ld50(_two_source_record([(T3DB, "LD50: 1944 mg/kg (Oral, Rat)")]), gate=False)
    assert rows[0]["sources"] == ["t3db"]


def test_ghs_ignores_a_restricted_source_and_names_the_ones_it_used():
    rec = _two_source_record([(NITE, "Danger"), (NITE, "H370: Causes damage to organs"),
                              (ECHA, "Warning"), (ECHA, "H302: Harmful if swallowed")],
                             heading="GHS Classification")
    withheld = []
    g = parse_ghs(rec, withheld=withheld)
    assert g["signal_word"] == "Warning" and g["h_statements"] == ["H302"] and g["sources"] == ["echa"]
    assert withheld == [NITE]
    assert parse_ghs(ghs_record(["Danger", "H370"], source=NITE)) is None


# ── assembly ────────────────────────────────────────────────────────────────
def test_a_cas_number_never_reaches_the_record():
    rec = assemble.assemble_record(canon_row(2519, "Caffeine"),
                                   fetched(CAFFEINE_PROPS, synonyms=["caffeine", "58-08-2"]), set())
    assert rec["cas"] is None


def test_a_curated_pin_no_source_reports_stops_the_build():
    curated = {"hooks": {"dose_poison": {"ld50_mg_per_kg": 47.2, "species": "rat", "route": "oral"}}}
    f = fetched(CAFFEINE_PROPS, curated=curated, toxicity=[
        {"endpoint": "LD50", "species": "mouse", "route": "oral", "value_num": 47.2, "unit": "mg/kg",
         "confidence": "from_source"}])
    with pytest.raises(LicenceRuleError, match="dose_poison pin 47.2"):
        assemble.assemble_record(canon_row(2519, "Caffeine"), f, set())


def test_the_hazard_hubs_cite_the_classifications_sources():
    rec = assemble.assemble_record(canon_row(2519, "Caffeine"), fetched(
        CAFFEINE_PROPS, ghs={"signal_word": "Danger", "pictograms": ["GHS06"], "h_statements": ["H301"],
                             "confidence": "from_source", "sources": ["echa", "hcis"]}), set())
    assemble.attach_derived_categories([rec])
    assert {c["source"] for c in rec["categories"] if c["kind"] == "poison"} == {"echa+hcis"}


# ── the gate ────────────────────────────────────────────────────────────────
def _clean(**over) -> dict:
    rec = {"slug": "x", "title": "X", "sources": ["pubchem"], "summary": "s", "summary_source": "wikidata",
           "toxicity": [{"species": "rat", "route": "oral", "value_num": 5.0, "sources": ["hsdb"]}],
           "ld50_mg_per_kg": 5.0, "ld50_species": "rat", "ld50_route": "oral",
           "ghs": {"signal_word": "Warning", "sources": ["echa"]}, "categories": [], "properties": []}
    return {**rec, **over}


def test_a_clean_record_passes():
    assert licence_gate.check_records([_clean()]) == []


@pytest.mark.parametrize("over,needle", [
    ({"cas": "58-08-2"}, "cas_registry"),
    ({"toxicity": [{"species": "rat", "route": "oral", "value_num": 5.0, "sources": ["t3db"]}]}, "t3db"),
    ({"toxicity": [{"species": "rat", "route": "oral", "value_num": 5.0}]}, "cites no source"),
    ({"ghs": {"signal_word": "Danger", "sources": ["nite"]}}, "nite"),
    ({"summary_source": "wikipedia"}, "no licence entry"),
    ({"ld50_mg_per_kg": 9.0}, "ld50_mg_per_kg: cites no source"),
    ({"approval": {"register": "Some Register"}}, "approval: cites no source"),
])
def test_the_gate_names_each_bad_citation(over, needle):
    found = licence_gate.check_records([_clean(**over)])
    assert any(needle in f for f in found), found


def test_a_comparison_may_quote_only_a_reported_figure():
    mols = [_clean(slug="a"), _clean(slug="b")]
    assert licence_gate.comparison_problems({"a-vs-b": {"a": "a", "b": "b", "text": "It is 5 mg/kg."}}, mols) == []
    found = licence_gate.comparison_problems({"a-vs-b": {"a": "a", "b": "b", "text": "It is 1,944 mg/kg."}}, mols)
    assert found and "1,944" in found[0]


def test_export_refuses_a_bad_value_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    with pytest.raises(LicenceRuleError):
        snapshot_export.export([_clean(cas="58-08-2")], {})
    assert not (tmp_path / "molecules").exists()


# ── the committed snapshot (what the site builds from) ──────────────────────
def test_the_committed_snapshot_passes_the_rule():
    assert (SNAPSHOTS / "molecules").is_dir()
    assert licence_gate.check_snapshot(SNAPSHOTS) == []


def test_the_committed_snapshot_carries_the_registry():
    shipped = json.loads((SNAPSHOTS / snapshot_export.SOURCES).read_text())["sources"]
    assert shipped == registry.public_registry()


def test_every_shown_ld50_is_a_row_a_displayable_source_reports():
    for p in (SNAPSHOTS / "molecules").glob("*.json"):
        m = json.loads(p.read_text())
        assert m.get("cas") is None, m["slug"]
        if m.get("ld50_mg_per_kg") is None:
            assert not any(h["type"] == "dose_poison" for h in m["hooks"]), m["slug"]
            continue
        lead = m["toxicity"][0]
        assert (lead["value_num"], lead["species"], lead["route"]) == (
            m["ld50_mg_per_kg"], m["ld50_species"], m["ld50_route"]), m["slug"]
        assert lead["sources"] and all(registry.may_display(s) for s in lead["sources"]), m["slug"]
