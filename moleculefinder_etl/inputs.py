"""Which upstream inputs a snapshot was built from, so any machine rebuilds it exactly.

THE PROBLEM (tranche 2, 2026-10-18 and 2026-10-19). The snapshot is a pure function of the code
and of the upstream answers in ``data/raw_cache`` (PubChem properties, synonyms and PUG-View
annotations; Wikidata descriptions). That cache is in no commit: GitHub keeps one copy in its
Actions cache, this Mac keeps another, and each machine refreshes its own on its own clock. So
the same commit built two different snapshots, and twice a rebuild on the Mac came out with
upstream drift the weekly run had not shipped (96 molecule files the second time: synonym
order, a CAS, doxycycline's GHS block, "Rohypnol" back on flunitrazepam), which were reverted
by hand. An expiry cannot fix that (it decides WHEN a machine refreshes, not WHAT it gets), and
neither can "refuse a cache older than the last data PR" alone, because the Mac's copy was
NEWER than GitHub's both times.

THE FIX: the inputs travel with the snapshot.
* The weekly run (GitHub Actions, mode ``refresh``) fetches as it always has, then records a
  fingerprint of every input it built from: ``data/seed/inputs.json`` (committed, tiny) names
  it, ``data/raw_cache/INPUTS.json`` (inside the cache) lists every entry's hash, and the
  workflow uploads the whole cache as the artifact ``inputs-<fingerprint>`` (public repo: no
  paid minutes or storage).
* Every other run is ``pinned`` (the CLI's default off GitHub). ``mfetl sync-inputs`` downloads
  that exact artifact. A pinned run never expires a cache entry, so nothing that main was built
  from is fetched again; only what is genuinely missing (a new tranche's molecules) is fetched.
  A pinned export REFUSES unless every input main was built from is present and byte-identical,
  and it keeps main's ``refreshed`` date, so the molecule of the week does not move either.
* ``MFETL_INPUTS=refresh`` on the Mac is a one-off local refresh: it fetches fresh, records a
  local fingerprint that matches nothing on main, and so every pinned build after it refuses
  until the next ``sync-inputs``. Only the weekly run publishes inputs.

Library code (and the test suite) leaves ``MFETL_INPUTS`` unset, which is neither mode: nothing
here runs, and the caches keep the expiry rules they have always had.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from .config import RAW_CACHE, SEED_DIR

log = logging.getLogger("mfetl")

MODE_ENV = "MFETL_INPUTS"
INPUTS_FILE = SEED_DIR / "inputs.json"          # committed: the fingerprint main was built from
MANIFEST_NAME = "INPUTS.json"                   # inside the cache and the artifact: per-entry hashes
REPO = "Trommsdorff/moleculefinder-etl"
_SKIP = {MANIFEST_NAME, ".gitkeep"}


class InputsMismatch(SystemExit):
    """A pinned run whose cache is not the one main was built from."""


def mode() -> str | None:
    value = os.getenv(MODE_ENV)
    return value if value in ("pinned", "refresh") else None


def pinned() -> bool:
    return mode() == "pinned"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest(root: Path) -> dict[str, object]:
    """Every cache file's hash, keyed by its path under ``root``. A file that is a map of dated
    entries (the Wikidata descriptions) is hashed entry by entry, because a pinned run adds a new
    molecule's entry to it without touching anybody else's, and that must not read as a change."""
    out: dict[str, object] = {}
    if not root.is_dir():
        return out
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name not in _SKIP):
        data = path.read_bytes()
        rel = path.relative_to(root).as_posix()
        try:
            parsed = json.loads(data)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("entries"), dict):
            out[rel] = {"entries": {k: _sha(json.dumps(v, sort_keys=True).encode())
                                    for k, v in parsed["entries"].items()}}
        else:
            out[rel] = _sha(data)
    return out


def fingerprint(files: dict[str, object]) -> str:
    return _sha(json.dumps(files, sort_keys=True).encode())


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def differences(want: dict[str, object], have: dict[str, object], limit: int = 5) -> list[str]:
    """Inputs ``want`` names that ``have`` lacks or holds differently. Extra inputs in ``have``
    (a new molecule's) are not differences."""
    out: list[str] = []
    for rel, expected in sorted(want.items()):
        got = have.get(rel)
        if isinstance(expected, dict):
            entries = got.get("entries", {}) if isinstance(got, dict) else {}
            for key, digest in sorted(expected.get("entries", {}).items()):
                if entries.get(key) != digest:
                    out.append(f"{rel} entry {key}: {'missing' if key not in entries else 'changed'}")
                    break
        elif got != expected:
            out.append(f"{rel}: {'missing' if got is None else 'changed'}")
        if len(out) >= limit:
            break
    return out


def verify(root: Path | None = None, inputs_file: Path | None = None) -> str:
    """Refuse unless ``root`` holds every input main was built from, unchanged. Returns the
    fingerprint. Called before a pinned run fetches anything and again before it exports."""
    root, inputs_file = root or RAW_CACHE, inputs_file or INPUTS_FILE
    committed = _read(inputs_file)
    if not committed or not committed.get("fingerprint"):
        raise InputsMismatch(
            f"{inputs_file.name} names no inputs yet, so there is nothing to pin this build to. "
            f"It is written by the weekly GitHub run; until that has run once, set "
            f"{MODE_ENV}=refresh for a one-off local refresh (a data refresh, not a code build).")
    local = _read(root / MANIFEST_NAME)
    if not local or local.get("fingerprint") != committed["fingerprint"]:
        raise InputsMismatch(
            f"data/raw_cache is not the cache main was built from (main: "
            f"{committed['fingerprint'][:16]}, here: {(local or {}).get('fingerprint', 'none')[:16]}). "
            f"Run `mfetl sync-inputs` to fetch it, then build again. Building from this cache is "
            f"how tranche 2 shipped upstream drift that the weekly run had not.")
    problems = differences(local.get("files") or {}, manifest(root))
    if problems:
        raise InputsMismatch(
            "data/raw_cache has inputs that differ from the ones main was built from: "
            + "; ".join(problems) + ". Run `mfetl sync-inputs` to restore them.")
    return committed["fingerprint"]


def record(root: Path | None = None, inputs_file: Path | None = None, *, publish: bool) -> str:
    """After a refresh export: write the manifest into the cache and, on the weekly run
    (``publish``), the committed pointer the artifact upload and every pinned build read."""
    root, inputs_file = root or RAW_CACHE, inputs_file or INPUTS_FILE
    files = manifest(root)
    fp = fingerprint(files)
    if not publish:
        fp = "local-" + fp                      # matches nothing on main, by construction
    root.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST_NAME).write_text(json.dumps({"fingerprint": fp, "files": files}, sort_keys=True))
    if publish:
        inputs_file.write_text(json.dumps({"fingerprint": fp, "artifact": artifact_name(fp),
                                           "files": len(files)}, indent=1, sort_keys=True) + "\n")
    log.info("  inputs: %d cache file(s), fingerprint %s%s", len(files), fp[:22],
             "" if publish else " (local refresh: pinned builds will refuse until `mfetl sync-inputs`)")
    return fp


