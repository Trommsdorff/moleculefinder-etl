"""The line under a molecule's name, and the parenthetical in its title (2026-09-12).

The stored PubChem synonyms have been sorted for determinism since run 3, and the page printed
the first four, so acetaminophen's line led with "4'-Hydroxyacetanilide". display_synonyms is a
separate list for reading: Wikidata's English label and aliases in Wikidata's order, then the
stored PubChem synonyms, kept only when a reader can use the name.
"""
from __future__ import annotations

import json

import pytest

from moleculefinder_etl.transform.assemble import display_synonyms


# ── The rules ───────────────────────────────────────────────────────────────
def test_wikidata_names_lead_in_their_own_order_then_pubchem():
    assert display_synonyms("Caffeine", ["caffeine", "guaranine", "methyltheobromine"],
                            ["Caffeine", "Cafipel", "Guaranine"]) == \
        ["guaranine", "methyltheobromine", "Cafipel"]


def test_acetaminophen_leads_with_paracetamol():
    """Replayed from the live item. Wikidata's English LABEL for Q57055 is "paracetamol" and
    "acetaminophen" is one of its aliases, so the label leads the Wikidata names; the aliases
    follow in the item's stored order."""
    wikidata = ["paracetamol", "p-acetylaminophenol", "acetaminofen4-(acetylamino)phenol",
                "N-acetyl-p-aminophenol4-hydroxyacetanilide", "N-(4-hydroxyphenyl)acetamide",
                "p-hydroxyacetanilide", "p-acetaminophenol", "acetaminophen", "APAP"]
    pubchem = ["Acetaminophen", "4'-Hydroxyacetanilide", "4-Acetamidophenol", "Acetaminofen",
               "Paracetamol", "Tylenol"]
    assert display_synonyms("Acetaminophen", wikidata, pubchem) == \
        ["paracetamol", "p-acetylaminophenol", "p-hydroxyacetanilide", "p-acetaminophenol"]


@pytest.mark.parametrize("name", ["4-acetamidophenol", "(RS)-ibuprofen", "Qutenza®", "U-18573",
                                  "D-(+)-Sucrose", "Alcohol, methyl", "caffeine (JP15)",
                                  "CHEBI:27732", "sodium;hydrogen carbonate"])
def test_only_letters_spaces_hyphens_and_apostrophes(name):
    assert display_synonyms("Title", [name], []) == []


def test_starts_with_a_letter():
    assert display_synonyms("Title", ["-ol", "'tis", " ok"], []) == ["ok"]


def test_apostrophes_straight_and_curly_are_allowed():
    assert display_synonyms("Title", ["confectioner's sugar", "baker’s yeast"], []) == \
        ["confectioner's sugar", "baker’s yeast"]


def test_twenty_five_characters_or_fewer():
    assert display_synonyms("Title", ["a" * 25, "b" * 26], []) == ["a" * 25]


def test_capitals_only_up_to_five_characters():
    assert display_synonyms("Title", ["APAP", "DEET", "GABAA", "CAFFEINE", "HUMAN INSULIN"], []) == \
        ["APAP", "DEET", "GABAA"]


def test_never_the_title_or_a_case_variant_of_it():
    assert display_synonyms("Sucrose", ["sucrose", "SUCROSE", "Sucrose", "saccharose"], []) == ["saccharose"]


def test_duplicates_compare_case_insensitively_and_keep_the_first():
    assert display_synonyms("Title", ["theine", "Theine", "THEINE"], ["theine"]) == ["theine"]


def test_at_most_four():
    assert display_synonyms("Title", ["a", "b", "c", "d", "e"], []) == ["a", "b", "c", "d"]


def test_letters_are_not_only_ascii():
    assert display_synonyms("Caffeine", ["teína", "β-carotene"], []) == ["teína", "β-carotene"]


def test_no_names_means_no_line():
    assert display_synonyms("Collagen", [None], ["Collagen"]) == []
    assert display_synonyms("Collagen", None, None) == []


def test_the_same_inputs_give_the_same_line():
    args = ("Ibuprofen", ["ibuprofen", "p-isobutylhydratropate", "ibuprophen"],
            ["Ibuprofen", "Advil", "Anflagen", "Brufen"])
    assert display_synonyms(*args) == display_synonyms(*args) == \
        ["p-isobutylhydratropate", "ibuprophen", "Advil", "Anflagen"]


# ── The record ──────────────────────────────────────────────────────────────
def test_the_record_carries_display_synonyms_and_keeps_its_search_list():
    from moleculefinder_etl.transform import assemble
    from tests.fixtures import canon_row, fetched, CAFFEINE_PROPS
    row = canon_row(2519, "Caffeine", qid="Q60235")
    row["wikidata_label"] = "caffeine"
    row["wikidata_aliases"] = ["guaranine", "1,3,7-trimethylxanthine", "theine"]
    rec = assemble.assemble_record(row, fetched(CAFFEINE_PROPS, synonyms=["caffeine", "Guaranine", "Koffein"]), set())
    assert rec["display_synonyms"] == ["guaranine", "theine", "Koffein"]
    assert rec["synonyms"] == ["Caffeine", "Guaranine", "Koffein"]


def test_a_hand_modeled_record_has_an_empty_line():
    from moleculefinder_etl.transform import assemble
    rec = assemble.assemble_handmodel({"cid": -5, "tier": "marquee"}, {"name": "Collagen"}, set())
    assert rec["display_synonyms"] == []


# ── Where the names come from ───────────────────────────────────────────────
class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


