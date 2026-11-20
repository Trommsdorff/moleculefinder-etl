"""Publish a new version of the MoleculeFinder dataset to Zenodo (`mfetl zenodo`, 2026-11-20).

Garrett's word (2026-11-17): new dataset versions publish themselves; his whole part is one Zenodo personal
access token, made once, kept in this repo's gitignored `.env` as ZENODO_TOKEN (scopes `deposit:write` and
`deposit:actions`). The token is read here with python-dotenv and sent only in the Authorization header. It is
never printed, never logged, and never in a URL; every message that could carry it is redacted first.

    mfetl zenodo --dry-run       read Zenodo (public, no token needed) and check everything; create nothing
    mfetl zenodo --draft-only    make the real draft with its files and stop before publishing
    mfetl zenodo                 the same, then publish (or publish the draft --draft-only left)
    mfetl zenodo --discard       delete this version's open draft and put the repo's files back
    mfetl zenodo --check         after a publish: the public record, its files and the DOIs, read only

WHAT A PUBLISH DOES, in order. Every check runs before the publish call, because a published Zenodo version
cannot be deleted:
  1. The package in data/dataset/ matches its MANIFEST.json byte for byte, says CC0, and names its version.
  2. Zenodo's record is MoleculeFinder's (the concept DOI in sources/seeds/dataset_published.yaml, the title,
     the creator, CC0), the repo's latest recorded version is Zenodo's latest, and this version is not on
     Zenodo yet and is newer than the latest.
  3. A new version of the record is opened (a draft) and Zenodo reserves its DOI.
  4. `mfetl dataset --version V --doi <that DOI>` records the DOI in dataset_published.yaml and rebuilds the
     package, so the package cites its own DOI. Only the documents may change; every data file must be
     byte-identical to the one checked in step 1.
  5. The draft's files are replaced with the package's (ZENODO_FILES) and its metadata is set from the
     package's zenodo.json.
  6. The draft is read back: its file list must be exactly the package's, every size and checksum must match,
     and title, version, date, licence, creators and the reserved DOI must be what the package says.
  7. Publish. Zenodo's reply must carry the reserved DOI and the concept DOI.
A failed run deletes the draft it made and puts dataset_published.yaml and data/dataset/ back as they were; if
the delete itself fails, it names the draft and how to discard it. Nothing is committed here: the caller
commits the recorded version (by hand today, the Mac's weekly job later).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import REPO_ROOT

log = logging.getLogger("mfetl.zenodo")

API = "https://zenodo.org/api"
ENV_FILE = REPO_ROOT / ".env"
TOKEN_KEY = "ZENODO_TOKEN"
# The package's own metadata file for Kaggle stays off Zenodo, as it did in 2026.10 and 2026.10.1 (17 files).
NOT_ON_ZENODO = frozenset({"dataset-metadata.json"})
CREATORS = ["MoleculeFinder"]
ZENODO_LICENCE = "cc-zero"
# The package files whose bytes may change when the version's own DOI is written into them (step 4).
DOCUMENTS = frozenset({"CITATION.cff", "README.md", "zenodo.json", "datapackage.json", "dataset-metadata.json",
                       "LICENSE.txt"})
TIMEOUT = 60
UPLOAD_TIMEOUT = 600
_ZENODO_DOI = re.compile(r"^10\.5281/zenodo\.(\d+)$")


class Refused(RuntimeError):
    """A check failed; nothing was published."""


# ── the token ───────────────────────────────────────────────────────────────────────────────────────────────────
def token(env_file: Path = ENV_FILE) -> str:
    """ZENODO_TOKEN from the ETL's .env (python-dotenv; the file is never sourced in a shell)."""
    from dotenv import dotenv_values
    if not env_file.is_file():
        raise Refused(f"no {env_file.name} at {env_file}; the token goes there as {TOKEN_KEY}")
    value = (dotenv_values(env_file).get(TOKEN_KEY) or "").strip()
    if not value:
        raise Refused(f"{env_file} has no {TOKEN_KEY} (see docs/MAC-WEEKLY-REFRESH.md, 'The dataset on Zenodo')")
    return value


