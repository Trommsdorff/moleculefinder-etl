"""Disk cache entries that record when they were fetched, and that expire.

A cache hit and a live fetch are indistinguishable to everything downstream. That is how
the 2026-09-08 snapshot shipped 26 regressed molecules: this machine's ``data/raw_cache``
predated a Wikidata refresh, ``mfetl all`` read it, and the pipeline wrote *worse* values
over good ones with nothing in the run to say so (22 ``wikidata_qid`` replaced by bulk-batch
items, 11 ``summary`` back to "chemical compound", omeprazole's oral LD50 nulled). The
weekly loop fetched fresh and corrected all 26 four minutes later, but only because it
happened to run; nothing had refused the bad write.

The fix has two halves and this module is the first: every cached entry carries the UTC
instant it was fetched, and an entry older than its caller's expiry is not a hit. The
second half is ``load.snapshot_guard``, which reads the dates this module records and
refuses an export in which a cached value overwrites a shipped one.

Which caches get an expiry is a judgement about the SOURCE, not a blanket policy:

* **Wikidata** (descriptions, QIDs) and **PUG-View** (Toxicity, GHS) are *derived* views
  that upstream rewrites: items get merged and split, annotations get added. A month-old
  copy is a claim about the past presented as the present. These expire.
* **PubChem synonyms** expire too, since 2026-09-12, on PUG-View's 30 days. A name list was
  treated as what a CID *is*, but depositors add and reorder names: 12 molecules' lists moved
  between 2026-09-09 and 2026-09-12, CI's copies never expired, and so every fresh local
  fetch disagreed with the weekly run until someone restored CI's versions by hand.
* **PubChem properties** do not: a CID's formula, weight and InChI are what that CID *is*.
  That cache is left exactly as it was, on purpose. Re-fetching 788 CIDs weekly to re-learn
  that caffeine is still C8H10N4O2 buys nothing and spends the rate limit that the
  annotation warm-up actually needs.

The envelope is discriminated by the ``_mfetl_cache`` key, so an entry written before this
module existed still reads back: it comes back with ``fetched_at`` of None, which means
*unknown age*, which is never fresh. That is deliberate. The entries that caused the
incident were exactly the ones whose age nobody could state.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ENVELOPE_KEY = "_mfetl_cache"
ENVELOPE_VERSION = 1
STAMP = "%Y-%m-%dT%H:%M:%SZ"


def now() -> str:
    """This instant, as the UTC stamp every cache entry and the freshness map use."""
    return datetime.now(timezone.utc).strftime(STAMP)


def parse(stamp: str | None) -> datetime | None:
    """Parse a stamp back to an aware datetime; None for absent or unreadable."""
    if not stamp:
        return None
    try:
        return datetime.strptime(stamp, STAMP).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class Entry:
    """A cached value, the instant it was fetched, and whether THIS run fetched it.

    ``fetched_at`` of None means the entry predates the envelope, i.e. unknown age.
    ``live`` is the signal the export guard actually turns on: a value that came back from
    the network in this run is by definition fresher than any value already on disk, so it
    is allowed to overwrite one. A cache hit is not, however recently it was written.
    """
    value: Any
    fetched_at: str | None
    live: bool = False

    @property
    def dated(self) -> bool:
        return self.fetched_at is not None


def wrap(value: Any, fetched_at: str | None = None) -> dict:
    """The on-disk envelope for ``value``."""
    return {ENVELOPE_KEY: ENVELOPE_VERSION, "fetched_at": fetched_at or now(), "value": value}


def unwrap(raw: Any) -> Entry:
    """Read an envelope, or adopt a pre-envelope payload as unknown-age."""
    if isinstance(raw, dict) and ENVELOPE_KEY in raw:
        return Entry(raw.get("value"), raw.get("fetched_at"), live=False)
    return Entry(raw, None, live=False)


def is_fresh(fetched_at: str | None, max_age_days: float, at: str | None = None) -> bool:
    """Is an entry fetched at ``fetched_at`` still usable ``at`` this instant?

    Unknown age is never fresh: the whole point is that an undated entry is the shape the
    incident had. A non-positive ``max_age_days`` disables the cache outright, which is the
    honest reading of "expire immediately" and makes the expiry easy to switch off in a run
    that must not trust the disk at all.
    """
    if max_age_days <= 0:
        return False
    when = parse(fetched_at)
    if when is None:
        return False
    reference = parse(at) or datetime.now(timezone.utc)
    if when > reference:                      # a clock skew, or a stamp from the future
        return True
    return reference - when <= timedelta(days=max_age_days)


def read_json(path: Path, max_age_days: float, at: str | None = None) -> Entry | None:
    """Return a FRESH entry, or None for a miss, an expired entry or an unreadable file.

    A corrupt file is a miss rather than a crash: the caller's next step is to fetch, which
    is also the repair.
    """
    if not path.exists():
        return None
    try:
        entry = unwrap(json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError):
        return None
    return entry if is_fresh(entry.fetched_at, max_age_days, at) else None


def write_json(path: Path, value: Any, fetched_at: str | None = None) -> Entry:
    """Write ``value`` in a dated envelope, creating the directory."""
    stamp = fetched_at or now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(wrap(value, stamp)))
    return Entry(value, stamp, live=True)
