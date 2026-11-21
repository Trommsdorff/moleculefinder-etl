"""The dataset's two mirrors follow Zenodo (`mfetl mirrors`, 2026-11-20).

Zenodo is the dataset's home; Hugging Face and Kaggle each hold a copy. Garrett's rule (2026-11-06): he does not
re-upload datasets by hand. This brings each mirror to the version Zenodo's latest public record holds.

    mfetl mirrors --dry-run    public reads only (no login needed): every check, what each mirror holds, nothing written
    mfetl mirrors              bring each mirror to Zenodo's latest version, then read it back
    mfetl mirrors --check      read only: each mirror holds this package, file for file
    mfetl mirrors --whoami     read only: each login works (prints who it is, never the token)

WHAT IT DOES, in order. It refuses rather than guesses; a refusal publishes nothing to the mirror concerned.
  1. The package in data/dataset/ matches its MANIFEST.json byte for byte, says CC0, and names its version.
  2. Zenodo's latest public record is MoleculeFinder's, is CC0, holds exactly this version (a mirror never gets
     ahead of Zenodo), lists the repo's versions, and its files have the package's sizes and md5s.
  3. The mirror's id is the one in sources/seeds/dataset_published.yaml (the Hugging Face repo, the Kaggle
     dataset), and the package's own documents link it.
  4. The mirror's current version is read. Holding this version already (the same files): it says so, exit 0.
     Holding it with other files, or a newer one, or one it cannot name: refused.
  5. Hugging Face: ONE commit, named for the version, writes the package's files and the card (huggingface/
     README.md, which is the repo's README.md) and removes any file the package does not have.
     Kaggle: the files are uploaded and ONE new dataset version is made with the package's Kaggle metadata
     (dataset-metadata.json) and a version note naming the version and its Zenodo DOI.
  6. The mirror is read back: the file list, sizes and, where the mirror gives them, checksums (Hugging Face's
     git blob ids; Kaggle's bytes, downloaded) equal the package; the licence is CC0; the concept DOI is named.
One mirror failing does not stop the other; the summary and the exit code name each.

LOGINS. Hugging Face: HF_TOKEN in the ETL's .env, else the `hf auth login` file (~/.cache/huggingface/token, a
plain file a launchd job reads like any other). Kaggle: KAGGLE_API_TOKEN (Kaggle's new API token), or
KAGGLE_USERNAME with KAGGLE_KEY (the legacy key), in .env. Read with python-dotenv, sent only in the
Authorization header, redacted from every message, never printed or logged, and taken out of the environment
for every other stage (cli.py).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import dataset, zenodo
from .config import REPO_ROOT

log = logging.getLogger("mfetl.mirrors")

ENV_FILE = REPO_ROOT / ".env"
HF = "https://huggingface.co"
KG_API = "https://api.kaggle.com/v1"
KG_WWW = "https://www.kaggle.com/api/v1"
HF_KEYS = ("HF_TOKEN",)
KAGGLE_KEYS = ("KAGGLE_API_TOKEN", "KAGGLE_USERNAME", "KAGGLE_KEY")
SECRET_KEYS = HF_KEYS + KAGGLE_KEYS
HF_LICENCE = "cc0-1.0"
KAGGLE_LICENCE = "CC0: Public Domain"
MIRRORS = ("huggingface", "kaggle")
HF_OWN = frozenset({".gitattributes"})          # the Hub's own file, never ours to touch
TIMEOUT = 60
UPLOAD_TIMEOUT = 600
_VERSION = re.compile(r"^(\d{4}\.\d{2}(?:\.\d+)?)(?=[:\s(]|$)")

Refused = zenodo.Refused


# ── the logins ──────────────────────────────────────────────────────────────────────────────────────────────────
def _env_values(env_file: Path) -> dict[str, str]:
    from dotenv import dotenv_values
    if not env_file.is_file():
        return {}
    return {k: (v or "").strip() for k, v in dotenv_values(env_file).items() if k in SECRET_KEYS}


def hf_login_file() -> Path:
    home = os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")
    return Path(home) / "token"


def hf_token(env_file: Path = ENV_FILE, login_file: Path | None = None) -> tuple[str, str]:
    """(token, where it came from): HF_TOKEN in .env, else the `hf auth login` file. Raises Refused."""
    value = _env_values(env_file).get("HF_TOKEN", "")
    if value:
        return value, f"HF_TOKEN in {env_file.name}"
    path = login_file or hf_login_file()
    try:
        value = path.read_text().strip()
    except OSError:
        value = ""
    if value:
        return value, f"the Hugging Face login file {path}"
    raise Refused(f"no Hugging Face login: {env_file} has no HF_TOKEN and {path} is empty or missing")


def kaggle_login(env_file: Path = ENV_FILE) -> tuple[dict[str, str], tuple[str, str] | None, list[str], str]:
    """(headers, basic auth, secrets, where it came from) for api.kaggle.com. Raises Refused."""
    v = _env_values(env_file)
    if v.get("KAGGLE_API_TOKEN"):
        t = v["KAGGLE_API_TOKEN"]
        return {"Authorization": f"Bearer {t}"}, None, [t], f"KAGGLE_API_TOKEN in {env_file.name}"
    if v.get("KAGGLE_USERNAME") and v.get("KAGGLE_KEY"):
        u, k = v["KAGGLE_USERNAME"], v["KAGGLE_KEY"]
        both = base64.b64encode(f"{u}:{k}".encode()).decode()
        return {}, (u, k), [k, both], f"KAGGLE_USERNAME and KAGGLE_KEY in {env_file.name}"
    raise Refused(f"no Kaggle login: {env_file} has neither KAGGLE_API_TOKEN nor KAGGLE_USERNAME with KAGGLE_KEY")


class Http:
    """One service's HTTP calls. Every message that could carry a secret is redacted first."""

    def __init__(self, secrets: list[str] | None = None, headers: dict[str, str] | None = None,
                 auth: tuple[str, str] | None = None, session: Any = None):
        import requests
        self._secrets = [s for s in (secrets or []) if s]
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = "moleculefinder-etl (dataset mirrors)"
        self.s.headers.update(headers or {})
        self.auth = auth

    def redact(self, text: str) -> str:
        for s in self._secrets:
            text = text.replace(s, "[secret]")
        return text

    def call(self, method: str, url: str, *, ok: tuple[int, ...] = (200,), timeout: int = TIMEOUT, raw: bool = False,
             **kw) -> Any:
        if self.auth:
            kw.setdefault("auth", self.auth)
        try:
            r = self.s.request(method, url, timeout=timeout, **kw)
        except Exception as e:  # noqa: BLE001  any network error: its text can carry a header, so redact it
            raise Refused(self.redact(f"{method} {url}: {type(e).__name__}: {e}")) from None
        if r.status_code not in ok:
            raise Refused(self.redact(f"{method} {url}: HTTP {r.status_code}: {(r.text or '')[:400]}"))
        if raw:
            return r.content
        if r.status_code == 204 or not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return r.content


