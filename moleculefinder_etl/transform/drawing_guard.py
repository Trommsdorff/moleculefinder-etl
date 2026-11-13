"""The drawing guard (2026-11-13): every drawing a run would ship, checked against what shipped.

Found at the phase 5 deploy (2026-11-13): the weekly run's only check on the drawings was the web
repo's ``lib/drawings.test.ts``, which pins caffeine's parts, the home page's caffeine and
theobromine pair and one framed pair. Any other part layer, pair drawing or repeat unit could have
been made again on the weekly run's Linux machine and merged unseen. This module closes that at the
root, in the ETL, over EVERY drawing output, not a sample:

- every ``structure_svg`` (with ``structure_svg_key``),
- every part layer in ``structure_parts``,
- every pair in ``compare_drawings.json``,
- every ``structure_repeat_unit``.

**The rule.** Each output carries a reuse key (``drawings.parts_key``, ``pair_key``, ``repeat_key``,
``structures.svg_key``). Compared with the snapshot on disk (what is shipped):

1. **The key is unchanged:** the output must be byte for byte the shipped one. The one exception is a
   palette repaint (a pair's ``b_svg`` or a repeat unit's ``svg``, when ``structures.RECIPE_VERSION``
   moved on purpose): only that drawing's colours and its ``palette`` field may differ, never a
   coordinate. Anything else STOPS the run.
2. **The key moved, or the entry appeared or went:** allowed when the guard can name the input that
   moved, read from the two snapshots themselves: a new molecule or pair; the recipe version; a
   SMILES; the shipped drawing the output rests on; or only the words a seed gives it (a caption, a
   part's label, sentence or source note, a repeat unit's label), with every drawn byte unchanged.
   Each one is listed by name with its reason, so a person sees every drawing made or remade.
3. **The key moved and none of those did:** the output was made again from inputs that did not
   move. Either this machine computes it differently (the parts key holds which atoms RDKit's
   patterns match, and the layers come from reading the drawing on this machine), or a seed's
   patterns (``structure_parts.yaml``, a pair's ``shipped:`` or ``stereo:`` entry, a repeat unit's
   linkage) changed without its data being built and committed with it. That STOPS the run. A
   person who changed such a seed on purpose builds on the Mac with ``MFETL_DRAWING_SEEDS_CHANGED=1``
   and commits the data with the seed; the weekly workflow never sets it (a test holds that).

Also stopped: a pair whose mark is drawn on the second molecule's SHIPPED drawing
(``mode: shipped`` with ``b_layer``: isotretinoin vs tretinoin) when that drawing moved while the
pair's key held, because that key does not cover the second drawing and the mark would sit on the
wrong pixels.

A stop goes through the refusal path every other check uses (``pipeline._preflight``): the run fails
before the database load and before anything is written, the summary names each entry and what
differs, the workflow's alarm opens its issue, and the live site keeps last week's data. The guard
reads and compares only: it calls nothing that reads, lays out or draws, so it changes no output.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import drawings, structures

log = logging.getLogger("mfetl")

# Set on the build that carries a deliberate change to a drawing seed's patterns (never in the
# weekly workflow): changes the guard cannot attribute from the data are then allowed and listed.
SEEDS_CHANGED_ENV = "MFETL_DRAWING_SEEDS_CHANGED"

# The seed words an output carries verbatim: a change to only these, with every drawn byte the
# same, is a person's edit of the seed and cannot come from a machine.
_PART_WORDS = ("label", "sentence", "from")
_PAIR_WORDS = ("caption",)
_REPEAT_WORDS = ("label",)

# How many names the plain-text block (the all-clear and alarm summaries, the issue) lists before
# it says how many more; the run job's own summary page lists every one.
TEXT_LIMIT = 40


class DrawingChanged(RuntimeError):
    """Raised instead of shipping a drawing that changed with nothing to explain it."""


@dataclass
class Verdict:
    """What the guard found: the four count lines, every drawing made, remade, repainted or
    removed (with why), and every change nothing explains (the stops)."""
    lines: list[str] = field(default_factory=list)
    made: list[str] = field(default_factory=list)
    stops: list[str] = field(default_factory=list)

    @property
    def stopped(self) -> bool:
        return bool(self.stops)

    def text(self, limit: int = TEXT_LIMIT) -> str:
        """The plain block for the log, the all-clear and alarm summaries and the alarm issue."""
        out: list[str] = []
        if self.stops:
            out.append(f"STOPPED: {len(self.stops)} drawing(s) changed with nothing to explain it; "
                       f"nothing was exported and the live site keeps last week's data.")
            out += [f"- {s}" for s in self.stops[:limit]]
            if len(self.stops) > limit:
                out.append(f"- ... and {len(self.stops) - limit} more (the run job's summary lists all)")
        out += self.lines
        if self.made:
            out.append(f"made or remade this run ({len(self.made)}):")
            out += [f"- {m}" for m in self.made[:limit]]
            if len(self.made) > limit:
                out.append(f"- ... and {len(self.made) - limit} more (the run job's summary lists all)")
        else:
            out.append("made or remade this run" + (", other than the stopped entries above" if self.stops
                                                     else "") + ": none")
        return "\n".join(out)

    def markdown(self) -> str:
        """The section of the run job's summary page: every name, no limit."""
        out = ["### Drawings", "",
               ("Every structure drawing, part layer, compare pair and repeat unit, checked against "
               "the shipped snapshot (transform/drawing_guard.py)."), ""]
        if self.stops:
            out += [(f"**STOPPED ({len(self.stops)}): changed with nothing to explain it. Nothing was "
                    f"exported; the live site keeps last week's data.**"), ""]
            out += [f"- {s}" for s in self.stops] + [""]
        out += [f"- {line}" for line in self.lines] + [""]
        if self.made:
            out += [f"**Made or remade this run ({len(self.made)}):**", ""]
            out += [f"- {m}" for m in self.made]
        else:
            out.append("**Made or remade this run" + (", other than the stopped entries above" if self.stops
                                                       else "") + ": none.**")
        return "\n".join(out) + "\n\n"


