"""`mfetl zenodo` (2026-11-20): a new dataset version reaches Zenodo by one command, and refuses rather than
guesses. Every test runs against a fake Zenodo; nothing here touches the network."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pytest

from moleculefinder_etl import cli, dataset, zenodo

TOKEN = "tok-SECRET-1234567890"
CONCEPT = "10.5281/zenodo.100"


# ── a small package and the published record ────────────────────────────────────────────────────────────────────
def _write_package(root: Path, version: str = "2026.11", doi: str | None = None, licence: str = "cc-zero") -> None:
    root.mkdir(parents=True, exist_ok=True)
    zj = {"upload_type": "dataset", "title": dataset.TITLE, "creators": [{"name": "MoleculeFinder",
          "affiliation": "137 Finder LLC"}], "description": "d", "version": version,
          "publication_date": "2026-11-16", "access_right": "open", "license": licence, "keywords": ["x"],
          "notes": f"This version {version}" + (f", https://doi.org/{doi}" if doi else "")}
    if doi:
        zj["doi"] = doi
    files = {"molecules.csv": "slug\ncaffeine\n", "README.md": "readme\n", "zenodo.json": json.dumps(zj),
             "CITATION.cff": f"version: {version}\n" + (f"doi: {doi}\n" if doi else ""),
             "dataset-metadata.json": "{}\n"}
    manifest = {"title": dataset.TITLE, "version": version, "license": "CC0-1.0", "rows": {"molecules": 1},
                "files": {}}
    for name, text in sorted(files.items()):
        (root / name).write_text(text)
        b = text.encode()
        manifest["files"][name] = {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
    (root / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    pkg = tmp_path / "dataset"
    _write_package(pkg)
    pub = tmp_path / "dataset_published.yaml"
    pub.write_text(f"concept_doi: {CONCEPT}\nzenodo_record: https://zenodo.org/records/102\nkaggle: a/b\n"
                   'versions:\n  "2026.10": 10.5281/zenodo.101\n  "2026.10.1": 10.5281/zenodo.102\n')
    real = dataset.published
    monkeypatch.setattr(dataset, "published", lambda path=pub: real(path))
    monkeypatch.setattr(dataset, "PUBLISHED", pub)
    monkeypatch.setattr(dataset, "OUT", pkg)

    def rebuild(p, doi):                       # what `mfetl dataset --version V --doi D` does to the package
        dataset.record_version(p.version, doi, pub)
        _write_package(p.root, p.version, doi)
        return zenodo.read_package(p.root)
    monkeypatch.setattr(zenodo, "rebuild_with_doi", rebuild)
    return tmp_path, pkg, pub


# ── a fake Zenodo ───────────────────────────────────────────────────────────────────────────────────────────────
class Resp:
    def __init__(self, status, body=None, raw=None, url=""):
        self.status_code, self._body, self.url = status, body, url
        self.content = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        self.text = self.content.decode(errors="replace")

    def json(self):
        if self._body is None:
            raise ValueError
        return self._body


class FakeZenodo:
    """Enough of Zenodo's API for the publisher: the public record, the version list and the deposit calls."""

    def __init__(self, title=dataset.TITLE, versions=(("2026.10", 101), ("2026.10.1", 102))):
        self.title = title
        self.versions = list(versions)
        self.drafts: dict[int, dict] = {}
        self.stored: dict[int, dict[str, bytes]] = {}
        self.calls: list[tuple[str, str]] = []
        self.headers: dict[str, str] = {}
        self.corrupt: str | None = None      # a file name whose stored copy is altered
        self.published: list[int] = []
        self.next_id = 200

    def _record(self, rid, version):
        return {"id": rid, "conceptrecid": "100", "conceptdoi": CONCEPT, "doi": f"10.5281/zenodo.{rid}",
                "metadata": {"title": self.title, "version": version, "creators": [{"name": "MoleculeFinder"}],
                             "license": {"id": "cc-zero"}}}

    def request(self, method, url, timeout=None, **kw):
        self.calls.append((method, url))
        path = url.replace(zenodo.API, "")
        latest_id, latest_v = self.versions[-1][1], self.versions[-1][0]
        if method == "GET" and path == "/records/100":
            return Resp(200, self._record(latest_id, latest_v))
        if method == "GET" and path.startswith(f"/records/{latest_id}/versions"):
            return Resp(200, {"hits": {"hits": [self._record(r, v) for v, r in self.versions]}, "links": {}})
        if method == "GET" and path.startswith("/deposit/depositions?status=draft"):
            return Resp(200, list(self.drafts.values()))
        if method == "POST" and path == f"/deposit/depositions/{latest_id}/actions/newversion":
            did = self.next_id
            self.next_id += 1
            self.drafts[did] = {"id": did, "conceptrecid": "100", "submitted": False, "metadata": {},
                                "links": {"bucket": f"https://zenodo.org/api/files/b{did}"}}
            self.stored[did] = {}
            return Resp(201, {"id": latest_id, "links": {"latest_draft": f"{zenodo.API}/deposit/depositions/{did}"}})
        for did, d in list(self.drafts.items()):
            base = f"/deposit/depositions/{did}"
            if path == base and method == "GET":
                return Resp(200, d)
            if path == base and method == "PUT":
                meta = dict(kw["json"]["metadata"])
                if meta.pop("prereserve_doi", None):
                    meta["prereserve_doi"] = {"doi": f"10.5281/zenodo.{did}", "recid": did}
                elif "prereserve_doi" in d["metadata"]:
                    meta["prereserve_doi"] = d["metadata"]["prereserve_doi"]
                d["metadata"] = meta
                return Resp(200, d)
            if path == base and method == "DELETE":
                del self.drafts[did]
                return Resp(204)
            if path == base + "/files" and method == "GET":
                return Resp(200, [{"id": n, "filename": n, "filesize": len(b),
                                   "checksum": hashlib.md5(b).hexdigest()} for n, b in self.stored[did].items()])
            if path.startswith(base + "/files/") and method == "DELETE":
                self.stored[did].pop(path.rsplit("/", 1)[1], None)
                return Resp(204)
            if path == base + "/actions/publish" and method == "POST":
                d["submitted"] = True
                self.published.append(did)
                self.versions.append((d["metadata"]["version"], did))
                del self.drafts[did]
                return Resp(202, {"id": did, "doi": f"10.5281/zenodo.{did}", "conceptdoi": CONCEPT, "submitted": True})
            if url.startswith(d["links"]["bucket"] + "/") and method == "PUT":
                name = url.rsplit("/", 1)[1]
                data = kw["data"]
                self.stored[did][name] = data + b"x" if name == self.corrupt else data
                return Resp(201, {"key": name})
        return Resp(404, {"message": f"no route {method} {path}; token was {self.headers.get('Authorization')}"})