# ── what a mirror should hold ───────────────────────────────────────────────────────────────────────────────────
def git_blob_oid(data: bytes) -> str:
    """Hugging Face's id for a plain file: git's blob hash."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # a git object id, not security


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hf_wanted(pkg: zenodo.Package) -> dict[str, bytes]:
    """The Hugging Face repo's files: the package's, with the card as README.md, plus Kaggle's metadata file
    (the repo has held it since the first upload)."""
    files = {n: pkg.data(n) for n in pkg.files()}
    files["README.md"] = (pkg.root / dataset.CARD).read_bytes()
    files["dataset-metadata.json"] = pkg.data("dataset-metadata.json")
    return files


def kaggle_wanted(pkg: zenodo.Package) -> dict[str, bytes]:
    """Kaggle's files: the package's, the same 17 Zenodo holds. Its metadata file is not a file of the dataset."""
    return {n: pkg.data(n) for n in pkg.files()}


def kaggle_notes(pkg: zenodo.Package, doi: str, concept: str) -> str:
    return (f"{pkg.version}: the same files as Zenodo version {pkg.version}, https://doi.org/{doi}. "
            f"All versions: https://doi.org/{concept}")


def parse_version(notes: str | None) -> str | None:
    m = _VERSION.match((notes or "").strip())
    return m.group(1) if m else None


# ── the checks every mirror shares ──────────────────────────────────────────────────────────────────────────────
def check_zenodo(c: zenodo.Client, pkg: zenodo.Package, pub: dict[str, Any]) -> zenodo.Record:
    """Zenodo's latest public record holds exactly this package. Raises Refused."""
    rec = zenodo.find_record(c, pub)          # MoleculeFinder's record, titled, created by, CC0 (it checks)
    v = pkg.version
    problems = []
    if rec.latest_version != v:
        problems.append(f"Zenodo's latest version is {rec.latest_version}, this package is {v}: a mirror never "
                        "gets ahead of Zenodo (publish it there first, `mfetl zenodo`)")
    if rec.versions != pub["versions"]:
        problems.append(f"Zenodo lists versions {sorted(rec.versions)}, the repo records {sorted(pub['versions'])}")
    doi = pub["versions"].get(v)
    if not doi or rec.versions.get(v) != doi:
        problems.append(f"version {v}'s DOI is {rec.versions.get(v)!r} on Zenodo, {doi!r} in the repo")
    if problems:
        raise Refused("; ".join(problems))
    page = c.call("GET", f"/records/{rec.latest_id}")
    listed = {f.get("key"): f for f in page.get("files") or []}
    if sorted(listed) != pkg.files():
        problems.append(f"Zenodo's record lists {sorted(listed)}, not the package's {pkg.files()}")
    for name in pkg.files():
        f = listed.get(name)
        data = pkg.data(name)
        if f and (int(f.get("size", -1)) != len(data) or str(f.get("checksum", "")).removeprefix("md5:") != zenodo.md5(data)):
            problems.append(f"{name}: Zenodo's copy is {f.get('size')} bytes, md5 {f.get('checksum')}: not the package's")
    if problems:
        raise Refused("; ".join(problems))
    return rec


