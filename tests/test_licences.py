"""Licence records for every medicine, from the regulators' own registers (growth plan run B2).

Drugs@FDA first, then the EMA's centrally authorised medicines, then the MHRA products database
(read by hand into licences_mhra.yaml); the six hand rulings in approvals.yaml stay as they are. A
medicine found in none of the three gets no record and is listed by name, never guessed."""
from __future__ import annotations

import json
import re
import zipfile

import pytest
import yaml

from moleculefinder_etl import licences as L
from moleculefinder_etl.config import SNAPSHOTS
from moleculefinder_etl.transform import relationships

# The hand rulings that carry no regulator URL (Garrett's rulings of 2026-10-18; kept as they are).
HAND_WITHOUT_SOURCE = {"meldonium", "phenibut", "clenbuterol", "clostebol"}


def _seed():
    return yaml.safe_load(L.LICENCES_YAML.read_text()) or {}


def _medicines():
    return L.medicines_of(L.load_catalog())


# ── The committed records ────────────────────────────────────────────────────────────────────
def test_every_record_names_its_regulator_and_a_regulator_source():
    """Every medicine's licence record names its regulator and its source, and no record cites
    anything but a regulator's own site (no news, no Wikipedia, no DailyMed as the source)."""
    hand = relationships.load_approvals()
    for slug, rec in {**_seed(), **hand}.items():
        assert rec.get("regulator"), slug
        if slug in HAND_WITHOUT_SOURCE:
            assert not rec.get("source"), f"{slug}: now has a source; drop it from HAND_WITHOUT_SOURCE"
            continue
        assert rec.get("source"), f"{slug}: no source"
        assert relationships.is_regulator_url(rec["source"]), f"{slug}: {rec['source']}"
    for slug, rec in _seed().items():
        assert rec["register"] in (L.REGISTER_FDA, L.REGISTER_EMA, L.REGISTER_MHRA), slug
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", rec["read"]), slug
        assert rec["regulator"] == {L.REGISTER_FDA: L.FDA, L.REGISTER_EMA: L.EC, L.REGISTER_MHRA: L.MHRA}[rec["register"]]


def test_no_record_cites_a_non_regulator_source():
    for url in ("https://en.wikipedia.org/wiki/Sertraline", "https://www.reuters.com/x",
                "https://dailymed.nlm.nih.gov/dailymed/", "http://www.fda.gov/x", "https://fda.gov.evil.com/",
                "https://notfda.gov/x", ""):
        assert not relationships.is_regulator_url(url), url
    for url in ("https://www.accessdata.fda.gov/scripts/cder/daf/", "https://www.ema.europa.eu/en/medicines/x",
                "https://products.mhra.gov.uk/substance/?substance=X", "https://api.aifa.gov.it/x"):
        assert relationships.is_regulator_url(url), url


def test_every_medicine_has_a_record_or_is_listed_by_name():
    meds = _medicines()
    hand = set(relationships.load_approvals())
    seed = _seed()
    header = L.LICENCES_YAML.read_text().split("\n\n", 1)[0]
    listed = set(re.findall(r"^#   (.+)$", header.split("in none of the three", 1)[1], re.MULTILINE))
    for m in meds:
        has = m["slug"] in seed or m["slug"] in hand
        assert has != (m["title"] in listed), m["slug"]
    assert set(seed) <= {m["slug"] for m in meds}            # medicines only
    assert not (set(seed) & hand)                           # the hand rulings are not re-recorded


def test_the_hand_rulings_are_untouched():
    hand = relationships.load_approvals()
    assert set(hand) == {"orforglipron", "meldonium", "phenibut", "clenbuterol", "clostebol", "flunitrazepam"}
    recs = [{"slug": m["slug"], "scope_bucket": m.get("scope_bucket")} for m in L.load_catalog()]
    relationships.attach_approvals(recs)
    relationships.attach_licences(recs)
    by = {r["slug"]: r for r in recs}
    for s, e in hand.items():
        assert by[s]["approval"] == {k: str(v) for k, v in e.items()}, s
    assert by["sertraline"]["approval"]["register"] == "Drugs@FDA"


