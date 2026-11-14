"""Latin remedy and pharmacopoeia label names stay off the "Also called" line (phase 10, Garrett's
ruling at the phase 8 deploy, 2026-11-14: gold read "Also called Aurum Metallicum"; fix it by rule)."""
from __future__ import annotations

import json

import pytest

from moleculefinder_etl.config import REPO_ROOT
from moleculefinder_etl.transform import assemble
from moleculefinder_etl.transform.assemble import display_synonyms, latin_pharmacy_name

LABEL_NAMES = [
    "Aurum Metallicum", "Argentum metallicum", "Argentum Metalicum", "Silicium Metallicum",
    "Thulium Metallicum", "Antimonium Metallicum", "Antimony Metallicum", "Stannum metallicum",
    "Zyncum Metallicum", "Niccolum metallicum", "Natrum Muriaticum", "Kali iodatum", "Kali causticum",
    "Acidum lacticum", "acidum lacticum", "Lacticum acidum", "Acidum mefenamicum", "Acidum yohimbicum",
    "Calcarea gluconica", "Magnesia Carbonica", "Carboneum oxygenisatum", "Natrium sulfurosum",
    "Natrii sulphis", "Calcii gluconas", "Chininum purum", "zincum oxydatum", "Methylenum chloratum",
]
REAL_NAMES = [
    # one-word Latin and historical names are real names, and this rule never judges one word
    "Silicium", "Argentum", "stannum", "Natrium", "hydrargyrum", "Meldonium", "columbium",
    # tellurium's names from its discoverer (1782), not label names
    "Aurum paradoxum", "Metallum problematum",
    # English names that end in a Latin-looking letter
    "fused silica", "colloidal silica", "Diatomaceous silica", "vitreous silica", "Amorphous silica dust",
    "Milk sugar", "Radium emanation", "Blue powder", "Coagulation Factor IV", "Dipeptide sweetener",
    "Benzoate of soda", "Sodium prussiate yellow", "Lyrica", "Absorica", "Atopica for Cats",
    "Acid Carbolicum",   # not every word Latin: left to the search list's other filters
]


@pytest.mark.parametrize("name", LABEL_NAMES)
def test_a_latin_label_name_is_caught(name):
    assert latin_pharmacy_name(name)


@pytest.mark.parametrize("name", REAL_NAMES)
def test_a_real_name_is_not(name):
    assert not latin_pharmacy_name(name)


def test_the_line_skips_them_and_the_next_name_moves_up():
    line = display_synonyms("Silver", [], ["Algaedyn", "Argentum", "Argentum metallicum", "Sterling"],
                            do_not_use=frozenset())
    assert line == ["Algaedyn", "Argentum", "Sterling"]


def test_the_wikidata_names_skip_them_too():
    row = {"wikidata_label": "lactic acid", "wikidata_aliases": ["acidum lacticum", "milk acid"]}
    assert assemble.wikidata_display_names("Lactic acid", row) == ["milk acid"]


def test_gold_is_caught_by_the_rule_not_by_the_do_not_use_list():
    assert "aurum metallicum" not in assemble.synonym_do_not_use()
    assert display_synonyms("Gold", [], ["Aurum Metallicum"]) == []


def _shipped():
    for f in sorted((REPO_ROOT / "data" / "snapshots" / "molecules").glob("*.json")):
        yield json.loads(f.read_text())


def test_no_shipped_line_carries_one():
    bad = [(m["slug"], n) for m in _shipped()
           for n in [*(m.get("display_synonyms") or []), *(m.get("wikidata_names") or []),
                     *([m["title_synonym"]] if m.get("title_synonym") else [])]
           if latin_pharmacy_name(n)]
    assert bad == []