def artifact_name(fp: str) -> str:
    return f"inputs-{fp[:16]}"


def before_run() -> None:
    """A pinned run checks its inputs before it fetches anything."""
    if pinned():
        fp = verify()
        log.info("inputs: pinned to %s (the inputs main was built from)", fp[:16])


def before_export() -> None:
    if pinned():
        verify()


def after_export() -> None:
    if mode() == "refresh":
        record(publish=os.getenv("GITHUB_ACTIONS") == "true")


def refreshed_date(meta_path: Path) -> str | None:
    """A pinned export keeps main's data date: nothing upstream was refreshed."""
    if not pinned():
        return None
    data = _read(meta_path)
    value = (data or {}).get("refreshed")
    return value if isinstance(value, str) and value else None


# ── sync-inputs ──────────────────────────────────────────────────────────────
def _gh(*args: str) -> bytes:
    res = subprocess.run(["gh", *args], capture_output=True, check=False)
    if res.returncode != 0:
        raise SystemExit(f"gh {' '.join(args[:2])} failed: {res.stderr.decode(errors='replace').strip()}")
    return res.stdout


def download(name: str) -> bytes:
    """The newest unexpired artifact called ``name`` on the ETL repo, as zip bytes."""
    listing = json.loads(_gh("api", f"repos/{REPO}/actions/artifacts?name={name}&per_page=10"))
    live = [a for a in listing.get("artifacts", []) if not a.get("expired")]
    if not live:
        raise SystemExit(f"no unexpired artifact named {name} on {REPO}. The weekly run uploads it; "
                         f"if it has expired, set {MODE_ENV}=refresh for a one-off local refresh.")
    newest = max(live, key=lambda a: a["created_at"])
    log.info("sync-inputs: downloading %s (%.1f MB, %s)", name, newest["size_in_bytes"] / 1e6,
             newest["created_at"])
    return _gh("api", f"repos/{REPO}/actions/artifacts/{newest['id']}/zip")


def sync(zip_bytes: bytes | None = None, root: Path | None = None, inputs_file: Path | None = None) -> str:
    """Replace ``root`` with the inputs main was built from. Verified before anything is replaced:
    a download that does not hash to the committed fingerprint leaves the cache as it was. One
    cache only, never a second copy (the disk rule): the new one is unpacked beside it, checked,
    then swapped in and the old one deleted."""
    root, inputs_file = root or RAW_CACHE, inputs_file or INPUTS_FILE
    committed = _read(inputs_file)
    if not committed or not committed.get("fingerprint"):
        raise SystemExit(f"{inputs_file} names no inputs yet; nothing to sync")
    fp = committed["fingerprint"]
    if zip_bytes is None:
        zip_bytes = download(committed.get("artifact") or artifact_name(fp))
    incoming = root.with_name(root.name + ".incoming")
    shutil.rmtree(incoming, ignore_errors=True)
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            for info in z.infolist():
                target = (incoming / info.filename).resolve()
                if not str(target).startswith(str(incoming.resolve())):
                    raise SystemExit(f"refusing an artifact path outside the cache: {info.filename}")
            z.extractall(incoming)
        files = manifest(incoming)
        if fingerprint(files) != fp:
            raise SystemExit(f"the downloaded inputs hash to {fingerprint(files)[:16]}, not main's "
                             f"{fp[:16]}; the cache was left as it was")
        (incoming / MANIFEST_NAME).write_text(json.dumps({"fingerprint": fp, "files": files}, sort_keys=True))
        gitkeep = root / ".gitkeep"
        keep = gitkeep.read_bytes() if gitkeep.exists() else None
        shutil.rmtree(root, ignore_errors=True)
        incoming.rename(root)
        if keep is not None:
            (root / ".gitkeep").write_bytes(keep)
    finally:
        shutil.rmtree(incoming, ignore_errors=True)
    log.info("sync-inputs: data/raw_cache is now the cache main was built from (%s, %d files)",
             fp[:16], len(files))
    return fp
