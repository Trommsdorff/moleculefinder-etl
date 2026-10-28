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
import logging
import re

import yaml

from ..config import SEEDS_DIR
from ..sources import registry
from .confidence import FROM_SOURCE, COMPUTED, INFERRED, label_for

log = logging.getLogger("mfetl")

WORLDS_YAML = SEEDS_DIR / "worlds.yaml"
RELATIONSHIPS_CSV = SEEDS_DIR / "relationships.csv"
WHY_IT_MATTERS_YAML = SEEDS_DIR / "why_it_matters.yaml"
BRANDS_YAML = SEEDS_DIR / "brands.yaml"
APPROVALS_YAML = SEEDS_DIR / "approvals.yaml"
LICENCES_YAML = SEEDS_DIR / "licences.yaml"
ODOR_THRESHOLDS_YAML = SEEDS_DIR / "odor_thresholds.yaml"
SWEETNESS_YAML = SEEDS_DIR / "sweetness.yaml"
OTC_ALLOWLIST_YAML = SEEDS_DIR / "otc_allowlist.yaml"
FOOD_HUBS_YAML = SEEDS_DIR / "food_hubs.yaml"
COMPARISONS_YAML = SEEDS_DIR / "comparisons.yaml"
PRODUCT_HUBS_YAML = SEEDS_DIR / "product_hubs.yaml"

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


def load_why_it_matters() -> dict[str, str]:
    """Read why_it_matters.yaml -> {slug: one-line curated 'why it matters' sentence}."""
    if not WHY_IT_MATTERS_YAML.exists():
        return {}
    data = yaml.safe_load(WHY_IT_MATTERS_YAML.read_text()) or {}
    return {str(k): str(v).strip() for k, v in data.items() if v and str(v).strip()}


# ── Comparisons (/vs/<pair>, build plan phase 5) ──────────────────────────────
def load_comparisons() -> dict[str, dict[str, str]]:
    """Read comparisons.yaml -> {"slug-a/slug-b": {"answer": ..., "text": ...}}.

    The prose only. Which pairs get a page is the web's curated list
    (``lib/compare-pairs.ts``); the two are held together by the web build, which
    fails when a listed pair has no text here or a text here is not listed there.
    ``answer`` is the pair's one-sentence difference (SEO run 1, 2026-10-28): the page's
    meta description, its first line of prose and the FAQ's answer to "What is the
    difference". A pair written as a bare string has no answer, which fails the compile.
    ``names`` (SEO run 2, optional) maps a molecule slug to the name the title carries in a
    parenthetical for it ("Benadryl"), held to ``_names_errors``.
    """
    if not COMPARISONS_YAML.exists():
        return {}
    data = yaml.safe_load(COMPARISONS_YAML.read_text()) or {}
    out: dict[str, dict] = {}
    for k, v in data.items():
        if not v:
            continue
        entry = v if isinstance(v, dict) else {"text": v}
        out[str(k).strip()] = {f: " ".join(str(entry.get(f) or "").split()) for f in ("answer", "text")}
        names = entry.get("names") if isinstance(entry, dict) else None
        if names:
            out[str(k).strip()]["names"] = {str(s): " ".join(str(n).split()) for s, n in dict(names).items()}
    return out