# ── Reading what shipped ──────────────────────────────────────────────────────────────────────
def shipped(snapshots: Path) -> tuple[dict[int, dict], dict | None]:
    """The molecule records on disk keyed by CID (the key the carry uses) and the shipped
    compare_drawings.json (None if there is none). An unreadable file is skipped, as the carry
    does: everything in it then counts as new, which the summary lists."""
    records: dict[int, dict] = {}
    mol_dir = snapshots / "molecules"
    if mol_dir.is_dir():
        for path in sorted(mol_dir.glob("*.json")):
            try:
                rec = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(rec, dict) and rec.get("cid") is not None:
                records[int(rec["cid"])] = rec
    pairs = None
    path = snapshots / "compare_drawings.json"
    if path.exists():
        try:
            pairs = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pairs = None
    return records, pairs


# ── Small helpers ─────────────────────────────────────────────────────────────────────────────
def _bytes(value) -> str:
    """An output as the export writes it (``json.dumps``, key order kept): byte for byte."""
    return json.dumps(value, ensure_ascii=False)


def _geometry(svg: str | None) -> str | None:
    return drawings.geometry_sha(svg) if svg else None


def _differs(old, new, path: str = "", limit: int = 6) -> list[str]:
    """The paths at which two outputs differ (a part by its id), for a stop line."""
    found: list[str] = []

    def walk(a, b, at: str) -> None:
        if len(found) >= limit or _bytes(a) == _bytes(b):
            return
        if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True):
            found.append(f"{at or 'entry'} (key order)")
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for k in [*a, *[k for k in b if k not in a]]:
                walk(a.get(k), b.get(k), f"{at}.{k}" if at else k)
            return
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b) and at.endswith("parts"):
            for x, y in zip(a, b):
                pid = x.get("id") if isinstance(x, dict) else None
                walk(x, y, f"{at}[{pid}]")
            return
        found.append(at or "entry")

    walk(old, new, path)
    return found


def _without(entry: dict | None, words: tuple[str, ...], nested: str | None = None) -> str:
    """An output's bytes with its key and its seed words taken out: equal for two outputs that
    differ only in the words a seed gives them."""
    if entry is None:
        return _bytes(None)
    e = {k: v for k, v in entry.items() if k != "key" and (nested or k not in words)}
    if nested and isinstance(e.get(nested), list):
        e[nested] = [{k: v for k, v in p.items() if k not in words} if isinstance(p, dict) else p
                     for p in e[nested]]
    return _bytes(e)