def check_ids(pkg: zenodo.Package, pub: dict[str, Any], which: str) -> str:
    """The mirror's id is the published record's, and the package's own documents link it. Returns the id."""
    if which == "huggingface":
        ident = pub.get("huggingface") or ""
        if not ident:
            raise Refused("dataset_published.yaml has no huggingface id")
        card = (pkg.root / dataset.CARD).read_text(encoding="utf-8")
        if f"{HF}/datasets/{ident}" not in card:
            raise Refused(f"the card does not link {ident}; run `mfetl dataset --card`")
        if f"| **Version** | {pkg.version} |" not in card or pub["versions"][pkg.version] not in card:
            raise Refused(f"the card does not name version {pkg.version} and its DOI; run `mfetl dataset --card`")
        return ident
    ident = pub.get("kaggle") or ""
    meta = json.loads(pkg.data("dataset-metadata.json"))
    if meta.get("id") != ident:
        raise Refused(f"the package's Kaggle metadata id is {meta.get('id')!r}, dataset_published.yaml says {ident!r}")
    if [x.get("name") for x in meta.get("licenses") or []] != [dataset.LICENSE_ID]:
        raise Refused(f"the Kaggle metadata's licence is {meta.get('licenses')!r}, not {dataset.LICENSE_ID}")
    return ident


# ── what a mirror holds ─────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Held:
    """A mirror as it stands: the version it names, its files, and what is wrong with it against a package."""
    version: str | None
    files: dict[str, tuple[int, str]] = field(default_factory=dict)   # name -> (size, id or sha256)
    licence: str | None = None
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def hf_read(h: Http, repo: str) -> Held:
    info = h.call("GET", f"{HF}/api/datasets/{repo}?blobs=true")
    if info.get("id") != repo:
        raise Refused(f"Hugging Face answers for {info.get('id')!r}, not {repo}")
    files = {s["rfilename"]: (int(s["size"]), str(s.get("blobId"))) for s in info.get("siblings") or []
             if s["rfilename"] not in HF_OWN}
    version = None
    if "MANIFEST.json" in files:
        try:
            version = json.loads(h.call("GET", f"{HF}/datasets/{repo}/resolve/main/MANIFEST.json", raw=True)).get("version")
        except (ValueError, AttributeError):
            version = None
    lic = (info.get("cardData") or {}).get("license")
    return Held(version, files, lic, extra={"sha": info.get("sha")})


def hf_diff(held: Held, wanted: dict[str, bytes]) -> list[str]:
    out = []
    for name in sorted(set(wanted) - set(held.files)):
        out.append(f"{name}: missing")
    for name in sorted(set(held.files) - set(wanted)):
        out.append(f"{name}: not in the package")
    for name, data in sorted(wanted.items()):
        got = held.files.get(name)
        if got and (got[0] != len(data) or got[1] != git_blob_oid(data)):
            out.append(f"{name}: differs ({got[0]} bytes against {len(data)})")
    return out


