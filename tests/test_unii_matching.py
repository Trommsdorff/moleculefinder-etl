"""Trust run 3 (2026-10-24): the molecule side of the label join is the FDA's own UNII table.

Pinned here, on fixed inputs:
* ``_record_codes`` / ``unii_index``: a code reaches a record by the FDA's PubChem CID for it,
  by the FDA's exact InChIKey, by PubChem's synonym list (a ``UNII-`` entry, or a bare code the
  table lists; never a bare code it does not), or by the hand list's substances; the sources are
  a union; a code two records claim goes to the one holding it by the FDA's link or the hand
  list, and to neither when both or none do;
* ``parent_index``: the FDA's InChIKey skeleton decides a stereo form with no parent at all; a
  hand alias wins over the rules;
* ``_resolve``: an alias on an active's own code applies after its moiety reached nothing, and
  the two rules never do;
* ``warm``: the parent of an unclaimed label UNII is asked by the FDA's CID when the table has
  one (cached by CID), else by the synonym (cached by UNII); a fresh table is fetched once;
* ``compile_products``: every matched row and every not-in-catalog entry carries the code it
  was decided on, the report counts the index, and a pipeline run without the table refuses;
* ``write_unii_index``: one line per code, valid JSON.
"""
from __future__ import annotations

import json

import pytest

from moleculefinder_etl.sources import cache, fda_unii
from moleculefinder_etl.transform import products

CAFF_IK, THEO_IK, NAHSO3_IK = "RYYVLZVUVIJVGH-UHFFFAOYSA-N", "YAPQBXQYLJRXSA-UHFFFAOYSA-N", "DWAQJAXMDSEUJJ-UHFFFAOYSA-M"
LACT_IK, LLACT_IK = "JVTAAEKCZFNVCJ-UHFFFAOYSA-N", "JVTAAEKCZFNVCJ-REOHCLBHSA-N"


def _table(*rows):
    """rows: (unii, name, cid or None, inchikey or None[, the FDA's substance type: chemical])."""
    return fda_unii.Table({"file": "UNII_Records_test.txt",
                           "rows": [[*r, "chemical"] if len(r) == 4 else list(r) for r in rows]})


def _rec(slug, cid, inchikey=None, formula="C8H10N4O2"):
    return {"slug": slug, "cid": cid, "title": slug.replace("-", " ").title(), "inchikey": inchikey,
            "molecular_formula": formula}


RECORDS = [_rec("caffeine", 2519, CAFF_IK), _rec("theobromine", 5429, THEO_IK),
           _rec("sodium-bisulfite", 656672, NAHSO3_IK, "HNaO3S"), _rec("lactic-acid", 612, LACT_IK, "C3H6O3"),
           _rec("xanthan-gum", -2095734229, None, None), _rec("tirzepatide", 156588324, "AAPYRSPHYSKGIS-X-N")]

TABLE = _table(("3G6A5W338E", "CAFFEINE", 2519, CAFF_IK),
               ("W4FQ5G2V9X", "CAFFEINE, UNSPECIFIED", None, None),            # PubChem lists it bare
               ("TZX5469Z6I", "SODIUM BISULFITE", 18000336, NAHSO3_IK),         # another CID, same InChIKey
               ("3B8D35Y7S4", "LACTIC ACID, DL-", 612, LACT_IK),
               ("33X04XA5AT", "LACTIC ACID, UNSPECIFIED FORM", None, None),
               ("Q5K8X2M1V7", "L-LACTIC ACID", 107689, LLACT_IK),               # stereo form, own CID
               ("TTV12P4NEE", "XANTHAN GUM", None, None, "structurallyDiverse"),
               ("OYN3CCI6QE", "TIRZEPATIDE", None, None, "protein"),
               ("SHAREDCODE", "SHARED BY TWO RECORDS ON PUBCHEM", None, None),
               ("FDASAYSTHE", "THEOBROMINE PER THE FDA", 5429, THEO_IK),
               # Source-defined substances the FDA still links to a PubChem CID (a reference, not an
               # identity): cochineal to caffeine's CID here, corn syrup to a glucose whose parent is
               # lactic acid's CID here. Neither may join a record by any automatic route.
               ("TZ8Z31B35M", "COCHINEAL", 2519, CAFF_IK, "structurallyDiverse"),
               ("9G5L16BK6N", "CORN SYRUP", 5282499, None, "structurallyDiverse"))


