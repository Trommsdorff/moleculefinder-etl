"""How each molecule's *derived* inputs were obtained in this run, for the export guard.

``sources.cache`` knows, per entry, whether a value came off the disk or off the network.
That fact has to survive from the stage that fetched it to the stage that writes the
snapshot, and the stages can run as separate processes (``mfetl seed`` then ``mfetl
transform`` then ``mfetl export``), so it is carried in a file beside the other stage
intermediates rather than in memory.

It is deliberately NOT carried on the records themselves and NOT in ``canon.parquet``.
Both are committed artifacts, and a timestamp that moves every run would put all 788
molecule files (or the parquet, which gates the workflow's heartbeat) into every weekly
diff. That is precisely the churn run 3 removed; a guard that reintroduced it would cost
more than the bug it prevents. ``data/seed/freshness.json`` is gitignored like
``fetched.json`` and ``molecules.json``, and travels with them.

Shape::

    {"wikidata": {"2244": {"fetched_at": "2026-09-08T13:26:41Z", "live": true}},
     "toxicity": {"4594": {"fetched_at": "2026-09-01T06:02:11Z", "live": false}}}

Sources are the two that expire. PubChem properties and synonyms are absent on purpose:
they are cached forever, so there is nothing about their age to record.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import SEED_DIR

log = logging.getLogger("mfetl")

PATH = SEED_DIR / "freshness.json"

WIKIDATA = "wikidata"          # schema:description + the QID, from WDQS
TOXICITY = "toxicity"          # the PUG-View Toxicity annotation the LD50 is parsed from
SOURCES = (WIKIDATA, TOXICITY)


def load(path: Path | None = None) -> dict:
    """The map as last written, or an empty one.

    An empty map is not an error and not a free pass: to the guard, an input it has no
    record of is an input that was not freshly fetched, which is the conservative reading.
    """
    path = path or PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def merge(updates: dict[str, dict], path: Path | None = None) -> dict:
    """Fold ``{source: {cid: entry}}`` into the map on disk and write it back.

    Merging rather than replacing is what lets ``mfetl seed`` record the Wikidata dates and
    ``mfetl transform`` record the PUG-View ones without either erasing the other.
    """
    path = path or PATH
    data = load(path)
    for source, by_cid in updates.items():
        into = data.setdefault(source, {})
        for cid, entry in by_cid.items():
            into[str(cid)] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True))
    return data


def entry(data: dict, source: str, cid: int) -> dict | None:
    """One record's entry for one source, or None if this run never touched it."""
    return (data.get(source) or {}).get(str(cid))


def is_live(data: dict, source: str, cid: int) -> bool:
    """Did this run fetch that input from the network (rather than read it off disk)?"""
    return bool((entry(data, source, cid) or {}).get("live"))


def describe(data: dict, source: str, cid: int) -> str:
    """A phrase for an error message: where the value actually came from."""
    e = entry(data, source, cid)
    if e is None:
        return f"{source}: no fetch recorded in this run"
    if e.get("live"):
        return f"{source}: fetched live at {e.get('fetched_at')}"
    when = e.get("fetched_at") or "an unknown date"
    return f"{source}: cache hit written {when}"


def from_entries(entries: dict) -> dict:
    """``{cid: cache.Entry}`` -> the serialisable per-cid shape stored above."""
    return {str(cid): {"fetched_at": e.fetched_at, "live": bool(e.live)}
            for cid, e in entries.items()}
