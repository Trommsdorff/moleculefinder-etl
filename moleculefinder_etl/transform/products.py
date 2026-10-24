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
``{"name": <the label's name>, "role": "active" | "inactive"}``, in label order, actives first,
one entry per name (it was a bare count). The page shows them as plain unlinked text under "Also
on the label". This is display, not matching: the names link to nothing, and the gate still counts
only molecules matched by code. ``actives_not_in_catalog`` (the actives' names alone) stays as it
was; the page's unmatched-active sentence reads it.

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
from ..sources import cache, dailymed, pubchem, wikidata
from ..sources.registry import assert_not_blocked
from .confidence import FROM_SOURCE
from .relationships import load_food_hubs, load_worlds

log = logging.getLogger("mfetl")

PRODUCTS_YAML = SEEDS_DIR / "products.yaml"
MIN_MOLECULES = 3
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
UNII_PREFIX = "unii"
PARENT_PREFIX = "uniiparent"          # pubchem/uniiparent-<UNII>.json: the UNII's parent CIDs
MIN_PARENT_CARBONS = 2

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


def read_parents(uniis) -> dict[str, list[int]]:
    """The cached parent CIDs per UNII (written by the fetch stage). Missing means not looked up."""
    out: dict[str, list[int]] = {}
    for u in uniis:
        hit = cache.read_json(_parent_path(u), UNII_CACHE_TTL_DAYS)
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
         fetch_parents=None) -> dict[str, int]:
    """Fetch whatever the product pages need that the cache does not hold fresh: each seeded
    DailyMed label, the seeded Wikidata items' parts, every molecule's UNII codes (through
    ``fetch_uniis``, the pipeline's batched per-CID cache), the PubChem parent of every label
    UNII no molecule claims, and those parents' properties (``fetch_props``, the pipeline's
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
    known = {u for codes in (fetch_uniis(cids) or {}).values() for u in (codes or [])}

    # Salts, hydrates and stereo forms: the parent of every label UNII no molecule claims.
    fetch_parents = fetch_parents or pubchem.unii_parents
    unclaimed = [u for u in label_uniis(seed) if u not in known]
    parents = read_parents(unclaimed)
    asked = [u for u in unclaimed if u not in parents]
    for i, u in enumerate(asked, 1):
        parents[u] = fetch_parents(u)
        cache.write_json(_parent_path(u), parents[u])
        if i % 100 == 0:
            log.info("  products: parent compounds %d/%d", i, len(asked))
    parent_cids = sorted({c for cs in parents.values() for c in cs} - set(cids))
    if fetch_props is not None and parent_cids:
        fetch_props(parent_cids)
    log.info("  products: %d DailyMed label(s), %d fetched; %d Wikidata item(s), %d fetched; "
             "UNII codes for %d CID(s); parents of %d unclaimed label UNII(s), %d fetched",
             labels, fetched_labels, len(qids), len(missing), len(cids), len(unclaimed), len(asked))
    return {"labels": labels, "labels_fetched": fetched_labels, "items": len(qids),
            "items_fetched": len(missing), "parents": len(unclaimed), "parents_fetched": len(asked)}


def read_uniis(cids: list[int]) -> dict[int, list[str]]:
    """The cached UNII codes per CID (written by the fetch stage). Missing means no codes."""
    out: dict[int, list[str]] = {}
    for c in cids:
        hit = cache.read_json(RAW_CACHE / "pubchem" / f"{UNII_PREFIX}-{c}.json", UNII_CACHE_TTL_DAYS)
        if hit is not None and isinstance(hit.value, list):
            out[c] = [str(u) for u in hit.value]
    return out


# ── compile ───────────────────────────────────────────────────────────────────
def unii_index(records: list[dict], uniis: dict[int, list[str]]) -> dict[str, str]:
    """UNII -> slug, for UNIIs exactly one molecule claims. A code two molecules share (a
    medicine and its own drug-form duplicate) matches neither: a miss before a wrong match."""
    owners: dict[str, set[str]] = {}
    for r in records:
        for u in uniis.get(int(r["cid"]), []):
            owners.setdefault(u, set()).add(r["slug"])
    return {u: next(iter(s)) for u, s in owners.items() if len(s) == 1}


_CARBON = re.compile(r"C(?![a-z])(\d*)")


def carbon_count(formula: str | None) -> int:
    """Carbon atoms in a molecular formula ("C12H22O11" -> 12; "Cl", "Ca" and "Cu" are not carbon)."""
    return sum(int(n or 1) for n in _CARBON.findall(formula or ""))


def load_unii_aliases(path: Path | None = None) -> dict[str, str]:
    """The hand list: UNII -> molecule slug, for forms the parent rule does not reach."""
    path = path or UNII_ALIASES_YAML
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return {str(u).strip(): str(s).strip() for u, s in (data.get("aliases") or {}).items()}


def parent_index(records: list[dict], parents: dict[str, list[int]], props: dict[int, dict],
                 aliases: dict[str, str] | None = None) -> dict[str, tuple[str, str]]:
    """UNII -> (slug, how) for label UNIIs no molecule claims: ``parent`` (the parent CID is a
    catalog CID), ``skeleton`` (one catalog molecule shares the parent's InChIKey first block) or
    ``alias`` (the hand list). Exactly one molecule must qualify, with two or more carbons."""
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
        how = "parent"
        found = set().union(*(cid_owners.get(c, set()) for c in cids)) if cids else set()
        if not found:
            how = "skeleton"
            keys = {str((props.get(c) or {}).get("InChIKey") or "")[:14] for c in cids} - {""}
            found = set().union(*(skel_owners.get(k, set()) for k in keys)) if keys else set()
        if len(found) == 1:
            slug = next(iter(found))
            if carbon_count(by_slug[slug].get("molecular_formula")) >= MIN_PARENT_CARBONS:
                out[u] = (slug, how)
    for u, slug in (aliases or {}).items():
        if slug not in by_slug:
            raise ProductSeedError(f"unii_aliases.yaml: {u} names no molecule {slug!r}")
        out.setdefault(u, (slug, "alias"))
    return out


def _resolve(ing: dict, by_unii: dict[str, str], by_parent: dict[str, tuple[str, str]]):
    """(slug, how) for one label ingredient, or (None, None)."""
    if ing.get("unii") and ing["unii"] in by_unii:
        return by_unii[ing["unii"]], "unii"
    for m in ing.get("moiety") or []:
        if m in by_unii:
            return by_unii[m], "moiety"
    # By rule. An active's parent is looked up from its ACTIVE MOIETY, the label's own statement of
    # what the active is: zinc acetate's moiety is zinc, so a lozenge never lists acetic acid as its
    # active, and methylphenidate hydrochloride (whose UNII PubChem files under the dex form) reaches
    # methylphenidate. An ingredient with no moiety (an excipient) is looked up by its own UNII.
    for u in ing.get("moiety") or [ing.get("unii")]:
        if u and u in by_parent:
            return by_parent[u]
    return None, None


def _dailymed_molecules(spl: dict, by_unii: dict[str, str],
                        by_parent: dict[str, tuple[str, str]] | None = None) -> tuple[list[dict], list[str]]:
    """The label's molecules in label order, actives first, and the names of ingredients that
    are not MoleculeFinder molecules. One entry per molecule; active wins over inactive."""
    purpose = dailymed.purposes(spl)
    found: dict[str, dict] = {}
    unmatched: list[str] = []
    for role in ("active", "inactive"):
        for ing in spl.get("ingredients", []):
            if ing["role"] != role:
                continue
            slug, via = _resolve(ing, by_unii, by_parent or {})
            if slug is None:
                if ing["name"] not in unmatched:
                    unmatched.append(ing["name"])
                continue
            if slug in found:
                continue
            entry = {"slug": slug, "role": role, "listed_as": ing["name"], "match": via}
            if role == "active" and purpose.get(ing["name"]):
                entry["purpose"] = purpose[ing["name"]]
            found[slug] = entry
    return list(found.values()), unmatched


def _not_in_catalog(unmatched: list[str], unmatched_actives: list[str], mols: list[dict]) -> list[dict]:
    """The label's ingredients that are not MoleculeFinder molecules, as the label names them: label
    order, actives first, one entry per name (Trust run 2, 2026-10-24). Shown on the page as plain
    unlinked text, never matched to anything; a name a listed molecule already carries is left out.
    The actives here are exactly ``actives_not_in_catalog``."""
    shown = {m["listed_as"] for m in mols}
    actives = set(unmatched_actives)
    return [{"name": n, "role": "active" if n in actives else "inactive"}
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


def compile_products(records: list[dict], seed: list[dict] | None = None, *,
                     spl=None, parts: dict[str, dict] | None = None,
                     uniis: dict[int, list[str]] | None = None,
                     worlds: list[dict] | None = None,
                     parents: dict[str, list[int]] | None = None,
                     props: dict[int, dict] | None = None,
                     aliases: dict[str, str] | None = None,
                     hubs: dict[str, dict] | None = None,
                     classes: dict[str, dict] | None = None) -> tuple[list[dict], dict]:
    """(products that pass the gate, the gate report). Reads only caches and records.

    ``spl`` (setid -> parsed label or ``{"missing": True}`` or None), ``parts``, ``uniis``,
    ``parents``, ``props``, ``aliases`` and ``hubs`` default to the cache and seeds; tests pass
    their own. The report's ``next_tranche_queue`` is the rows ``write_queue`` writes."""
    seed = load_seed() if seed is None else seed
    worlds = load_worlds() if worlds is None else worlds
    spl = spl or spl_cached
    parts = _read_parts() if parts is None else parts
    uniis = read_uniis([int(r["cid"]) for r in records if int(r["cid"]) > 0]) if uniis is None else uniis
    by_slug = {r["slug"]: r for r in records}
    by_unii = unii_index(records, uniis)
    if parents is None:
        parents = read_parents(label_uniis(seed, spl))
    if props is None:
        props = read_props(sorted({c for cs in parents.values() for c in cs}))
    by_parent = parent_index(records, {u: c for u, c in parents.items() if u not in by_unii}, props,
                             load_unii_aliases() if aliases is None else aliases)
    hubs = curated_hubs(records) if hubs is None else hubs
    classes = load_classes() if classes is None else classes
    by_qid = {r["wikidata_qid"]: r["slug"] for r in records if r.get("wikidata_qid")}
    titles = {r["slug"]: r["title"] for r in records}
    world_by_slug = {w["slug"]: w for w in worlds}

    products: list[dict] = []
    failed: list[dict] = []
    queue: dict[str, dict] = {}
    rule_matches: Counter[str] = Counter()
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
            rule_matches.update(m["match"] for m in mols if m["match"] in ("parent", "skeleton", "alias"))
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
            entry["not_in_catalog"] = _not_in_catalog(unmatched, unmatched_actives, mols)
            entry["actives_not_in_catalog"] = list(dict.fromkeys(unmatched_actives))
        products.append(entry)

    products.sort(key=lambda x: x["slug"])
    by_kind = Counter(p["kind"] for p in products)
    queue_rows = _queue_rows(queue)
    report = {
        "seeded": len(seed), "passed": len(products), "failed": len(failed),
        "by_kind": {k: by_kind.get(k, 0) for k in KINDS},
        "min_molecules": MIN_MOLECULES,
        # Label ingredients reached through PubChem's parent compound or the hand list, by rule.
        "matched_by_rule": {k: rule_matches.get(k, 0) for k in ("parent", "skeleton", "alias")},
        "failures": sorted(failed, key=lambda f: (KINDS.index(f["kind"]), f["slug"])),
        # The label ingredients MoleculeFinder does not hold, by how many seeded labels list them:
        # the molecules that would open the most product pages. The whole list is
        # data/seed/next_tranche_queue.csv; the top 60 by labels here.
        "label_ingredients_not_in_catalog": [{"name": r["name"], "labels": r["labels"]}
                                             for r in sorted(queue_rows, key=lambda r: (-r["labels"], r["name"].lower()))[:60]],
        "next_tranche_queue": queue_rows,
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
