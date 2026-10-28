"""The CC0 dataset (growth plan run D): its schema, its exclusions, its counts.

Two halves. The committed package in data/dataset/ is read back and checked against its own
manifest and, when it was built from the snapshot now on disk, against that snapshot row for row.
The builder is exercised on small synthetic records (offline: no raw_cache needed), including the
LD50 provenance trace on a PUG-View-shaped record.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from moleculefinder_etl import dataset
from moleculefinder_etl.config import DATA, SNAPSHOTS

PKG = DATA / "dataset"
BUILT = (PKG / "MANIFEST.json").exists()
EXPECTED_FILES = {f"{t}.csv" for t in dataset.TABLES} | {
    "moleculefinder.json", "README.md", "LICENSE.txt", "CITATION.cff", "datapackage.json",
    "dataset-metadata.json", "zenodo.json", "MANIFEST.json",
}
# Columns that must never appear: the fields left out for their sources' terms, or as dosing.
FORBIDDEN_COLUMNS = {"cas", "ghs", "signal_word", "pictograms", "h_statements", "synonyms",
                     "display_synonyms", "serving_mg", "structure_svg", "approval_register"}


def _csv(name: str) -> list[dict[str, str]]:
    with (PKG / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ── the committed package ───────────────────────────────────────────────────
pytestmark_built = pytest.mark.skipif(not BUILT, reason="data/dataset not built (mfetl dataset)")


@pytestmark_built
def test_the_package_holds_exactly_its_files_and_their_checksums():
    manifest = json.loads((PKG / "MANIFEST.json").read_text())
    on_disk = {p.name for p in PKG.iterdir() if p.name != ".DS_Store"}   # Finder metadata, gitignored
    assert on_disk == EXPECTED_FILES
    for name, meta in manifest["files"].items():
        data = (PKG / name).read_bytes()
        assert len(data) == meta["bytes"], name
        assert hashlib.sha256(data).hexdigest() == meta["sha256"], name
    assert manifest["license"] == "CC0-1.0"


@pytestmark_built
def test_every_table_has_its_columns_and_the_manifest_row_count():
    manifest = json.loads((PKG / "MANIFEST.json").read_text())
    whole = json.loads((PKG / "moleculefinder.json").read_text())
    for t, cols in dataset.TABLES.items():
        with (PKG / f"{t}.csv").open(encoding="utf-8", newline="") as f:
            header = next(csv.reader(f))
        assert header == [c[0] for c in cols], t
        assert not FORBIDDEN_COLUMNS & set(header), t
        rows = _csv(f"{t}.csv")
        assert len(rows) == manifest["rows"][t] == len(whole["tables"][t]), t
        for c, ty, desc, src in cols:
            assert desc and src, f"{t}.{c} lacks a description or a source"


@pytestmark_built
def test_types_keys_and_joins():
    mols = _csv("molecules.csv")
    slugs = [m["slug"] for m in mols]
    assert len(slugs) == len(set(slugs))
    products = {p["slug"] for p in _csv("products.csv")}
    cats = {c["slug"] for c in _csv("categories.csv")}
    worlds = {w["slug"] for w in _csv("worlds.csv")}
    S = set(slugs)
    for r in _csv("product_molecules.csv"):
        assert r["product_slug"] in products and r["molecule_slug"] in S
    for r in _csv("molecule_categories.csv"):
        assert r["category_slug"] in cats and r["molecule_slug"] in S
    for r in _csv("relationships.csv") + _csv("similarity.csv"):
        assert (r.get("from_slug") or r["molecule_slug"]) in S
        assert (r.get("to_slug") or r["neighbor_slug"]) in S
    for r in _csv("world_molecules.csv"):
        assert r["world_slug"] in worlds and r["molecule_slug"] in S
    for t, cols in dataset.TABLES.items():
        for r in _csv(f"{t}.csv"):
            for c, ty, _, _ in cols:
                v = r[c]
                if v == "":
                    continue
                if ty == "integer":
                    int(v)
                elif ty == "number":
                    float(v)
                elif ty == "boolean":
                    assert v in ("true", "false"), (t, c, v)


@pytestmark_built
def test_every_ld50_kept_names_a_us_government_source_and_carries_all_four_columns():
    kept = 0
    for m in _csv("molecules.csv"):
        cols = [m["ld50_mg_per_kg"], m["ld50_species"], m["ld50_route"], m["ld50_sources"]]
        if m["ld50_mg_per_kg"]:
            kept += 1
            assert all(cols[1:]), m["slug"]
            assert set(m["ld50_sources"].split(" | ")) <= dataset.PUBLIC_DOMAIN_TOX_SOURCES, m["slug"]
        else:
            assert not any(cols), m["slug"]
    assert kept > 200


@pytestmark_built
def test_licences_are_drugs_at_fda_only():
    for r in _csv("licences.csv"):
        assert r["regulator"] == "US Food and Drug Administration"
        assert r["source_url"].startswith("https://www.accessdata.fda.gov/")


@pytestmark_built
def test_no_ghs_hub_survives_and_the_readme_names_every_exclusion():
    kinds = {c["kind"] for c in _csv("categories.csv")}
    assert "poison" not in kinds
    readme = (PKG / "README.md").read_text()
    for phrase in ["GHS hazard classification", "LD50 values", "licence records", "CAS Registry Numbers",
                   "PubChem synonyms", "Serving sizes", "CC0 1.0"]:
        assert phrase in readme, phrase
    # A package built since SEO run 2 counts the sweetness values it withholds and says so.
    manifest = json.loads((PKG / "MANIFEST.json").read_text())
    if manifest["withheld"].get("sweetness"):
        assert "relative sweetness values" in readme
    assert "chemical database" not in readme.lower()
    assert "Creative Commons Legal Code" in (PKG / "LICENSE.txt").read_text()
    for name in ["datapackage.json", "dataset-metadata.json", "zenodo.json"]:
        meta = json.loads((PKG / name).read_text())
        assert "chemical database" not in json.dumps(meta).lower(), name
    assert json.loads((PKG / "zenodo.json").read_text())["license"] == "cc-zero"
    assert json.loads((PKG / "dataset-metadata.json").read_text())["licenses"] == [{"name": "CC0-1.0"}]


@pytestmark_built
def test_row_counts_match_the_snapshot_it_was_built_from():
    manifest = json.loads((PKG / "MANIFEST.json").read_text())
    snap = dataset.load_snapshot(SNAPSHOTS)
    if snap["sha"] != manifest["snapshot_sha256"]:
        pytest.skip("the snapshot moved since the dataset was built; `mfetl dataset` rebuilds it")
    rows = manifest["rows"]
    assert rows["molecules"] == len(snap["molecules"])
    assert rows["products"] == len(snap["products"])
    assert rows["product_molecules"] == sum(len(p["molecules"]) for p in snap["products"])
    assert rows["worlds"] == len(snap["worlds"])
    approvals = sum(1 for m in snap["molecules"] if isinstance(m.get("approval"), dict))
    assert rows["licences"] + manifest["withheld"]["licences"] == approvals
    mol_by = {m["slug"]: m for m in snap["molecules"]}
    for r in _csv("molecules.csv"):
        m = mol_by[r["slug"]]
        assert r["name"] == m["title"]
        assert r["molecular_formula"] == (m.get("molecular_formula") or "")
        assert r["description"] == (m.get("description") or "")
        if r["ld50_mg_per_kg"]:
            assert float(r["ld50_mg_per_kg"]) == m["ld50_mg_per_kg"]


# ── the builder, offline ────────────────────────────────────────────────────
def _tox_record(*items: tuple[int, str]) -> dict:
    """A PUG-View Toxicity record: (reference number, string) Information items plus references."""
    refs = {1: "Hazardous Substances Data Bank (HSDB)", 2: "Toxin and Toxin Target Database (T3DB)",
            3: "ChemIDplus"}
    return {"Record": {
        "Section": [{"TOCHeading": "Toxicity", "Section": [{"Information": [
            {"ReferenceNumber": n, "Value": {"StringWithMarkup": [{"String": s}]}} for n, s in items]}]}],
        "Reference": [{"ReferenceNumber": n, "SourceName": name} for n, name in refs.items()],
    }}


def test_ld50_sources_names_only_the_sources_that_say_that_exact_row():
    rec = _tox_record((1, "LD50 Rat oral 192 mg/kg"), (2, "LD50: 192 mg/kg (Oral, Rat)"),
                      (3, "LD50 Mouse oral 127 mg/kg"))
    assert dataset.ld50_sources(rec, 192, "rat", "oral") == [
        "Hazardous Substances Data Bank (HSDB)", "Toxin and Toxin Target Database (T3DB)"]
    assert dataset.ld50_sources(rec, 127, "mouse", "oral") == ["ChemIDplus"]
    assert dataset.ld50_sources(rec, 192, "mouse", "oral") == []
    assert dataset.ld50_sources(None, 192, "rat", "oral") == []


def _mol(slug: str, **kw) -> dict:
    base = {"slug": slug, "title": slug.title(), "cid": 100 + len(slug), "molecular_formula": "C1",
            "molecular_weight": 12.0, "descriptors": {}, "categories": [], "trails": {}, "edges": [],
            "summary": "x", "summary_source": "wikidata", "description": f"{slug} line", "ld50_mg_per_kg": None,
            "cas": "50-00-0", "ghs": None, "synonyms": ["Secret depositor name"]}
    base.update(kw)
    return base


def _snap(mols, products=(), worlds=()):
    return {"molecules": list(mols), "products": list(products), "worlds": list(worlds),
            "refreshed": "2026-10-21", "sha": "x"}


def test_an_ld50_only_t3db_reports_is_withheld_and_counted():
    a = _mol("alpha", cid=1, ld50_mg_per_kg=192, ld50_species="rat", ld50_route="oral")
    b = _mol("beta", cid=2, ld50_mg_per_kg=50, ld50_species="rat", ld50_route="oral")
    tox = {1: _tox_record((1, "LD50 Rat oral 192 mg/kg")), 2: _tox_record((2, "LD50: 50 mg/kg (Oral, Rat)"))}
    build = dataset.build(_snap([a, b]), version="2026.10", inputs=None, tox=lambda cid: tox.get(cid))
    rows = {r["slug"]: r for r in build.tables["molecules"]}
    assert rows["alpha"]["ld50_mg_per_kg"] == 192
    assert rows["alpha"]["ld50_sources"] == "Hazardous Substances Data Bank (HSDB)"
    assert rows["beta"]["ld50_mg_per_kg"] is None and rows["beta"]["ld50_sources"] is None
    assert build.withheld["ld50"] == ["beta"]


def test_a_sweetness_from_an_attribution_source_is_withheld_and_counted():
    """Garrett's ruling (2026-10-28): the credit-required sweetness values (six CC BY articles, EFSA)
    stay out of the CC0 dataset. The FDA's, HSDB's and MeSH's are public domain and stay in; a value
    with no source, or an unknown one, fails closed."""
    fda = _mol("fda-sweet", relative_sweetness=600, relative_sweetness_source="fda")
    hsdb = _mol("hsdb-sweet", relative_sweetness=0.74, relative_sweetness_source="hsdb")
    cc_by = _mol("cc-by-sweet", relative_sweetness=220000, relative_sweetness_source="dragomir_2025")
    efsa = _mol("efsa-sweet", relative_sweetness=250, relative_sweetness_source="efsa")
    bare = _mol("unsourced-sweet", relative_sweetness=1)
    unknown = _mol("unknown-sweet", relative_sweetness=2, relative_sweetness_source="nobody")
    build = dataset.build(_snap([fda, hsdb, cc_by, efsa, bare, unknown]), version="2026.10", inputs=None,
                          tox=lambda cid: None)
    rows = {r["slug"]: r["relative_sweetness"] for r in build.tables["molecules"]}
    assert rows == {"fda-sweet": 600, "hsdb-sweet": 0.74, "cc-by-sweet": None, "efsa-sweet": None,
                    "unsourced-sweet": None, "unknown-sweet": None}
    assert build.withheld["sweetness"] == ["cc-by-sweet", "efsa-sweet", "unsourced-sweet", "unknown-sweet"]
    assert dataset.in_dataset_class("fda") and dataset.in_dataset_class("curated")
    assert not dataset.in_dataset_class("efsa") and not dataset.in_dataset_class(None)


def test_the_committed_snapshots_credit_required_sweetness_values_would_be_withheld():
    """The eight Garrett named: lugduname, fructose, galactose, trehalose, maltose, lactulose,
    glycerol (CC BY) and mogroside V (EFSA)."""
    from moleculefinder_etl.config import SNAPSHOTS
    files = sorted((SNAPSHOTS / "molecules").glob("*.json")) if SNAPSHOTS.exists() else []
    if not files:
        pytest.skip("no snapshot exported yet")
    mols = [json.loads(f.read_text()) for f in files]
    withheld = sorted(m["slug"] for m in mols if dataset.withheld_fields(m))
    assert withheld == ["fructose", "galactose", "glycerol", "lactulose", "lugduname", "maltose", "mogroside-v", "trehalose"]
    kept = [m for m in mols if m.get("relative_sweetness") is not None and not dataset.withheld_fields(m)]
    assert len(kept) == 18 and all(dataset.in_dataset_class(m["relative_sweetness_source"]) for m in kept)


def test_cas_ghs_synonyms_and_hazard_hubs_never_reach_a_row():
    m = _mol("gamma", ghs={"signal_word": "Danger"}, categories=[
        {"slug": "irritant", "name": "Irritant", "kind": "poison"},
        {"slug": "alcohols", "name": "Alcohols", "kind": "functional_group"}])
    build = dataset.build(_snap([m]), version="2026.10", inputs=None, tox=lambda cid: None)
    text = json.dumps(build.tables)
    assert "50-00-0" not in text and "Secret depositor name" not in text and "Danger" not in text
    assert [c["slug"] for c in build.tables["categories"]] == ["alcohols"]
    assert build.withheld["ghs_hubs"] == ["irritant"] and build.withheld["ghs_molecules"] == 1


def test_licences_keep_drugs_at_fda_and_withhold_the_rest():
    fda = _mol("delta", approval={"regulator": "US Food and Drug Administration", "application": "NDA 1",
                                  "source": "https://www.accessdata.fda.gov/scripts/cder/daf/x"})
    mhra = _mol("epsilon", approval={"regulator": "Medicines and Healthcare products Regulatory Agency",
                                     "register": "MHRA Products", "source": "https://products.mhra.gov.uk/x"})
    build = dataset.build(_snap([fda, mhra]), version="2026.10", inputs=None, tox=lambda cid: None)
    assert [r["molecule_slug"] for r in build.tables["licences"]] == ["delta"]
    assert [r["molecule_slug"] for r in build.withheld["licences"]] == ["epsilon"]


def test_counts_are_checked_and_a_hand_modelled_cid_is_blank(tmp_path: Path):
    hm = _mol("starch", cid=-5)
    p = {"slug": "bread", "name": "Bread", "kind": "food", "source": {"type": "curated", "hub": "bread"},
         "listed": 2, "molecules": [{"slug": "starch", "role": "curated"}]}
    w = {"slug": "fresh-bread", "title": "Fresh bread", "blurb": "b", "count": 1}
    hm["trails"] = {"found_in": [{"to": "fresh-bread", "kind": "world"}]}
    snap = _snap([hm], [p], [w])
    build = dataset.build(snap, version="2026.10", inputs=None, tox=lambda cid: None)
    assert dataset.check_counts(build, snap) == []
    assert build.tables["molecules"][0]["pubchem_cid"] is None
    assert build.tables["product_molecules"][0]["matched_by"] == "curated"
    build.tables["products"].append(dict(build.tables["products"][0]))
    assert dataset.check_counts(build, snap)  # a row too many is refused
    manifest = dataset.write(dataset.build(snap, version="2026.10", inputs=None, tox=lambda cid: None), tmp_path / "pkg")
    assert set(manifest["files"]) | {"MANIFEST.json"} == EXPECTED_FILES
    assert manifest["rows"]["molecules"] == 1


def test_run_refuses_a_cache_that_is_not_mains(monkeypatch, tmp_path: Path):
    from moleculefinder_etl import inputs

    def refuse():
        raise inputs.InputsMismatch("not main's cache")
    monkeypatch.setattr(inputs, "verify", refuse)
    with pytest.raises(inputs.InputsMismatch):
        dataset.run(out=tmp_path / "pkg")
    assert not (tmp_path / "pkg").exists()


# ── the published record (2026-10-23): every package carries its DOIs ────────
def test_the_published_record_is_complete():
    p = dataset.published()
    assert p["concept_doi"] == "10.5281/zenodo.23605767"
    assert p["versions"]["2026.10"] == "10.5281/zenodo.23605768"
    assert list(p["versions"].items())[-1] == ("2026.10.1", "10.5281/zenodo.23620892")
    assert p["zenodo_record"] == "https://zenodo.org/records/23620892"
    assert p["kaggle"] == "trommsdorff/moleculefinder-molecules-in-everyday-products"


@pytest.mark.parametrize("text", [
    "concept_doi: ''\nzenodo_record: https://zenodo.org/records/1\nkaggle: a/b\nversions: {'1': 10.5281/zenodo.1}\n",
    "concept_doi: 10.5281/zenodo.1\nzenodo_record: https://zenodo.org/records/1\nkaggle: ''\nversions: {'1': 10.5281/zenodo.1}\n",
    "concept_doi: 10.5281/zenodo.1\nzenodo_record: https://zenodo.org/records/1\nkaggle: a/b\nversions: {}\n",
    "concept_doi: 10.5281/zenodo.1\nzenodo_record: https://zenodo.org/records/1\nkaggle: a/b\nversions: {'1': ''}\n",
    # zenodo_record left on an older version's page
    ("concept_doi: 10.5281/zenodo.1\nzenodo_record: https://zenodo.org/records/2\nkaggle: a/b\n"
     "versions: {'1': 10.5281/zenodo.2, '2': 10.5281/zenodo.3}\n"),
    "",
])
def test_an_empty_doi_field_refuses_the_build(tmp_path, text):
    f = tmp_path / "dataset_published.yaml"
    f.write_text(text)
    with pytest.raises(dataset.Unpublished):
        dataset.published(f)


def test_run_refuses_before_writing_when_a_doi_is_missing(tmp_path, monkeypatch):
    f = tmp_path / "dataset_published.yaml"
    f.write_text("concept_doi: ''\n")
    monkeypatch.setattr(dataset, "PUBLISHED", f)
    monkeypatch.setattr(dataset.published, "__defaults__", (f,))
    out = tmp_path / "out"
    assert dataset.run(out=out) == 1
    assert not out.exists()


def test_the_committed_package_carries_the_dois():
    p = dataset.published()
    readme = (PKG / "README.md").read_text()
    cff = (PKG / "CITATION.cff").read_text()
    zen = json.loads((PKG / "zenodo.json").read_text())
    for doi in [p["concept_doi"], *p["versions"].values()]:
        assert doi in readme and doi in cff
    assert p["kaggle"] in readme and p["zenodo_record"] in readme
    assert p["concept_doi"] in zen["notes"]
    assert json.loads((PKG / "dataset-metadata.json").read_text())["id"] == p["kaggle"]


def test_the_committed_package_cites_the_concept_doi_with_this_version_beside_it():
    p = dataset.published()
    v, doi = list(p["versions"].items())[-1]
    readme = (PKG / "README.md").read_text()
    cite = readme.split("## Citation", 1)[1]
    assert cite.split("\n\n")[1].rstrip().endswith(f"https://doi.org/{p['concept_doi']}")
    assert f"This version {v}, https://doi.org/{doi}." in cite
    assert f'doi: "{p["concept_doi"]}"' in (PKG / "CITATION.cff").read_text()
    zen = json.loads((PKG / "zenodo.json").read_text())
    assert zen["version"] == v and zen["doi"] == doi
    assert f"This version {v}, https://doi.org/{doi}" in zen["notes"]


# ── `mfetl dataset --version V --doi D` records a new version (2026-10-24) ───
_SEED = ("# kept\nconcept_doi: 10.5281/zenodo.1    # concept\nzenodo_record: https://zenodo.org/records/2\n"
         "kaggle: a/b\nversions:\n  \"2026.10\": 10.5281/zenodo.2\n")


def test_recording_a_version_appends_it_as_the_latest(tmp_path):
    f = tmp_path / "dataset_published.yaml"
    f.write_text(_SEED)
    assert dataset.record_version("2026.11", "10.5281/zenodo.9", f) is True
    p = dataset.published(f)
    assert list(p["versions"].items()) == [("2026.10", "10.5281/zenodo.2"), ("2026.11", "10.5281/zenodo.9")]
    assert p["zenodo_record"] == "https://zenodo.org/records/9"
    assert f.read_text().startswith("# kept\n") and "# concept" in f.read_text()
    assert dataset.record_version("2026.11", "10.5281/zenodo.9", f) is False  # again: no change


@pytest.mark.parametrize("version,doi", [
    ("2026.11", "10.1234/other.9"),     # not a Zenodo DOI
    ("2026.11", "10.5281/zenodo.1"),    # the concept DOI
    ("2026.11", "10.5281/zenodo.2"),    # another version's DOI
    ("2026.10", "10.5281/zenodo.9"),    # a version already recorded with another DOI
])
def test_recording_a_wrong_doi_refuses_and_leaves_the_file(tmp_path, version, doi):
    f = tmp_path / "dataset_published.yaml"
    f.write_text(_SEED)
    with pytest.raises(dataset.Unpublished):
        dataset.record_version(version, doi, f)
    assert f.read_text() == _SEED


def test_run_refuses_a_doi_without_a_version(tmp_path):
    out = tmp_path / "out"
    assert dataset.run(out=out, doi="10.5281/zenodo.9") == 1
    assert not out.exists()


def test_a_build_before_upload_names_the_latest_published_version(tmp_path):
    from moleculefinder_etl import dataset_docs
    f = tmp_path / "dataset_published.yaml"
    f.write_text(_SEED)
    b = dataset.Build({}, "2026.11", "2026-11-02", "sha", None, {})
    b.published = dataset.published(f)
    assert dataset_docs.this_version(b) == ("This version 2026.11 (its DOI is minted at upload); "
                                            "latest published version 2026.10, https://doi.org/10.5281/zenodo.2")
    assert dataset_docs.citation(b).endswith("https://doi.org/10.5281/zenodo.1")
    rel = dataset_docs.zenodo(b, {"molecules": 0, "products": 0})["related_identifiers"]
    assert {"identifier": "10.5281/zenodo.2", "relation": "isNewVersionOf",
            "resource_type": "dataset", "scheme": "doi"} in rel
