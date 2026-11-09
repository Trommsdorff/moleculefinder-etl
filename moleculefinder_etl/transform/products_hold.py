"""A live product page does not vanish because a weekly refresh changed its inputs (gate hold,
Garrett, 2026-11-09).

THE INCIDENT. /whats-in/ambien and /whats-in/blue-lizard-sport-spf-50 were live from 2026-10-22.
On Monday 2026-11-09 DailyMed answered 404 for both labels' set ids: Sanofi's Ambien label was
retired when the brand moved to Cosette Pharmaceuticals (same tablets, same eleven ingredients,
a new set id), and Crown Laboratories withdrew the Blue Lizard Sport SPF 50 label the page read
(the octisalate formula; the current lotion is another set id). The gate did exactly what it was
told: no label, no page. The run went green, the data PR merged itself, and two indexed URLs
started answering 404 with no 410, no notice and nobody deciding.

THE RULE, in the spirit of the Wikidata hold (``wikidata_age.py``):

* A product the SHIPPED snapshot has, whose row is still in ``products.yaml``, and which this
  run's rebuild would drop for any reason (a label gone from DailyMed, a label that lost a
  molecule, a code that stopped reaching one, a Wikidata item that lost its parts), is HELD: the
  run keeps the shipped page's data for it (molecule titles follow the catalog, so the page and
  the molecule pages agree), logs one line with the gate's reason, and records it in the
  committed ``data/seed/products_held.json`` with the date it was first held. A person then
  decides: fix the row (a new set id) and it rebuilds on its merits, or remove the row.
* A product leaves the catalog ONLY when its row is removed from ``products.yaml`` on purpose.
  Then it is not held; the run names it as removed, and its URL must answer 410 through the web
  repo's ``lib/gone.ts`` (tranche 2's removed-pages mechanism), which the web's tests enforce
  against ``products_published.json`` below.
* A held product that passes again (the row fixed, the label back) simply passes; the held file
  empties.

WHERE "SHIPPED" COMES FROM. ``data/snapshots/products.json`` on disk, read before the export
overwrites it: the last snapshot this repo committed, which is what the site serves. A held
product is written back into it, so next week compares against it again.

THE LEDGER. ``data/snapshots/products_published.json`` lists every /whats-in/ product and
comparison slug any snapshot has ever published, never shrinking. It travels to the web with
``npm run sync-data``; the web's ``lib/gone.test.ts`` fails if a slug in it has neither a page
nor a 410, so a page can no longer disappear without a decision.

A held product can still fail the run: when molecules it lists have left the catalog (a
deliberate removal) and fewer than ``MIN_MOLECULES`` remain, holding it would ship a page the
gate forbids, so the run refuses and names the product.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..config import SEED_DIR, SNAPSHOTS

log = logging.getLogger("mfetl")

# Committed (data/seed is): the products held this run, empty when none.
HELD_FILE = SEED_DIR / "products_held.json"
SHIPPED_FILE = SNAPSHOTS / "products.json"
# In the snapshot, so it reaches the web: every product and pair slug ever published.
PUBLISHED = "products_published.json"
PUBLISHED_FILE = SNAPSHOTS / PUBLISHED
GONE_FILE = "lib/gone.ts"


def _read(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def read_shipped(path: Path | None = None) -> list[dict]:
    """The products the shipped snapshot has; empty when there is none (a first run)."""
    data = _read(path or SHIPPED_FILE)
    rows = data.get("products") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


def read_held(path: Path | None = None) -> list[dict]:
    """Last run's held products (for the date each was first held); empty when none."""
    data = _read(path or HELD_FILE)
    return data if isinstance(data, list) else []


def _source_summary(source: dict | None) -> dict:
    """What the held page was built from, as the held file shows it."""
    source = source or {}
    keep = ("type", "setid", "labeler", "version", "effective", "qid", "world", "hub", "class")
    return {k: source[k] for k in keep if source.get(k) is not None}


