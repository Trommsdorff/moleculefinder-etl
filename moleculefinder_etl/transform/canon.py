"""Stage 0: build the canon from notable seeds, ranked by demand.

The 119M-compound universe is a trap; the canon is *built up* from notable
seeds, not subtracted from infinity (build plan §4). Three inputs are unioned by
PubChem CID:

  1. **Marquee (filter-2).** A bounded list of famous names resolved to CIDs via
     PubChem name→CID. This *guarantees* the household molecules are present —
     the notability net below is intentionally narrow and misses most of them.
  2. **Curated.** Every molecule with a `sources/curated/*.yaml` overlay, forced
     in so its hand-authored hooks/foods/editorial always have a page.
  3. **Notability net.** Wikidata compounds with an English Wikipedia article
     (CC0 labels/descriptions/ids). Widen with SPARQL UNIONs later toward 50k.

Build order = descending Wikipedia pageviews, so we ship what people look for
first. Every network call is cached under data/raw_cache so re-runs are cheap
and resumable. Emits data/seed/canon.parquet.
"""
from __future__ import annotations
import csv
import json
import logging
import os
import zlib
from pathlib import Path

import yaml

from ..config import (SEED_DIR, CANON_TARGET, RAW_CACHE, CURATED_DIR, SEEDS_DIR,
                      WIKIDATA_CACHE_TTL_DAYS)
from ..sources import wikidata, pageviews, pubchem, cache
from .. import freshness

log = logging.getLogger("mfetl")

# Downgrade a failed Wikidata refresh from a failed run back to a warning. For a
# deliberately offline or degraded run only; the default is to fail.
ALLOW_STALE_WIKIDATA_ENV = "MFETL_ALLOW_STALE_WIKIDATA"

# ~household-name molecules forced into the marquee tier, spanning families that
# cluster structurally (xanthines, sugars, alcohols, NSAIDs, catecholamines,
# nucleobases, terpenes…) so similarity edges and functional groups are rich.
MARQUEE_SEED_TITLES = [
    # xanthines / stimulants
    "Caffeine", "Theobromine", "Theophylline", "Nicotine", "Cotinine",
    # neurotransmitters & amino acids
    "Dopamine", "Serotonin", "Epinephrine", "Norepinephrine", "Histamine",
    "Melatonin", "Acetylcholine", "Gamma-aminobutyric acid", "Glycine",
    "Glutamic acid", "Tryptophan", "Tyrosine", "Phenylalanine",
    # sugars & sugar alcohols
    "Glucose", "Fructose", "Sucrose", "Lactose", "Galactose", "Maltose",
    "Ribose", "Sorbitol", "Xylitol",
    # alcohols, solvents & simple acids
    "Ethanol", "Methanol", "Isopropyl alcohol", "Glycerol", "Ethylene glycol",
    "Acetone", "Acetic acid", "Formic acid", "Citric acid", "Lactic acid",
    "Oxalic acid", "Benzoic acid", "Salicylic acid", "Malic acid", "Tartaric acid",
    # analgesics & common drugs
    "Aspirin", "Ibuprofen", "Acetaminophen", "Naproxen", "Morphine", "Codeine",
    "Penicillin G", "Amoxicillin",
    # vitamins
    "Ascorbic acid", "Retinol", "Thiamine", "Riboflavin", "Niacin",
    "Pyridoxine", "Folic acid", "Cholecalciferol", "Biotin", "alpha-Tocopherol",
    # aromatics / industrial
    "Benzene", "Toluene", "Phenol", "Aniline", "Styrene", "Naphthalene",
    "Formaldehyde", "Acetaldehyde",
    # scents, flavors & plant compounds
    "Vanillin", "Menthol", "Limonene", "Geosmin", "Eugenol", "Cinnamaldehyde",
    "Camphor", "Linalool", "Thymol", "Carvone", "Capsaicin", "Piperine",
    "Curcumin", "Resveratrol", "Quercetin",
    # sweeteners
    "Aspartame", "Saccharin", "Sucralose", "Stevioside",
    # alkaloids & classic poisons
    "Quinine", "Cocaine", "Strychnine", "Atropine",
    # steroids & metabolites
    "Cholesterol", "Testosterone", "Estradiol", "Progesterone", "Cortisol",
    "Urea", "Uric acid", "Creatinine",
    # nucleobases
    "Adenine", "Guanine", "Cytosine", "Thymine", "Uracil", "Adenosine",
    # notable hazards
    "Nitroglycerin", "2,4,6-Trinitrotoluene", "Hydrogen cyanide",
]


