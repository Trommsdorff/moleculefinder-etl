"""Molecule of the week: compile ``sources/seeds/featured.yaml`` into ``featured.json``.

The seed maps each ISO week (1 to 53) to a molecule slug and an optional one-line hook. The web
renders the result three ways: a block on the home page, the ``/molecule-of-the-week`` archive and
its RSS feed.

**Which week is "this week".** The ISO week of the snapshot's own ``refreshed`` date (meta.json),
passed in by ``snapshot_export.export``. Never the clock of whatever machine builds the site: the
weekly CI run, a local run later the same week and the Vercel build of either all name the same
molecule, because they all read the same snapshot date.

**Stateless.** Nothing is stored between runs. The history is recomputed from the seed every time,
from ``START_WEEK`` (the week the feature launched) to the current week, so it is a pure function
of the seed, the catalog and one date. The price is stated in the seed's header: editing a week that
has already run rewrites the archive.

**Validated like every other curated seed** (``relationships.attach_why_it_matters`` is the model):
every problem is collected and the run fails with all of them listed, so a typo cannot ship a block
pointing at a page that does not exist.
"""
from __future__ import annotations
import csv
import logging
import re
from datetime import date, timedelta

import yaml

from ..config import SEEDS_DIR
from .confidence import FROM_SOURCE
from .relationships import _ADVICE_PATTERNS
from .slugs import slugify

log = logging.getLogger("mfetl")

FEATURED_YAML = SEEDS_DIR / "featured.yaml"
DEFERRED_CSV = SEEDS_DIR / "deferred_rows.csv"

# The week the feature launched: 2026-W39, Monday 2026-09-21. The archive and the feed start here
# and grow by one week per week. Moving it rewrites the archive, so it is a constant, not seed data.
START_WEEK = (2026, 39)
WEEKS = range(1, 54)
HOOK_MIN, HOOK_MAX = 40, 170
_ENTRY_KEYS = {"week", "slug", "hook"}


def iso_label(year: int, week: int) -> str:
    """(2026, 39) -> '2026-W39'."""
    return f"{year}-W{week:02d}"


def monday(year: int, week: int) -> date:
    return date.fromisocalendar(year, week, 1)


def load_featured(path=None) -> list | None:
    """The raw ``weeks`` list from the seed, or None when there is no seed (the feature is off)."""
    path = path or FEATURED_YAML
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("weeks") if isinstance(data, dict) else data


def _held_rows() -> list[dict]:
    """deferred_rows.csv: molecules pulled back out of a tranche. Comment lines start with '#'."""
    if not DEFERRED_CSV.exists():
        return []
    with DEFERRED_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(line for line in f if not line.startswith("#")))


def _skeleton(rec: dict) -> str | None:
    """The first block of the InChIKey: the connectivity, without stereo or charge."""
    key = rec.get("inchikey") or ""
    return key.split("-")[0] or None


def _hook_errors(hook: str) -> list[str]:
    errors = []
    if "\n" in hook or "\r" in hook:
        errors.append("the hook must be one line")
    if not HOOK_MIN <= len(hook) <= HOOK_MAX:
        errors.append(f"the hook is {len(hook)} characters, the rule is {HOOK_MIN} to {HOOK_MAX}")
    if "—" in hook or "–" in hook:
        errors.append("em-dash or en-dash in the hook (house rule)")
    if not hook.endswith((".", "!", "?")):
        errors.append("the hook must end with a full stop")
    for pat in _ADVICE_PATTERNS:
        if re.search(pat, hook, re.I):
            errors.append(f"the hook reads as advice or dosing: /{pat}/")
    return errors


