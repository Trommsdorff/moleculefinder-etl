"""An LD50 a live PubChem answer stops reporting is held for 7 days, then released (2026-11-21).

THE INCIDENT. levonorgestrel (CID 13109) shipped an oral rat LD50 of 5010 mg/kg from four HSDB rows.
On 2026-11-21 PubChem's Toxicity answer for 13109 no longer carried them: the HSDB record those rows
belong to is number 3595, "NORGESTREL" (the racemic mixture, CID 4542), and PubChem had stopped
attaching it to levonorgestrel's page. Levonorgestrel's own HSDB record (6483) reports no LD50. A
real upstream correction, so the value should leave the site. But not silently, and not by stopping
the weekly job.

THE RULE, in the pattern of the weekly run's other holds (``wikidata_age.py``: a Wikidata text
change ships once it is 7 days old; ``products_hold.py``: a live page is held, not dropped):

* A molecule whose SHIPPED record has an LD50, and whose Toxicity answer, FETCHED LIVE in this run,
  yields none, is HELD: the run assembles it from the shipped LD50 rows, logs one line, and records it
  in the committed ``data/seed/ld50_held.json`` with the date the removal was first seen.
* It is RELEASED on a live fetch at least ``DAYS`` days after that first sighting that still yields
  no LD50: the record then goes out without one (the export guard allows it, because the fetch was
  live) and the run summary says so.
* A value that comes back in between (any LD50 in the answer) ends the hold: the clock resets.
* A CACHE HIT never starts a hold and never releases one. A cache hit on a molecule already held
  keeps it held with its clock unchanged (a pinned rebuild reproduces what shipped). A cache hit
  that would null an LD50 that is not held is left alone, so ``load.snapshot_guard`` still refuses
  it, exactly as before: this module does not weaken the guard.

The weekly run re-fetches a held molecule's Toxicity answer every run, whatever the cache's age
(``pipeline.stage_fetch``), so the second sighting is a live one and not the 30-day cached copy.

Dates are the UTC dates of the fetches (the cache entry's ``fetched_at``), never a clock read here,
so a pinned rebuild from the same inputs writes the same file.
"""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

from ..config import SEED_DIR
from . import toxicity

DAYS = 7
HELD_FILE = SEED_DIR / "ld50_held.json"

HELD, RELEASED, BACK = "held", "released", "back"


def read_held(path: Path | None = None) -> dict[int, dict]:
    """Last run's held LD50s, keyed by CID; empty when none or unreadable."""
    try:
        data = json.loads((path or HELD_FILE).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, list):
        return {}
    return {int(h["cid"]): h for h in data if isinstance(h, dict) and h.get("cid") is not None}


def write_held(events: list[dict], path: Path | None = None) -> Path:
    """The committed record of the LD50s held this run (an empty list when none)."""
    path = path or HELD_FILE
    keep = ("slug", "cid", "ld50_mg_per_kg", "species", "route", "qualifier", "since", "seen")
    rows = [{k: e[k] for k in keep if e.get(k) is not None}
            for e in sorted(events, key=lambda e: (e.get("slug") or "", e["cid"])) if e["kind"] == HELD]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
    return path


def _day(stamp: str | None) -> str | None:
    return stamp[:10] if stamp else None


def _days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def decide(cid: int, rows: list[dict], prior: dict | None, *, live: bool, fetched_at: str | None,
           previous: dict | None) -> tuple[list[dict], dict | None]:
    """(the LD50 rows to assemble the record from, this molecule's hold event or None).

    ``rows`` is what ``toxicity.parse_ld50`` read from this run's answer; ``prior`` the molecule's
    shipped record; ``live`` and ``fetched_at`` where that answer came from (``freshness``);
    ``previous`` last run's held entry for this CID. Pure."""
    slug = (prior or {}).get("slug")
    if not prior or prior.get("ld50_mg_per_kg") is None:
        return rows, None                                     # nothing shipped, nothing to hold
    shipped = {"slug": slug, "cid": cid, "ld50_mg_per_kg": prior["ld50_mg_per_kg"],
               "species": prior.get("ld50_species"), "route": prior.get("ld50_route"),
               "qualifier": prior.get("ld50_qualifier")}
    if toxicity.primary_ld50(rows, slug) is not None:
        if previous:                                          # it came back: the hold ends, the clock resets
            return rows, {**shipped, "kind": BACK, "since": previous.get("since"), "now": toxicity.primary_ld50(rows, slug)}
        return rows, None
    held_rows = copy.deepcopy(prior.get("toxicity") or [])
    today = _day(fetched_at)
    if not live or today is None:
        if previous:                                          # a cache hit keeps a hold; the clock does not move
            return held_rows, {**shipped, "kind": HELD, "since": previous.get("since"),
                               "seen": previous.get("seen"), "live": False}
        return rows, None                                     # not ours: the export guard refuses it
    since = (previous or {}).get("since") or today
    if previous and _days_between(since, today) >= DAYS:
        return rows, {**shipped, "kind": RELEASED, "since": since, "seen": today}
    return held_rows, {**shipped, "kind": HELD, "since": since, "seen": today, "live": True,
                       "first": not previous}


def _value(e: dict) -> str:
    v = e["ld50_mg_per_kg"]
    num = f"{v:,.0f}" if float(v).is_integer() else f"{v:,}"
    return (f"LD50 {toxicity.words(e.get('qualifier'))}{num} mg/kg "
            f"({', '.join(x for x in (e.get('species'), e.get('route')) if x)})")


def release_on(since: str) -> str:
    return date.fromordinal(date.fromisoformat(since).toordinal() + DAYS).isoformat()


def report_line(e: dict) -> str:
    """One event, as the log and the run summary print it."""
    name = e.get("slug") or e["cid"]
    if e["kind"] == RELEASED:
        return (f"{name}: {_value(e)} RELEASED. PubChem's live Toxicity answer has not reported it since "
                f"{e['since']} and still did not on {e['seen']}, so the page now shows no LD50.")
    if e["kind"] == BACK:
        now = e.get("now") or {}
        return (f"{name}: the LD50 is back in PubChem's answer ({now.get('value_num')} mg/kg, "
                f"{now.get('species')}, {now.get('route')}); the hold since {e.get('since')} ends.")
    if not e.get("live"):
        return (f"{name}: {_value(e)} held since {e['since']} (this run read the cached answer, so the "
                f"clock did not move); released on a live fetch on or after {release_on(e['since'])} "
                f"that still lacks it.")
    first = "first seen gone today" if e.get("first") else f"gone since {e['since']}, seen gone again"
    return (f"{name}: {_value(e)} held. PubChem's live Toxicity answer of {e['seen']} no longer reports it "
            f"({first}); the page keeps the shipped value until a live fetch on or after "
            f"{release_on(e['since'])} still lacks it, then it is released.")