def build_comparisons(molecules: list[dict]) -> dict[str, dict]:
    """Compile comparisons.yaml into the snapshot, keyed by the URL slug ``a-vs-b``.

    Validates the way every other curated file here is validated, and for the same
    reason: a typo must fail the build, not ship a page comparing a molecule with
    nothing. Both slugs must exist, a pair may not be written twice in either
    direction, and the text must obey the house rules it is written under (no
    em-dash, no dosing, no "which should I take"). Every pair carries its answer line,
    held to its own rules (``_answer_errors``).
    """
    curated = load_comparisons()
    if not curated:
        return {}
    by_slug = {m["slug"]: m for m in molecules}
    errors: list[str] = []
    seen: dict[frozenset[str], str] = {}
    out: dict[str, dict] = {}
    for key, entry in sorted(curated.items()):
        text, answer = entry.get("text") or "", entry.get("answer") or ""
        parts = key.split("/")
        if len(parts) != 2 or not all(parts):
            errors.append(f"{key}: not a 'slug-a/slug-b' pair")
            continue
        a, b = parts
        missing = [s for s in (a, b) if s not in by_slug]
        if missing:
            errors.append(f"{key}: unknown slug(s) {', '.join(missing)}")
            continue
        if a == b:
            errors.append(f"{key}: a molecule cannot be compared with itself")
            continue
        unordered = frozenset((a, b))
        if unordered in seen:
            errors.append(f"{key}: same pair as {seen[unordered]}, one page per pair")
            continue
        seen[unordered] = key
        errors.extend(f"{key}: {e}" for e in _comparison_prose_errors(text))
        errors.extend(f"{key}: {e}" for e in _answer_errors(answer, by_slug[a], by_slug[b]))
        names = entry.get("names") or {}
        errors.extend(f"{key}: {e}" for e in _names_errors(names, answer, by_slug[a], by_slug[b]))
        out[f"{a}-vs-{b}"] = {
            "pair": key, "a": a, "b": b, "answer": answer, "text": text,
            "confidence": FROM_SOURCE, "source": "MoleculeFinder curated",
        }
        if names:
            out[f"{a}-vs-{b}"]["names"] = names
    if errors:
        raise SystemExit("comparisons compile failed:\n  " + "\n  ".join(errors))
    log.info("  comparisons: %d pair(s) compiled", len(out))
    return out


# Phrases that turn a description into advice. The comparison pages exist to line two
# records up beside each other, not to help anyone choose between two medicines, so the
# rule is enforced rather than remembered.
_ADVICE_PATTERNS = (
    # Narrow on purpose. An earlier, looser "which (to|should)" flagged ordinary prose like
    # "which should be enough", and a rule that cries wolf gets switched off.
    r"\byou should\b", r"\bshould (?:you|i) (?:take|use|choose|pick)\b",
    r"\bwhich (?:one )?(?:to (?:take|use|choose|pick|buy|go for)|should (?:i|you|a person))\b",
    r"\bconsult\b", r"\bask your doctor\b", r"\bwe recommend\b", r"\brecommended dose\b",
    # "500 mg" is a dose; "636 mg/kg" is the LD50 off the record, which these pages exist
    # to show. The negative lookahead keeps the second and still catches the first.
    r"\btake \d", r"\b\d+(?:\.\d+)?\s*mg\b(?!\s*/)", r"\bper day\b", r"\bdaily dose\b",
    r"\btwice a day\b",
    r"\bbetter (?:choice|option) (?:for|if)\b", r"\bsafer to take\b",
)


def _comparison_prose_errors(text: str) -> list[str]:
    errors = []
    if "\u2014" in text or "\u2013" in text:
        errors.append("em-dash or en-dash in visible copy (house rule)")
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    if not 4 <= len(sentences) <= 6:
        errors.append(f"{len(sentences)} sentences, the rule is 4 to 6")
    if len(text) < 320:
        errors.append(f"{len(text)} characters, too thin to be worth a page")
    for pat in _ADVICE_PATTERNS:
        if re.search(pat, text, re.I):
            errors.append(f"reads as advice or dosing: /{pat}/")
    return errors


# The answer line (SEO run 1, 2026-10-28). A searcher typing "lactose vs galactose" asked what the
# difference is; the line says it in one sentence that fits a search snippet. The web's own test
# holds every line to the same words (lib/products.test.ts ADVICE), so the two cannot disagree.
ANSWER_MAX = 160          # under 160 characters
_ANSWER_ADVICE = re.compile(
    r"\b(safe|safer|unsafe|should|recommend|take \d|dose|dosing|consult|per day)\b", re.IGNORECASE)


def _name_key(s: str) -> str:
    """A title as it reads inside a sentence: "β-Carotene" is written "beta-carotene"."""
    return s.lower().replace("\u03b2-", "beta-").replace("\u03b1-", "alpha-")


