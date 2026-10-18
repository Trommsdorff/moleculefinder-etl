"""A run the export would refuse never writes to the database (2026-09-28, the second lesson).

Run 36422607328 refused dicalcium phosphate's placeholder summary in stage 4, the export, but
stage 3, the Supabase load, had already run and written that placeholder to production: the
guard lived in the export and the load came first. ``pipeline._preflight`` now runs every
refusal the export can make (the snapshot guard, the comparison and molecule-of-the-week
compiles) inside ``stage_load``, before a client exists.

The database here is the real PostgREST client answered by a recorder instead of the network,
so "untouched" means zero HTTP requests, not zero calls to a mock we wrote ourselves.
"""
from __future__ import annotations

import json

import httpx
import pytest
from postgrest import SyncPostgrestClient

from moleculefinder_etl import pipeline
from moleculefinder_etl.config import Settings
from moleculefinder_etl.load import snapshot_export, snapshot_guard, supabase_loader
from moleculefinder_etl.load.snapshot_guard import SnapshotRegression
from moleculefinder_etl.transform import featured, relationships
from tests.test_summary_carry import SHIPPED, _live, _plant, _record

CREDS = Settings("https://project.supabase.co", "sb_secret_test")


class Database:
    """Enough of PostgREST for ``load_all`` and ``record_run``, recording every request."""

    def __init__(self):
        self.requests: list[tuple[str, str]] = []
        self.clients = 0

    def _answer(self, request):
        self.requests.append((request.method, request.url.path.rsplit("/", 1)[-1]))
        if request.method in ("GET", "DELETE"):
            return httpx.Response(200, json=[])
        rows = json.loads(request.content)
        rows = rows if isinstance(rows, list) else [rows]
        return httpx.Response(201, json=[{**r, "id": i + 1} for i, r in enumerate(rows)])

    def client(self, settings=None):
        self.clients += 1
        return SyncPostgrestClient("https://project.supabase.co/rest/v1",
                                   http_client=httpx.Client(transport=httpx.MockTransport(self._answer)))


@pytest.fixture
def run(tmp_path, monkeypatch):
    """A workspace with the snapshot dicalcium phosphate shipped in, Wikidata fetched live (as
    on Sep 28), stages 0-2 already done, and the database replaced by a recorder. The catalog
    is one molecule, so the curated comparison and featured seeds (which name 122 pairs and 53
    weeks of other molecules) are compiled to nothing here; tests that want them to fail say so."""
    monkeypatch.delenv(snapshot_guard.OVERRIDE_ENV, raising=False)
    snapshots = tmp_path / "snapshots"
    for module in (pipeline, snapshot_export):
        monkeypatch.setattr(module, "SNAPSHOTS", snapshots)
    monkeypatch.setattr(pipeline, "MOLECULES", tmp_path / "molecules.json")
    _plant(snapshots, _record(SHIPPED))
    _live(monkeypatch)
    for stage in ("stage_seed", "stage_fetch", "stage_transform"):
        monkeypatch.setattr(pipeline, stage, lambda settings: None)
    monkeypatch.setattr(relationships, "build_comparisons", lambda molecules: {})
    monkeypatch.setattr(featured, "compile_queue", lambda molecules: None)
    db = Database()
    monkeypatch.setattr(supabase_loader, "get_client", db.client)

    def stage(summary):
        (tmp_path / "molecules.json").write_text(json.dumps([_record(summary)], ensure_ascii=False))
        return db

    stage.shipped = lambda: (snapshots / "molecules" / "dicalcium-phosphate.json").read_text()
    return stage


def test_a_refused_run_sends_the_database_nothing(run):
    """The Sep 28 run, replayed: the export's refusal now comes before the load, so not one
    request is sent, not even the failed-run ingest_run row, and the snapshot is whole."""
    db = run("chemical compound")
    before = run.shipped()
    with pytest.raises(SnapshotRegression, match=r"dicalcium-phosphate \(summary\)"):
        pipeline.run_all(CREDS)
    assert db.requests == []
    assert db.clients == 0
    assert run.shipped() == before


def test_mfetl_load_on_its_own_refuses_too(run):
    """``mfetl load`` alone runs the same preflight, so a stage-by-stage rerun cannot slip past."""
    db = run("chemical compound")
    with pytest.raises(SnapshotRegression):
        pipeline.stage_load(CREDS)
    assert db.requests == [] and db.clients == 0


def test_a_bad_seed_stops_the_run_before_the_database(run, monkeypatch):
    """The compile checks the export makes are in the preflight as well: a molecule-of-the-week
    seed naming a molecule that is not in the catalog fails before any write."""
    def bad_seed(molecules):
        raise SystemExit("featured.yaml compile failed:\n  W40: unknown slug 'quinine'")
    monkeypatch.setattr(featured, "compile_queue", bad_seed)
    db = run(SHIPPED)
    with pytest.raises(SystemExit, match="unknown slug"):
        pipeline.run_all(CREDS)
    assert db.requests == []


def test_a_clean_run_does_reach_the_database(run):
    """The control: the recorder sees writes when there are writes to see, so the empty lists
    above mean the preflight stopped the run and not that the harness was deaf."""
    db = run(SHIPPED)
    pipeline.stage_load(CREDS)
    assert ("POST", "molecule") in db.requests
    assert db.requests[-1] == ("POST", "ingest_run")


def test_without_the_preflight_the_refused_run_writes_first_as_it_did(run, monkeypatch):
    """Load-bearing check: take the preflight out of the load and the Sep 28 order comes back.
    The placeholder reaches the molecule table and the failure arrives only at the export."""
    real = pipeline._preflight
    monkeypatch.setattr(pipeline, "_preflight",
                        lambda molecules, guard=True: real(molecules, guard=False))
    db = run("chemical compound")
    with pytest.raises(SnapshotRegression):
        pipeline.run_all(CREDS)
    assert ("POST", "molecule") in db.requests

