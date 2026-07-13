"""Everyday Worlds + Molecule Trails — compile the one curated relationship dataset.

Two hand-curated inputs (build spec §2) drive both the world explorer (`/roam`) and the
"Keep roaming" Trails module on every molecule page:

  - ``sources/seeds/worlds.yaml``        — the 10 curated worlds (title, blurb, tint,
                                            member slugs, guided journey).
  - ``sources/seeds/relationships.csv``  — the typed molecule->molecule edges
                                            (``affects`` / ``becomes``).

Four relation types, exactly (spec §2a). Where each comes from:
  - ``found_in``  molecule -> world.  Derived from ``worlds.yaml`` membership (a molecule
                  is "found in" a world iff it is a member), so the membership list is the
                  single source of truth and can never drift from a duplicate edge list.
                  Explicit ``found_in`` rows in the CSV are also honored (forward-compat).
  - ``affects``   molecule -> molecule.  Curated, ``inferred``, neutral non-advice wording.
  - ``becomes``   molecule -> molecule.  Curated metabolite / derived product.
  - ``resembles`` molecule -> molecule.  Computed structural similarity: this is the ETL's
                  existing top-N Morgan/Tanimoto ``edges`` (assemble.attach_edges). We do
                  not recompute it here; the molecule page's "Related" lane reads those
                  ``edges`` directly, and the world map surfaces the within-world subset.

Every emitted edge carries a confidence label (from source / computed / inferred). Every
slug is validated against the built snapshot, so a typo fails the build loudly instead of
shipping a dangling reference (spec §9 acceptance criteria).
"""
from __future__ import annotations
import csv

import yaml

from ..config import SEEDS_DIR
from .confidence import FROM_SOURCE, COMPUTED, INFERRED

WORLDS_YAML = SEEDS_DIR / "worlds.yaml"
RELATIONSHIPS_CSV = SEEDS_DIR / "relationships.csv"

CURATED_RELATIONS = ("found_in", "affects", "becomes")   # the CSV / membership relations
VALID_CONFIDENCE = {FROM_SOURCE, COMPUTED, INFERRED}
# Default confidence per relation when a CSV row leaves the column blank (spec §2a).
DEFAULT_CONFIDENCE = {"found_in": FROM_SOURCE, "affects": INFERRED, "becomes": FROM_SOURCE}
FOUND_IN_NOTE = "everyday world"


# ── inputs ───────────────────────────────────────────────────────────────────
def load_worlds() -> list[dict]:
    if not WORLDS_YAML.exists():
        return []
    data = yaml.safe_load(WORLDS_YAML.read_text()) or {}
    return list(data.get("worlds") or [])


def load_relationships() -> list[dict]:
    """Read relationships.csv -> normalized edge dicts. Confidence defaults by relation."""
    if not RELATIONSHIPS_CSV.exists():
        return []
    out: list[dict] = []
    with RELATIONSHIPS_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rel = (row.get("relation") or "").strip()
            if not rel:
                continue
            conf = (row.get("confidence") or "").strip() or DEFAULT_CONFIDENCE.get(rel, FROM_SOURCE)
            out.append({
                "from_slug": (row.get("from_slug") or "").strip(),
                "relation": rel,
                "to": (row.get("to") or "").strip(),
                "note": (row.get("note") or "").strip(),
                "confidence": conf,
            })
    return out


# ── validation ───────────────────────────────────────────────────────────────
def _validate(worlds: list[dict], rels: list[dict], by_slug: dict[str, dict]) -> None:
    """Fail loudly on any world/edge that references a slug absent from the snapshot,
    an unknown relation, or an out-of-vocabulary confidence label (spec §9)."""
    problems: list[str] = []
    world_slugs = {w.get("slug") for w in worlds}

    for w in worlds:
        for s in w.get("molecules") or []:
            if s not in by_slug:
                problems.append(f"world '{w.get('slug')}' references unknown molecule '{s}'")
        for j in w.get("journey") or []:
            js = j.get("slug")
            if js not in by_slug:
                problems.append(f"world '{w.get('slug')}' journey references unknown molecule '{js}'")
            elif js not in (w.get("molecules") or []):
                problems.append(f"world '{w.get('slug')}' journey step '{js}' is not one of its molecules")

    for r in rels:
        if r["relation"] not in CURATED_RELATIONS:
            problems.append(f"relationship has unknown relation '{r['relation']}' ({r['from_slug']} -> {r['to']})")
            continue
        if r["confidence"] not in VALID_CONFIDENCE:
            problems.append(f"relationship {r['from_slug']} -> {r['to']} has invalid confidence '{r['confidence']}'")
        elif r["relation"] == "affects" and r["confidence"] != INFERRED:
            # spec §2a: an affects edge is a mechanism, always labeled inferred (never advice).
            problems.append(f"affects edge '{r['from_slug']}' -> '{r['to']}' must be confidence "
                            f"'{INFERRED}', got '{r['confidence']}'")
        if r["from_slug"] not in by_slug:
            problems.append(f"relationship from unknown molecule '{r['from_slug']}'")
        if r["relation"] == "found_in":
            if r["to"] not in world_slugs:
                problems.append(f"found_in edge '{r['from_slug']}' -> unknown world '{r['to']}'")
        elif r["to"] not in by_slug:
            problems.append(f"{r['relation']} edge '{r['from_slug']}' -> unknown molecule '{r['to']}'")

    if problems:
        raise SystemExit("relationship compile failed:\n  " + "\n  ".join(problems))


