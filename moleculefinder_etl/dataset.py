"""The MoleculeFinder dataset, for Zenodo and Kaggle (growth plan run D, the teacher kit).

`mfetl dataset` rebuilds `data/dataset/` from the committed snapshot: MoleculeFinder's
structured fields only, from public-domain and CC0 sources, released under CC0 1.0. Garrett
uploads it by hand; nothing here talks to Zenodo or Kaggle. The next tranche republishes by
running it again (the version is the snapshot's year and month unless `--version` says).

What goes in, and why, is decided field by field (README "What is not in the dataset"):

* PubChem's own computed identity and properties (formula, weight, SMILES, InChI, XLogP and
  the other descriptors) are NCBI's computations, public domain. Wikidata's
  description, label and aliases are CC0, and so are Wikimedia page views. MoleculeFinder's
  curated lines, groups, hubs, product lists, worlds and relationships are released CC0 here
  by their owner.
* PubChem is not uniformly public domain: its annotations carry each depositor's terms. So an
  LD50 is included only when a US government source (HSDB, ChemIDplus, the EPA, the FDA, NIOSH,
  NTP...) reports that exact value, species and route in the PUG-View record main was built
  from (`ld50_sources` names them). The rest are withheld, with their count.
* Left out: the GHS hazard classification and the hazard hubs built from it (ECHA's reuse terms
  ask for acknowledgement; NITE, Safe Work Australia and EUR-Lex carry their own), licence
  records from the MHRA (OGL v3), the EMA (source acknowledged) and the national registers
  (AIFA, Latvia's SAM), CAS Registry Numbers (a registry of the American Chemical Society),
  PubChem's depositor synonyms, serving sizes (dosing), and prose that is not a structured field
  (comparisons, short answers). Drugs@FDA records are US government works and stay.

The build verifies the inputs are the ones main was built from (`inputs.verify`), so the LD50
trace reads the same PUG-View records the snapshot did, and it checks every table's row count
against the snapshot before it writes anything.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import DATA, RAW_CACHE, SNAPSHOTS
from .sources import cache as rawcache
from .transform.toxicity import parse_ld50

log = logging.getLogger("mfetl.dataset")

OUT = DATA / "dataset"
SITE = "https://moleculefinder.com"
TITLE = "MoleculeFinder: the molecules in everyday foods, drinks and products"
KAGGLE_ID = "trommsdorff/moleculefinder"
LICENSE_ID = "CC0-1.0"

# PUG-View reference sources whose content is a work of the US federal government (17 U.S.C. 105).
# An LD50 is kept only when one of these reports it. Anything else (T3DB, Haz-Map, StatPearls,
# ILO-WHO ICSC, EFSA, IARC, CIR, RAIS, personal collections) is withheld, whatever its terms say,
# because a CC0 release cannot carry a term it does not own.
PUBLIC_DOMAIN_TOX_SOURCES = frozenset({
    "Hazardous Substances Data Bank (HSDB)",
    "ChemIDplus",
    "EPA Toxicity Values Database (ToxValDB)",
    "EPA Human Health Benchmarks for Pharmaceuticals (HHB-Rx)",
    "EPA Regional Screening Levels for Chemical Contaminants at Superfund Sites",
    "EPA Integrated Risk Information System (IRIS)",
    "EPA Pesticide Ecotoxicity Database",
    "EPA Provisional Peer-Reviewed Toxicity Values (PPRTVs)",
    "EPA Safe Drinking Water Act (SDWA)",
    "FDA Liver Toxicity Knowledge Base (LTKB)",
    "Drugs and Lactation Database (LactMed)",
    "LiverTox",
    "The National Institute for Occupational Safety and Health (NIOSH)",
    "Agency for Toxic Substances and Disease Registry (ATSDR)",
    "NTP Technical Reports",
    "USGS Health-Based Screening Levels for Evaluating Water-Quality Data",
    "USGS Columbia Environmental Research Center",
    "USDA APHIS Chemical Effects Database",
})

# Category kinds left out: `poison` hubs are built from the GHS classification.
EXCLUDED_CATEGORY_KINDS = frozenset({"poison"})
# Licence records kept: the FDA's (Drugs@FDA, a US government work).
FDA = "US Food and Drug Administration"


# ── the tables ──────────────────────────────────────────────────────────────
MOLECULE_COLUMNS: list[tuple[str, str, str, str]] = [
    # (column, type, description, provenance)
    ("slug", "string", "MoleculeFinder's identifier; the page is https://moleculefinder.com/m/<slug>.", "MoleculeFinder"),
    ("name", "string", "The name MoleculeFinder uses (its page title).", "MoleculeFinder, from PubChem and Wikidata"),
    ("pubchem_cid", "integer", "PubChem Compound ID. Blank for the 18 hand-modelled biopolymers and mixtures, which have no single PubChem compound.", "PubChem"),
    ("wikidata_qid", "string", "Wikidata item.", "Wikidata (CC0)"),
    ("wikipedia_title", "string", "English Wikipedia article title (the title only, no Wikipedia text).", "Wikidata sitelink (CC0)"),
    ("molecular_formula", "string", "Molecular formula (Hill order).", "PubChem (computed)"),
    ("molecular_weight", "number", "Molecular weight, g/mol.", "PubChem (computed)"),
    ("canonical_smiles", "string", "SMILES without stereochemistry (PubChem ConnectivitySMILES).", "PubChem (computed)"),
    ("isomeric_smiles", "string", "SMILES with stereochemistry.", "PubChem (computed)"),
    ("inchi", "string", "Standard InChI.", "PubChem (computed)"),
    ("inchikey", "string", "Standard InChIKey.", "PubChem (computed)"),
    ("xlogp", "number", "XLogP3 partition coefficient.", "PubChem (computed)"),
    ("tpsa", "number", "Topological polar surface area, square angstroms.", "PubChem (computed)"),
    ("h_bond_donors", "integer", "Hydrogen bond donor count.", "PubChem (computed)"),
    ("h_bond_acceptors", "integer", "Hydrogen bond acceptor count.", "PubChem (computed)"),
    ("rotatable_bonds", "integer", "Rotatable bond count.", "PubChem (computed)"),
    ("complexity", "number", "Bertz/Hendrickson complexity.", "PubChem (computed)"),
    ("formal_charge", "integer", "Formal charge.", "PubChem (computed)"),
    ("wikidata_description", "string", "Wikidata's short English description.", "Wikidata (CC0)"),
    ("other_names", "string", "Up to four other names, the Wikidata label then aliases, separated by ' | '.", "Wikidata (CC0), filtered by MoleculeFinder"),
    ("brand_names", "string", "Curated brand names, separated by ' | '.", "MoleculeFinder curated"),
    ("description", "string", "MoleculeFinder's one-line description of the molecule (the page's own).", "MoleculeFinder curated (CC0 in this dataset)"),
    ("why_it_matters", "string", "MoleculeFinder's curated line on why the molecule matters in everyday life.", "MoleculeFinder curated (CC0 in this dataset)"),
    ("group", "string", "MoleculeFinder's everyday group (food-flavor, sweetener, prescription-medicine...).", "MoleculeFinder curated"),
    ("family", "string", "Chemical or drug family (alkaloid, ssri, terpenoid...).", "MoleculeFinder curated"),
    ("is_otc", "boolean", "Sold over the counter in the US (MoleculeFinder's allowlist).", "MoleculeFinder curated"),
    ("dual_use", "boolean", "Also has a common use outside medicine or food.", "MoleculeFinder curated"),
    ("macromolecule", "boolean", "A biopolymer or mixture with no single structure drawing.", "MoleculeFinder"),
    ("ld50_mg_per_kg", "number", "The molecule page's one LD50 (oral rat, then oral mouse, then any oral, then any route), mg/kg. An animal study measurement, not a dose for a person. Blank when no US government source reports it (see ld50_sources).", "US government sources via PubChem"),
    ("ld50_species", "string", "Species of that LD50.", "US government sources via PubChem"),
    ("ld50_route", "string", "Route of that LD50 (oral, dermal, inhalation, iv, other).", "US government sources via PubChem"),
    ("ld50_sources", "string", "The US government sources reporting that LD50, separated by ' | '.", "PubChem PUG-View references"),
    ("half_life_hours", "number", "Elimination half-life in people, hours (8 molecules).", "MoleculeFinder curated"),
    ("relative_sweetness", "number", "Sweetness relative to sucrose = 1.", "MoleculeFinder curated"),
    ("scoville_shu", "number", "Pungency of the pure compound, Scoville heat units.", "MoleculeFinder curated"),
    ("odor_threshold_ng_m3", "number", "Odor detection threshold, ng per cubic metre of air.", "MoleculeFinder curated"),
    ("pageviews_monthly", "integer", "English Wikipedia page views per month, the demand signal MoleculeFinder ranks by.", "Wikimedia Pageviews (CC0)"),
    ("catalog_batch", "string", "The tranche that added the molecule (blank: the original everyday core).", "MoleculeFinder"),
    ("url", "string", "The molecule's MoleculeFinder page.", "MoleculeFinder"),
]

TABLES: dict[str, list[tuple[str, str, str, str]]] = {
    "molecules": MOLECULE_COLUMNS,
    "products": [
        ("slug", "string", "MoleculeFinder's identifier; the page is https://moleculefinder.com/whats-in/<slug>.", "MoleculeFinder"),
        ("name", "string", "Product, food or drink name, used only to name it.", "DailyMed label, Wikidata or MoleculeFinder"),
        ("kind", "string", "food, drink, medicine, cosmetic, household, chemistry (a class such as PFAS) or moment (an everyday world).", "MoleculeFinder"),
        ("source_type", "string", "Where the ingredient list comes from: dailymed, wikidata, world, curated or class.", "MoleculeFinder"),
        ("source_id", "string", "The DailyMed set id, Wikidata QID, world slug, curated hub or class slug.", "DailyMed / Wikidata / MoleculeFinder"),
        ("source_url", "string", "The label or item the list was read from.", "DailyMed / Wikidata / MoleculeFinder"),
        ("also_from", "string", "Further sources a food or drink combines, as type:id, separated by ' | '.", "MoleculeFinder"),
        ("labeler", "string", "The label's labeler (DailyMed products).", "DailyMed (US public domain)"),
        ("document_type", "string", "The label's document type (DailyMed products).", "DailyMed (US public domain)"),
        ("label_effective", "string", "The label version's effective date, YYYYMMDD (DailyMed products).", "DailyMed (US public domain)"),
        ("ingredients_listed", "integer", "Ingredients the source lists.", "DailyMed / Wikidata / MoleculeFinder"),
        ("molecules_in_dataset", "integer", "Of those, the molecules in this dataset (rows in product_molecules.csv).", "MoleculeFinder"),
        ("url", "string", "The product's MoleculeFinder page.", "MoleculeFinder"),
    ],
    "product_molecules": [
        ("product_slug", "string", "products.slug", "MoleculeFinder"),
        ("molecule_slug", "string", "molecules.slug", "MoleculeFinder"),
        ("role", "string", "active, inactive (label ingredients), part (Wikidata), curated, world or class.", "DailyMed / Wikidata / MoleculeFinder"),
        ("listed_as", "string", "The ingredient's name on the label, where it differs in form (sertraline hydrochloride).", "DailyMed (US public domain)"),
        ("purpose", "string", "The label's own purpose line for an active ingredient.", "DailyMed (US public domain)"),
        ("matched_by", "string", "How the ingredient was matched to the molecule: unii, moiety, parent, skeleton or alias (labels); qid, curated, world or class otherwise. Never by name.", "MoleculeFinder"),
    ],
    "categories": [
        ("slug", "string", "MoleculeFinder's identifier; the hub is https://moleculefinder.com/in/<slug>.", "MoleculeFinder"),
        ("name", "string", "Category name.", "MoleculeFinder"),
        ("kind", "string", "bucket, family, food, product, use, type, functional_group (RDKit SMARTS), element or size.", "MoleculeFinder (curated, or computed from PubChem and RDKit)"),
        ("molecules", "integer", "Members (rows in molecule_categories.csv).", "MoleculeFinder"),
    ],
    "molecule_categories": [
        ("molecule_slug", "string", "molecules.slug", "MoleculeFinder"),
        ("category_slug", "string", "categories.slug", "MoleculeFinder"),
        ("note", "string", "The curated note, where there is one (caffeine in coffee: ~95 mg per 8 oz cup).", "MoleculeFinder curated"),
    ],
    "relationships": [
        ("from_slug", "string", "molecules.slug", "MoleculeFinder curated"),
        ("relation", "string", "becomes (a metabolite or product) or affects (acts on).", "MoleculeFinder curated"),
        ("to_slug", "string", "molecules.slug", "MoleculeFinder curated"),
        ("note", "string", "What the relation is (major metabolite, receptor antagonist).", "MoleculeFinder curated"),
        ("confidence", "string", "from_source or inferred, as the site labels it.", "MoleculeFinder curated"),
    ],
    "similarity": [
        ("molecule_slug", "string", "molecules.slug", "MoleculeFinder"),
        ("neighbor_slug", "string", "molecules.slug of a structural neighbour.", "MoleculeFinder"),
        ("tanimoto", "number", "Tanimoto similarity of Morgan fingerprints (radius 2, 2048 bits).", "Computed with RDKit from PubChem SMILES"),
    ],
    "worlds": [
        ("slug", "string", "MoleculeFinder's identifier; the page is https://moleculefinder.com/roam/<slug>.", "MoleculeFinder"),
        ("title", "string", "The everyday world (Morning coffee, After the rain...).", "MoleculeFinder curated"),
        ("blurb", "string", "One line about it.", "MoleculeFinder curated (CC0 in this dataset)"),
    ],
    "world_molecules": [
        ("world_slug", "string", "worlds.slug", "MoleculeFinder curated"),
        ("molecule_slug", "string", "molecules.slug", "MoleculeFinder curated"),
    ],
    "licences": [
        ("molecule_slug", "string", "molecules.slug", "MoleculeFinder"),
        ("regulator", "string", "US Food and Drug Administration.", "Drugs@FDA (US public domain)"),
        ("application", "string", "The application (NDA, ANDA or BLA number).", "Drugs@FDA (US public domain)"),
        ("product", "string", "A product marketed under it.", "Drugs@FDA (US public domain)"),
        ("authorised", "string", "Original approval date, YYYY-MM-DD.", "Drugs@FDA (US public domain)"),
        ("holder", "string", "The application holder.", "Drugs@FDA (US public domain)"),
        ("combination_only", "boolean", "Marketed only in combination with another active ingredient.", "Drugs@FDA (US public domain)"),
        ("source_url", "string", "The application's Drugs@FDA page.", "Drugs@FDA (US public domain)"),
    ],
}


@dataclass
class Build:
    tables: dict[str, list[dict[str, Any]]]
    version: str
    refreshed: str
    snapshot_sha: str
    inputs: str | None
    withheld: dict[str, Any] = field(default_factory=dict)


# ── reading ─────────────────────────────────────────────────────────────────
def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_snapshot(root: Path = SNAPSHOTS) -> dict[str, Any]:
    files = sorted((root / "molecules").glob("*.json"))
    h = hashlib.sha256()
    for name in ["meta.json", "products.json", "worlds.json"]:
        p = root / name
        if p.exists():
            h.update(name.encode() + b"\0" + p.read_bytes())
    for f in files:
        h.update(f.name.encode() + b"\0" + f.read_bytes())
    meta = _read(root / "meta.json") if (root / "meta.json").exists() else {}
    return {
        "molecules": [_read(f) for f in files],
        "products": (_read(root / "products.json") if (root / "products.json").exists() else {}).get("products", []),
        "worlds": (_read(root / "worlds.json") if (root / "worlds.json").exists() else {}).get("worlds", []),
        "refreshed": meta.get("refreshed"),
        "sha": h.hexdigest(),
    }


def pug_view_toxicity(cid: int | None, cache_root: Path = RAW_CACHE) -> dict | None:
    """The PUG-View Toxicity record main was built from, or None."""
    if not cid or cid < 0:
        return None
    p = cache_root / "pubchem" / f"{cid}-Toxicity.json"
    if not p.exists():
        return None
    return rawcache.unwrap(_read(p)).value


def ld50_sources(record: dict | None, value: float, species: str | None, route: str | None) -> list[str]:
    """Every PUG-View reference source whose own text yields this exact LD50 row.

    Each Information item names its reference; the item is parsed with the same parser the
    snapshot used (`toxicity.parse_ld50`), so a source counts only when its string says this value,
    species and route."""
    if not record:
        return []
    rec = record.get("Record", record)
    names = {r.get("ReferenceNumber"): r.get("SourceName") for r in rec.get("Reference", []) or []}
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for info in node.get("Information", []) or []:
                for row in parse_ld50({"Information": [info]}):
                    if (abs(row["value_num"] - value) < 1e-9 and row.get("species") == species
                            and row.get("route") == route):
                        src = names.get(info.get("ReferenceNumber"))
                        if src:
                            found.add(src)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(rec.get("Section", []))
    return sorted(found)


# ── building ────────────────────────────────────────────────────────────────
def _join(items: list[str] | None) -> str | None:
    items = [str(x) for x in (items or []) if x not in (None, "")]
    return " | ".join(items) if items else None


def _prop(m: dict, key: str) -> Any:
    for p in m.get("properties") or []:
        if p.get("key") == key:
            return p.get("value_num") if p.get("value_num") is not None else p.get("value_text")
    return None


def molecule_row(m: dict, tox_sources: list[str]) -> dict[str, Any]:
    d = m.get("descriptors") or {}
    has_ld50 = m.get("ld50_mg_per_kg") is not None and bool(tox_sources)
    cid = m.get("cid")
    return {
        "slug": m["slug"],
        "name": m["title"],
        "pubchem_cid": cid if isinstance(cid, int) and cid > 0 else None,
        "wikidata_qid": m.get("wikidata_qid"),
        "wikipedia_title": m.get("wikipedia_title"),
        "molecular_formula": m.get("molecular_formula"),
        "molecular_weight": m.get("molecular_weight"),
        "canonical_smiles": m.get("canonical_smiles"),
        "isomeric_smiles": m.get("isomeric_smiles"),
        "inchi": m.get("inchi"),
        "inchikey": m.get("inchikey"),
        "xlogp": d.get("xlogp"),
        "tpsa": d.get("tpsa"),
        "h_bond_donors": d.get("h_bond_donors"),
        "h_bond_acceptors": d.get("h_bond_acceptors"),
        "rotatable_bonds": d.get("rotatable_bonds"),
        "complexity": d.get("complexity"),
        "formal_charge": d.get("formal_charge"),
        "wikidata_description": m.get("summary") if m.get("summary_source") == "wikidata" else None,
        "other_names": _join(m.get("wikidata_names")),
        "brand_names": _join(m.get("brands")),
        "description": m.get("description"),
        "why_it_matters": (m.get("why_it_matters") or {}).get("text"),
        "group": m.get("scope_bucket"),
        "family": m.get("scope_family") or m.get("family"),
        "is_otc": bool(m.get("is_otc")),
        "dual_use": bool(m.get("dual_use")),
        "macromolecule": bool(m.get("macromolecule")),
        "ld50_mg_per_kg": m.get("ld50_mg_per_kg") if has_ld50 else None,
        "ld50_species": m.get("ld50_species") if has_ld50 else None,
        "ld50_route": m.get("ld50_route") if has_ld50 else None,
        "ld50_sources": _join(tox_sources) if has_ld50 else None,
        "half_life_hours": m.get("half_life_hours"),
        "relative_sweetness": m.get("relative_sweetness"),
        "scoville_shu": m.get("scoville_shu"),
        "odor_threshold_ng_m3": m.get("odor_threshold"),
        "pageviews_monthly": m.get("pageviews_monthly"),
        "catalog_batch": m.get("batch"),
        "url": f"{SITE}/m/{m['slug']}",
    }


def _source_id(src: dict) -> tuple[str | None, str | None]:
    t = src.get("type")
    sid = {"dailymed": "setid", "wikidata": "qid", "world": "slug", "curated": "hub", "class": "slug"}.get(t)
    ident = src.get(sid) if sid else None
    if ident is None:
        ident = src.get("slug") or src.get("hub") or src.get("qid") or src.get("setid")
    url = src.get("url")
    if not url and t == "wikidata" and ident:
        url = f"https://www.wikidata.org/wiki/{ident}"
    if not url and t == "world" and ident:
        url = f"{SITE}/roam/{ident}"
    if not url and t == "curated" and ident:
        url = f"{SITE}/in/{ident}"
    return ident, url


def _matched_by(src_type: str, entry: dict) -> str:
    if entry.get("match"):
        return entry["match"]
    return {"wikidata": "qid", "world": "world", "curated": "curated", "class": "class"}.get(src_type, src_type)


def build(snapshot: dict[str, Any], *, version: str, inputs: str | None,
          tox: Any = pug_view_toxicity) -> Build:
    mols = snapshot["molecules"]
    slugs = {m["slug"] for m in mols}
    withheld_ld50: list[str] = []
    rows = []
    for m in mols:
        srcs: list[str] = []
        if m.get("ld50_mg_per_kg") is not None:
            every = ld50_sources(tox(m.get("cid")), m["ld50_mg_per_kg"], m.get("ld50_species"), m.get("ld50_route"))
            srcs = [s for s in every if s in PUBLIC_DOMAIN_TOX_SOURCES]
            if not srcs:
                withheld_ld50.append(m["slug"])
        rows.append(molecule_row(m, srcs))

    products, pm = [], []
    for p in snapshot["products"]:
        src = p.get("source") or {}
        sid, url = _source_id(src)
        also = [f"{a.get('type')}:{_source_id(a)[0]}" for a in p.get("also") or []]
        entries = [e for e in p.get("molecules") or [] if e.get("slug") in slugs]
        products.append({
            "slug": p["slug"], "name": p["name"], "kind": p["kind"], "source_type": src.get("type"),
            "source_id": sid, "source_url": url, "also_from": _join(also),
            "labeler": src.get("labeler"), "document_type": src.get("doc_type"),
            "label_effective": src.get("effective"), "ingredients_listed": p.get("listed"),
            "molecules_in_dataset": len(entries), "url": f"{SITE}/whats-in/{p['slug']}",
        })
        for e in entries:
            pm.append({
                "product_slug": p["slug"], "molecule_slug": e["slug"], "role": e.get("role"),
                "listed_as": e.get("listed_as"), "purpose": e.get("purpose"),
                "matched_by": _matched_by(src.get("type") or "", e),
            })

    cats: dict[str, dict[str, Any]] = {}
    mc: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    excluded_hubs: set[str] = set()
    for m in mols:
        for c in m.get("categories") or []:
            if c.get("kind") in EXCLUDED_CATEGORY_KINDS:
                excluded_hubs.add(c["slug"])
                continue
            key = (m["slug"], c["slug"])
            if key in seen:
                continue
            seen.add(key)
            cats.setdefault(c["slug"], {"slug": c["slug"], "name": c["name"], "kind": c["kind"], "molecules": 0})
            cats[c["slug"]]["molecules"] += 1
            mc.append({"molecule_slug": m["slug"], "category_slug": c["slug"], "note": c.get("note")})

    rel, sim, wm = [], [], []
    for m in mols:
        trails = m.get("trails") or {}
        for relation in ("becomes", "affects"):
            for t in trails.get(relation) or []:
                if t.get("kind") == "molecule" and t.get("to") in slugs:
                    rel.append({"from_slug": m["slug"], "relation": relation, "to_slug": t["to"],
                                "note": t.get("note"), "confidence": t.get("confidence")})
        for t in trails.get("found_in") or []:
            if t.get("kind") == "world":
                wm.append({"world_slug": t["to"], "molecule_slug": m["slug"]})
        for e in m.get("edges") or []:
            if e.get("neighbor_slug") in slugs:
                sim.append({"molecule_slug": m["slug"], "neighbor_slug": e["neighbor_slug"], "tanimoto": e.get("tanimoto")})
    worlds = [{"slug": w["slug"], "title": w["title"], "blurb": w.get("blurb")} for w in snapshot["worlds"]]

    lic, withheld_lic = [], []
    for m in mols:
        a = m.get("approval")
        if not isinstance(a, dict):
            continue
        if a.get("regulator") == FDA and str(a.get("source", "")).startswith("https://www.accessdata.fda.gov/"):
            lic.append({"molecule_slug": m["slug"], "regulator": a["regulator"], "application": a.get("application"),
                        "product": a.get("product"), "authorised": a.get("authorised"), "holder": a.get("holder"),
                        "combination_only": bool(a.get("combination")), "source_url": a.get("source")})
        else:
            withheld_lic.append({"molecule_slug": m["slug"], "regulator": a.get("regulator"), "register": a.get("register")})

    ghs_count = sum(1 for m in mols if m.get("ghs"))
    tables = {
        "molecules": rows, "products": products, "product_molecules": pm,
        "categories": sorted(cats.values(), key=lambda c: c["slug"]), "molecule_categories": mc,
        "relationships": rel, "similarity": sim, "worlds": worlds, "world_molecules": wm, "licences": lic,
    }
    withheld = {
        "ld50": withheld_ld50,
        "ghs_molecules": ghs_count,
        "ghs_hubs": sorted(excluded_hubs),
        "licences": withheld_lic,
        "cas_numbers": sum(1 for m in mols if m.get("cas")),
    }
    return Build(tables, version, snapshot.get("refreshed") or "", snapshot["sha"], inputs, withheld)


def check_counts(b: Build, snapshot: dict[str, Any]) -> list[str]:
    """Each table's rows against the snapshot it came from. Empty when they agree."""
    mols, products = snapshot["molecules"], snapshot["products"]
    slugs = {m["slug"] for m in mols}
    want = {
        "molecules": len(mols),
        "products": len(products),
        "product_molecules": sum(len([e for e in p.get("molecules") or [] if e.get("slug") in slugs]) for p in products),
        "worlds": len(snapshot["worlds"]),
        "licences": sum(1 for m in mols if isinstance(m.get("approval"), dict)) - len(b.withheld["licences"]),
    }
    problems = [f"{t}: {len(b.tables[t])} rows, the snapshot has {n}" for t, n in want.items() if len(b.tables[t]) != n]
    for p in products:
        if len(p.get("molecules") or []) != sum(1 for r in b.tables["product_molecules"] if r["product_slug"] == p["slug"]):
            problems.append(f"product {p['slug']}: molecule count differs")
    for w in snapshot["worlds"]:
        if w.get("count") is not None and w["count"] != sum(1 for r in b.tables["world_molecules"] if r["world_slug"] == w["slug"]):
            problems.append(f"world {w['slug']}: {w['count']} molecules on the site")
    for t, cols in TABLES.items():
        names = [c[0] for c in cols]
        for r in b.tables[t]:
            if list(r) != names:
                problems.append(f"{t}: columns {list(r)}")
                break
    return problems