def _only_words(prev: dict | None, new: dict | None, words: tuple[str, ...], nested: str | None = None) -> bool:
    """True when two outputs differ in a seed's words and in nothing else but their key."""
    if prev is None or new is None:
        return False
    return (_without(prev, words, nested) == _without(new, words, nested)
            and _without(prev, (), nested) != _without(new, (), nested))


def _what_differs(prev, new) -> str:
    diff = [d for d in _differs(prev, new) if d != "key"]
    return "only the key moved" if not diff else ", ".join(diff) + " differ"


@dataclass
class _Tally:
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, name: str, n: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + n

    def __getitem__(self, name: str) -> int:
        return self.counts.get(name, 0)


class _Guard:
    def __init__(self, allow_seeds: bool):
        self.allow_seeds = allow_seeds
        self.v = Verdict()

    def made(self, name: str, what: str, why: str) -> None:
        self.v.made.append(f"{name}: {what}, {why}")

    def stop(self, name: str, why: str) -> None:
        self.v.stops.append(f"{name}: {why}")

    def unexplained(self, name: str, what: str, detail: str, seed: str) -> bool:
        """A key that moved with no input the data shows moving. Allowed only on a build that says
        a drawing seed changed on purpose; otherwise a stop. True when allowed."""
        if self.allow_seeds:
            self.made(name, what, f"{SEEDS_CHANGED_ENV}=1 (a drawing seed changed on purpose; "
                                  f"here {detail})")
            return True
        self.stop(name, f"{what} with its recipe, SMILES and drawing unchanged ({detail}): either this "
                        f"machine computes it differently, or {seed} changed without its data being "
                        f"built and committed with it (build it on the Mac with "
                        f"{SEEDS_CHANGED_ENV}=1 and commit the data)")
        return False


# ── structure_svg ─────────────────────────────────────────────────────────────────────────────
def _structure_svg(g: _Guard, t: _Tally, rec: dict, old: dict | None) -> None:
    name = f"{rec['slug']} (structure drawing)"
    svg, key = rec.get("structure_svg"), rec.get("structure_svg_key")
    was = (old or {}).get("structure_svg")
    if not svg:
        t.add("none")
        if was:
            g.made(name, "removed", "its SMILES is gone" if not rec.get("isomeric_smiles")
                   else "it no longer has a drawing")
        return
    if old is None or not was:
        t.add("drawn")
        g.made(name, "new", "a new molecule" if old is None else "it had no drawing")
        return
    if key == old.get("structure_svg_key"):
        if svg != was:
            g.stop(name, "changed under an unchanged key (structure_svg)")
        elif rec.get("isomeric_smiles") != old.get("isomeric_smiles"):
            g.stop(name, "kept under an unchanged key although its SMILES moved (the key covers it)")
        else:
            t.add("carried")
        return
    smiles, before = rec.get("isomeric_smiles"), old.get("isomeric_smiles")
    if smiles != before:
        why = "its SMILES changed"
    else:
        # The key is recipe, canvas and SMILES; the SMILES held, so the recipe moved on purpose.
        older = {structures.svg_key(smiles, recipe=r): r for r in structures.RECOLOURABLE} if smiles else {}
        prev = older.get(old.get("structure_svg_key"))
        why = (f"the structure recipe moved from {prev} to {structures.RECIPE_VERSION}" if prev else
               "drawn before the key existed" if old.get("structure_svg_key") is None else
               f"the structure recipe moved (now {structures.RECIPE_VERSION})")
    if _geometry(svg) == _geometry(was):
        t.add("repainted")
        g.made(name, "repainted", why)
    else:
        t.add("drawn")
        g.made(name, "redrawn", why)


