"""The MoleculeFinder dataset's README, licence and metadata files (growth plan run D), and the
Hugging Face dataset card (the links kit, 2026-10-29).

Rendered by `dataset.write` from the build itself, so every count, column and exclusion in the
README is the one the CSVs carry. The words describe a set of everyday molecules and the products
they are in; per the outreach standing orders, never "a chemical database" and never set beside
PubChem or any other search tool (PubChem is named only as a source).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .dataset import LICENSE_ID, SITE, TABLES, TITLE, Build, withheld_counts

CC0_TEXT = (Path(__file__).with_name("dataset_cc0.txt")).read_text(encoding="utf-8")
CREATOR = "MoleculeFinder (137 Finder LLC)"
SHORT = "The molecules in everyday foods, drinks and products"

KEYWORDS = [
    "chemistry", "molecules", "everyday chemistry", "food chemistry", "consumer products",
    "chemistry education", "cheminformatics", "SMILES", "InChI", "LD50", "Wikidata", "PubChem",
]
KAGGLE_KEYWORDS = ["chemistry", "food", "education", "biology"]

# The Hugging Face card's front matter (https://huggingface.co/docs/hub/datasets-cards and the
# spec it links, hub-docs/datasetcard.md, read 2026-10-29): `license` is the Hub's identifier for
# CC0 1.0 (its repositories-licenses table), `task_categories` come from its pipeline list
# (huggingface.js packages/tasks/src/pipelines.ts), `size_categories` from its buckets, `tags` are
# free text for discovery, and one `configs` entry per table makes the Hub's viewer show each CSV
# as its own subset.
HF_LICENSE = "cc0-1.0"
HF_TASKS = ["tabular-classification", "tabular-regression", "other"]
HF_TAGS = [
    "chemistry", "cheminformatics", "molecules", "everyday-chemistry", "food", "consumer-products",
    "chemistry-education", "toxicology", "ld50", "smiles", "inchi", "pubchem", "wikidata", "tabular",
]
SIZE_CATEGORIES = ["n<1K", "1K<n<10K", "10K<n<100K", "100K<n<1M", "1M<n<10M", "10M<n<100M",
                   "100M<n<1B", "1B<n<10B", "10B<n<100B", "100B<n<1T", "n>1T"]

TABLE_BLURB = {
    "molecules": "one row per molecule",
    "products": "one row per food, drink, product or class page",
    "product_molecules": "which molecules each product lists",
    "categories": "MoleculeFinder's groups, families, food and product hubs, functional groups",
    "molecule_categories": "which molecules each category holds",
    "relationships": "curated molecule-to-molecule links (becomes, affects)",
    "similarity": "structural neighbours (Tanimoto, Morgan fingerprints)",
    "worlds": "the ten everyday worlds",
    "world_molecules": "which molecules each world holds",
    "licences": "the FDA marketing record for each approved medicine (Drugs@FDA)",
}


def _doi_url(doi: str) -> str:
    return f"https://doi.org/{doi}"


def _version_doi(b: Build) -> str | None:
    """This version's own DOI, once it is published (a new version's is minted at upload)."""
    return b.published["versions"].get(b.version)


def _kaggle_url(b: Build) -> str:
    return f"https://www.kaggle.com/datasets/{b.published['kaggle']}"


def _huggingface_id(b: Build) -> str:
    """The Hugging Face dataset repo (owner/name), or "" until Garrett creates it."""
    return b.published.get("huggingface") or ""


def _huggingface_url(b: Build) -> str | None:
    hf = _huggingface_id(b)
    return f"https://huggingface.co/datasets/{hf}" if hf else None


def size_category(rows: int) -> str:
    """The Hub's size bucket for a dataset of `rows` examples. This dataset's examples are the rows
    of all its tables together (the card's `configs` list every table)."""
    limit = 1_000
    for bucket in SIZE_CATEGORIES[:-1]:
        if rows < limit:
            return bucket
        limit *= 10
    return SIZE_CATEGORIES[-1]


def citation(b: Build) -> str:
    """The one citation line (README, and the site's Sources & methodology page says the same). It
    cites the concept DOI, which every version shares, so no new version leaves it stale; the
    version and its own DOI go beside it (`this_version`)."""
    return (f"{CREATOR} ({b.refreshed[:4]}). *{TITLE}* [Data set]. Zenodo. "
            f"{_doi_url(b.published['concept_doi'])}")


def this_version(b: Build) -> str:
    """The line beside the citation: this package's version and its own DOI, or, before Zenodo
    mints that DOI, the latest published version it follows."""
    doi = _version_doi(b)
    if doi:
        return f"This version {b.version}, {_doi_url(doi)}"
    v, d = list(b.published["versions"].items())[-1]
    return f"This version {b.version} (its DOI is minted at upload); latest published version {v}, {_doi_url(d)}"


def _previous_version_doi(b: Build) -> str | None:
    """The DOI of the published version this one follows (the record lists versions oldest first)."""
    vs = list(b.published["versions"])
    before = vs[:vs.index(b.version)] if b.version in vs else vs
    return b.published["versions"][before[-1]] if before else None


def description(b: Build, counts: dict[str, int]) -> str:
    """The plain-text description used on Zenodo and Kaggle."""
    return (
        f"{counts['molecules']:,} molecules from everyday life (coffee, chili, chocolate, sweeteners, "
        f"medicines, cleaning products, PFAS) and the {counts['products']:,} foods, drinks and products "
        f"they are in, from MoleculeFinder ({SITE}). Each molecule carries its PubChem identity and computed "
        "properties (formula, weight, SMILES, InChI, descriptors), its Wikidata item and names, "
        "MoleculeFinder's one-line description and everyday group, and, where a US government source "
        "reports it, one LD50 with species, route and source. Product ingredient lists are read from "
        "DailyMed labels, Wikidata and MoleculeFinder's curated food lists, matched to molecules by code, "
        "never by name. Also included: curated relationships, structural neighbours, the ten everyday "
        "worlds and FDA approval records. Every column states its source; every field is public domain or "
        f"CC0, and the whole dataset is released under CC0 1.0. Snapshot of {b.refreshed}."
    )


# ── the sections the README and the Hugging Face card share ─────────────────
def _files_section(counts: dict[str, int]) -> list[str]:
    return [
        "## Files",
        "",
        "| file | rows | what it holds |",
        "|---|---:|---|",
        *[f"| `{t}.csv` | {counts[t]:,} | {TABLE_BLURB[t]} |" for t in TABLES],
        "| `moleculefinder.json` | | every table above in one JSON file (`tables.<name>` is a list of rows) |",
        "| `MANIFEST.json` | | row counts, file sizes and SHA-256 checksums |",
        "",
        "CSV files are UTF-8 with a header row; an empty cell means no value. Lists inside a cell are",
        "separated by ` | `. Every `*_slug` column joins to the `slug` of the table it names, and every",
        f"slug is a page on the site ({SITE}/m/caffeine, {SITE}/whats-in/coffee).",
        "",
    ]


def _column_dictionary() -> list[str]:
    lines = ["## Column dictionary and provenance", ""]
    for t, cols in TABLES.items():
        lines += [f"### `{t}.csv`", "", "| column | type | description | source |", "|---|---|---|---|"]
        lines += [f"| `{c}` | {ty} | {d} | {src} |" for c, ty, d, src in cols]
        lines.append("")
    return lines


def _sources_section() -> list[str]:
    return [
        "## Sources",
        "",
        "| source | what it supplies | status |",
        "|---|---|---|",
        "| PubChem (NCBI, US National Library of Medicine) | identity and computed properties (formula, weight, SMILES, InChI, descriptors) | US government computations, public domain |",
        "| US government toxicology sources, read through PubChem (HSDB, ChemIDplus, the EPA, the FDA, NIOSH, NTP, ATSDR, USGS, USDA) | the LD50 values kept | public domain (17 U.S.C. 105) |",
        "| Wikidata | items, descriptions, other names | CC0 |",
        "| Wikimedia Pageviews | monthly page views | CC0 |",
        "| DailyMed (US National Library of Medicine) | product labels: ingredients, roles, purposes | public domain |",
        "| Drugs@FDA | FDA approval records | public domain |",
        "| RDKit | similarity fingerprints, functional groups | BSD software; the outputs are facts |",
        "| MoleculeFinder (137 Finder LLC) | descriptions, groups, hubs, product lists, worlds, relationships | released CC0 1.0 in this dataset |",
        "",
    ]


def _exclusions_section(w: dict[str, int], hub_names: list[str] | None) -> list[str]:
    """What is left out and why. `w` is the manifest's count per kind; `hub_names` are the hazard
    hubs by name when the build has them (a card rewritten from the manifest alone has the count)."""
    hubs = f" ({', '.join(hub_names)})" if hub_names else ""
    return [
        "## What is not in the dataset, and why",
        "",
        "The dataset is CC0, so it carries only fields whose sources are public domain or CC0. Where a",
        "source asks for attribution, restricts reuse, or its terms could not be confirmed, the field is",
        "left out, even though MoleculeFinder's pages show it with the source named.",
        "",
        f"- **GHS hazard classification** (signal word, pictograms, H-statements; on {w['ghs_molecules']:,} molecules on the",
        f"  site) and the {w['ghs_hubs']} hazard categories built from it{hubs}. PubChem",
        "  aggregates it from the European Chemicals Agency's C&L Inventory and EUR-Lex (reuse with the source",
        "  acknowledged) and Safe Work Australia (CC BY 4.0); the site shows it with that attribution, which a",
        "  CC0 release cannot carry. Japan's NITE classifications are used nowhere (NITE reserves publication).",
        *(([f"- **{w['ld50']} LD50 values** that no US government source reports in PubChem's record (their",
            "  only sources are, for example, T3DB (non-commercial terms), Haz-Map (all rights reserved),",
            "  StatPearls (CC BY-NC), the ILO-WHO cards (CC BY) or EFSA (source acknowledged)). Those rows keep",
            "  the molecule and leave the four LD50 columns empty. Every LD50 that is kept names its sources."])
          if w["ld50"] else
          ["- **LD50 values from sources that are not US government works.** None is withheld: since",
           "  2026-10-23 MoleculeFinder shows an LD50 only from a source whose terms allow it, and every LD50",
           "  on the site is a US government value, so the dataset's LD50 columns match the site's. Every",
           "  LD50 kept names its sources."]),
        f"- **{w['licences']} licence records** from the MHRA (Open Government Licence, attribution), the",
        "  European Medicines Agency (reproduction with the source acknowledged) and national registers",
        "  (Italy's AIFA, Latvia's medicines agency). Drugs@FDA records are kept.",
        *([f"- **{w['sweetness']} relative sweetness values** whose source asks for attribution (open-access",
           "  CC BY articles, the EFSA Journal). The site shows each with its credit; here the cell is blank, and",
           "  the values kept come from the FDA, HSDB and MeSH (public domain)."]
          if w.get("sweetness") else []),
        "- **CAS Registry Numbers.** The CAS Registry is maintained by the American Chemical Society, which",
        "  requires a licence to publish its numbers; since 2026-10-23 neither the site nor the dataset",
        "  carries them. Each row carries the PubChem CID, InChIKey and Wikidata QID instead.",
        "- **PubChem synonyms.** Depositors supply them under their own terms; the dataset's names come from",
        "  Wikidata (`other_names`) and MoleculeFinder's curated brand list.",
        "- **Serving sizes**, a dosing figure, which MoleculeFinder keeps out of anything it publishes as data.",
        "- **Prose that is not a structured field**: the written comparisons, the short answers, and the",
        "  structure drawings (SMILES and InChI carry the structure).",
        "",
    ]


def _notes_section() -> list[str]:
    return [
        "## Notes",
        "",
        "- An LD50 is an animal study measurement, not a dose for a person. Nothing here is medical advice.",
        "- Product names are used only to name the products. Ingredient lists are the labels' own; a",
        "  product lists only the ingredients that are MoleculeFinder molecules (`ingredients_listed` is",
        "  the label's full count).",
        "- Ingredients are matched to molecules by code (a label's UNII, its active moiety, PubChem's parent",
        "  compound for a salt or hydrate, a Wikidata QID), never by name.",
        "",
    ]


def _citation_links(b: Build) -> list[str]:
    hf = _huggingface_url(b)
    return [
        f"- Every version (always the latest): {_doi_url(b.published['concept_doi'])}",
        *[f"- Version {v}: {_doi_url(d)}" for v, d in b.published["versions"].items()],
        f"- Zenodo: {b.published['zenodo_record']}",
        f"- Kaggle: {_kaggle_url(b)}",
        *([f"- Hugging Face: {hf}"] if hf else []),
        f"- Website: {SITE}/about/methodology",
    ]


def _hub_names(b: Build) -> list[str] | None:
    hubs = b.withheld.get("ghs_hubs")
    return hubs if isinstance(hubs, list) else None


def readme(b: Build, counts: dict[str, int]) -> str:
    lines = [
        f"# {TITLE}",
        "",
        f"{SHORT}, with their structures, properties and the products that list them, from",
        f"[MoleculeFinder]({SITE}). Released under **CC0 1.0** (public domain dedication): use it for",
        "anything, no permission or credit needed. A citation is welcome (below).",
        "",
        "| | |",
        "|---|---|",
        f"| **Version** | {b.version} |",
        f"| **Snapshot** | MoleculeFinder data of {b.refreshed} |",
        f"| **Molecules** | {counts['molecules']:,} |",
        f"| **Products** | {counts['products']:,} |",
        "| **Licence** | CC0 1.0 (`LICENSE.txt`) |",
        f"| **Website** | {SITE} |",
        "",
        *_files_section(counts),
        *_column_dictionary(),
        *_sources_section(),
        *_exclusions_section(withheld_counts(b.withheld), _hub_names(b)),
        *_notes_section(),
        "## Citation",
        "",
        citation(b),
        "",
        this_version(b) + ".",
        "",
        *_citation_links(b),
        "",
        "## Rebuilding",
        "",
        "`mfetl dataset` in the MoleculeFinder ETL rebuilds this folder from the site's snapshot, checks",
        "every table's row count against it, and writes the checksums in `MANIFEST.json`.",
        "",
    ]
    return "\n".join(lines)


def bibtex(b: Build) -> list[str]:
    """The citation as BibTeX, for the Hugging Face card (the Hub renders a `bibtex` block and
    offers it under "Cite")."""
    return [
        "```bibtex",
        f"@dataset{{moleculefinder_{b.refreshed[:4]},",
        f"  author    = {{{{{CREATOR}}}}},",
        f"  title     = {{{TITLE}}},",
        f"  year      = {{{b.refreshed[:4]}}},",
        "  publisher = {Zenodo},",
        f"  doi       = {{{b.published['concept_doi']}}},",
        f"  url       = {{{_doi_url(b.published['concept_doi'])}}},",
        f"  note      = {{{this_version(b)}}}",
        "}",
        "```",
    ]


def huggingface_card(b: Build, counts: dict[str, int]) -> str:
    """The Hugging Face dataset card: a README.md with the Hub's YAML front matter over the same
    facts as the package README (links kit, 2026-10-29). Written beside the package as
    `huggingface/README.md`, outside the manifest, because on the Hub it replaces the package
    README as the repo's README.md and is not a file of the Zenodo or Kaggle record. Garrett
    uploads it himself; nothing here talks to the Hub."""
    w = withheld_counts(b.withheld)
    total = sum(counts[t] for t in TABLES)
    hf_id, hf_url = _huggingface_id(b), _huggingface_url(b)
    concept = _doi_url(b.published["concept_doi"])
    front = [
        "---",
        f'pretty_name: "{TITLE}"',
        f"license: {HF_LICENSE}",
        "language:",
        "- en",
        "size_categories:",
        f"- {size_category(total)}",
        "task_categories:",
        *[f"- {t}" for t in HF_TASKS],
        "tags:",
        *[f"- {t}" for t in HF_TAGS],
        "configs:",
    ]
    for i, t in enumerate(TABLES):
        front += [f"- config_name: {t}", *(["  default: true"] if i == 0 else []),
                  "  data_files:", "  - split: train", f"    path: {t}.csv"]
    front.append("---")
    loading = ["## Loading", ""]
    if hf_id:
        loading += [
            "```python",
            "from datasets import load_dataset",
            "",
            f'molecules = load_dataset("{hf_id}", "molecules")["train"]',
            f'in_products = load_dataset("{hf_id}", "product_molecules")["train"]',
            "```",
            "",
            "Each table is its own subset, named as its CSV file (the `configs` above). Or read the files directly:",
            "",
        ]
    loading += [
        "```python",
        "import pandas as pd",
        "",
        'molecules = pd.read_csv("molecules.csv")',
        'in_products = pd.read_csv("product_molecules.csv").merge(',
        '    pd.read_csv("products.csv"), left_on="product_slug", right_on="slug")',
        "```",
        "",
    ]
    body = [
        f"# Dataset Card for {TITLE}",
        "",
        f"{SHORT}, with their structures, properties and the products that list them, from",
        f"[MoleculeFinder]({SITE}). Released under **CC0 1.0** (public domain dedication): use it for",
        "anything, no permission or credit needed. A citation is welcome (below).",
        "",
        f"This is the Hugging Face copy of the dataset published on [Zenodo]({concept}), its home and the",
        f"DOI to cite, and mirrored on [Kaggle]({_kaggle_url(b)}); the data files are the same.",
        "",
        "## Dataset details",
        "",
        "| | |",
        "|---|---|",
        f"| **Version** | {b.version} |",
        f"| **Snapshot** | MoleculeFinder data of {b.refreshed} |",
        f"| **Molecules** | {counts['molecules']:,} |",
        f"| **Products** | {counts['products']:,} |",
        f"| **Rows in all tables** | {total:,} |",
        "| **Licence** | CC0 1.0 (`LICENSE.txt`) |",
        f"| **Website** | {SITE} |",
        f"| **Methodology** | {SITE}/about/methodology |",
        f"| **Zenodo** | {b.published['zenodo_record']} |",
        f"| **Kaggle** | {_kaggle_url(b)} |",
        *([f"| **Hugging Face** | {hf_url} |"] if hf_url else []),
        "",
        *_files_section(counts),
        *loading,
        *_column_dictionary(),
        *_sources_section(),
        *_exclusions_section(w, _hub_names(b)),
        *_notes_section(),
        "## Citation",
        "",
        citation(b),
        "",
        this_version(b) + ".",
        "",
        *bibtex(b),
        "",
        *_citation_links(b),
        "",
        "## Rebuilding",
        "",
        "`mfetl dataset` in the MoleculeFinder ETL rebuilds the package from the site's snapshot and writes",
        "this card beside it as `huggingface/README.md`; `mfetl dataset --card` rewrites the card alone from",
        "the package's `MANIFEST.json`.",
        "",
    ]
    return "\n".join(front + [""] + body)


def cff(b: Build) -> str:
    hf = _huggingface_url(b)
    return "\n".join([
        "cff-version: 1.2.0",
        'message: "If you use this data, please cite it as below."',
        f'title: "{TITLE}"',
        "abstract: >-",
        f"  {SHORT}: molecules with their PubChem identity and properties, Wikidata items and names,",
        "  MoleculeFinder's descriptions and groups, LD50 values from US government sources, and the",
        "  foods, drinks and products that list them. CC0 1.0.",
        "type: dataset",
        "authors:",
        '  - name: "MoleculeFinder"',
        '    alias: "137 Finder LLC"',
        f'version: "{b.version}"',
        f'date-released: "{b.refreshed}"',
        f"license: {LICENSE_ID}",
        f'url: "{SITE}"',
        f'doi: "{b.published["concept_doi"]}"',
        f'repository: "{b.published["zenodo_record"]}"',
        "identifiers:",
        "  - type: doi",
        f'    value: "{b.published["concept_doi"]}"',
        '    description: "Every version (Zenodo concept DOI, always the latest)"',
        *[line for v, d in b.published["versions"].items() for line in (
            "  - type: doi", f'    value: "{d}"', f'    description: "Version {v}"')],
        "  - type: url",
        f'    value: "{_kaggle_url(b)}"',
        '    description: "Kaggle copy"',
        *(["  - type: url", f'    value: "{hf}"', '    description: "Hugging Face copy"'] if hf else []),
        "keywords:",
        *[f"  - {k}" for k in KEYWORDS],
        "",
    ])


def datapackage(b: Build, counts: dict[str, int]) -> dict[str, Any]:
    return {
        "$schema": "https://datapackage.org/profiles/2.0/datapackage.json",
        "name": "moleculefinder",
        "title": TITLE,
        "description": description(b, counts),
        "version": b.version,
        "created": b.refreshed,
        "homepage": SITE,
        "keywords": KEYWORDS,
        "licenses": [{"name": LICENSE_ID, "title": "CC0 1.0 Universal",
                      "path": "https://creativecommons.org/publicdomain/zero/1.0/"}],
        "contributors": [{"title": "MoleculeFinder", "organization": "137 Finder LLC", "roles": ["author", "maintainer"]}],
        "resources": [
            {"name": t, "path": f"{t}.csv", "format": "csv", "mediatype": "text/csv", "encoding": "utf-8",
             "dialect": {"delimiter": ",", "header": True, "lineTerminator": "\n"},
             "schema": {"missingValues": [""],
                        "fields": [{"name": c, "type": ty, "description": f"{d} Source: {src}."} for c, ty, d, src in cols]}}
            for t, cols in TABLES.items()
        ],
    }


def kaggle(b: Build, counts: dict[str, int]) -> dict[str, Any]:
    return {
        "title": "MoleculeFinder: Molecules in Everyday Products",
        "id": b.published["kaggle"],
        "subtitle": f"{counts['molecules']} molecules, {counts['products']} foods, drinks and products, CC0",
        "description": description(b, counts) + "\n\nColumn dictionary and provenance: README.md. "
                       + f"Website: {SITE}. Cite: {_doi_url(b.published['concept_doi'])}",
        "licenses": [{"name": "CC0-1.0"}],
        "keywords": KAGGLE_KEYWORDS,
        "resources": [
            {"path": f"{t}.csv", "description": f"{TABLE_BLURB[t].capitalize()} ({counts[t]:,} rows).",
             "schema": {"fields": [{"name": c, "type": "number" if ty in ("number", "integer") else ty,
                                     "description": d} for c, ty, d, _ in cols]}}
            for t, cols in TABLES.items()
        ] + [{"path": "moleculefinder.json", "description": "Every table in one JSON file."}],
    }


def zenodo(b: Build, counts: dict[str, int]) -> dict[str, Any]:
    """Zenodo's deposit metadata, the same fields the upload form asks for (kept for the record and
    for an API upload later; this repository never uploads)."""
    hf = _huggingface_url(b)
    return {
        "upload_type": "dataset",
        "title": TITLE,
        "creators": [{"name": "MoleculeFinder", "affiliation": "137 Finder LLC"}],
        "description": description(b, counts),
        "version": b.version,
        "publication_date": b.refreshed,
        "access_right": "open",
        "license": "cc-zero",
        "keywords": KEYWORDS,
        "language": "eng",
        "related_identifiers": [
            {"identifier": SITE, "relation": "isDocumentedBy", "resource_type": "other"},
            {"identifier": _kaggle_url(b), "relation": "isIdenticalTo", "resource_type": "dataset"},
            *([{"identifier": hf, "relation": "isIdenticalTo", "resource_type": "dataset"}] if hf else []),
            # The version this one follows; Zenodo mints this one's own DOI under the same concept
            # DOI when it is uploaded with "New version".
            *[{"identifier": d, "relation": "isNewVersionOf", "resource_type": "dataset", "scheme": "doi"}
              for d in [_previous_version_doi(b)] if d],
        ],
        # Zenodo deposit fields only: `doi` is set for a version already published (its own DOI);
        # the concept DOI travels in `notes`, which the form shows as "Additional notes".
        **({"doi": _version_doi(b)} if _version_doi(b) else {}),
        "notes": (f"Cite all versions: {_doi_url(b.published['concept_doi'])}. {this_version(b)}. "
                  f"Kaggle copy: {_kaggle_url(b)}."
                  + (f" Hugging Face copy: {hf}." if hf else "")),
    }


def render(b: Build, counts: dict[str, int]) -> dict[str, str]:
    """The package's own documents (the files Garrett drags into Zenodo and Kaggle). The Hugging
    Face card is rendered separately by `huggingface_card` and written outside the manifest."""
    dump = lambda v: json.dumps(v, indent=2, ensure_ascii=False) + "\n"
    return {
        "README.md": readme(b, counts),
        "LICENSE.txt": CC0_TEXT,
        "CITATION.cff": cff(b),
        "datapackage.json": dump(datapackage(b, counts)),
        "dataset-metadata.json": dump(kaggle(b, counts)),
        "zenodo.json": dump(zenodo(b, counts)),
    }