def test_mhra_file_entries_are_medicines_and_carry_a_substance_and_date():
    meds = {m["slug"] for m in _medicines()}
    mhra = L.load_mhra()
    assert set(mhra) <= meds
    for slug, c in mhra.items():
        assert c.source.startswith("https://products.mhra.gov.uk/substance/?substance="), slug


# ── attach_licences refuses a bad record ─────────────────────────────────────────────────────
def _write(tmp_path, monkeypatch, data):
    p = tmp_path / "licences.yaml"
    p.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(relationships, "LICENCES_YAML", p)


GOOD = {"regulator": L.FDA, "register": L.REGISTER_FDA, "basis": "x", "read": "2026-10-21",
        "source": "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?ApplNo=1"}


def test_a_news_or_wikipedia_source_fails_the_build(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"sertraline": {**GOOD, "source": "https://en.wikipedia.org/wiki/Sertraline"}})
    with pytest.raises(SystemExit) as err:
        relationships.attach_licences([{"slug": "sertraline", "scope_bucket": "prescription-medicine"}])
    assert "not a regulator's site" in str(err.value)


@pytest.mark.parametrize("change,message", [
    ({"read": None}, "missing ['read']"),
    ({"regulator": None}, "missing ['regulator']"),
    ({"nonsense": 1}, "unknown field"),
])
def test_a_missing_or_unknown_field_fails_the_build(tmp_path, monkeypatch, change, message):
    rec = {k: v for k, v in {**GOOD, **change}.items() if v is not None}
    _write(tmp_path, monkeypatch, {"sertraline": rec})
    with pytest.raises(SystemExit) as err:
        relationships.attach_licences([{"slug": "sertraline", "scope_bucket": "prescription-medicine"}])
    assert message in str(err.value)


def test_an_unknown_slug_or_a_non_medicine_fails_the_build(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"nosuch": GOOD, "caffeine": GOOD})
    with pytest.raises(SystemExit) as err:
        relationships.attach_licences([{"slug": "caffeine", "scope_bucket": "food-flavor"}])
    assert "nosuch: unknown slug" in str(err.value) and "caffeine: not a medicine" in str(err.value)


def test_combination_is_a_boolean_on_the_record(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"simeticone": {**GOOD, "combination": True, "product": "Imodium"}})
    recs = [{"slug": "simeticone", "scope_bucket": "otc-medicine"}]
    relationships.attach_licences(recs)
    assert recs[0]["approval"]["combination"] is True and recs[0]["approval"]["product"] == "Imodium"


# ── Matching ─────────────────────────────────────────────────────────────────────────────────
def test_an_ingredient_matches_its_name_with_salt_words_only():
    names = {"sertraline", "citalopram"}
    assert L.ingredient_matches("SERTRALINE HYDROCHLORIDE", names)
    assert L.ingredient_matches("Citalopram hydrobromide", names)
    assert not L.ingredient_matches("ESCITALOPRAM OXALATE", names)        # a different molecule
    assert not L.ingredient_matches("SERTRALINE EXTRACT", names)          # not a salt word
    assert L.ingredient_matches("TESTOSTERONE CYPIONATE", {"testosterone"})


def test_a_leading_parenthesis_is_part_of_the_name_and_a_parent_alias_is_not_used():
    rec = {"slug": "escitalopram", "title": "Escitalopram", "preferred_name": None, "wikipedia_title": None}
    canon = {"wikidata_label": "escitalopram", "wikidata_aliases": ["(S)-citalopram", "citalopram", "Lexapro"]}
    names = L.medicine_names(rec, canon, others={"omeprazole"})
    assert "citalopram" not in names and "s citalopram" in names and "lexapro" in names
    est = {"slug": "x", "title": "Estradiol (medication)", "preferred_name": None, "wikipedia_title": None}
    assert L.medicine_names(est, None) == {"estradiol"}
    eso = {"slug": "esomeprazole", "title": "Esomeprazole", "preferred_name": None, "wikipedia_title": None}
    assert "omeprazole" not in L.medicine_names(eso, {"wikidata_aliases": ["omeprazole"]}, others={"omeprazole"})


def test_another_molecules_name_is_not_used_even_when_wikidata_lists_it():
    rec = {"slug": "levofloxacin", "title": "Levofloxacin", "preferred_name": None, "wikipedia_title": None}
    assert "ketamine" not in L.medicine_names(rec, {"wikidata_aliases": ["ketamine"]}, others={"ketamine"})


