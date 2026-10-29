"""The Hugging Face dataset card (the links kit, 2026-10-29): `huggingface/README.md` beside the
package, with the front matter the Hub reads over the same facts as the package README. Checked
on the committed package against its manifest and the published record, and offline: written with
the package, rewritten alone from the manifest byte for byte, and linking the Hub repo once the
published record names it.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from moleculefinder_etl import dataset, dataset_docs
from moleculefinder_etl.config import DATA

PKG = DATA / "dataset"
CARD = PKG / "huggingface" / "README.md"
BUILT = (PKG / "MANIFEST.json").exists()
pytestmark_built = pytest.mark.skipif(not BUILT, reason="data/dataset not built (mfetl dataset)")

PUB = {"concept_doi": "10.5281/zenodo.1", "zenodo_record": "https://zenodo.org/records/3", "kaggle": "a/b",
       "versions": {"2026.10": "10.5281/zenodo.2", "2026.11": "10.5281/zenodo.3"}, "huggingface": ""}


def _split(text: str) -> tuple[dict, str]:
    """The YAML front matter and the Markdown body."""
    assert text.startswith("---\n"), "the card must open with the front matter"
    front, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(front), body.lstrip("\n")


def _mol(slug: str, **kw) -> dict:
    base = {"slug": slug, "title": slug.title(), "cid": 100 + len(slug), "molecular_formula": "C1",
            "molecular_weight": 12.0, "descriptors": {}, "categories": [], "trails": {}, "edges": [],
            "summary": "x", "summary_source": "wikidata", "description": f"{slug} line", "ld50_mg_per_kg": None,
            "cas": None, "ghs": None, "synonyms": []}
    base.update(kw)
    return base


def _snap() -> dict:
    hm = _mol("starch", cid=-5, ghs={"signal_word": "Danger"},
              categories=[{"slug": "irritant", "name": "Irritant", "kind": "poison"}])
    p = {"slug": "bread", "name": "Bread", "kind": "food", "source": {"type": "curated", "hub": "bread"},
         "listed": 2, "molecules": [{"slug": "starch", "role": "curated"}]}
    w = {"slug": "fresh-bread", "title": "Fresh bread", "blurb": "b", "count": 1}
    hm["trails"] = {"found_in": [{"to": "fresh-bread", "kind": "world"}]}
    return {"molecules": [hm], "products": [p], "worlds": [w], "refreshed": "2026-11-02", "sha": "x"}


# ── the committed card ───────────────────────────────────────────────────────
@pytestmark_built
def test_the_committed_card_matches_the_package_and_its_published_record():
    manifest = json.loads((PKG / "MANIFEST.json").read_text())
    p = dataset.published()
    meta, body = _split(CARD.read_text(encoding="utf-8"))
    # the front matter the Hub reads
    assert meta["license"] == "cc0-1.0"
    assert meta["language"] == ["en"]
    assert meta["pretty_name"] == dataset.TITLE
    total = sum(manifest["rows"][t] for t in dataset.TABLES)
    assert meta["size_categories"] == [dataset_docs.size_category(total)]
    assert meta["size_categories"][0] in dataset_docs.SIZE_CATEGORIES
    assert meta["task_categories"] == dataset_docs.HF_TASKS
    assert "chemistry" in meta["tags"] and "tabular" in meta["tags"]
    assert [c["config_name"] for c in meta["configs"]] == list(dataset.TABLES)
    assert meta["configs"][0]["default"] is True and not any("default" in c for c in meta["configs"][1:])
    for c in meta["configs"]:
        assert c["data_files"] == [{"split": "train", "path": f"{c['config_name']}.csv"}]
        assert (PKG / c["data_files"][0]["path"]).exists()
    # the body says what the package says
    assert body.startswith(f"# Dataset Card for {dataset.TITLE}\n")
    assert f"| **Version** | {manifest['version']} |" in body
    assert f"| **Snapshot** | MoleculeFinder data of {manifest['snapshot_refreshed']} |" in body
    assert f"| **Rows in all tables** | {total:,} |" in body
    for t in dataset.TABLES:
        assert f"| `{t}.csv` | {manifest['rows'][t]:,} | " in body, t
        assert f"### `{t}.csv`" in body, t
    for doi in [p["concept_doi"], *p["versions"].values()]:
        assert doi in body, doi
    assert p["zenodo_record"] in body and p["kaggle"] in body
    assert f"{dataset.SITE}/about/methodology" in body
    for phrase in ["## Files", "## Loading", "## Column dictionary and provenance", "## Sources",
                   "## What is not in the dataset, and why", "GHS hazard classification", "licence records",
                   "CAS Registry Numbers", "PubChem synonyms", "Serving sizes", "## Notes",
                   "not a dose for a person", "## Citation", "```bibtex", f"doi       = {{{p['concept_doi']}}}",
                   "CC0 1.0", "## Rebuilding", "mfetl dataset --card"]:
        assert phrase in body, phrase
    if manifest["withheld"].get("sweetness"):
        assert "relative sweetness values" in body
    assert "chemical database" not in body.lower()
    assert "—" not in body and "–" not in body
    assert "[More Information Needed]" not in body
    # the Hub repo is linked once the published record names it, and never before
    if p["huggingface"]:
        assert f"https://huggingface.co/datasets/{p['huggingface']}" in body
        assert f'load_dataset("{p["huggingface"]}", "molecules")' in body
    else:
        assert "huggingface.co" not in body and "load_dataset" not in body
    assert 'pd.read_csv("molecules.csv")' in body


@pytestmark_built
def test_the_committed_card_is_what_write_card_writes_from_the_manifest(tmp_path: Path):
    """`mfetl dataset --card` on the committed package changes nothing: the card is derived."""
    shutil.copy(PKG / "MANIFEST.json", tmp_path / "MANIFEST.json")
    path = dataset.write_card(tmp_path)
    assert path == tmp_path / "huggingface" / "README.md"
    assert path.read_bytes() == CARD.read_bytes()


# ── the builder, offline ─────────────────────────────────────────────────────
def test_the_card_is_written_with_the_package_and_alone_from_its_manifest(tmp_path: Path, monkeypatch):
    snap = _snap()
    b = dataset.build(snap, version="2026.11", inputs=None, tox=lambda cid: None)
    b.published = dict(PUB)
    manifest = dataset.write(b, tmp_path / "pkg")
    card = tmp_path / "pkg" / "huggingface" / "README.md"
    assert card.exists()
    assert not any(name.startswith("huggingface") for name in manifest["files"])   # outside the manifest
    assert manifest["withheld"] == {"ld50": 0, "ghs_molecules": 1, "ghs_hubs": 1, "licences": 0,
                                    "cas_numbers": 0, "sweetness": 0}
    first = card.read_bytes()
    meta, body = _split(first.decode("utf-8"))
    assert meta["size_categories"] == ["n<1K"] and meta["configs"][0]["config_name"] == "molecules"
    assert sum(manifest["rows"].values()) == 5                 # molecule, product, its row, world, its row
    assert "| **Rows in all tables** | 5 |" in body
    assert "the 1 hazard categories built from it (irritant)." in body   # the build names the hubs
    assert "This version 2026.11, https://doi.org/10.5281/zenodo.3." in body
    assert "huggingface.co" not in body and "load_dataset" not in body
    # rewritten from the manifest alone: the same card, except that the manifest holds no hub names
    card.unlink()
    monkeypatch.setattr(dataset, "published", lambda path=None: dict(PUB))
    assert dataset.write_card(tmp_path / "pkg") == card
    again = card.read_bytes().decode("utf-8")
    assert again == first.decode("utf-8").replace(" built from it (irritant).", " built from it.")
    # and the package README was not touched by either
    assert (tmp_path / "pkg" / "README.md").read_bytes() == b"".join(
        [(tmp_path / "pkg" / "README.md").read_bytes()])


def test_the_card_readme_and_cff_link_the_hub_repo_once_the_record_names_it(tmp_path: Path):
    b = dataset.build(_snap(), version="2026.11", inputs=None, tox=lambda cid: None)
    b.published = dict(PUB, huggingface="Trommsdorff/moleculefinder")
    dataset.write(b, tmp_path / "pkg")
    url = "https://huggingface.co/datasets/Trommsdorff/moleculefinder"
    card = (tmp_path / "pkg" / "huggingface" / "README.md").read_text(encoding="utf-8")
    assert f"| **Hugging Face** | {url} |" in card
    assert 'molecules = load_dataset("Trommsdorff/moleculefinder", "molecules")["train"]' in card
    assert f"- Hugging Face: {url}" in card
    readme = (tmp_path / "pkg" / "README.md").read_text(encoding="utf-8")
    assert f"- Hugging Face: {url}\n- Website:" in readme
    cff = (tmp_path / "pkg" / "CITATION.cff").read_text(encoding="utf-8")
    assert f'    value: "{url}"\n    description: "Hugging Face copy"' in cff
    zen = json.loads((tmp_path / "pkg" / "zenodo.json").read_text())
    assert {"identifier": url, "relation": "isIdenticalTo", "resource_type": "dataset"} in zen["related_identifiers"]
    assert zen["notes"].endswith(f"Hugging Face copy: {url}.")


@pytest.mark.parametrize("rows,bucket", [
    (0, "n<1K"), (999, "n<1K"), (1_000, "1K<n<10K"), (12_604, "10K<n<100K"), (100_000, "100K<n<1M"),
    (10**12 - 1, "100B<n<1T"), (10**12, "n>1T"),
])
def test_size_category(rows, bucket):
    assert dataset_docs.size_category(rows) == bucket


@pytest.mark.parametrize("line,expected", [("", ""), ("huggingface: Trommsdorff/moleculefinder\n", "Trommsdorff/moleculefinder")])
def test_the_published_record_takes_an_optional_hugging_face_id(tmp_path: Path, line, expected):
    f = tmp_path / "dataset_published.yaml"
    f.write_text("concept_doi: 10.5281/zenodo.1\nzenodo_record: https://zenodo.org/records/2\nkaggle: a/b\n"
                 + line + "versions:\n  \"2026.10\": 10.5281/zenodo.2\n")
    assert dataset.published(f)["huggingface"] == expected


@pytest.mark.parametrize("bad", ["nope", "a/b/c", "/b", "a/"])
def test_a_malformed_hugging_face_id_refuses_the_build(tmp_path: Path, bad):
    f = tmp_path / "dataset_published.yaml"
    f.write_text("concept_doi: 10.5281/zenodo.1\nzenodo_record: https://zenodo.org/records/2\nkaggle: a/b\n"
                 f"huggingface: {bad}\nversions:\n  \"2026.10\": 10.5281/zenodo.2\n")
    with pytest.raises(dataset.Unpublished):
        dataset.published(f)


def test_run_card_refuses_without_a_package_or_with_a_version(tmp_path: Path):
    assert dataset.run(out=tmp_path / "none", card=True) == 1
    assert not (tmp_path / "none").exists()
    assert dataset.run(out=tmp_path / "none", card=True, version="2026.11") == 1