def _answer_errors(answer: str, a: dict, b: dict) -> list[str]:
    if not answer:
        return ["no answer line: one sentence under 160 characters that states the difference"]
    errors = []
    if len(answer) >= ANSWER_MAX:
        errors.append(f"answer line is {len(answer)} characters, the rule is under {ANSWER_MAX}")
    if "\u2014" in answer or "\u2013" in answer:
        errors.append("em-dash or en-dash in the answer line (house rule)")
    if len(re.split(r"(?<=[.!?])\s+", answer.strip())) != 1 or not answer.endswith("."):
        errors.append("the answer line is one sentence ending in a full stop")
    for m in (a, b):
        title = m.get("title") or m["slug"].replace("-", " ")
        if _name_key(title) not in _name_key(answer):
            errors.append(f"the answer line does not name {title}")
    if _ANSWER_ADVICE.search(answer) or any(re.search(p, answer, re.IGNORECASE) for p in _ADVICE_PATTERNS):
        errors.append("the answer line reads as advice or dosing")
    return errors


# The searcher's words in the title (SEO run 2, 2026-10-28). A /vs title may carry a parenthetical
# for a molecule ("Diphenhydramine (Benadryl)") under the molecule page's own rule for its
# parenthetical: a name the record carries, which the page's own text (here, the answer line) uses.
def _record_names(m: dict) -> set[str]:
    """Every name a record answers to, as it reads in a sentence: the title, the slug's words, the
    ETL's title synonym, the curated brands, the Wikidata names and the synonym lines."""
    names = [m.get("title") or "", m.get("slug", "").replace("-", " "), m.get("title_synonym") or "",
             *(m.get("brands") or []), *(m.get("wikidata_names") or []),
             *(m.get("display_synonyms") or []), *(m.get("synonyms") or [])]
    return {_name_key(n) for n in names if n}


def _names_errors(names: dict, answer: str, a: dict, b: dict) -> list[str]:
    errors = []
    for slug, name in (names or {}).items():
        m = a if slug == a.get("slug") else b if slug == b.get("slug") else None
        if m is None:
            errors.append(f"names: {slug} is not one of the pair")
            continue
        if not isinstance(name, str) or not name.strip():
            errors.append(f"names: no name for {slug}")
            continue
        if "—" in name or "–" in name:
            errors.append(f"names: em-dash or en-dash in {name!r} (house rule)")
        if _name_key(name) == _name_key(m.get("title") or ""):
            errors.append(f"names: {name!r} is {slug}'s title itself")
        elif _name_key(name) not in _record_names(m):
            errors.append(f"names: {name!r} is not a brand, Wikidata name, synonym, title synonym or the slug of {slug}")
        if _name_key(name) not in _name_key(answer):
            errors.append(f"names: the answer line does not use {name!r} (the page's own words must)")
    return errors


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


# ── compile: curated "why it matters" ──────────────────────────────────────────
def attach_why_it_matters(molecules: list[dict]) -> None:
    """Attach ``rec['why_it_matters']`` = {text, confidence, source} for each molecule that has a
    curated line in why_it_matters.yaml (follow-up #1). Plain, experiential, non-advice wording;
    always ``from_source`` / MoleculeFinder curated. The web shows this in the world SELECTED panel
    instead of the generic PubChem description, falling back to that description when absent.

    Validates every curated slug against the snapshot and fails the build loudly on a typo, the
    same discipline as ``attach_trails``. Mutates in place; call once after the records are built."""
    curated = load_why_it_matters()
    if not curated:
        return
    by_slug = {m["slug"]: m for m in molecules}
    unknown = sorted(s for s in curated if s not in by_slug)
    if unknown:
        raise SystemExit("why_it_matters compile failed, unknown slug(s):\n  " + "\n  ".join(unknown))
    for slug, text in curated.items():
        by_slug[slug]["why_it_matters"] = {
            "text": text, "confidence": FROM_SOURCE, "source": "MoleculeFinder curated",
        }


def load_brands() -> dict[str, list[str]]:
    """Read brands.yaml -> {slug: [commercial/brand names]}."""
    if not BRANDS_YAML.exists():
        return {}
    data = yaml.safe_load(BRANDS_YAML.read_text()) or {}
    return {str(k): [str(b).strip() for b in (v or []) if str(b).strip()] for k, v in data.items()}


