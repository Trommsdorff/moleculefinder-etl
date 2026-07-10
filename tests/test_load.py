"""Pure DB-row construction + static snapshot export (both offline)."""
import json
import yaml

from moleculefinder_etl.config import CURATED_DIR
from moleculefinder_etl.transform import assemble, leaderboards
from moleculefinder_etl.load import supabase_loader, snapshot_export
from tests.fixtures import canon_row, fetched, CAFFEINE_PROPS, THEOBROMINE_PROPS


def _two_molecules():
    caf = assemble.assemble_record(
        canon_row(2519, "Caffeine", tier="marquee", summary="a stimulant"),
        fetched(CAFFEINE_PROPS, synonyms=["caffeine", "Guaranine"],
                curated=yaml.safe_load((CURATED_DIR / "caffeine.yaml").read_text()),
                ghs={"signal_word": "Danger", "pictograms": ["GHS06"], "h_statements": ["H302"],
                     "confidence": "from_source"}),
        set())
    theo = assemble.assemble_record(canon_row(5429, "Theobromine"), fetched(THEOBROMINE_PROPS), set())
    assemble.attach_edges([caf, theo])
    return caf, theo


def test_build_db_rows_shapes():
    caf, theo = _two_molecules()
    rows = supabase_loader.build_db_rows([caf, theo])

    assert {m["cid"] for m in rows["molecule"]} == {2519, 5429}
    caf_row = next(m for m in rows["molecule"] if m["cid"] == 2519)
    assert caf_row["tier"] == "marquee" and caf_row["_summary_source"] == "wikidata"

    # descriptors carry a source; synonyms mark the first as primary
    assert any(d["cid"] == 2519 for d in rows["descriptor"])
    caf_syns = [s for s in rows["synonym"] if s["cid"] == 2519]
    assert caf_syns[0]["is_primary"] and not any(s["is_primary"] for s in caf_syns[1:])

    # labeled hook inputs + toxicity + GHS
    assert any(p["key"] == "half_life_hours" and p["cid"] == 2519 for p in rows["property"])
    assert any(t["cid"] == 2519 and t["value_num"] == 192 for t in rows["toxicity_value"])
    assert any(g["cid"] == 2519 and g["signal_word"] == "Danger" for g in rows["ghs_classification"])

    # categories are deduped globally; memberships link by slug
    assert len({c["slug"] for c in rows["category"]}) == len(rows["category"])
    assert any(mc["cid"] == 2519 and mc["category_slug"] == "coffee" for mc in rows["molecule_category"])

    # hooks + editorial content block
    assert {"still_in_system", "dose_poison", "structure", "similar"} <= {h["type"] for h in rows["hook"] if h["cid"] == 2519}
    assert any(b["cid"] == 2519 and b["block_type"] == "editorial" for b in rows["content_block"])


def test_similarity_edges_are_intra_canon_only():
    caf, theo = _two_molecules()
    caf["edges"].append({"neighbor_cid": 999999, "neighbor_slug": "ghost",
                         "neighbor_title": "Ghost", "tanimoto": 0.9, "method": "morgan_r2_2048",
                         "confidence": "computed"})
    rows = supabase_loader.build_db_rows([caf, theo])
    neighbors = {e["neighbor_cid"] for e in rows["similarity_edge"]}
    assert 999999 not in neighbors            # neighbor outside the loaded set is dropped
    assert 5429 in neighbors                  # the real caffeine↔theobromine edge survives


def test_snapshot_export(tmp_path, monkeypatch):
    caf, theo = _two_molecules()
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    molecules = [caf, theo]
    boards = {slug: leaderboards.rank(slug, molecules) for slug in leaderboards.BOARDS}
    snapshot_export.export(molecules, boards)

    assert (tmp_path / "molecules" / "caffeine.json").exists()
    index = json.loads((tmp_path / "index.json").read_text())
    assert {e["slug"] for e in index} == {"caffeine", "theobromine"}
    biggest = json.loads((tmp_path / "leaderboards" / "biggest.json").read_text())
    assert biggest[0]["molecule_cid"] == 2519          # caffeine (194) heavier than theobromine (180)
