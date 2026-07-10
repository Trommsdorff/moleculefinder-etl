"""LD50 parser: real-world formats, unit conversion, and prose rejection."""
from moleculefinder_etl.transform.toxicity import parse_ld50
from moleculefinder_etl.transform.confidence import FROM_SOURCE
from tests.fixtures import tox_record


def _rows(*strings):
    return parse_ld50(tox_record(list(strings)))


def test_none_and_empty():
    assert parse_ld50(None) == []
    assert parse_ld50(tox_record([])) == []


def test_canonical_hsdb_format():
    (row,) = _rows("LD50 Rat oral 192 mg/kg")
    assert row["species"] == "rat" and row["route"] == "oral"
    assert row["value_num"] == 192.0 and row["unit"] == "mg/kg"
    assert row["confidence"] == FROM_SOURCE          # routed through confidence.py


def test_drugbank_paren_format():
    (row,) = _rows("LD50: 127 mg/kg (Oral, Mouse) (A308)")
    assert (row["species"], row["route"], row["value_num"]) == ("mouse", "oral", 127.0)


def test_comma_thousands_separator():
    (row,) = _rows("LD50 Rat oral 25,800 mg/kg")
    assert row["value_num"] == 25800.0


def test_unit_conversion_to_mgkg():
    (gkg,) = _rows("LD50 Mouse intravenous 9 g/kg")
    assert gkg["value_num"] == 9000.0 and gkg["route"] == "iv"      # g/kg → mg/kg, full-word route
    (ugkg,) = _rows("LD50: 47200 ug/kg (Oral, Mouse)")
    assert ugkg["value_num"] == 47.2                                # ug/kg → mg/kg


def test_greater_than_qualifier():
    (row,) = _rows("LD50 Mouse oral >2500 mg/kg")
    assert row["value_num"] == 2500.0


def test_ip_route_maps_to_other():
    (row,) = _rows("LD50 Rat ip 260 mg/kg")
    assert row["route"] == "other"                  # no enum value for intraperitoneal


def test_prose_is_rejected():
    # No clean species+route+value triple → nothing (the old parser emitted species="for").
    assert _rows("The exact LD50 for humans is estimated between 150 and 200 mg/kg.") == []


def test_per_volume_units_skipped():
    # g/L is a concentration, not a body-weight dose the hook can scale — skip it.
    assert _rows("LD50 Mouse iv 2.0 g/L") == []


def test_dedup_and_oral_first_ordering():
    rows = _rows(
        "LD50 Rat ip 260 mg/kg",
        "LD50 Rat oral 192 mg/kg",
        "LD50 Mouse oral 127 mg/kg",
        "LD50 Rat oral 192 mg/kg",          # duplicate of the second
    )
    assert len(rows) == 3                    # duplicate collapsed
    assert rows[0]["route"] == "oral"        # oral sorts first
    assert rows[0]["value_num"] == 127.0     # then lowest (deadliest) first
    assert rows[-1]["route"] == "other"


def test_multiple_ld50s_in_one_string():
    rows = _rows("LD50: 47200 ug/kg (Oral, Mouse) (T13)\nLD50: 6500 ug/kg (Intraperitoneal, Mouse) (T13)")
    assert {r["value_num"] for r in rows} == {47.2, 6.5}
