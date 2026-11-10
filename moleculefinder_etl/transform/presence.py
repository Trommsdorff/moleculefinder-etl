"""How a molecule comes to be in a food, drink, product or world: the presence field (build plan
everyday chemistry 2026-11, phase 1; rulings b and g of 2026-11-09).

Every curated list entry says, by hand, how its molecule comes to be there, so no page ever shows an
inferred mark. One of five values:

* ``natural``  Naturally present        caffeine in coffee
* ``added``    Added by the maker       caffeine in energy drinks
* ``body``     Made by your body        adenosine in the Morning coffee world
* ``formed``   Formed when roasted (baked, cooked, cured, aged) or Formed by fermentation, with
               ``formed_when`` from the closed list ``FORMED_WHEN``, so the words are true for each
               food (bread is baked, not roasted)
* ``none``     no mark, with a written reason in ``presence_note``

``presence_note`` is the one-line reason, shown later in Sources and notes; ``none`` must carry one.

WHERE THE MARKS LIVE (all hand curated, nothing fetched):
* every entry of ``food_hubs.yaml`` and ``product_hubs.yaml``, each ``foods:`` row of the curated
  overlays (an overlay row and a food-hub row for the same molecule must agree), and the rosters in
  ``worlds.yaml``;
* ``presence_wikidata.yaml`` for the rows a product reads from a Wikidata item, by product and molecule;
* by RULE: a DailyMed label row is ``added`` (a label is the maker's own declaration of what it put
  in), and a class page's row (PFAS) is ``none``.

WHAT IS EXPORTED. On each marked row, ``presence`` is ``{"value", "formed_when"?, "note"?, "rule"?,
"confidence": "from_source", "source": "curated"}``: on a molecule's curated ``food`` and ``product``
categories, on every ``products.json`` molecule entry and, copied from it, on the molecule's own
``products`` rows, so both directions are one fact.

WHAT STOPS THE BUILD. A curated entry with no mark, an unknown value, ``formed`` with no
``formed_when`` (or a ``formed_when`` outside the list), ``none`` with no reason, or two marks for one
fact that disagree: ``PresenceError`` (a ``SystemExit``), here and in ``pytest``, so it never reaches
Monday. A Wikidata row a weekly refresh adds with no mark in the seed is NOT an error: an outside edit
must not break Monday. It is exported with ``presence: null`` (the page will say "Not marked"), listed in
``data/seed/presence_unmarked.json`` and the run summary, and the run goes on.
"""
from __future__ import annotations

import glob
import json
import logging
from pathlib import Path

import yaml

from ..config import SEEDS_DIR
from .confidence import FROM_SOURCE

log = logging.getLogger("mfetl")

VALUES = ("natural", "added", "body", "formed", "none")
# The closed list of how a molecule is formed, with the words the page shows.
FORMED_WHEN = {
    "roasted": "Formed when roasted",
    "baked": "Formed when baked",
    "cooked": "Formed when cooked",
    "cured": "Formed when cured",
    "aged": "Formed when aged",
    "fermentation": "Formed by fermentation",
}
WORDS = {"natural": "Naturally present", "added": "Added by the maker", "body": "Made by your body"}
SOURCE = "curated"                                   # registry key; display name "MoleculeFinder curated"
NOTE_MAX = 160
_DASHES = ("—", "–")

FOOD_HUBS_YAML = SEEDS_DIR / "food_hubs.yaml"
PRODUCT_HUBS_YAML = SEEDS_DIR / "product_hubs.yaml"
WORLDS_YAML = SEEDS_DIR / "worlds.yaml"
WIKIDATA_YAML = SEEDS_DIR / "presence_wikidata.yaml"
CURATED_DIR = SEEDS_DIR.parent / "curated"

# The rules: no seed entry, one mark for every row of the kind.
LABEL_MARK = {"value": "added", "rule": "label", "confidence": FROM_SOURCE, "source": SOURCE}
CLASS_MARK = {"value": "none", "rule": "class",
              "note": "A class page: its molecules share a structure, not a source.",
              "confidence": FROM_SOURCE, "source": SOURCE}


class PresenceError(SystemExit):
    """A curated presence mark is missing or malformed: the build stops, naming every problem."""


def wording(mark: dict | None) -> str:
    """The words a page shows for a mark ("" for none, "Not marked" for an unmarked row)."""
    if mark is None:
        return "Not marked"
    if mark["value"] == "formed":
        return FORMED_WHEN[mark["formed_when"]]
    return WORDS.get(mark["value"], "")