# ── structure_parts ───────────────────────────────────────────────────────────────────────────
def _structure_parts(g: _Guard, t: _Tally, rec: dict, old: dict | None) -> None:
    name = f"{rec['slug']} (structure parts)"
    new = rec.get("structure_parts")
    prev = (old or {}).get("structure_parts")
    # The counts, in the recipe's own words (drawings.attach_structure_parts).
    if new is None:
        t.add("none")
    elif new.get("unread"):
        t.add("unreadable")
    elif prev is not None and _bytes(new) == _bytes(prev):
        t.add("carried")
    else:
        t.add("made")
    if old is None:
        if new is not None:
            g.made(name, "new", "a new molecule" + (" (its drawing has no proven atom positions, so no "
                                                    "part is shown)" if new.get("unread") else ""))
        return
    if new is None and prev is None:
        return
    if new is not None and prev is not None and new.get("key") == prev.get("key"):
        moved = [w for w, a, b in (("drawing", _geometry(old.get("structure_svg")),
                                    _geometry(rec.get("structure_svg"))),
                                   ("SMILES", old.get("isomeric_smiles"), rec.get("isomeric_smiles")))
                 if a != b]
        if _bytes(new) != _bytes(prev):
            g.stop(name, "changed under an unchanged key (" + ", ".join(_differs(prev, new)) + ")")
        elif moved:
            g.stop(name, f"kept under an unchanged key although its {' and '.join(moved)} moved (the key "
                         f"covers them, so its layers would sit on the wrong atoms)")
        return
    what = "made" if prev is None else "dropped" if new is None else "remade"
    reasons = []
    if rec.get("isomeric_smiles") != old.get("isomeric_smiles"):
        reasons.append("its SMILES changed")
    if _geometry(rec.get("structure_svg")) != _geometry(old.get("structure_svg")):
        reasons.append("its drawing changed")
    if new is not None and prev is not None and new.get("recipe") != prev.get("recipe"):
        reasons.append(f"the parts recipe moved from {prev.get('recipe')} to {new.get('recipe')}")
    if reasons:
        g.made(name, what, ", ".join(reasons))
        return
    if _only_words(prev, new, _PART_WORDS, "parts"):
        g.made(name, what, "only its words in structure_parts.yaml changed; every layer is as shipped")
        return
    if new is None or prev is None:
        detail = "it " + ("lost its parts" if new is None else "gained parts")
    elif bool(new.get("unread")) != bool(prev.get("unread")):
        detail = ("its drawing now reads as unproven" if new.get("unread")
                  else "its unproven drawing now reads")
    else:
        ids_was = [p.get("id") for p in prev.get("parts") or []]
        ids_now = [p.get("id") for p in new.get("parts") or []]
        if ids_was != ids_now:
            detail = f"parts {ids_was} became {ids_now}"
        else:
            detail = _what_differs({"parts": prev.get("parts")}, {"parts": new.get("parts")})
    g.unexplained(name, what, detail, "structure_parts.yaml")


# ── structure_repeat_unit ─────────────────────────────────────────────────────────────────────
def _repainted(prev: dict, new: dict, svg_field: str) -> bool:
    """Only the palette moved, to the current recipe, and with it only the drawing's colours."""
    if prev.get("palette") == new.get("palette") or new.get("palette") != structures.RECIPE_VERSION:
        return False
    def rest(e: dict) -> str:
        return _bytes({k: v for k, v in e.items() if k not in ("palette", svg_field)})
    return rest(prev) == rest(new) and _geometry(prev.get(svg_field)) == _geometry(new.get(svg_field))


def _repeat_unit(g: _Guard, t: _Tally, rec: dict, old: dict | None) -> None:
    name = f"{rec['slug']} (repeat unit)"
    new = rec.get("structure_repeat_unit")
    prev = (old or {}).get("structure_repeat_unit")
    if new is None and prev is None:
        return
    if new is not None:
        t.add("units")
    if new is None:
        g.made(name, "removed", "it is no longer in repeat_units.yaml")
        return
    if prev is None:
        t.add("drawn")
        g.made(name, "new", "a new molecule" if old is None else "added in repeat_units.yaml")
        return
    if new.get("key") == prev.get("key"):
        if _bytes(new) == _bytes(prev):
            t.add("carried")
        elif _repainted(prev, new, "svg"):
            t.add("repainted")
            g.made(name, "repainted", f"the palette moved from {prev.get('palette')} to {new.get('palette')}")
        else:
            g.stop(name, "changed under an unchanged key (" + ", ".join(_differs(prev, new)) + ")")
        return
    t.add("drawn")
    reasons = []
    if new.get("recipe") != prev.get("recipe"):
        reasons.append(f"the repeat-unit recipe moved from {prev.get('recipe')} to {new.get('recipe')}")
    if new.get("smiles") != prev.get("smiles"):
        reasons.append("its SMILES in repeat_units.yaml changed")
    for k in ("linkage", "units"):
        if new.get(k) != prev.get(k):
            reasons.append(f"its {k} in repeat_units.yaml changed")
    if reasons:
        g.made(name, "redrawn", ", ".join(reasons))
    elif _only_words(prev, new, _REPEAT_WORDS):
        g.made(name, "remade", "only its label in repeat_units.yaml changed; the drawing is as shipped")
    else:
        g.unexplained(name, "redrawn", _what_differs(prev, new), "repeat_units.yaml")


