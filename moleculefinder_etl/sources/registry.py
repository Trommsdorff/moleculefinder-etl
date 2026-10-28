"""Provenance registry, the license firewall and the source-licence rule.

The registry seeds the `source` table and enforces two rules:

1. **The firewall** (since launch): never ingest non-commercial or share-alike data. Any code
   path that tries to attach a BLOCKED source to a row raises immediately.
2. **The source-licence rule** (2026-10-23, after run D found 41 live LD50s whose only source,
   T3DB, restricts commercial reuse): every source carries a licence class, and whether its
   values may be displayed is DERIVED from that class, never set by hand. A value reaches the
   snapshot only from a source that may be displayed (`may_display`), and
   `transform/licence_gate.py` fails the build if any snapshot value cites a source that is
   not here or may not be displayed. A source PubChem's PUG-View names that is not in
   `PUGVIEW_NAMES` is treated as not displayable (fail closed) until someone registers it.

A source whose class asks for attribution may be displayed only with that attribution, which
the snapshot carries (`sources.json`, written by the export) for the site to print.
"""
from __future__ import annotations

# ── licence classes ──────────────────────────────────────────────────────────
# class -> (may_display, attribution_required, what it means). `may_display` is the ONLY thing
# that decides whether a source's values reach the site; each source's class is its terms.
LICENCE_CLASSES: dict[str, tuple[bool, bool, str]] = {
    "public_domain": (True, False, "Public domain (a US government work, 17 U.S.C. 105, or a public-domain release)"),
    "cc0": (True, False, "CC0 1.0 public-domain dedication"),
    "own": (True, False, "MoleculeFinder's own curation, released under CC0 1.0 in the MoleculeFinder dataset"),
    "computed": (True, False, "Computed by open-source software (the output carries no licence of its own)"),
    "cc_by": (True, True, "Creative Commons Attribution (reuse, including commercial, with attribution)"),
    "ogl": (True, True, "Open Government Licence (reuse, including commercial, with attribution)"),
    "acknowledged": (True, True, "Reproduction authorised provided the source is acknowledged"),
    "restricted": (False, False, "Reuse restricted: permission needed for commercial reuse or publication"),
    "non_commercial": (False, False, "Non-commercial use only"),
    "share_alike": (False, False, "Share-alike: reuse obliges re-licensing under the same terms"),
}

