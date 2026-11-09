"""Gate hold (2026-11-09): a live product page never vanishes because a weekly refresh changed its
inputs; it leaves only when its row is removed from products.yaml, and then it must answer 410.

Both directions, through the real compiler: a live label that goes missing is held with its shipped
data, named and recorded; a row removed on purpose leaves and is named as removed. Plus the ledger
of every published slug, the export, the run's report, the workflow's counts and the 404 log line.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import yaml

from moleculefinder_etl import pipeline
from moleculefinder_etl.load import snapshot_export
from moleculefinder_etl.sources import dailymed
from moleculefinder_etl.transform import products, products_hold
from tests.test_products import RECORDS, SETID, SPL, _compile, _p

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "etl.yml"
COLD = _p("example-cold", "medicine", "dailymed", SETID, name="Example Cold")


def _live():
    """The shipped snapshot: the label read fine last week, so the page is live."""
    passed, _ = _compile([COLD], {SETID: dailymed.parse(SPL, SETID)})
    assert [p["slug"] for p in passed] == ["example-cold"]
    return passed


def _hold(seed, labels, shipped, *, previous=None, records=RECORDS, since="2026-11-09"):
    passed, report = _compile(seed, labels)
    out, held, removed = products_hold.hold(passed, report, seed, shipped, records,
                                            since=since, previous=previous)
    return out, held, removed, report


# ── the rule, both directions ────────────────────────────────────────────────
def test_a_live_label_gone_from_dailymed_is_held_with_its_shipped_data():
    shipped = _live()
    out, held, removed, report = _hold([COLD], {SETID: {"missing": True}}, shipped)
    assert out == shipped                                   # the page is exactly what shipped
    assert removed == []
    assert held == [{"slug": "example-cold", "name": "Example Cold", "kind": "medicine",
                     "reason": "label not found on DailyMed (withdrawn, archived or not yet fetched)",
                     "item": SETID,
                     "shipped": {"type": "dailymed", "setid": SETID, "labeler": "Example Brands LLC",
                                 "version": 4, "effective": "20260818"},
                     "since": "2026-11-09"}]
    # The gate report still says why it failed, and says it is held.
    assert report["passed"] == 0 and report["failed"] == 1 and report["held"] == 1
    assert report["failures"][0]["held"] is True
    assert report["held_products"] == ["example-cold"] and report["removed_products"] == []


def test_a_label_that_loses_molecules_below_the_gate_is_held_too():
    shipped = _live()
    thin = dailymed.parse(SPL, SETID)
    thin["ingredients"] = thin["ingredients"][:1]           # one molecule left: fails the gate
    out, held, _, _ = _hold([COLD], {SETID: thin}, shipped)
    assert out == shipped and len(held) == 1
    assert "fewer than 3" in held[0]["reason"]


def test_a_row_removed_from_the_seed_leaves_and_is_named_as_removed():
    shipped = _live()
    out, held, removed, report = _hold([], {}, shipped)
    assert out == [] and held == []
    assert removed == [{"slug": "example-cold", "name": "Example Cold", "kind": "medicine"}]
    assert report["removed_products"] == ["example-cold"]
    assert "410" in products_hold.removed_line(removed[0]) and "lib/gone.ts" in products_hold.removed_line(removed[0])


def test_a_product_that_passes_is_not_held_and_a_new_one_needs_no_shipped_copy():
    shipped = _live()
    out, held, removed, _ = _hold([COLD], {SETID: dailymed.parse(SPL, SETID)}, shipped)
    assert [p["slug"] for p in out] == ["example-cold"] and held == [] and removed == []
    # Never shipped and failing: nothing to hold, the gate's word stands.
    out, held, removed, _ = _hold([COLD], {SETID: {"missing": True}}, [])
    assert out == [] and held == [] and removed == []


def test_a_fixed_row_rebuilds_on_its_merits_from_the_new_label():
    """The Ambien case: the row re-pointed to the new set id passes, so nothing is held."""
    shipped = _live()
    moved = "11111111-2222-3333-4444-555555555555"
    out, held, _, _ = _hold([{**COLD, "item": moved}],
                            {SETID: {"missing": True}, moved: dailymed.parse(SPL, moved)}, shipped)
    assert held == [] and out[0]["source"]["setid"] == moved


def test_a_re_pointed_row_whose_new_label_fails_still_holds_the_shipped_page():
    shipped = _live()
    moved = "11111111-2222-3333-4444-555555555555"
    out, held, _, _ = _hold([{**COLD, "item": moved}], {moved: {"missing": True}}, shipped)
    assert out == shipped and held[0]["item"] == moved and held[0]["shipped"]["setid"] == SETID


def test_the_first_held_date_is_kept_week_after_week():
    shipped = _live()
    _, held, _, _ = _hold([COLD], {SETID: {"missing": True}}, shipped,
                          previous=[{"slug": "example-cold", "since": "2026-11-02"}], since="2026-11-09")
    assert held[0]["since"] == "2026-11-02"


def test_a_held_page_takes_the_catalogs_current_molecule_titles():
    shipped = _live()
    records = [{**r, "title": "Paracetamol"} if r["slug"] == "acetaminophen" else r for r in RECORDS]
    out, _, _, _ = _hold([COLD], {SETID: {"missing": True}}, shipped, records=records)
    titles = {m["slug"]: m["title"] for m in out[0]["molecules"]}
    assert titles["acetaminophen"] == "Paracetamol"


def test_a_held_page_whose_molecules_left_the_catalog_refuses_below_the_gate():
    shipped = _live()
    gone = {m["slug"] for m in shipped[0]["molecules"][:2]}
    records = [r for r in RECORDS if r["slug"] not in gone]
    with pytest.raises(SystemExit, match="example-cold.*fewer than 3"):
        _hold([COLD], {SETID: {"missing": True}}, shipped, records=records)


def test_the_hold_is_deterministic():
    shipped = _live()
    a = _hold([COLD], {SETID: {"missing": True}}, shipped)
    b = _hold([COLD], {SETID: {"missing": True}}, json.loads(json.dumps(shipped)))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_report_line_names_the_page_the_reason_and_what_to_do():
    shipped = _live()
    _, held, _, _ = _hold([COLD], {SETID: {"missing": True}}, shipped)
    line = products_hold.report_line(held[0])
    assert line.startswith("/whats-in/example-cold: held since 2026-11-09: label not found on DailyMed")
    assert SETID in line and "products.yaml" in line and "lib/gone.ts" in line


# ── the committed record and the run's report ────────────────────────────────
def test_the_held_file_is_written_sorted_and_empty_when_nothing_is_held(tmp_path):
    path = tmp_path / "products_held.json"
    products_hold.write_held([{"slug": "b"}, {"slug": "a"}], path)
    assert [h["slug"] for h in json.loads(path.read_text())] == ["a", "b"]
    products_hold.write_held([], path)
    assert json.loads(path.read_text()) == []
    assert products_hold.read_held(path) == []


def test_the_run_reports_each_held_and_removed_page_as_a_notice_and_in_the_summary(tmp_path, monkeypatch, capsys,
                                                                                   caplog):
    monkeypatch.setattr(products_hold, "HELD_FILE", tmp_path / "products_held.json")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    held = [{"slug": "ambien", "name": "Ambien", "kind": "medicine", "reason": "label not found on DailyMed",
             "item": SETID, "shipped": {"type": "dailymed", "setid": SETID}, "since": "2026-11-09"}]
    removed = [{"slug": "old-thing", "name": "Old thing", "kind": "cosmetic"}]
    with caplog.at_level(logging.INFO, logger="mfetl"):
        pipeline._report_products_held(held, removed)
    out = capsys.readouterr().out
    assert "::notice title=Product page held::/whats-in/ambien: held since 2026-11-09" in out
    assert "::warning title=Product page removed::/whats-in/old-thing" in out
    text = summary.read_text()
    assert "### Product pages held (1)" in text and "### Product pages removed on purpose (1)" in text
    assert json.loads((tmp_path / "products_held.json").read_text())[0]["slug"] == "ambien"
    assert "1 live product page(s) held, 1 removed" in caplog.text


# ── the ledger ───────────────────────────────────────────────────────────────
def test_the_ledger_never_shrinks():
    prev = {"products": ["a", "b"], "pairs": ["a-vs-b"]}
    led = products_hold.published(prev, [{"slug": "c"}, {"slug": "a"}], [])
    assert led == {"products": ["a", "b", "c"], "pairs": ["a-vs-b"]}
    assert products_hold.published(None, [{"slug": "z"}], [{"slug": "y-vs-z"}]) == {
        "products": ["z"], "pairs": ["y-vs-z"]}


def test_export_writes_the_ledger_and_keeps_it_without_one(tmp_path, monkeypatch):
    from moleculefinder_etl import freshness
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    monkeypatch.setattr(freshness, "load", lambda path=None: {})
    recs = [{"cid": 2519, "slug": "caffeine", "title": "Caffeine", "synonyms": []}]
    led = {"products": ["p"], "pairs": []}
    snapshot_export.export(recs, {}, today="2026-11-09", products=[{"slug": "p", "source": {"type": "curated"},
                                                                    "molecules": []}], published=led)
    path = tmp_path / snapshot_export.PUBLISHED
    assert json.loads(path.read_text()) == led
    snapshot_export.export(recs, {}, today="2026-11-10")
    assert json.loads(path.read_text()) == led               # never deleted by the export


def test_the_committed_ledger_covers_every_published_product_and_pair():
    """The real snapshot: every product and pair on the site is in the ledger."""
    snap = Path(__file__).resolve().parents[1] / "data" / "snapshots"
    led = products_hold.read_published(snap / products_hold.PUBLISHED)
    prods = json.loads((snap / "products.json").read_text())["products"]
    pairs = json.loads((snap / "product_pairs.json").read_text())["pairs"]
    assert {p["slug"] for p in prods} <= set(led["products"])
    assert {p["slug"] for p in pairs} <= set(led["pairs"])


def test_the_committed_held_file_matches_the_snapshot():
    """Every held product is on the site and still seeded; nothing held is missing a page."""
    root = Path(__file__).resolve().parents[1]
    held = products_hold.read_held(root / "data" / "seed" / "products_held.json")
    prods = {p["slug"] for p in json.loads((root / "data" / "snapshots" / "products.json").read_text())["products"]}
    seeded = {p["slug"] for p in products.load_seed()}
    for h in held:
        assert h["slug"] in prods and h["slug"] in seeded


# ── the workflow and the 404 line ────────────────────────────────────────────
def test_the_workflow_counts_held_pages_into_the_all_clear_and_alarm_summaries():
    wf = yaml.safe_load(WORKFLOW.read_text())
    run = wf["jobs"]["run"]
    assert run["outputs"]["products_held"] == "${{ steps.products_held.outputs.count }}"
    step = next(s for s in run["steps"] if s.get("id") == "products_held")
    assert step["if"] == "always()" and "data/seed/products_held.json" in step["run"]
    names = [s.get("name") or s.get("uses") for s in run["steps"]]
    assert names.index("Count held product pages") < names.index("commit snapshot")
    clear = next(s for s in wf["jobs"]["all-clear"]["steps"] if s.get("name") == "Summary")
    assert clear["env"]["PRODUCTS_HELD"] == "${{ needs.run.outputs.products_held }}"
    assert "Product pages held live this run" in clear["run"]
    alarm = wf["jobs"]["alarm"]["steps"][0]
    assert alarm["env"]["PRODUCTS_HELD"] == "${{ needs.run.outputs.products_held }}"
    assert alarm["run"].count("PRODUCTS_HELD") == 3            # summary, "Failed again", the issue body


def test_a_label_dailymed_answers_404_for_is_named_in_the_log(monkeypatch, caplog):
    class R:
        status_code = 404
    monkeypatch.setattr(dailymed._session, "get", lambda url, timeout: R())
    monkeypatch.setattr(dailymed, "_MIN_INTERVAL", 0)
    with caplog.at_level(logging.WARNING, logger="mfetl"):
        assert dailymed.fetch(SETID) is None
    assert f"dailymed {SETID}: 404" in caplog.text