def kaggle_read(h: Http, ref: str, *, with_bytes: bool = False) -> Held:
    view = h.call("GET", f"{KG_WWW}/datasets/view/{ref}")
    if view.get("ref") != ref:
        raise Refused(f"Kaggle answers for {view.get('ref')!r}, not {ref}")
    versions = view.get("versions") or []
    if not versions:
        raise Refused(f"Kaggle lists no versions of {ref}")
    latest = max(versions, key=lambda x: int(x.get("versionNumber") or 0))
    number = int(latest.get("versionNumber") or 0)
    held = Held(parse_version(latest.get("versionNotes")), {}, view.get("licenseName"),
                note=str(latest.get("versionNotes") or ""),
                extra={"number": number, "status": latest.get("status"), "subtitle": view.get("subtitle"),
                       "description": view.get("description") or ""})
    token = None
    while True:
        q = f"?datasetVersionNumber={number}" + (f"&pageToken={token}" if token else "")
        page = h.call("GET", f"{KG_WWW}/datasets/list/{ref}{q}")
        for f in page.get("datasetFiles") or []:
            held.files[f["name"]] = (int(f.get("totalBytes") or 0), "")
        token = page.get("nextPageToken")
        if not token:
            break
    if with_bytes:
        for name in list(held.files):
            data = h.call("GET", f"{KG_WWW}/datasets/download/{ref}/{name}?datasetVersionNumber={number}",
                          timeout=UPLOAD_TIMEOUT, raw=True)
            held.files[name] = (len(data), sha256(data))
    return held


def kaggle_diff(held: Held, wanted: dict[str, bytes]) -> list[str]:
    out = []
    for name in sorted(set(wanted) - set(held.files)):
        out.append(f"{name}: missing")
    for name in sorted(set(held.files) - set(wanted)):
        out.append(f"{name}: not in the package")
    for name, data in sorted(wanted.items()):
        got = held.files.get(name)
        if got and (got[0] != len(data) or (got[1] and got[1] != sha256(data))):
            out.append(f"{name}: differs ({got[0]} bytes against {len(data)})")
    return out


# ── what a mirror does next ─────────────────────────────────────────────────────────────────────────────────────
def decide(held: Held, diffs: list[str], pkg: zenodo.Package, who: str) -> str:
    """'hold' (it has this version), or 'publish' (it has an older one). Raises Refused otherwise."""
    if held.version is None:
        raise Refused(f"cannot tell which version {who} holds (no version in its record); not guessing")
    if zenodo.version_key(held.version) > zenodo.version_key(pkg.version):
        raise Refused(f"{who} holds version {held.version}, newer than this package's {pkg.version}")
    if held.version == pkg.version:
        if diffs:
            raise Refused(f"{who} holds version {pkg.version} but its files differ from the package: "
                          + "; ".join(diffs[:6]))
        return "hold"
    return "publish"


# ── Hugging Face ────────────────────────────────────────────────────────────────────────────────────────────────
def hf_commit(h: Http, repo: str, pkg: zenodo.Package, doi: str, held: Held, wanted: dict[str, bytes]) -> str:
    """ONE commit, named for the version, with every changed file and every removal. Returns the commit id."""
    concept = dataset.published()["concept_doi"]
    ops: list[dict[str, Any]] = [{"key": "header", "value": {
        "summary": f"MoleculeFinder dataset {pkg.version} (Zenodo {doi})",
        "description": f"The same files as Zenodo version {pkg.version}, https://doi.org/{doi}. "
                       f"All versions: https://doi.org/{concept}"}}]
    for name, data in sorted(wanted.items()):
        if held.files.get(name, (0, ""))[1] == git_blob_oid(data):
            continue
        ops.append({"key": "file", "value": {"path": name, "encoding": "base64",
                                             "content": base64.b64encode(data).decode()}})
    for name in sorted(set(held.files) - set(wanted)):
        ops.append({"key": "deletedFile", "value": {"path": name}})
    body = ("\n".join(json.dumps(o) for o in ops) + "\n").encode()
    done = h.call("POST", f"{HF}/api/datasets/{repo}/commit/main", data=body, ok=(200, 201),
                  timeout=UPLOAD_TIMEOUT, headers={"Content-Type": "application/x-ndjson"})
    return str((done or {}).get("commitOid") or "")


