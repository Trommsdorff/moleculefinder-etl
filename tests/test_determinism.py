"""The snapshot must be a function of its inputs, not of the machine that built it.

Two defects made the weekly data PR unreadable (2026-09-06: 217 changed molecule files, of
which roughly 190 carried no change a reader could see):

1. **PubChem synonym order.** The head of a synonym list is stable for months, but further
   down PubChem swaps neighbours between rebuilds. Storing them in arrival order turned that
   into 69 file changes; a truncation window of 20 names, dense with registry codes, turned
   it into 68 more as names crossed the boundary.
2. **RDKit depiction.** For fused and bridged polycyclics the 2D layout goes through a
   numerical minimiser whose result differs between the macOS and Linux wheels of the SAME
   rdkit version. 53 files rewrote themselves whenever the pipeline changed platform.

These tests pin the two rules that fix them. They are cheap and offline.
"""
from __future__ import annotations

from moleculefinder_etl.transform import structures
from moleculefinder_etl.transform.assemble import _carried_svg, _clean_synonyms
from moleculefinder_etl.transform.names import preferred_name

CAFFEINE = "CN1C=NC2=C1C(=O)N(C)C(=O)N2C"


# ── Synonyms ────────────────────────────────────────────────────────────────
def test_synonym_storage_order_survives_an_upstream_swap():
    """The exact churn seen on 4-aminobenzoic-acid: two neighbours traded places."""
    a = ["p-aminobenzoic acid", "PABA", "Vitamin BX", "para-aminobenzoic acid",
         "p-Carboxyaniline", "Sunbrella"]
    b = ["p-aminobenzoic acid", "PABA", "Vitamin BX", "p-Carboxyaniline",
         "para-aminobenzoic acid", "Sunbrella"]
    assert _clean_synonyms(a, "4-Aminobenzoic acid") == _clean_synonyms(b, "4-Aminobenzoic acid")


def test_synonym_selection_still_follows_pubchem():
    """Storage order is ours; SELECTION order stays PubChem's, because it is the only
    signal for which names a reader recognises. A name outside the first twelve non-code
    entries must not be pulled in just because it sorts early."""
    syns = [f"Name{i:02d}" for i in range(20)] + ["Aaaa"]
    out = _clean_synonyms(syns, "Title")
    assert "Aaaa" not in out
    assert len(out) == 12


def test_synonym_title_leads_and_the_rest_are_sorted():
    out = _clean_synonyms(["Zeta", "alpha", "Beta"], "Caffeine")
    assert out == ["Caffeine", "alpha", "Beta", "Zeta"]


def test_synonym_order_is_case_stable():
    """casefold first, exact string second: 'advil'/'Advil' cannot trade places."""
    assert _clean_synonyms(["advil", "Advil ", "Brufen"], "Ibuprofen") == \
           _clean_synonyms(["Advil ", "advil", "Brufen"], "Ibuprofen")


def test_preferred_name_tie_is_broken_by_the_string_not_the_feed():
    """Two equally short candidates must not depend on which one PubChem listed first."""
    assert preferred_name(1, None, ["Abcde", "Vwxyz"]) == preferred_name(1, None, ["Vwxyz", "Abcde"])


# ── Structure SVG ───────────────────────────────────────────────────────────
def test_svg_key_tracks_smiles_and_recipe():
    assert structures.svg_key(CAFFEINE) == structures.svg_key(CAFFEINE)
    assert structures.svg_key(CAFFEINE) != structures.svg_key("CCO")
    assert structures.svg_key(CAFFEINE, width=401) != structures.svg_key(CAFFEINE)


def test_matching_key_carries_the_drawing_forward_untouched():
    """The whole point: a byte-for-byte reuse, even if this platform would draw it
    differently. The sentinel is not valid SVG on purpose, so a redraw cannot fake a pass."""
    key = structures.svg_key(CAFFEINE)
    prior = {"structure_svg": "<svg>from-the-other-platform</svg>", "structure_svg_key": key}
    assert _carried_svg(CAFFEINE, prior)["structure_svg"] == "<svg>from-the-other-platform</svg>"


def test_a_changed_structure_redraws():
    prior = {"structure_svg": "<svg>stale</svg>", "structure_svg_key": structures.svg_key("CCO")}
    out = _carried_svg(CAFFEINE, prior)
    assert out["structure_svg"] != "<svg>stale</svg>"
    assert out["structure_svg_key"] == structures.svg_key(CAFFEINE)


def test_a_record_from_before_the_key_is_adopted_by_its_smiles():
    """Migration path. Without it the run that introduced the key would redraw the whole
    catalog on whichever machine ran it: the churn, one last time, for nothing."""
    prior = {"structure_svg": "<svg>already-shipped</svg>", "isomeric_smiles": CAFFEINE}
    out = _carried_svg(CAFFEINE, prior)
    assert out["structure_svg"] == "<svg>already-shipped</svg>"
    assert out["structure_svg_key"] == structures.svg_key(CAFFEINE)


def test_a_record_from_before_the_key_with_a_different_smiles_is_not_adopted():
    prior = {"structure_svg": "<svg>wrong-molecule</svg>", "isomeric_smiles": "CCO"}
    assert _carried_svg(CAFFEINE, prior)["structure_svg"] != "<svg>wrong-molecule</svg>"


def test_no_prior_draws_and_no_smiles_is_empty():
    assert _carried_svg(CAFFEINE, None)["structure_svg"].startswith("<?xml")
    assert _carried_svg(None, None) == {"structure_svg": None, "structure_svg_key": None}