def compile_queue(molecules: list[dict], entries: list | None = None) -> dict[int, dict] | None:
    """Validate the seed against the catalog being exported; return {week: {slug, hook}}.

    Returns None when there is no seed. Raises SystemExit listing every problem otherwise.
    """
    if entries is None:
        entries = load_featured()
        if entries is None:
            return None
    by_slug = {m["slug"]: m for m in molecules}
    # A structure skeleton held by two catalog records is a molecule that appears twice: the same
    # compound under two pages, or a stereoisomer or salt twin a reader would take for it.
    skeletons: dict[str, list[str]] = {}
    for m in molecules:
        sk = _skeleton(m)
        if sk:
            skeletons.setdefault(sk, []).append(m["slug"])
    held = _held_rows()
    held_cids = {int(r["pubchem_cid"]) for r in held if (r.get("pubchem_cid") or "").strip()}
    held_slugs = {slugify(r["molecule"]) for r in held if (r.get("molecule") or "").strip()}

    problems: list[str] = []
    queue: dict[int, dict] = {}
    seen_weeks: set[int] = set()
    week_of_slug: dict[str, int] = {}
    if not isinstance(entries, list):
        raise SystemExit("featured compile failed:\n  featured.yaml needs a `weeks:` list")
    for i, e in enumerate(entries, 1):
        if not isinstance(e, dict):
            problems.append(f"entry {i}: not a mapping")
            continue
        unknown = sorted(set(e) - _ENTRY_KEYS)
        if unknown:
            problems.append(f"entry {i}: unknown key(s) {', '.join(map(str, unknown))}")
        week = e.get("week")
        if not isinstance(week, int) or isinstance(week, bool) or week not in WEEKS:
            problems.append(f"entry {i}: week must be a whole number from 1 to 53, got {week!r}")
            continue
        at = f"week {week}"
        if week in seen_weeks:
            problems.append(f"{at}: listed twice")
            continue
        seen_weeks.add(week)
        slug = e.get("slug")
        if not isinstance(slug, str) or not slug.strip():
            problems.append(f"{at}: no slug")
            continue
        slug = slug.strip()
        hook = e.get("hook")
        if hook is not None and not isinstance(hook, str):
            problems.append(f"{at}: the hook must be text")
            hook = None
        hook = hook.strip() if isinstance(hook, str) and hook.strip() else None
        queue[week] = {"slug": slug, "hook": hook}

        rec = by_slug.get(slug)
        if rec is None:
            problems.append(f"{at}: unknown slug '{slug}'")
            continue
        if slug in week_of_slug:
            problems.append(f"{at}: '{slug}' is already week {week_of_slug[slug]}")
        week_of_slug.setdefault(slug, week)
        if rec.get("hand_model") or rec.get("macromolecule") or not rec.get("structure_svg"):
            problems.append(f"{at}: '{slug}' is a macromolecule or has no structure to draw")
        if not ((rec.get("why_it_matters") or {}).get("text") or "").strip():
            problems.append(f"{at}: '{slug}' has no why_it_matters line")
        if rec.get("cid") in held_cids or slug in held_slugs:
            problems.append(f"{at}: '{slug}' is held in deferred_rows.csv")
        twins = [s for s in skeletons.get(_skeleton(rec) or "", []) if s != slug]
        if twins:
            problems.append(f"{at}: '{slug}' appears twice in the catalog, it shares its structure "
                            f"skeleton with {', '.join(sorted(twins))}")
        if hook:
            problems.extend(f"{at}: {err}" for err in _hook_errors(hook))

    missing = [w for w in WEEKS if w not in seen_weeks]
    if missing:
        problems.append(f"missing week(s): {', '.join(map(str, missing))}")
    if problems:
        raise SystemExit("featured compile failed:\n  " + "\n  ".join(problems))
    log.info("  molecule of the week: %d weeks compiled, %d with a hook",
             len(queue), sum(1 for q in queue.values() if q["hook"]))
    return queue


def _weeks_back(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    """ISO (year, week) from ``end`` back to ``start``, both inclusive. Week 53 appears only in
    the years that have one, because the walk steps a real Monday back seven days at a time."""
    stop = monday(*start)
    day = monday(*end)
    if day < stop:
        return [end]
    out = []
    while day >= stop:
        y, w, _ = day.isocalendar()
        out.append((y, w))
        day -= timedelta(days=7)
    return out


def _item(queue: dict[int, dict], by_slug: dict[str, dict], year: int, week: int) -> dict:
    entry = queue[week]
    rec = by_slug[entry["slug"]]
    hook = entry["hook"]
    return {
        "week": iso_label(year, week),
        "iso_year": year,
        "iso_week": week,
        "monday": monday(year, week).isoformat(),
        "slug": rec["slug"],
        "title": rec["title"],
        "formula": rec.get("molecular_formula"),
        "line": hook or rec["why_it_matters"]["text"],
        "line_source": "hook" if hook else "why_it_matters",
        "confidence": FROM_SOURCE,
        "source": "MoleculeFinder curated",
    }


def build_featured(queue: dict[int, dict], molecules: list[dict], refreshed: str) -> dict:
    """The featured.json payload for a snapshot refreshed on ``refreshed`` (YYYY-MM-DD).

    ``current`` is that date's ISO week; ``weeks`` is every week from START_WEEK to it, newest
    first, so ``weeks[0]`` is ``current``. A pure function of its arguments: it reads no clock.
    """
    by_slug = {m["slug"]: m for m in molecules}
    year, week, _ = date.fromisoformat(refreshed).isocalendar()
    weeks = [_item(queue, by_slug, y, w) for y, w in _weeks_back(START_WEEK, (year, week))]
    return {"start": iso_label(*START_WEEK), "current": weeks[0], "weeks": weeks}
