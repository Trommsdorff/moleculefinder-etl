"""Product comparisons (SEO run 2, 2026-10-28): /whats-in/<a>-vs-<b>, two labels' ingredient lists.

Pinned here:
* the strength a label states for an active is read off its own active-ingredient line or table
  row ("200 mg", "220 mg (naproxen 200 mg)", "0.24% (0.15% w/v fluoride ion)"), paired like the
  purposes, never computed, and lands on the product entry with what it is stated for;
* the pair seed is fenced like every seed (every problem named at once);
* a pair is built only from two seeded DailyMed labels that both passed the gate; one whose
  product failed the gate is skipped with its reason; one naming an unseeded product, a non-label,
  a URL that is a product's own slug, or an answer line that breaks the rules stops the build;
* product_pairs.json is written by the export and removed with the products.
"""
from __future__ import annotations

import json

import pytest

from moleculefinder_etl.load import snapshot_export
from moleculefinder_etl.sources import dailymed
from moleculefinder_etl.transform import products
from tests.test_products import SETID, SETID2, SPL, _compile, _p


# ── strengths ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("line, want", [
    ("Ibuprofen 200 mg (NSAID)*", "200 mg"),
    ("Naproxen sodium 220 mg (naproxen 200 mg) (NSAID) nonsteroidal anti-inflammatory drug", "220 mg (naproxen 200 mg)"),
    ("Solubilized ibuprofen equal to 200 mg ibuprofen (NSAID) nonsteroidal anti-inflammatory drug", "200 mg"),
    ("Omeprazole delayed-release tablet 20 mg (equivalent to 20.6 mg omeprazole magnesium)",
     "20 mg (equivalent to 20.6 mg omeprazole magnesium)"),
    ("Calcium Carbonate USP 500 mg", "500 mg"),
    ("Sodium fluoride 0.24% (0.15% w/v fluoride ion)", "0.24% (0.15% w/v fluoride ion)"),
    ("Potassium nitrate 5%", "5%"),
    ("Diphenhydramine HCl 12.5 mg", "12.5 mg"),
    ("Vitamin D3 1,000 IU", "1,000 IU"),
    ("Pain reliever/fever reducer", None),
    ("*nonsteroidal anti-inflammatory drug", None),
])
def test_strength_text_reads_the_first_quantity_and_a_quantity_bearing_parenthetical(line, want):
    assert dailymed.strength_text(line) == want


def test_strengths_and_what_they_are_stated_for_from_the_example_label():
    spl = dailymed.parse(SPL, SETID)
    assert dailymed.strengths(spl) == {"ACETAMINOPHEN": "500 mg", "DEXTROMETHORPHAN HYDROBROMIDE": "15 mg"}
    assert dailymed.strength_per(spl) == "caplet"


def test_a_label_without_quantities_gives_no_strength():
    spl = {"ingredients": [{"role": "active", "name": "MENTHOL", "unii": "x", "moiety": []}],
           "active_lines": ["Menthol"], "purpose_lines": ["Cough suppressant"], "purpose_rows": []}
    assert dailymed.strengths(spl) == {}
    assert dailymed.strength_per(spl) is None


def test_an_active_entry_carries_its_strength_and_an_inactive_does_not():
    passed, _ = _compile([_p("example-cold", "medicine", "dailymed", SETID)], {SETID: dailymed.parse(SPL, SETID)})
    by = {m["slug"]: m for m in passed[0]["molecules"]}
    assert by["acetaminophen"]["strength"] == "500 mg" and by["acetaminophen"]["strength_per"] == "caplet"
    assert by["dextromethorphan"]["strength"] == "15 mg"
    assert "strength" not in by["magnesium-stearate"]


# ── the seed ─────────────────────────────────────────────────────────────────
def _pairs(tmp_path, rows):
    p = tmp_path / "product_pairs.yaml"
    p.write_text(json.dumps({"pairs": rows}))
    return p


def test_load_pairs_names_every_problem_at_once(tmp_path):
    path = _pairs(tmp_path, [
        "not a mapping",
        {"a": "advil", "b": "advil", "answer": "x."},
        {"a": "advil", "b": "aleve", "answer": "Advil and Aleve."},
        {"a": "aleve", "b": "advil", "answer": "Aleve and Advil."},
        {"a": "tums", "b": "rolaids", "answer": "x.", "extra": 1},
        {"a": "tums", "b": "pepcid-complete"},
        {"a": "Bad Slug", "b": "pepcid-complete", "answer": "x."},
    ])
    with pytest.raises(products.ProductSeedError) as e:
        products.load_pairs(path)
    msg = str(e.value)
    for phrase in ["not a mapping", "compared with itself", "same pair as advil/aleve", "unknown field(s) extra",
                   "no answer line", "a and b are product slugs"]:
        assert phrase in msg, phrase


def test_load_pairs_reads_a_good_seed_and_an_absent_one(tmp_path):
    assert products.load_pairs(tmp_path / "none.yaml") == []
    path = _pairs(tmp_path, [{"a": "advil", "b": "aleve", "answer": "  Advil   and Aleve. "}])
    assert products.load_pairs(path) == [{"a": "advil", "b": "aleve", "answer": "Advil and Aleve."}]