def hf_verify(reader: Http, repo: str, pkg: zenodo.Package, wanted: dict[str, bytes], concept: str,
              commit: str | None = None) -> None:
    held = hf_read(reader, repo)
    problems = hf_diff(held, wanted)
    if held.version != pkg.version:
        problems.append(f"MANIFEST.json says version {held.version!r}")
    if held.licence != HF_LICENCE:
        problems.append(f"licence is {held.licence!r}, not {HF_LICENCE}")
    if commit and held.extra.get("sha") != commit:
        problems.append(f"the repo's head is {held.extra.get('sha')}, not the commit {commit}")
    card = wanted["README.md"].decode("utf-8")
    if concept not in card:
        problems.append("the card does not name the concept DOI")
    if problems:
        raise Refused("read back from Hugging Face, it does not match the package: " + "; ".join(problems))


# ── Kaggle ──────────────────────────────────────────────────────────────────────────────────────────────────────
def kaggle_publish(w: Http, up: Http, ref: str, pkg: zenodo.Package, doi: str, concept: str,
                   wanted: dict[str, bytes]) -> None:
    """Upload every file, then ONE new dataset version with the package's metadata and a version note."""
    meta = json.loads(pkg.data("dataset-metadata.json"))
    resources = {r.get("path"): r for r in meta.get("resources") or []}
    entries = []
    for name, data in sorted(wanted.items()):
        start = w.call("POST", f"{KG_API}/blobs.BlobApiService/StartBlobUpload",
                       json={"type": "DATASET", "name": name, "contentLength": len(data),
                             "lastModifiedEpochSeconds": int(time.time())})
        if not start or not start.get("token") or not start.get("createUrl"):
            raise Refused(f"Kaggle gave no upload for {name}")
        up.call("PUT", start["createUrl"], data=data, ok=(200, 201), timeout=UPLOAD_TIMEOUT)
        entry: dict[str, Any] = {"token": start["token"]}
        res = resources.get(name)
        if res:
            if res.get("description"):
                entry["description"] = res["description"]
            fields = (res.get("schema") or {}).get("fields") or []
            if fields:
                entry["columns"] = [{k: f[k] for k in ("name", "type", "description") if f.get(k)} for f in fields]
        entries.append(entry)
        log.info("mirrors: kaggle: uploaded %s (%d bytes)", name, len(data))
    owner, slug = ref.split("/")
    body = {"versionNotes": kaggle_notes(pkg, doi, concept), "files": entries, "deleteOldVersions": False,
            "subtitle": meta.get("subtitle"), "description": meta.get("description"),
            "categoryIds": meta.get("keywords") or []}
    done = w.call("POST", f"{KG_API}/datasets.DatasetApiService/CreateDatasetVersion",
                  json={"ownerSlug": owner, "datasetSlug": slug, "body": {k: v for k, v in body.items() if v is not None}})
    if (done or {}).get("error"):
        raise Refused(f"Kaggle refused the new version: {done['error']}")


def kaggle_wait(reader: Http, ref: str, number: int, *, tries: int = 60, pause: float = 10.0,
                sleep=time.sleep) -> Held:
    """Wait for version number+1 to be Ready (Kaggle processes it after the call returns)."""
    held = None
    for i in range(tries):
        held = kaggle_read(reader, ref)
        if held.extra["number"] > number and str(held.extra["status"]).lower() == "ready":
            return held
        if i < tries - 1:
            sleep(pause)
    raise Refused(f"Kaggle's new version of {ref} was not Ready after {tries * pause:.0f} s (version "
                  f"{held.extra['number'] if held else '?'}, status {held.extra['status'] if held else '?'})")


def kaggle_verify(reader: Http, ref: str, pkg: zenodo.Package, wanted: dict[str, bytes], concept: str) -> None:
    held = kaggle_read(reader, ref, with_bytes=True)
    problems = kaggle_diff(held, wanted)
    if held.version != pkg.version:
        problems.append(f"the latest version's note names {held.version!r}")
    if held.licence != KAGGLE_LICENCE:
        problems.append(f"licence is {held.licence!r}, not {KAGGLE_LICENCE!r}")
    meta = json.loads(pkg.data("dataset-metadata.json"))
    if held.extra.get("subtitle") != meta.get("subtitle"):
        problems.append(f"subtitle is {held.extra.get('subtitle')!r}")
    if concept not in held.extra.get("description", ""):
        problems.append("the description does not name the concept DOI")
    if problems:
        raise Refused("read back from Kaggle, it does not match the package: " + "; ".join(problems))