def test_record_codes_fda_cid_then_inchikey_then_pubchem_as_a_union():
    got = products._record_codes(2519, CAFF_IK, ["UNII-3G6A5W338E", "W4FQ5G2V9X", "HMS3264B22", "UNII-ZZZZZZZZZ9"], TABLE)
    assert got == {"3G6A5W338E": "cid", "W4FQ5G2V9X": "pubchem", "ZZZZZZZZZ9": "pubchem"}
    # A bare code the table does not list is a screening id of the same shape, never a UNII.
    assert "HMS3264B22" not in got
    # The FDA links sodium bisulfite's code to another CID of the same structure: the InChIKey decides.
    assert products._record_codes(656672, NAHSO3_IK, [], TABLE) == {"TZX5469Z6I": "inchikey"}
    # A hand-modelled record (negative CID) reaches nothing on its own.
    assert products._record_codes(-2095734229, None, [], TABLE) == {}
    # No table: the old reading, UNII- entries only.
    assert products._record_codes(2519, CAFF_IK, ["UNII-3G6A5W338E", "W4FQ5G2V9X"], None) == {"3G6A5W338E": "pubchem"}


def test_unii_index_substances_conflicts_and_the_authority_rule():
    uniis = {2519: ["UNII-SHAREDCODE", "UNII-FDASAYSTHE"], 5429: ["UNII-SHAREDCODE"], 156588324: ["OYN3CCI6QE"]}
    subs = {"TTV12P4NEE": "xanthan-gum"}
    idx = products.unii_index(RECORDS, uniis, TABLE, subs)
    assert idx["3G6A5W338E"] == ("caffeine", "cid")
    assert idx["TZX5469Z6I"] == ("sodium-bisulfite", "inchikey")
    assert idx["TTV12P4NEE"] == ("xanthan-gum", "substance")
    assert idx["OYN3CCI6QE"] == ("tirzepatide", "pubchem")                  # bare, listed by the table
    assert "SHAREDCODE" not in idx                                          # two PubChem claims: neither
    assert idx["FDASAYSTHE"] == ("theobromine", "cid")                      # the FDA's link beats PubChem's listing
    assert "Q5K8X2M1V7" not in idx                                          # a stereo form is not the record
    # Two authoritative claims (the FDA's CID is one record, its InChIKey another): neither.
    t = _table(("TWOFDAHOWS", "X", 2519, THEO_IK))
    assert "TWOFDAHOWS" not in products.unii_index(RECORDS, {}, t, {})
    # A source-defined substance joins no record by the FDA's link or PubChem's list, only by hand.
    assert "TZ8Z31B35M" not in idx
    assert "TZ8Z31B35M" not in products.unii_index(RECORDS, {2519: ["UNII-TZ8Z31B35M"]}, TABLE, {})
    assert products.unii_index(RECORDS, {}, TABLE, {"TZ8Z31B35M": "caffeine"})["TZ8Z31B35M"] == ("caffeine", "substance")
    assert idx["TTV12P4NEE"] == ("xanthan-gum", "substance")                # the hand list carries one
    with pytest.raises(products.ProductSeedError, match="names no molecule"):
        products.unii_index(RECORDS, {}, TABLE, {"TTV12P4NEE": "no-such-slug"})
    with pytest.raises(products.ProductSeedError, match="not a UNII in the FDA table"):
        products.unii_index(RECORDS, {}, TABLE, {"NOTINTABLE": "xanthan-gum"})
    # Without a table, a substance is still carried and nothing is checked against the FDA.
    assert products.unii_index(RECORDS, {}, None, subs)["TTV12P4NEE"] == ("xanthan-gum", "substance")


