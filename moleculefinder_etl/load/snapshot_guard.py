"""Refuse to export a snapshot in which a cached value overwrites a better shipped one.

``sources.cache`` stops the *known* stale entries from being read at all. This is the
backstop for the ones it cannot know about, and it is written against the exact shape of
the 2026-09-08 incident rather than against a general idea of "data got worse":

* a ``summary`` reverting to the placeholder "chemical compound" (11 molecules: taurine,
  hesperidin and 9 more went back to it after phase 1 existed specifically to remove it),
* an existing ``ld50_mg_per_kg`` going null (omeprazole's 4000 mg/kg oral),
* an existing ``wikidata_qid`` changing to something else (22 molecules: alanine
  ``Q218642`` -> ``Q106345485``, glycine ``Q620730`` -> ``Q106345678``, taurine
  ``Q207051`` -> ``Q106345481``, all of them a real item replaced by a bulk-batch one).

The rule is not "these fields may never change". It is:

    a protected field may only regress if the input that produced the new value was
    **fetched live in this run**.

That is the whole test, and it needs no timestamp stored in the snapshot. A live fetch is
by definition fresher than anything already on disk, so the weekly CI run that corrected
all 26 of these passes untouched. A cache hit is not fresher than the value it would
replace: if the two disagree, the shipped value came from somewhere newer, which is
exactly the direction that must not be written. An input this run never touched counts as
not-live, so a partial re-run cannot launder a stale value either.

Set ``MFETL_ALLOW_REGRESSION=1`` to export anyway. It exists because a deliberate change
to the pipeline can legitimately drop a value (tightening ``toxicity.best_oral`` is the
obvious one: it nulls LD50s on purpose), and a guard with no override would make that
change unshippable. It logs loudly and names every molecule it let through.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .. import freshness

log = logging.getLogger("mfetl")

PLACEHOLDER_SUMMARY = "chemical compound"
OVERRIDE_ENV = "MFETL_ALLOW_REGRESSION"


class SnapshotRegression(RuntimeError):
    """Raised instead of writing a snapshot that walks a shipped value backwards."""


def _prior(snapshots: Path) -> dict[str, dict]:
    """The molecule records currently on disk, keyed by slug. Empty is fine: a first
    export has nothing to regress against."""
    out: dict[str, dict] = {}
    mol_dir = snapshots / "molecules"
    if not mol_dir.is_dir():
        return out
    for path in sorted(mol_dir.glob("*.json")):
        try:
            rec = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(rec, dict) and rec.get("slug"):
            out[rec["slug"]] = rec
    return out


def _is_placeholder(summary: object) -> bool:
    return isinstance(summary, str) and summary.strip().lower().rstrip(".") == PLACEHOLDER_SUMMARY


def _regressions(new: list[dict], prior: dict[str, dict], fresh: dict) -> list[dict]:
    """Every protected field that goes backwards without a live fetch behind it."""
    found: list[dict] = []
    for rec in new:
        old = prior.get(rec.get("slug"))
        if not old:                                   # a new molecule regresses nothing
            continue
        cid = rec.get("cid")

        # 1. summary back to the placeholder phase 1 exists to remove.
        if (_is_placeholder(rec.get("summary")) and old.get("summary")
                and not _is_placeholder(old.get("summary"))
                and not freshness.is_live(fresh, freshness.WIKIDATA, cid)):
            found.append({"slug": rec["slug"], "cid": cid, "field": "summary",
                          "was": old.get("summary"), "now": rec.get("summary"),
                          "why": freshness.describe(fresh, freshness.WIKIDATA, cid)})

        # 2. an LD50 that was published, nulled.
        if (rec.get("ld50_mg_per_kg") is None and old.get("ld50_mg_per_kg") is not None
                and not freshness.is_live(fresh, freshness.TOXICITY, cid)):
            found.append({"slug": rec["slug"], "cid": cid, "field": "ld50_mg_per_kg",
                          "was": old.get("ld50_mg_per_kg"), "now": None,
                          "why": freshness.describe(fresh, freshness.TOXICITY, cid)})

        # 3. a QID replaced by a different one. Filling a null is not a regression;
        #    swapping a real item for another is how the bulk-batch QIDs got in.
        if (old.get("wikidata_qid") and rec.get("wikidata_qid") != old.get("wikidata_qid")
                and not freshness.is_live(fresh, freshness.WIKIDATA, cid)):
            found.append({"slug": rec["slug"], "cid": cid, "field": "wikidata_qid",
                          "was": old.get("wikidata_qid"), "now": rec.get("wikidata_qid"),
                          "why": freshness.describe(fresh, freshness.WIKIDATA, cid)})
    found.sort(key=lambda r: (r["slug"], r["field"]))
    return found


def _report(found: list[dict], limit: int = 12) -> str:
    lines = [f"  {r['slug']} ({r['field']}): {r['was']!r} -> {r['now']!r}  [{r['why']}]"
             for r in found[:limit]]
    if len(found) > limit:
        lines.append(f"  ... and {len(found) - limit} more")
    return "\n".join(lines)


def check(molecules: list[dict], snapshots: Path, fresh: dict | None = None) -> list[dict]:
    """Raise ``SnapshotRegression`` if this export would walk a shipped value backwards.

    Returns the (possibly empty) list of regressions when the override is set, so the
    caller can log what it chose to ship.
    """
    prior = _prior(snapshots)
    if not prior:
        return []
    found = _regressions(molecules, prior, freshness.load() if fresh is None else fresh)
    if not found:
        return []
    if os.getenv(OVERRIDE_ENV) == "1":
        log.warning("%s=1: exporting %d regression(s) anyway:\n%s",
                    OVERRIDE_ENV, len(found), _report(found, limit=len(found)))
        return found
    raise SnapshotRegression(
        f"refusing to export: {len(found)} value(s) would go backwards without a fresh "
        f"fetch behind them.\n{_report(found)}\n"
        "A cache hit is not evidence of an upstream change. Re-fetch the derived sources "
        "and run again:\n"
        "  rm -rf data/raw_cache/wikidata && mfetl seed && mfetl transform && mfetl export\n"
        f"If the change is deliberate (a pipeline rule that drops values on purpose), set "
        f"{OVERRIDE_ENV}=1.")