# ── the command ─────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Outcome:
    mirror: str
    status: str           # PUBLISHED, HOLDS, WOULD PUBLISH, CHECKED, LOGIN OK, REFUSED
    text: str
    ok: bool = True


def _link(which: str, pub: dict[str, Any]) -> str:
    return f"{HF}/datasets/{pub['huggingface']}" if which == "huggingface" else f"https://www.kaggle.com/datasets/{pub['kaggle']}"


def _one(which: str, *, pkg: zenodo.Package, pub: dict[str, Any], mode: str, env_file: Path, session: Any,
         login_file: Path | None, sleep) -> Outcome:
    v, doi, concept = pkg.version, pub["versions"][pkg.version], pub["concept_doi"]
    ident = check_ids(pkg, pub, which)
    reader = Http(session=session)                              # public reads carry no login
    link = _link(which, pub)
    if which == "huggingface":
        wanted = hf_wanted(pkg)
        if mode == "whoami":
            tok, where = hf_token(env_file, login_file)
            who = Http([tok], {"Authorization": f"Bearer {tok}"}, session=session).call("GET", f"{HF}/api/whoami-v2")
            at = (who.get("auth") or {}).get("accessToken") or {}
            if str(at.get("role")) not in ("write", "admin") and not at.get("fineGrained"):
                raise Refused(f"the Hugging Face login ({where}) is a {at.get('role')!r} token, not a write token")
            return Outcome(which, "LOGIN OK", f"{who.get('name')} ({where}; token role {at.get('role')})")
        held = hf_read(reader, ident)
        diffs = hf_diff(held, wanted)
        if mode == "check":
            if held.version != v or diffs:
                raise Refused(f"holds {held.version}; " + ("; ".join(diffs[:6]) if diffs else "version differs"))
            hf_verify(reader, ident, pkg, wanted, concept)
            return Outcome(which, "CHECKED", f"{len(wanted)} files, version {v}, CC0, {link}")
        verdict = decide(held, diffs, pkg, "Hugging Face")
        if verdict == "hold":
            hf_verify(reader, ident, pkg, wanted, concept)
            return Outcome(which, "HOLDS", f"Hugging Face already holds {v}, file for file; nothing to do. {link}")
        changed = [n for n in sorted(wanted) if held.files.get(n, (0, ""))[1] != git_blob_oid(wanted[n])]
        gone = sorted(set(held.files) - set(wanted))
        plan = f"from {held.version} to {v}: write {len(changed)} files, remove {len(gone)}"
        if mode == "dry":
            return Outcome(which, "WOULD PUBLISH", plan)
        tok, where = hf_token(env_file, login_file)
        w = Http([tok], {"Authorization": f"Bearer {tok}"}, session=session)
        commit = hf_commit(w, ident, pkg, doi, held, wanted)
        hf_verify(reader, ident, pkg, wanted, concept, commit or None)
        return Outcome(which, "PUBLISHED", f"{plan}; commit {commit[:12]}; read back: {len(wanted)} files match. {link}")
    wanted = kaggle_wanted(pkg)
    if mode == "whoami":
        headers, auth, secrets, where = kaggle_login(env_file)
        w = Http(secrets, headers, auth, session=session)
        owner, slug = ident.split("/")
        st = w.call("POST", f"{KG_API}/datasets.DatasetApiService/GetDatasetStatus",
                    json={"ownerSlug": owner, "datasetSlug": slug})
        return Outcome(which, "LOGIN OK", f"{where}; Kaggle answers for {ident}: status {(st or {}).get('status')}")
    held = kaggle_read(reader, ident, with_bytes=True)
    diffs = kaggle_diff(held, wanted)
    if mode == "check":
        if held.version != v or diffs:
            raise Refused(f"holds {held.version}; " + ("; ".join(diffs[:6]) if diffs else "version differs"))
        kaggle_verify(reader, ident, pkg, wanted, concept)
        return Outcome(which, "CHECKED", f"{len(wanted)} files, version {v}, CC0, {link}")
    verdict = decide(held, diffs, pkg, "Kaggle")
    if verdict == "hold":
        kaggle_verify(reader, ident, pkg, wanted, concept)
        return Outcome(which, "HOLDS", f"Kaggle already holds {v}, file for file; nothing to do. {link}")
    plan = f"from {held.version} (Kaggle version {held.extra['number']}) to {v}: upload {len(wanted)} files, one new version"
    if mode == "dry":
        return Outcome(which, "WOULD PUBLISH", plan)
    headers, auth, secrets, where = kaggle_login(env_file)
    w = Http(secrets, headers, auth, session=session)
    up = Http(secrets, session=session)                         # the upload URL gets no Authorization header
    kaggle_publish(w, up, ident, pkg, doi, concept, wanted)
    new = kaggle_wait(reader, ident, held.extra["number"], sleep=sleep)
    kaggle_verify(reader, ident, pkg, wanted, concept)
    return Outcome(which, "PUBLISHED", f"{plan}; now Kaggle version {new.extra['number']}; read back: "
                                       f"{len(wanted)} files match byte for byte. {link}")