def test_parent_index_uses_the_fda_inchikey_skeleton_and_an_alias_wins():
    # L-lactic acid: no parent looked up (PubChem has no UNII- synonym for it), but the FDA's
    # InChIKey shares lactic acid's skeleton, and nothing else does.
    got = products.parent_index(RECORDS, {"Q5K8X2M1V7": []}, {}, {}, TABLE)
    assert got == {"Q5K8X2M1V7": ("lactic-acid", "skeleton")}
    # A parent that IS a catalog CID would make it "parent"; an alias on the same code is final.
    got = products.parent_index(RECORDS, {"Q5K8X2M1V7": [612]}, {}, {"Q5K8X2M1V7": "caffeine"}, TABLE)
    assert got["Q5K8X2M1V7"] == ("caffeine", "alias")
    # One carbon is never reached by the skeleton rule (carbonate ion is not bicarbonate).
    recs = RECORDS + [_rec("bicarbonate", 769, "BVKZGUZCCUSVTD-UHFFFAOYSA-M", "CHO3-")]
    t = _table(("7UJQ5OPE7D", "CARBONATE ION", 19660, "BVKZGUZCCUSVTD-UHFFFAOYSA-L"))
    assert products.parent_index(recs, {"7UJQ5OPE7D": []}, {}, {}, t) == {}
    # Corn syrup's FDA CID has a parent that is a catalog CID; a source-defined substance is still
    # no form of that molecule, so neither rule applies to it. A hand alias would.
    assert products.parent_index(RECORDS, {"9G5L16BK6N": [612]}, {}, {}, TABLE) == {}
    assert products.parent_index(RECORDS, {"9G5L16BK6N": [612]}, {}, {"9G5L16BK6N": "lactic-acid"}, TABLE) == {
        "9G5L16BK6N": ("lactic-acid", "alias")}


def test_resolve_applies_an_alias_on_an_actives_own_code_but_never_a_rule():
    by_unii = {"3G6A5W338E": ("caffeine", "cid")}
    by_parent = {"0E53J927NA": ("magnesium-carbonate", "alias"), "ZNACET": ("acetic-acid", "parent")}
    active = {"role": "active", "name": "MAGNESIUM CARBONATE", "unii": "0E53J927NA", "moiety": ["7UJQ5OPE7D"]}
    assert products._resolve(active, by_unii, by_parent) == ("magnesium-carbonate", "alias", "0E53J927NA")
    zinc = {"role": "active", "name": "ZINC ACETATE", "unii": "ZNACET", "moiety": ["ZINC"]}
    assert products._resolve(zinc, by_unii, by_parent) == (None, None, None)
    direct = {"role": "inactive", "name": "CAFFEINE", "unii": "3G6A5W338E", "moiety": []}
    assert products._resolve(direct, by_unii, by_parent) == ("caffeine", "unii", "3G6A5W338E")
    moiety = {"role": "active", "name": "CAFFEINE CITRATE", "unii": "CAFCIT", "moiety": ["3G6A5W338E"]}
    assert products._resolve(moiety, by_unii, by_parent) == ("caffeine", "moiety", "3G6A5W338E")


def _label(*ings):
    return {"doc_type": "HUMAN PRESCRIPTION DRUG LABEL", "ingredients": list(ings),
            "active_lines": [], "purpose_lines": [], "purpose_rows": []}


def _ing(role, name, unii, moiety=()):
    return {"role": role, "name": name, "unii": unii, "moiety": list(moiety)}


SETID = "5d12e396-f82d-4c44-e063-6294a90ae291"
SEED = [{"slug": "mounjaro", "name": "Mounjaro", "kind": "medicine", "source": "dailymed", "item": SETID}]


