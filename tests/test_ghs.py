"""GHS parser: signal word severity, H-codes, and pictograms from Markup URLs."""
from moleculefinder_etl.transform.ghs import parse_ghs
from moleculefinder_etl.transform.confidence import FROM_SOURCE
from tests.fixtures import ghs_record


def test_none_and_empty():
    assert parse_ghs(None) is None
    assert parse_ghs(ghs_record([])) is None


def test_most_severe_signal_word_wins():
    g = parse_ghs(ghs_record([
        "Warning", "H302: Harmful if swallowed [Warning Acute toxicity, oral]",
        "Danger", "H301: Toxic if swallowed [Danger Acute toxicity, oral]",
    ]))
    assert g["signal_word"] == "Danger"        # Danger outranks Warning


def test_h_statements_extracted_and_sorted():
    g = parse_ghs(ghs_record(["Warning", "H302 and H319 and H302 apply, plus H225."]))
    assert g["h_statements"] == ["H225", "H302", "H319"]
    assert g["confidence"] == FROM_SOURCE


def test_pictograms_from_markup_urls():
    g = parse_ghs(ghs_record(
        ["Danger", "H301: Toxic if swallowed"],
        picto_urls=["https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS06.svg",
                    "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS07.svg"],
    ))
    assert g["pictograms"] == ["GHS06", "GHS07"]


def test_h_codes_without_signal_still_classify():
    g = parse_ghs(ghs_record(["H315: Causes skin irritation"]))
    assert g is not None and g["signal_word"] is None and g["h_statements"] == ["H315"]