def _login_notes(env_file: Path, login_file: Path | None) -> list[str]:
    notes = []
    for name, fn in (("huggingface", lambda: hf_token(env_file, login_file)[1]),
                     ("kaggle", lambda: kaggle_login(env_file)[3])):
        try:
            notes.append(f"{name}: login found ({fn()})")
        except Refused as e:
            notes.append(f"{name}: NO LOGIN ({e})")
    return notes


def run(*, dry_run: bool = False, check: bool = False, whoami: bool = False, only: str | None = None,
        out: Path | None = None, env_file: Path = ENV_FILE, login_file: Path | None = None, session: Any = None,
        wait_for_zenodo: int = 0, sleep=time.sleep) -> int:
    """`mfetl mirrors`. Exit 0 when every mirror was brought to, or already holds, Zenodo's latest version."""
    mode = "whoami" if whoami else "check" if check else "dry" if dry_run else "publish"
    root = out or dataset.OUT
    try:
        pub = dataset.published()
        pkg = zenodo.read_package(root)
        zc = zenodo.Client(None, session=session)
        for attempt in range(max(1, wait_for_zenodo)):          # right after `mfetl zenodo`, the record may lag
            try:
                rec = check_zenodo(zc, pkg, pub)
                break
            except Refused:
                if attempt >= wait_for_zenodo - 1:
                    raise
                sleep(15)
        log.info("mirrors: package %s matches its manifest; Zenodo's latest is %s (record %s, %s), CC0",
                 pkg.version, rec.latest_version, rec.latest_id, pub["versions"][pkg.version])
    except (Refused, dataset.Unpublished) as e:
        log.error("mirrors: REFUSED, nothing published to either mirror: %s", e)
        return 1
    if mode in ("dry", "publish"):
        for line in _login_notes(env_file, login_file):
            log.info("mirrors: %s", line)
    results: list[Outcome] = []
    for which in MIRRORS:
        if only and which != only:
            continue
        try:
            res = _one(which, pkg=pkg, pub=pub, mode=mode, env_file=env_file, session=session,
                       login_file=login_file, sleep=sleep)
        except Exception as e:  # noqa: BLE001  one mirror failing never stops the other; the text is redacted below
            res = Outcome(which, "REFUSED" if isinstance(e, Refused) else "FAILED", _scrub(str(e), env_file), ok=False)
        results.append(res)
        (log.info if res.ok else log.error)("mirrors: %s: %s: %s", res.mirror, res.status, res.text)
    bad = [r for r in results if not r.ok]
    log.info("mirrors: SUMMARY %s", "; ".join(f"{r.mirror} {r.status}" for r in results))
    if bad:
        log.error("mirrors: %d of %d mirror(s) need a look: %s", len(bad), len(results), ", ".join(r.mirror for r in bad))
        return 1
    return 0


def _scrub(text: str, env_file: Path) -> str:
    """Belt and braces: no login value ever survives into a summary line."""
    secrets = [v for v in _env_values(env_file).values() if len(v) >= 8]
    try:
        secrets.append(hf_login_file().read_text().strip())
    except OSError:
        pass
    for s in secrets:
        if s:
            text = text.replace(s, "[secret]")
    return text
