"""The inactive-ingredients finding (2026-11-22): the group seed's codes resolve, an ingredient joins
a group by its code and never by its name, every code a label lists is in exactly one group, the
totals equal the table, the colours count as on the dyes finding, and the committed file agrees with
itself and with products.json."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from moleculefinder_etl.sources import fda_unii, registry
from moleculefinder_etl.transform import findings

ROOT = Path(__file__).resolve().parent.parent
SNAP = ROOT / "data" / "snapshots"
FILE = SNAP / "findings" / "inactive-ingredients.json"
DYES = SNAP / "findings" / "dyes-in-medicines.json"
CLAIM_WORDS = re.compile(r"\b(only|first|most|leading|largest|world's|never|always)\b", re.IGNORECASE)
DASH = re.compile("[–—]")
HARM = re.compile(r"\b(harm|harmful|safe|safety|unsafe|toxic|cancer|danger|risk|allerg|intoleran|avoid|vegan|vegetarian|"
                  r"halal|kosher|religio|pork|porcine|bovine|diet)\w*", re.IGNORECASE)
ADVICE = re.compile(r"\b(should|recommend|take \d|dose|dosing|consult|per day)\b", re.IGNORECASE)

LACTOSE_MONO, LACTOSE_ANHYD, MAG_STEARATE, TIO2, GELATIN = "EWQ57Q8I5X", "3SY5LH9PMK", "70097M6I30", "15FIX9V2JP", "2G86QN327L"
BLUE1, BLUE1_LAKE, HYDRATED_SILICA, SILICA = "H3R47K3TBD", "J9EQA3S2JM", "Y6O7T4G8P9", "ETJ7Z6XBU4"


def _product(slug, name, ings, *, doc="HUMAN OTC DRUG LABEL", kind="medicine", molecules=None):
    """ings: [(unii, name)] inactive, or [(unii, name, role)]."""
    return {"slug": slug, "name": name, "kind": kind,
            "source": {"type": "dailymed", "setid": f"setid-{slug}", "labeler": "Acme", "doc_type": doc,
                       "version": 3, "effective": "20260101", "url": f"https://dailymed.example/{slug}"},
            "molecules": molecules or [], "not_in_catalog": [], "actives_not_in_catalog": [],
            "_ings": [(i[0], i[1], i[2] if len(i) > 2 else "inactive") for i in ings]}


def _compile(prods, routes=None, fda_name=None):
    labels = {p["source"]["setid"]: {"ingredients": [{"unii": u, "name": n, "role": r} for u, n, r in p["_ings"]]}
              for p in prods}
    return findings.compile_inactive(prods, spl=lambda s: labels.get(s), routes=routes or (lambda s, v: None),
                                     fda_name=fda_name)


def _group(f, gid):
    return next(g for g in f["groups"] if g["id"] == gid)


# ── the seed ──────────────────────────────────────────────────────────────────
def test_the_seed_validates_and_its_pages_are_lactose_gelatin_and_titanium_dioxide():
    s = findings.load_inactive_groups()
    assert s["checked"] == "2026-11-22"
    assert s["pages"] == ["lactose", "gelatin", "titanium-dioxide"]
    ids = [g["id"] for g in s["groups"]]
    assert len(ids) == len(set(ids))


def test_every_code_is_a_unii_in_one_group_only_and_carries_the_registry_check():
    s, c = findings.load_inactive_groups(), findings.load_colours()
    codes = [x["unii"] for g in s["groups"] for x in g["codes"]]
    assert len(codes) == len(set(codes)) == len(s["by_unii"])
    assert all(fda_unii.UNII_RE.match(u) for u in codes)
    assert all(x["gsrs_name"] and x["gsrs_status"] and x["member"] for g in s["groups"] for x in g["codes"])
    assert not set(codes) & set(c["by_unii"])
    kept = {k["unii"] for k in s["kept_apart"]}
    assert not kept & set(codes) and not kept & set(c["by_unii"])


@pytest.mark.skipif(fda_unii.cached(max_age_days=10**6) is None, reason="the FDA UNII table is not in data/raw_cache here")
def test_every_seed_code_resolves_in_the_fdas_table_to_the_name_the_registry_check_recorded():
    table = fda_unii.cached(max_age_days=10**6)
    s = findings.load_inactive_groups()
    for g in s["groups"]:
        for x in g["codes"]:
            assert x["unii"] in table, f"{x['unii']} ({g['id']}) is not in the FDA's UNII table"
            assert table.name(x["unii"]).upper() == x["gsrs_name"].upper(), x["unii"]
    for k in s["kept_apart"]:
        assert table.name(k["unii"]).upper() == k["gsrs_name"].upper(), k["unii"]


def test_the_groupings_the_brief_names_are_as_stated():
    by = {g["id"]: {x["unii"] for x in g["codes"]} for g in findings.load_inactive_groups()["groups"]}
    assert by["lactose"] == {LACTOSE_MONO, LACTOSE_ANHYD, "J2B2A4N98G"}
    assert by["cellulose"] == {"OP1R32D61U", "PNR0YF693Y", "7T9FYH5QMK", "SMD1X3XO9M"}
    assert {"3NXW29V3WO", "0WZ8WG20P6"} <= by["hypromellose"] and not by["hypromellose"] & by["cellulose"]
    assert not by["hydroxypropyl-cellulose"] & by["cellulose"]
    assert by["starch"] == {"O8232NY3SJ", "8I089SAH3T", "4DGK8B7I3S"}
    assert not by["sodium-starch-glycolate"] & by["starch"]
    assert by["iron-oxides"] == {"1K09F3G675", "EX438O2MRT", "XM0M87F357", "1N032N7MFO"}
    assert by["gelatin"] == {GELATIN} and by["titanium-dioxide"] == {TIO2} and by["magnesium-stearate"] == {MAG_STEARATE}
    assert by["talc"] == {"7SEV7J4R1U"} and by["silicon-dioxide"] == {SILICA}
    assert {"3WJQ0SDW1A", "B697894SGQ", "G2M7P15E5P"} <= by["polyethylene-glycol"]


def test_the_words_the_seed_puts_on_the_page_obey_the_copy_rules():
    s = findings.load_inactive_groups()
    words = [g["name"] for g in s["groups"]] + [g["phrase"] for g in s["groups"]] + [g.get("note") or "" for g in s["groups"]]
    words += [x["member"] for g in s["groups"] for x in g["codes"]] + [k["reason"] for k in s["kept_apart"]]
    for text in words:
        assert not DASH.search(text), text
        assert not CLAIM_WORDS.search(text), text
        assert not HARM.search(text), text
        assert not ADVICE.search(text), text
        assert "%" not in text, text


def test_a_bad_seed_names_every_problem(tmp_path):
    bad = tmp_path / "g.yaml"
    bad.write_text(yaml.safe_dump({"checked": "2026-11-22", "pages": ["nope"], "groups": [
        {"id": "a", "name": "A", "phrase": "a", "codes": [{"unii": "short"}]},
        {"id": "b", "name": "B", "phrase": "b", "codes": [{"unii": BLUE1, "member": "x", "gsrs_name": "x", "gsrs_status": "x"}]},
        {"id": "blue-1", "name": "C", "phrase": "c", "codes": [{"unii": TIO2, "member": "x", "gsrs_name": "x", "gsrs_status": "x"}]}],
        "kept_apart": [{"unii": TIO2, "near": "zz", "reason": "r", "gsrs_name": "x", "gsrs_status": "x"}]}))
    with pytest.raises(findings.FindingsError) as e:
        findings.load_inactive_groups(bad)
    msg = str(e.value)
    for part in ("'short' is not a UNII", "is a colour in colour_additives.yaml", "not be a colour's id",
                 f"kept_apart {TIO2} is also in a group", "near must be a group id", "pages: 'nope' is not a group id"):
        assert part in msg, part


def test_the_sources_the_finding_cites_may_be_displayed():
    for key in findings.INACTIVE_SOURCE_KEYS:
        assert registry.may_display(key), key


# ── the compiler ──────────────────────────────────────────────────────────────
def test_an_ingredient_joins_a_group_by_its_code_never_its_name():
    prods = [_product("a", "A", [(LACTOSE_MONO, "LACTOSE MONOHYDRATE")]),
             _product("b", "B", [("ZZZZZZZZZ1", "LACTOSE MONOHYDRATE")]),      # the NAME of a member, a code no group has
             _product("c", "C", [(LACTOSE_ANHYD, "milk sugar")])]               # a member's CODE, any words
    f = _compile(prods)
    assert _group(f, "lactose")["labels"] == 2
    assert [lb["groups"] for lb in f["labels"]] == [["lactose"], ["code-zzzzzzzzz1"], ["lactose"]]
    # the name looks like a lactose member, so it is reported for a person, never counted as lactose
    assert [(u["unii"], u["looks_like"], u["slugs"]) for u in f["unrecognised"]] == [("ZZZZZZZZZ1", "lactose", ["b"])]


def test_a_label_listing_two_members_counts_once_and_every_member_is_shown():
    f = _compile([_product("a", "A", [(LACTOSE_MONO, "x"), (LACTOSE_ANHYD, "y")]), _product("b", "B", [(LACTOSE_MONO, "x")])])
    g = _group(f, "lactose")
    assert g["labels"] == 2
    assert {c["unii"]: c["labels"] for c in g["codes"]}[LACTOSE_MONO] == 2
    assert {c["unii"]: c["labels"] for c in g["codes"]}[LACTOSE_ANHYD] == 1


def test_only_the_inactive_role_counts():
    f = _compile([_product("a", "A", [(TIO2, "TITANIUM DIOXIDE", "active")]), _product("b", "B", [(TIO2, "TITANIUM DIOXIDE")])])
    assert _group(f, "titanium-dioxide")["labels"] == 1
    assert f["labels"][0]["codes"] == [] and f["totals"]["lists_none"]["slugs"] == ["a"]


def test_a_colour_is_counted_as_the_dyes_finding_counts_it_dye_and_lake_together():
    f = _compile([_product("a", "A", [(BLUE1, "x")]), _product("b", "B", [(BLUE1_LAKE, "y")]), _product("c", "C", [(TIO2, "z")])])
    g = _group(f, "blue-1")
    assert g["kind"] == "colour" and g["labels"] == 2
    assert {c["form"] for c in g["codes"]} == {"dye", "lake"}


def test_a_code_in_no_group_is_its_own_group_named_by_the_fda_and_nothing_is_dropped():
    prods = [_product("a", "A", [("QQQQQQQQQ1", "Sodium Lauryl Sulfate"), (TIO2, "t")])]
    f = _compile(prods, fda_name=lambda u: {"QQQQQQQQQ1": "SODIUM LAURYL SULFATE"}.get(u))
    g = _group(f, "code-qqqqqqqqq1")
    assert (g["kind"], g["name"], g["phrase"], g["codes"][0]["gsrs_name"]) == ("code", "Sodium lauryl sulfate", "sodium lauryl sulfate", "SODIUM LAURYL SULFATE")
    assert f["totals"]["codes"] == 2 and f["totals"]["groups"] == 2
    # without the table, the label's own words name it
    assert _group(_compile(prods), "code-qqqqqqqqq1")["phrase"] == "sodium lauryl sulfate"


def test_a_kept_apart_code_stays_apart_and_is_not_reported_as_unrecognised():
    f = _compile([_product("a", "A", [(HYDRATED_SILICA, "HYDRATED SILICA")]), _product("b", "B", [(SILICA, "SILICON DIOXIDE")])])
    assert _group(f, "silicon-dioxide")["labels"] == 1
    assert f["unrecognised"] == []
    k = next(x for x in f["kept_apart"] if x["unii"] == HYDRATED_SILICA)
    assert k["near"] == "silicon-dioxide" and k["labels"] == 1 and k["arguable"] is True


def test_a_group_is_shown_when_at_least_one_label_in_ten_lists_it():
    prods = [_product(f"p{i:02d}", f"P{i:02d}", [(MAG_STEARATE, "m")] + ([(TIO2, "t")] if i < 2 else []) +
                      ([(GELATIN, "g")] if i < 1 else [])) for i in range(11)]
    f = _compile(prods)
    assert f["totals"]["shown"]["floor"] == 2           # ceil(11 / 10)
    assert f["totals"]["shown"]["groups"] == ["magnesium-stearate", "titanium-dioxide"]
    assert _group(f, "gelatin")["shown"] is False and _group(f, "gelatin")["labels"] == 1


def test_the_totals_equal_the_table_with_by_mouth_from_the_labels_routes():
    prods = [_product("a", "A", [(TIO2, "t"), (MAG_STEARATE, "m")], doc="HUMAN PRESCRIPTION DRUG LABEL"),
             _product("b", "B", [(TIO2, "t")]), _product("c", "C", [(MAG_STEARATE, "m")])]
    routes = {"setid-a": [{"code": "C38288", "name": "ORAL"}], "setid-b": [{"code": "C38305", "name": "TOPICAL"}]}
    f = _compile(prods, routes=lambda s, v: routes.get(s))
    t, g = f["totals"], _group(f, "titanium-dioxide")
    assert t["labels"] == {"labels": 3, "otc": 2, "prescription": 1, "by_mouth": 1}
    assert (g["labels"], g["otc"], g["prescription"], g["by_mouth"]) == (2, 1, 1, 1)
    assert t["routes_read"] == 2
    for grp in f["groups"]:
        assert grp["labels"] == sum(grp["id"] in lb["groups"] for lb in f["labels"])


def test_a_groups_molecule_pages_come_from_the_labels_own_matches():
    p = _product("a", "A", [(LACTOSE_MONO, "LACTOSE MONOHYDRATE")],
                 molecules=[{"slug": "lactose", "role": "inactive", "unii": LACTOSE_MONO}])
    f = _compile([p])
    assert _group(f, "lactose")["molecules"] == ["lactose"]
    assert _group(f, "gelatin")["molecules"] == []


def test_the_compiler_is_deterministic_and_has_no_timestamp():
    prods = [_product("b", "B", [(TIO2, "t"), (LACTOSE_MONO, "l")]), _product("a", "A", [(GELATIN, "g")])]
    one, two = json.dumps(_compile(prods)), json.dumps(_compile(list(reversed(prods))))
    assert one == two
    assert not re.search(r"20\d\d-\d\d-\d\dT\d\d", one)


def test_registry_words_reads_the_registrys_notation():
    assert findings.registry_words("CROSPOVIDONE (120 .MU.M)") == "crospovidone (120 micrometres)"
    assert findings.registry_words(".ALPHA.-TOCOPHEROL") == "alpha-tocopherol"
    assert findings.registry_words("D&C RED NO. 28") == "D&C red no. 28"


def test_the_run_reports_the_finding_with_its_three_pages_and_any_code_to_read():
    f = _compile([_product("a", "A", [(LACTOSE_MONO, "x"), (TIO2, "t")]), _product("b", "B", [("ZZZZZZZZZ1", "GELATIN TYPE B")])])
    lines = findings.summary_lines("inactive-ingredients", f, "changed")
    assert lines[0].startswith("inactive-ingredients: rebuilt (changed from the shipped file): 2 medicine labels")
    assert "lactose 1, gelatin 0, titanium dioxide 1" in lines[0]
    assert "1 code(s) look like a group's and are in none" in lines[0]
    assert "ZZZZZZZZZ1 GELATIN TYPE B looks like gelatin" in lines[1]


# ── the committed file ────────────────────────────────────────────────────────
@pytest.mark.skipif(not FILE.exists(), reason="no inactive-ingredients file in data/snapshots yet")
class TestTheSnapshotsFile:
    f = json.loads(FILE.read_text()) if FILE.exists() else {}

    def test_totals_equal_the_table(self):
        rows, t = self.f["labels"], self.f["totals"]
        assert t["labels"]["labels"] == len(rows)
        assert t["labels"]["otc"] == sum(r["class"] == "otc" for r in rows)
        assert t["labels"]["by_mouth"] == sum(r["taken"] in ("oral", "oral+other") for r in rows)
        assert t["lists_none"]["slugs"] == [r["slug"] for r in rows if not r["codes"]]
        assert t["codes"] == len({u for r in rows for u in r["codes"]})
        for g in self.f["groups"]:
            have = [r for r in rows if g["id"] in r["groups"]]
            assert (g["labels"], g["otc"], g["prescription"]) == (
                len(have), sum(r["class"] == "otc" for r in have), sum(r["class"] == "prescription" for r in have)), g["id"]
            assert g["shown"] == (g["labels"] >= t["shown"]["floor"])
        assert t["shown"]["floor"] == -(-len(rows) // 10)

    def test_every_code_is_in_exactly_one_group_and_every_label_group_is_described(self):
        owner = {}
        for g in self.f["groups"]:
            for c in g["codes"]:
                assert c["unii"] not in owner, c["unii"]
                owner[c["unii"]] = g["id"]
        for r in self.f["labels"]:
            assert sorted({owner[u] for u in r["codes"]}) == r["groups"]

    def test_it_covers_every_medicine_label_the_products_file_has_at_its_edition(self):
        prods = {p["slug"]: p for p in json.loads((SNAP / "products.json").read_text())["products"]
                 if p["kind"] == "medicine" and p["source"]["type"] == "dailymed"}
        assert sorted(r["slug"] for r in self.f["labels"]) == sorted(prods)
        for r in self.f["labels"]:
            assert (r["setid"], r["version"]) == (prods[r["slug"]]["source"]["setid"], prods[r["slug"]]["source"]["version"])

    def test_the_colours_agree_with_the_dyes_finding(self):
        dyes = json.loads(DYES.read_text())
        by = {g["id"]: g for g in self.f["groups"]}
        for dye, v in dyes["totals"]["by_dye"].items():
            assert by[dye]["labels"] == v["labels"], dye
        assert by["red-3"]["labels"] == dyes["totals"]["red_3"]["labels"]

    def test_the_three_pages_have_a_group_and_a_molecule_page(self):
        by = {g["id"]: g for g in self.f["groups"]}
        for p in self.f["pages"]:
            assert by[p]["molecules"], p
            for slug in by[p]["molecules"]:
                assert (SNAP / "molecules" / f"{slug}.json").exists(), slug

    def test_nothing_in_it_is_a_timestamp(self):
        assert not re.search(r"20\d\d-\d\d-\d\dT\d\d:", FILE.read_text())
