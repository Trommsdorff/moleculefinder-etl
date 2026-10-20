"""The snapshot comes out the same whichever machine builds it (moleculefinder_etl/inputs.py).

Tranche 2 twice rebuilt on the Mac and got upstream drift the weekly run had not shipped (96
molecule files the second time), because the two machines held different caches. These pin
the fix: the weekly run records the inputs it built from, a pinned build refuses any other
cache, `sync-inputs` installs exactly those inputs, and a pinned build never re-fetches them.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
import yaml

from moleculefinder_etl import cli, inputs, pipeline
from moleculefinder_etl.load import snapshot_export
from moleculefinder_etl.sources import cache

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "etl.yml"


def _cache(root: Path) -> Path:
    """A miniature data/raw_cache: two PubChem entries and a Wikidata descriptions map."""
    (root / "pubchem").mkdir(parents=True)
    (root / "wikidata").mkdir()
    cache.write_json(root / "pubchem" / "syn60-2519.json", ["Caffeine", "Guaranine"], "2026-10-19T06:01:00Z")
    (root / "pubchem" / "props-2519.json").write_text(json.dumps({"CID": 2519, "MolecularFormula": "C8H10N4O2"}))
    (root / "wikidata" / "descriptions.json").write_text(json.dumps({
        cache.ENVELOPE_KEY: 1, "fetched_at": "2026-10-19T06:00:00Z",
        "entries": {"2519": {"desc": "stimulant", "qid": "Q60235", "aliases": [],
                             "fetched_at": "2026-10-19T06:00:00Z"}}}))
    return root


def _published(tmp_path: Path) -> tuple[Path, Path]:
    """The weekly run's side: a cache plus the committed inputs.json naming it."""
    root, inputs_file = _cache(tmp_path / "ci_cache"), tmp_path / "inputs.json"
    inputs.record(root, inputs_file, publish=True)
    return root, inputs_file


def _zip(root: Path) -> bytes:
    """What actions/upload-artifact stores: the cache directory's contents."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(root).as_posix())
    return buf.getvalue()


# ── the weekly run records what it built from ───────────────────────────────
def test_the_weekly_run_records_a_fingerprint_and_an_artifact_name(tmp_path):
    root, inputs_file = _published(tmp_path)
    pointer = json.loads(inputs_file.read_text())
    manifest = json.loads((root / inputs.MANIFEST_NAME).read_text())
    assert pointer["fingerprint"] == manifest["fingerprint"] == inputs.fingerprint(inputs.manifest(root))
    assert pointer["artifact"] == "inputs-" + pointer["fingerprint"][:16] and pointer["files"] == 3
    # The descriptions map is hashed entry by entry; a plain file is one hash.
    assert set(manifest["files"]["wikidata/descriptions.json"]["entries"]) == {"2519"}
    assert isinstance(manifest["files"]["pubchem/props-2519.json"], str)
    assert inputs.verify(root, inputs_file) == pointer["fingerprint"]


def test_a_local_refresh_never_publishes_and_pinned_builds_then_refuse(tmp_path):
    root, inputs_file = _published(tmp_path)
    before = inputs_file.read_text()
    cache.write_json(root / "pubchem" / "syn60-2519.json", ["Caffeine", "Theine"])   # a fresh local fetch
    inputs.record(root, inputs_file, publish=False)
    assert inputs_file.read_text() == before                     # main's pointer is untouched
    with pytest.raises(inputs.InputsMismatch, match="sync-inputs"):
        inputs.verify(root, inputs_file)


# ── the refusal ──────────────────────────────────────────────────────────────
def test_a_cache_main_was_not_built_from_is_refused(tmp_path):
    """Tranche 2's case: this Mac's own cache, newer than the weekly run's, never synced."""
    _, inputs_file = _published(tmp_path)
    mac = _cache(tmp_path / "mac_cache")
    cache.write_json(mac / "pubchem" / "syn60-2519.json", ["Caffeine", "Rohypnol"])
    with pytest.raises(inputs.InputsMismatch, match="not the cache main was built from"):
        inputs.verify(mac, inputs_file)


@pytest.mark.parametrize("tamper, says", [
    (lambda r: (r / "pubchem" / "props-2519.json").write_text('{"CID": 2519}'), "props-2519.json: changed"),
    (lambda r: (r / "pubchem" / "syn60-2519.json").unlink(), "syn60-2519.json: missing"),
    (lambda r: (r / "wikidata" / "descriptions.json").write_text(json.dumps({
        cache.ENVELOPE_KEY: 1, "entries": {"2519": {"desc": "chemical compound"}}})), "entry 2519: changed"),
])
def test_an_input_changed_after_the_sync_is_refused(tmp_path, tamper, says):
    root, inputs_file = _published(tmp_path)
    tamper(root)
    with pytest.raises(inputs.InputsMismatch, match=says):
        inputs.verify(root, inputs_file)


def test_a_new_molecules_inputs_are_not_a_difference(tmp_path):
    """A tranche built pinned fetches only its new molecules: new files and new entries pass."""
    root, inputs_file = _published(tmp_path)
    cache.write_json(root / "pubchem" / "syn60-5793.json", ["Glucose"])
    d = json.loads((root / "wikidata" / "descriptions.json").read_text())
    d["entries"]["5793"] = {"desc": "sugar", "qid": "Q37525", "aliases": [], "fetched_at": "2026-10-20T00:00:00Z"}
    d["fetched_at"] = "2026-10-20T00:00:00Z"
    (root / "wikidata" / "descriptions.json").write_text(json.dumps(d))
    inputs.verify(root, inputs_file)