# key -> row for the `source` table, plus `licence_class` (the rule above), `attribution` (the
# line a displayed value carries when its class asks for one) and `pugview_names` (the exact
# PubChem PUG-View `SourceName` strings that are this source). Only the `source` table's own
# columns go to the database (`source_rows`).
SOURCES: dict[str, dict] = {
    "pubchem":  dict(name="PubChem", license="Public Domain", licence_class="public_domain",
                     license_url="https://www.ncbi.nlm.nih.gov/home/about/policies/",
                     homepage="https://pubchem.ncbi.nlm.nih.gov/",
                     commercial_ok=True, attribution_required=False),
    "wikidata": dict(name="Wikidata", license="CC0", licence_class="cc0",
                     license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                     homepage="https://www.wikidata.org/",
                     commercial_ok=True, attribution_required=False),
    "rdkit":    dict(name="RDKit", license="BSD-3-Clause", licence_class="computed",
                     license_url="https://github.com/rdkit/rdkit/blob/master/license.txt",
                     homepage="https://www.rdkit.org/",
                     commercial_ok=True, attribution_required=False),
    "wikimedia_pageviews": dict(name="Wikimedia Pageviews", license="CC0", licence_class="cc0",
                     license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                     homepage="https://wikimedia.org/api/rest_v1/",
                     commercial_ok=True, attribution_required=False),
    "curated":  dict(name="MoleculeFinder curated", license="curated", licence_class="own",
                     license_url=None, homepage=None,
                     commercial_ok=True, attribution_required=False),
    "epa_comptox": dict(name="EPA CompTox", license="US Government Public Domain", licence_class="public_domain",
                     license_url="https://www.epa.gov/", homepage="https://comptox.epa.gov/",
                     commercial_ok=True, attribution_required=False),
    # Licence records (run B2, moleculefinder_etl/licences.py), read from the regulators' own data.
    "drugs_at_fda": dict(name="Drugs@FDA", license="US Government Public Domain", licence_class="public_domain",
                     license_url="https://www.fda.gov/about-fda/about-website/website-policies",
                     homepage="https://www.fda.gov/drugs/drug-approvals-and-databases/drugsfda-data-files",
                     commercial_ok=True, attribution_required=False),
    "ema":      dict(name="European Medicines Agency", license="Reproduction authorised, source acknowledged",
                     licence_class="acknowledged", attribution="Source: European Medicines Agency.",
                     license_url="https://www.ema.europa.eu/en/about-us/legal-notice",
                     homepage="https://www.ema.europa.eu/en/medicines/download-medicine-data",
                     commercial_ok=True, attribution_required=True),
    "mhra":     dict(name="MHRA Products", license="Open Government Licence v3.0", licence_class="ogl",
                     attribution="Contains public sector information licensed under the Open Government Licence v3.0.",
                     license_url="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
                     homepage="https://products.mhra.gov.uk/",
                     commercial_ok=True, attribution_required=True),
    # Product labels (growth plan run C1): DailyMed SPL documents, published by the US National
    # Library of Medicine; the labels are US government public domain.
    "dailymed": dict(name="DailyMed", license="US Government Public Domain", licence_class="public_domain",
                     license_url="https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm",
                     homepage="https://dailymed.nlm.nih.gov/",
                     commercial_ok=True, attribution_required=False),
    # The FDA's UNII table (trust run 3, 2026-10-24; sources/fda_unii.py): the code a label carries
    # for each ingredient, with the PubChem CID and InChIKey the FDA records for it. FDA website
    # policies: "Unless otherwise noted, the contents of the FDA website ... are not copyrighted.
    # They are in the public domain and may be republished, reprinted and otherwise used freely."
    "fda_unii": dict(name="FDA Substance Registration System (UNII)", license="US Government Public Domain",
                     licence_class="public_domain",
                     license_url="https://www.fda.gov/about-fda/about-website/website-policies",
                     homepage="https://precision.fda.gov/uniisearch",
                     commercial_ok=True, attribution_required=False),

    # ── Relative sweetness (SEO run 1, 2026-10-28; sources/seeds/sweetness.yaml). Each figure is
    # hand-transcribed, cited and quoted in the seed; these are the publishers it cites.
    "fda":      {"name": "US Food and Drug Administration (FDA)", "license": "US Government Public Domain",
                 "licence_class": "public_domain",
                 "license_url": "https://www.fda.gov/about-fda/about-website/website-policies",
                 "homepage": "https://www.fda.gov/food/food-additives-petitions/aspartame-and-other-sweeteners-food",
                 "commercial_ok": True, "attribution_required": False},
    "mesh":     {"name": "Medical Subject Headings (MeSH), US National Library of Medicine",
                 "license": "US Government Public Domain", "licence_class": "public_domain",
                 "license_url": "https://www.nlm.nih.gov/web_policies.html",
                 "homepage": "https://meshb.nlm.nih.gov/record/ui?ui=C012043",
                 "commercial_ok": True, "attribution_required": False},
    # The EFSA Journal is published under CC BY-ND 4.0: verbatim reuse, commercial included, with
    # attribution. A single figure quoted as published is that, so the class is "acknowledged".
    "efsa":     {"name": "EFSA Journal (European Food Safety Authority)",
                 "license": "CC BY-ND 4.0 (verbatim reuse with attribution)", "licence_class": "acknowledged",
                 "attribution": ("Source: EFSA Panel on Food Additives and Flavourings, \"Safety of use of Monk "
                                 "fruit extract as a food additive in different food categories\", EFSA Journal "
                                 "17 (2019) e05921, CC BY-ND 4.0."),
                 "license_url": "https://creativecommons.org/licenses/by-nd/4.0/",
                 "homepage": "https://doi.org/10.2903/j.efsa.2019.5921",
                 "commercial_ok": True, "attribution_required": True},
    # Open-access articles under CC BY 4.0 (the licence statement read on each article's PMC page).
    **{key: {"name": name, "license": "CC BY 4.0", "licence_class": "cc_by",
             "attribution": f"Source: {cite}, CC BY 4.0.",
             "license_url": "https://creativecommons.org/licenses/by/4.0/", "homepage": f"https://doi.org/{doi}",
             "commercial_ok": True, "attribution_required": True}
       for key, name, cite, doi in (
           ("dragomir_2025", "Dragomir et al., Foods 2025",
            ("N. Dragomir et al., \"Beyond Sugar: A Holistic Review of Sweeteners and Their Role in Modern "
             "Nutrition\", Foods 14 (2025) 3182"), "10.3390/foods14183182"),
           ("weber_2025", "Weber et al., J. Agric. Food Chem. 2025",
            ("N. Weber et al., \"Comparison of Two L-Arabinose Isomerases for Multienzymatic Conversion of "
             "Lactose in Skim Milk Permeate at Neutral and Acidic pH\", J. Agric. Food Chem. 73 (2025) 15889"),
            "10.1021/acs.jafc.5c04545"),
           ("saraiva_2020", "Saraiva et al., IJERPH 2020",
            ("A. Saraiva et al., \"Natural Sweeteners: The Relevance of Food Naturalness for Consumers, Food "
             "Security Aspects, Sustainability and Health Impacts\", Int. J. Environ. Res. Public Health 17 "
             "(2020) 6285"), "10.3390/ijerph17176285"),
           ("gourineni_2018", "Gourineni et al., Nutrients 2018",
            ("V. Gourineni et al., \"Gastrointestinal Tolerance and Glycemic Response of Isomaltooligosaccharides "
             "in Healthy Adults\", Nutrients 10 (2018) 301"), "10.3390/nu10030301"),
           ("vajdovich_2025", "Vajdovich et al., Foods 2025",
            ("D. K. Vajdovich et al., \"Pseudocereal-Based Functional Beverages: Main Properties and Nutritional "
             "Evaluation with an Emphasis on Amino Acid Content: A Review\", Foods 14 (2025) 2080"),
            "10.3390/foods14122080"),
           ("dermesonlouoglou_2026", "Dermesonlouoglou et al., Foods 2026",
            ("E. Dermesonlouoglou et al., \"Osmotic Dehydration with Alternative Humectants for the Production "
             "of Ultrachilled Cherry Tomatoes\", Foods 15 (2026) 2569"), "10.3390/foods15142569"),
       )},
    # ── The sources behind PubChem's annotations (2026-10-23). PubChem's own computed data is
    # public domain, but a PUG-View annotation (an LD50, a GHS classification) is a depositor's
    # content under the depositor's terms, so each depositor is its own source here.
    "hsdb":     dict(name="Hazardous Substances Data Bank (HSDB)", license="US Government Public Domain",
                     licence_class="public_domain",
                     license_url="https://www.nlm.nih.gov/web_policies.html",
                     homepage="https://pubchem.ncbi.nlm.nih.gov/source/11933",
                     commercial_ok=True, attribution_required=False,
                     pugview_names=("Hazardous Substances Data Bank (HSDB)",)),
    "chemidplus": dict(name="ChemIDplus", license="US Government Public Domain", licence_class="public_domain",
                     license_url="https://www.nlm.nih.gov/web_policies.html",
                     homepage="https://pubchem.ncbi.nlm.nih.gov/source/ChemIDplus",
                     commercial_ok=True, attribution_required=False,
                     pugview_names=("ChemIDplus",)),
    # The other US government sources PUG-View files toxicity under (17 U.S.C. 105). None of
    # them reports a parseable LD50 for the catalog today (HSDB does, 2026-10-23), but each is
    # registered so the dataset's allowlist and the site's rule are the same list.
    **{key: dict(name=name, license="US Government Public Domain", licence_class="public_domain",
                 license_url=None, homepage=None, commercial_ok=True, attribution_required=False,
                 pugview_names=(name,))
       for key, name in (
           ("epa_toxvaldb", "EPA Toxicity Values Database (ToxValDB)"),
           ("epa_hhb_rx", "EPA Human Health Benchmarks for Pharmaceuticals (HHB-Rx)"),
           ("epa_rsl", "EPA Regional Screening Levels for Chemical Contaminants at Superfund Sites"),
           ("epa_iris", "EPA Integrated Risk Information System (IRIS)"),
           ("epa_pesticide_ecotox", "EPA Pesticide Ecotoxicity Database"),
           ("epa_pprtv", "EPA Provisional Peer-Reviewed Toxicity Values (PPRTVs)"),
           ("epa_sdwa", "EPA Safe Drinking Water Act (SDWA)"),
           ("fda_ltkb", "FDA Liver Toxicity Knowledge Base (LTKB)"),
           ("lactmed", "Drugs and Lactation Database (LactMed)"),
           ("livertox", "LiverTox"),
           ("niosh", "The National Institute for Occupational Safety and Health (NIOSH)"),
           ("atsdr", "Agency for Toxic Substances and Disease Registry (ATSDR)"),
           ("ntp", "NTP Technical Reports"),
           ("usgs_hbsl", "USGS Health-Based Screening Levels for Evaluating Water-Quality Data"),
           ("usgs_cerc", "USGS Columbia Environmental Research Center"),
           ("usda_aphis", "USDA APHIS Chemical Effects Database"),
       )},
    # T3DB's downloads page: "Use and re-distribution of the data, in whole or in part, for
    # commercial purposes requires explicit permission of the authors."
    "t3db":     dict(name="Toxin and Toxin Target Database (T3DB)",
                     license="Free to use; commercial reuse requires the authors' permission",
                     licence_class="restricted",
                     license_url="http://www.t3db.ca/downloads", homepage="http://www.t3db.ca/",
                     commercial_ok=False, attribution_required=True,
                     pugview_names=("Toxin and Toxin Target Database (T3DB)",)),
    # ECHA's legal notice: reproduction is authorised provided the source is acknowledged.
    "echa":     dict(name="European Chemicals Agency (ECHA)",
                     license="Reproduction authorised, source acknowledged", licence_class="acknowledged",
                     attribution="Source: European Chemicals Agency, echa.europa.eu.",
                     license_url="https://echa.europa.eu/legal-notice",
                     homepage="https://echa.europa.eu/information-on-chemicals/cl-inventory-database",
                     commercial_ok=True, attribution_required=True,
                     pugview_names=("European Chemicals Agency (ECHA)",)),
    # The CLP Regulation's harmonised classifications, published on EUR-Lex (Commission Decision
    # 2011/833/EU: reuse authorised, source acknowledged).
    "eu_clp":   dict(name="Regulation (EC) No 1272/2008 (CLP), EUR-Lex",
                     license="Reuse authorised, source acknowledged (Decision 2011/833/EU)",
                     licence_class="acknowledged",
                     attribution="Source: EUR-Lex, Regulation (EC) No 1272/2008, © European Union.",
                     license_url="https://eur-lex.europa.eu/content/legal-notice/legal-notice.html",
                     homepage="https://eur-lex.europa.eu/eli/reg/2008/1272/oj",
                     commercial_ok=True, attribution_required=True,
                     pugview_names=("Regulation (EC) No 1272/2008 of the European Parliament and of the Council",)),
    # Safe Work Australia: "All material on our website is under a Creative Commons Attribution
    # 4.0 International Licence", attributed as © Commonwealth of Australia.
    "hcis":     dict(name="Hazardous Chemical Information System (HCIS), Safe Work Australia",
                     license="CC BY 4.0", licence_class="cc_by",
                     attribution="Source: Safe Work Australia, Hazardous Chemical Information System, © Commonwealth of Australia, CC BY 4.0.",
                     license_url="https://www.safeworkaustralia.gov.au/copyright",
                     homepage="https://hcis.safeworkaustralia.gov.au/",
                     commercial_ok=True, attribution_required=True,
                     pugview_names=("Hazardous Chemical Information System (HCIS), Safe Work Australia",)),
    # NITE's site terms: "All information and materials appearing on this site are copyright
    # protected"; copying or publishing without permission is not allowed beyond private use and
    # quotation. Its GHS pages permit copying only to prepare a GHS label or safety data sheet.
    "nite":     dict(name="NITE Chemical Management Center (NITE-CMC)",
                     license="Copyright NITE; publication needs permission", licence_class="restricted",
                     license_url="https://www.nite.go.jp/en/homepage/index.html",
                     homepage="https://www.nite.go.jp/chem/english/ghs/ghs_index.html",
                     commercial_ok=False, attribution_required=True,
                     pugview_names=("NITE-CMC",)),
    # CAS Registry Numbers: CAS (a division of the American Chemical Society) requires a licence
    # to publish CAS RNs to the public or to use them to power a public platform. They reach the
    # pipeline inside PubChem's synonym lists, but the numbers are CAS's.
    "cas_registry": dict(name="CAS Registry (American Chemical Society)",
                     license="Publication requires a CAS licence", licence_class="restricted",
                     license_url="https://www.cas.org/training/documentation/chemical-substances/cas-rn-verified-partner-program",
                     homepage="https://www.cas.org/cas-data/cas-registry",
                     commercial_ok=False, attribution_required=True),
}

