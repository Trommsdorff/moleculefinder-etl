"""What's in it: product pages (growth plan run C1, 2026-10-22).

One page per everyday product, food or drink, listing the molecules MoleculeFinder holds that
are in it. Garrett's decisions (2026-10-22): URL ``/whats-in/<product>``; a product page exists
only when MoleculeFinder already holds AT LEAST THREE of its molecules (a quality gate, not a
quota); the ten everyday worlds are the first ten products.

INPUTS
* ``sources/seeds/products.yaml``, hand-maintained: each product's slug, name, kind and ONE
  source item: a DailyMed set id (medicines, cosmetics, household OTC products), a Wikidata
  QID (foods and drinks) or a world slug (the ten worlds).
* DailyMed SPL labels (public domain), read by ``sources/dailymed.py``: the ingredient list,
  the active/inactive split and the OTC "Purpose" lines.
* Wikidata (CC0) "has part(s)" (P527) and "made from material" (P186), read by
  ``sources/wikidata.parts_for_qids``.
* ``worlds.yaml`` for the ten worlds.
* Class pages (Run C2, 2026-10-22): ``sources/seeds/product_classes.yaml`` names a class of
  chemicals (PFAS) and the catalog molecules in it, and a seed row ``class: <slug>`` makes the
  page. Membership is hand-curated like a food hub, then CHECKED against each member's formula
  by the class's rule (PFAS: perfluorinated, so at most one hydrogen and at least 2C - 1
  fluorines), so a wrong slug fails the build instead of shipping a false member.
* MoleculeFinder's own curated food hubs (amendment, 2026-10-22): the ``kind: food`` categories
  ``food_hubs.yaml`` and the curated overlays put on the records, the same membership /in/coffee
  shows. A seed row names a hub with ``curated: <hub slug>``. A curated row may also name a world
  and a Wikidata item (chocolate is the curated hub, the chocolate world and Q195): the page is
  their union, curated first, one entry per molecule.

MATCHING IS DETERMINISTIC. A label ingredient is a molecule when its UNII code (or, failing
that, its active moiety's UNII) is one of the UNIIs PubChem lists for that molecule's CID. A
Wikidata part is a molecule when its QID is the molecule's ``wikidata_qid``. No name matching,
no Wikipedia prose, no Open Food Facts (share-alike; blocked in ``sources/registry.py``). A UNII
two molecules share names neither.

SALTS, HYDRATES AND STEREO FORMS, BY RULE (amendment, 2026-10-22). A label ingredient whose UNII
matches no molecule is resolved through PubChem's parent compound (``pubchem.unii_parents``) of its
active moiety (an active) or of its own UNII (an excipient, which has no moiety): the
parent CID of a salt or hydrate (lactose monohydrate, saccharin sodium) when it is a catalog CID,
else a catalog molecule sharing the parent's InChIKey skeleton (its first block: same atoms and
bonds, any stereo), which is how racemic menthol reaches menthol and lactose monohydrate reaches
lactose. Accepted only when exactly ONE molecule qualifies (glucose and galactose share a skeleton,
so a skeleton they share matches neither) and that molecule has at least two carbon atoms: the
parent of an inorganic salt is its acid (sodium fluoride's is hydrogen fluoride), and a toothpaste
does not contain hydrofluoric acid. Forms the rule does not reach are on the hand list
``sources/seeds/unii_aliases.yaml``.

Fetching happens in the fetch stage (``warm``), into ``data/raw_cache``, so the inputs travel
with the snapshot (``moleculefinder_etl/inputs.py``) and the Mac and GitHub build identically;
compiling (``compile_products``) reads only the cache and the records.

THE LABEL'S OTHER INGREDIENTS (Trust run 2, 2026-10-24). A DailyMed product's ``not_in_catalog``
is the list of its label ingredients that are not MoleculeFinder molecules, each
``{"name": <the label's name>, "role": "active" | "inactive", "unii": <the label's code>}``, in
label order, actives first, one entry per name (it was a bare count). The page shows them as plain
unlinked text under "Also on the label". This is display, not matching: the names link to nothing,
and the gate still counts only molecules matched by code. ``actives_not_in_catalog`` (the actives'
names alone) stays as it was; the page's unmatched-active sentence reads it.

THE MOLECULE SIDE OF THE JOIN IS THE FDA'S OWN TABLE (Trust run 3, 2026-10-24). Until this run a
molecule's UNIIs were read from PubChem's synonym list alone, and PubChem files many codes bare,
under another compound, or not at all, so 23 label ingredients that ARE MoleculeFinder molecules
(polysorbate 80, xanthan gum, tirzepatide...) were shown as not in the catalog on 118 pages.
``unii_index`` now reads ``sources/fda_unii.py``, the FDA's UNII table, as well: a UNII belongs to a
record when the FDA's PubChem CID for it is the record's CID (``cid``), when the FDA's InChIKey is
the record's exactly (``inchikey``), when PubChem's synonym list for the record's CID carries it
(``pubchem``: a ``UNII-`` entry, or a bare code the table lists, never a bare code it does not), or
when the hand list's ``substances`` say so (``substance``: the codes of records neither source
links, hand-modelled polymers and proteins, a biologic with no PubChem synonyms). The sources are a
union, since each has codes the other lacks. A code two records claim goes to the one holding it by
the FDA's own link or the hand list, when exactly one does, else to neither. The by-rule route asks
PubChem for a label UNII's parent BY THE FDA'S CID (``pubchem.cid_parents``) instead of by the
``UNII-`` synonym PubChem may not hold, and the FDA's InChIKey skeleton counts beside the parents'.
A hand alias is final. Every matched row and every ``not_in_catalog`` entry carries the code it was decided on
(``unii``), and ``data/seed/unii_index.json`` (committed, ``write_unii_index``) lists every code
that reaches a molecule and how, so ``tests/test_unii_index.py`` can hold both directions over the
real snapshot: no name shown as not in the catalog carries a code that reaches a molecule, and
every matched row's code reaches the molecule it is listed under.

Product names are used as names only: no logos, no packaging, no claim beyond the ingredient
list. Every value here is from the source (``from_source``).
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path

import yaml

from ..config import PRODUCTS_CACHE_TTL_DAYS, RAW_CACHE, SEEDS_DIR, UNII_CACHE_TTL_DAYS
from ..sources import cache, dailymed, fda_unii, pubchem, wikidata
from ..sources.registry import assert_not_blocked
from .confidence import FROM_SOURCE
from .relationships import load_food_hubs, load_worlds

log = logging.getLogger("mfetl")

PRODUCTS_YAML = SEEDS_DIR / "products.yaml"
MIN_MOLECULES = 3
# Product comparisons (SEO run 2, 2026-10-28): /whats-in/<a>-vs-<b>, two labels' ingredient lists
# side by side. The seed names the pairs; the web computes the shared and unshared lists from the
# two product records. The answer line is MoleculeFinder's, written from the labels' facts.
PAIRS_YAML = SEEDS_DIR / "product_pairs.yaml"
PAIR_SOURCE = "MoleculeFinder curated, from the labels on DailyMed"
# The page's kinds, in the order the /whats-in index lists them. "moment" holds the worlds
# that are an experience, not a thing you buy (the smell after rain, falling asleep, a workout).
# "chemistry" (Run C2) holds class pages: a class of everyday chemicals (PFAS), not a product.
KINDS = ("food", "drink", "medicine", "cosmetic", "household", "chemistry", "moment")
# The order a combined row's molecules are listed in: curated first, then the world, then Wikidata.
SOURCE_KEYS = ("dailymed", "class", "curated", "world", "wikidata")
# Sources that stand alone on a row (no second source).
SOLE_SOURCES = ("dailymed", "class")
UNII_ALIASES_YAML = SEEDS_DIR / "unii_aliases.yaml"
CLASSES_YAML = SEEDS_DIR / "product_classes.yaml"

DAILYMED_DIR = RAW_CACHE / "dailymed"
SPL_PREFIX = "spl1"                   # bump when ``dailymed.parse`` changes what it keeps
PARTS_CACHE = RAW_CACHE / "wikidata" / "product_parts.json"
# pubchem/unii2-<cid>.json: the codes shaped like a UNII in the CID's full synonym list. Was "unii"
# (the ``UNII-`` entries only); bumped 2026-10-24 so a pinned build, which never expires an entry,
# re-reads the lists with the bare codes kept (pubchem.uniis). The old files are left to be evicted.
UNII_PREFIX = "unii2"
PARENT_PREFIX = "uniiparent"          # pubchem/uniiparent-<UNII>.json: the UNII's parent CIDs, asked by synonym
CID_PARENT_PREFIX = "parent"          # pubchem/parent-<cid>.json: a CID's parent CIDs, asked by the FDA's CID
MIN_PARENT_CARBONS = 2
# How a UNII reaches a molecule, in the committed index: directly, by the FDA's PubChem CID or
# InChIKey for it, by PubChem's own synonym list, or by the hand list of substances; or by rule.
DIRECT_HOWS = ("cid", "inchikey", "pubchem", "substance")
RULE_HOWS = ("parent", "skeleton", "alias")

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_QID = re.compile(r"^Q[1-9][0-9]*$")
_DASHES = ("—", "–")


class ProductSeedError(ValueError):
    """products.yaml is malformed. The build stops and names every problem."""


# ── seed ──────────────────────────────────────────────────────────────────────
def load_seed(path: Path | None = None, worlds: list[dict] | None = None) -> list[dict]:
    """Read and validate products.yaml. Every problem is reported at once."""
    path = path or PRODUCTS_YAML
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    rows = data.get("products") or []
    world_slugs = {w["slug"] for w in (worlds if worlds is not None else load_worlds())}
    errors: list[str] = []
    seen_slug: set[str] = set()
    seen_source: dict[tuple[str, str], str] = {}
    out: list[dict] = []
    for i, row in enumerate(rows):
        where = f"products[{i}]"
        if not isinstance(row, dict):
            errors.append(f"{where}: not a mapping")
            continue
        slug, name, kind = row.get("slug"), row.get("name"), row.get("kind")
        where = f"{where} {slug or '?'}"
        if not isinstance(slug, str) or not _SLUG.match(slug):
            errors.append(f"{where}: slug must be lowercase words joined by hyphens")
        elif slug in seen_slug:
            errors.append(f"{where}: slug used twice")
        else:
            seen_slug.add(slug)
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{where}: no name")
        elif any(d in name for d in _DASHES):
            errors.append(f"{where}: name has an em or en dash")
        if kind not in KINDS:
            errors.append(f"{where}: kind must be one of {', '.join(KINDS)}")
        sources = [k for k in SOURCE_KEYS if row.get(k)]
        unknown = sorted(set(row) - {"slug", "name", "kind", *SOURCE_KEYS})
        if unknown:
            errors.append(f"{where}: unknown field(s) {', '.join(unknown)}")
        if not sources:
            errors.append(f"{where}: needs one of {', '.join(SOURCE_KEYS)}")
            continue
        if "dailymed" in sources and len(sources) > 1:
            errors.append(f"{where}: a DailyMed label stands alone (no second source)")
            continue
        if "class" in sources and len(sources) > 1:
            errors.append(f"{where}: a class page stands alone (no second source)")
            continue
        if ("class" in sources) != (kind == "chemistry"):
            errors.append(f"{where}: a class page is kind chemistry, and only a class page is")
        items = []
        for key in sources:
            value = str(row[key]).strip()
            if key == "dailymed" and not dailymed.SETID_RE.match(value):
                errors.append(f"{where}: not a DailyMed set id: {value}")
            if key == "wikidata" and not _QID.match(value):
                errors.append(f"{where}: not a Wikidata QID: {value}")
            if key == "world" and value not in world_slugs:
                errors.append(f"{where}: no world {value!r} in worlds.yaml")
            if key in ("curated", "class") and not _SLUG.match(value):
                errors.append(f"{where}: not a {'food hub' if key == 'curated' else 'class'} slug: {value}")
            if (key, value) in seen_source:
                errors.append(f"{where}: same {key} item as {seen_source[(key, value)]}")
            seen_source[(key, value)] = str(slug)
            items.append({"source": key, "item": value})
        entry = {"slug": slug, "name": " ".join(str(name).split()), "kind": kind, **items[0]}
        if len(items) > 1:
            entry["also"] = items[1:]
        out.append(entry)
    if errors:
        raise ProductSeedError("products.yaml:\n  " + "\n  ".join(errors))
    return out


# ── class pages (Run C2) ──────────────────────────────────────────────────────
_ATOM = re.compile(r"([A-Z][a-z]?)(\d*)")


def formula_counts(formula: str | None) -> dict[str, int]:
    """{"C": 8, "H": 1, "F": 15, ...} from a molecular formula; {} for none or a charged one."""
    if not formula or not re.fullmatch(r"(?:[A-Z][a-z]?\d*)+", formula):
        return {}
    out: dict[str, int] = {}
    for el, n in _ATOM.findall(formula):
        out[el] = out.get(el, 0) + (int(n) if n else 1)
    return out


def perfluorinated(formula: str | None) -> bool:
    """The PFAS rule for a class member, read off the formula alone: carbon and fluorine, at most
    one hydrogen (the acid's), and at least 2C - 1 fluorines, which is what a fully fluorinated
    carbon chain carries (a carboxylic acid's carbonyl carbon is the one without fluorine)."""
    c = formula_counts(formula)
    carbons, fluorines = c.get("C", 0), c.get("F", 0)
    return carbons >= 2 and c.get("H", 0) <= 1 and fluorines >= 2 * carbons - 1


CLASS_RULES = {"perfluorinated": perfluorinated}


def load_classes(path: Path | None = None) -> dict[str, dict]:
    """product_classes.yaml -> {class slug: {"name", "title", "rule", "molecules": [slug, ...]}}."""
    path = path or CLASSES_YAML
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    errors: list[str] = []
    out: dict[str, dict] = {}
    for slug, row in data.items():
        if not _SLUG.match(str(slug)) or not isinstance(row, dict):
            errors.append(f"{slug}: a class is a slug with a mapping")
            continue
        mols = row.get("molecules") or []
        if row.get("rule") not in CLASS_RULES:
            errors.append(f"{slug}: rule must be one of {', '.join(CLASS_RULES)}")
        if not row.get("name") or not row.get("title") or len(mols) < MIN_MOLECULES:
            errors.append(f"{slug}: needs a name, a title and {MIN_MOLECULES}+ molecules")
        if any(d in str(row.get("name", "")) + str(row.get("title", "")) for d in _DASHES):
            errors.append(f"{slug}: em or en dash")
        out[str(slug)] = {"name": str(row.get("name")), "title": str(row.get("title")),
                          "rule": row.get("rule"), "molecules": [str(m) for m in mols]}
    if errors:
        raise ProductSeedError("product_classes.yaml:\n  " + "\n  ".join(errors))
    return out


def class_members(cls_slug: str, cls: dict, by_slug: dict[str, dict]) -> list[dict]:
    """The class's molecule entries, each checked: a catalog molecule whose formula passes the
    class's rule. A slug that fails either stops the build, naming it."""
    rule = CLASS_RULES[cls["rule"]]
    bad = [s for s in cls["molecules"] if s not in by_slug]
    bad += [f"{s} ({by_slug[s].get('molecular_formula')} fails the {cls['rule']} rule)"
            for s in cls["molecules"] if s in by_slug and not rule(by_slug[s].get("molecular_formula"))]
    if bad:
        raise ProductSeedError(f"product_classes.yaml {cls_slug}: " + ", ".join(bad))
    out = []
    for s in cls["molecules"]:
        counts = formula_counts(by_slug[s].get("molecular_formula"))
        # The atoms the rule read, so the page's line is the formula's own numbers.
        out.append({"slug": s, "role": "class", "class": cls_slug,
                    "carbons": counts.get("C", 0), "fluorines": counts.get("F", 0)})
    return out


# ── fetch stage: warm the caches ──────────────────────────────────────────────
def _spl_path(setid: str) -> Path:
    return DAILYMED_DIR / f"{SPL_PREFIX}-{setid}.json"


def spl_cached(setid: str) -> dict | None:
    """The cached label, or None when it is not cached (or expired). A label DailyMed answered
    404 for is cached as ``{"missing": true}`` so it is not asked again until it expires."""
    hit = cache.read_json(_spl_path(setid), PRODUCTS_CACHE_TTL_DAYS)
    return hit.value if hit is not None else None


def _read_parts() -> dict[str, dict]:
    if not PARTS_CACHE.exists():
        return {}
    try:
        raw = json.loads(PARTS_CACHE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    entries = raw.get("entries") if isinstance(raw, dict) else None
    return entries if isinstance(entries, dict) else {}


def _parent_path(unii: str) -> Path:
    return RAW_CACHE / "pubchem" / f"{PARENT_PREFIX}-{unii}.json"


def _cid_parent_path(cid: int) -> Path:
    return RAW_CACHE / "pubchem" / f"{CID_PARENT_PREFIX}-{int(cid)}.json"


def _label_parent_path(unii: str, table: fda_unii.Table | None) -> Path:
    """Where a label UNII's parent CIDs are cached: by the FDA's PubChem CID for it when the table
    has one (the question PubChem can always answer), else by the ``UNII-`` synonym."""
    cid = table.cid(unii) if table is not None else None
    return _cid_parent_path(cid) if cid else _parent_path(unii)


def label_uniis(seed: list[dict], spl=None) -> list[str]:
    """Every ingredient and active-moiety UNII on the seeded labels the cache holds, sorted."""
    out: set[str] = set()
    for p in seed:
        if p["source"] != "dailymed":
            continue
        label = (spl or spl_cached)(p["item"])
        for ing in (label or {}).get("ingredients") or []:
            if ing.get("unii"):
                out.add(ing["unii"])
            out.update(m for m in ing.get("moiety") or [] if m)
    return sorted(out)


def read_parents(uniis, table: fda_unii.Table | None = None) -> dict[str, list[int]]:
    """The cached parent CIDs per label UNII (written by the fetch stage): by the FDA's CID for
    the UNII when the table has one, else by synonym. Missing means not looked up."""
    out: dict[str, list[int]] = {}
    for u in uniis:
        hit = cache.read_json(_label_parent_path(u, table), UNII_CACHE_TTL_DAYS)
        if hit is not None and isinstance(hit.value, list):
            out[u] = [int(c) for c in hit.value]
    return out


def read_props(cids) -> dict[int, dict]:
    """PubChem properties from the pipeline's permanent per-CID cache (``props-<cid>.json``)."""
    out: dict[int, dict] = {}
    for c in cids:
        path = RAW_CACHE / "pubchem" / f"props-{c}.json"
        if path.exists():
            try:
                value = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(value, dict):
                out[int(c)] = value
    return out


def warm(seed: list[dict], cids: list[int], fetch_uniis, fetch_props=None,
         fetch_parents=None, fetch_table=None, fetch_cid_parents=None) -> dict[str, int]:
    """Fetch whatever the product pages need that the cache does not hold fresh: each seeded
    DailyMed label, the seeded Wikidata items' parts, the FDA's UNII table (``fetch_table``,
    default ``fda_unii.warm``; a test passes ``lambda: None`` for no table), every molecule's UNII
    codes (through ``fetch_uniis``, the pipeline's batched per-CID cache), the PubChem parent of
    every label UNII no molecule claims (by the FDA's CID for it, ``fetch_cid_parents``, else by
    synonym, ``fetch_parents``), and those parents' properties (``fetch_props``, the pipeline's
    permanent property cache) for the InChIKey skeleton. Returns request counts for the log."""
    assert_not_blocked("dailymed")
    labels = fetched_labels = 0
    for p in seed:
        if p["source"] != "dailymed":
            continue
        labels += 1
        if spl_cached(p["item"]) is None:
            parsed = dailymed.fetch(p["item"])
            cache.write_json(_spl_path(p["item"]), parsed if parsed is not None else {"missing": True})
            fetched_labels += 1

    qids = sorted({s["item"] for p in seed for s in [p, *p.get("also", [])] if s["source"] == "wikidata"})
    stored = _read_parts()
    at = cache.now()
    # An item never fetched is a miss in every mode: a pinned build treats any CACHED entry as
    # fresh, but there is nothing cached to pin to until the first fetch.
    missing = [q for q in qids if q not in stored
               or not cache.is_fresh(stored[q].get("fetched_at"), PRODUCTS_CACHE_TTL_DAYS, at)]
    if missing:
        got = wikidata.parts_for_qids(missing)
        for q in missing:
            row = got.get(q) or {}
            stored[q] = {prop: list(row.get(prop) or []) for prop in wikidata.PART_PROPERTIES}
            stored[q]["missing"] = q not in got
            stored[q]["fetched_at"] = at
        PARTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        PARTS_CACHE.write_text(json.dumps({cache.ENVELOPE_KEY: cache.ENVELOPE_VERSION,
                                           "fetched_at": at, "entries": stored}, sort_keys=True))
    # The molecule side of the join: the FDA's table first, PubChem's synonym lists as the fallback,
    # the hand list's substances; the same reading ``unii_index`` makes of the assembled records.
    table = fetch_table() if fetch_table is not None else fda_unii.warm()
    pubchem_codes = fetch_uniis(cids) or {}
    inchikeys = {c: (p.get("InChIKey") or None) for c, p in read_props(cids).items()}
    known: set[str] = set(load_unii_substances())
    for c in cids:
        known.update(_record_codes(c, inchikeys.get(c), pubchem_codes.get(c) or [], table))

    # Salts, hydrates and stereo forms: the parent of every label UNII no molecule claims, asked
    # by the FDA's PubChem CID for the UNII when the table has one, else by the UNII- synonym.
    fetch_parents = fetch_parents or pubchem.unii_parents
    fetch_cid_parents = fetch_cid_parents or pubchem.cid_parents
    unclaimed = [u for u in label_uniis(seed) if u not in known]
    parents = read_parents(unclaimed, table)
    asked = [u for u in unclaimed if u not in parents]
    for i, u in enumerate(asked, 1):
        cid = table.cid(u) if table is not None else None
        parents[u] = fetch_cid_parents(cid) if cid else fetch_parents(u)
        cache.write_json(_label_parent_path(u, table), parents[u])
        if i % 100 == 0:
            log.info("  products: parent compounds %d/%d", i, len(asked))
    parent_cids = sorted({c for cs in parents.values() for c in cs} - set(cids))
    if fetch_props is not None and parent_cids:
        fetch_props(parent_cids)
    log.info("  products: %d DailyMed label(s), %d fetched; %d Wikidata item(s), %d fetched; "
             "UNII codes for %d CID(s), FDA table %s; parents of %d unclaimed label UNII(s), %d fetched",
             labels, fetched_labels, len(qids), len(missing), len(cids),
             f"{len(table)} UNIIs ({table.file})" if table is not None else "absent", len(unclaimed), len(asked))
    return {"labels": labels, "labels_fetched": fetched_labels, "items": len(qids),
            "items_fetched": len(missing), "parents": len(unclaimed), "parents_fetched": len(asked),
            "fda_uniis": len(table) if table is not None else 0}


def read_uniis(cids: list[int]) -> dict[int, list[str]]:
    """The cached UNII codes per CID (written by the fetch stage). Missing means no codes."""
    out: dict[int, list[str]] = {}
    for c in cids:
        hit = cache.read_json(RAW_CACHE / "pubchem" / f"{UNII_PREFIX}-{c}.json", UNII_CACHE_TTL_DAYS)
        if hit is not None and isinstance(hit.value, list):
            out[c] = [str(u) for u in hit.value]
    return out


# ── compile ───────────────────────────────────────────────────────────────────
def _record_codes(cid: int, inchikey: str | None, pubchem_codes: list[str],
                  table: fda_unii.Table | None) -> dict[str, str]:
    """The UNIIs that name one record, code -> how (trust run 3), from both sources. The FDA's
    table: every UNII whose PubChem CID is the record's (``cid``), then every UNII whose InChIKey
    is the record's exactly (``inchikey``; the FDA links some substances to another CID of the
    same structure). PubChem's own synonym list for the CID (``pubchem``): a ``UNII-`` entry, or a
    bare code the table lists (a bare code the table does not know is a screening-library id of
    the same shape, not a UNII). The two are a UNION, not a preference: the FDA registers many
    forms with no PubChem link ("TOCOPHEROL", "CITRIC ACID", the unspecified forms) that PubChem
    files under the molecule's CID, and the FDA links other codes to a different PubChem CID of
    the same substance than PubChem lists them under (zinc oxide), so either source alone loses
    codes the other has. Where the two disagree about WHICH record a code names, ``unii_index``
    lets the FDA's explicit link decide. A code the FDA registers as a source-defined substance
    (``fda_unii.SOURCE_DEFINED_KINDS``: cochineal, corn syrup) joins no record here, whatever
    either source links it to; only the hand list may carry such a code."""
    got: dict[str, str] = {}
    if table is not None:
        if cid > 0:
            for u in table.by_cid.get(cid, []):
                if table.defined_by_structure(u):
                    got[u] = "cid"
        if inchikey:
            for u in table.by_inchikey.get(inchikey, []):
                if table.defined_by_structure(u):
                    got.setdefault(u, "inchikey")
    for code in pubchem_codes:
        u, bare = pubchem.split_unii(code)
        if bare and (table is None or u not in table):
            continue
        if table is not None and not table.defined_by_structure(u):
            continue
        got.setdefault(u, "pubchem")
    return got


# The routes that state what a code means on the FDA's or a human's authority. A code two records
# claim goes to the one that holds it by such a route, when exactly one does; a code PubChem's
# lists put on two records, or two records hold by the FDA's own links, matches neither.
AUTHORITATIVE_HOWS = ("cid", "inchikey", "substance")


def _owner(claims: dict[str, str]) -> tuple[str, str] | None:
    if len(claims) == 1:
        return next(iter(claims.items()))
    decided = [(slug, how) for slug, how in claims.items() if how in AUTHORITATIVE_HOWS]
    return decided[0] if len(decided) == 1 else None


def unii_index(records: list[dict], uniis: dict[int, list[str]], table: fda_unii.Table | None = None,
               substances: dict[str, str] | None = None) -> dict[str, tuple[str, str]]:
    """UNII -> (slug, how), for UNIIs one molecule claims (``_record_codes`` per record, plus the
    hand list's ``substances``). A code two molecules share (a medicine and its own drug-form
    duplicate) goes to the one the FDA's own link or the hand list gives it to, and when neither
    or both decide it, to neither: a miss before a wrong match (``_owner``). A substance naming no
    molecule, or a code the FDA table on hand does not know, stops the build."""
    by_slug = {r["slug"] for r in records}
    for u, slug in (substances or {}).items():
        if slug not in by_slug:
            raise ProductSeedError(f"unii_aliases.yaml substances: {u} names no molecule {slug!r}")
        if table is not None and u not in table:
            raise ProductSeedError(f"unii_aliases.yaml substances: {u} is not a UNII in the FDA table ({table.file})")
    owners: dict[str, dict[str, str]] = {}
    for r in records:
        cid = int(r["cid"])
        codes = _record_codes(cid, r.get("inchikey"), uniis.get(cid, []) if cid > 0 else [], table)
        for u, slug in (substances or {}).items():
            if slug == r["slug"]:
                codes.setdefault(u, "substance")
        for u, how in codes.items():
            owners.setdefault(u, {})[r["slug"]] = how
    decided = {u: _owner(claims) for u, claims in owners.items()}
    return {u: owner for u, owner in decided.items() if owner is not None}


_CARBON = re.compile(r"C(?![a-z])(\d*)")


def carbon_count(formula: str | None) -> int:
    """Carbon atoms in a molecular formula ("C12H22O11" -> 12; "Cl", "Ca" and "Cu" are not carbon)."""
    return sum(int(n or 1) for n in _CARBON.findall(formula or ""))


def _hand_list(path: Path | None, section: str) -> dict[str, str]:
    path = path or UNII_ALIASES_YAML
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return {str(u).strip(): str(s).strip() for u, s in (data.get(section) or {}).items()}


def load_unii_aliases(path: Path | None = None) -> dict[str, str]:
    """The hand list's ``aliases``: a FORM's UNII -> molecule slug (a hydrate, an unspecified form,
    a stereo form), for forms the parent rule does not reach. A hand ruling is final."""
    return _hand_list(path, "aliases")


def load_unii_substances(path: Path | None = None) -> dict[str, str]:
    """The hand list's ``substances`` (trust run 3): a molecule's OWN UNII -> its slug, for records
    neither the FDA table nor PubChem links to their code (hand-modelled polymers and proteins, a
    biologic with no PubChem synonyms, a tautomer the FDA draws differently)."""
    return _hand_list(path, "substances")


def parent_index(records: list[dict], parents: dict[str, list[int]], props: dict[int, dict],
                 aliases: dict[str, str] | None = None,
                 table: fda_unii.Table | None = None) -> dict[str, tuple[str, str]]:
    """UNII -> (slug, how) for label UNIIs no molecule claims: ``parent`` (the parent CID is a
    catalog CID), ``skeleton`` (one catalog molecule shares the InChIKey first block of a parent,
    or of the FDA's own structure for the UNII) or ``alias`` (the hand list, which is final and
    wins over the two rules). Exactly one molecule must qualify, with two or more carbons. A code
    the FDA registers as a source-defined substance (corn syrup) is no form of any molecule, so
    neither rule applies to it; only the hand list may."""
    by_slug = {r["slug"]: r for r in records}
    cid_owners: dict[int, set[str]] = {}
    skel_owners: dict[str, set[str]] = {}
    for r in records:
        if int(r["cid"]) > 0:
            cid_owners.setdefault(int(r["cid"]), set()).add(r["slug"])
        if r.get("inchikey"):
            skel_owners.setdefault(str(r["inchikey"])[:14], set()).add(r["slug"])
    out: dict[str, tuple[str, str]] = {}
    for u, cids in parents.items():
        if table is not None and not table.defined_by_structure(u):
            continue
        how = "parent"
        found = set().union(*(cid_owners.get(c, set()) for c in cids)) if cids else set()
        if not found:
            how = "skeleton"
            keys = {str((props.get(c) or {}).get("InChIKey") or "")[:14] for c in cids}
            keys.add(str((table.inchikey(u) if table is not None else None) or "")[:14])
            keys -= {""}
            found = set().union(*(skel_owners.get(k, set()) for k in keys)) if keys else set()
        if len(found) == 1:
            slug = next(iter(found))
            if carbon_count(by_slug[slug].get("molecular_formula")) >= MIN_PARENT_CARBONS:
                out[u] = (slug, how)
    for u, slug in (aliases or {}).items():
        if slug not in by_slug:
            raise ProductSeedError(f"unii_aliases.yaml: {u} names no molecule {slug!r}")
        out[u] = (slug, "alias")              # a hand ruling is final (trust run 3; was a gap-filler)
    return out


def _resolve(ing: dict, by_unii: dict[str, tuple[str, str]], by_parent: dict[str, tuple[str, str]]):
    """(slug, how, the code it was decided on) for one label ingredient, or (None, None, None)."""
    if ing.get("unii") and ing["unii"] in by_unii:
        return by_unii[ing["unii"]][0], "unii", ing["unii"]
    for m in ing.get("moiety") or []:
        if m in by_unii:
            return by_unii[m][0], "moiety", m
    # By rule. An active's parent is looked up from its ACTIVE MOIETY, the label's own statement of
    # what the active is: zinc acetate's moiety is zinc, so a lozenge never lists acetic acid as its
    # active, and methylphenidate hydrochloride (whose UNII PubChem files under the dex form) reaches
    # methylphenidate. An ingredient with no moiety (an excipient) is looked up by its own UNII.
    for u in ing.get("moiety") or [ing.get("unii")]:
        if u and u in by_parent:
            return by_parent[u][0], by_parent[u][1], u
    # A hand ALIAS on the active's own code is a ruling on exactly that code, so it still applies
    # when the moiety reached nothing (trust run 3: magnesium carbonate hydrate as an active, whose
    # moiety is the carbonate ion). The two rules are never applied to an active's own code.
    own = by_parent.get(ing.get("unii") or "")
    if own is not None and own[1] == "alias":
        return own[0], own[1], ing["unii"]
    return None, None, None


def _dailymed_molecules(spl: dict, by_unii: dict[str, tuple[str, str]],
                        by_parent: dict[str, tuple[str, str]] | None = None) -> tuple[list[dict], list[str]]:
    """The label's molecules in label order, actives first, and the names of ingredients that
    are not MoleculeFinder molecules. One entry per molecule; active wins over inactive. Each
    entry carries the code it was matched on (``unii``: the ingredient's own, or its moiety's)."""
    purpose = dailymed.purposes(spl)
    # The strength the label states for an active ("200 mg"), and what for ("tablet"), SEO run 2.
    strength = dailymed.strengths(spl)
    per = dailymed.strength_per(spl)
    found: dict[str, dict] = {}
    unmatched: list[str] = []
    for role in ("active", "inactive"):
        for ing in spl.get("ingredients", []):
            if ing["role"] != role:
                continue
            slug, via, code = _resolve(ing, by_unii, by_parent or {})
            if slug is None:
                if ing["name"] not in unmatched:
                    unmatched.append(ing["name"])
                continue
            if slug in found:
                continue
            entry = {"slug": slug, "role": role, "listed_as": ing["name"], "match": via, "unii": code}
            if role == "active" and purpose.get(ing["name"]):
                entry["purpose"] = purpose[ing["name"]]
            if role == "active" and strength.get(ing["name"]):
                entry["strength"] = strength[ing["name"]]
                if per:
                    entry["strength_per"] = per
            found[slug] = entry
    return list(found.values()), unmatched


def _not_in_catalog(unmatched: list[str], unmatched_actives: list[str], mols: list[dict],
                    spl: dict | None = None) -> list[dict]:
    """The label's ingredients that are not MoleculeFinder molecules, as the label names them: label
    order, actives first, one entry per name (Trust run 2, 2026-10-24), each with the label's UNII
    for it (trust run 3; None when the label gives none). Shown on the page as plain unlinked text,
    never matched to anything; a name a listed molecule already carries is left out. The actives
    here are exactly ``actives_not_in_catalog``."""
    shown = {m["listed_as"] for m in mols}
    actives = set(unmatched_actives)
    codes: dict[str, str | None] = {}
    for ing in (spl or {}).get("ingredients", []):
        codes.setdefault(ing["name"], ing.get("unii") or None)
    return [{"name": n, "role": "active" if n in actives else "inactive", "unii": codes.get(n)}
            for n in unmatched if n not in shown]


def _world_molecules(world: dict) -> list[dict]:
    captions = {j["slug"]: j.get("caption") for j in (world.get("journey") or [])}
    out = []
    for s in world.get("molecules") or []:
        entry = {"slug": s, "role": "world"}
        if captions.get(s):
            entry["caption"] = captions[s]
        out.append(entry)
    return out


def _wikidata_molecules(parts: dict, by_qid: dict[str, str]) -> tuple[list[dict], int]:
    """The item's parts that are molecules, "has part(s)" first, each in Wikidata's own order,
    and how many parts the item lists in all."""
    found: dict[str, dict] = {}
    listed = 0
    for prop in wikidata.PART_PROPERTIES:
        for q in parts.get(prop) or []:
            listed += 1
            s = by_qid.get(q)
            if s and s not in found:
                found[s] = {"slug": s, "role": "part", "property": prop}
    return list(found.values()), listed


def curated_hubs(records: list[dict]) -> dict[str, dict]:
    """hub slug -> {"name", "molecules": [{"slug", "note"?}]}: the curated ``kind: food``
    memberships on the records (food_hubs.yaml plus the curated overlays), in food_hubs.yaml's
    order and then by slug. The same membership the /in/<hub> page lists."""
    order = {h: [*v["molecules"]] for h, v in load_food_hubs().items()}
    names = {h: v["name"] for h, v in load_food_hubs().items()}
    members: dict[str, dict[str, dict]] = {}
    for r in records:
        for c in r.get("categories") or []:
            if c.get("kind") != "food" or c.get("source") != "curated":
                continue
            entry = {"slug": r["slug"]}
            if c.get("note"):
                entry["note"] = c["note"]
            members.setdefault(c["slug"], {})[r["slug"]] = entry
            names.setdefault(c["slug"], c.get("name") or c["slug"])
    out = {}
    for hub, mols in members.items():
        listed = order.get(hub, [])
        ranked = sorted(mols, key=lambda s: (listed.index(s) if s in listed else len(listed), s))
        out[hub] = {"name": names[hub], "molecules": [mols[s] for s in ranked]}
    return out


_SOURCE_WORDS = {"curated": "MoleculeFinder's curated list", "world": "the world",
                 "wikidata": "Wikidata"}


def _queue_rows(queue: dict[str, dict]) -> list[dict]:
    """The next tranche's queue: label actives MoleculeFinder lacks, then inactives, each by how
    many seeded labels list it."""
    rows = []
    for q in queue.values():
        name = q["names"].most_common(1)[0][0]
        rows.append({"section": "active" if q["active"] else "inactive", "name": name,
                     "unii": q["unii"] or "", "labels": len(q["labels"]),
                     "labels_as_active": len(q["active"]), "pubchem_parent_cid": " ".join(map(str, q["parents"])),
                     "example_products": " ".join(sorted(q["products"])[:3])})
    rows.sort(key=lambda r: (r["section"] != "active", -r["labels"], r["name"].lower()))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


QUEUE_FIELDS = ("rank", "section", "name", "unii", "labels", "labels_as_active",
                "pubchem_parent_cid", "example_products")


def write_queue(rows: list[dict], path: Path) -> None:
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=QUEUE_FIELDS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in QUEUE_FIELDS})


def unii_index_entries(by_unii: dict[str, tuple[str, str]], by_parent: dict[str, tuple[str, str]],
                       table: fda_unii.Table | None) -> dict[str, dict]:
    """Every code that reaches a molecule, with how and the FDA's display name for the code
    (trust run 3): the direct index, then the by-rule resolutions of the label UNIIs. Sorted by
    code, so the committed file diffs line by line."""
    out: dict[str, dict] = {}
    for source in (by_unii, by_parent):
        for u, (slug, how) in source.items():
            out.setdefault(u, {"slug": slug, "how": how, "name": table.name(u) if table is not None else None})
    return dict(sorted(out.items()))


def write_unii_index(entries: dict[str, dict], path: Path, table: fda_unii.Table | None = None) -> None:
    """``data/seed/unii_index.json``: one line per code, so a weekly diff reads as codes moving."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"  {json.dumps(u)}: {json.dumps(e, ensure_ascii=False)}" for u, e in entries.items()]
    body = ",\n".join(lines)
    head = {"source": (f"FDA Substance Registration System ({table.file})" if table is not None else None),
            "how": {"direct": list(DIRECT_HOWS), "by_rule": list(RULE_HOWS)}, "count": len(entries)}
    path.write_text("{\n" + ",\n".join(f" {json.dumps(k)}: {json.dumps(v)}" for k, v in head.items())
                    + ",\n \"uniis\": {\n" + body + "\n }\n}\n")


def compile_products(records: list[dict], seed: list[dict] | None = None, *,
                     spl=None, parts: dict[str, dict] | None = None,
                     uniis: dict[int, list[str]] | None = None,
                     worlds: list[dict] | None = None,
                     parents: dict[str, list[int]] | None = None,
                     props: dict[int, dict] | None = None,
                     aliases: dict[str, str] | None = None,
                     hubs: dict[str, dict] | None = None,
                     classes: dict[str, dict] | None = None,
                     table: fda_unii.Table | None | bool = None,
                     substances: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    """(products that pass the gate, the gate report). Reads only caches and records.

    ``spl`` (setid -> parsed label or ``{"missing": True}`` or None), ``parts``, ``uniis``,
    ``parents``, ``props``, ``aliases``, ``substances`` and ``hubs`` default to the cache and
    seeds; tests pass their own. ``table`` is the FDA's UNII table: None reads the cache and
    REFUSES when it is not there while a label is seeded (the fetch stage puts it there); a test
    passes ``False`` for no table. The report's ``next_tranche_queue`` is the rows ``write_queue``
    writes, and its ``unii_index`` the entries ``write_unii_index`` writes."""
    seed = load_seed() if seed is None else seed
    worlds = load_worlds() if worlds is None else worlds
    spl = spl or spl_cached
    parts = _read_parts() if parts is None else parts
    uniis = read_uniis([int(r["cid"]) for r in records if int(r["cid"]) > 0]) if uniis is None else uniis
    if table is None:
        table = fda_unii.cached()
        if table is None and any(p["source"] == "dailymed" for p in seed):
            raise SystemExit("the FDA UNII table is not in data/raw_cache (fda/); run `mfetl fetch` first, "
                             "which fetches it. Matching labels without it would silently miss molecules.")
    elif table is False:
        table = None
    substances = load_unii_substances() if substances is None else substances
    by_slug = {r["slug"]: r for r in records}
    by_unii = unii_index(records, uniis, table, substances)
    if parents is None:
        parents = read_parents(label_uniis(seed, spl), table)
    if props is None:
        props = read_props(sorted({c for cs in parents.values() for c in cs}))
    # Every unclaimed label UNII reaches the rules, looked up or not: the FDA's InChIKey for it
    # can decide a skeleton match with no parent at all.
    unclaimed = {u: list(c) for u, c in parents.items() if u not in by_unii}
    for u in label_uniis(seed, spl):
        if u not in by_unii:
            unclaimed.setdefault(u, [])
    by_parent = parent_index(records, unclaimed, props,
                             load_unii_aliases() if aliases is None else aliases, table)
    hubs = curated_hubs(records) if hubs is None else hubs
    classes = load_classes() if classes is None else classes
    by_qid = {r["wikidata_qid"]: r["slug"] for r in records if r.get("wikidata_qid")}
    titles = {r["slug"]: r["title"] for r in records}
    world_by_slug = {w["slug"]: w for w in worlds}

    products: list[dict] = []
    failed: list[dict] = []
    queue: dict[str, dict] = {}
    rule_matches: Counter[str] = Counter()
    code_matches: Counter[str] = Counter()
    for p in seed:
        base = {"slug": p["slug"], "name": p["name"], "kind": p["kind"]}
        listed = 0
        unmatched: list[str] = []
        if p["source"] == "dailymed":
            label = spl(p["item"])
            if not label or label.get("missing"):
                failed.append({**base, "source": "dailymed", "item": p["item"],
                               "reason": "label not found on DailyMed (withdrawn, archived or not yet fetched)",
                               "matched": []})
                continue
            if not str(label.get("doc_type") or "").upper().startswith("HUMAN"):
                failed.append({**base, "source": "dailymed", "item": p["item"],
                               "reason": f"not a label for people (DailyMed lists it as {label.get('doc_type') or 'unknown'})",
                               "matched": []})
                continue
            # A label that gives no UNII for an ingredient cannot be matched by code for that
            # ingredient, and the page would then name it as not a MoleculeFinder molecule on no
            # evidence (trust run 3: Keflex's label names "Cellulose" and "FD&C Blue No. 1" with no
            # codes, and both are molecules here). Such a label is not matched at all.
            uncoded = list(dict.fromkeys(i["name"] for i in label.get("ingredients", []) if not i.get("unii")))
            if uncoded:
                failed.append({**base, "source": "dailymed", "item": p["item"],
                               "reason": (f"the label gives no UNII code for {len(uncoded)} ingredient(s) "
                                          f"({', '.join(uncoded)}), which cannot be matched by code"),
                               "matched": []})
                continue
            mols, unmatched = _dailymed_molecules(label, by_unii, by_parent)
            matched_actives = {m["listed_as"] for m in mols if m["role"] == "active"}
            # The label's active ingredients that are not MoleculeFinder molecules, by the label's own
            # name: a page whose active is not in the catalog still says what the active is.
            unmatched_actives = [i["name"] for i in label.get("ingredients", [])
                                 if i["role"] == "active" and i["name"] in unmatched
                                 and i["name"] not in matched_actives]
            listed = len(label.get("ingredients") or [])
            source = {"type": "dailymed", "setid": p["item"], "labeler": label.get("labeler") or None,
                      "doc_type": label.get("doc_type") or None, "version": label.get("version"),
                      "effective": label.get("effective") or None,
                      "url": dailymed.LABEL_PAGE.format(setid=p["item"])}
            rule_matches.update(m["match"] for m in mols if m["match"] in RULE_HOWS)
            code_matches.update(m["match"] for m in mols if m["match"] in ("unii", "moiety"))
            for ing in label.get("ingredients", []):
                if ing["name"] not in unmatched:
                    continue
                key = ing.get("unii") or "name:" + ing["name"].upper()
                q = queue.setdefault(key, {"unii": ing.get("unii"), "names": Counter(), "labels": set(),
                                           "active": set(), "products": set(),
                                           "parents": parents.get(ing.get("unii") or "", [])})
                q["names"][ing["name"]] += 1
                q["labels"].add(p["item"])
                q["products"].add(p["slug"])
                if ing["role"] == "active":
                    q["active"].add(p["item"])
            sources = [source]
        elif p["source"] == "class":
            cls = classes.get(p["item"])
            if cls is None:
                raise ProductSeedError(f"products.yaml {p['slug']}: no class {p['item']!r} in product_classes.yaml")
            mols = class_members(p["item"], cls, by_slug)
            listed = len(mols)
            words = ["MoleculeFinder's class list"]
            source = {"type": "class", "class": p["item"], "title": cls["title"], "rule": cls["rule"]}
            sources = [source]
        else:
            mols, sources, words, gone = [], [], [], []
            for key, item in [(p["source"], p["item"])] + [(a["source"], a["item"]) for a in p.get("also", [])]:
                if key == "curated":
                    hub = hubs.get(item)
                    if hub is None:
                        raise ProductSeedError(f"products.yaml {p['slug']}: no curated food hub {item!r}")
                    got = [{"slug": m["slug"], "role": "curated", "hub": item,
                            **({"note": m["note"]} if m.get("note") else {})} for m in hub["molecules"]]
                    listed += len(got)
                    sources.append({"type": "curated", "hub": item, "title": hub["name"]})
                elif key == "wikidata":
                    item_parts = parts.get(item) or {}
                    if not item_parts or item_parts.get("missing"):
                        gone.append(item)
                        continue
                    got, n = _wikidata_molecules(item_parts, by_qid)
                    listed += n
                    sources.append({"type": "wikidata", "qid": item,
                                    "url": f"https://www.wikidata.org/wiki/{item}"})
                else:
                    world = world_by_slug[item]
                    got = [m for m in _world_molecules(world) if m["slug"] in by_slug]
                    listed += len(world.get("molecules") or [])
                    sources.append({"type": "world", "world": world["slug"], "title": world.get("title"),
                                    "blurb": world.get("blurb")})
                words.append(_SOURCE_WORDS[key])
                have = {m["slug"] for m in mols}
                new = [m for m in got if m["slug"] not in have]
                if not new and len(sources) > 1:
                    sources.pop()              # a second source that adds no molecule is not cited
                mols += new
            if not sources:
                failed.append({**base, "source": p["source"], "item": p["item"],
                               "reason": "item not found on Wikidata (or not yet fetched)", "matched": []})
                continue
            source = sources[0]
        for m in mols:
            m["title"] = titles[m["slug"]]
        if len(mols) < MIN_MOLECULES:
            if p["source"] == "dailymed":
                what = "the label lists"
            else:
                what = (" and ".join(words) + (" lists" if len(words) == 1 else " list"))
            failed.append({**base, "source": p["source"], "item": p["item"],
                           "reason": (f"{what} {listed} ingredient(s); {len(mols)} "
                                      f"{'is a' if len(mols) == 1 else 'are'} MoleculeFinder "
                                      f"molecule{'' if len(mols) == 1 else 's'}, fewer than {MIN_MOLECULES}"),
                           "matched": [m["slug"] for m in mols]})
            continue
        entry = {**base, "source": source, "listed": listed, "molecules": mols,
                 "confidence": FROM_SOURCE}
        if len(sources) > 1:
            entry["also"] = sources[1:]
        if p["source"] == "dailymed":
            entry["not_in_catalog"] = _not_in_catalog(unmatched, unmatched_actives, mols, label)
            entry["actives_not_in_catalog"] = list(dict.fromkeys(unmatched_actives))
        products.append(entry)

    products.sort(key=lambda x: x["slug"])
    by_kind = Counter(p["kind"] for p in products)
    queue_rows = _queue_rows(queue)
    direct_hows = Counter(how for _, how in by_unii.values())
    report = {
        "seeded": len(seed), "passed": len(products), "failed": len(failed),
        "by_kind": {k: by_kind.get(k, 0) for k in KINDS},
        "min_molecules": MIN_MOLECULES,
        # Label ingredients matched directly, by the ingredient's own code or its active moiety's.
        "matched_by_code": {k: code_matches.get(k, 0) for k in ("unii", "moiety")},
        # Label ingredients reached through PubChem's parent compound or the hand list, by rule.
        "matched_by_rule": {k: rule_matches.get(k, 0) for k in RULE_HOWS},
        # The molecule side of the join (trust run 3): how many codes the FDA's table gives the
        # catalog by CID and by InChIKey, how many come from PubChem's own lists, how many from the
        # hand list; and the table's edition.
        "unii_index": {"fda_table": table.file if table is not None else None,
                       "codes": {k: direct_hows.get(k, 0) for k in DIRECT_HOWS},
                       "molecules_with_a_code": len({slug for slug, _ in by_unii.values()})},
        "failures": sorted(failed, key=lambda f: (KINDS.index(f["kind"]), f["slug"])),
        # The label ingredients MoleculeFinder does not hold, by how many seeded labels list them:
        # the molecules that would open the most product pages. The whole list is
        # data/seed/next_tranche_queue.csv; the top 60 by labels here.
        "label_ingredients_not_in_catalog": [{"name": r["name"], "labels": r["labels"]}
                                             for r in sorted(queue_rows, key=lambda r: (-r["labels"], r["name"].lower()))[:60]],
        "next_tranche_queue": queue_rows,
        "unii_index_entries": unii_index_entries(by_unii, by_parent, table),
    }
    return products, report


def attach_products(records: list[dict], products: list[dict]) -> None:
    """Each molecule's products, the reverse of every product's list, so the two directions are
    one fact and cannot disagree: ``products`` on the record, ordered by kind then name. Only a
    molecule in at least one product gets the field, so every other molecule file is untouched."""
    by_slug = {r["slug"]: r for r in records}
    for r in records:
        r.pop("products", None)
    for p in products:
        for m in p["molecules"]:
            by_slug[m["slug"]].setdefault("products", []).append(
                {"slug": p["slug"], "name": p["name"], "kind": p["kind"], "role": m["role"]})
    for r in records:
        if "products" in r:
            r["products"].sort(key=lambda x: (KINDS.index(x["kind"]), x["name"].lower(), x["slug"]))


# ── product comparisons (SEO run 2, 2026-10-28) ───────────────────────────────
def load_pairs(path: Path | None = None) -> list[dict]:
    """Read and validate product_pairs.yaml -> [{"a", "b", "answer"}]. Every problem is named at
    once, like every other seed. Which products exist is products.yaml; which pairs is this."""
    path = path or PAIRS_YAML
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    rows = data.get("pairs") or []
    errors: list[str] = []
    seen: dict[frozenset, str] = {}
    out: list[dict] = []
    for i, row in enumerate(rows):
        where = f"pairs[{i}]"
        if not isinstance(row, dict):
            errors.append(f"{where}: not a mapping")
            continue
        a, b, answer = row.get("a"), row.get("b"), row.get("answer")
        where = f"{where} {a or '?'}/{b or '?'}"
        unknown = sorted(set(row) - {"a", "b", "answer"})
        if unknown:
            errors.append(f"{where}: unknown field(s) {', '.join(unknown)}")
        if not all(isinstance(s, str) and _SLUG.match(s) for s in (a, b)):
            errors.append(f"{where}: a and b are product slugs")
            continue
        if a == b:
            errors.append(f"{where}: a product cannot be compared with itself")
            continue
        key = frozenset((a, b))
        if key in seen:
            errors.append(f"{where}: same pair as {seen[key]}, one page per pair")
            continue
        seen[key] = f"{a}/{b}"
        if not isinstance(answer, str) or not answer.strip():
            errors.append(f"{where}: no answer line")
            continue
        out.append({"a": a, "b": b, "answer": " ".join(answer.split())})
    if errors:
        raise ProductSeedError("product_pairs.yaml:\n  " + "\n  ".join(errors))
    return out


def pair_slug(a: str, b: str) -> str:
    """The URL segment under /whats-in/: "advil-vs-tylenol-extra-strength"."""
    return f"{a}-vs-{b}"


def _pair_answer_errors(answer: str, a_name: str, b_name: str) -> list[str]:
    """The /vs answer-line rules (relationships._answer_errors), with the two PRODUCT names in place
    of the molecule titles: under 160 characters, one sentence ending in a full stop, no dash, no
    advice or dosing word, and no bare strength (a "200 mg" in a sentence reads as a dose; the
    page's active rows carry the strengths with the label's own wording)."""
    from . import relationships
    errors = []
    if len(answer) >= relationships.ANSWER_MAX:
        errors.append(f"answer line is {len(answer)} characters, the rule is under {relationships.ANSWER_MAX}")
    if any(d in answer for d in _DASHES):
        errors.append("em-dash or en-dash in the answer line (house rule)")
    if len(re.split(r"(?<=[.!?])\s+", answer.strip())) != 1 or not answer.endswith("."):
        errors.append("the answer line is one sentence ending in a full stop")
    for name in (a_name, b_name):
        if name.lower() not in answer.lower():
            errors.append(f"the answer line does not name {name}")
    if relationships._ANSWER_ADVICE.search(answer) or any(
            re.search(p, answer, re.IGNORECASE) for p in relationships._ADVICE_PATTERNS):
        errors.append("the answer line reads as advice or dosing")
    return errors


def compile_pairs(pairs: list[dict], passed: list[dict], seed: list[dict]) -> tuple[list[dict], list[dict]]:
    """(the product comparisons to export, the pairs skipped with a reason).

    A pair names two seeded DailyMed labels (a food's curated list has no inactive ingredients to
    compare). A pair naming a product that is not seeded, not a label, whose URL would be a
    product's own slug, or whose answer line breaks its rules stops the build. A pair whose product
    passed the seed but not the gate this run is SKIPPED, not failed: a withdrawn label drops its
    product page the same way, and the comparison goes with it (reported, like the gate's failures).
    """
    seeded = {p["slug"]: p for p in seed}
    built = {p["slug"] for p in passed}
    errors: list[str] = []
    out: list[dict] = []
    skipped: list[dict] = []
    for pr in pairs:
        a, b = pr["a"], pr["b"]
        where = f"{a}/{b}"
        missing = [s for s in (a, b) if s not in seeded]
        if missing:
            errors.append(f"{where}: not in products.yaml: {', '.join(missing)}")
            continue
        not_labels = [s for s in (a, b) if seeded[s]["source"] != "dailymed"]
        if not_labels:
            errors.append(f"{where}: a label comparison needs two DailyMed labels; {', '.join(not_labels)} is not one")
            continue
        slug = pair_slug(a, b)
        if slug in seeded:
            errors.append(f"{where}: its URL {slug} is a product's own slug")
            continue
        errors.extend(f"{where}: {e}" for e in _pair_answer_errors(pr["answer"], seeded[a]["name"], seeded[b]["name"]))
        gone = [s for s in (a, b) if s not in built]
        if gone:
            skipped.append({"pair": where, "reason": f"{', '.join(gone)} did not pass the gate this run"})
            continue
        out.append({"slug": slug, "a": a, "b": b, "answer": pr["answer"],
                    "confidence": FROM_SOURCE, "source": PAIR_SOURCE})
    if errors:
        raise ProductSeedError("product_pairs.yaml:\n  " + "\n  ".join(errors))
    for s in skipped:
        log.warning("  product pair %s skipped: %s", s["pair"], s["reason"])
    return out, skipped