# ── compare_drawings.json ─────────────────────────────────────────────────────────────────────
def _pair(g: _Guard, t: _Tally, slug: str, new: dict, prev: dict | None,
          now: dict[str, dict], was: dict[str, dict]) -> None:
    name = f"{slug} (compare drawing)"
    if prev is None:
        t.add("made")
        g.made(name, "new", "a new pair")
        return
    a_now, b_now = now.get(new.get("a"), {}), now.get(new.get("b"), {})
    a_was, b_was = was.get(prev.get("a"), {}), was.get(prev.get("b"), {})
    if new.get("key") == prev.get("key"):
        # Its mark drawn on the second molecule's SHIPPED drawing: that drawing is not in the key.
        if (new.get("mode") == "shipped" and new.get("b_layer")
                and _geometry(b_now.get("structure_svg")) != _geometry(b_was.get("structure_svg"))):
            t.add("carried" if _bytes(new) == _bytes(prev) else "made")
            g.stop(name, f"its mark sits on {new.get('b')}'s shipped drawing, which moved while the "
                         f"pair's key did not (bump drawings.PAIRS_RECIPE to make the pair again)")
            return
        moved = [f"{new.get(side)}'s SMILES" for side, m_now, m_was in (("a", a_now, a_was), ("b", b_now, b_was))
                 if m_now.get("isomeric_smiles") != m_was.get("isomeric_smiles")]
        if _geometry(a_now.get("structure_svg")) != _geometry(a_was.get("structure_svg")):
            moved.append(f"{new.get('a')}'s drawing")
        if moved and _bytes(new) == _bytes(prev):
            t.add("carried")
            g.stop(name, f"kept under an unchanged key although {' and '.join(moved)} moved (the key "
                         f"covers them)")
            return
        if _bytes(new) == _bytes(prev):
            t.add("carried")
        elif _repainted(prev, new, "b_svg"):
            t.add("repainted")
            g.made(name, "repainted", f"the palette moved from {prev.get('palette')} to {new.get('palette')}")
        else:
            t.add("made")
            g.stop(name, "changed under an unchanged key (" + ", ".join(_differs(prev, new)) + ")")
        return
    t.add("made")
    reasons = []
    if new.get("recipe") != prev.get("recipe"):
        reasons.append(f"the pairs recipe moved from {prev.get('recipe')} to {new.get('recipe')}")
    for side, mol_now, mol_was in (("a", a_now, a_was), ("b", b_now, b_was)):
        if mol_now.get("isomeric_smiles") != mol_was.get("isomeric_smiles"):
            reasons.append(f"{new.get(side)}'s SMILES changed")
    if _geometry(a_now.get("structure_svg")) != _geometry(a_was.get("structure_svg")):
        reasons.append(f"{new.get('a')}'s drawing changed")
    if reasons:
        g.made(name, "remade", ", ".join(reasons))
    elif _only_words(prev, new, _PAIR_WORDS):
        g.made(name, "remade", "only its caption in compare_drawings.yaml changed; both drawings are "
                               "as shipped")
    else:
        g.unexplained(name, "remade", _what_differs(prev, new), "its entry in compare_drawings.yaml")


def _modes(pairs: dict[str, dict]) -> str:
    modes: dict[str, int] = {}
    for p in pairs.values():
        m = p["mode"] + ("+highlight" if p.get("highlight") else "")
        modes[m] = modes.get(m, 0) + 1
    return ", ".join(f"{k} {v}" for k, v in sorted(modes.items()))