def hold(passed: list[dict], report: dict, seed: list[dict], shipped: list[dict],
         records: list[dict], *, since: str, previous: list[dict] | None = None,
         min_molecules: int = 3) -> tuple[list[dict], list[dict], list[dict]]:
    """(the products to publish, the held products, the products removed on purpose).

    ``passed`` and ``report`` are ``compile_products``' result; ``seed`` the rows of
    ``products.yaml``; ``shipped`` the shipped snapshot's products; ``records`` the catalog this
    run built; ``since`` the date to stamp a newly held product with; ``previous`` last run's held
    file. Pure; ``report`` gains ``held`` (count), ``held_products`` and ``removed_products``, and
    each held product's failure entry is marked ``"held": true``."""
    passed_slugs = {p["slug"] for p in passed}
    seeded = {p["slug"]: p for p in seed}
    titles = {r["slug"]: r["title"] for r in records}
    failures = {f["slug"]: f for f in report.get("failures", [])}
    first_held = {h.get("slug"): h.get("since") for h in (previous or []) if h.get("slug")}

    out = list(passed)
    held: list[dict] = []
    removed: list[dict] = []
    for s in sorted(shipped, key=lambda x: x["slug"]):
        slug = s["slug"]
        if slug in passed_slugs:
            continue
        row = seeded.get(slug)
        if row is None:
            removed.append({"slug": slug, "name": s.get("name"), "kind": s.get("kind")})
            continue
        mols = [{**m, "title": titles[m["slug"]]} for m in s.get("molecules", []) if m["slug"] in titles]
        left = [m["slug"] for m in s.get("molecules", []) if m["slug"] not in titles]
        if len(mols) < min_molecules:
            raise SystemExit(
                f"products: {slug} would be held (it is live and its row is in products.yaml), but "
                f"{', '.join(left)} left the catalog and only {len(mols)} of its molecules remain, "
                f"fewer than {min_molecules}. Remove the row from products.yaml and add "
                f"/whats-in/{slug} to the web repo's {GONE_FILE}, or fix the row.")
        entry = {**s, "name": row["name"], "kind": row["kind"], "molecules": mols}
        out.append(entry)
        failure = failures.get(slug)
        if failure is not None:
            failure["held"] = True
        held.append({
            "slug": slug, "name": row["name"], "kind": row["kind"],
            "reason": (failure or {}).get("reason") or "not built this run",
            "item": row.get("item"),
            "shipped": _source_summary(s.get("source")),
            "since": first_held.get(slug) or since,
            **({"molecules_left_catalog": left} if left else {}),
        })
    out.sort(key=lambda x: x["slug"])
    report["held"] = len(held)
    report["held_products"] = [h["slug"] for h in held]
    report["removed_products"] = [r["slug"] for r in removed]
    return out, held, removed


def report_line(h: dict) -> str:
    """One held product, as the log, the run summary and the notice print it."""
    src = h.get("shipped") or {}
    built = ", ".join(f"{k} {src[k]}" for k in ("setid", "qid", "version", "effective") if src.get(k))
    return (f"/whats-in/{h['slug']}: held since {h['since']}: {h['reason']}. The page keeps the data it "
            f"shipped with ({built or src.get('type', 'unknown source')}). Fix its row in products.yaml, or "
            f"remove the row and add /whats-in/{h['slug']} to the web repo's {GONE_FILE}.")


def removed_line(r: dict) -> str:
    """One product removed from products.yaml on purpose."""
    return (f"/whats-in/{r['slug']}: removed from products.yaml, so it leaves the catalog; it must answer "
            f"410 (the web repo's {GONE_FILE}), or the web's tests fail.")


def write_held(held: list[dict], path: Path | None = None) -> Path:
    """The committed record of this run's held products (an empty list when none)."""
    path = path or HELD_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(held, key=lambda h: h["slug"]), ensure_ascii=False, indent=1) + "\n")
    return path


def read_published(path: Path | None = None) -> dict[str, list[str]]:
    data = _read(path or PUBLISHED_FILE)
    data = data if isinstance(data, dict) else {}
    return {k: [s for s in data.get(k) or [] if isinstance(s, str)] for k in ("products", "pairs")}


def published(previous: dict[str, list[str]] | None, products: list[dict] | None,
              pairs: list[dict] | None) -> dict[str, list[str]]:
    """The ledger: every product and comparison slug ever published, the previous ledger's and
    this snapshot's, sorted. It never shrinks; a removal is answered by a 410, not by forgetting."""
    previous = previous or {}
    return {
        "products": sorted(set(previous.get("products") or []) | {p["slug"] for p in products or []}),
        "pairs": sorted(set(previous.get("pairs") or []) | {p["slug"] for p in pairs or []}),
    }
