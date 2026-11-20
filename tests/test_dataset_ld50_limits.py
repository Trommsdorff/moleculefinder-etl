"""The CC0 dataset names an LD50 limit in words beside the figure (Garrett's ruling, 2026-11-15, the 2026-12-care review,
decision 3: a limit is not a value). The column ships in the next published version (2026.11), once Zenodo mints its DOI."""
from __future__ import annotations

from moleculefinder_etl import dataset


def _pv(*strings: str) -> dict:
    return {"Record": {"Reference": [{"ReferenceNumber": 1, "SourceName": "Hazardous Substances Data Bank (HSDB)"}],
                       "Section": [{"Information": [{"ReferenceNumber": 1, "Value": {"StringWithMarkup": [
                           {"String": s} for s in strings]}}]}]}}


# ── the CC0 dataset ──────────────────────────────────────────────────────────────────────────────────────────────
def test_the_dataset_names_the_limit_in_words_beside_the_figure():
    cols = [c[0] for c in dataset.TABLES["molecules"]]
    assert cols.index("ld50_qualifier") == cols.index("ld50_mg_per_kg") + 1
    m = {"slug": "x", "title": "X", "ld50_mg_per_kg": 10000.0, "ld50_species": "rat", "ld50_route": "oral",
         "ld50_qualifier": ">"}
    row = dataset.molecule_row(m, ["Hazardous Substances Data Bank (HSDB)"])
    assert (row["ld50_mg_per_kg"], row["ld50_qualifier"]) == (10000.0, "more than")
    plain = dataset.molecule_row({**m, "ld50_qualifier": None}, ["Hazardous Substances Data Bank (HSDB)"])
    assert plain["ld50_qualifier"] is None


def test_the_dataset_traces_a_limit_only_to_a_source_that_gives_it_as_a_limit():
    rec = _pv("LD50 Rat oral > 10,000 mg/kg")
    assert dataset.ld50_sources(rec, 10000.0, "rat", "oral", ">") == ["Hazardous Substances Data Bank (HSDB)"]
    assert dataset.ld50_sources(rec, 10000.0, "rat", "oral") == []