# ── compile ──────────────────────────────────────────────────────────────────
SEED = [
    _p("example-cold", "medicine", "dailymed", SETID, "Example Cold"),
    _p("other-cold", "medicine", "dailymed", SETID2, "Other Cold"),
    _p("morning-coffee", "drink", "world", "morning-coffee", "Morning coffee"),
    _p("example-cold-vs-other-cold", "medicine", "dailymed", "00000000-0000-0000-0000-000000000000", "Collision"),
]
LINE = "Example Cold lists acetaminophen and dextromethorphan as its active ingredients, while Other Cold lists acetaminophen alone."


def _passed(*slugs):
    return [{"slug": s} for s in slugs]


def test_a_pair_is_built_from_two_labels_that_passed_and_carries_its_answer():
    out, skipped = products.compile_pairs([{"a": "example-cold", "b": "other-cold", "answer": LINE}],
                                          _passed("example-cold", "other-cold"), SEED[:3])
    assert skipped == []
    assert out == [{"slug": "example-cold-vs-other-cold", "a": "example-cold", "b": "other-cold", "answer": LINE,
                    "confidence": "from_source", "source": products.PAIR_SOURCE}]


def test_a_pair_whose_product_failed_the_gate_is_skipped_with_the_reason_not_failed():
    out, skipped = products.compile_pairs([{"a": "example-cold", "b": "other-cold", "answer": LINE}],
                                          _passed("example-cold"), SEED[:3])
    assert out == []
    assert skipped == [{"pair": "example-cold/other-cold", "reason": "other-cold did not pass the gate this run"}]


@pytest.mark.parametrize("pair, phrase", [
    ({"a": "example-cold", "b": "nothing", "answer": LINE}, "not in products.yaml: nothing"),
    ({"a": "example-cold", "b": "morning-coffee", "answer": LINE}, "needs two DailyMed labels; morning-coffee"),
    ({"a": "example-cold", "b": "other-cold", "answer": LINE.replace("Other Cold", "the other")}, "does not name Other Cold"),
    ({"a": "example-cold", "b": "other-cold", "answer": LINE[:-1] + ", so take 2 a day."}, "advice or dosing"),
    ({"a": "example-cold", "b": "other-cold", "answer": LINE[:-1] + " at 500 mg."}, "advice or dosing"),
    ({"a": "example-cold", "b": "other-cold", "answer": LINE + " Second sentence."}, "one sentence"),
    ({"a": "example-cold", "b": "other-cold", "answer": LINE.replace(",", " —")}, "em-dash"),
    ({"a": "example-cold", "b": "other-cold", "answer": LINE + " " + "x" * 60 + "."}, "characters"),
])
def test_a_bad_pair_stops_the_build_naming_the_problem(pair, phrase):
    with pytest.raises(products.ProductSeedError, match=phrase):
        products.compile_pairs([pair], _passed("example-cold", "other-cold"), SEED[:3])


def test_a_pair_whose_url_is_a_products_slug_stops_the_build():
    with pytest.raises(products.ProductSeedError, match="is a product's own slug"):
        products.compile_pairs([{"a": "example-cold", "b": "other-cold", "answer": LINE}],
                               _passed("example-cold", "other-cold"), SEED)


# ── export ───────────────────────────────────────────────────────────────────
def test_export_writes_product_pairs_json_and_removes_it_with_the_products(tmp_path, monkeypatch):
    from moleculefinder_etl import freshness
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    monkeypatch.setattr(freshness, "load", lambda path=None: {})
    recs = [{"cid": 2519, "slug": "caffeine", "title": "Caffeine", "synonyms": []}]
    prods = [{"slug": "p", "source": {"type": "curated"}, "molecules": []}]
    pair = {"slug": "p-vs-q", "a": "p", "b": "q", "answer": "P and Q."}
    snapshot_export.export(recs, {}, today="2026-10-28", products=prods, product_pairs=[pair])
    assert json.loads((tmp_path / "product_pairs.json").read_text()) == {"pairs": [pair]}
    snapshot_export.export(recs, {}, today="2026-10-29", products=prods)
    assert not (tmp_path / "product_pairs.json").exists()
    assert json.loads((tmp_path / "meta.json").read_text()) == {"refreshed": "2026-10-29"}


# ── the committed seed against the committed snapshot ────────────────────────
def test_the_committed_pairs_are_valid_and_every_one_is_built_from_the_committed_products():
    from moleculefinder_etl.config import SNAPSHOTS
    pairs = products.load_pairs()
    assert len(pairs) >= 10
    snap = SNAPSHOTS / "products.json"
    if not snap.exists():
        pytest.skip("no snapshot exported yet")
    passed = json.loads(snap.read_text())["products"]
    out, skipped = products.compile_pairs(pairs, passed, products.load_seed())
    assert skipped == []
    assert len(out) == len(pairs)
    shipped = SNAPSHOTS / "product_pairs.json"
    if shipped.exists():
        assert json.loads(shipped.read_text()) == {"pairs": out}