class Client:
    """Zenodo's REST API with the token in the Authorization header only. Every error message is redacted."""

    def __init__(self, tok: str | None, api: str = API, session: Any = None):
        import requests
        self._tok = tok
        self.api = api.rstrip("/")
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = "moleculefinder-etl (dataset publisher)"
        if tok:
            self.s.headers["Authorization"] = f"Bearer {tok}"

    def redact(self, text: str) -> str:
        return text.replace(self._tok, "[token]") if self._tok else text

    def call(self, method: str, url: str, *, ok: tuple[int, ...] = (200,), timeout: int = TIMEOUT, raw: bool = False,
             **kw) -> Any:
        if not url.startswith("http"):
            url = self.api + url
        try:
            r = self.s.request(method, url, timeout=timeout, **kw)
        except Exception as e:  # noqa: BLE001  any network error: its text can carry a header, so redact it
            raise Refused(self.redact(f"{method} {url}: {type(e).__name__}: {e}")) from None
        if r.status_code not in ok:
            body = self.redact((r.text or "")[:600])
            raise Refused(f"{method} {url}: HTTP {r.status_code}: {body}")
        if raw:
            return r.content
        if r.status_code == 204 or not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return r.content


# ── the package ─────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Package:
    root: Path
    manifest: dict[str, Any]
    zenodo: dict[str, Any]

    @property
    def version(self) -> str:
        return str(self.manifest["version"])

    def files(self) -> list[str]:
        """The files Zenodo holds for a version: the manifest's, less Kaggle's own, plus MANIFEST.json."""
        return sorted([f for f in self.manifest["files"] if f not in NOT_ON_ZENODO] + ["MANIFEST.json"])

    def data(self, name: str) -> bytes:
        return (self.root / name).read_bytes()


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()  # Zenodo's file checksum; the manifest's sha256 is checked too


def read_package(root: Path) -> Package:
    """The package as built, checked against its own MANIFEST.json byte for byte. Raises Refused."""
    from .dataset import CARD, LICENSE_ID, TITLE
    mpath = root / "MANIFEST.json"
    if not mpath.is_file():
        raise Refused(f"{mpath} is missing; run `mfetl dataset` first")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    problems: list[str] = []
    for name, want in sorted(manifest.get("files", {}).items()):
        p = root / name
        if not p.is_file():
            problems.append(f"{name}: listed in the manifest, missing on disk")
            continue
        data = p.read_bytes()
        if len(data) != want.get("bytes") or hashlib.sha256(data).hexdigest() != want.get("sha256"):
            problems.append(f"{name}: does not match the manifest ({len(data)} bytes)")
    on_disk = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p.name != ".DS_Store"}
    extra = sorted(on_disk - set(manifest.get("files", {})) - {"MANIFEST.json", CARD})
    problems += [f"{name}: on disk, not in the manifest" for name in extra]
    if manifest.get("license") != LICENSE_ID:
        problems.append(f"the manifest's licence is {manifest.get('license')!r}, not {LICENSE_ID}")
    if manifest.get("title") != TITLE:
        problems.append("the manifest's title is not the MoleculeFinder dataset's")
    zj: dict[str, Any] = {}
    if "zenodo.json" in manifest.get("files", {}) and (root / "zenodo.json").is_file():
        zj = json.loads((root / "zenodo.json").read_text(encoding="utf-8"))
        if zj.get("license") != ZENODO_LICENCE:
            problems.append(f"zenodo.json's licence is {zj.get('license')!r}, not {ZENODO_LICENCE}")
        if zj.get("version") != manifest.get("version"):
            problems.append(f"zenodo.json says version {zj.get('version')!r}, the manifest {manifest.get('version')!r}")
        if zj.get("title") != TITLE:
            problems.append("zenodo.json's title is not the MoleculeFinder dataset's")
        if [c.get("name") for c in zj.get("creators") or []] != CREATORS:
            problems.append(f"zenodo.json's creators are not {CREATORS}")
    else:
        problems.append("zenodo.json is not in the package")
    if not re.fullmatch(r"\d{4}\.\d{2}(\.\d+)?", str(manifest.get("version") or "")):
        problems.append(f"version {manifest.get('version')!r} is not YYYY.MM or YYYY.MM.N")
    if problems:
        raise Refused("the package does not match its manifest: " + "; ".join(problems))
    return Package(root, manifest, zj)


