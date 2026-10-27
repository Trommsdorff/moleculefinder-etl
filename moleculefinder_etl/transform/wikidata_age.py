"""Wikidata edits age before they ship (trust run 8, Garrett, 2026-10-26).

THE INCIDENT. On 2026-10-25 13:37 UTC an anonymous edit set propane's (Q131189) English label to
"priest". The Monday run read it a day later, and the title came out "Propane (Priest)"; Garrett held
propane's live file by hand on web PR #12. Nothing in the pipeline was wrong by its own rules: the
value was fetched live, it was not the placeholder, and it was the item's real current label.

THE RULE. Not a list of bad names. A CHANGE to a Wikidata text field the site shows (the English
description, the English label and the English aliases; together they feed the summary, the title's
parenthetical, the synonym line and ``wikidata_names``) ships only once it has stood on Wikidata for
``AGE_DAYS``. Until then the value this molecule shipped with stands, in the spirit of the 2026-09-28
placeholder carry (``assemble._carried_summary``). So:

* a value equal to the shipped one is not a change, and an edit reverted on Wikidata before it ages
  is exactly that: it never reaches the site;
* a changed value that the item already carried at the cutoff (now minus ``AGE_DAYS``) ships;
* a changed value introduced after the cutoff is HELD, and reported (``Held``), never silent;
* a molecule with no shipped value (new to the catalog) takes Wikidata's current value, as before.

PER FIELD, NOT PER ITEM. The cheap signal, the item's ``modified`` stamp, would hold every field of an
item edited for any reason (propane's last-but-one edit was a property statement). Instead, for each
item whose values differ from the shipped ones, one request reads the item AS IT STOOD AT THE CUTOFF
(``wikidata.entity_as_of``: the newest revision at or before that instant), and each field is compared
with it. That is one request per changed item, a handful a week, never one per molecule; plus one
batched ``entity_info`` request (50 items each) for the modified dates the report prints.

THE ITEM ITSELF (which QID a CID maps to) is aged the same way: when another item takes the CID, or
the CID loses its item, the change ships only if the item already carried (or no longer carried) the
CID's P662 at the cutoff with the same values; otherwise the shipped item and all its values stand.

WHERE "SHIPPED" COMES FROM. The committed ``data/seed/canon.parquet``, read before the seed stage
overwrites it: it carries each CID's raw Wikidata QID, description, label and aliases exactly as the
snapshot was built from them (the records carry only filtered names). A held value is written back
into the new parquet as the shipped one, so next week compares against it again.

REPRODUCIBLE. The answers are cached in ``raw_cache/wikidata/ageing.json`` (an ``entries`` map, so the
inputs artifact carries them entry by entry). The weekly run asks again every run (the cutoff moves);
a pinned build reuses the weekly run's answers, so it reproduces main's holds exactly, and asks only
for an item the artifact lacks.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from pathlib import Path

from ..config import RAW_CACHE, SEED_DIR
from ..sources import cache, wikidata

log = logging.getLogger("mfetl")

AGE_DAYS = 7
FIELDS = ("desc", "label", "aliases")
# The report's words for them, and for the item itself.
FIELD_NAMES = {"qid": "item", "desc": "description", "label": "label", "aliases": "aliases"}
AGEING_CACHE = RAW_CACHE / "wikidata" / "ageing.json"
# Committed (data/seed is): this week's held values, empty when nothing is held.
HELD_FILE = SEED_DIR / "wikidata_held.json"
# 0 = a fresh read every run outside a pinned build, which reuses whatever main was built from.
AGEING_TTL_DAYS = 0
ALLOW_STALE_WIKIDATA_ENV = "MFETL_ALLOW_STALE_WIKIDATA"


def _value(entry: dict | None, field: str):
    entry = entry or {}
    if field == "aliases":
        return list(entry.get("aliases") or [])
    return entry.get(field) or None


def shipped_from_canon(rows: list[dict]) -> dict[int, dict]:
    """{cid: {"qid", "desc", "label", "aliases"}} from the shipped canon rows (real CIDs only)."""
    out: dict[int, dict] = {}
    for r in rows:
        cid = int(r.get("cid") or 0)
        if cid > 0:
            out[cid] = {"qid": r.get("wikidata_qid"), "desc": r.get("summary"),
                        "label": r.get("wikidata_label"),
                        "aliases": list(r.get("wikidata_aliases") or [])}
    return out


def read_shipped(path: Path | None = None) -> dict[int, dict]:
    """The shipped values from the committed canon.parquet; empty when there is none (a first run)."""
    path = path or (SEED_DIR / "canon.parquet")
    if not path.exists():
        return {}
    from . import canon
    return shipped_from_canon(canon.read_parquet(path))


def changed_fields(fresh: dict, shipped: dict) -> list[str]:
    return [f for f in ("qid", *FIELDS) if _value(fresh, f) != _value(shipped, f)]


def decide(cid: int, fresh: dict, shipped: dict | None, as_of: dict | None) -> tuple[dict, list[str]]:
    """The Wikidata entry to build this CID from, and the fields held back.

    ``fresh`` is this run's entry (``qid``, ``desc``, ``label``, ``aliases``), ``shipped`` the one
    the molecule shipped with (None for a new molecule), ``as_of`` the relevant item as it stood at
    the cutoff (``wikidata.entity_as_of``; None when it had no revision that old or could not be read,
    which holds). Pure: the same inputs give the same answer on any machine."""
    if shipped is None:
        return fresh, []
    changed = changed_fields(fresh, shipped)
    if not changed:
        return fresh, []
    if "qid" not in changed:
        # The same item: each field on its own. A field ships when the item already carried this
        # value at the cutoff; otherwise the shipped value stands.
        out, held = dict(fresh), []
        for f in changed:
            if as_of is not None and _value(as_of, f) == _value(fresh, f):
                continue
            out[f] = _value(shipped, f)
            held.append(f)
        return out, held
    # The item changed. ``as_of`` is the incoming item at the cutoff, or the outgoing one when the
    # CID lost its item. Either way it ships only if the cutoff already looked like today.
    if fresh.get("qid"):
        settled = (as_of is not None and str(cid) in (as_of.get("p662") or [])
                   and all(_value(as_of, f) == _value(fresh, f) for f in FIELDS))
    else:
        settled = as_of is not None and str(cid) not in (as_of.get("p662") or [])
    if settled:
        return fresh, []
    out = dict(fresh)
    for f in ("qid", *FIELDS):
        out[f] = _value(shipped, f)
    return out, changed


def cutoff(at: str | None = None) -> str:
    """The instant a value must already have stood on Wikidata by: ``AGE_DAYS`` before ``at``."""
    now = cache.parse(at or cache.now())
    return (now - timedelta(days=AGE_DAYS)).strftime(cache.STAMP)


def _read_cache(path: Path) -> dict[str, dict]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    entries = raw.get("entries") if isinstance(raw, dict) else None
    return entries if isinstance(entries, dict) else {}


def _ageing(qids: list[str], at: str) -> dict[str, dict]:
    """{qid: {"checked_at", "cutoff", "modified", "lastrevid", "as_of"}} for the given items, from
    the cache where it may be reused (a pinned build), else asked now. A failed request fails the
    run, as a failed Wikidata refresh does; ``MFETL_ALLOW_STALE_WIKIDATA=1`` instead leaves the item
    unanswered, which holds every change on it."""
    path = AGEING_CACHE
    stored = _read_cache(path)
    pinned = os.getenv("MFETL_INPUTS") == "pinned"
    reuse = {q: stored[q] for q in qids if q in stored
             and cache.is_fresh(stored[q].get("checked_at"), AGEING_TTL_DAYS, at)}
    ask = [q for q in qids if q not in reuse]
    asked: dict[str, dict] = {}
    if ask:
        when = cutoff(at)
        try:
            info = wikidata.entity_info(ask)
            for q in ask:
                asked[q] = {"checked_at": at, "cutoff": when,
                            "modified": (info.get(q) or {}).get("modified"),
                            "lastrevid": (info.get(q) or {}).get("lastrevid"),
                            "as_of": wikidata.entity_as_of(q, when)}
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            if os.getenv(ALLOW_STALE_WIKIDATA_ENV) != "1":
                raise wikidata.WikidataQueryError(
                    f"wikidata ageing: could not read {len(ask)} item(s) as of the cutoff ({detail}). "
                    f"Without that a changed value cannot be told from a vandal edit. Set "
                    f"{ALLOW_STALE_WIKIDATA_ENV}=1 to hold every such change instead.") from exc
            log.warning("wikidata ageing: query failed (%s); %s=1, so every change on %d item(s) is "
                        "held", detail, ALLOW_STALE_WIKIDATA_ENV, len(ask))
            asked = {}
        log.info("  wikidata ageing: %d item(s) read as of %s, %d reused", len(asked), when, len(reuse))
    # A pinned build keeps every entry main was built from (inputs.verify requires them); any other
    # run writes only what it used, so the file holds this run's answers and nothing older.
    keep = {**stored, **asked} if pinned else {**reuse, **asked}
    if asked or not pinned:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({cache.ENVELOPE_KEY: cache.ENVELOPE_VERSION, "entries": keep},
                                   sort_keys=True, ensure_ascii=False))
    return {**reuse, **asked}


def age_entries(fresh: dict[int, dict], shipped: dict[int, dict],
                at: str | None = None) -> tuple[dict[int, dict], list[dict]]:
    """Apply the rule to this run's Wikidata entries (``canon._descriptions_cached``'s output).

    Returns the entries to build from (held fields carry the shipped value) and the held list, one
    dict per held field: cid, qid, field, shipped, held (Wikidata's current value), modified (the
    item's last edit) and the cutoff it was compared at. A CID with no entry this run is left alone."""
    at = at or cache.now()
    candidates = {c: d for c, d in fresh.items()
                  if d is not None and c in shipped and changed_fields(d, shipped[c])}
    if not candidates:
        return fresh, []
    # The item to read: the incoming one, or the outgoing one when the CID lost its item.
    item = {c: d.get("qid") or shipped[c].get("qid") for c, d in candidates.items()}
    answers = _ageing(sorted({q for q in item.values() if q}), at)
    out = dict(fresh)
    held: list[dict] = []
    for c in sorted(candidates):
        d, answer = candidates[c], answers.get(item[c]) or {}
        entry, fields = decide(c, d, shipped[c], answer.get("as_of"))
        out[c] = {**d, **{k: entry.get(k) for k in ("qid", *FIELDS)}}
        for f in fields:
            held.append({"cid": c, "qid": item[c], "field": FIELD_NAMES[f],
                         "shipped": _value(shipped[c], f), "held": _value(d, f),
                         "modified": answer.get("modified"), "cutoff": answer.get("cutoff")})
    return out, held


def report_line(h: dict) -> str:
    """One held change, as the log, the run summary and the notice print it."""
    def show(v):
        return json.dumps(v, ensure_ascii=False)
    return (f"{h.get('slug') or h['cid']}: {h['field']} held, shipped {show(h['shipped'])}, "
            f"Wikidata now {show(h['held'])}, item {h['qid']} modified {h.get('modified') or 'unknown'}")


def write_held(held: list[dict], path: Path | None = None) -> Path:
    """The committed record of this week's holds (an empty list when none), stable across reruns."""
    path = path or HELD_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{k: h.get(k) for k in ("slug", "cid", "qid", "field", "shipped", "held", "modified")}
            for h in sorted(held, key=lambda h: (h.get("slug") or "", h["cid"], h["field"]))]
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
    return path