_APPROVAL_FIELDS = ("regulator", "product", "application", "authorised", "basis", "source", "label")
# A licence record read from a register (licences.yaml, written by `mfetl licences`) also names the
# register, the holder, whether the molecule is part of a combination product, and the date read.
_LICENCE_FIELDS = ("regulator", "register", "product", "application", "authorised", "holder",
                   "combination", "basis", "source", "read")
_LICENCE_REQUIRED = ("regulator", "register", "basis", "source", "read")
# A licence record's source is the regulator's own site, never news or Wikipedia (run B2).
REGULATOR_HOSTS = ("fda.gov", "ema.europa.eu", "mhra.gov.uk", "aifa.gov.it")


def is_regulator_url(url: str) -> bool:
    from urllib.parse import urlparse
    u = urlparse(str(url or ""))
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in REGULATOR_HOSTS)


def load_approvals() -> dict:
    """approvals.yaml as written: {slug: entry}."""
    if not APPROVALS_YAML.exists():
        return {}
    return yaml.safe_load(APPROVALS_YAML.read_text()) or {}


def attach_approvals(molecules: list[dict]) -> None:
    """Attach ``rec['approval']`` for medicines admitted under a ruling (approvals.yaml): which
    regulator licenses it, and, where the authorisation was confirmed from the regulator's own
    record, the source. Fails the build on an unknown slug, an unknown field or an entry with no
    regulator or basis, like every other curated seed."""
    if not APPROVALS_YAML.exists():
        return
    data = yaml.safe_load(APPROVALS_YAML.read_text()) or {}
    by_slug = {m["slug"]: m for m in molecules}
    errors = []
    for slug, entry in data.items():
        entry = entry or {}
        if slug not in by_slug:
            errors.append(f"{slug}: unknown slug")
            continue
        extra = sorted(set(entry) - set(_APPROVAL_FIELDS))
        if extra:
            errors.append(f"{slug}: unknown field(s) {extra}")
        if not entry.get("regulator") or not entry.get("basis"):
            errors.append(f"{slug}: needs a regulator and a basis")
        by_slug[slug]["approval"] = {k: str(entry[k]) for k in _APPROVAL_FIELDS if entry.get(k)}
    if errors:
        raise SystemExit("approvals compile failed:\n  " + "\n  ".join(errors))


def attach_licences(molecules: list[dict]) -> None:
    """Attach ``rec['approval']`` from licences.yaml (run B2): a medicine's licence record read
    from Drugs@FDA, the EMA's medicines data or the MHRA products database. Runs after
    attach_approvals and never replaces a hand-ruled record. Reads only the committed file, so a
    build makes no request. Fails the build on an unknown slug, a record that is not a medicine, an
    unknown or missing field, or a source that is not the regulator's own site."""
    if not LICENCES_YAML.exists():
        return
    data = yaml.safe_load(LICENCES_YAML.read_text()) or {}
    by_slug = {m["slug"]: m for m in molecules}
    errors = []
    for slug, entry in data.items():
        entry = entry or {}
        rec = by_slug.get(slug)
        if rec is None:
            errors.append(f"{slug}: unknown slug")
            continue
        if rec.get("scope_bucket") not in ("prescription-medicine", "otc-medicine"):
            errors.append(f"{slug}: not a medicine ({rec.get('scope_bucket')})")
        extra = sorted(set(entry) - set(_LICENCE_FIELDS))
        missing = [k for k in _LICENCE_REQUIRED if not entry.get(k)]
        if extra:
            errors.append(f"{slug}: unknown field(s) {extra}")
        if missing:
            errors.append(f"{slug}: missing {missing}")
        if not is_regulator_url(entry.get("source")):
            errors.append(f"{slug}: source is not a regulator's site: {entry.get('source')}")
        if rec.get("approval"):
            continue                                    # the hand ruling stands
        rec["approval"] = {k: (True if k == "combination" else str(entry[k]))
                           for k in _LICENCE_FIELDS if entry.get(k)}
    if errors:
        raise SystemExit("licences compile failed:\n  " + "\n  ".join(errors))


