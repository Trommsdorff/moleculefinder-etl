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

MATCHING IS DETERMINISTIC. A label ingredient is a molecule when its UNII code (or, failing
that, its active moiety's UNII) is one of the UNIIs PubChem lists for that molecule's CID. A
Wikidata part is a molecule when its QID is the molecule's ``wikidata_qid``. No name matching,
no Wikipedia prose, no Open Food Facts (share-alike; blocked in ``sources/registry.py``). A UNII
two molecules share names neither.

Fetching happens in the fetch stage (``warm``), into ``data/raw_cache``, so the inputs travel
with the snapshot (``moleculefinder_etl/inputs.py``) and the Mac and GitHub build identically;
compiling (``compile_products``) reads only the cache and the records.

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
from ..sources import cache, dailymed, wikidata
from ..sources.registry import assert_not_blocked
from .confidence import FROM_SOURCE
from .relationships import load_worlds

log = logging.getLogger("mfetl")

PRODUCTS_YAML = SEEDS_DIR / "products.yaml"
MIN_MOLECULES = 3
# The page's kinds, in the order the /whats-in index lists them. "moment" holds the worlds
# that are an experience, not a thing you buy (the smell after rain, falling asleep, a workout).
KINDS = ("food", "drink", "medicine", "cosmetic", "household", "moment")
SOURCE_KEYS = ("dailymed", "wikidata", "world")

DAILYMED_DIR = RAW_CACHE / "dailymed"
SPL_PREFIX = "spl1"                   # bump when ``dailymed.parse`` changes what it keeps
PARTS_CACHE = RAW_CACHE / "wikidata" / "product_parts.json"
UNII_PREFIX = "unii"

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
        if len(sources) != 1:
            errors.append(f"{where}: needs exactly one of {', '.join(SOURCE_KEYS)}")
            continue
        key = sources[0]
        value = str(row[key]).strip()
        if key == "dailymed" and not dailymed.SETID_RE.match(value):
            errors.append(f"{where}: not a DailyMed set id: {value}")
        if key == "wikidata" and not _QID.match(value):
            errors.append(f"{where}: not a Wikidata QID: {value}")
        if key == "world" and value not in world_slugs:
            errors.append(f"{where}: no world {value!r} in worlds.yaml")
        if (key, value) in seen_source:
            errors.append(f"{where}: same {key} item as {seen_source[(key, value)]}")
        seen_source[(key, value)] = str(slug)
        out.append({"slug": slug, "name": " ".join(str(name).split()), "kind": kind,
                    "source": key, "item": value})
    if errors:
        raise ProductSeedError("products.yaml:\n  " + "\n  ".join(errors))
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


def warm(seed: list[dict], cids: list[int], fetch_uniis) -> dict[str, int]:
    """Fetch whatever the product pages need that the cache does not hold fresh: each seeded
    DailyMed label, the seeded Wikidata items' parts, and every molecule's UNII codes (through
    ``fetch_uniis``, the pipeline's batched per-CID cache). Returns request counts for the log."""
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

    qids = sorted({p["item"] for p in seed if p["source"] == "wikidata"})
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
    fetch_uniis(cids)
    log.info("  products: %d DailyMed label(s), %d fetched; %d Wikidata item(s), %d fetched; "
             "UNII codes for %d CID(s)", labels, fetched_labels, len(qids), len(missing), len(cids))
    return {"labels": labels, "labels_fetched": fetched_labels, "items": len(qids),
            "items_fetched": len(missing)}


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


def _dailymed_molecules(spl: dict, by_unii: dict[str, str]) -> tuple[list[dict], list[str]]:
    """The label's molecules in label order, actives first, and the names of ingredients that
    are not MoleculeFinder molecules. One entry per molecule; active wins over inactive."""
    purpose = dailymed.purposes(spl)
    found: dict[str, dict] = {}
    unmatched: list[str] = []
    for role in ("active", "inactive"):
        for ing in spl.get("ingredients", []):
            if ing["role"] != role:
                continue
            slug, via = None, None
            if ing.get("unii") and ing["unii"] in by_unii:
                slug, via = by_unii[ing["unii"]], "unii"
            else:
                for m in ing.get("moiety") or []:
                    if m in by_unii:
                        slug, via = by_unii[m], "moiety"
                        break
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


def compile_products(records: list[dict], seed: list[dict] | None = None, *,
                     spl=None, parts: dict[str, dict] | None = None,
                     uniis: dict[int, list[str]] | None = None,
                     worlds: list[dict] | None = None) -> tuple[list[dict], dict]:
    """(products that pass the gate, the gate report). Reads only caches and records.

    ``spl`` (setid -> parsed label or ``{"missing": True}`` or None), ``parts`` and ``uniis``
    default to the cache; tests pass their own."""
    seed = load_seed() if seed is None else seed
    worlds = load_worlds() if worlds is None else worlds
    spl = spl or spl_cached
    parts = _read_parts() if parts is None else parts
    uniis = read_uniis([int(r["cid"]) for r in records if int(r["cid"]) > 0]) if uniis is None else uniis
    by_slug = {r["slug"]: r for r in records}
    by_unii = unii_index(records, uniis)
    by_qid = {r["wikidata_qid"]: r["slug"] for r in records if r.get("wikidata_qid")}
    titles = {r["slug"]: r["title"] for r in records}
    world_by_slug = {w["slug"]: w for w in worlds}

    products: list[dict] = []
    failed: list[dict] = []
    missing_counter: Counter[str] = Counter()
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
            mols, unmatched = _dailymed_molecules(label, by_unii)
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
            missing_counter.update(dict.fromkeys(unmatched, 1))
        elif p["source"] == "wikidata":
            item = parts.get(p["item"]) or {}
            if not item or item.get("missing"):
                failed.append({**base, "source": "wikidata", "item": p["item"],
                               "reason": "item not found on Wikidata (or not yet fetched)", "matched": []})
                continue
            mols, listed = _wikidata_molecules(item, by_qid)
            source = {"type": "wikidata", "qid": p["item"],
                      "url": f"https://www.wikidata.org/wiki/{p['item']}"}
        else:
            world = world_by_slug[p["item"]]
            mols = [m for m in _world_molecules(world) if m["slug"] in by_slug]
            listed = len(world.get("molecules") or [])
            source = {"type": "world", "world": world["slug"], "title": world.get("title"),
                      "blurb": world.get("blurb")}
        for m in mols:
            m["title"] = titles[m["slug"]]
        if len(mols) < MIN_MOLECULES:
            what = {"dailymed": "the label lists", "wikidata": "Wikidata lists",
                    "world": "the world lists"}[p["source"]]
            failed.append({**base, "source": p["source"], "item": p["item"],
                           "reason": (f"{what} {listed} ingredient(s); {len(mols)} "
                                      f"{'is a' if len(mols) == 1 else 'are'} MoleculeFinder "
                                      f"molecule{'' if len(mols) == 1 else 's'}, fewer than {MIN_MOLECULES}"),
                           "matched": [m["slug"] for m in mols]})
            continue
        entry = {**base, "source": source, "listed": listed, "molecules": mols,
                 "confidence": FROM_SOURCE}
        if p["source"] == "dailymed":
            entry["not_in_catalog"] = len(unmatched)
            entry["actives_not_in_catalog"] = list(dict.fromkeys(unmatched_actives))
        products.append(entry)

    products.sort(key=lambda x: x["slug"])
    by_kind = Counter(p["kind"] for p in products)
    report = {
        "seeded": len(seed), "passed": len(products), "failed": len(failed),
        "by_kind": {k: by_kind.get(k, 0) for k in KINDS},
        "min_molecules": MIN_MOLECULES,
        "failures": sorted(failed, key=lambda f: (KINDS.index(f["kind"]), f["slug"])),
        # The label ingredients MoleculeFinder does not hold, by how many seeded labels list them:
        # the molecules that would open the most product pages (the next tranche's queue order).
        "label_ingredients_not_in_catalog": [{"name": n, "labels": c}
                                             for n, c in sorted(missing_counter.items(),
                                                                key=lambda kv: (-kv[1], kv[0]))[:60]],
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