def _fda_zip(tmp_path, products, statuses, apps, subs):
    def tsv(header, rows):
        return "\t".join(header) + "\r\n" + "".join("\t".join(r) + "\r\n" for r in rows)
    p = tmp_path / "fda.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Products.txt", tsv(["ApplNo", "ProductNo", "Form", "Strength", "ReferenceDrug", "DrugName",
                                        "ActiveIngredient", "ReferenceStandard"], products))
        z.writestr("MarketingStatus.txt", tsv(["MarketingStatusID", "ApplNo", "ProductNo"], statuses))
        z.writestr("MarketingStatus_Lookup.txt", tsv(["MarketingStatusID", "MarketingStatusDescription"],
                   [["1", "Prescription"], ["2", "Over-the-counter"], ["3", "Discontinued"],
                    ["4", "None (Tentative Approval)"]]))
        z.writestr("Applications.txt", tsv(["ApplNo", "ApplType", "ApplPublicNotes", "SponsorName"], apps))
        z.writestr("Submissions.txt", tsv(["ApplNo", "SubmissionClassCodeID", "SubmissionType", "SubmissionNo",
                                           "SubmissionStatus", "SubmissionStatusDate", "SubmissionsPublicNotes",
                                           "ReviewPriority"], subs))
    return p


def test_fda_counts_only_marketed_products_and_prefers_the_original_single_ingredient_application(tmp_path):
    z = _fda_zip(tmp_path,
                 products=[["019839", "001", "TABLET;ORAL", "50MG", "1", "ZOLOFT", "SERTRALINE HYDROCHLORIDE", "0"],
                           ["018000", "001", "TABLET;ORAL", "50MG", "0", "OLDSERT", "SERTRALINE HYDROCHLORIDE", "0"],
                           ["077000", "001", "TABLET;ORAL", "50MG", "0", "SERTRALINE HYDROCHLORIDE",
                            "SERTRALINE HYDROCHLORIDE", "0"],
                           ["090000", "001", "TABLET;ORAL", "1MG", "0", "COMBO", "SERTRALINE HYDROCHLORIDE; OTHER", "0"]],
                 statuses=[["1", "019839", "001"], ["3", "018000", "001"], ["1", "077000", "001"], ["1", "090000", "001"]],
                 apps=[["019839", "NDA", "", "VIATRIS"], ["018000", "NDA", "", "X"], ["077000", "ANDA", "", "Y"],
                       ["090000", "NDA", "", "Z"]],
                 subs=[["019839", "1", "ORIG", "1", "AP", "1991-12-30 00:00:00", "", ""],
                       ["018000", "1", "ORIG", "1", "AP", "1980-01-01 00:00:00", "", ""],
                       ["077000", "1", "ORIG", "1", "AP", "2006-01-01 00:00:00", "", ""],
                       ["090000", "1", "ORIG", "1", "AP", "1970-01-01 00:00:00", "", ""]])
    products = L.parse_fda(z)
    assert {p["appl_no"] for p in products} == {"019839", "077000", "090000"}      # discontinued dropped
    c = L.fda_candidates({"sertraline"}, products)
    assert [x.application for x in c] == ["NDA 019839", "ANDA 077000", "NDA 090000"]
    rec = L.record_from(c[0], "2026-10-21")
    assert rec["product"] == "Zoloft" and rec["authorised"] == "1991-12-30" and "combination" not in rec
    assert rec["source"].endswith("ApplNo=019839")
    assert "product" not in L.record_from(c[1], "2026-10-21")      # a generic under its own name
    assert L.record_from(c[2], "2026-10-21")["combination"] is True