def version_key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def deposit_metadata(zj: dict[str, Any]) -> dict[str, Any]:
    """The draft's metadata, from the package's zenodo.json. `doi` stays out: Zenodo reserved this version's DOI
    itself, and a `doi` sent in the metadata would be taken for an external one."""
    keep = ("upload_type", "title", "creators", "description", "version", "publication_date", "access_right",
            "license", "keywords", "language", "related_identifiers", "notes")
    return {k: zj[k] for k in keep if k in zj}


# ── the record on Zenodo (public reads) ───────────────────────────────────────────────────────────────────────────
@dataclass
class Record:
    concept_recid: str
    latest_id: int
    latest_version: str
    versions: dict[str, str]          # version -> its own DOI, as Zenodo lists them


def _licence_id(meta: dict[str, Any]) -> str | None:
    lic = meta.get("license")
    return lic.get("id") if isinstance(lic, dict) else lic


def find_record(c: Client, published: dict[str, Any]) -> Record:
    """MoleculeFinder's record, found by its concept DOI and checked to be it. Raises Refused."""
    from .dataset import TITLE
    m = _ZENODO_DOI.match(published["concept_doi"])
    if not m:
        raise Refused(f"the concept DOI {published['concept_doi']} is not a Zenodo DOI")
    concept = m.group(1)
    latest = c.call("GET", f"/records/{concept}")          # Zenodo answers with the latest version
    meta = latest.get("metadata") or {}
    problems = []
    if str(latest.get("conceptrecid")) != concept or latest.get("conceptdoi") != published["concept_doi"]:
        problems.append(f"record {latest.get('id')} is not under concept {published['concept_doi']}")
    if meta.get("title") != TITLE:
        problems.append(f"record {latest.get('id')} is titled {meta.get('title')!r}")
    if [x.get("name") for x in meta.get("creators") or []] != CREATORS:
        problems.append(f"record {latest.get('id')}'s creators are not {CREATORS}")
    if _licence_id(meta) != ZENODO_LICENCE:
        problems.append(f"record {latest.get('id')}'s licence is {_licence_id(meta)!r}, not CC0")
    if problems:
        raise Refused("the record found is not the MoleculeFinder record: " + "; ".join(problems))
    versions: dict[str, str] = {}
    url = f"/records/{latest['id']}/versions?size=25&sort=version"
    while url:
        page = c.call("GET", url)
        for h in (page.get("hits") or {}).get("hits") or []:
            if str(h.get("conceptrecid")) != concept:
                raise Refused(f"version listing returned record {h.get('id')} from another concept")
            versions[str((h.get("metadata") or {}).get("version"))] = str(h.get("doi"))
        url = (page.get("links") or {}).get("next")
    return Record(concept, int(latest["id"]), str(meta.get("version")), versions)


def check_plan(pkg: Package, rec: Record, published: dict[str, Any], *, resuming: bool = False) -> None:
    """This version is new, newer than the latest, and the repo's record agrees with Zenodo's. Raises Refused."""
    v = pkg.version
    if v in rec.versions:
        raise Refused(f"version {v} already exists on Zenodo ({rec.versions[v]}); nothing to publish")
    if version_key(v) <= version_key(rec.latest_version):
        raise Refused(f"version {v} is not newer than Zenodo's latest, {rec.latest_version}")
    ours = dict(published["versions"])
    if resuming:
        ours.pop(v, None)
    elif v in ours:
        raise Refused(f"dataset_published.yaml already records {v} ({ours[v]}) but Zenodo has no such version and "
                      "no open draft of it; put the file back (git checkout) before publishing")
    if ours != rec.versions:
        raise Refused(f"dataset_published.yaml's versions {sorted(ours)} are not Zenodo's {sorted(rec.versions)}; "
                      "a version was published another way. Record it (`mfetl dataset --version V --doi D`) first")


