"""Every curated overlay (sources/curated/*.yaml) joins the catalog by CID, so an overlay whose CID
is not a catalog molecule's silently applies to nothing. Fructose's did exactly that from the day it
was written until SEO run 2 (2026-10-28): CID 2723872 against the catalog's 5984, so its type, foods
and editorial never reached the site. This holds every overlay's CID and slug to the snapshot."""
from __future__ import annotations

import json

import pytest
import yaml

from moleculefinder_etl.config import CURATED_DIR, SNAPSHOTS


def test_every_curated_overlay_keys_a_catalog_molecule_by_cid_and_slug():
    files = sorted((SNAPSHOTS / "molecules").glob("*.json")) if SNAPSHOTS.exists() else []
    if not files:
        pytest.skip("no snapshot exported yet")
    by_cid = {}
    for f in files:
        m = json.loads(f.read_text())
        by_cid[int(m["cid"])] = m["slug"]
    problems = []
    for path in sorted(CURATED_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        cid = data.get("cid")
        if not cid:
            continue
        slug = by_cid.get(int(cid))
        if slug is None:
            problems.append(f"{path.name}: cid {cid} is not a catalog molecule")
        elif data.get("slug") and data["slug"] != slug:
            problems.append(f"{path.name}: cid {cid} is {slug}, not {data['slug']}")
    assert problems == []


def test_fructose_is_keyed_to_the_catalogs_fructose():
    data = yaml.safe_load((CURATED_DIR / "fructose.yaml").read_text())
    assert data["cid"] == 5984 and data["slug"] == "fructose"
    assert "sugar" in data["types"]
    assert {f["category"] for f in data["foods"]} == {"fruit", "honey"}
