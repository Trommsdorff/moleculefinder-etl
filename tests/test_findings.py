"""The dyes-in-medicines finding (findings run, 2026-11-21): the seed's codes resolve, a dye is a
code and never a name, the totals equal the table, the FDA statements come only from the FDA, and
the committed snapshot's file is the one the compiler would write."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from moleculefinder_etl.load import snapshot_export
from moleculefinder_etl.sources import dailymed, fda_unii, registry
from moleculefinder_etl.transform import findings, products

ROOT = Path(__file__).resolve().parent.parent
SNAP = ROOT / "data" / "snapshots"
FILE = SNAP / "findings" / "dyes-in-medicines.json"
CLAIM_WORDS = re.compile(r"\b(only|first|most|leading|largest|world's|never|always)\b", re.IGNORECASE)
DASH = re.compile("[–—]")

BLUE1, BLUE1_LAKE, RED40, RED3, DC_Y10 = "H3R47K3TBD", "J9EQA3S2JM", "WZB9127XOA", "PN2ZH5LOQY", "35SW5USQ3G"
YELLOW6, BLUE2, BLUE2_PART = "H77VEI93A8", "L06K8R7DQK", "D3741U8K7L"


def _product(slug, name, ings, *, doc="HUMAN OTC DRUG LABEL", kind="medicine", version=3, actives_missing=None):
    return {"slug": slug, "name": name, "kind": kind,
            "source": {"type": "dailymed", "setid": f"setid-{slug}", "labeler": "Acme", "doc_type": doc,
                       "version": version, "effective": "20260101", "url": f"https://dailymed.example/{slug}"},
            "molecules": [], "not_in_catalog": [], "actives_not_in_catalog": actives_missing or [],
            "_ings": ings}


def _labels(prods):
    return {p["source"]["setid"]: {"ingredients": [{"unii": u, "name": n, "role": "inactive"} for u, n in p["_ings"]]}
            for p in prods}


def _compile(prods, routes=None):
    labels = _labels(prods)
    return findings.compile_dyes(prods, spl=lambda s: labels.get(s), routes=routes or (lambda s, v: None))


# ── the seed ──────────────────────────────────────────────────────────────────
def test_the_seed_validates_and_the_six_group_is_exactly_the_six():
    c = findings.load_colours()
    six = sorted(d["id"] for d in c["dyes"] if d["group"] == "six")
    assert six == sorted(findings.SIX_ORDER)
    assert [d["id"] for d in c["dyes"] if d["group"] == "red-3"] == ["red-3"]
    assert c["checked"] == "2026-11-21"


def test_every_code_is_a_unii_used_once_and_carries_the_registry_check():
    c = findings.load_colours()
    codes = [x["unii"] for d in c["dyes"] for x in d["codes"]]
    assert len(codes) == len(set(codes)) == len(c["by_unii"])
    assert all(fda_unii.UNII_RE.match(u) for u in codes)
    assert all(x["gsrs_name"] and x["gsrs_status"] for d in c["dyes"] for x in d["codes"])
    assert not {n["unii"] for n in c["not_counted"]} & set(codes)


@pytest.mark.skipif(fda_unii.cached() is None, reason="the FDA UNII table is not in data/raw_cache here")
def test_the_seeds_codes_resolve_in_the_fdas_table_to_the_name_the_registry_check_recorded():
    table = fda_unii.cached()
    c = findings.load_colours()
    for d in c["dyes"]:
        for x in d["codes"]:
            assert x["unii"] in table, f"{x['unii']} ({d['name']}) is not in the FDA's UNII table"
            assert table.name(x["unii"]).upper() == x["gsrs_name"].upper(), x["unii"]
    for n in c["not_counted"]:
        assert table.name(n["unii"]).upper() == n["gsrs_name"].upper()


def test_a_bad_seed_names_every_problem(tmp_path):
    bad = tmp_path / "c.yaml"
    bad.write_text(yaml.safe_dump({"checked": "2026-11-21", "dyes": [
        {"id": "x", "name": "X", "group": "nope", "codes": [{"unii": "short", "form": "dye"}]}]}))
    with pytest.raises(findings.FindingsError) as e:
        findings.load_colours(bad)
    msg = str(e.value)
    assert "group must be one of" in msg and "is not a UNII" in msg and "six group" in msg


# ── what the FDA said ─────────────────────────────────────────────────────────
def test_every_fda_statement_is_from_the_fda_or_the_federal_register_with_a_link_and_the_date_read():
    s = findings.load_statements()
    assert s["read"] == "2026-11-21"
    ids = [x["id"] for x in s["statements"]]
    assert {"red3-order", "red3-stay", "six-announcement", "six-tracker"} <= set(ids)
    for x in s["statements"]:
        assert x["source"] in ("fda", "federal_register")
        assert re.match(r"^https://(www\.)?(fda\.gov|federalregister\.gov)/", x["url"])
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", x["date"])
        assert x["quote"] and x["says"]


def test_the_words_the_page_prints_have_no_dash_no_claim_word_and_no_word_of_harm_or_safety():
    s = findings.load_statements()
    printed = [x["says"] for x in s["statements"]] + list(s["selection"].values())
    for text in printed:
        assert not DASH.search(text), text
        assert not CLAIM_WORDS.search(text), text
        assert not re.search(r"\b(harm|harmful|safe|safety|unsafe|toxic|cancer|danger|risk)\w*", text, re.IGNORECASE), text
        # the web's ADVICE words (lib/copy-rules.ts), so a seed edit fails here before the web build does
        assert not re.search(r"\b(should|recommend|take \d|dose|dosing|consult|per day)\b", text, re.IGNORECASE), text


def test_a_statement_from_a_news_site_is_refused(tmp_path):
    bad = tmp_path / "f.yaml"
    bad.write_text(yaml.safe_dump({"read": "2026-11-21", "selection": {"chosen_by": "a", "gate": "b", "not_by": "c"},
                                   "statements": [{"id": "n", "date": "2026-01-01", "kind": "x", "title": "t",
                                                   "publisher": "p", "source": "news", "url": "https://example.com/a",
                                                   "says": "s", "quote": "q"}]}))
    with pytest.raises(findings.FindingsError) as e:
        findings.load_statements(bad)
    assert "not 'news'" in str(e.value) and "not an fda.gov or federalregister.gov link" in str(e.value)


def test_the_sources_the_finding_cites_may_be_displayed():
    assert "federal_register" in registry.SOURCES
    for key in findings.SOURCE_KEYS:
        assert registry.may_display(key), key


# ── the compiler ──────────────────────────────────────────────────────────────
def test_a_dye_is_a_code_never_a_name():
    prods = [_product("a", "A", [(BLUE1, "FD&C BLUE NO. 1")]),
             _product("b", "B", [("NOTADYE123", "FD&C BLUE NO. 1")]),        # the NAME of a dye, a code the table lacks
             _product("c", "C", [(BLUE1, "Some other spelling")])]          # the CODE of a dye, any spelling
    f = _compile(prods)
    by = {lb["slug"]: lb for lb in f["labels"]}
    assert by["a"]["six"] == ["blue-1"] and by["c"]["six"] == ["blue-1"] and by["b"]["six"] == []
    assert [u["slug"] for u in f["unrecognised"]] == ["b"]


def test_a_lake_counts_as_its_dye_and_the_groups_stay_apart():
    prods = [_product("a", "A", [(BLUE1_LAKE, "FD&C BLUE NO. 1 ALUMINUM LAKE"), (RED3, "FD&C RED NO. 3"), (DC_Y10, "D&C YELLOW NO. 10")])]
    f = _compile(prods)
    lb = f["labels"][0]
    assert lb["six"] == ["blue-1"] and lb["red_3"] is True and lb["d_and_c"] == ["dc-yellow-10"]
    assert f["totals"]["any_of_six"]["labels"] == 1                    # Red 3 and D&C are not the six
    assert f["totals"]["red_3"]["slugs"] == ["a"] and f["totals"]["d_and_c_any"]["labels"] == 1
    assert {c["form"] for c in lb["codes"]} == {"lake", "dye"}


def test_the_part_of_blue_2_the_registry_lists_separately_is_not_counted_as_blue_2():
    f = _compile([_product("a", "A", [(BLUE2_PART, "INDIGOTINDISULFONATE SODIUM")])])
    assert f["labels"][0]["six"] == [] and f["unrecognised"] == []
    assert f["totals"]["any_of_six"]["labels"] == 0


def test_the_totals_equal_the_table():
    prods = [_product("a", "A", [(BLUE1, "x"), (RED40, "y")], doc="HUMAN PRESCRIPTION DRUG LABEL"),
             _product("b", "B", [(BLUE1, "x"), (RED40, "y"), (YELLOW6, "z")]),
             _product("c", "C", [("ZZZZZZZZZZ", "water")]),
             _product("d", "D", [(RED3, "r")], doc="Human Prescription Drug Label")]
    f = _compile(prods)
    rows, t = f["labels"], f["totals"]
    assert t["labels"] == {"labels": 4, "otc": 2, "prescription": 2}
    assert t["any_of_six"] == {"labels": 2, "otc": 1, "prescription": 1}
    assert t["two_or_more"]["labels"] == 2 and t["three_or_more"]["labels"] == 1
    assert t["by_dye"]["blue-1"]["labels"] == sum("blue-1" in r["six"] for r in rows) == 2
    assert t["by_dye"]["yellow-5"]["labels"] == 0
    assert t["red_3"]["labels"] == 1
    for k in ("any_of_six", "two_or_more", "three_or_more"):
        assert t[k]["labels"] == t[k]["otc"] + t[k]["prescription"]


def test_only_medicine_labels_from_dailymed_are_counted_and_an_unknown_document_type_stops():
    prods = [_product("a", "A", [(BLUE1, "x")]), _product("s", "Sunscreen", [(BLUE1, "x")], kind="cosmetic")]
    assert [lb["slug"] for lb in _compile(prods)["labels"]] == ["a"]
    with pytest.raises(findings.FindingsError):
        _compile([_product("z", "Z", [(BLUE1, "x")], doc="VETERINARY")])


def test_routes_are_kept_only_when_cached_for_the_labels_version_and_split_when_all_are_known():
    prods = [_product("a", "A", [(BLUE1, "x")]), _product("b", "B", [(BLUE1, "x")]), _product("c", "C", [("ZZZZZZZZZZ", "w")])]
    table = {"setid-a": [{"code": "C38288", "name": "ORAL"}],
             "setid-b": [{"code": "C38288", "name": "ORAL"}, {"code": "C38675", "name": "TOPICAL"}],
             "setid-c": [{"code": "C38305", "name": "TOPICAL"}]}
    f = _compile(prods, routes=lambda s, v: table.get(s))
    assert [lb["taken"] for lb in f["labels"]] == ["oral", "oral+other", "other"]
    assert f["totals"]["routes"]["all"] == {"oral": 1, "oral+other": 1, "other": 1, "unstated": 0}
    assert f["totals"]["routes"]["any_of_six"]["oral"] == 1
    part = _compile(prods, routes=lambda s, v: table.get(s) if s != "setid-c" else None)
    assert part["labels"][2]["routes"] is None
    assert part["totals"]["routes"]["read"] == 2 and part["totals"]["routes"]["all"]["unstated"] == 1
    assert _compile(prods)["totals"]["routes"] is None            # none cached: no split at all


def test_a_label_missing_from_the_cache_is_counted_from_the_pages_own_data():
    p = _product("a", "A", [])
    p["molecules"] = [{"slug": "brilliant-blue-fcf", "role": "inactive", "listed_as": "FD&C BLUE NO. 1", "unii": BLUE1}]
    p["not_in_catalog"] = [{"name": "FD&C RED NO. 40 ALUMINUM LAKE", "role": "inactive", "unii": "6T47AS764T"}]
    f = findings.compile_dyes([p], spl=lambda s: None, routes=lambda s, v: None)
    assert f["labels"][0]["six"] == ["blue-1", "red-40"]


def test_the_compiler_is_deterministic_and_has_no_timestamp():
    prods = [_product("b", "B", [(BLUE1, "x")]), _product("a", "A", [(RED40, "y")])]
    one, two = json.dumps(_compile(prods)), json.dumps(_compile(list(reversed(prods))))
    assert one == two
    assert not re.search(r"20\d\d-\d\d-\d\dT\d\d", one)


# ── routes of administration ──────────────────────────────────────────────────
SPL = b"""<document xmlns="urn:hl7-org:v3"><versionNumber value="7"/><component><structuredBody>
<manufacturedProduct><consumedIn><substanceAdministration><routeCode code="C38288" displayName="ORAL"/>
</substanceAdministration></consumedIn></manufacturedProduct>
<manufacturedProduct><consumedIn><substanceAdministration><routeCode code="C38288" displayName="ORAL"/>
</substanceAdministration></consumedIn><consumedIn><substanceAdministration>
<routeCode code="C38305" displayName="TOPICAL"/></substanceAdministration></consumedIn></manufacturedProduct>
</structuredBody></component></document>"""


def test_parse_routes_reads_each_route_once_sorted_by_name():
    assert dailymed.parse_routes(SPL) == [{"code": "C38288", "name": "ORAL"}, {"code": "C38305", "name": "TOPICAL"}]
    assert dailymed.parse_routes(b'<document xmlns="urn:hl7-org:v3"/>') == []


def test_warm_reads_a_medicines_routes_once_per_version(tmp_path, monkeypatch):
    monkeypatch.setattr(products, "DAILYMED_DIR", tmp_path / "dailymed")
    seed = [{"slug": "a", "name": "A", "kind": "medicine", "source": "dailymed", "item": "11111111-1111-1111-1111-111111111111"},
            {"slug": "b", "name": "B", "kind": "cosmetic", "source": "dailymed", "item": "22222222-2222-2222-2222-222222222222"}]
    from moleculefinder_etl.sources import cache
    for s in seed:
        cache.write_json(products._spl_path(s["item"]), {"setid": s["item"], "version": 3, "ingredients": []})
    calls: list[str] = []

    def fake(setid):
        calls.append(setid)
        return {"version": 3, "routes": [{"code": "C38288", "name": "ORAL"}]}
    monkeypatch.setattr(products.dailymed, "fetch", lambda s: None)
    kw = {"fetch_table": lambda: None, "fetch_routes": fake}
    products.warm(seed, [], lambda c: None, **kw)
    assert calls == ["11111111-1111-1111-1111-111111111111"]            # the cosmetic is not read
    assert products.routes_cached(seed[0]["item"], 3) == [{"code": "C38288", "name": "ORAL"}]
    assert products.routes_cached(seed[0]["item"], 4) is None            # another edition of the label: not used
    products.warm(seed, [], lambda c: None, **kw)
    assert calls == ["11111111-1111-1111-1111-111111111111"]            # cached: not asked again


# ── the snapshot ──────────────────────────────────────────────────────────────
def test_export_writes_each_finding_to_its_own_file_and_removes_it_when_there_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    monkeypatch.setattr(snapshot_export.snapshot_guard, "check", lambda *a, **k: None)
    monkeypatch.setattr(snapshot_export.licence_gate, "enforce", lambda *a, **k: None)
    snapshot_export.export([], {}, findings={"dyes-in-medicines": {"id": "dyes-in-medicines", "x": 1}})
    assert json.loads((tmp_path / "findings" / "dyes-in-medicines.json").read_text())["x"] == 1
    snapshot_export.export([], {}, findings=None)
    assert not (tmp_path / "findings").exists()


@pytest.mark.skipif(not FILE.exists(), reason="no findings file in data/snapshots yet")
class TestTheSnapshotsFile:
    f = json.loads(FILE.read_text()) if FILE.exists() else {}

    def test_totals_equal_the_table(self):
        rows, t = self.f["labels"], self.f["totals"]
        assert t["labels"]["labels"] == len(rows)
        assert t["any_of_six"]["labels"] == sum(bool(r["six"]) for r in rows)
        assert t["two_or_more"]["labels"] == sum(len(r["six"]) >= 2 for r in rows)
        assert t["three_or_more"]["labels"] == sum(len(r["six"]) >= 3 for r in rows)
        for dye, v in t["by_dye"].items():
            assert v["labels"] == sum(dye in r["six"] for r in rows)
        assert t["red_3"]["slugs"] == [r["slug"] for r in rows if r["red_3"]]
        assert t["labels"]["otc"] == sum(r["class"] == "otc" for r in rows)
        assert t["any_of_six"]["otc"] == sum(r["class"] == "otc" and bool(r["six"]) for r in rows)

    def test_it_covers_every_medicine_label_the_products_file_has(self):
        prods = json.loads((SNAP / "products.json").read_text())["products"]
        med = sorted(p["slug"] for p in prods if p["kind"] == "medicine" and p["source"]["type"] == "dailymed")
        assert sorted(r["slug"] for r in self.f["labels"]) == med

    def test_every_listed_code_is_in_the_seed_and_the_label_is_the_one_the_page_links(self):
        by = findings.load_colours()["by_unii"]
        prods = {p["slug"]: p for p in json.loads((SNAP / "products.json").read_text())["products"]}
        for r in self.f["labels"]:
            assert all(c["unii"] in by for c in r["codes"])
            assert r["setid"] == prods[r["slug"]]["source"]["setid"]
            assert r["version"] == prods[r["slug"]]["source"]["version"]
            assert r["url"].startswith("https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=")

    def test_nothing_in_it_is_a_timestamp(self):
        assert not re.search(r"20\d\d-\d\d-\d\dT\d\d:", FILE.read_text())


# ── the familiar labels under the headline (deploy amendments, 2026-11-21) ─────
def test_the_seeds_examples_are_on_their_sides_in_the_committed_file():
    s = findings.load_statements()
    assert s["examples"]["lists"] and s["examples"]["lists_none"]
    if FILE.exists():
        f = json.loads(FILE.read_text())
        by = {r["slug"]: r for r in f["labels"]}
        for e in f["examples"]["lists"]:
            assert by[e["slug"]]["six"] and e["name"] == by[e["slug"]]["name"]
        for e in f["examples"]["lists_none"]:
            assert not by[e["slug"]]["six"] and e["name"] == by[e["slug"]]["name"]
        assert [e["slug"] for e in f["examples"]["lists"]] == [x for x in s["examples"]["lists"] if x not in
                                                                 {d["slug"] for d in f["examples"]["dropped"]}]


def test_an_example_that_changes_sides_or_leaves_drops_out_and_is_logged(caplog):
    prods = [_product("a", "A", [(BLUE1, "FD&C BLUE NO. 1")]), _product("b", "B", [("XXXXXXXXXX", "WATER")]),
             _product("c", "C", [(RED40, "FD&C RED NO. 40")])]
    s = {**findings.load_statements(), "examples": {"lists": ["a", "b", "gone"], "lists_none": ["c", "b"]}}
    labels = _labels(prods)
    with caplog.at_level("WARNING", logger="mfetl"):
        f = findings.compile_dyes(prods, spl=lambda x: labels.get(x), routes=lambda x, v: None, statements=s)
    ex = f["examples"]
    assert ex["lists"] == [{"slug": "a", "name": "A"}]
    assert ex["lists_none"] == [{"slug": "b", "name": "B"}]
    assert ex["dropped"] == [{"slug": "b", "side": "lists", "why": "now lists none of the six"},
                             {"slug": "gone", "side": "lists", "why": "not a medicine label in this count"},
                             {"slug": "c", "side": "lists_none", "why": "now lists one of the six"}]
    assert sum("example" in r.getMessage() for r in caplog.records) == 3


def test_a_bad_examples_seed_is_named(tmp_path):
    bad = tmp_path / "f.yaml"
    base = yaml.safe_load(findings.FINDINGS_YAML.read_text())
    base["examples"] = {"lists": ["a", "a"], "lists_none": ["a"]}
    bad.write_text(yaml.safe_dump(base))
    with pytest.raises(findings.FindingsError) as e:
        findings.load_statements(bad)
    assert "names a slug twice" in str(e.value) and "a slug on both sides" in str(e.value)


def test_the_fda_draft_guidance_on_colour_additives_in_drugs_is_there_as_the_fda_states_it():
    s = {x["id"]: x for x in findings.load_statements()["statements"]}
    g = s["drugs-guidance"]
    assert g["url"].startswith("https://www.fda.gov/regulatory-information/search-fda-guidance-documents/")
    assert g["date"] == "2025-05-30" and "FDA-2025-D-0507" in g["title"]
    assert "draft" in g["says"] and "not binding" in g["says"] and "names no dye" in g["says"]


def test_the_run_reports_each_finding_rebuilt_in_the_log_and_the_weekly_summary(tmp_path, monkeypatch, caplog):
    from moleculefinder_etl import pipeline
    monkeypatch.setattr(pipeline, "SNAPSHOTS", tmp_path)
    (tmp_path / "findings").mkdir()
    prods = [_product("a", "A", [(BLUE1, "FD&C BLUE NO. 1")]), _product("b", "B", [("XXXXXXXXXX", "WATER")])]
    s = {**findings.load_statements(), "examples": {"lists": ["a", "b"], "lists_none": []}}
    labels = _labels(prods)
    f = findings.compile_dyes(prods, spl=lambda x: labels.get(x), routes=lambda x, v: None, statements=s)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("MFETL_WEEKLY", "1")
    monkeypatch.setenv("MFETL_STEP_SUMMARY", str(summary))
    before = pipeline._findings_shipped({"dyes-in-medicines": f})
    assert before == {"dyes-in-medicines": None}
    (tmp_path / "findings" / "dyes-in-medicines.json").write_text("{}")
    with caplog.at_level("INFO", logger="mfetl"):
        pipeline._report_findings({"dyes-in-medicines": f}, before)
    text = summary.read_text()
    assert "### Findings (1)" in text
    assert "dyes-in-medicines: rebuilt (new from the shipped file): 1 of the 2 medicine labels list one of the six" in text
    assert "dyes-in-medicines: b left out of the lists sentence: now lists none of the six" in text
    assert any("findings: dyes-in-medicines: rebuilt" in r.getMessage() for r in caplog.records)
    pipeline._report_findings({"dyes-in-medicines": f}, {"dyes-in-medicines": "{}"})
    assert "rebuilt (unchanged from the shipped file)" in summary.read_text()
