"""Trust run 3 (2026-10-24): the committed snapshot's labels against the committed UNII index.

Two directions, over the real data (data/snapshots/products.json and data/seed/unii_index.json,
both written by the build): no label ingredient shown as not a MoleculeFinder molecule carries a
code that reaches one, and every matched row's code reaches the molecule it is listed under. Plus
the sweep that found the 23: no name shown as not in the catalog is a catalog molecule's title
(a test, not matching). And the hand list: every substance's FDA display name is the molecule's
own name, every alias's is the molecule's name plus a form.
"""
from __future__ import annotations

import json
import re

import pytest

from moleculefinder_etl.config import SEED_DIR, SNAPSHOTS
from moleculefinder_etl.transform import products

INDEX = SEED_DIR / "unii_index.json"
PRODUCTS = SNAPSHOTS / "products.json"

pytestmark = pytest.mark.skipif(not INDEX.exists() or not PRODUCTS.exists(),
                                reason="needs the built snapshot and data/seed/unii_index.json")


def _index() -> dict[str, dict]:
    return json.loads(INDEX.read_text())["uniis"]


def _labels() -> list[dict]:
    return [p for p in json.loads(PRODUCTS.read_text())["products"] if p["source"]["type"] == "dailymed"]


def _records() -> dict[str, dict]:
    return {r["slug"]: r for r in (json.loads(p.read_text()) for p in sorted((SNAPSHOTS / "molecules").glob("*.json")))}


def test_the_index_is_sorted_and_names_only_catalog_molecules_with_a_known_route():
    data = json.loads(INDEX.read_text())
    uniis = data["uniis"]
    assert data["count"] == len(uniis) >= 900
    assert data["source"].startswith("FDA Substance Registration System (UNII_Records_")
    assert list(uniis) == sorted(uniis)
    records = _records()
    hows = set(products.DIRECT_HOWS) | set(products.RULE_HOWS)
    for u, e in uniis.items():
        assert re.fullmatch(r"[0-9A-Z]{10}", u), u
        assert e["slug"] in records, (u, e)
        assert e["how"] in hows, (u, e)
    direct = sum(1 for e in uniis.values() if e["how"] in products.DIRECT_HOWS)
    assert direct >= 800                                   # the FDA table covers most of the catalog


def test_no_name_shown_as_not_in_the_catalog_carries_a_code_that_reaches_a_molecule():
    """One exemption, by design: an ACTIVE is resolved through its active moiety, never through the
    parent or skeleton rule on its own code (a zinc lozenge's active is zinc acetate, not acetic
    acid), so an active's own code may stand in the index by rule while the page names the active
    as not in the catalog. A direct code or a hand alias on an active's code always applies."""
    index = _index()
    problems = []
    for p in _labels():
        for e in p["not_in_catalog"]:
            hit = index.get(e.get("unii") or "")
            if hit is None:
                continue
            if e["role"] == "active" and hit["how"] in ("parent", "skeleton"):
                continue
            problems.append((p["slug"], e["name"], e["role"], e["unii"], hit))
    assert problems == []


def test_every_matched_rows_code_reaches_the_molecule_it_is_listed_under():
    index = _index()
    problems = []
    for p in _labels():
        for m in p["molecules"]:
            code = m.get("unii")
            if not code:
                problems.append((p["slug"], m["slug"], "no code"))
            elif code not in index:
                problems.append((p["slug"], m["slug"], code, "not in the index"))
            elif index[code]["slug"] != m["slug"]:
                problems.append((p["slug"], m["slug"], code, index[code]))
            elif m["match"] in products.RULE_HOWS and index[code]["how"] != m["match"]:
                problems.append((p["slug"], m["slug"], code, m["match"], index[code]["how"]))
    assert problems == []


def test_no_name_shown_as_not_in_the_catalog_is_a_catalog_molecules_title():
    """The sweep that found the 23 (trust run 2): a test, not matching. Case-insensitive."""
    records = _records()
    titles = {r["title"].lower(): s for s, r in records.items()}
    titles.update({(r.get("preferred_name") or "").lower(): s for s, r in records.items() if r.get("preferred_name")})
    problems = [(p["slug"], e["name"], e.get("unii"), titles[e["name"].lower()])
                for p in _labels() for e in p["not_in_catalog"] if e["name"].lower() in titles]
    assert problems == []


def test_the_hand_list_is_in_the_index_and_each_code_names_its_molecule():
    index = _index()
    records = _records()
    for u, slug in products.load_unii_substances().items():
        assert index.get(u, {}).get("slug") == slug, (u, slug, index.get(u))
        fda = (index[u]["name"] or "").lower()
        title = records[slug]["title"].lower()
        # The FDA's display name is the molecule's own name, allowing its "unspecified" marker.
        assert re.sub(r", unspecified( form)?$", "", fda) == title, (u, fda, title)
    for u, slug in products.load_unii_aliases().items():
        # An alias is final; a code the FDA's table also links directly to the same molecule is
        # simply redundant on the hand list, never a different answer.
        assert index.get(u, {}).get("slug") == slug, (u, slug, index.get(u))
        assert index[u]["how"] in ("alias", *products.DIRECT_HOWS), (u, index[u])
        assert index[u]["name"], (u, "no FDA display name")