def test_compile_rows_and_not_in_catalog_entries_carry_their_code_and_the_report_counts_the_index():
    label = _label(_ing("active", "TIRZEPATIDE", "OYN3CCI6QE"),
                   _ing("inactive", "CAFFEINE", "3G6A5W338E"), _ing("inactive", "XANTHAN GUM", "TTV12P4NEE"),
                   _ing("inactive", "SODIUM BISULFITE", "TZX5469Z6I"),
                   _ing("inactive", "L-LACTIC ACID", "Q5K8X2M1V7"), _ing("inactive", "TALC", "7SEV7J4R1U"),
                   _ing("inactive", "WATER", "059QF0KO0R"))
    uniis = {156588324: ["OYN3CCI6QE"], 2519: ["UNII-3G6A5W338E"]}
    passed, report = products.compile_products(
        RECORDS, SEED, spl=lambda s: label, parts={}, uniis=uniis, worlds=[], parents={"Q5K8X2M1V7": []},
        props={}, aliases={}, hubs={}, table=TABLE, substances={"TTV12P4NEE": "xanthan-gum"})
    (p,) = passed
    assert [(m["slug"], m["role"], m["match"], m["unii"]) for m in p["molecules"]] == [
        ("tirzepatide", "active", "unii", "OYN3CCI6QE"), ("caffeine", "inactive", "unii", "3G6A5W338E"),
        ("xanthan-gum", "inactive", "unii", "TTV12P4NEE"), ("sodium-bisulfite", "inactive", "unii", "TZX5469Z6I"),
        ("lactic-acid", "inactive", "skeleton", "Q5K8X2M1V7")]
    assert p["not_in_catalog"] == [{"name": "TALC", "role": "inactive", "unii": "7SEV7J4R1U"},
                                   {"name": "WATER", "role": "inactive", "unii": "059QF0KO0R"}]
    assert p["actives_not_in_catalog"] == []
    assert report["matched_by_code"] == {"unii": 4, "moiety": 0}
    assert report["matched_by_rule"] == {"parent": 0, "skeleton": 1, "alias": 0}
    # cid: caffeine, lactic acid (DL-) and theobromine; inchikey: sodium bisulfite; pubchem: tirzepatide
    # (bare, listed by the table); substance: xanthan gum. Six records hold a code.
    assert report["unii_index"] == {"fda_table": "UNII_Records_test.txt",
                                    "codes": {"cid": 3, "inchikey": 1, "pubchem": 1, "substance": 1},
                                    "molecules_with_a_code": 6}
    entries = report["unii_index_entries"]
    assert list(entries) == sorted(entries)
    assert entries["OYN3CCI6QE"] == {"slug": "tirzepatide", "how": "pubchem", "name": "TIRZEPATIDE"}
    assert entries["Q5K8X2M1V7"] == {"slug": "lactic-acid", "how": "skeleton", "name": "L-LACTIC ACID"}
    assert "7SEV7J4R1U" not in entries


def test_a_label_that_gives_no_code_for_an_ingredient_fails_the_gate_with_the_names():
    """Keflex's label names "Cellulose" and "FD&C Blue No. 1" with no UNII at all, and both are
    molecules here under other titles. Nothing can match a code-less row by code, and the page
    would call them not MoleculeFinder molecules on no evidence, so the label is not matched."""
    label = _label(_ing("active", "CEFALEXIN", "3G6A5W338E"), _ing("inactive", "CAFFEINE", "3G6A5W338E"),
                   _ing("inactive", "Cellulose", None), _ing("inactive", "FD&C Blue No. 1", None),
                   _ing("inactive", "Cellulose", None), _ing("inactive", "XANTHAN GUM", "TTV12P4NEE"))
    passed, report = products.compile_products(
        RECORDS, SEED, spl=lambda s: label, parts={}, uniis={2519: ["UNII-3G6A5W338E"]}, worlds=[], parents={},
        props={}, aliases={}, hubs={}, table=TABLE, substances={"TTV12P4NEE": "xanthan-gum"})
    assert passed == []
    (failure,) = report["failures"]
    assert failure["reason"] == ("the label gives no UNII code for 2 ingredient(s) (Cellulose, FD&C Blue No. 1), "
                                 "which cannot be matched by code")
    assert failure["matched"] == [] and failure["slug"] == "mounjaro"