# ── writing ─────────────────────────────────────────────────────────────────
def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return repr(v)
    return str(v)


def csv_text(rows: list[dict[str, Any]], columns: list[str]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        w.writerow([_cell(r[c]) for c in columns])
    return buf.getvalue()


def write(b: Build, out: Path = OUT) -> dict[str, Any]:
    """Write the package into ``out`` (replacing what is there) and return the manifest."""
    tmp = out.with_name(out.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    files: dict[str, str] = {}
    for name, cols in TABLES.items():
        files[f"{name}.csv"] = csv_text(b.tables[name], [c[0] for c in cols])
    files["moleculefinder.json"] = json.dumps({
        "title": TITLE, "version": b.version, "license": LICENSE_ID, "snapshot": b.refreshed,
        "homepage": SITE, "tables": b.tables,
    }, ensure_ascii=False, indent=1, sort_keys=False) + "\n"
    counts = {name: len(b.tables[name]) for name in TABLES}
    from . import dataset_docs  # the README, LICENSE and metadata texts
    files.update(dataset_docs.render(b, counts))
    manifest = {
        "title": TITLE, "version": b.version, "license": LICENSE_ID, "snapshot_refreshed": b.refreshed,
        "snapshot_sha256": b.snapshot_sha, "inputs_fingerprint": b.inputs, "rows": counts,
        "withheld": {"ld50": len(b.withheld["ld50"]), "ghs_molecules": b.withheld["ghs_molecules"],
                     "ghs_hubs": len(b.withheld["ghs_hubs"]), "licences": len(b.withheld["licences"]),
                     "cas_numbers": b.withheld["cas_numbers"]},
        "files": {},
    }
    for name, text in sorted(files.items()):
        data = text.encode("utf-8")
        (tmp / name).write_bytes(data)
        manifest["files"][name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    (tmp / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    if out.exists():
        shutil.rmtree(out)
    tmp.rename(out)
    return manifest


def run(version: str | None = None, out: Path = OUT) -> int:
    """`mfetl dataset`: verify the pinned inputs, build, check the counts, write. Exit code."""
    from . import inputs
    fp = inputs.verify()
    snap = load_snapshot()
    v = version or (snap["refreshed"] or "")[:7].replace("-", ".")
    b = build(snap, version=v, inputs=fp)
    problems = check_counts(b, snap)
    if problems:
        for p in problems:
            log.error("dataset: %s", p)
        log.error("dataset: refused, nothing written")
        return 1
    manifest = write(b, out)
    log.info("dataset %s from snapshot %s (inputs %s): %s", v, snap["refreshed"], fp[:16],
             ", ".join(f"{k} {n}" for k, n in manifest["rows"].items()))
    log.info("dataset: withheld %s", manifest["withheld"])
    return 0
