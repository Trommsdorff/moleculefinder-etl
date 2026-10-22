"""The MoleculeFinder dataset's README, licence and metadata files (growth plan run D).

Rendered by `dataset.write` from the build itself, so every count, column and exclusion in the
README is the one the CSVs carry. The words describe a set of everyday molecules and the products
they are in; per the outreach standing orders, never "a chemical database" and never set beside
PubChem or any other search tool (PubChem is named only as a source).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .dataset import KAGGLE_ID, LICENSE_ID, SITE, TABLES, TITLE, Build

CC0_TEXT = (Path(__file__).with_name("dataset_cc0.txt")).read_text(encoding="utf-8")
CREATOR = "MoleculeFinder (137 Finder LLC)"
SHORT = "The molecules in everyday foods, drinks and products"

KEYWORDS = [
    "chemistry", "molecules", "everyday chemistry", "food chemistry", "consumer products",
    "chemistry education", "cheminformatics", "SMILES", "InChI", "LD50", "Wikidata", "PubChem",
]
KAGGLE_KEYWORDS = ["chemistry", "food", "education", "biology"]

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


def readme(b: Build, counts: dict[str, int]) -> str:
    w = b.withheld
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
        "## Column dictionary and provenance",
        "",
    ]
    for t, cols in TABLES.items():
        lines += [f"### `{t}.csv`", "", "| column | type | description | source |", "|---|---|---|---|"]
        lines += [f"| `{c}` | {ty} | {d} | {src} |" for c, ty, d, src in cols]
        lines.append("")
    lines += [
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
        "## What is not in the dataset, and why",
        "",
        "The dataset is CC0, so it carries only fields whose sources are public domain or CC0. Where a",
        "source asks for attribution, restricts reuse, or its terms could not be confirmed, the field is",
        "left out, even though MoleculeFinder's pages show it with the source named.",
        "",
        f"- **GHS hazard classification** (signal word, pictograms, H-statements; on {w['ghs_molecules']:,} molecules on the",
        f"  site) and the {len(w['ghs_hubs'])} hazard categories built from it ({', '.join(w['ghs_hubs'])}). PubChem",
        "  aggregates it mostly from the European Chemicals Agency's C&L Inventory, whose legal notice permits",
        "  reuse with the source acknowledged, and from Japan's NITE, Safe Work Australia and EUR-Lex, each",
        "  with its own terms.",
        f"- **{len(w['ld50'])} LD50 values** that no US government source reports in PubChem's record (their",
        "  only sources are, for example, T3DB (non-commercial terms), Haz-Map (all rights reserved),",
        "  StatPearls (CC BY-NC), the ILO-WHO cards (CC BY) or EFSA (source acknowledged)). Those rows keep",
        "  the molecule and leave the four LD50 columns empty. Every LD50 that is kept names its sources.",
        f"- **{len(w['licences'])} licence records** from the MHRA (Open Government Licence, attribution), the",
        "  European Medicines Agency (reproduction with the source acknowledged) and national registers",
        "  (Italy's AIFA, Latvia's medicines agency). Drugs@FDA records are kept.",
        f"- **CAS Registry Numbers** ({w['cas_numbers']:,} on the site). The CAS Registry is maintained by the",
        "  American Chemical Society, whose terms govern redistributing its numbers in bulk. Each row",
        "  carries the PubChem CID, InChIKey and Wikidata QID instead.",
        "- **PubChem synonyms.** Depositors supply them under their own terms; the dataset's names come from",
        "  Wikidata (`other_names`) and MoleculeFinder's curated brand list.",
        "- **Serving sizes**, a dosing figure, which MoleculeFinder keeps out of anything it publishes as data.",
        "- **Prose that is not a structured field**: the written comparisons, the short answers, and the",
        "  structure drawings (SMILES and InChI carry the structure).",
        "",
        "## Notes",
        "",
        "- An LD50 is an animal study measurement, not a dose for a person. Nothing here is medical advice.",
        "- Product names are used only to name the products. Ingredient lists are the labels' own; a",
        "  product lists only the ingredients that are MoleculeFinder molecules (`ingredients_listed` is",
        "  the label's full count).",
        "- Ingredients are matched to molecules by code (a label's UNII, its active moiety, PubChem's parent",
        "  compound for a salt or hydrate, a Wikidata QID), never by name.",
        "",
        "## Citation",
        "",
        f"{CREATOR} ({b.refreshed[:4]}). *{TITLE}* (Version {b.version}) [Data set]. {SITE}",
        "",
        "The Zenodo DOI is added on the site's Sources & methodology page once it is minted.",
        "",
        "## Rebuilding",
        "",
        "`mfetl dataset` in the MoleculeFinder ETL rebuilds this folder from the site's snapshot, checks",
        "every table's row count against it, and writes the checksums in `MANIFEST.json`.",
        "",
    ]
    return "\n".join(lines)


def cff(b: Build) -> str:
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
        "id": KAGGLE_ID,
        "subtitle": f"{counts['molecules']} molecules, {counts['products']} foods, drinks and products, CC0",
        "description": description(b, counts) + "\n\nColumn dictionary and provenance: README.md. " + f"Website: {SITE}",
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
        "related_identifiers": [{"identifier": SITE, "relation": "isDocumentedBy", "resource_type": "other"}],
    }


def render(b: Build, counts: dict[str, int]) -> dict[str, str]:
    dump = lambda v: json.dumps(v, indent=2, ensure_ascii=False) + "\n"
    return {
        "README.md": readme(b, counts),
        "LICENSE.txt": CC0_TEXT,
        "CITATION.cff": cff(b),
        "datapackage.json": dump(datapackage(b, counts)),
        "dataset-metadata.json": dump(kaggle(b, counts)),
        "zenodo.json": dump(zenodo(b, counts)),
    }
