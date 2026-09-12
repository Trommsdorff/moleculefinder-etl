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
    # "p-acetaminophenol" contains the title and "Acetaminofen" is two letters from it, so both go
    # (the near-duplicate rule, below) and APAP takes the fourth place.
    assert display_synonyms("Acetaminophen", wikidata, pubchem) == \
        ["paracetamol", "p-acetylaminophenol", "p-hydroxyacetanilide", "APAP"]


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
        ["p-isobutylhydratropate", "Advil", "Anflagen", "Brufen"]


# ── Near duplicates of the title (Garrett, 2026-09-12) ──────────────────────
@pytest.mark.parametrize("title,name", [
    ("Aciclovir", "Acyclovir"),                 # one letter, any case
    ("Aluminium", "aluminum"),                  # one letter
    ("Ibuprofen", "ibuprophen"),                # two letters
    ("Sulfur", "sulphur"),                      # two letters
    ("Aluminium", "Aluminium flake"),           # contains the title
    ("Caffeine", "anhydrous Caffeine"),         # contains it, any case
    ("Sodium bicarbonate", "bicarbonate"),      # sits inside it
    ("Aluminium", "Al"),                        # sits inside it, however short
    ("β-Alanine", "beta-alanine"),              # the title with its Greek letter spelled out
    ("β-Alanine", "Beta Alanine"),              # ...and one letter from that
])
def test_a_near_duplicate_of_the_title_is_dropped(title, name):
    assert display_synonyms(title, [name], []) == []


@pytest.mark.parametrize("title,name", [
    ("Caffeine", "Koffein"),                    # three letters away
    ("Aciclovir", "acycloguanosine"),
    ("Sodium bicarbonate", "baking soda"),
])
def test_three_letters_away_or_a_different_name_stays(title, name):
    assert display_synonyms(title, [name], []) == [name]


def test_the_four_are_counted_after_the_filter():
    """Aciclovir's names: the respelling goes and the next name moves up."""
    assert display_synonyms("Aciclovir", ["aciclovir", "acyclovir", "acycloguanosine", "zovirax", "ACV"],
                            ["Aciclovir", "Acyclovir", "Zovirax", "Zovir"]) == \
        ["acycloguanosine", "zovirax", "ACV", "Zovir"]


# ── The title's parenthetical (Garrett, 2026-09-12) ─────────────────────────
def _title_synonym(*args):
    from moleculefinder_etl.transform.assemble import title_synonym
    return title_synonym(*args)


def test_the_wikidata_label_when_it_differs_from_the_title():
    names = display_synonyms("Acetaminophen", ["paracetamol", "APAP"], ["Tylenol"])
    assert _title_synonym("Acetaminophen", "paracetamol", names, ["Sold as Tylenol."]) == "paracetamol"


def test_otherwise_the_first_name_the_page_itself_uses():
    names = ["sodium hydrogencarbonate", "baking soda", "monosodium carbonate", "bicarbonate of soda"]
    text = "Baking soda. It releases carbon dioxide when it meets an acid."
    assert _title_synonym("Sodium bicarbonate", "sodium bicarbonate", names, [text, None]) == "baking soda"
    # the why_it_matters text counts as much as the description
    assert _title_synonym("Sodium bicarbonate", None, names, [None, "Also bicarbonate of soda."]) == \
        "bicarbonate of soda"


def test_a_respelled_label_is_not_a_parenthetical():
    names = display_synonyms("Aluminum", ["aluminium", "element 13"], [])
    assert names == []
    assert _title_synonym("Aluminum", "aluminium", names, ["Aluminium is a light metal."]) is None


def test_a_name_counts_only_as_a_whole_word_in_any_case():
    assert _title_synonym("Title", None, ["tea"], ["Steam rises from it."]) is None
    assert _title_synonym("Title", None, ["tea"], ["TEA is mostly water."]) == "tea"


def test_never_a_second_parenthesis_and_nothing_when_nothing_matches():
    assert _title_synonym("Estradiol (medication)", "oestradiol", ["oestradiol"], ["oestradiol"]) is None
    assert _title_synonym("Caffeine", "caffeine", ["guaranine", "theine"],
                          ["The molecule behind coffee's lift."]) is None
    assert _title_synonym(None, "x", ["x"], ["x"]) is None


def test_every_record_gets_its_parenthetical_after_its_description():
    from moleculefinder_etl.transform import assemble
    recs = [{"cid": 1983, "title": "Acetaminophen", "display_synonyms": ["paracetamol", "APAP"],
             "description": "The pain reliever.", "why_it_matters": None},
            {"cid": 516892, "title": "Sodium bicarbonate", "display_synonyms": ["baking soda"],
             "description": "Baking soda.", "why_it_matters": {"text": "Baking soda."}},
            {"cid": 2519, "title": "Caffeine", "display_synonyms": ["guaranine"],
             "description": "Coffee's lift.", "why_it_matters": None}]
    assemble.attach_title_synonyms(recs, {1983: "paracetamol", 516892: "sodium bicarbonate"})
    assert [r["title_synonym"] for r in recs] == ["paracetamol", "baking soda", None]


def test_a_do_not_use_name_is_passed_over_by_both_rules():
    """Apigenin's page mentions chamomile and PubChem lists "chamomile" as a synonym, but a plant
    is not another name for the molecule."""
    skip = frozenset({"chamomile", "vitamin a"})
    assert _title_synonym("Apigenin", "apigenin", ["chamomile", "versulin"],
                          ["The yellow flavonoid in chamomile tea."], skip) is None
    # a listed label falls through to the text rule, which can still find a real name
    assert _title_synonym("Retinol", "vitamin A", ["vitamin A", "axerophthol"],
                          ["Also called axerophthol."], skip) == "axerophthol"


def test_the_seed_list_carries_its_names_with_reasons():
    import yaml
    from moleculefinder_etl.transform import assemble
    names = assemble.synonym_do_not_use()
    assert {"chamomile", "ephedra", "estrogen", "cochineal"} <= names
    assert all(n == n.casefold() for n in names)
    assert all(e["why"].strip() for e in yaml.safe_load(assemble.SYNONYM_DO_NOT_USE.read_text()))


def test_a_do_not_use_name_leaves_the_synonym_line_and_the_next_name_moves_up():
    """Apigenin's line read "chamomile · versulin"; a plant is not another name for it."""
    assert display_synonyms("Apigenin", ["apigenin", "Chamomile"], ["versulin", "Apigenine"],
                            frozenset({"chamomile"})) == ["versulin"]
    assert display_synonyms("Estradiol", [], ["estrogen", "Menorest", "Gynergon", "Estrace", "Climara"],
                            frozenset({"estrogen"})) == ["Menorest", "Gynergon", "Estrace", "Climara"]


def test_no_page_in_the_snapshot_shows_a_listed_name():
    """Neither on the synonym line nor in the title's parenthetical."""
    from moleculefinder_etl.config import SNAPSHOTS
    from moleculefinder_etl.transform import assemble
    listed = assemble.synonym_do_not_use()
    shown = []
    for path in sorted((SNAPSHOTS / "molecules").glob("*.json")):
        rec = json.loads(path.read_text())
        for name in [rec.get("title_synonym"), *(rec.get("display_synonyms") or [])]:
            if name and name.casefold() in listed:
                shown.append(f"{path.stem}: {name}")
    assert shown == []


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