def client(fake: FakeZenodo, tok: str | None = TOKEN) -> zenodo.Client:
    c = zenodo.Client(tok, session=_Session(fake))
    return c


class _Session:
    def __init__(self, fake):
        self.fake, self.headers = fake, {}

    def request(self, method, url, timeout=None, **kw):
        self.fake.headers = dict(self.headers)
        return self.fake.request(method, url, timeout=timeout, **kw)


# ── the package is checked against its manifest ─────────────────────────────────────────────────────────────────
def test_the_package_must_match_its_manifest_byte_for_byte(repo):
    _, pkg, _ = repo
    assert zenodo.read_package(pkg).files() == ["CITATION.cff", "MANIFEST.json", "README.md", "molecules.csv",
                                                 "zenodo.json"]        # Kaggle's own metadata stays off Zenodo
    (pkg / "molecules.csv").write_text("slug\ncaffeinf\n")
    with pytest.raises(zenodo.Refused, match="molecules.csv: does not match"):
        zenodo.read_package(pkg)


def test_a_file_not_in_the_manifest_or_a_licence_not_cc0_refuses(repo, tmp_path):
    _, pkg, _ = repo
    (pkg / "stray.csv").write_text("x")
    with pytest.raises(zenodo.Refused, match="stray.csv: on disk, not in the manifest"):
        zenodo.read_package(pkg)
    other = tmp_path / "other"
    _write_package(other, licence="cc-by-4.0")
    with pytest.raises(zenodo.Refused, match="licence is 'cc-by-4.0'"):
        zenodo.read_package(other)


def test_the_token_goes_in_the_header_and_is_never_shown(repo, caplog):
    fake = FakeZenodo()
    c = client(fake)
    with pytest.raises(zenodo.Refused) as e:
        c.call("GET", "/no/such/route")
    assert TOKEN not in str(e.value) and "[token]" in str(e.value)
    assert all(TOKEN not in url for _, url in fake.calls)
    assert fake.headers["Authorization"] == f"Bearer {TOKEN}"


def test_the_token_is_read_from_the_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SUPABASE_URL=x\n")
    with pytest.raises(zenodo.Refused, match="has no ZENODO_TOKEN") as e:
        zenodo.token(env)
    env.write_text(f"ZENODO_TOKEN={TOKEN}\n")
    assert zenodo.token(env) == TOKEN
    assert TOKEN not in str(e.value)


def test_no_other_stage_carries_the_token():
    # cli.py loads .env into the environment for the database keys; the token is taken straight back out, so no
    # stage (and no process a stage starts) carries it. Read from the source: reloading cli would load the real .env.
    src = Path(cli.__file__).read_text()
    assert src.index('os.environ.pop("ZENODO_TOKEN", None)') > src.index("load_dotenv()")
    assert "dotenv_values" in Path(zenodo.__file__).read_text()


# ── the record and the plan ─────────────────────────────────────────────────────────────────────────────────────
def test_the_record_must_be_moleculefinders(repo):
    pub = dataset.published()
    rec = zenodo.find_record(client(FakeZenodo(), None), pub)
    assert (rec.latest_id, rec.latest_version) == (102, "2026.10.1")
    with pytest.raises(zenodo.Refused, match="not the MoleculeFinder record"):
        zenodo.find_record(client(FakeZenodo(title="Something else"), None), pub)