# ── The check ─────────────────────────────────────────────────────────────────────────────────
def check(molecules: list[dict], compare: dict | None, snapshots: Path,
          allow_seeds: bool | None = None) -> Verdict:
    """Compare every drawing output of this run with the shipped snapshot in ``snapshots``.
    Read-only: returns the verdict; ``enforce`` raises on it."""
    allow = os.getenv(SEEDS_CHANGED_ENV) == "1" if allow_seeds is None else allow_seeds
    was_by_cid, was_compare = shipped(snapshots)
    g = _Guard(allow)
    svg, parts, units, pairs_t = _Tally(), _Tally(), _Tally(), _Tally()
    seen = {int(rec["cid"]) for rec in molecules if rec.get("cid") is not None}
    for rec in molecules:
        old = was_by_cid.get(int(rec["cid"])) if rec.get("cid") is not None else None
        _structure_svg(g, svg, rec, old)
        _structure_parts(g, parts, rec, old)
        _repeat_unit(g, units, rec, old)
    # A molecule that left the catalog takes its drawings with it: listed, never a stop.
    for cid, old in sorted(was_by_cid.items()):
        if cid in seen:
            continue
        if old.get("structure_svg"):
            svg.add("removed")
        for field_, kind in (("structure_svg", "structure drawing"), ("structure_parts", "structure parts"),
                             ("structure_repeat_unit", "repeat unit")):
            if old.get(field_):
                g.made(f"{old.get('slug')} ({kind})", "removed", "the molecule left the catalog")

    now_pairs = (compare or {}).get("pairs") or {}
    was_pairs = (was_compare or {}).get("pairs") or {}
    now_by_slug = {m["slug"]: m for m in molecules}
    was_by_slug = {r["slug"]: r for r in was_by_cid.values() if r.get("slug")}
    for slug in sorted(now_pairs):
        _pair(g, pairs_t, slug, now_pairs[slug], was_pairs.get(slug), now_by_slug, was_by_slug)
    for slug in sorted(set(was_pairs) - set(now_pairs)):
        g.made(f"{slug} (compare drawing)", "removed", "the pair left comparisons.yaml")
    if compare and was_compare:
        for k in ("recipe", "thresholds"):
            if _bytes(compare.get(k)) != _bytes(was_compare.get(k)):
                g.made(f"compare_drawings.json {k}", "changed",
                       f"{_bytes(was_compare.get(k))} -> {_bytes(compare.get(k))}")

    g.v.lines = [
        f"structure drawings: {svg['carried']} carried, {svg['repainted']} repainted, {svg['drawn']} drawn, "
        f"{svg['none']} with no drawing" + (f", {svg['removed']} removed with their molecule"
                                            if svg["removed"] else ""),
        (f"structure parts: {parts['carried']} carried, {parts['made']} made, {parts['none']} with no part, "
         f"{parts['unreadable']} drawings unreadable"),
        (f"compare drawings: {len(now_pairs)} pairs ({_modes(now_pairs)}); {pairs_t['carried']} carried, "
         f"{pairs_t['repainted']} repainted, {pairs_t['made']} made"),
        (f"repeat units: {units['units']} ({units['carried']} carried, {units['repainted']} repainted, "
         f"{units['drawn']} drawn this run)"),
    ]
    return g.v


def enforce(verdict: Verdict) -> None:
    """The refusal: raise with every stop named, before anything is loaded or written."""
    if not verdict.stopped:
        return
    raise DrawingChanged(
        f"refusing to export: {len(verdict.stops)} drawing(s) changed with nothing to explain it.\n"
        + "\n".join(f"  {s}" for s in verdict.stops) + "\n"
        "Nothing was loaded or written; the shipped snapshot stands. A drawing output may change only "
        "when its key does, and a key only when an input the data shows moved (a new molecule or "
        "pair, a recipe version, a SMILES, the drawing it rests on, a seed's words). Do not re-run "
        "the job: compare this machine's output for the entries above with the shipped snapshot "
        "(docs/DRAWING-RECIPES.md, section 10).")