# Non-commercial / share-alike sources we must NOT ingest on an ad-supported site.
BLOCKED: frozenset[str] = frozenset({
    "drugbank", "hmdb", "foodb", "flavordb", "leffingwell",  # non-commercial
    "chembl",                                                 # CC BY-SA: isolate, don't blend
    "openfoodfacts",                                          # ODbL share-alike (Garrett, 2026-10-18)
})

# The short name a chip or a list uses ("LD50: HSDB via PubChem"); the full name otherwise.
SHORT_NAMES: dict[str, str] = {
    "ema": "EMA", "mhra": "MHRA", "hsdb": "HSDB", "t3db": "T3DB", "echa": "ECHA",
    "eu_clp": "EU CLP Regulation", "hcis": "Safe Work Australia", "nite": "NITE",
    "cas_registry": "CAS Registry", "fda_unii": "FDA UNII", "epa_toxvaldb": "EPA ToxValDB", "epa_iris": "EPA IRIS",
    "niosh": "NIOSH", "atsdr": "ATSDR", "fda_ltkb": "FDA LTKB", "lactmed": "LactMed",
    "fda": "FDA", "mesh": "MeSH", "efsa": "EFSA", "dragomir_2025": "Dragomir et al. 2025",
    "weber_2025": "Weber et al. 2025", "saraiva_2020": "Saraiva et al. 2020", "gourineni_2018": "Gourineni et al. 2018",
    "vajdovich_2025": "Vajdovich et al. 2025", "dermesonlouoglou_2026": "Dermesonlouoglou et al. 2026",
}

