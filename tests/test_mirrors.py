"""`mfetl mirrors` (2026-11-20): the dataset's Hugging Face and Kaggle copies follow Zenodo, and refuse rather than
guess. Every test runs against fake Zenodo, Hugging Face and Kaggle servers in one fake session; nothing here
touches the network."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path

import pytest

from moleculefinder_etl import cli, dataset, mirrors, zenodo

CONCEPT = "10.5281/zenodo.100"
DOI = "10.5281/zenodo.103"
HF_ID = "own/hf-data"
KG_ID = "own/kg-data"
HF_TOKEN = "hf_SECRETSECRETSECRET123456"
KG_TOKEN = "KGAT_SECRETSECRETSECRET654321"
KG_KEY = "legacykey-SECRET-0123456789"


# ── a small package, the published record, the logins ──────────────────────────────────────────────────────────
def _write_package(root: Path, version: str = "2026.11") -> None:
    root.mkdir(parents=True, exist_ok=True)
    zj = {"upload_type": "dataset", "title": dataset.TITLE, "creators": [{"name": "MoleculeFinder"}],
          "description": "d", "version": version, "publication_date": "2026-11-16", "access_right": "open",
          "license": "cc-zero"}
    meta = {"id": KG_ID, "title": "T", "subtitle": "929 molecules, 430 products, CC0",
            "description": f"The dataset. Cite: https://doi.org/{CONCEPT}", "keywords": ["chemistry"],
            "licenses": [{"name": "CC0-1.0"}],
            "resources": [{"path": "molecules.csv", "description": "One row per molecule.",
                           "schema": {"fields": [{"name": "slug", "type": "string", "description": "id"}]}}]}
    files = {"molecules.csv": "slug\ncaffeine\n", "README.md": "readme\n", "zenodo.json": json.dumps(zj),
             "CITATION.cff": f"version: {version}\n", "dataset-metadata.json": json.dumps(meta)}
    manifest = {"title": dataset.TITLE, "version": version, "license": "CC0-1.0", "rows": {"molecules": 1}, "files": {}}
    for name, text in sorted(files.items()):
        (root / name).write_text(text)
        b = text.encode()
        manifest["files"][name] = {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
    (root / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n")
    card = root / "huggingface" / "README.md"
    card.parent.mkdir(exist_ok=True)
    card.write_text(f"---\nlicense: cc0-1.0\n---\n| **Version** | {version} |\n{DOI}\nhttps://doi.org/{CONCEPT}\n"
                    f"https://huggingface.co/datasets/{HF_ID}\n")


class Resp:
    def __init__(self, status, body=None, raw=None):
        self.status_code = status
        self._body = body
        self.content = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        self.text = self.content.decode(errors="replace")

    def json(self):
        if self._body is None:
            raise ValueError
        return self._body


def _oid(b: bytes) -> str:
    return mirrors.git_blob_oid(b)


class Fake:
    """Zenodo (public record), Hugging Face and Kaggle, enough for the mirrors."""

    def __init__(self, pkg_root: Path, zenodo_version="2026.11", hf_version="2026.10.1", kg_version="2026.10.1"):
        self.zv = zenodo_version
        self.pkg = pkg_root
        self.calls: list[tuple[str, str]] = []
        self.headers_seen: list[tuple[str, dict]] = []
        self.hf = self._old_files(hf_version) if hf_version else {}
        self.hf_sha = "aaaa"
        self.hf_commits: list[str] = []
        self.hf_licence = "cc0-1.0"
        self.hf_fail = False
        self.kg_versions = [(1, "Initial release", {}), (2, f"{kg_version}: older", self._old_files(kg_version))]
        self.kg_licence = "CC0: Public Domain"
        self.kg_pending: dict[str, bytes] = {}
        self.kg_blobs: dict[str, bytes] = {}
        self.kg_fail = False
        self.kg_corrupt: str | None = None
        self.kg_status = "Ready"
        self.kg_stale_public = False        # Kaggle's anonymous view trails a new version (its description)

    def _old_files(self, version):
        files = {n: (self.pkg / n).read_bytes() for n in ("molecules.csv", "CITATION.cff", "zenodo.json", "MANIFEST.json",
                                                         "README.md", "dataset-metadata.json")}
        files["MANIFEST.json"] = json.dumps({"version": version}).encode()
        files["molecules.csv"] = b"slug\nold\n"
        return files

    # ── session API ──
    def request(self, method, url, timeout=None, **kw):
        self.calls.append((method, url))
        self.headers_seen.append((url, dict(getattr(self, "_headers", {}))))
        if url.startswith("https://zenodo.org"):
            return self._zenodo(method, url)
        if url.startswith(mirrors.HF):
            return self._hf(method, url, kw)
        if url.startswith((mirrors.KG_API, mirrors.KG_WWW)) or "upload.example" in url:
            return self._kaggle(method, url, kw)
        return Resp(404, {})

    @property
    def headers(self):
        self._headers = getattr(self, "_headers", {})
        return self._headers

    def _zenodo(self, method, url):
        path = url.replace(zenodo.API, "")
        rid = {"2026.10": 101, "2026.10.1": 102, "2026.11": 103}
        latest_v = self.zv
        latest = rid[latest_v]
        rec = lambda r, v: {"id": r, "conceptrecid": "100", "conceptdoi": CONCEPT, "doi": f"10.5281/zenodo.{r}",
                            "metadata": {"title": dataset.TITLE, "version": v, "creators": [{"name": "MoleculeFinder"}],
                                         "license": {"id": "cc-zero"}}}
        if path == "/records/100":
            return Resp(200, rec(latest, latest_v))
        if path.startswith(f"/records/{latest}/versions"):
            vs = [v for v in rid if zenodo.version_key(v) <= zenodo.version_key(latest_v)]
            return Resp(200, {"hits": {"hits": [rec(rid[v], v) for v in vs]}, "links": {}})
        if path == f"/records/{latest}":
            r = rec(latest, latest_v)
            names = zenodo.read_package(self.pkg).files()
            r["files"] = [{"key": n, "size": len((self.pkg / n).read_bytes()),
                           "checksum": "md5:" + zenodo.md5((self.pkg / n).read_bytes())} for n in names]
            return Resp(200, r)
        return Resp(404, {})

    def _hf(self, method, url, kw):
        if url.endswith("/api/whoami-v2"):
            return Resp(200, {"name": "own", "auth": {"accessToken": {"role": "write"}}})
        if url.startswith(f"{mirrors.HF}/api/datasets/{HF_ID}?blobs=true"):
            return Resp(200, {"id": HF_ID, "sha": self.hf_sha, "cardData": {"license": self.hf_licence},
                              "siblings": [{"rfilename": ".gitattributes", "size": 5, "blobId": "x"}]
                              + [{"rfilename": n, "size": len(b), "blobId": _oid(b)} for n, b in sorted(self.hf.items())]})
        if url.startswith(f"{mirrors.HF}/datasets/{HF_ID}/resolve/main/"):
            name = url.rsplit("/", 1)[1]
            return Resp(200, raw=self.hf[name]) if name in self.hf else Resp(404, {})
        if method == "POST" and url == f"{mirrors.HF}/api/datasets/{HF_ID}/commit/main":
            if self.hf_fail:
                return Resp(500, raw=b"boom")
            ops = [json.loads(line) for line in kw["data"].decode().splitlines()]
            self.hf_commits.append(ops[0]["value"]["summary"])
            for op in ops[1:]:
                v = op["value"]
                if op["key"] == "file":
                    self.hf[v["path"]] = base64.b64decode(v["content"])
                elif op["key"] == "deletedFile":
                    self.hf.pop(v["path"], None)
            self.hf_sha = f"commit{len(self.hf_commits)}"
            return Resp(200, {"commitOid": self.hf_sha})
        return Resp(404, {})

    def _kaggle(self, method, url, kw):
        newest = self.kg_versions[-1]
        if url.startswith(f"{mirrors.KG_WWW}/datasets/view/{KG_ID}"):
            meta = json.loads((self.pkg / "dataset-metadata.json").read_text())
            stale = self.kg_stale_public and not self._authed(kw)
            return Resp(200, {"ref": KG_ID, "licenseName": self.kg_licence, "subtitle": meta["subtitle"],
                              "description": "915 molecules, the old description" if stale else meta["description"],
                              "versions": [{"versionNumber": n, "versionNotes": note,
                                            "status": self.kg_status if n == newest[0] else "Ready"}
                                           for n, note, _ in self.kg_versions]})
        if url.startswith(f"{mirrors.KG_WWW}/datasets/list/{KG_ID}"):
            return Resp(200, {"datasetFiles": [{"name": n, "totalBytes": len(b)} for n, b in sorted(newest[2].items())]})
        if url.startswith(f"{mirrors.KG_WWW}/datasets/download/{KG_ID}/"):
            name = url.split(f"/download/{KG_ID}/")[1].split("?")[0]
            data = newest[2][name]
            return Resp(200, raw=data + b"x" if name == self.kg_corrupt else data)
        if url.endswith("/GetDatasetStatus"):
            return Resp(200, {"status": "READY"}) if kw.get("_authed") or self._authed(kw) else Resp(401, {"error": "no"})
        if url.endswith("/StartBlobUpload"):
            if not self._authed(kw):
                return Resp(401, {"error": "no"})
            j = kw["json"]
            tok = f"blob-{j['name']}"
            self.kg_pending[tok] = b""
            self.kg_blobs[tok] = b""
            return Resp(200, {"token": tok, "createUrl": f"https://upload.example/{j['name']}"})
        if method == "PUT" and "upload.example" in url:
            self.kg_blobs[f"blob-{url.rsplit('/', 1)[1]}"] = kw["data"]
            return Resp(200, {})
        if url.endswith("/CreateDatasetVersion"):
            if self.kg_fail:
                return Resp(200, {"error": "nope"})
            j = kw["json"]
            files = {}
            for f in j["body"]["files"]:
                name = f["token"].removeprefix("blob-")
                files[name] = self.kg_blobs[f["token"]]
            self.kg_versions.append((newest[0] + 1, j["body"]["versionNotes"], files))
            self.last_version_body = j["body"]
            return Resp(200, {"ref": KG_ID})
        return Resp(404, {})

    def _authed(self, kw):
        h = self.headers
        return bool(h.get("Authorization")) or bool(kw.get("auth"))


class Session:
    """The one fake session every Http shares; it records the Authorization header each call carried."""

    def __init__(self, fake: Fake):
        self.fake = fake
        self.headers: dict[str, str] = {}
        self.auths: list[tuple[str, bool]] = []

    def request(self, method, url, timeout=None, **kw):
        merged = {**self.headers, **kw.get("headers", {})}
        self.fake._headers = merged
        self.auths.append((url, bool(merged.get("Authorization") or kw.get("auth"))))
        self.fake.s_headers = merged
        return self.fake.request(method, url, timeout=timeout, **kw)


def _session_factory(fake):
    """Each Http gets its own headers, as a real requests.Session would."""
    class S(Session):
        def __init__(self):
            super().__init__(fake)
    return S


@pytest.fixture
def world(tmp_path, monkeypatch):
    pkg = tmp_path / "dataset"
    _write_package(pkg)
    pub = tmp_path / "dataset_published.yaml"
    pub.write_text(f"concept_doi: {CONCEPT}\nzenodo_record: https://zenodo.org/records/103\nkaggle: {KG_ID}\n"
                   f"huggingface: {HF_ID}\n"
                   'versions:\n  "2026.10": 10.5281/zenodo.101\n  "2026.10.1": 10.5281/zenodo.102\n'
                   '  "2026.11": 10.5281/zenodo.103\n')
    real = dataset.published
    monkeypatch.setattr(dataset, "published", lambda path=pub: real(path))
    monkeypatch.setattr(dataset, "PUBLISHED", pub)
    monkeypatch.setattr(dataset, "OUT", pkg)
    env = tmp_path / ".env"
    env.write_text(f"HF_TOKEN={HF_TOKEN}\nKAGGLE_API_TOKEN={KG_TOKEN}\n")
    env.chmod(0o600)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hfhome"))       # no real login is ever read
    fake = Fake(pkg)
    monkeypatch.setattr("requests.Session", _session_factory(fake))
    return tmp_path, pkg, pub, env, fake


def _run(world, **kw):
    _, pkg, _, env, _ = world
    return mirrors.run(out=pkg, env_file=env, sleep=lambda s: None, **kw)


def _messages(caplog):
    return "\n".join(r.getMessage() for r in caplog.records)


# ── the happy path ──────────────────────────────────────────────────────────────────────────────────────────────
def test_publishes_both_mirrors_and_reads_them_back(world, caplog):
    caplog.set_level(logging.INFO)
    _, pkg, _, _, fake = world
    assert _run(world) == 0
    msg = _messages(caplog)
    assert "huggingface: PUBLISHED" in msg and "kaggle: PUBLISHED" in msg
    # Hugging Face: ONE commit named for the version; the card is the repo's README.md; Kaggle's metadata rides along
    assert fake.hf_commits == [f"MoleculeFinder dataset 2026.11 (Zenodo {DOI})"]
    assert fake.hf["README.md"] == (pkg / "huggingface" / "README.md").read_bytes()
    assert set(fake.hf) == set(zenodo.read_package(pkg).files()) | {"dataset-metadata.json"}
    # Kaggle: one new version, noted with the version and the DOI, the package's files, the metadata's words
    n, notes, files = fake.kg_versions[-1]
    assert n == 3 and notes.startswith("2026.11:") and DOI in notes and CONCEPT in notes
    assert set(files) == set(zenodo.read_package(pkg).files()) and "dataset-metadata.json" not in files
    body = fake.last_version_body
    assert body["subtitle"] == "929 molecules, 430 products, CC0" and body["categoryIds"] == ["chemistry"]
    mol = next(f for f in body["files"] if f["token"] == "blob-molecules.csv")
    assert mol["description"] == "One row per molecule." and mol["columns"][0]["name"] == "slug"
    assert files["molecules.csv"] == (pkg / "molecules.csv").read_bytes()


def test_a_second_run_says_each_already_holds_it_and_exits_0(world, caplog):
    assert _run(world) == 0
    caplog.clear()
    caplog.set_level(logging.INFO)
    _, _, _, _, fake = world
    commits, versions = len(fake.hf_commits), len(fake.kg_versions)
    assert _run(world) == 0
    msg = _messages(caplog)
    assert "Hugging Face already holds 2026.11" in msg and "Kaggle already holds 2026.11" in msg
    assert len(fake.hf_commits) == commits and len(fake.kg_versions) == versions      # nothing written again


def test_the_commit_sends_only_what_changed_and_removes_what_the_package_lacks(world):
    _, _, _, _, fake = world
    fake.hf["stale.csv"] = b"old"
    assert _run(world, only="huggingface") == 0
    assert "stale.csv" not in fake.hf


def test_dry_run_needs_no_login_and_writes_nothing(world, caplog):
    caplog.set_level(logging.INFO)
    _, _, _, env, fake = world
    env.write_text("")
    assert _run(world, dry_run=True) == 0
    msg = _messages(caplog)
    assert "huggingface: WOULD PUBLISH" in msg and "kaggle: WOULD PUBLISH" in msg and "NO LOGIN" in msg
    assert not fake.hf_commits and len(fake.kg_versions) == 2
    assert not [c for c in fake.calls if c[0] in ("POST", "PUT") and "zenodo" not in c[1]]


def test_check_is_read_only_and_needs_the_mirrors_to_hold_the_package(world, caplog):
    caplog.set_level(logging.INFO)
    assert _run(world, check=True) == 1                    # they hold 2026.10.1
    assert _run(world) == 0
    caplog.clear()
    assert _run(world, check=True) == 0
    assert "CHECKED" in _messages(caplog)


# ── every refusal ───────────────────────────────────────────────────────────────────────────────────────────────
def test_refuses_a_file_that_does_not_match_the_manifest(world, caplog):
    _, pkg, _, _, fake = world
    (pkg / "molecules.csv").write_text("slug\ntampered\n")
    assert _run(world) == 1
    assert "does not match its manifest" in _messages(caplog)
    assert not fake.hf_commits and len(fake.kg_versions) == 2


def test_refuses_a_version_zenodo_does_not_hold_yet(world, caplog):
    _, _, _, _, fake = world
    fake.zv = "2026.10.1"                                  # Zenodo's latest is older than the package
    assert _run(world) == 1
    assert "never gets ahead of Zenodo" in _messages(caplog)
    assert not fake.hf_commits and len(fake.kg_versions) == 2


def test_refuses_when_the_package_is_not_the_one_on_zenodo(world, caplog):
    _, _, _, _, fake = world
    orig = fake._zenodo

    def altered(method, url):
        r = orig(method, url)
        if url.endswith("/records/103"):
            body = r.json()
            body["files"][0]["checksum"] = "md5:" + "0" * 32
            return Resp(200, body)
        return r
    fake._zenodo = altered
    assert _run(world) == 1
    assert "not the package's" in _messages(caplog) and not fake.hf_commits


def test_refuses_a_licence_that_is_not_cc0(world, caplog):
    _, pkg, _, _, fake = world
    m = json.loads((pkg / "MANIFEST.json").read_text())
    m["license"] = "CC-BY-4.0"
    (pkg / "MANIFEST.json").write_text(json.dumps(m))
    assert _run(world) == 1
    assert "licence" in _messages(caplog) and not fake.hf_commits


def test_refuses_a_zenodo_record_that_is_not_cc0(world, caplog):
    _, _, _, _, fake = world
    orig = fake._zenodo

    def altered(method, url):
        r = orig(method, url)
        if url.endswith("/records/100"):
            body = r.json()
            body["metadata"]["license"] = {"id": "cc-by-4.0"}
            return Resp(200, body)
        return r
    fake._zenodo = altered
    assert _run(world) == 1
    assert "not CC0" in _messages(caplog) and not fake.hf_commits


def test_refuses_a_kaggle_id_that_is_not_the_published_one(world, caplog):
    _, pkg, _, _, fake = world
    meta = json.loads((pkg / "dataset-metadata.json").read_text())
    meta["id"] = "someone/else"
    text = json.dumps(meta)
    (pkg / "dataset-metadata.json").write_text(text)
    m = json.loads((pkg / "MANIFEST.json").read_text())
    m["files"]["dataset-metadata.json"] = {"bytes": len(text.encode()), "sha256": hashlib.sha256(text.encode()).hexdigest()}
    (pkg / "MANIFEST.json").write_text(json.dumps(m))
    caplog.set_level(logging.INFO)
    assert _run(world) == 1
    msg = _messages(caplog)
    assert "kaggle: REFUSED" in msg and "someone/else" in msg
    assert len(fake.kg_versions) == 2 and fake.hf_commits          # the other mirror went ahead


def test_refuses_a_hugging_face_id_the_card_does_not_link(world, caplog):
    _, _, pub, _, fake = world
    pub.write_text(pub.read_text().replace(f"huggingface: {HF_ID}", "huggingface: own/another"))
    caplog.set_level(logging.INFO)
    assert _run(world) == 1
    assert "does not link own/another" in _messages(caplog) and not fake.hf_commits


def test_refuses_a_mirror_answering_for_another_id(world, caplog):
    _, _, _, _, fake = world
    orig = fake._hf

    def altered(method, url, kw):
        r = orig(method, url, kw)
        if "?blobs=true" in url:
            body = r.json()
            body["id"] = "own/different"
            return Resp(200, body)
        return r
    fake._hf = altered
    caplog.set_level(logging.INFO)
    assert _run(world) == 1
    assert "answers for 'own/different'" in _messages(caplog) and not fake.hf_commits


def test_refuses_a_mirror_that_holds_this_version_with_other_files(world, caplog):
    _, _, _, _, fake = world
    assert _run(world) == 0
    fake.hf["molecules.csv"] = b"slug\nsomeone edited\n"
    caplog.clear()
    caplog.set_level(logging.INFO)
    commits = len(fake.hf_commits)
    assert _run(world) == 1
    assert "holds version 2026.11 but its files differ" in _messages(caplog)
    assert len(fake.hf_commits) == commits


def test_refuses_a_mirror_newer_than_the_package_and_one_it_cannot_name(world, caplog):
    _, _, _, _, fake = world
    fake.hf["MANIFEST.json"] = json.dumps({"version": "2026.12"}).encode()
    del fake.kg_versions[-1]
    fake.kg_versions.append((2, "something unnamed", {}))
    caplog.set_level(logging.INFO)
    assert _run(world) == 1
    msg = _messages(caplog)
    assert "newer than this package's 2026.11" in msg and "cannot tell which version Kaggle holds" in msg
    assert not fake.hf_commits and len(fake.kg_versions) == 2


# ── one failing mirror does not stop the other; the read-back catches a bad copy ──────────────────────────────────
def test_one_mirror_failing_does_not_stop_the_other(world, caplog):
    caplog.set_level(logging.INFO)
    _, _, _, _, fake = world
    fake.hf_fail = True
    assert _run(world) == 1
    msg = _messages(caplog)
    assert "huggingface: REFUSED" in msg and "kaggle: PUBLISHED" in msg
    assert "1 of 2 mirror(s) need a look: huggingface" in msg
    assert len(fake.kg_versions) == 3


def test_a_missing_login_fails_that_mirror_alone(world, caplog):
    caplog.set_level(logging.INFO)
    _, _, _, env, _ = world
    env.write_text(f"HF_TOKEN={HF_TOKEN}\n")
    assert _run(world) == 1
    msg = _messages(caplog)
    assert "huggingface: PUBLISHED" in msg and "kaggle: REFUSED: no Kaggle login" in msg


def test_the_read_back_compares_the_bytes_the_mirror_holds(world, caplog):
    caplog.set_level(logging.INFO)
    _, _, _, _, fake = world
    fake.kg_corrupt = "molecules.csv"                      # Kaggle serves a copy that is not what was sent
    assert _run(world) == 1
    msg = _messages(caplog)
    assert "read back from Kaggle, it does not match the package" in msg and "molecules.csv: differs" in msg
    assert "huggingface: PUBLISHED" in msg


def test_the_read_back_checks_the_licence_and_the_head(world, caplog):
    caplog.set_level(logging.INFO)
    _, _, _, _, fake = world
    fake.hf_licence = "mit"
    assert _run(world, only="huggingface") == 1
    assert "licence is 'mit'" in _messages(caplog)


def test_a_stale_public_kaggle_page_does_not_fail_a_publish_that_the_login_can_read_back(world, caplog):
    caplog.set_level(logging.INFO)
    _, _, _, env, fake = world
    fake.kg_stale_public = True
    assert _run(world, only="kaggle") == 0
    assert "kaggle: PUBLISHED" in _messages(caplog)
    env.write_text("")                                     # no login: the public view is all there is
    caplog.clear()
    assert _run(world, only="kaggle", check=True) == 1
    assert "the description does not name the concept DOI" in _messages(caplog)


def test_kaggle_that_never_becomes_ready_is_reported(world, caplog):
    caplog.set_level(logging.INFO)
    _, _, _, _, fake = world
    fake.kg_status = "Pending"
    assert _run(world, only="kaggle") == 1
    assert "was not Ready" in _messages(caplog)


def test_kaggle_error_in_the_reply_is_a_failure(world, caplog):
    caplog.set_level(logging.INFO)
    _, _, _, _, fake = world
    fake.kg_fail = True
    assert _run(world, only="kaggle") == 1
    assert "Kaggle refused the new version: nope" in _messages(caplog)


# ── logins ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_hugging_face_login_falls_back_to_the_login_file_and_names_where(tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    f = tmp_path / "token"
    f.write_text(HF_TOKEN + "\n")
    tok, where = mirrors.hf_token(env, f)
    assert tok == HF_TOKEN and str(f) in where and HF_TOKEN not in where
    env.write_text("HF_TOKEN=fromenv123\n")
    assert mirrors.hf_token(env, f)[0] == "fromenv123"
    with pytest.raises(zenodo.Refused):
        mirrors.hf_token(tmp_path / "nope", tmp_path / "missing")


def test_kaggle_login_takes_either_kind_of_credential(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"KAGGLE_API_TOKEN={KG_TOKEN}\n")
    headers, auth, secrets, where = mirrors.kaggle_login(env)
    assert headers == {"Authorization": f"Bearer {KG_TOKEN}"} and auth is None and KG_TOKEN not in where
    env.write_text(f"KAGGLE_USERNAME=me\nKAGGLE_KEY={KG_KEY}\n")
    headers, auth, secrets, where = mirrors.kaggle_login(env)
    assert auth == ("me", KG_KEY) and KG_KEY in secrets and KG_KEY not in where
    env.write_text("KAGGLE_USERNAME=me\n")
    with pytest.raises(zenodo.Refused):
        mirrors.kaggle_login(env)


def test_whoami_checks_each_login_read_only(world, caplog):
    caplog.set_level(logging.INFO)
    _, _, _, env, fake = world
    assert _run(world, whoami=True) == 0
    msg = _messages(caplog)
    assert "huggingface: LOGIN OK: own" in msg and "kaggle: LOGIN OK" in msg
    assert not fake.hf_commits and len(fake.kg_versions) == 2
    env.write_text(f"HF_TOKEN={HF_TOKEN}\n")
    caplog.clear()
    assert _run(world, whoami=True) == 1


def test_the_upload_url_never_gets_the_login(world):
    _, _, _, _, fake = world
    sess = {}

    class Spy(Session):
        def __init__(self):
            super().__init__(fake)
            sess[id(self)] = self
    import requests
    requests.Session = Spy                                # monkeypatch fixture restores it
    assert _run(world, only="kaggle") == 0
    puts = [(u, a) for s in sess.values() for u, a in s.auths if "upload.example" in u]
    assert puts and not any(a for _, a in puts)


# ── no token ever appears in any output ─────────────────────────────────────────────────────────────────────────
def test_no_token_appears_in_any_output(world, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    _, _, _, env, fake = world
    env.write_text(f"HF_TOKEN={HF_TOKEN}\nKAGGLE_USERNAME=me\nKAGGLE_KEY={KG_KEY}\n")
    fake.hf_fail = True                                    # a failure path as well as a success path
    _run(world)
    _run(world, dry_run=True)
    _run(world, whoami=True)
    out = capsys.readouterr()
    text = _messages(caplog) + out.out + out.err
    for secret in (HF_TOKEN, KG_TOKEN, KG_KEY, base64.b64encode(f"me:{KG_KEY}".encode()).decode()):
        assert secret not in text


def test_http_redacts_a_secret_from_a_network_error():
    class Boom:
        def __init__(self):
            self.headers = {}

        def request(self, *a, **k):
            raise ConnectionError(f"failed with Authorization: Bearer {HF_TOKEN}")

    h = mirrors.Http([HF_TOKEN], {"Authorization": f"Bearer {HF_TOKEN}"}, session=Boom())
    with pytest.raises(zenodo.Refused) as e:
        h.call("GET", "https://huggingface.co/x")
    assert HF_TOKEN not in str(e.value) and "[secret]" in str(e.value)


def test_cli_takes_the_logins_out_of_the_environment():
    import os
    for k in ("HF_TOKEN", "KAGGLE_API_TOKEN", "KAGGLE_USERNAME", "KAGGLE_KEY", "ZENODO_TOKEN"):
        assert k not in os.environ
    assert cli.main is not None


def test_a_zenodo_publish_is_followed_by_the_mirrors(monkeypatch):
    seen = {}
    monkeypatch.setattr(zenodo, "run", lambda **kw: 0)
    monkeypatch.setattr(mirrors, "run", lambda **kw: seen.setdefault("kw", kw) and 0)
    assert cli.main(["zenodo"]) == 0
    assert seen["kw"]["wait_for_zenodo"] > 0
    seen.clear()
    for flag in ("--dry-run", "--draft-only", "--discard", "--check"):
        assert cli.main(["zenodo", flag]) == 0
    assert not seen                                       # only a real publish calls the mirrors


def test_a_mirror_failure_after_a_zenodo_publish_is_reported_not_hidden(monkeypatch, caplog):
    monkeypatch.setattr(zenodo, "run", lambda **kw: 0)
    monkeypatch.setattr(mirrors, "run", lambda **kw: 1)
    assert cli.main(["zenodo"]) == 1