def test_names_come_from_wbgetentities_in_each_items_own_order(monkeypatch):
    from moleculefinder_etl.sources import wikidata
    seen: list[dict] = []

    def get(url, params=None, headers=None, timeout=None):
        seen.append({"url": url, **(params or {})})
        return _Resp({"entities": {q: {"labels": {"en": {"value": f"label {q}"}},
                                       "aliases": {"en": [{"value": "zeta"}, {"value": "alpha"}]}}
                                   for q in params["ids"].split("|")}})

    monkeypatch.setattr(wikidata.requests, "get", get)
    out = wikidata.names_for_qids([f"Q{i}" for i in range(1, 121)] + ["Q7", None])
    assert len(seen) == 3                                    # 120 distinct ids, 50 per request
    assert all(p["url"] == wikidata.WIKIDATA_API and p["action"] == "wbgetentities" for p in seen)
    assert all(p["props"] == "labels|aliases" and p["languages"] == "en" for p in seen)
    assert out["Q7"] == {"label": "label Q7", "aliases": ["zeta", "alpha"]}   # stored order, not sorted
    assert len(out) == 120


def test_a_missing_item_is_left_out_and_an_api_error_fails(monkeypatch):
    from moleculefinder_etl.sources import wikidata
    monkeypatch.setattr(wikidata.requests, "get",
                        lambda *a, **k: _Resp({"entities": {"Q1": {"id": "Q1", "missing": ""}}}))
    assert wikidata.names_for_qids(["Q1"]) == {}
    monkeypatch.setattr(wikidata.requests, "get",
                        lambda *a, **k: _Resp({"error": {"code": "maxlag", "info": "lagged"}}))
    with pytest.raises(RuntimeError, match="maxlag"):
        wikidata.names_for_qids(["Q1"])
    assert wikidata.names_for_qids([]) == {}


def test_the_chosen_item_brings_its_names(monkeypatch):
    """Selection is unchanged: the names are looked up for the item the rules chose."""
    from moleculefinder_etl.sources import wikidata
    rows = [{"cid": "650", "compound": "http://www.wikidata.org/entity/Q81978300", "desc": "chemical compound"},
            {"cid": "650", "compound": "http://www.wikidata.org/entity/Q650", "desc": "chemical element"}]
    monkeypatch.setattr(wikidata, "sparql", lambda *a, **k: rows)
    monkeypatch.setattr(wikidata, "names_for_qids",
                        lambda qids: {q: {"label": "fluorine", "aliases": ["F"]} for q in qids})
    assert wikidata.descriptions_for_cids([650])[650] == \
        {"qid": "Q650", "desc": "chemical element", "label": "fluorine", "aliases": ["F"]}


def test_a_cached_entry_without_names_is_fetched_again(tmp_path, monkeypatch):
    """The first run after this change must not reuse a fresh entry that predates the names."""
    from moleculefinder_etl import freshness
    from moleculefinder_etl.sources import cache
    from moleculefinder_etl.transform import canon
    monkeypatch.setattr(canon, "RAW_CACHE", tmp_path)
    monkeypatch.setattr(canon, "DESCRIPTIONS_CACHE", tmp_path / "wikidata" / "descriptions.json")
    monkeypatch.setattr(canon, "WIKIDATA_CACHE_TTL_DAYS", 6)
    monkeypatch.setattr(freshness, "PATH", tmp_path / "freshness.json")
    path = tmp_path / "wikidata" / "descriptions.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({cache.ENVELOPE_KEY: cache.ENVELOPE_VERSION, "fetched_at": cache.now(),
                                "entries": {"2519": {"desc": "stimulant", "qid": "Q60235",
                                                     "fetched_at": cache.now()}}}))
    calls: list[list[int]] = []

    def fake(cids):
        calls.append(list(cids))
        return {c: {"desc": "stimulant", "qid": "Q60235", "label": "caffeine", "aliases": ["guaranine"]}
                for c in cids}

    monkeypatch.setattr(canon.wikidata, "descriptions_for_cids", fake)
    assert canon._descriptions_cached([2519])[2519]["aliases"] == ["guaranine"]
    assert calls == [[2519]]
    canon._descriptions_cached([2519])                       # now it has names: a plain hit
    assert calls == [[2519]]


def test_names_attach_only_to_the_item_they_belong_to():
    from moleculefinder_etl.transform.canon import _apply_wikidata
    other = {"summary": None, "wikidata_qid": "Q1"}
    _apply_wikidata(other, {"desc": "d", "qid": "Q2", "label": "x", "aliases": ["y"]})
    assert "wikidata_aliases" not in other
    row = {"summary": None, "wikidata_qid": None}
    _apply_wikidata(row, {"desc": "d", "qid": "Q2", "label": "x", "aliases": ["y"]})
    assert row["wikidata_qid"] == "Q2" and row["wikidata_label"] == "x" and row["wikidata_aliases"] == ["y"]


def test_the_names_ride_the_canon_parquet_with_fixed_types(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from moleculefinder_etl.transform import canon
    rows = [{"cid": 2519, "wikidata_qid": "Q60235", "wikidata_label": "caffeine",
             "wikidata_aliases": ["guaranine", "theine"]},
            {"cid": 1, "wikidata_qid": None, "wikidata_label": None, "wikidata_aliases": None}]
    back = canon.read_parquet(canon.write_parquet(rows, tmp_path / "canon.parquet"))
    assert back[0]["wikidata_label"] == "caffeine" and back[0]["wikidata_aliases"] == ["guaranine", "theine"]
    assert back[1]["wikidata_label"] is None and back[1]["wikidata_aliases"] == []
    empty = canon.write_parquet([{"cid": 1}], tmp_path / "empty.parquet")
    schema = pq.read_schema(empty)
    assert schema.field("wikidata_label").type == pa.string()
    assert schema.field("wikidata_aliases").type == pa.list_(pa.string())