# ── Cached network helpers (resumable) ───────────────────────────────────────
def _cache(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _notable_cached() -> list[dict]:
    """The notability net, cached with an expiry (``WIKIDATA_CACHE_TTL_DAYS``).

    Wikidata is a live wiki: items are created, merged and split, so a copy of this query
    is only true as of the moment it ran. It used to be kept forever, which meant a machine
    that had run the query once was pinned to that day's answer indefinitely.
    """
    path = _cache(RAW_CACHE / "wikidata" / "notable.json")
    hit = cache.read_json(path, WIKIDATA_CACHE_TTL_DAYS)
    if hit is not None:
        return hit.value
    rows = wikidata.notable_compounds()
    cache.write_json(path, rows)
    return rows


def _pageviews_cached(title: str) -> int:
    if not title:
        return 0
    slug = "".join(c if c.isalnum() else "-" for c in title.lower()).strip("-") or "x"
    path = _cache(RAW_CACHE / "pageviews" / f"{slug}.json")
    if path.exists():
        return json.loads(path.read_text())
    try:
        v = pageviews.monthly_average(title)
    except Exception:
        v = 0
    path.write_text(json.dumps(v))
    return v


DESCRIPTIONS_CACHE = RAW_CACHE / "wikidata" / "descriptions.json"


def _read_descriptions_cache(path: Path) -> dict[str, dict]:
    """Per-CID entries, each with its own ``fetched_at``.

    Entries written before dates existed come back undated, which ``cache.is_fresh``
    treats as unknown age and therefore never fresh. That is the migration: the first run
    after this change re-fetches the whole map once, and the undated entries that caused
    the 2026-09-08 regression cannot be reused even once more.
    """
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(raw, dict) and raw.get(cache.ENVELOPE_KEY):
        entries = raw.get("entries") or {}
        return entries if isinstance(entries, dict) else {}
    # Legacy flat {cid: {desc, qid}} — adopt it, undated.
    return {str(k): dict(v or {}) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _descriptions_cached(cids: list[int]) -> dict[int, dict]:
    """CC0 descriptions + QIDs per CID, cached **with a per-entry expiry**.

    This is the cache that shipped the regression. It held bulk-batch items
    (alanine ``Q106345485`` where Wikidata now has ``Q218642``) and null descriptions where
    Wikidata now has prose, and because a hit was indistinguishable from a fetch the
    pipeline wrote those over 22 QIDs and 11 summaries that were already correct in the
    snapshot. An entry now states when it was fetched and stops being a hit once it is
    older than ``WIKIDATA_CACHE_TTL_DAYS``.

    Misses are still recorded so a CID with genuinely no Wikidata item is not re-queried
    every run, but a recorded miss expires exactly like a recorded value: omeprazole's
    nulled LD50 came from the same "we asked once and got nothing" shape.

    Each returned entry carries ``fetched_at`` and ``live``; they are handed to the
    freshness map so the export guard can tell an upstream change from a stale overwrite.
    """
    path = _cache(DESCRIPTIONS_CACHE)
    stored = _read_descriptions_cache(path)
    at = cache.now()
    missing = [c for c in cids
               if not cache.is_fresh((stored.get(str(c)) or {}).get("fetched_at"),
                                     WIKIDATA_CACHE_TTL_DAYS, at)]
    live: set[int] = set()
    if missing:
        try:
            fetched = wikidata.descriptions_for_cids(missing)
        except Exception as exc:
            # A failed refresh is a FAILED RUN, not a warning. The fallback below is safe
            # (cached values are kept and marked not-live, so `snapshot_guard` will refuse
            # any regression built on them), and that safety is exactly what let this hide:
            # on 2026-09-09 every run was failing with HTTP 414 and each one logged a line
            # nobody read, produced an identical snapshot, and reported success. Silence
            # that looks like a healthy no-op is worse than a red run.
            detail = f"{type(exc).__name__}: {exc}"
            if os.getenv(ALLOW_STALE_WIKIDATA_ENV) == "1":
                fetched = {}
                log.warning("wikidata descriptions: query failed for %d CID(s) (%s); "
                            "%s=1, so they keep their cached values and are marked "
                            "not-freshly-fetched", len(missing), detail,
                            ALLOW_STALE_WIKIDATA_ENV)
            else:
                raise wikidata.WikidataQueryError(
                    f"wikidata descriptions: query failed for {len(missing)} CID(s) "
                    f"({detail}). The snapshot would be built from cached descriptions and "
                    f"QIDs of unknown age, which is the shape of the 2026-09-08 regression. "
                    f"Set {ALLOW_STALE_WIKIDATA_ENV}=1 to continue with the cached values "
                    f"anyway (the export guard still refuses any regression built on them)."
                ) from exc
        else:
            live = set(missing)
            for c in missing:                   # record misses too, so we don't refetch
                d = fetched.get(c) or {"desc": None, "qid": None}
                stored[str(c)] = {"desc": d.get("desc"), "qid": d.get("qid"), "fetched_at": at}
            path.write_text(json.dumps({cache.ENVELOPE_KEY: cache.ENVELOPE_VERSION,
                                        "fetched_at": at, "entries": stored}, sort_keys=True))
            log.info("  wikidata descriptions: %d fetched, %d still fresh in cache",
                     len(missing), len(cids) - len(missing))
    out = {int(k): {**v, "live": int(k) in live} for k, v in stored.items()}
    freshness.merge({freshness.WIKIDATA: {
        c: {"fetched_at": (out.get(c) or {}).get("fetched_at"), "live": c in live}
        for c in cids}})
    return out


def _curated_seed() -> dict[int, dict]:
    """Read curated/*.yaml → {cid: {"title": ..., "slug": ...}} (guaranteed marquee)."""
    out: dict[int, dict] = {}
    for path in sorted(CURATED_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        cid = data.get("cid")
        if not cid:
            continue
        slug = data.get("slug") or ""
        out[int(cid)] = {"title": (slug.replace("-", " ").title() or f"CID {cid}"), "slug": slug}
    return out


# ── Household must-include seed (the permanent fix for the traffic-ranking blind spots) ──
HOUSEHOLD_SEED = SEEDS_DIR / "household_must_include.yaml"


def _synthetic_cid(name: str) -> int:
    """A stable, negative pseudo-CID for a hand-modeled molecule that has no PubChem
    compound. Negative so it can never collide with a real (always-positive) PubChem CID;
    deterministic in the name so re-runs and the DB natural key stay stable."""
    return -(zlib.crc32(name.strip().lower().encode("utf-8")) + 1)


def household_seed() -> list[dict]:
    """The hand-maintained must-include molecules (name, bucket, family, cid-or-null,
    is_otc, dual_use, handling). `hand-model` entries get a synthetic negative CID and are
    flagged so fetch skips PubChem and transform builds a structureless record. This is the
    marquee-union mechanism that guarantees glucose, generalized to every blind-spot name."""
    if not HOUSEHOLD_SEED.exists():
        return []
    data = yaml.safe_load(HOUSEHOLD_SEED.read_text()) or {}
    out: list[dict] = []
    for m in data.get("molecules", []):
        name = (m.get("name") or "").strip()
        if not name:
            continue
        hand = (m.get("handling") == "hand-model") or m.get("cid") in (None, "null", "")
        cid = _synthetic_cid(name) if hand else int(m["cid"])
        out.append({**m, "name": name, "cid": cid, "hand_model": hand})
    return out


# ── Scope B everyday-core canon (the curated 489, not a demand slice of 119M) ──
SCOPE_B_CSV = SEEDS_DIR / "scope_b_core.csv"


def _scope_b_rows() -> list[dict]:
    """Read scope_b_core.csv → canon rows, each already stamped with its bucket/family.

    The 489 are hand-picked, so every row is marquee tier (never truncated). Real compounds
    keep their PubChem CID; ``hand-model`` rows (collagen, starch, gluten...) get a synthetic
    negative CID — the same value `household_seed()` derives from the name, so the two agree.
    Pageviews come straight from the CSV (no Wikipedia API call needed to rank).

    The optional `batch` column tags a catalog-growth tranche (build plan phase 4, e.g.
    "2026-09-A"). It is provenance, not behaviour: it rides through to the record so a
    reviewer can tell which run a molecule arrived in, and so a bad tranche can be found
    and lifted back out in one query. Rows written before batches exist carry None."""
    if not SCOPE_B_CSV.exists():
        return []
    out: list[dict] = []
    with SCOPE_B_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("molecule") or "").strip()
            if not name:
                continue
            raw_cid = (row.get("pubchem_cid") or "").strip()
            hand = (row.get("handling") == "hand-model") or not raw_cid
            out.append({
                "cid": _synthetic_cid(name) if hand else int(raw_cid),
                "enwiki_title": name, "wikidata_qid": None, "has_common_name": True,
                "tier": "marquee", "summary": None,
                "pageviews": int(row.get("wikipedia_views_monthly") or 0),
                "hand_model": hand,
                "scope_bucket": (row.get("bucket") or "").strip() or None,
                "scope_family": (row.get("family") or "").strip() or None,
                "is_otc": (row.get("is_otc") or "").strip().lower() == "yes",
                "dual_use": (row.get("dual_use") or "").strip().lower() == "yes",
                "batch": (row.get("batch") or "").strip() or None,
            })
    return out


def build_scope_b_canon() -> "list[dict]":
    """The Scope B everyday-core canon: exactly the molecules in scope_b_core.csv, each
    stamped with its Scope B bucket/family and ranked by the CSV's Wikipedia pageviews.

    No notability net — this is a curated everyday core, not a demand-ranked slice of the
    119M-compound universe, so the target/notability machinery of `build_canon` is bypassed.
    CC0 Wikidata descriptions + QIDs are filled for the real CIDs (cached; synthetic CIDs
    have no PubChem/Wikidata row and are skipped)."""
    canon = _scope_b_rows()
    if not canon:
        raise SystemExit(f"missing {SCOPE_B_CSV.name}; cannot build the Scope B canon")

    desc = _descriptions_cached([r["cid"] for r in canon if r["cid"] > 0])
    for r in canon:
        d = desc.get(r["cid"])
        if d:
            r["summary"] = r["summary"] or d.get("desc")
            r["wikidata_qid"] = r["wikidata_qid"] or d.get("qid")

    canon.sort(key=lambda r: -r["pageviews"])
    for i, r in enumerate(canon):
        r["build_order"] = i
    return canon


# ── Canon build ──────────────────────────────────────────────────────────────
def build_canon(target: int = CANON_TARGET) -> "list[dict]":
    """Return the canon rows (network-bound; cached). Marquee is always included."""
    rows: dict[int, dict] = {}

    # 1. Marquee via name→CID (filter-2): guarantees the famous molecules.
    for name in MARQUEE_SEED_TITLES:
        try:
            cid = pubchem.name_to_cid(name)
        except Exception:
            cid = None
        if cid and cid not in rows:
            rows[cid] = {"cid": cid, "enwiki_title": name, "wikidata_qid": None,
                         "has_common_name": True, "tier": "marquee", "summary": None}

    # 2. Curated overlays: force every hand-authored molecule in.
    for cid, meta in _curated_seed().items():
        rows.setdefault(cid, {"cid": cid, "enwiki_title": meta["title"], "wikidata_qid": None,
                              "has_common_name": True, "tier": "marquee", "summary": None})

    # 2b. Household must-include seed: force in water / everyday chemistry and the hand-
    #     modeled macromolecules (collagen, starch, gluten...) that traffic-ranking or a
    #     missing Wikidata compound link would silently drop — the glucose failure mode,
    #     generalized. Marquee tier ⇒ never truncated; hand_model flag ⇒ fetch skips it.
    for m in household_seed():
        c = m["cid"]
        rows.setdefault(c, {"cid": c, "enwiki_title": m["name"], "wikidata_qid": None,
                            "has_common_name": True, "tier": "marquee", "summary": None})
        rows[c]["tier"] = "marquee"
        rows[c]["hand_model"] = m["hand_model"]

    # 3. Notability net (Wikidata + enwiki), cached. Canon tier unless already marquee.
    for row in _notable_cached():
        c = row.get("cid")
        if not c:
            continue
        c = int(c)
        qid = row["compound"].rsplit("/", 1)[-1]
        if c in rows:
            rows[c]["wikidata_qid"] = rows[c]["wikidata_qid"] or qid
            continue
        title = row.get("compoundLabel", "")
        rows[c] = {"cid": c, "enwiki_title": title, "wikidata_qid": qid,
                   "has_common_name": bool(title) and not title[0].isdigit(),
                   "tier": "marquee" if title in MARQUEE_SEED_TITLES else "canon",
                   "summary": row.get("desc")}

    canon = list(rows.values())

    # 4. CC0 descriptions + QIDs for everyone (fills marquee summaries the net missed).
    #    Skip synthetic (negative) CIDs — hand-modeled molecules have no PubChem/Wikidata row.
    desc = _descriptions_cached([r["cid"] for r in canon if r["cid"] > 0])
    for r in canon:
        d = desc.get(r["cid"])
        if d:
            r["summary"] = r["summary"] or d.get("desc")
            r["wikidata_qid"] = r["wikidata_qid"] or d.get("qid")

    # 5. Rank by pageviews (cached). Keep all marquee, fill with top canon to target.
    for r in canon:
        r["pageviews"] = _pageviews_cached(r["enwiki_title"])
    canon.sort(key=lambda r: (r["tier"] != "marquee", -r["pageviews"]))
    canon = canon[:target]
    canon.sort(key=lambda r: -r["pageviews"])
    for i, r in enumerate(canon):
        r["build_order"] = i
    return canon


def write_parquet(rows: "list[dict]", path: Path | None = None) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq
    path = path or (SEED_DIR / "canon.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Uniform schema across rows (pyarrow infers from the first row otherwise). The Scope B
    # bucket/family/flags ride the parquet so stage_transform can stamp all 489 (not just the
    # household seed) — assemble_record reads row["scope_bucket"] straight off the canon row.
    cols = ["cid", "tier", "build_order", "has_common_name", "wikidata_qid",
            "enwiki_title", "summary", "pageviews", "hand_model",
            "scope_bucket", "scope_family", "is_otc", "dual_use", "batch"]
    norm = [{**{c: r.get(c) for c in cols}, "hand_model": bool(r.get("hand_model")),
             "is_otc": bool(r.get("is_otc")), "dual_use": bool(r.get("dual_use"))} for r in rows]
    pq.write_table(pa.Table.from_pylist(norm), path)
    return path


def read_parquet(path: Path | None = None) -> "list[dict]":
    import pyarrow.parquet as pq
    path = path or (SEED_DIR / "canon.parquet")
    return pq.read_table(path).to_pylist()