def _tint(bucket: "str | None", family: "str | None") -> "str | None":
    """The color key for a molecule target: Scope B bucket first, structural family fallback."""
    return bucket or family


# ── compile: per-molecule Trails ───────────────────────────────────────────────
def attach_trails(molecules: list[dict]) -> None:
    """Attach ``rec['trails']`` = {found_in, affects, becomes} to each molecule record.

    ``found_in`` is generated from world membership (plus any explicit CSV rows); ``affects``
    and ``becomes`` come from relationships.csv. The "Related" lane is NOT stored here: the
    web reads the record's existing computed similarity ``edges`` for that (spec §6). Mutates
    the records in place. Safe to call once, after edges + filter-4."""
    by_slug = {m["slug"]: m for m in molecules}
    worlds = load_worlds()
    rels = load_relationships()
    _validate(worlds, rels, by_slug)

    world_by_slug = {w["slug"]: w for w in worlds}
    for m in molecules:
        m["trails"] = {"found_in": [], "affects": [], "becomes": []}

    def _add_found_in(mol_slug: str, world: dict, note: str, confidence: str) -> None:
        lane = by_slug[mol_slug]["trails"]["found_in"]
        if any(c["to"] == world["slug"] for c in lane):        # de-dupe membership + explicit row
            return
        lane.append({
            "to": world["slug"], "kind": "world", "title": world["title"],
            "note": note or FOUND_IN_NOTE, "tint": world.get("tint"), "confidence": confidence,
        })

    # found_in from world membership (the single source of truth for "appears in").
    for w in worlds:
        for s in w.get("molecules") or []:
            _add_found_in(s, w, FOUND_IN_NOTE, FROM_SOURCE)

    # affects / becomes (molecule targets) + any explicit found_in rows from the CSV.
    for r in rels:
        if r["relation"] == "found_in":
            _add_found_in(r["from_slug"], world_by_slug[r["to"]], r["note"], r["confidence"])
            continue
        tgt = by_slug[r["to"]]
        by_slug[r["from_slug"]]["trails"][r["relation"]].append({
            "to": tgt["slug"], "kind": "molecule", "title": tgt["title"], "note": r["note"],
            "tint": _tint(tgt.get("scope_bucket"), tgt.get("family")),
            "bucket": tgt.get("scope_bucket"), "family": tgt.get("family"),
            "confidence": r["confidence"],
        })


# ── compile: worlds.json (screens 1 + 2) ───────────────────────────────────────
def build_worlds(molecules: list[dict]) -> dict:
    """Compile ``worlds.json``: a lightweight index for the /roam landing (screen 1) and a
    per-world detail map for /roam/<world> (screen 2). Each world's map edges are the
    curated affects/becomes among its members plus the computed ``resembles`` (similarity)
    subset that stays within the world. Every edge keeps its verb + confidence.

    Lenient by design: a world is emitted only if every member resolves in the given
    molecule set, so a partial or empty snapshot still exports a valid (possibly empty)
    worlds.json. Curation typos are caught earlier and loudly by ``attach_trails`` on the
    full build set, so this stage does not need to re-raise."""
    by_slug = {m["slug"]: m for m in molecules}
    rels = load_relationships()

    index: list[dict] = []
    detail: dict[str, dict] = {}
    for w in load_worlds():
        members = w.get("molecules") or []
        if not members or any(s not in by_slug for s in members):
            continue                                           # skip worlds not fully present
        member_set = set(members)
        nodes = [{
            "slug": s, "title": by_slug[s]["title"],
            "bucket": by_slug[s].get("scope_bucket"), "family": by_slug[s].get("family"),
            "formula": by_slug[s].get("molecular_formula"), "summary": by_slug[s].get("summary"),
        } for s in members]

        edges: list[dict] = []
        for r in rels:
            if r["relation"] in ("affects", "becomes") and r["from_slug"] in member_set and r["to"] in member_set:
                edges.append({"from": r["from_slug"], "to": r["to"], "relation": r["relation"],
                              "note": r["note"], "confidence": r["confidence"]})
        seen: set[tuple[str, str]] = set()                     # computed resembles within the world
        for s in members:
            for e in (by_slug[s].get("edges") or []):
                t = e.get("neighbor_slug")
                if t in member_set and t != s:
                    key = tuple(sorted((s, t)))
                    if key in seen:
                        continue
                    seen.add(key)
                    edges.append({"from": s, "to": t, "relation": "resembles",
                                  "note": f"{round(e['tanimoto'] * 100)}% similar",
                                  "tanimoto": e["tanimoto"], "confidence": COMPUTED})

        journey = [{"slug": j["slug"], "title": by_slug[j["slug"]]["title"], "caption": j.get("caption", "")}
                   for j in (w.get("journey") or [])]

        detail[w["slug"]] = {
            "slug": w["slug"], "title": w["title"], "blurb": w.get("blurb", ""),
            "tint": w.get("tint"), "molecules": nodes, "edges": edges, "journey": journey,
        }
        index.append({
            "slug": w["slug"], "title": w["title"], "blurb": w.get("blurb", ""),
            "tint": w.get("tint"), "count": len(nodes),
            "specks": [n["bucket"] or n["family"] for n in nodes],
        })

    return {"worlds": index, "detail": detail}