# PUG-View SourceName -> registry key.
PUGVIEW_NAMES: dict[str, str] = {n: k for k, s in SOURCES.items() for n in s.get("pugview_names", ())}

# The `source` table's columns (supabase/migrations/0001_init.sql).
_DB_COLUMNS = ("name", "license", "license_url", "homepage", "commercial_ok", "attribution_required")


class BlockedSourceError(RuntimeError):
    pass


class LicenceRuleError(RuntimeError):
    """A value would reach the snapshot from a source that is unregistered or may not be displayed."""


def assert_not_blocked(source_key: str) -> None:
    """Raise if a caller tries to attach a blocked/NC source to any record."""
    if source_key in BLOCKED:
        raise BlockedSourceError(
            f"Source '{source_key}' is non-commercial or share-alike and must not be "
            f"ingested on an ad-supported site. Hand-curate the marquee equivalent instead."
        )


def licence_class(source_key: str) -> str | None:
    s = SOURCES.get(source_key)
    return s.get("licence_class") if s else None


def may_display(source_key: str | None) -> bool:
    """True only for a registered source whose licence class allows display. Unknown -> False."""
    cls = licence_class(source_key or "")
    return bool(cls) and LICENCE_CLASSES[cls][0]


def pugview_key(source_name: str | None) -> str | None:
    """The registry key for a PUG-View SourceName, or None when it is not registered."""
    return PUGVIEW_NAMES.get(source_name or "")


def source_rows() -> list[dict]:
    """Rows to upsert into the `source` table (its own columns only)."""
    return [{"key": k, **{c: v.get(c) for c in _DB_COLUMNS}} for k, v in SOURCES.items()]


def public_registry() -> list[dict]:
    """The registry as the snapshot carries it (`sources.json`), for the site to name sources
    and print the attribution a class asks for. Keys sorted for a byte-stable file."""
    out = []
    for k in sorted(SOURCES):
        s = SOURCES[k]
        cls = s["licence_class"]
        display, attrib, meaning = LICENCE_CLASSES[cls]
        out.append({"key": k, "name": s["name"], "short": SHORT_NAMES.get(k, s["name"]),
                    "license": s["license"], "licence_class": cls,
                    "licence_meaning": meaning, "may_display": display,
                    "attribution_required": attrib, "attribution": s.get("attribution"),
                    "license_url": s.get("license_url"), "homepage": s.get("homepage")})
    return out
