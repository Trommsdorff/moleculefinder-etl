"""A limit is not a value (Garrett's ruling, 2026-11-15, on the 2026-12-care review, decision 3).

Where a source reports an LD50 as "LD50 Rat oral > 10,000 mg/kg" (no animal died at the highest amount tested), the
figure is a lower bound. The parser used to read the ">" and throw it away, so 27 live pages (and titanium dioxide and
octinoxate, about to go live) showed the bound as if it were the LD50. A toxicity row now keeps the qualifier as
`qualifier`, the record's own LD50 as `ld50_qualifier`, and each is written only when the source gives one. Also here:
carboxymethyl cellulose's family (decision 4) and the paint list's white pigment (decision 5)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from moleculefinder_etl.config import SEEDS_DIR
from moleculefinder_etl.transform import assemble, toxicity

SNAP = Path(__file__).resolve().parents[1] / "data" / "snapshots"
HAVE_SNAP = (SNAP / "molecules" / "titanium-dioxide.json").exists()


def _pv(*strings: str) -> dict:
    return {"Record": {"Reference": [{"ReferenceNumber": 1, "SourceName": "Hazardous Substances Data Bank (HSDB)"}],
                       "Section": [{"Information": [{"ReferenceNumber": 1, "Value": {"StringWithMarkup": [
                           {"String": s} for s in strings]}}]}]}}


# ── the parser ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_greater_than_figure_keeps_its_qualifier():
    rows = toxicity.parse_ld50(_pv("LD50 Rat oral > 10,000 mg/kg", "LD50 Mouse oral 127 mg/kg"))
    by = {(r["species"], r["value_num"]): r for r in rows}
    assert by[("rat", 10000.0)]["qualifier"] == ">"
    assert "qualifier" not in by[("mouse", 127.0)]          # a plain value carries no key: absent means a value


@pytest.mark.parametrize("text, qual, value", [
    ("LD50 Rat oral >5000 mg/kg", ">", 5000.0),
    ("LD50 Rat oral > 4 g/kg", ">", 4000.0),
    ("LD50 Rat oral <50 mg/kg", "<", 50.0),
    ("LD50 Rat oral ~ 300 mg/kg", "~", 300.0),
    ("LD50: >8000 mg/kg (Oral, Rat)", ">", 8000.0),
])
def test_each_qualifier_the_parser_reads_is_kept(text, qual, value):
    (row,) = toxicity.parse_ld50(_pv(text))
    assert (row["qualifier"], row["value_num"]) == (qual, value)


def test_a_limit_and_a_value_at_the_same_figure_are_two_rows_and_the_value_leads():
    rows = toxicity.parse_ld50(_pv("LD50 Rat oral > 2000 mg/kg", "LD50 Rat oral 2000 mg/kg"))
    assert sorted(r.get("qualifier") or "" for r in rows) == ["", ">"]
    assert "qualifier" not in toxicity.primary_ld50(rows)


@pytest.mark.parametrize("text", [
    "LD50 Rat oral 3000-4000 mg/kg", "LD50 Rat oral more than 2000 mg/kg", "LD50 Rat oral greater than 3200 mg/kg",
    "LD50 Rat oral 180 +/- 45 mg/kg", "LD50 Hamster dermal > or = 10,000 mg/kg",
])
def test_the_shapes_it_never_read_are_still_skipped_whole(text):
    # No new shape: a range or a limit in words yields no row, so no value reaches the site from it.
    assert toxicity.parse_ld50(_pv(text)) == []


def test_the_words_every_surface_prints():
    assert toxicity.QUALIFIERS == {">": "more than", "<": "less than", "~": "about"}
    assert toxicity.words(">") == "more than " and toxicity.words(None) == ""


# ── the record ───────────────────────────────────────────────────────────────────────────────────────────────────
def _assembled(tox):
    rec = {"slug": "x", "toxicity": tox, "ld50_mg_per_kg": None, "ld50_route": None, "ld50_species": None}
    assemble._apply_primary_ld50(rec)
    return rec


def test_the_record_carries_the_qualifier_of_its_one_ld50_and_leads_with_that_row():
    rows = toxicity.parse_ld50(_pv("LD50 Rat oral > 10,000 mg/kg", "LD50 Rat dermal 500 mg/kg"))
    rec = _assembled(rows)
    assert (rec["ld50_mg_per_kg"], rec["ld50_qualifier"]) == (10000.0, ">")
    assert toxicity.row_key(rec["toxicity"][0]) == ("rat", "oral", 10000.0, ">")


def test_a_plain_ld50_writes_no_qualifier_key():
    rec = _assembled(toxicity.parse_ld50(_pv("LD50 Rat oral 192 mg/kg")))
    assert rec["ld50_mg_per_kg"] == 192.0 and "ld50_qualifier" not in rec


def test_the_oral_clause_says_more_than():
    rec = {"ld50_mg_per_kg": 10000.0, "ld50_route": "oral", "ld50_species": "rat", "ld50_qualifier": ">"}
    assert assemble._measure_clause(rec) == "Its reported oral LD50 is more than 10,000 mg/kg in the rat."


@pytest.mark.skipif(not HAVE_SNAP, reason="no snapshot")
def test_every_shipped_limit_is_carried_from_its_row():
    seen = 0
    for p in (SNAP / "molecules").glob("*.json"):
        m = json.loads(p.read_text())
        if m.get("ld50_mg_per_kg") is None:
            assert "ld50_qualifier" not in m, m["slug"]
            continue
        lead = m["toxicity"][0]
        assert lead.get("qualifier") == m.get("ld50_qualifier"), m["slug"]
        assert m.get("ld50_qualifier") in (None, *toxicity.QUALIFIERS), m["slug"]
        seen += bool(m.get("ld50_qualifier"))
    assert seen >= 29          # 27 live pages, titanium dioxide and octinoxate on 2026-11-15
    tio2 = json.loads((SNAP / "molecules" / "titanium-dioxide.json").read_text())
    assert (tio2["ld50_mg_per_kg"], tio2["ld50_qualifier"], tio2["ld50_species"], tio2["ld50_route"]) == (
        10000.0, ">", "rat", "oral")


# ── decisions 4 and 5 ────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not HAVE_SNAP, reason="no snapshot")
def test_carboxymethyl_cellulose_is_a_polysaccharide_as_cellulose_and_starch_are():
    for slug in ("carboxymethyl-cellulose", "cellulose", "starch"):
        m = json.loads((SNAP / "molecules" / f"{slug}.json").read_text())
        assert m["scope_family"] == "polysaccharide", slug
        assert [c["slug"] for c in m["categories"] if c["kind"] == "family"] == ["polysaccharide"], slug


def test_the_paint_list_names_titanium_dioxide_as_the_white_pigment_and_not_the_element():
    hubs = yaml.safe_load((SEEDS_DIR / "product_hubs.yaml").read_text())
    paint = {m["slug"]: m for m in hubs["paint-and-solvent"]["molecules"]}
    assert "titanium" not in paint
    assert paint["titanium-dioxide"]["presence"] == "added"
    assert paint["titanium-dioxide"]["presence_note"] == "The white pigment the maker adds."
    # the element had no other list to be on
    assert not any(m["slug"] == "titanium" for h in hubs.values() for m in h["molecules"])