def test_nothing_to_pin_to_is_a_refusal_with_the_way_out(tmp_path):
    with pytest.raises(inputs.InputsMismatch, match="MFETL_INPUTS=refresh"):
        inputs.verify(_cache(tmp_path / "c"), tmp_path / "absent.json")


def test_a_pinned_export_refuses_before_it_writes_anything(tmp_path, monkeypatch):
    """Through the real stage: the refusal comes before snapshot_export.export is called."""
    _, inputs_file = _published(tmp_path)
    mac = _cache(tmp_path / "mac_cache")
    cache.write_json(mac / "pubchem" / "syn60-2519.json", ["Caffeine", "Rohypnol"])
    molecules = tmp_path / "molecules.json"
    molecules.write_text("[]")
    monkeypatch.setenv(inputs.MODE_ENV, "pinned")
    monkeypatch.setattr(inputs, "RAW_CACHE", mac)
    monkeypatch.setattr(inputs, "INPUTS_FILE", inputs_file)
    monkeypatch.setattr(pipeline, "MOLECULES", molecules)
    monkeypatch.setattr(pipeline, "_preflight", lambda m, guard=True: ({}, {}, None))
    wrote = []
    monkeypatch.setattr(snapshot_export, "export", lambda *a, **k: wrote.append(1))
    with pytest.raises(inputs.InputsMismatch):
        pipeline.stage_export(None)
    assert wrote == []


# ── the sync ─────────────────────────────────────────────────────────────────
def test_sync_installs_exactly_the_published_inputs(tmp_path):
    ci, inputs_file = _published(tmp_path)
    mac = _cache(tmp_path / "mac_cache")
    cache.write_json(mac / "pubchem" / "syn60-2519.json", ["Caffeine", "Rohypnol"])
    (mac / ".gitkeep").write_text("")
    inputs.sync(_zip(ci), mac, inputs_file)
    assert json.loads((mac / "pubchem" / "syn60-2519.json").read_text())["value"] == ["Caffeine", "Guaranine"]
    assert (mac / ".gitkeep").exists() and not mac.with_name("mac_cache.incoming").exists()
    inputs.verify(mac, inputs_file)


def test_a_download_that_does_not_hash_to_main_leaves_the_cache_alone(tmp_path):
    ci, inputs_file = _published(tmp_path)
    (ci / "pubchem" / "props-2519.json").write_text('{"CID": 1}')           # corrupted in transit
    mac = _cache(tmp_path / "mac_cache")
    before = inputs.manifest(mac)
    with pytest.raises(SystemExit, match="the cache was left as it was"):
        inputs.sync(_zip(ci), mac, inputs_file)
    assert inputs.manifest(mac) == before and not mac.with_name("mac_cache.incoming").exists()


# ── a pinned build never re-fetches, and keeps main's date ──────────────────
def test_pinned_reads_ignore_the_expiry_and_unset_mode_keeps_it(monkeypatch, tmp_path):
    p = tmp_path / "old.json"
    cache.write_json(p, "x", "2026-01-01T00:00:00Z")
    monkeypatch.delenv(inputs.MODE_ENV, raising=False)
    assert cache.read_json(p, 6) is None                      # library default: expired
    monkeypatch.setenv(inputs.MODE_ENV, "refresh")
    assert cache.read_json(p, 6) is None                      # the weekly run: expired, re-fetched
    monkeypatch.setenv(inputs.MODE_ENV, "pinned")
    assert cache.read_json(p, 6).value == "x"                 # pinned: the input main used


def test_a_pinned_export_keeps_mains_refreshed_date(monkeypatch, tmp_path):
    meta = tmp_path / "meta.json"
    meta.write_text('{"refreshed": "2026-10-19"}')
    monkeypatch.setenv(inputs.MODE_ENV, "pinned")
    assert inputs.refreshed_date(meta) == "2026-10-19"
    monkeypatch.setenv(inputs.MODE_ENV, "refresh")
    assert inputs.refreshed_date(meta) is None                # the weekly run stamps today


@pytest.mark.parametrize("gha, expected", [("true", "refresh"), (None, "pinned")])
def test_the_cli_pins_everywhere_but_the_weekly_run(monkeypatch, gha, expected):
    monkeypatch.delenv(inputs.MODE_ENV, raising=False)
    if gha:
        monkeypatch.setenv("GITHUB_ACTIONS", gha)
    else:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(inputs, "sync", lambda: None)
    assert cli.main(["sync-inputs"]) == 0
    assert inputs.mode() == expected


def test_the_weekly_run_uploads_the_inputs_only_after_a_green_commit():
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["run"]["steps"]
    names = [s.get("name") or s.get("uses") for s in steps]
    commit, name = names.index("commit snapshot"), names.index("Name the inputs artifact")
    upload = names.index("actions/upload-artifact@v4")
    failed = names.index("heartbeat after a failed run")
    assert commit < name < upload < failed
    assert "if" not in steps[name] and "if" not in steps[upload]        # success() only
    assert "data/seed/inputs.json" in steps[name]["run"]
    assert steps[upload]["with"]["path"] == "data/raw_cache"
    assert steps[upload]["with"]["name"] == "${{ steps.inputs.outputs.artifact }}"
