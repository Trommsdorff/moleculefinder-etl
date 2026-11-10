"""The copy sweep (build plan everyday chemistry 2026-11, phase 2): the claim rule, the lines it rewrote,
and Garrett's roster rulings of 2026-11-10."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from moleculefinder_etl.transform import claims, leaderboards, presence, relationships

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "data" / "snapshots"
SEEDS = claims.SEEDS_DIR


def _molecules() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((SNAP / "molecules").glob("*.json"))]


def _products() -> dict[str, dict]:
    return {p["slug"]: p for p in json.loads((SNAP / "products.json").read_text())["products"]}


def _corpus() -> dict[tuple[str, str], str]:
    return {(k, key): text for k, key, text in claims.corpus()}


# ── The rule ──────────────────────────────────────────────────────────────────
def test_the_word_lists_are_pinned():
    # The web's lib/copy-rules.ts holds the same two lists (CLAIM_WORDS, COMPLETENESS) and pins
    # them the same way, so a change has to be made in both repos.
    assert claims.CLAIM_WORDS == ("only", "first", "most", "leading", "largest", "world's", "never", "always")
    assert claims.COMPLETENESS == ("every molecule in", "all the molecules in", "the molecules in it")
    for w in claims.CLAIM_WORDS:
        assert claims.words_in(f"It is the {w} one.") == [w]


def test_the_matcher():
    assert claims.words_in("Caffeine is the world’s most used") == ["most", "world's"]
    assert claims.words_in("The twenty-first amino acid, a first-line medicine") == ["first"]
    assert claims.words_in("mostly, firstly, lonely, almost") == []
    assert claims.line_id("a  b\n c") == claims.line_id("a b c")


def test_every_curated_line_with_a_claim_word_has_its_basis():
    assert claims.line_problems() == []


def test_the_corpus_is_every_line_the_rule_covers():
    c = _corpus()
    kinds = {k for k, _ in c}
    assert kinds == {"why_it_matters", "editorial", "comparison", "answer"}
    assert sum(1 for k, _ in c if k == "why_it_matters") == len(yaml.safe_load((SEEDS / "why_it_matters.yaml").read_text()))
    assert sum(1 for k, _ in c if k == "comparison") == sum(1 for k, _ in c if k == "answer") == \
        len(yaml.safe_load((SEEDS / "comparisons.yaml").read_text()))


def _allowed_for(lines):
    return {(k, key): {"words": claims.words_in(t), "basis": "science", "why": "x", "line": claims.line_id(t)}
            for k, key, t in lines if claims.words_in(t)}


def test_a_new_line_with_a_claim_word_and_no_entry_fails():
    lines = [("why_it_matters", "x", "The most used thing.")]
    problems = claims.line_problems(lines, {})
    assert len(problems) == 1 and "no entry" in problems[0] and claims.line_id("The most used thing.") in problems[0]


def test_an_edited_line_fails_until_its_entry_is_rewritten():
    old = [("editorial", "x", "The only metal liquid at room temperature.")]
    allowed = _allowed_for(old)
    assert claims.line_problems(old, allowed) == []
    edited = [("editorial", "x", "The only metal that is liquid at room temperature.")]
    problems = claims.line_problems(edited, allowed)
    assert len(problems) == 1 and "edited" in problems[0]


def test_entry_mistakes_fail():
    lines = [("why_it_matters", "x", "The first and only one.")]
    good = _allowed_for(lines)
    entry = good[("why_it_matters", "x")]
    for bad, says in ((dict(entry, words=["only"]), "carries"), (dict(entry, basis="vibes"), "basis"),
                      (dict(entry, why=" "), "reason"), (dict(entry, basis="data"), "DATA_CHECKS"),
                      (dict(entry, basis="held"), "held")):
        problems = claims.line_problems(lines, {("why_it_matters", "x"): bad})
        assert any(says in p for p in problems), (bad, problems)
    # An entry whose line no longer carries a word is stale.
    stale = claims.line_problems([("why_it_matters", "x", "Plain now.")], good)
    assert stale and "no longer carries" in stale[0]


def test_a_line_without_a_claim_word_needs_no_entry():
    assert claims.line_problems([("comparison", "a/b", "Both are acids.")], {}) == []


def test_answer_lines_are_held_only_with_a_reason():
    allowed = claims.load_allowed()
    held = sorted(key for (k, key), e in allowed.items() if e["basis"] == "held")
    # Garrett, 2026-11-10: furosemide's line is fixed (no claim word now); meloxicam's stays as it is.
    assert held == ["meloxicam/ibuprofen"]
    assert all(k == "answer" for (k, _), e in allowed.items() if e["basis"] == "held")


# ── Claims our data must keep showing ─────────────────────────────────────────
def _boards(molecules):
    return {slug: leaderboards.rank(slug, molecules) for slug in leaderboards.BOARDS}


def test_the_data_claims_hold_on_the_snapshot():
    mols = _molecules()
    assert claims.data_problems(mols, _boards(mols)) == []
    used = {e.get("check") for e in claims.load_allowed().values() if e["basis"] == "data"}
    assert used == set(claims.DATA_CHECKS)


@pytest.mark.parametrize("slug,field,value,check", [
    ("resiniferatoxin", "scoville_shu", 16_000_000, "rtx_tops_spiciest"),
    ("glucose", "relative_sweetness", 0.5, "glucose_three_quarters_sweet"),
])
def test_a_data_claim_that_stops_holding_refuses_the_export(slug, field, value, check):
    mols = _molecules()
    for m in mols:
        if m["slug"] == slug:
            m[field] = value
    problems = claims.data_problems(mols, _boards(mols))
    assert problems and any(slug.split("-")[0] in p for p in problems)
    with pytest.raises(SystemExit):
        claims.check_data_claims(mols, _boards(mols))


# ── The rewrites ──────────────────────────────────────────────────────────────
def test_the_overreaching_lines_are_gone():
    c = _corpus()
    gone = {
        ("editorial", "caffeine"): ["world's most widely used", "the only one routinely served"],
        ("editorial", "acetaminophen"): ["most common drug", "leading cause", "most people assume"],
        ("why_it_matters", "acetaminophen"): ["most-visited"],
        ("why_it_matters", "carnosine"): ["only real dietary source"],
        ("why_it_matters", "p-menthane-3-8-diol"): ["the only plant-derived"],
        ("why_it_matters", "tirzepatide"): ["largest medicine"],
        ("comparison", "semaglutide/tirzepatide"): ["two largest molecules"],
        ("why_it_matters", "insulin"): ["first human protein"],
        ("comparison", "sertraline/fluoxetine"): ["first SSRI to reach the market"],
        ("why_it_matters", "fructose"): ["most of high-fructose"],
        ("why_it_matters", "celecoxib"): ["only the COX-2"],
        # Garrett's review of 2026-11-10.
        ("why_it_matters", "doxorubicin"): ["that bacterium's ring system"],
        ("why_it_matters", "acrylonitrile-butadiene-styrene"): ["matte"],
        ("why_it_matters", "acetaldehyde"): ["a large part of a hangover"],
        ("editorial", "nicotine"): ["fastest-clearing"],
        ("comparison", "formaldehyde/acetaldehyde"): ["much of a hangover"],
        ("answer", "formaldehyde/acetaldehyde"): ["much of a hangover"],
        ("answer", "hydrochlorothiazide/furosemide"): ["where most sodium is reabsorbed"],
    }
    for key, phrases in gone.items():
        for phrase in phrases:
            assert phrase not in c[key], (key, phrase)


def test_garretts_review_fixes_2026_11_10():
    c = _corpus()
    assert c[("why_it_matters", "doxorubicin")].endswith(
        "Its deep red colour comes from the four fused rings at the molecule's core.")
    radon = c[("why_it_matters", "radon")]
    assert "densest gaseous element" in radon and "The US EPA ranks it second only to smoking" in radon
    assert claims.load_allowed()[("why_it_matters", "radon")]["basis"] == "history"
    assert "it clears fast: its half-life is only about two hours" in c[("editorial", "nicotine")]
    assert "the tough, glossy plastic of LEGO bricks" in c[("why_it_matters", "acrylonitrile-butadiene-styrene")]
    assert c[("answer", "hydrochlorothiazide/furosemide")] == (
        "Furosemide is a strong loop diuretic acting in the loop of Henle, while hydrochlorothiazide acts "
        "further along the kidney tubule and is gentler.")
    # Every curated line that ties acetaldehyde to a hangover says "long blamed for part of" it.
    for (kind, key), text in c.items():
        for sentence in text.split(". "):
            if "hangover" in sentence and ("acetaldehyde" in key or "cetaldehyde" in sentence):
                assert "long blamed for part of a hangover" in sentence, (kind, key, sentence)


def test_the_caffeine_editorial_keeps_adenosine_and_the_three_plants():
    text = _corpus()[("editorial", "caffeine")]
    assert "adenosine" in text and "Coffee, tea and cocoa" in text
    # Every place the editorial names is on caffeine's own lists, marked natural.
    caf = json.loads((SNAP / "molecules" / "caffeine.json").read_text())
    marks = {c["slug"]: c["presence"]["value"] for c in caf["categories"] if c["kind"] == "food"}
    assert marks["coffee"] == marks["tea"] == marks["chocolate"] == "natural"


def test_rewritten_lines_keep_the_house_rules():
    for kind, key, text in claims.corpus():
        assert "—" not in text and "–" not in text, (kind, key)
    for slug, line in yaml.safe_load((SEEDS / "why_it_matters.yaml").read_text()).items():
        assert len(line) <= 200, slug


# ── Garrett's roster rulings, 2026-11-10 ──────────────────────────────────────
def test_the_removals():
    hubs = relationships.load_food_hubs()
    assert "tannic-acid" not in hubs["tea"]["molecules"]
    assert "tannic-acid" not in hubs["wine"]["molecules"]
    assert hubs["table-sugar"]["molecules"] == ["sucrose"]
    worlds = {w["slug"]: w for w in relationships.load_worlds()}
    for world, slug in (("glass-of-wine", "tannic-acid"), ("after-the-rain", "2-nonenal"), ("fresh-bread", "ethyl-maltol")):
        assert slug not in worlds[world]["molecules"], (world, slug)
        assert slug not in [j["slug"] for j in worlds[world].get("journey") or []], (world, slug)
    # Nothing still says it is due to be removed.
    for f in [*SEEDS.glob("*.yaml"), *claims.CURATED_DIR.glob("*.yaml")]:
        assert "due to be removed" not in f.read_text(), f.name
    marks = presence.load_marks()
    for kind, key in (("food", ("tea", "tannic-acid")), ("food", ("wine", "tannic-acid")),
                      ("food", ("table-sugar", "glucose")), ("food", ("table-sugar", "fructose")),
                      ("world", ("glass-of-wine", "tannic-acid")), ("world", ("after-the-rain", "2-nonenal")),
                      ("world", ("fresh-bread", "ethyl-maltol"))):
        assert key not in marks[kind], key


def test_the_removals_reach_the_snapshot():
    products = _products()
    assert "tannic-acid" not in [m["slug"] for m in products["tea"]["molecules"]]
    assert "tannic-acid" not in [m["slug"] for m in products["wine"]["molecules"]]
    assert "tannic-acid" not in [m["slug"] for m in products["glass-of-wine"]["molecules"]]
    assert "2-nonenal" not in [m["slug"] for m in products["after-the-rain"]["molecules"]]
    assert "ethyl-maltol" not in [m["slug"] for m in products["fresh-bread"]["molecules"]]
    # Table sugar is sucrose alone, under the three-molecule gate: its product page is retired (and
    # answers 410 on the web, lib/gone.ts), while the ledger keeps the slug it once published.
    assert "table-sugar" not in products
    ledger = json.loads((SNAP / "products_published.json").read_text())
    assert "table-sugar" in ledger["products"]
    tannic = json.loads((SNAP / "molecules" / "tannic-acid.json").read_text())
    assert not [c for c in tannic["categories"] if c["slug"] in ("tea", "wine")]


def test_glutamate_not_msg_on_cheese_soy_sauce_and_mushrooms():
    products = _products()
    for food in ("cheese", "soy-sauce", "mushrooms"):
        slugs = [m["slug"] for m in products[food]["molecules"]]
        assert "glutamic-acid" in slugs and "monosodium-glutamate" not in slugs, food
    glu = json.loads((SNAP / "molecules" / "glutamic-acid.json").read_text())
    notes = {c["slug"]: c.get("note") for c in glu["categories"] if c["kind"] == "food"}
    assert notes == {f: "free glutamate, the taste of MSG" for f in ("cheese", "mushrooms", "soy-sauce")}
    msg = json.loads((SNAP / "molecules" / "monosodium-glutamate.json").read_text())
    assert [c["slug"] for c in msg["categories"] if c["kind"] == "food"] == ["processed-snacks"]
