"""Provenance registry + the license firewall.

The registry seeds the `source` table and, crucially, enforces the one rule the
whole ad-supported model depends on: never ingest non-commercial data. Any code
path that tries to attach a BLOCKED source to a row raises immediately.
"""
from __future__ import annotations

# key -> row for the `source` table
SOURCES: dict[str, dict] = {
    "pubchem":  dict(name="PubChem", license="Public Domain",
                     license_url="https://www.ncbi.nlm.nih.gov/home/about/policies/",
                     homepage="https://pubchem.ncbi.nlm.nih.gov/",
                     commercial_ok=True, attribution_required=False),
    "wikidata": dict(name="Wikidata", license="CC0",
                     license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                     homepage="https://www.wikidata.org/",
                     commercial_ok=True, attribution_required=False),
    "rdkit":    dict(name="RDKit", license="BSD-3-Clause",
                     license_url="https://github.com/rdkit/rdkit/blob/master/license.txt",
                     homepage="https://www.rdkit.org/",
                     commercial_ok=True, attribution_required=False),
    "wikimedia_pageviews": dict(name="Wikimedia Pageviews", license="CC0",
                     license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                     homepage="https://wikimedia.org/api/rest_v1/",
                     commercial_ok=True, attribution_required=False),
    "curated":  dict(name="MoleculeFinder curated", license="curated",
                     license_url=None, homepage=None,
                     commercial_ok=True, attribution_required=False),
    "epa_comptox": dict(name="EPA CompTox", license="US Government Public Domain",
                     license_url="https://www.epa.gov/", homepage="https://comptox.epa.gov/",
                     commercial_ok=True, attribution_required=False),
    # Licence records (run B2, moleculefinder_etl/licences.py), read from the regulators' own data.
    "drugs_at_fda": dict(name="Drugs@FDA", license="US Government Public Domain",
                     license_url="https://www.fda.gov/about-fda/about-website/website-policies",
                     homepage="https://www.fda.gov/drugs/drug-approvals-and-databases/drugsfda-data-files",
                     commercial_ok=True, attribution_required=False),
    "ema":      dict(name="European Medicines Agency", license="Reproduction authorised, source acknowledged",
                     license_url="https://www.ema.europa.eu/en/about-us/legal-notice",
                     homepage="https://www.ema.europa.eu/en/medicines/download-medicine-data",
                     commercial_ok=True, attribution_required=True),
    "mhra":     dict(name="MHRA Products", license="Open Government Licence v3.0",
                     license_url="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
                     homepage="https://products.mhra.gov.uk/",
                     commercial_ok=True, attribution_required=True),
    # Product labels (growth plan run C1): DailyMed SPL documents, published by the US National
    # Library of Medicine; the labels are US government public domain.
    "dailymed": dict(name="DailyMed", license="US Government Public Domain",
                     license_url="https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm",
                     homepage="https://dailymed.nlm.nih.gov/",
                     commercial_ok=True, attribution_required=False),
}

# Non-commercial / share-alike sources we must NOT ingest on an ad-supported site.
BLOCKED: frozenset[str] = frozenset({
    "drugbank", "hmdb", "foodb", "flavordb", "leffingwell",  # non-commercial
    "chembl",                                                 # CC BY-SA: isolate, don't blend
    "openfoodfacts",                                          # ODbL share-alike (Garrett, 2026-10-18)
})


class BlockedSourceError(RuntimeError):
    pass


def assert_not_blocked(source_key: str) -> None:
    """Raise if a caller tries to attach a blocked/NC source to any record."""
    if source_key in BLOCKED:
        raise BlockedSourceError(
            f"Source '{source_key}' is non-commercial or share-alike and must not be "
            f"ingested on an ad-supported site. Hand-curate the marquee equivalent instead."
        )


def source_rows() -> list[dict]:
    """Rows to upsert into the `source` table."""
    return [{"key": k, **v} for k, v in SOURCES.items()]
