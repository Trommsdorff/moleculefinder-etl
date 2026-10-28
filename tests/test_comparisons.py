"""The /vs/ prose is curated, so it gets the same fence every other curated file here has.

A comparison page puts two records side by side. If the seed names a molecule that is not in
the catalog, the page compares something with nothing; if it names the same pair twice in
opposite orders, two URLs render the same page and compete with each other in search. Both
fail the build rather than shipping.

The prose rules are enforced for a different reason. These pages are about medicines as often
as about food, and a comparison that slips into "which one to take" is the one thing a
molecule database must not publish.
"""
from __future__ import annotations

import pytest

from moleculefinder_etl.transform import relationships as rel

_OK = (
    "One. One. One. "
    "This fourth sentence carries the page past the length floor, which exists so that a stub "
    "cannot masquerade as a comparison, and clearing three hundred and twenty characters turns "
    "out to take rather more words than a test author expects, so here are a good many more of "
    "them to be going on with, which should finally be enough to clear the floor."
)


# One sentence under 160 characters that names both molecules (SEO run 1, 2026-10-28).
_ANSWER = "Caffeine carries three methyl groups and theobromine two, so caffeine binds adenosine receptors far harder."


def _pair(text=_OK, answer=_ANSWER):
    return {"answer": answer, "text": text}


def _mols(*slugs):
    return [{"slug": s} for s in slugs]


def test_a_real_pair_compiles_to_its_url_slug(monkeypatch):
    monkeypatch.setattr(rel, "load_comparisons", lambda: {"caffeine/theobromine": _pair()})
    out = rel.build_comparisons(_mols("caffeine", "theobromine"))
    assert set(out) == {"caffeine-vs-theobromine"}
    assert out["caffeine-vs-theobromine"]["a"] == "caffeine"
    assert out["caffeine-vs-theobromine"]["b"] == "theobromine"
    assert out["caffeine-vs-theobromine"]["answer"] == _ANSWER


def test_an_unknown_slug_fails_the_build(monkeypatch):
    monkeypatch.setattr(rel, "load_comparisons", lambda: {"caffeine/nosuchmolecule": _pair()})
    with pytest.raises(SystemExit, match="nosuchmolecule"):
        rel.build_comparisons(_mols("caffeine"))


def test_the_same_pair_in_both_orders_fails(monkeypatch):
    monkeypatch.setattr(rel, "load_comparisons",
                        lambda: {"a/b": _pair(), "b/a": _pair()})
    with pytest.raises(SystemExit, match="one page per pair"):
        rel.build_comparisons(_mols("a", "b"))


def test_a_molecule_cannot_be_compared_with_itself(monkeypatch):
    monkeypatch.setattr(rel, "load_comparisons", lambda: {"caffeine/caffeine": _pair()})
    with pytest.raises(SystemExit, match="itself"):
        rel.build_comparisons(_mols("caffeine"))


@pytest.mark.parametrize("text, expected", [
    ("Too short. Two. Three. Four.", "too thin"),
    (_OK + " Five. Six. Seven.", "the rule is 4 to 6"),
    (_OK.replace("One.", "One — dash.", 1), "em-dash"),
    (_OK + " You should pick the second one.", "advice or dosing"),
    (_OK + " A tablet is 500 mg of it.", "advice or dosing"),
    (_OK + " Which one to take is the question.", "advice or dosing"),
    (_OK + " You should pick the cheaper one.", "advice or dosing"),
])
def test_prose_rules(text, expected):
    assert any(expected in e for e in rel._comparison_prose_errors(text)), \
        f"{expected!r} not caught in {rel._comparison_prose_errors(text)}"


def test_a_pair_without_an_answer_line_fails(monkeypatch):
    monkeypatch.setattr(rel, "load_comparisons", lambda: {"caffeine/theobromine": _pair(answer="")})
    with pytest.raises(SystemExit, match="no answer line"):
        rel.build_comparisons(_mols("caffeine", "theobromine"))


_CT = ({"slug": "caffeine", "title": "Caffeine"}, {"slug": "theobromine", "title": "Theobromine"})


@pytest.mark.parametrize("answer, expected", [
    (_ANSWER + " " + "x" * 60 + ".", "one sentence"),
    ("Caffeine and theobromine differ in " + "a great many ways " * 8 + "indeed.", "the rule is under 160"),
    ("Caffeine has three methyl groups and theobromine two \u2014 that is all.", "em-dash"),
    ("Caffeine has three methyl groups and its cousin has two.", "does not name Theobromine"),
    ("Caffeine and theobromine are both safe in chocolate.", "advice or dosing"),
    ("Caffeine and theobromine differ, and you should pick the second.", "advice or dosing"),
    ("Caffeine and theobromine differ by one methyl group", "full stop"),
])
def test_answer_rules(answer, expected):
    errors = rel._answer_errors(answer, *_CT)
    assert any(expected in e for e in errors), f"{expected!r} not caught in {errors}"


def test_a_good_answer_passes_and_a_greek_title_reads_as_written():
    assert rel._answer_errors(_ANSWER, *_CT) == []
    carotene = {"slug": "beta-carotene", "title": "\u03b2-Carotene"}
    retinol = {"slug": "retinol", "title": "Retinol"}
    assert rel._answer_errors("Retinol is used directly, while beta-carotene is cut into it as needed.",
                              carotene, retinol) == []


def test_every_shipped_pair_has_its_own_answer_line():
    """Every shipped pair has its own line: two pages answering with one sentence would compete."""
    import json

    from moleculefinder_etl.config import SNAPSHOTS
    index = SNAPSHOTS / "index.json"
    if not index.exists():
        pytest.skip("no snapshot exported yet")
    out = rel.build_comparisons(json.loads(index.read_text()))
    answers = [c["answer"] for c in out.values()]
    assert all(answers) and len(set(answers)) == len(answers)


def test_an_ld50_in_mg_per_kg_is_not_mistaken_for_a_dose():
    """The negative lookahead in the dosing pattern earns its keep: these pages quote the
    oral LD50 off the record constantly, and 636 mg/kg is data, not a prescription."""
    assert rel._comparison_prose_errors(_OK + " Its oral LD50 is 636 mg/kg in rats.") == []


def test_the_shipped_file_compiles_and_every_pair_is_real():
    """The real seed against the real catalog, which is what CI actually protects."""
    import json

    from moleculefinder_etl.config import SNAPSHOTS
    index = SNAPSHOTS / "index.json"
    if not index.exists():
        pytest.skip("no snapshot exported yet")
    molecules = json.loads(index.read_text())
    out = rel.build_comparisons(molecules)
    assert len(out) >= 100, f"only {len(out)} comparisons compiled"