def attach_brands(molecules: list[dict]) -> None:
    """Attach ``rec['brands']`` = [commercial names] for curated OTC drugs (follow-up: "also known
    as Advil / Benadryl"). The web shows them on an "Also sold as" line; the search index folds
    them in so a search for a brand finds the molecule. Validates every slug against the snapshot
    and fails the build loudly on a typo. Mutates in place; call once after the records are built."""
    brands = load_brands()
    if not brands:
        return
    by_slug = {m["slug"]: m for m in molecules}
    unknown = sorted(s for s in brands if s not in by_slug)
    if unknown:
        raise SystemExit("brands compile failed, unknown slug(s):\n  " + "\n  ".join(unknown))
    for slug, names in brands.items():
        if names:
            by_slug[slug]["brands"] = names


def load_odor_thresholds() -> dict[str, float]:
    """Read odor_thresholds.yaml -> {slug: odor detection threshold in ng/m3 air}."""
    if not ODOR_THRESHOLDS_YAML.exists():
        return {}
    data = yaml.safe_load(ODOR_THRESHOLDS_YAML.read_text()) or {}
    return {str(k): float(v) for k, v in data.items() if v is not None}


def attach_odor_thresholds(molecules: list[dict]) -> None:
    """Attach ``rec['odor_threshold']`` (ng/m3 air) for the malodorous compounds that power the
    "Most pungent" (stinkiest) leaderboard. Lower = smellable at a tinier amount = more potent.
    Validates every slug against the snapshot and fails the build loudly on a typo. Mutates in
    place; call once after the records are built."""
    odt = load_odor_thresholds()
    if not odt:
        return
    by_slug = {m["slug"]: m for m in molecules}
    unknown = sorted(s for s in odt if s not in by_slug)
    if unknown:
        raise SystemExit("odor_thresholds compile failed, unknown slug(s):\n  " + "\n  ".join(unknown))
    for slug, value in odt.items():
        by_slug[slug]["odor_threshold"] = value


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
            "why_it_matters": by_slug[s].get("why_it_matters"),
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


# ── kind:"use" hubs from the OTC allowlist (build plan 2026-09-05, phase 2.2) ──
# The allowlist's groups were documented as "for readability only". They are the one
# piece of curation on the site that answers the question a person actually asks at a
# pharmacy shelf: what do I take this FOR. Each group below becomes a /in/<slug> hub,
# using the "use" kind whose label KIND_LABEL on the web already reserved.
#
# Groups deliberately not mapped: `vitamins_supplements_otc` holds two unrelated
# molecules (a joint supplement and a motion-sickness antihistamine) and would make a
# hub that means nothing.
USE_GROUPS: dict[str, tuple[str, str]] = {
    "analgesics_nsaids":       ("pain-and-fever", "Pain and fever"),
    "sleep_and_neuro":         ("sleep-and-calm", "Sleep and calm"),
    "antihistamines":          ("allergy", "Allergy"),
    "antacids_and_gi":         ("heartburn-and-digestion", "Heartburn and digestion"),
    "cough_cold_decongestant": ("cough-and-cold", "Cough and cold"),
    "topical_and_skin":        ("skin-and-topical", "Skin and topical"),
    "antiseptics":             ("antiseptic", "Antiseptic"),
}


# ── Sweetness (SEO run 1, 2026-10-28) ─────────────────────────────────────────
# Every relative sweetness the site shows comes from sources/seeds/sweetness.yaml, each value with
# a named source that may be displayed (the source-licence rule) and the source's own words. The
# curated overlays carried eight bare "commonly cited" figures until this run; none may carry one
# now (tests/test_sweetness.py), so a value has one home and one citation.
_SWEETNESS_FIELDS = ("value", "source", "cite", "says")
# Where the sweetness hook sits among a record's hooks: where assemble used to put it, before these.
_HOOKS_AFTER_SWEETNESS = ("smell_card", "structure", "similar")


def load_sweetness() -> dict[str, dict]:
    """Read sweetness.yaml -> {slug: {value, source, cite, says}}."""
    if not SWEETNESS_YAML.exists():
        return {}
    data = yaml.safe_load(SWEETNESS_YAML.read_text()) or {}
    return {str(k): dict(v or {}) for k, v in data.items()}


