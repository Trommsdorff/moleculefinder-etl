"""Phase 3A (2026-11-14): four corrections to what is live.

1. (web only) product page descriptions.
2. The hazard statements' words, from the US Hazard Communication Standard (registry osha_hcs).
3. One-element records' "Also called" from Wikidata's names only; the eleven symbol origins; the sweep.
4. Fructose and allulose drawn as their rings (seeds/structure_display.yaml), the same substance.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from moleculefinder_etl.sources import registry
from moleculefinder_etl.transform import assemble, ghs, structures

SNAP = Path(__file__).resolve().parents[1] / "data" / "snapshots"
SEEDS = Path(__file__).resolve().parents[1] / "moleculefinder_etl" / "sources" / "seeds"


def _mol(slug: str) -> dict:
    return json.loads((SNAP / "molecules" / f"{slug}.json").read_text())


def _all() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((SNAP / "molecules").glob("*.json"))]


# ── 2. hazard statement words ────────────────────────────────────────────────────────────────
def test_the_wording_source_is_registered_public_domain():
    assert registry.licence_class("osha_hcs") == "public_domain"
    assert registry.may_display("osha_hcs")


def test_the_seed_words_every_code_once_with_its_table():
    words = ghs.hazard_wording()
    assert len(words) == 50
    raw = yaml.safe_load((SEEDS / "hazard_statements.yaml").read_text())["statements"]
    for code, e in raw.items():
        assert e["hcs"].startswith("C.4."), code
        assert e["class"], code
    # The codes the HCS does not adopt stay codes.
    for code in ("H303", "H305", "H313", "H316", "H333", "H400", "H401", "H402", "H410", "H411", "H412", "H413"):
        assert code not in words


def test_with_wording_keeps_the_label_and_adds_only_worded_codes():
    label = {"signal_word": "Warning", "pictograms": ["GHS07"], "h_statements": ["H302", "H410"],
             "confidence": "from_source", "sources": ["echa"]}
    out = ghs.with_wording(label)
    # Phase 3B: H410 now takes the EU CLP Regulation's words, listed in h_wording_clp; the HCS stays the source of H302.
    assert out["h_wording"] == {"H302": "Harmful if swallowed", "H410": "Very toxic to aquatic life with long lasting effects"}
    assert out["h_wording_source"] == "osha_hcs" and out["h_wording_clp"] == ["H410"]
    assert {k: out[k] for k in label} == label          # the classification itself untouched
    # A code no allowed source words (H401: CLP does not adopt acute aquatic category 2) stays a code.
    assert ghs.with_wording({"h_statements": ["H401"], "sources": ["echa"]}) == {"h_statements": ["H401"], "sources": ["echa"]}
    assert ghs.with_wording(None) is None


def test_the_snapshot_words_exactly_the_codes_the_seed_has():
    words, clp = ghs.hazard_wording(), ghs.clp_wording()
    worded = 0
    for m in _all():
        g = m.get("ghs") or {}
        want = {c: words[c] for c in g.get("h_statements") or [] if c in words}
        eu = {c: clp[c] for c in g.get("h_statements") or [] if c in clp}     # phase 3B
        assert (g.get("h_wording") or {}) == {**want, **eu}, m["slug"]
        assert g.get("h_wording_clp", []) == sorted(eu), m["slug"]
        if want:
            assert g["h_wording_source"] == "osha_hcs"
            worded += 1
        else:
            assert "h_wording_source" not in g, m["slug"]
    assert worded > 600


# ── 3. names ─────────────────────────────────────────────────────────────────────────────────
def test_a_one_element_line_is_wikidata_names_plus_a_name_its_text_uses():
    for m in _all():
        if not assemble.one_element(m):
            continue
        wd = m.get("wikidata_names") or []
        texts = [m.get("description"), (m.get("why_it_matters") or {}).get("text")]
        for n in m["display_synonyms"]:
            assert n in wd or any(assemble._uses_name(t, n) for t in texts if t), (m["slug"], n)
    assert _mol("chromium")["display_synonyms"] == ["Cr", "Chrome"]
    assert _mol("chromium")["title_synonym"] == "Chrome"          # the title does not move
    assert _mol("bismuth")["display_synonyms"] == []                # "Colitis" gone
    assert _mol("polonium")["display_synonyms"] == []               # "Mens external delayed" gone


def test_the_eleven_symbol_origins():
    want = {"sodium": "Na", "potassium": "K", "iron": "Fe", "copper": "Cu", "silver": "Ag", "tin": "Sn",
            "antimony": "Sb", "tungsten": "W", "gold": "Au", "mercury": "Hg", "lead": "Pb"}
    have = {m["slug"]: m["symbol_origin"] for m in _all() if m.get("symbol_origin")}
    assert set(have) == set(want)
    for slug, sym in want.items():
        o = have[slug]
        assert o["symbol"] == sym and sym in o["line"] and o["name"] in o["line"]
        assert o["source"] == "curated" and o["confidence"] == "from_source"
        assert "—" not in o["line"] and "–" not in o["line"]
    # No null key on any other record (IndexNow fingerprints whole records).
    assert sum("symbol_origin" in m for m in _all()) == 11


def test_the_swept_names_are_off_every_line():
    swept = {"s-wat", "sulftech", "evits", "paratartaric aicd", "tatum-t", "natriumsulfid"}
    for m in _all():
        for n in (m.get("display_synonyms") or []) + (m.get("wikidata_names") or []):
            assert n.casefold() not in swept, (m["slug"], n)
    # A medicine's brand stays (Garrett's 2026-09-12 ruling).
    assert "Actigall" in _mol("ursodeoxycholic-acid")["display_synonyms"]


# ── 4. the sugars as rings ───────────────────────────────────────────────────────────────────
FRUCTOSE_CHAIN = "C([C@H]([C@H]([C@@H](C(=O)CO)O)O)O)O"
ALLULOSE_CHAIN = "C([C@H]([C@H]([C@H](C(=O)CO)O)O)O)O"


def test_a_ring_opens_to_its_own_chain_and_to_no_other():
    pytest.importorskip("rdkit")
    seed = yaml.safe_load((SEEDS / "structure_display.yaml").read_text())["molecules"]
    fru, allu = seed["fructose"]["smiles"], seed["allulose"]["smiles"]
    assert structures.ring_opens_to(fru, FRUCTOSE_CHAIN)
    assert structures.ring_opens_to(allu, ALLULOSE_CHAIN)
    assert not structures.ring_opens_to(fru, ALLULOSE_CHAIN)       # the C3 epimer
    assert not structures.ring_opens_to(allu, FRUCTOSE_CHAIN)
    mirror = "C([C@H]1[C@@H]([C@H](C(O1)(CO)O)O)O)O"                # L-fructofuranose
    assert not structures.ring_opens_to(mirror, FRUCTOSE_CHAIN)


def test_fructose_is_drawn_as_the_ring_inside_sucrose():
    """The five-membered ring the page's text and sucrose's part describe: the display ring matches
    sucrose's fructose unit, every stereocentre included."""
    Chem = pytest.importorskip("rdkit.Chem")
    ring = Chem.MolFromSmiles(_mol("fructose")["structure_display"]["smiles"])
    sucrose = Chem.MolFromSmiles(_mol("sucrose")["isomeric_smiles"])
    assert sucrose.HasSubstructMatch(ring, useChirality=True)
    glucose = Chem.MolFromSmiles(_mol("glucose")["isomeric_smiles"])
    assert not glucose.HasSubstructMatch(ring, useChirality=True)


