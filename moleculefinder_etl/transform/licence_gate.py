"""The source-licence rule's backstop: every displayed value in the snapshot names a source the
registry knows and allows to be displayed (2026-10-23).

The parsers already keep values from non-displayable sources out (`toxicity.parse_ld50`,
`ghs.parse_ghs`, the CAS line in `assemble`). This module walks what was actually produced and
lists every citation, so a new field, a new parser or a hand edit that skips the rule fails the
export (`snapshot_export.export`) and the test suite (`tests/test_licence_gate.py`, which reads
the committed snapshot), instead of reaching the site.

A citation is (where, source key). A field with no explicit source carries the source it can
only have come from (`IMPLIED`): a CAS Registry Number cites the CAS Registry, a drawing RDKit.
Single numbers MoleculeFinder hand-transcribes from published literature and cites in its seed
files (half-lives, sweetness, Scoville, odor thresholds) are MoleculeFinder curated facts.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

from ..sources import registry

# Fields that cite a source by being present. (field, source key)
IMPLIED: tuple[tuple[str, str], ...] = (
    ("molecular_formula", "pubchem"), ("molecular_weight", "pubchem"),
    ("canonical_smiles", "pubchem"), ("isomeric_smiles", "pubchem"),
    ("inchi", "pubchem"), ("inchikey", "pubchem"),
    ("synonyms", "pubchem"), ("cas", "cas_registry"),
    ("wikidata_names", "wikidata"), ("wikidata_qid", "wikidata"),
    ("pageviews_monthly", "wikimedia_pageviews"),
    ("structure_svg", "rdkit"), ("edges", "rdkit"),
    ("brands", "curated"), ("odor_threshold", "curated"), ("trails", "curated"),
    ("content_blocks", "curated"),
)

# A licence record's register (lib/registers.ts on the web) -> registry key. A record with no
# register is one of Garrett's hand rulings: MoleculeFinder's own statement of a licence.
REGISTERS = {"Drugs@FDA": "drugs_at_fda", "European Medicines Agency": "ema", "MHRA Products": "mhra"}

# How a product's ingredient list is sourced (products.json `source.type`) -> registry key.
PRODUCT_SOURCES = {"dailymed": "dailymed", "wikidata": "wikidata", "curated": "curated",
                   "world": "curated", "class": "curated"}

_BY_NAME = {s["name"]: k for k, s in registry.SOURCES.items()}


def _key(cited: str | None) -> str | None:
    """A citation as written in the snapshot (a key, or a source's display name) -> its key."""
    if cited is None:
        return None
    return cited if cited in registry.SOURCES else _BY_NAME.get(cited, cited)


def _present(v) -> bool:
    return v is not None and v != "" and v != [] and v != {}


def molecule_citations(m: dict) -> Iterator[tuple[str, str | None]]:
    slug = m.get("slug")
    for s in m.get("sources") or []:
        yield f"{slug}.sources", s
    if _present(m.get("summary")):
        yield f"{slug}.summary", _key(m.get("summary_source"))
    if _present(m.get("description")):
        yield f"{slug}.description", _key(m.get("description_source"))
    w = m.get("why_it_matters") or {}
    if _present(w.get("text")):
        yield f"{slug}.why_it_matters", _key(w.get("source"))
    for field, key in IMPLIED:
        if _present(m.get(field)):
            yield f"{slug}.{field}", key
    if _present(m.get("descriptors")) and any(v is not None for k, v in m["descriptors"].items()
                                               if k != "confidence"):
        yield f"{slug}.descriptors", "pubchem"
    for p in m.get("properties") or []:
        yield f"{slug}.properties.{p.get('key')}", _key(p.get("source"))
    if m.get("relative_sweetness") is not None:
        yield f"{slug}.relative_sweetness", _key(m.get("relative_sweetness_source"))
    for c in m.get("categories") or []:
        for s in str(c.get("source") or "").split("+") if c.get("source") else [None]:
            yield f"{slug}.categories.{c.get('slug')}", _key(s)
    for i, t in enumerate(m.get("toxicity") or []):
        srcs = t.get("sources") or [None]          # a row with no source is a failure
        for s in srcs:
            yield f"{slug}.toxicity[{i}]", s
    g = m.get("ghs")
    if g:
        for s in g.get("sources") or [None]:
            yield f"{slug}.ghs", s
    if m.get("ld50_mg_per_kg") is not None:
        row = next((t for t in m.get("toxicity") or []
                    if (t.get("value_num"), t.get("species"), t.get("route"))
                    == (m["ld50_mg_per_kg"], m.get("ld50_species"), m.get("ld50_route"))), None)
        for s in (row or {}).get("sources") or [None]:
            yield f"{slug}.ld50_mg_per_kg", s
    a = m.get("approval")
    if isinstance(a, dict):
        yield f"{slug}.approval", REGISTERS.get(a.get("register") or "", "curated" if not a.get("register") else None)


def product_citations(p: dict) -> Iterator[tuple[str, str | None]]:
    for s in [p.get("source") or {}] + list(p.get("also") or []):
        yield f"product:{p.get('slug')}.source", PRODUCT_SOURCES.get(s.get("type"))


_MGKG = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*mg/kg")


def comparison_problems(comparisons: dict[str, dict] | None, molecules: list[dict]) -> list[str]:
    """Every mg/kg figure the curated /vs prose or answer line quotes must be a toxicity row a
    displayable source reports for one of the pair (2026-10-23: five comparisons quoted T3DB's figures).
    The rows on a record have already passed the rule, so membership is the whole test."""
    by_slug = {m.get("slug"): m for m in molecules}
    out = []
    for key, c in (comparisons or {}).items():
        reported = {float(t["value_num"]) for s in (c.get("a"), c.get("b"))
                    for t in (by_slug.get(s) or {}).get("toxicity") or [] if t.get("sources")}
        for fig in _MGKG.findall(f"{c.get('answer') or ''} {c.get('text') or ''}"):
            if float(fig.replace(",", "")) not in reported:
                out.append(f"comparison {key}: quotes {fig} mg/kg, which no displayable source reports "
                           f"for {c.get('a')} or {c.get('b')} (sources/seeds/comparisons.yaml)")
    return out


def problems(citations) -> list[str]:
    """Every citation of an unregistered source or one that may not be displayed."""
    out = []
    for where, key in citations:
        if key is None:
            out.append(f"{where}: cites no source")
        elif key not in registry.SOURCES:
            out.append(f"{where}: cites '{key}', which has no licence entry in the registry")
        elif not registry.may_display(key):
            out.append(f"{where}: cites '{key}' ({registry.licence_class(key)}), which may not be displayed")
    return out


def check_records(molecules: list[dict], products: list[dict] | None = None,
                  comparisons: dict[str, dict] | None = None) -> list[str]:
    cites = [c for m in molecules for c in molecule_citations(m)]
    cites += [c for p in products or [] for c in product_citations(p)]
    return problems(cites) + comparison_problems(comparisons, molecules)


def check_snapshot(snapshots: Path) -> list[str]:
    """The same check over a snapshot on disk (what the tests read)."""
    mols = [json.loads(p.read_text()) for p in sorted((snapshots / "molecules").glob("*.json"))]
    prod_path = snapshots / "products.json"
    prods = json.loads(prod_path.read_text()).get("products", []) if prod_path.exists() else []
    comp_path = snapshots / "comparisons.json"
    comps = json.loads(comp_path.read_text()) if comp_path.exists() else {}
    return check_records(mols, prods, comps)


def enforce(molecules: list[dict], products: list[dict] | None = None,
            comparisons: dict[str, dict] | None = None) -> None:
    found = check_records(molecules, products, comparisons)
    if found:
        more = f"\n  ... and {len(found) - 20} more" if len(found) > 20 else ""
        raise registry.LicenceRuleError(
            f"refusing to export: {len(found)} value(s) cite a source that is unregistered or may "
            "not be displayed (sources/registry.py):\n  " + "\n  ".join(found[:20]) + more)