def _set_sweetness(rec: dict, value: float, source: str) -> None:
    rec["relative_sweetness"] = value
    rec["relative_sweetness_source"] = source
    prop = {"key": "relative_sweetness", "value_num": value, "value_text": None, "unit": "x sugar",
            "confidence": label_for("relative_sweetness"), "source": source}
    props = rec.setdefault("properties", [])
    at = next((i for i, p in enumerate(props) if p.get("key") == "relative_sweetness"), None)
    if at is None:
        props.append(prop)
    else:
        props[at] = prop
    hooks = rec.setdefault("hooks", [])
    hook = {"type": "sweetness", "enabled": True, "confidence": FROM_SOURCE, "params": {"x_sugar": value}}
    hooks[:] = [h for h in hooks if h.get("type") != "sweetness"]
    at = next((i for i, h in enumerate(hooks) if h.get("type") in _HOOKS_AFTER_SWEETNESS), len(hooks))
    hooks.insert(at, hook)
    if isinstance(rec.get("curated"), dict):           # the Supabase row's curated block
        rec["curated"]["relative_sweetness"] = value


def attach_sweetness(molecules: list[dict]) -> None:
    """Attach ``relative_sweetness`` (sucrose = 1) and ``relative_sweetness_source`` (a registry key)
    from sweetness.yaml, with the property row and the sweetness hook the molecule page reads. Fails
    the build on an unknown slug, a missing or unknown field, a value that is not a positive number,
    a source that may not be displayed, or sucrose at anything but 1."""
    data = load_sweetness()
    by_slug = {m["slug"]: m for m in molecules}
    errors = []
    for slug, entry in sorted(data.items()):
        rec = by_slug.get(slug)
        if rec is None:
            errors.append(f"{slug}: unknown slug")
            continue
        extra = sorted(set(entry) - set(_SWEETNESS_FIELDS))
        missing = [k for k in _SWEETNESS_FIELDS if entry.get(k) in (None, "")]
        if extra or missing:
            errors.append(f"{slug}: unknown field(s) {extra}, missing {missing}")
            continue
        value = entry["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            errors.append(f"{slug}: value {value!r} is not a positive number")
            continue
        if slug == "sucrose" and value != 1:
            errors.append("sucrose: the reference point of the scale is 1 by definition")
            continue
        if not registry.may_display(entry["source"]):
            errors.append(f"{slug}: source {entry['source']!r} is not a registered source that may be displayed")
            continue
        _set_sweetness(rec, value, entry["source"])
    if errors:
        raise SystemExit("sweetness compile failed:\n  " + "\n  ".join(errors))
    log.info("  sweetness: %d molecule(s), each with a named source", len(data))


def _name_key(name: str) -> str:
    """Normalize an allowlist name or a molecule name to a comparable key."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")


def load_otc_uses() -> dict[str, list[tuple[str, str]]]:
    """Read otc_allowlist.yaml -> {name key: [(hub slug, hub label), ...]}.

    A molecule can appear in more than one group (salicylic acid is both a topical and,
    as aspirin's parent, an analgesic), so the value is a list."""
    if not OTC_ALLOWLIST_YAML.exists():
        return {}
    data = yaml.safe_load(OTC_ALLOWLIST_YAML.read_text()) or {}
    out: dict[str, list[tuple[str, str]]] = {}
    for group, names in data.items():
        hub = USE_GROUPS.get(group)
        if not hub:
            continue
        for name in names or []:
            out.setdefault(_name_key(str(name)), []).append(hub)
    return out


def attach_otc_uses(molecules: list[dict]) -> None:
    """Add a kind:"use" category for every allowlisted OTC molecule, from its group.

    Matched on the molecule's slug, title and synonyms, because the allowlist is written
    in ordinary pharmacy names ("Paracetamol", "Chlorphenamine") and the canon's title may
    be the other one. Unlike the other curated overlays this does NOT fail on an unmatched
    entry: the allowlist is a scope document that deliberately names molecules not yet in
    the canon, so a miss is expected. It is logged instead."""
    uses = load_otc_uses()
    if not uses:
        return
    matched: set[str] = set()
    for m in molecules:
        keys = {_name_key(m["slug"]), _name_key(m.get("title") or "")}
        keys |= {_name_key(s) for s in (m.get("synonyms") or [])}
        hubs: dict[str, str] = {}
        for k in keys:
            for slug, label in uses.get(k, []):
                hubs[slug] = label
                matched.add(k)
        for slug, label in hubs.items():
            if not any(c.get("slug") == slug and c.get("kind") == "use" for c in m["categories"]):
                m["categories"].append({"slug": slug, "name": label, "kind": "use",
                                        "confidence": FROM_SOURCE, "source": "curated"})
        if hubs:
            m["is_otc"] = True
    unmatched = sorted(k for k in uses if k not in matched)
    log.info("  otc uses: %d allowlist names matched, %d not in the canon (%s)",
             len(matched), len(unmatched), ", ".join(unmatched[:6]) or "none")


# ── Food hubs (build plan 2026-09-05, phase 2.3) ──────────────────────────────
def _load_hub_yaml(path) -> dict[str, dict]:
    """Read a hub file -> {hub slug: {"name": ..., "molecules": [...]}}."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    out: dict[str, dict] = {}
    for slug, entry in data.items():
        mols = [str(m).strip() for m in ((entry or {}).get("molecules") or []) if str(m).strip()]
        if mols:
            out[str(slug)] = {"name": (entry or {}).get("name") or str(slug).replace("-", " ").title(),
                              "molecules": mols}
    return out


def load_food_hubs() -> dict[str, dict]:
    """Read food_hubs.yaml -> {hub slug: {"name": ..., "molecules": [...]}}."""
    return _load_hub_yaml(FOOD_HUBS_YAML)


def load_product_hubs() -> dict[str, dict]:
    """Read product_hubs.yaml, same shape as the food hubs and emitted as kind:"product".

    Phase 6 needed a home for the honest answer to "where you will find it" when the
    answer is not a food. Household bleach, a first aid kit and a can of compressed air
    are where a reader actually meets sodium hypochlorite, hydrogen peroxide and
    difluoroethane, and filing those as foods would have been a lie for the sake of
    reusing a mechanism.
    """
    return _load_hub_yaml(PRODUCT_HUBS_YAML)


def _attach_hubs(molecules: list[dict], hubs: dict[str, dict], kind: str, label: str) -> None:
    """Add a category of ``kind`` per curated membership.

    Additive and idempotent: a membership a curated/*.yaml overlay already set is left
    exactly as it is, note and all. Validates every slug against the snapshot and fails the
    build loudly on a typo, the same discipline as attach_trails."""
    if not hubs:
        return
    by_slug = {m["slug"]: m for m in molecules}
    unknown = sorted({s for h in hubs.values() for s in h["molecules"] if s not in by_slug})
    if unknown:
        raise SystemExit(f"{label} compile failed, unknown molecule slug(s):\n  " + "\n  ".join(unknown))
    added = 0
    for hub, entry in hubs.items():
        for slug in entry["molecules"]:
            rec = by_slug[slug]
            if any(c.get("slug") == hub and c.get("kind") == kind for c in rec["categories"]):
                continue
            rec["categories"].append({"slug": hub, "name": entry["name"], "kind": kind,
                                      "note": None, "confidence": FROM_SOURCE, "source": "curated"})
            added += 1
    log.info("  %s: %d hubs, %d memberships added", label, len(hubs), added)


def attach_food_hubs(molecules: list[dict]) -> None:
    """Add a kind:"food" category per curated membership, filling out the thin hubs.

    14 of the 17 food hubs had two molecules or fewer; /in/coffee was a one-molecule page."""
    _attach_hubs(molecules, load_food_hubs(), "food", "food hubs")


def attach_product_hubs(molecules: list[dict]) -> None:
    """Add a kind:"product" category per curated membership (phase 6).

    The molecule page's "Where you will find it" box promises everyday foods OR products
    and could only ever deliver the first half, so 705 of 788 pages carried an empty state
    that read as a missing mapping even where no food could ever exist."""
    _attach_hubs(molecules, load_product_hubs(), "product", "product hubs")

