"""Medicines admitted under a ruling carry their licence basis on the record (Garrett, 2026-10-18).

The rule: a CURRENT marketing authorisation for human use from the FDA, the MHRA, the EMA, or the
national regulator of any single EU member state. approvals.yaml records the basis for the rows let in
under a ruling, and orforglipron's FDA approval was confirmed from the regulator's own record."""
from __future__ import annotations

import csv

import pytest
import yaml

from moleculefinder_etl.config import SEEDS_DIR
from moleculefinder_etl.transform import relationships
from moleculefinder_etl.transform.slugs import slugify


def _seed():
    return yaml.safe_load((SEEDS_DIR / "approvals.yaml").read_text())


def test_every_ruled_row_has_an_entry_and_every_entry_is_in_the_catalog():
    core = {slugify(r["molecule"]) for r in csv.DictReader((SEEDS_DIR / "scope_b_core.csv").open())}
    seed = _seed()
    assert {"orforglipron", "meldonium", "phenibut", "clenbuterol", "clostebol"} <= set(seed)
    assert set(seed) <= core


def test_orforglipron_cites_the_fda_record():
    o = _seed()["orforglipron"]
    assert o["application"] == "NDA 220934" and o["authorised"] == "2026-04-01"
    assert o["source"].startswith("https://www.accessdata.fda.gov/")
    assert o["label"].startswith("https://dailymed.nlm.nih.gov/")


def test_attach_puts_the_basis_on_the_record():
    recs = {s: {"slug": s} for s in [*_seed(), "caffeine"]}
    relationships.attach_approvals(list(recs.values()))
    assert recs["orforglipron"]["approval"]["product"] == "Foundayo"
    assert "Latvian" in recs["meldonium"]["approval"]["basis"]
    assert "approval" not in recs["caffeine"]


def test_an_unknown_slug_or_a_missing_basis_fails_the_build(tmp_path, monkeypatch):
    bad = tmp_path / "approvals.yaml"
    bad.write_text("nosuch:\n  regulator: FDA\n  basis: x\nmeldonium:\n  regulator: x\n")
    monkeypatch.setattr(relationships, "APPROVALS_YAML", bad)
    with pytest.raises(SystemExit) as err:
        relationships.attach_approvals([{"slug": "meldonium"}])
    assert "nosuch: unknown slug" in str(err.value) and "meldonium: needs a regulator and a basis" in str(err.value)


def test_the_two_vet_only_rows_are_held_and_phenibut_stays():
    held = (SEEDS_DIR / "deferred_rows.csv").read_text()
    core = (SEEDS_DIR / "scope_b_core.csv").read_text()
    for name in ("Fenbendazole", "Carfentanil", "Nandrolone"):
        assert f"\n{name}," in held and f",{name}," not in core
    assert ",Phenibut," in core