def test_the_3d_model_is_the_commoner_furanose():
    """fructose's model is beta-D-fructofuranose (CID 439709), the anomer inside sucrose; allulose's is
    alpha-D-psicofuranose (CID 21581131). Both conformers were read in the session (2026-11-14)."""
    assert _mol("fructose")["structure_display"]["model_cid"] == 439709
    assert _mol("allulose")["structure_display"]["model_cid"] == 21581131


def test_the_record_stays_the_same_substance():
    """Only the drawing, its key and its parts move: every identifier is PubChem's record."""
    for slug, chain, cid in (("fructose", FRUCTOSE_CHAIN, 5984), ("allulose", ALLULOSE_CHAIN, 90008)):
        m = _mol(slug)
        d = m["structure_display"]
        assert m["isomeric_smiles"] == chain and m["cid"] == cid
        assert m["molecular_formula"] == "C6H12O6" and m["molecular_weight"] == 180.16
        assert m["structure_svg_key"] == structures.svg_key(d["smiles"])
        assert d["cid"] != cid and d["has_3d"] is True and m["has_3d"] is True
        assert d["model_cid"] not in (cid, d["cid"])
        assert structures.drawn_smiles(m) == d["smiles"]
    assert sum("structure_display" in m for m in _all()) == 2


def test_the_display_lines_are_under_the_claim_rule():
    """Garrett, 2026-11-14: fructose's line names the six-membered ring as most of free fructose in
    water, a claim word with its entry; allulose's gives no share and carries none. Both lines are in
    the claim corpus (kind part, display.<slug>.line), so an edit to either is checked."""
    from moleculefinder_etl.transform import claims
    lines = {key: text for kind, key, text in claims.corpus() if kind == "part" and key.startswith("display.")}
    assert set(lines) == {"display.fructose.line", "display.fructose.model_line",
                          "display.allulose.line", "display.allulose.model_line"}
    assert lines["display.fructose.line"].startswith("Drawn as a ring, as nearly all fructose in water is.")
    assert "most free fructose in water is the six-membered ring" in lines["display.fructose.line"]
    assert claims.words_in(lines["display.fructose.line"]) == ["most"]
    assert "percent" not in lines["display.allulose.line"]
    assert claims.words_in(lines["display.allulose.line"]) == []
    entry = claims.load_allowed()[("part", "display.fructose.line")]
    assert entry["basis"] == "science" and entry["line"] == claims.line_id(lines["display.fructose.line"])
    assert claims.line_problems() == []