@pytest.mark.parametrize("versions, match", [
    ((("2026.10", 101), ("2026.10.1", 102), ("2026.11", 103)), "already exists on Zenodo"),
    ((("2026.10", 101), ("2026.12", 102)), "not newer than Zenodo's latest"),
    ((("2026.10", 101), ("2026.10.1", 102), ("2026.10.2", 103)), "a version was published another way"),
])
def test_the_plan_refuses(repo, versions, match):
    fake = FakeZenodo(versions=versions)
    assert zenodo.run(dry_run=True, client=client(fake, None)) == 1
    assert not fake.drafts and not fake.published
    pub = dataset.published()
    with pytest.raises(zenodo.Refused, match=match):
        zenodo.check_plan(zenodo.read_package(dataset.OUT), zenodo.find_record(client(fake, None), pub), pub)


def test_a_dry_run_creates_nothing(repo):
    fake = FakeZenodo()
    assert zenodo.run(dry_run=True, client=client(fake, None)) == 0
    assert all(m == "GET" for m, _ in fake.calls)


# ── the publish ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_publish_reserves_the_doi_writes_it_into_the_package_and_checks_the_draft_first(repo, caplog):
    _, pkg, pub = repo
    fake = FakeZenodo()
    caplog.set_level(logging.INFO)
    assert zenodo.run(client=client(fake)) == 0
    assert fake.published == [200]
    assert fake.versions[-1] == ("2026.11", 200)
    assert '"2026.11": 10.5281/zenodo.200' in pub.read_text()
    assert "zenodo_record: https://zenodo.org/records/200" in pub.read_text()
    assert "10.5281/zenodo.200" in (pkg / "CITATION.cff").read_text()
    methods = [m for m, u in fake.calls if "actions/publish" in u]
    assert methods == ["POST"]
    # the draft was read back (its files) after the uploads and before the publish call
    order = [u for _, u in fake.calls]
    last_upload = max(i for i, u in enumerate(order) if "/api/files/" in u)
    check = max(i for i, u in enumerate(order) if u.endswith("/deposit/depositions/200/files"))
    assert last_upload < check < order.index(next(u for u in order if "actions/publish" in u))
    assert TOKEN not in caplog.text


def test_a_draft_that_does_not_match_is_discarded_and_the_files_put_back(repo):
    _, pkg, pub = repo
    before_pub, before_cff = pub.read_text(), (pkg / "CITATION.cff").read_text()
    fake = FakeZenodo()
    fake.corrupt = "molecules.csv"
    assert zenodo.run(client=client(fake)) == 1
    assert not fake.published and not fake.drafts                     # nothing published, no stray draft
    assert pub.read_text() == before_pub and (pkg / "CITATION.cff").read_text() == before_cff


def test_an_open_draft_someone_else_left_refuses_before_anything_is_made(repo):
    fake = FakeZenodo()
    fake.drafts[150] = {"id": 150, "conceptrecid": "100", "submitted": False, "metadata": {"version": "2026.10.2"},
                        "links": {"bucket": "https://zenodo.org/api/files/b150"}}
    assert zenodo.run(client=client(fake)) == 1
    assert not any("newversion" in u for _, u in fake.calls) and not fake.published
    assert 150 in fake.drafts                                           # never deleted without --discard


def test_draft_only_stops_before_publishing_and_the_next_run_publishes_that_draft(repo):
    fake = FakeZenodo()
    assert zenodo.run(draft_only=True, client=client(fake)) == 0
    assert list(fake.drafts) == [200] and not fake.published
    assert zenodo.run(dry_run=True, client=client(fake, None)) == 0    # the resumable state dry-runs clean
    assert zenodo.run(client=client(fake)) == 0
    assert fake.published == [200]
    assert sum("newversion" in u for _, u in fake.calls) == 1


def test_discard_deletes_the_open_draft(repo):
    fake = FakeZenodo()
    assert zenodo.run(draft_only=True, client=client(fake)) == 0
    assert zenodo.run(do_discard=True, client=client(fake)) == 0
    assert not fake.drafts and not fake.published


def test_the_published_record_is_checked_read_only(repo, monkeypatch):
    _, pkg, _ = repo
    fake = FakeZenodo()
    assert zenodo.run(client=client(fake)) == 0
    files = {n: (pkg / n).read_bytes() for n in zenodo.read_package(pkg).files()}
    orig = fake.request

    def public(method, url, timeout=None, **kw):
        seen.append(method)
        if method == "GET" and url.endswith("/records/200"):
            return Resp(200, {**fake._record(200, "2026.11"), "files": [{"key": n} for n in files]})
        if method == "GET" and url.endswith("/records/101"):
            return Resp(200, fake._record(101, "2026.10"))
        if method == "GET" and url.endswith("/records/102"):
            return Resp(200, fake._record(102, "2026.10.1"))
        if "/records/200/files/" in url:
            return Resp(200, raw=files[url.split("/files/")[1].split("?")[0]])
        return orig(method, url, timeout=timeout, **kw)
    seen: list[str] = []
    fake.request = public

    class R:
        url = "https://zenodo.org/records/200"
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    assert zenodo.run(check=True, client=client(fake, None)) == 0
    assert seen and set(seen) == {"GET"}
