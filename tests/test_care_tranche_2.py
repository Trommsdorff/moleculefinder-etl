"""The 2026-12-care tranche (2026-11-15, Garrett's word to build it the same day): titanium dioxide, octinoxate and
oxybenzone; carboxymethyl cellulose stops showing what PubChem's two-fragment record (CID 24748) computed from its
structure (Garrett's decision 5 on the phase 3B review). Brief: ../CARE-TRANCHE-2-PROMPT.md."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import yaml

from moleculefinder_etl.config import SEEDS_DIR
from moleculefinder_etl.transform import assemble, relationships

SNAP = Path(__file__).resolve().parents[1] / "data" / "snapshots"
NEW = ["titanium-dioxide", "octinoxate", "oxybenzone"]
M020 = {"titanium-dioxide": "(o)", "octinoxate": "(i)", "oxybenzone": "(l)"}
CLAIM_WORDS = re.compile(r"\b(only|first|most|leading|largest|world's|never|always)\b", re.IGNORECASE)


def _rec(slug):
    return json.loads((SNAP / "molecules" / f"{slug}.json").read_text())


def _products():
    return {p["slug"]: p for p in json.loads((SNAP / "products.json").read_text())["products"]}


# ── the three rows ───────────────────────────────────────────────────────────────────────────────
def test_the_tranche_is_three_rows_in_one_batch():
    with (SEEDS_DIR / "scope_b_core.csv").open(newline="", encoding="utf-8") as f:
        rows = {r["molecule"]: r for r in csv.DictReader(f) if r["batch"] == "2026-12-care"}
    assert set(rows) == {"Titanium dioxide", "Octinoxate", "Oxybenzone"}
    # PubChem's own titanium dioxide record, not CID 162651 (the FDA table's link, whose title, CAS and Wikidata item
    # are trititanium oxide's) and never the element titanium (CID 23963)
    assert rows["Titanium dioxide"]["pubchem_cid"] == "26042"
    assert {r["pubchem_cid"] for r in rows.values()} == {"26042", "5355130", "4632"}


def test_each_carries_its_m020_approval_checked_against_the_fdas_order():
    for slug, para in M020.items():
        a = _rec(slug)["approval"]
        assert a["regulator"] == "US Food and Drug Administration" and a["application"] == "OTC Monograph M020"
        assert a["basis"].startswith(f"FDA OTC monograph. M020.10{para}") and "Checked 2026-11-15" in a["basis"]
        assert "OTC000039" in a["basis"] and "OTC000008-1" in a["basis"] and "authorised" not in a


def test_each_line_is_its_description_within_the_rules():
    lines = yaml.safe_load((SEEDS_DIR / "why_it_matters.yaml").read_text())
    for slug in NEW:
        r = _rec(slug)
        assert r["description"] == lines[slug] and 100 <= len(lines[slug]) <= 200
        assert not CLAIM_WORDS.search(lines[slug]) and "—" not in lines[slug] and "–" not in lines[slug]


def test_no_name_that_is_not_the_molecule_reaches_a_name_line():
    banned = {"titanium peroxide", "flamenco", "rutile", "parsol"}
    for slug in NEW:
        r = _rec(slug)
        shown = [r.get("title_synonym") or ""] + (r.get("display_synonyms") or []) + (r.get("wikidata_names") or [])
        assert not {n.lower() for n in shown} & banned, (slug, shown)
    assert "Parsol MCX" in _rec("octinoxate")["display_synonyms"]      # the filter's own trade name stays


# ── titanium dioxide ─────────────────────────────────────────────────────────────────────────────
def test_titanium_dioxide_is_a_lattice_drawn_with_nothing():
    r = _rec("titanium-dioxide")
    assert r["cid"] == 26042 and r["title"] == "Titanium dioxide" and r["wikidata_qid"] == "Q193521"
    assert r["structure_svg"] is None and r["structure_svg_key"] is None and r["has_3d"] is False
    assert not r.get("structure_parts") and not r.get("structure_repeat_unit")
    assert r["structure_none"]["line"].startswith("a crystal lattice of titanium and oxygen with no single molecule")
    # its formula and weight stay PubChem's, those of one formula unit
    assert r["molecular_formula"] == "O2Ti" and r["isomeric_smiles"] == "O=[Ti]=O"
    # and no computed descriptor of a molecule it does not have (PubChem computes them from O=[Ti]=O)
    assert all(v is None for k, v in r["descriptors"].items() if k != "confidence")
    assert assemble.structure_none_for("caffeine") is None


def test_titanium_dioxide_reaches_its_labels_by_code_and_never_the_element():
    prods = _products()
    tio2 = {s for s, p in prods.items() for m in p["molecules"] if m["slug"] == "titanium-dioxide"}
    for s in tio2 - {"m-and-ms"}:
        m = next(m for m in prods[s]["molecules"] if m["slug"] == "titanium-dioxide")
        assert m["unii"] == "15FIX9V2JP" and m["match"] == "unii", s
    assert not any(m["slug"] == "titanium" for p in prods.values() for m in p["molecules"])
    assert not any(n.get("unii") == "15FIX9V2JP" for p in prods.values() for n in p.get("not_in_catalog") or [])
    # NyQuil's and DayQuil's labels list it (inactive); three sunscreens name it as the active
    for s in ("vicks-nyquil-intense-flu-liquicaps", "vicks-dayquil-severe-cold-and-flu"):
        assert s in tio2
    active = sorted(s for s in tio2 for m in prods[s]["molecules"] if m["slug"] == "titanium-dioxide" and m["role"] == "active")
    assert active == ["blue-lizard-sport-spf-50", "cerave-hydrating-mineral-sunscreen-spf-30",
                      "cetaphil-sheer-mineral-stick-spf-50"]


def test_the_lists_it_and_the_filters_join_carry_added_marks():
    hubs = yaml.safe_load((SEEDS_DIR / "product_hubs.yaml").read_text())
    by = {h: {m["slug"]: m for m in hubs[h]["molecules"]} for h in ("sunscreen", "toothpaste", "skincare")}
    assert [m["slug"] for m in hubs["sunscreen"]["molecules"]][-3:] == NEW
    assert "titanium-dioxide" in by["toothpaste"] and "titanium-dioxide" in by["skincare"]
    for h, members in by.items():
        for slug in set(NEW) & set(members):
            assert members[slug]["presence"] == "added" and members[slug]["presence_note"], (h, slug)
    wd = yaml.safe_load((SEEDS_DIR / "presence_wikidata.yaml").read_text())["products"]["m-and-ms"]
    assert {m["slug"]: m["presence"] for m in wd}["titanium-dioxide"] == "added"


def test_the_approvals_compile():
    hand = relationships.load_approvals()
    assert set(NEW) <= set(hand)


# ── carboxymethyl cellulose (decision 5) ─────────────────────────────────────────────────────────
def test_cmc_drops_what_the_two_fragment_record_computed_and_keeps_the_rest():
    r = _rec("carboxymethyl-cellulose")
    for f in ("molecular_formula", "molecular_weight", "canonical_smiles", "isomeric_smiles", "inchi", "inchikey"):
        assert r[f] is None, f
    assert all(v is None for k, v in r["descriptors"].items() if k != "confidence")
    assert not [c for c in r["categories"] if c["kind"] == "functional_group"]       # Aldehydes among them
    assert r["edges"] == [] and r["macromolecule"] is True and r["has_3d"] is False
    # kept: its CID (PubChem's record of the substance), title, names, Wikidata item, line and repeat unit
    assert r["cid"] == 24748 and r["title"] == "Carboxymethyl cellulose" and r["wikidata_qid"] == "Q411030"
    assert r["description"].startswith("The thickener that stops ice cream growing crystals")
    assert r["structure_repeat_unit"]["group"] == "carboxymethyl"


def test_cmc_leaves_the_weight_boards_and_every_other_molecules_neighbours():
    for board in ("lightest", "biggest"):
        rows = json.loads((SNAP / "leaderboards" / f"{board}.json").read_text())["entries"]
        assert "carboxymethyl-cellulose" not in {e["slug"] for e in rows}, board
    for p in (SNAP / "molecules").glob("*.json"):
        assert "carboxymethyl-cellulose" not in {e["neighbor_slug"] for e in json.loads(p.read_text())["edges"]}, p.name