def test_ema_counts_only_authorised_human_medicines(tmp_path):
    rows = [
        {"category": "Human", "medicine_status": "Authorised", "name_of_medicine": "Valdoxan",
         "ema_product_number": "EMEA/H/C/000915", "active_substance": "agomelatine",
         "international_non_proprietary_name_common_name": "agomelatine", "generic": "No", "biosimilar": "No",
         "marketing_authorisation_developer_applicant_holder": "Servier", "marketing_authorisation_date": "19/02/2009",
         "medicine_url": "https://www.ema.europa.eu/en/medicines/human/EPAR/valdoxan"},
        {"category": "Human", "medicine_status": "Withdrawn", "name_of_medicine": "Thymanax",
         "ema_product_number": "EMEA/H/C/000916", "active_substance": "agomelatine",
         "international_non_proprietary_name_common_name": "agomelatine", "generic": "No", "biosimilar": "No",
         "marketing_authorisation_date": "19/02/2009", "medicine_url": "https://www.ema.europa.eu/x"},
        {"category": "Veterinary", "medicine_status": "Authorised", "name_of_medicine": "Vet",
         "ema_product_number": "EMEA/V/C/1", "active_substance": "agomelatine",
         "international_non_proprietary_name_common_name": "", "medicine_url": "https://www.ema.europa.eu/y"},
    ]
    p = tmp_path / "ema.json"
    p.write_text(json.dumps({"data": rows}))
    c = L.ema_candidates({"agomelatine"}, L.parse_ema(p))
    assert len(c) == 1
    rec = L.record_from(c[0], "2026-10-21")
    assert rec["regulator"] == L.EC and rec["application"] == "EMEA/H/C/000915"
    assert rec["authorised"] == "2009-02-19" and rec["product"] == "Valdoxan"


def test_build_takes_fda_then_ema_then_mhra_and_lists_the_rest(tmp_path):
    def m(slug, title):
        return {"slug": slug, "cid": 1, "title": title, "scope_bucket": "prescription-medicine"}
    meds = [m("a", "Alphamab"), m("b", "Betazine"), m("c", "Ceemol"), m("d", "Deltine")]
    fda = [{"appl_no": "1", "appl_type": "NDA", "sponsor": "", "drug_name": "ALPHA", "ingredients": ["ALPHAMAB"],
            "status": "Prescription", "form": "", "orig_date": "2000-01-01"}]
    ema = [{"name": "Beta", "number": "EMEA/H/C/1", "substances": ["betazine"], "inn": ["betazine"],
            "generic": False, "biosimilar": False, "holder": "", "authorised": "2010-01-01",
            "url": "https://www.ema.europa.eu/b"}]
    mhra = {"c": L.Candidate(L.REGISTER_MHRA, L.MHRA, "", "Cee", None, None,
                             "https://products.mhra.gov.uk/substance/?substance=CEEMOL", "x", True, ("2026-10-20",))}
    recs, missing = L.build(meds, {}, fda, ema, mhra, read="2026-10-21")
    assert {k: v["register"] for k, v in recs.items()} == {"a": "Drugs@FDA", "b": "European Medicines Agency",
                                                          "c": "MHRA Products"}
    assert recs["c"]["read"] == "2026-10-20" and "application" not in recs["c"]
    assert missing == ["Deltine"]


def test_the_build_reads_only_the_committed_file(monkeypatch):
    """`mfetl all` never fetches a register: attach_licences opens licences.yaml and nothing else."""
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("a build fetched a register"))
    snap = {p.stem: json.loads(p.read_text()) for p in (SNAPSHOTS / "molecules").glob("*.json")}
    recs = [{"slug": s, "scope_bucket": r.get("scope_bucket")} for s, r in snap.items()]
    relationships.attach_approvals(recs)
    relationships.attach_licences(recs)
    assert sum(1 for r in recs if r.get("approval")) == len(_seed()) + len(relationships.load_approvals())


def test_title_case_keeps_release_suffixes():
    assert L._title_case("EFFEXOR XR") == "Effexor XR"
    assert L._title_case("PEPCID AC") == "Pepcid AC"
    assert L._title_case("Valdoxan") == "Valdoxan"


def test_the_seed_is_sorted_and_says_what_it_is():
    text = L.LICENCES_YAML.read_text()
    assert text.startswith("# Licence records for medicines")
    assert "GENERATED by `mfetl licences`" in text
    keys = list(yaml.safe_load(text))
    assert keys == sorted(keys)


def test_mhra_file_rejects_an_entry_without_a_substance(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("x: {product: Y, read: '2026-10-21'}\n")
    with pytest.raises(SystemExit):
        L.load_mhra(p)
