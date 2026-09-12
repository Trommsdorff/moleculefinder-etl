"""One LD50 everywhere (Garrett, 2026-09-12).

The Safety panel led with the parser's first row, the lowest oral value in any species, while
the dose hook, the Deadliest and Safest boards and the /vs tables read the oral-rat-first
choice. 53 molecules showed one LD50 on their own page and another everywhere else:
acetaminophen's panel said 338 mg/kg in the mouse and its comparison tables 1,944 in the rat.
These pin the one choice (toxicity.primary_ld50) and that every reader gets the same row.
"""
from __future__ import annotations

import yaml

from moleculefinder_etl.config import CURATED_DIR
from moleculefinder_etl.transform import assemble, leaderboards, toxicity
from tests.fixtures import canon_row, fetched, CAFFEINE_PROPS


def _row(value, route="oral", species="rat"):
    return {"endpoint": "LD50", "species": species, "route": route, "value_num": value,
            "unit": "mg/kg", "confidence": "from_source"}


def _key(row):
    return (row["value_num"], row["route"], row["species"])


# Acetaminophen's six rows as parse_ld50 sorts them (oral first, then lowest first).
ACETAMINOPHEN = [_row(338.0, species="mouse"), _row(1944.0), _row(2400.0),
                 _row(310.0, "other", "mouse"), _row(367.0, "other", "mouse"), _row(1205.0, "other")]
ACETAMINOPHEN_PROPS = {"CID": 1983, "SMILES": "CC(=O)NC1=CC=C(C=C1)O",
                       "MolecularFormula": "C8H9NO2", "MolecularWeight": "151.16"}
# Stearic acid has no oral row at all.
STEARIC_ACID = [_row(21.5, "iv"), _row(22.0, "iv"), _row(23.0, "iv", "mouse"),
                _row(5000.0, "dermal", "rabbit")]
STEARIC_ACID_PROPS = {"CID": 5281, "SMILES": "CCCCCCCCCCCCCCCCCC(=O)O",
                      "MolecularFormula": "C18H36O2", "MolecularWeight": "284.5"}


# ── the rule ────────────────────────────────────────────────────────────────
def test_acetaminophen_reads_1944_in_the_rat():
    assert _key(toxicity.primary_ld50(ACETAMINOPHEN)) == (1944.0, "oral", "rat")


def test_oral_rat_then_oral_mouse_then_any_oral():
    rows = [_row(5.0, species="dog"), _row(50.0, species="mouse"), _row(500.0)]
    assert toxicity.primary_ld50(rows)["species"] == "rat"
    assert toxicity.primary_ld50(rows[:2])["species"] == "mouse"
    assert toxicity.primary_ld50(rows[:1])["species"] == "dog"


def test_any_oral_value_beats_a_lower_value_by_another_route():
    rows = [_row(0.5, "iv"), _row(3000.0, species="dog")]
    assert _key(toxicity.primary_ld50(rows)) == (3000.0, "oral", "dog")


def test_with_no_oral_row_the_lowest_value_by_any_other_route():
    assert _key(toxicity.primary_ld50(STEARIC_ACID)) == (21.5, "iv", "rat")


def test_a_sub_floor_oral_value_is_dropped_not_demoted():
    """Oxymetazoline: 0.8 mg/kg oral is a parsing artifact, so its 1.1 by another route leads."""
    rows = [_row(0.8), _row(1.1, "other")]
    assert _key(toxicity.primary_ld50(rows, "oxymetazoline")) == (1.1, "other", "rat")
    assert toxicity.primary_ld50([_row(0.8)], "oxymetazoline") is None
    named = next(iter(toxicity.POTENT_TOXIN_SLUGS))
    assert _key(toxicity.primary_ld50(rows, named)) == (0.8, "oral", "rat")


def test_a_value_by_another_route_has_no_floor():
    assert _key(toxicity.primary_ld50([_row(0.4, "iv", "mouse")])) == (0.4, "iv", "mouse")


def test_a_tie_does_not_depend_on_row_order():
    rows = [_row(300.0, "other", "dog"), _row(300.0, "iv", "cat")]
    assert toxicity.primary_ld50(rows) == toxicity.primary_ld50(rows[::-1]) == rows[1]


def test_nothing_usable_is_none():
    assert toxicity.primary_ld50(None) is None and toxicity.primary_ld50([]) is None
    assert toxicity.primary_ld50([{**_row(5.0, "inhalation"), "unit": "mg/L"}]) is None


# ── every reader gets the same row ──────────────────────────────────────────
def _assemble(title, cid, rows, props, curated=None):
    f = fetched(props, toxicity=[dict(r) for r in rows], curated=curated)
    return assemble.assemble_record(canon_row(cid, title), f, set())


def _dose_hook(rec):
    return next((h for h in rec["hooks"] if h["type"] == "dose_poison"), None)


def test_the_panel_the_hook_and_the_record_read_one_row():
    rec = _assemble("Acetaminophen", 1983, ACETAMINOPHEN, ACETAMINOPHEN_PROPS)
    assert (rec["ld50_mg_per_kg"], rec["ld50_route"], rec["ld50_species"]) == (1944.0, "oral", "rat")
    assert _key(rec["toxicity"][0]) == (1944.0, "oral", "rat")        # the Safety panel's first row
    params = _dose_hook(rec)["params"]
    assert (params["ld50_mg_per_kg"], params["route"], params["species"]) == (1944.0, "oral", "rat")
    # the other five keep their order behind it
    assert [_key(r) for r in rec["toxicity"][1:]] == \
        [_key(r) for r in ACETAMINOPHEN if r["value_num"] != 1944.0]


def test_a_curated_overlay_still_pins_the_value():
    curated = yaml.safe_load((CURATED_DIR / "caffeine.yaml").read_text())
    rec = _assemble("Caffeine", 2519, [_row(127.0, species="mouse"), _row(105.0, "iv")],
                    CAFFEINE_PROPS, curated)
    assert _key(rec["toxicity"][0]) == (192, "oral", "rat") and rec["ld50_mg_per_kg"] == 192
    assert _dose_hook(rec)["params"]["ld50_mg_per_kg"] == 192


def test_an_injected_only_molecule_shows_its_ld50_but_gets_no_dose_hook():
    rec = _assemble("Stearic acid", 5281, STEARIC_ACID, STEARIC_ACID_PROPS)
    assert (rec["ld50_mg_per_kg"], rec["ld50_route"], rec["ld50_species"]) == (21.5, "iv", "rat")
    assert _key(rec["toxicity"][0]) == (21.5, "iv", "rat")
    assert _dose_hook(rec) is None


def test_the_ld50_boards_rank_only_an_oral_value_and_print_the_page_value():
    acet = _assemble("Acetaminophen", 1983, ACETAMINOPHEN, ACETAMINOPHEN_PROPS)
    stearic = _assemble("Stearic acid", 5281, STEARIC_ACID, STEARIC_ACID_PROPS)
    for board in ("deadliest", "safest"):
        entries = leaderboards.rank(board, [acet, stearic])["entries"]
        assert [e["slug"] for e in entries] == [acet["slug"]]
        assert (entries[0]["value_num"], entries[0]["route"], entries[0]["species"]) == \
            (1944.0, "oral", "rat")