def parse(entry: dict, where: str, errors: list[str]) -> dict | None:
    """One seed entry's mark -> the exported shape, or None with the problem appended to ``errors``."""
    value = entry.get("presence")
    when = entry.get("formed_when")
    note = " ".join(str(entry.get("presence_note") or "").split())
    bad = []
    if value is None:
        bad.append("no presence mark")
    elif value not in VALUES:
        bad.append(f"presence {value!r} is not one of {', '.join(VALUES)}")
    if value == "formed" and not when:
        bad.append("presence formed with no formed_when")
    if when and value != "formed":
        bad.append(f"formed_when {when!r} on a mark that is not formed")
    if when and when not in FORMED_WHEN:
        bad.append(f"formed_when {when!r} is not one of {', '.join(FORMED_WHEN)}")
    if value == "none" and not note:
        bad.append("presence none with no written reason (presence_note)")
    if note and any(d in note for d in _DASHES):
        bad.append("presence_note has an em or en dash")
    if len(note) > NOTE_MAX:
        bad.append(f"presence_note is {len(note)} characters, over {NOTE_MAX}")
    if "inferred" in note.lower():
        bad.append("presence_note says inferred")
    if bad:
        errors.extend(f"{where}: {b}" for b in bad)
        return None
    mark = {"value": value}
    if when:
        mark["formed_when"] = when
    if note:
        mark["note"] = note
    mark["confidence"] = FROM_SOURCE
    mark["source"] = SOURCE
    return mark


def _entries(rows, where: str, errors: list[str]) -> list[tuple[str, dict]]:
    """A seed list of molecule entries -> [(slug, the entry as a dict)]; a bare slug has no mark."""
    out = []
    for i, row in enumerate(rows or []):
        if isinstance(row, dict):
            slug = str(row.get("slug") or "").strip()
            if not slug:
                errors.append(f"{where}[{i}]: an entry with no slug")
                continue
            out.append((slug, row))
        else:
            out.append((str(row).strip(), {}))
    return out


def _put(marks: dict, key: tuple, mark: dict | None, where: str, errors: list[str]) -> None:
    if mark is None:
        return
    if key in marks and marks[key][0] != mark:
        errors.append(f"{where}: marked {wording(mark) or 'none'!r} here and "
                      f"{wording(marks[key][0]) or 'none'!r} in {marks[key][1]}; one fact, one mark")
        return
    marks.setdefault(key, (mark, where))


def load_marks(food_hubs: Path | None = None, product_hubs: Path | None = None, worlds: Path | None = None,
               curated_dir: Path | None = None, wikidata: Path | None = None) -> dict[str, dict]:
    """Every hand mark, validated: {"food": {(hub, slug): mark}, "product": {...}, "world": {(world,
    slug): mark}, "wikidata": {(product, slug): mark}}. Raises ``PresenceError`` naming every problem."""
    errors: list[str] = []
    out: dict[str, dict] = {"food": {}, "product": {}, "world": {}, "wikidata": {}}
    for kind, path in (("food", food_hubs or FOOD_HUBS_YAML), ("product", product_hubs or PRODUCT_HUBS_YAML)):
        data = yaml.safe_load(path.read_text()) if path.exists() else {}
        for hub, entry in (data or {}).items():
            for slug, row in _entries((entry or {}).get("molecules"), f"{path.name} {hub}", errors):
                where = f"{path.name} {hub}/{slug}"
                _put(out[kind], (hub, slug), parse(row, where, errors), where, errors)
    for f in sorted(glob.glob(str((curated_dir or CURATED_DIR) / "*.yaml"))):
        data = yaml.safe_load(Path(f).read_text()) or {}
        for row in data.get("foods") or []:
            hub = row.get("category")
            if not hub:
                continue
            where = f"curated/{Path(f).name} foods {hub}"
            _put(out["food"], (hub, data.get("slug")), parse(row, where, errors), where, errors)
    wpath = worlds or WORLDS_YAML
    for w in ((yaml.safe_load(wpath.read_text()) or {}).get("worlds") or []) if wpath.exists() else []:
        for slug, row in _entries(w.get("molecules"), f"worlds.yaml {w.get('slug')}", errors):
            where = f"worlds.yaml {w.get('slug')}/{slug}"
            _put(out["world"], (w.get("slug"), slug), parse(row, where, errors), where, errors)
    kpath = wikidata or WIKIDATA_YAML
    data = (yaml.safe_load(kpath.read_text()) or {}) if kpath.exists() else {}
    for product, rows in (data.get("products") or {}).items():
        for slug, row in _entries(rows, f"{kpath.name} {product}", errors):
            where = f"{kpath.name} {product}/{slug}"
            _put(out["wikidata"], (product, slug), parse(row, where, errors), where, errors)
    if errors:
        raise PresenceError("presence marks refused (build plan everyday chemistry, phase 1):\n  "
                            + "\n  ".join(errors))
    return {k: {key: m for key, (m, _) in v.items()} for k, v in out.items()}