def test_a_pipeline_run_without_the_table_refuses_and_a_test_run_may_pass_false(monkeypatch):
    monkeypatch.setattr(products.fda_unii, "cached", lambda *a, **k: None)
    label = _label(_ing("inactive", "CAFFEINE", "3G6A5W338E"))
    with pytest.raises(SystemExit, match="FDA UNII table is not in data/raw_cache"):
        products.compile_products(RECORDS, SEED, spl=lambda s: label, parts={}, uniis={}, worlds=[],
                                  parents={}, props={}, aliases={}, hubs={}, substances={})
    passed, _ = products.compile_products(RECORDS, SEED, spl=lambda s: label, parts={},
                                          uniis={2519: ["UNII-3G6A5W338E"]}, worlds=[], parents={}, props={},
                                          aliases={}, hubs={}, table=False, substances={})
    assert passed == []                                                     # one molecule: the gate


def test_warm_asks_parents_by_the_fda_cid_when_it_has_one_and_by_synonym_otherwise(tmp_path, monkeypatch):
    monkeypatch.setattr(products, "RAW_CACHE", tmp_path)
    monkeypatch.setattr(products, "DAILYMED_DIR", tmp_path / "dailymed")
    monkeypatch.setattr(products, "PARTS_CACHE", tmp_path / "wikidata" / "product_parts.json")
    monkeypatch.setattr(products, "load_unii_substances", lambda: {"TTV12P4NEE": "xanthan-gum"})
    label = _label(_ing("active", "L-LACTIC ACID", "Q5K8X2M1V7"), _ing("inactive", "XANTHAN GUM", "TTV12P4NEE"),
                   _ing("inactive", "LACTIC ACID, UNSPECIFIED FORM", "33X04XA5AT"),
                   _ing("inactive", "CAFFEINE", "3G6A5W338E"))
    (tmp_path / "dailymed").mkdir()
    cache.write_json(products._spl_path(SETID), label)
    by_cid, by_name, tables = [], [], []

    def table():
        tables.append(1)
        return TABLE
    stats = products.warm(SEED, [2519], lambda cids: {2519: ["UNII-3G6A5W338E"]}, lambda c: None,
                          fetch_parents=lambda u: by_name.append(u) or [],
                          fetch_table=table, fetch_cid_parents=lambda c: by_cid.append(c) or [612])
    assert by_cid == [107689] and by_name == ["33X04XA5AT"]                 # claimed codes are never asked
    assert tables == [1] and stats["fda_uniis"] == len(TABLE) and stats["parents_fetched"] == 2
    assert json.loads((tmp_path / "pubchem" / "parent-107689.json").read_text())["value"] == [612]
    assert json.loads((tmp_path / "pubchem" / "uniiparent-33X04XA5AT.json").read_text())["value"] == []
    assert products.read_parents(["Q5K8X2M1V7", "33X04XA5AT", "3G6A5W338E"], TABLE) == {
        "Q5K8X2M1V7": [612], "33X04XA5AT": []}
    products.warm(SEED, [2519], lambda cids: {2519: ["UNII-3G6A5W338E"]}, lambda c: None,
                  fetch_parents=lambda u: pytest.fail("asked again"), fetch_table=table,
                  fetch_cid_parents=lambda c: pytest.fail("asked again"))


def test_write_unii_index_is_one_line_per_code_and_valid_json(tmp_path):
    entries = {"3G6A5W338E": {"slug": "caffeine", "how": "cid", "name": "CAFFEINE"},
               "TTV12P4NEE": {"slug": "xanthan-gum", "how": "substance", "name": "XANTHAN GUM"}}
    path = tmp_path / "unii_index.json"
    products.write_unii_index(entries, path, TABLE)
    text = path.read_text()
    data = json.loads(text)
    assert data["uniis"] == entries and data["count"] == 2
    assert data["source"] == "FDA Substance Registration System (UNII_Records_test.txt)"
    assert data["how"] == {"direct": list(products.DIRECT_HOWS), "by_rule": list(products.RULE_HOWS)}
    assert sum(1 for line in text.splitlines() if line.startswith('  "')) == 2
    products.write_unii_index({}, path, None)
    assert json.loads(path.read_text()) == {"source": None, "how": data["how"], "count": 0, "uniis": {}}
