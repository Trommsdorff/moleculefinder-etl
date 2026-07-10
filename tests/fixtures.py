"""Compact PUG-View-shaped fixtures + assembly helpers for offline tests.

The string shapes here mirror what PubChem actually returns (verified against
live records for caffeine/ethanol/capsaicin/glucose while building M1), so the
parser tests exercise real-world formatting without any network.
"""
from __future__ import annotations


def tox_record(strings: list[str]) -> dict:
    """A PUG-View 'Toxicity' record whose String leaves are `strings`."""
    return {"Record": {"Section": [{"TOCHeading": "Non-Human Toxicity Values", "Information": [
        {"Value": {"StringWithMarkup": [{"String": s}]}} for s in strings]}]}}


def ghs_record(strings: list[str], picto_urls: list[str] | None = None) -> dict:
    """A PUG-View 'GHS Classification' record with String leaves + pictogram Markup URLs."""
    info = [{"Value": {"StringWithMarkup": [{"String": s}]}} for s in strings]
    if picto_urls:
        info.append({"Value": {"StringWithMarkup": [
            {"String": "Pictogram(s)", "Markup": [{"URL": u, "Type": "Icon"} for u in picto_urls]}]}})
    return {"Record": {"Section": [{"TOCHeading": "GHS Classification", "Information": info}]}}


# Property blocks in the *current* PubChem field naming (SMILES/ConnectivitySMILES).
CAFFEINE_PROPS = {
    "CID": 2519, "MolecularFormula": "C8H10N4O2", "MolecularWeight": "194.19",
    "SMILES": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "ConnectivitySMILES": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
    "InChI": "InChI=1S/C8H10N4O2", "InChIKey": "RYYVLZVUVIJVGH-UHFFFAOYSA-N",
    "XLogP": -0.1, "TPSA": 58.4, "HBondDonorCount": 0, "HBondAcceptorCount": 3,
    "RotatableBondCount": 0, "Complexity": 293, "Charge": 0,
}
THEOBROMINE_PROPS = {
    "CID": 5429, "MolecularFormula": "C7H8N4O2", "MolecularWeight": "180.16",
    "SMILES": "CN1C=NC2=C1C(=O)NC(=O)N2C", "ConnectivitySMILES": "CN1C=NC2=C1C(=O)NC(=O)N2C",
    "InChIKey": "YAPQBXQYLJRXSA-UHFFFAOYSA-N", "XLogP": -0.8, "TPSA": 67.2,
    "HBondDonorCount": 1, "HBondAcceptorCount": 3, "RotatableBondCount": 0, "Complexity": 289, "Charge": 0,
}
ETHANOL_PROPS = {
    "CID": 702, "MolecularFormula": "C2H6O", "MolecularWeight": "46.07",
    "SMILES": "CCO", "ConnectivitySMILES": "CCO", "InChIKey": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
    "XLogP": -0.1, "TPSA": 20.2, "HBondDonorCount": 1, "HBondAcceptorCount": 1,
    "RotatableBondCount": 0, "Complexity": 2.8, "Charge": 0,
}


def canon_row(cid, title, **kw):
    row = {"cid": cid, "enwiki_title": title, "wikidata_qid": kw.get("qid"),
           "tier": kw.get("tier", "canon"), "summary": kw.get("summary"),
           "pageviews": kw.get("pageviews", 0)}
    return row


def fetched(props, **kw):
    return {"props": props, "synonyms": kw.get("synonyms", []), "curated": kw.get("curated"),
            "toxicity": kw.get("toxicity", []), "ghs": kw.get("ghs")}