def mark_categories(records: list[dict], marks: dict[str, dict] | None = None) -> int:
    """Stamp ``presence`` on every curated ``food`` and ``product`` category of every record. A curated
    category with no mark stops the build (``PresenceError``). Returns how many were marked."""
    marks = load_marks() if marks is None else marks
    missing, n = [], 0
    for r in records:
        for c in r.get("categories") or []:
            if c.get("kind") not in ("food", "product") or c.get("source") != "curated":
                continue
            mark = marks[c["kind"]].get((c["slug"], r["slug"]))
            if mark is None:
                missing.append(f"{c['kind']} {c['slug']}/{r['slug']}")
                continue
            c["presence"] = dict(mark)
            n += 1
    if missing:
        raise PresenceError("presence: a curated entry has no mark:\n  " + "\n  ".join(sorted(missing)))
    return n


def mark_products(products: list[dict], marks: dict[str, dict] | None = None) -> list[dict]:
    """Stamp ``presence`` on every molecule entry of every product, by the entry's role: a curated hub's
    mark, a world's, a label's or a class's by rule, a Wikidata row's from ``presence_wikidata.yaml``.
    A curated or world entry with no mark stops the build. A Wikidata row with no mark gets ``presence:
    null`` and is returned (the unmarked list), never an error."""
    marks = load_marks() if marks is None else marks
    missing: list[str] = []
    unmarked: list[dict] = []
    used: set[tuple] = set()
    for p in products:
        for m in p.get("molecules") or []:
            role = m.get("role")
            if role in ("active", "inactive"):
                m["presence"] = dict(LABEL_MARK)
            elif role == "class":
                m["presence"] = dict(CLASS_MARK)
            elif role == "curated":
                mark = marks["food"].get((m.get("hub"), m["slug"]))
                if mark is None:
                    missing.append(f"product {p['slug']}: curated {m.get('hub')}/{m['slug']}")
                m["presence"] = dict(mark) if mark else None
            elif role == "world":
                world = (p.get("source") or {}).get("world") if (p.get("source") or {}).get("type") == "world" \
                    else next((s.get("world") for s in p.get("also") or [] if s.get("type") == "world"), None)
                mark = marks["world"].get((world, m["slug"]))
                if mark is None:
                    missing.append(f"product {p['slug']}: world {world}/{m['slug']}")
                m["presence"] = dict(mark) if mark else None
            elif role == "part":
                mark = marks["wikidata"].get((p["slug"], m["slug"]))
                used.add((p["slug"], m["slug"]))
                m["presence"] = dict(mark) if mark else None
                if mark is None:
                    qid = next((s.get("qid") for s in [p.get("source") or {}, *(p.get("also") or [])]
                                if s.get("type") == "wikidata"), None)
                    unmarked.append({"product": p["slug"], "molecule": m["slug"], "qid": qid,
                                     "property": m.get("property")})
            else:
                missing.append(f"product {p['slug']}: {m['slug']} has role {role!r}, which no rule marks")
    if missing:
        raise PresenceError("presence: a product entry has no mark:\n  " + "\n  ".join(missing))
    for key in sorted(set(marks["wikidata"]) - used):
        log.info("  presence: presence_wikidata.yaml marks %s/%s, a row Wikidata no longer lists (unused)", *key)
    return sorted(unmarked, key=lambda u: (u["product"], u["molecule"]))


def unmarked_line(u: dict) -> str:
    return (f"{u['product']}: {u['molecule']} (Wikidata {u.get('qid') or '?'} {u.get('property') or ''}) "
            "has no presence mark; exported unmarked. Add it to sources/seeds/presence_wikidata.yaml.")


def write_unmarked(unmarked: list[dict], path: Path) -> Path:
    path.write_text(json.dumps(unmarked, ensure_ascii=False, indent=1) + "\n")
    return path
