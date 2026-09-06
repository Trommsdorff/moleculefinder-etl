"""The deferred queue is a fence, not a note.

`sources/seeds/deferred_rows.csv` records molecules pulled back OUT of a built tranche
and why. Without a test it is documentation, and the next tranche, assembled from
`../drugs-wing-deferred.csv` in view-count order, would re-add exactly the highest-traffic
rows that were held: trenbolone and xylazine are in the top 15 of that queue.
"""
from __future__ import annotations

import csv

from moleculefinder_etl.transform import canon

DEFERRED_CSV = canon.SEEDS_DIR / "deferred_rows.csv"


def _rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(line for line in f if not line.startswith("#"))]


def test_deferred_file_is_shaped():
    rows = _rows(DEFERRED_CSV)
    assert rows, "deferred_rows.csv must not be empty while a hold is in force"
    for r in rows:
        assert r["molecule"] and r["pubchem_cid"]
        assert r["held_from_batch"], f"{r['molecule']} must say which tranche it was held from"
        # A reason a reader can act on, not a shrug. The hold rule is a scope decision and
        # the next person to look at this file needs to be able to disagree with it.
        assert len(r["reason"]) > 30, f"{r['molecule']} needs a real reason, got {r['reason']!r}"


def test_no_deferred_row_is_in_the_canon():
    held = {r["molecule"].strip().lower(): r for r in _rows(DEFERRED_CSV)}
    held_cids = {int(r["pubchem_cid"]) for r in held.values()}
    with canon.SCOPE_B_CSV.open(newline="", encoding="utf-8") as f:
        canon_rows = list(csv.DictReader(f))
    by_name = [r["molecule"] for r in canon_rows if r["molecule"].strip().lower() in held]
    by_cid = [r["molecule"] for r in canon_rows
              if r["pubchem_cid"].strip() and int(r["pubchem_cid"]) in held_cids]
    assert not by_name, f"held molecule(s) back in scope_b_core.csv by name: {by_name}"
    assert not by_cid, f"held molecule(s) back in scope_b_core.csv by CID: {by_cid}"