# ── drafts (the token's calls) ───────────────────────────────────────────────────────────────────────────────────
def open_drafts(c: Client, rec: Record) -> list[dict[str, Any]]:
    """Unpublished drafts under this record's concept."""
    out = []
    for d in c.call("GET", "/deposit/depositions?status=draft&size=100") or []:
        if str(d.get("conceptrecid")) == rec.concept_recid and not d.get("submitted"):
            out.append(d)
    return out


def reserved_doi(draft: dict[str, Any]) -> str | None:
    return ((draft.get("metadata") or {}).get("prereserve_doi") or {}).get("doi")


def new_draft(c: Client, rec: Record, metadata: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Open a new version of the record, set its metadata and reserve its DOI. Returns (draft, DOI)."""
    made = c.call("POST", f"/deposit/depositions/{rec.latest_id}/actions/newversion", ok=(200, 201))
    url = (made.get("links") or {}).get("latest_draft")
    if not url:
        raise Refused("Zenodo opened no draft for the new version")
    did = int(url.rstrip("/").rsplit("/", 1)[-1])
    try:
        draft = c.call("GET", url)
        log.info("zenodo: draft %s opened (new version of record %s)", draft.get("id"), rec.latest_id)
        draft = put_metadata(c, draft, metadata, reserve=True)
        doi = reserved_doi(draft)
        if not doi or doi != f"10.5281/zenodo.{draft.get('id')}":
            raise Refused(f"Zenodo reserved no DOI for draft {draft.get('id')} (got {doi!r})")
    except Exception:
        discard(c, did)        # the draft this call opened never leaves a stray behind
        raise
    return draft, doi


def put_metadata(c: Client, draft: dict[str, Any], metadata: dict[str, Any], *, reserve: bool = False) -> dict:
    body = dict(metadata)
    if reserve:
        body["prereserve_doi"] = True
    return c.call("PUT", f"/deposit/depositions/{draft['id']}", json={"metadata": body},
                  headers={"Content-Type": "application/json"})


def replace_files(c: Client, draft: dict[str, Any], pkg: Package) -> None:
    """The draft's files become exactly the package's: whatever a new version carried over is deleted first."""
    did = draft["id"]
    for f in c.call("GET", f"/deposit/depositions/{did}/files") or []:
        c.call("DELETE", f"/deposit/depositions/{did}/files/{f['id']}", ok=(204, 200))
    bucket = (draft.get("links") or {}).get("bucket")
    if not bucket:
        raise Refused(f"draft {did} has no file bucket")
    for name in pkg.files():
        c.call("PUT", f"{bucket}/{name}", data=pkg.data(name), ok=(200, 201), timeout=UPLOAD_TIMEOUT,
               headers={"Content-Type": "application/octet-stream"})
        log.info("zenodo: uploaded %s (%d bytes)", name, len(pkg.data(name)))


def check_draft(c: Client, did: int, pkg: Package, doi: str, rec: Record) -> list[dict[str, Any]]:
    """Read the draft back and compare it with the package. Returns its file rows; raises Refused."""
    from .dataset import TITLE
    draft = c.call("GET", f"/deposit/depositions/{did}")
    meta = draft.get("metadata") or {}
    zj = pkg.zenodo
    problems = []
    if draft.get("submitted"):
        problems.append("the draft is already published")
    if str(draft.get("conceptrecid")) != rec.concept_recid:
        problems.append(f"the draft is not under concept {rec.concept_recid}")
    if reserved_doi(draft) != doi:
        problems.append(f"the draft's reserved DOI is {reserved_doi(draft)!r}, not {doi}")
    for key, want in (("title", TITLE), ("version", pkg.version), ("publication_date", zj.get("publication_date")),
                      ("upload_type", "dataset"), ("access_right", "open")):
        if meta.get(key) != want:
            problems.append(f"{key} is {meta.get(key)!r}, not {want!r}")
    if _licence_id(meta) != ZENODO_LICENCE:
        problems.append(f"licence is {_licence_id(meta)!r}, not {ZENODO_LICENCE}")
    if [x.get("name") for x in meta.get("creators") or []] != CREATORS:
        problems.append(f"creators are {[x.get('name') for x in meta.get('creators') or []]}")
    files = c.call("GET", f"/deposit/depositions/{did}/files") or []
    have = {f.get("filename"): f for f in files}
    if sorted(have) != pkg.files():
        problems.append(f"files differ from the package: missing {sorted(set(pkg.files()) - set(have))}, "
                        f"extra {sorted(set(have) - set(pkg.files()))}")
    for name in pkg.files():
        f = have.get(name)
        if not f:
            continue
        data = pkg.data(name)
        if int(f.get("filesize", -1)) != len(data) or str(f.get("checksum", "")).removeprefix("md5:") != md5(data):
            problems.append(f"{name}: Zenodo holds {f.get('filesize')} bytes, md5 {f.get('checksum')}")
    if problems:
        raise Refused(f"draft {did} does not match the package: " + "; ".join(problems))
    return files


def discard(c: Client, did: int) -> bool:
    try:
        c.call("DELETE", f"/deposit/depositions/{did}", ok=(201, 204, 200))
        log.info("zenodo: draft %s discarded", did)
        return True
    except Refused as e:
        log.error("zenodo: could not discard draft %s (%s). Discard it with `mfetl zenodo --discard`, or at "
                  "https://zenodo.org/uploads/%s (Delete)", did, e, did)
        return False


# ── the repo's files, kept so a failed run can put them back ─────────────────────────────────────────────────────
class Backup:
    def __init__(self, package_root: Path, published_file: Path):
        self.root, self.pub = package_root, published_file
        self.tmp = Path(tempfile.mkdtemp(prefix="mfetl-zenodo-"))
        shutil.copytree(package_root, self.tmp / "dataset")
        shutil.copy2(published_file, self.tmp / "published.yaml")

    def restore(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.copytree(self.tmp / "dataset", self.root)
        shutil.copy2(self.tmp / "published.yaml", self.pub)
        log.info("zenodo: put back %s and %s as they were", self.root.name, self.pub.name)

    def drop(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


def rebuild_with_doi(pkg: Package, doi: str) -> Package:
    """`mfetl dataset --version V --doi D`: record the DOI and rebuild, then prove only documents moved."""
    from . import dataset
    before = {n: pkg.manifest["files"][n]["sha256"] for n in pkg.manifest["files"]}
    if dataset.run(version=pkg.version, out=pkg.root, doi=doi) != 0:
        raise Refused(f"`mfetl dataset --version {pkg.version} --doi {doi}` refused (its log says why)")
    dataset.write_card(pkg.root)   # the card as `mfetl dataset --card` writes it (tests/test_dataset_card.py)
    new = read_package(pkg.root)
    moved = sorted(n for n, sha in before.items() if new.manifest["files"].get(n, {}).get("sha256") != sha)
    data_moved = [n for n in moved if n not in DOCUMENTS]
    if data_moved or new.manifest["rows"] != pkg.manifest["rows"] or set(new.manifest["files"]) != set(before):
        raise Refused(f"the rebuild with the DOI moved data, not only documents: {data_moved or 'rows or files'}")
    if doi not in (pkg.root / "CITATION.cff").read_text() or doi not in (pkg.root / "zenodo.json").read_text():
        raise Refused(f"the rebuilt package does not cite {doi}")
    log.info("zenodo: package rebuilt with %s; documents moved: %s; data files unchanged", doi, ", ".join(moved))
    return new


# ── the command ─────────────────────────────────────────────────────────────────────────────────────────────────
def _show(pkg: Package, rec: Record, metadata: dict[str, Any]) -> None:
    log.info("zenodo: record %s (concept %s), latest version %s; versions on Zenodo: %s", rec.latest_id,
             rec.concept_recid, rec.latest_version, ", ".join(f"{v} {d}" for v, d in rec.versions.items()))
    log.info("zenodo: would publish version %s, dated %s, licence %s, creators %s", pkg.version,
             metadata.get("publication_date"), metadata.get("license"), [x["name"] for x in metadata["creators"]])
    for name in pkg.files():
        data = pkg.data(name)
        log.info("zenodo:   %-24s %9d bytes  sha256 %s  md5 %s", name, len(data),
                 hashlib.sha256(data).hexdigest()[:16], md5(data))


def run(*, dry_run: bool = False, draft_only: bool = False, do_discard: bool = False, check: bool = False,
        out: Path | None = None, client: Client | None = None) -> int:
    from . import dataset
    root = out or dataset.OUT
    try:
        pub = dataset.published()
        if check:
            return verify_published(client or Client(None), read_package(root), pub)
        pkg = read_package(root)
        reader = client or Client(None)          # the public reads need no token
        rec = find_record(reader, pub)
        meta = deposit_metadata(pkg.zenodo)
        if dry_run:
            check_plan(pkg, rec, pub, resuming=pkg.version in pub["versions"])
            _show(pkg, rec, meta)
            log.info("zenodo: DRY RUN passed: every check holds; nothing was created on Zenodo")
            return 0
        c = client or Client(token())
        drafts = open_drafts(c, rec)
        if do_discard:
            return _discard_ours(c, drafts, pkg, pub)
        return _publish(c, rec, pkg, pub, drafts, root, draft_only=draft_only)
    except (Refused, dataset.Unpublished) as e:
        log.error("zenodo: REFUSED, nothing published: %s", e)
        return 1


def _discard_ours(c: Client, drafts: list[dict], pkg: Package, pub: dict[str, Any]) -> int:
    if not drafts:
        log.info("zenodo: no open draft under this record")
        return 0
    rc = 0
    for d in drafts:
        if not discard(c, d["id"]):
            rc = 1
    if pkg.version in pub["versions"] and pub["versions"][pkg.version] in {reserved_doi(d) for d in drafts}:
        log.info("zenodo: dataset_published.yaml and data/dataset/ still name the discarded draft's DOI: put them "
                 "back with `git checkout -- moleculefinder_etl/sources/seeds/dataset_published.yaml data/dataset`")
    return rc


def _publish(c: Client, rec: Record, pkg: Package, pub: dict[str, Any], drafts: list[dict], root: Path, *,
             draft_only: bool) -> int:
    from . import dataset
    v = pkg.version
    resume = None
    if drafts:
        mine = [d for d in drafts if (d.get("metadata") or {}).get("version") == v
                and reserved_doi(d) and pub["versions"].get(v) == reserved_doi(d)]
        if len(drafts) != 1 or not mine:
            names = ", ".join(f"{d['id']} (version {(d.get('metadata') or {}).get('version')!r})" for d in drafts)
            raise Refused(f"an open draft already exists under this record: {names}. Discard it with "
                          "`mfetl zenodo --discard` (or at https://zenodo.org/uploads/<id>, Delete) and run again")
        resume = mine[0]
    check_plan(pkg, rec, pub, resuming=resume is not None)
    _show(pkg, rec, deposit_metadata(pkg.zenodo))

    if resume is not None:
        draft, doi = resume, reserved_doi(resume)
        log.info("zenodo: resuming draft %s (%s), left by --draft-only", draft["id"], doi)
        backup = None
    else:
        backup = Backup(root, dataset.PUBLISHED)
        draft = None
    try:
        if resume is None:
            draft, doi = new_draft(c, rec, deposit_metadata(pkg.zenodo))
            log.info("zenodo: draft %s reserved %s", draft["id"], doi)
            pkg = rebuild_with_doi(pkg, doi)
            put_metadata(c, draft, deposit_metadata(pkg.zenodo))
            replace_files(c, draft, pkg)
        else:
            put_metadata(c, draft, deposit_metadata(pkg.zenodo))
        files = check_draft(c, draft["id"], pkg, doi, rec)
        log.info("zenodo: draft %s checked: %d files match the package, metadata as zenodo.json says",
                 draft["id"], len(files))
        if draft_only:
            log.info("zenodo: DRAFT ONLY: stopped before publishing. Draft https://zenodo.org/uploads/%s (%s). "
                     "Publish it with `mfetl zenodo`; discard it with `mfetl zenodo --discard`", draft["id"], doi)
            if backup:
                backup.drop()
            return 0
        done = c.call("POST", f"/deposit/depositions/{draft['id']}/actions/publish", ok=(200, 202))
    except Exception as e:  # noqa: BLE001  whatever broke, the draft goes and the files come back
        msg = c.redact(str(e))
        log.error("zenodo: REFUSED, nothing published: %s", msg)
        if draft is not None and resume is None:
            discard(c, draft["id"])
        if backup:
            backup.restore()
            backup.drop()
        return 1
    if backup:
        backup.drop()
    if done.get("doi") != doi or done.get("conceptdoi") != pub["concept_doi"] or not done.get("submitted"):
        log.error("zenodo: PUBLISHED, but Zenodo's reply is not what was reserved: doi %r, concept %r. Check "
                  "https://zenodo.org/records/%s by hand", done.get("doi"), done.get("conceptdoi"), draft["id"])
        return 1
    log.info("zenodo: PUBLISHED version %s: https://doi.org/%s (record https://zenodo.org/records/%s); every "
             "version: https://doi.org/%s", v, doi, draft["id"], pub["concept_doi"])
    log.info("zenodo: commit moleculefinder_etl/sources/seeds/dataset_published.yaml and data/dataset/")
    return 0


# ── after a publish: the public record, read only ────────────────────────────────────────────────────────────────
def verify_published(c: Client, pkg: Package, pub: dict[str, Any], *, doi_wait: int = 0) -> int:
    """The version is Zenodo's latest, the earlier ones still answer, every file downloads and matches the
    package, and the concept DOI resolves to this version's record."""
    rec = find_record(c, pub)
    v = pkg.version
    problems = []
    if rec.latest_version != v:
        problems.append(f"Zenodo's latest is {rec.latest_version}, not {v}")
    if rec.versions != pub["versions"]:
        problems.append(f"Zenodo lists {rec.versions}, the repo records {pub['versions']}")
    for ver, doi in pub["versions"].items():
        rid = _ZENODO_DOI.match(doi).group(1)
        r = c.call("GET", f"/records/{rid}")
        if (r.get("metadata") or {}).get("version") != ver:
            problems.append(f"record {rid} is not version {ver}")
    page = c.call("GET", f"/records/{rec.latest_id}")
    listed = {f["key"]: f for f in page.get("files") or []}
    if sorted(listed) != pkg.files():
        problems.append(f"the public record lists {sorted(listed)}")
    for name in pkg.files():
        f = listed.get(name)
        if not f:
            continue
        got = c.call("GET", f"https://zenodo.org/records/{rec.latest_id}/files/{name}?download=1",
                     timeout=UPLOAD_TIMEOUT, raw=True)
        if hashlib.sha256(got).hexdigest() != hashlib.sha256(pkg.data(name)).hexdigest():
            problems.append(f"{name}: the download does not match the package")
    target = None
    for attempt in range(max(1, doi_wait // 30 + 1)):
        import requests
        try:
            r = requests.get(f"https://doi.org/{pub['concept_doi']}", timeout=TIMEOUT, allow_redirects=True)
            target = r.url
        except requests.RequestException as e:
            target = f"error {type(e).__name__}"
        if target and target.rstrip("/").endswith(f"/records/{rec.latest_id}"):
            break
        if attempt < doi_wait // 30:
            time.sleep(30)
    if not (target or "").rstrip("/").endswith(f"/records/{rec.latest_id}"):
        problems.append(f"https://doi.org/{pub['concept_doi']} leads to {target}, not record {rec.latest_id}")
    if problems:
        for p in problems:
            log.error("zenodo: check: %s", p)
        return 1
    log.info("zenodo: CHECKED: version %s is the latest (record %s); %d earlier version(s) answer; %d files "
             "download and match; https://doi.org/%s leads to it", v, rec.latest_id, len(pub["versions"]) - 1,
             len(pkg.files()), pub["concept_doi"])
    return 0
