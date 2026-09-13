"""Assemble the per-molecule record — the M1 contract that flows fetch → transform
→ load → export.

One rich, self-contained dict per molecule: identity + structure (from PubChem),
descriptors, parsed toxicity/GHS, functional-group + curated categories, curated
overlays merged, interactive hooks (`hooks.hooks_for`, plan §7.1), a build-time
2D SVG, and — attached in a second pass — top-N similarity edges. Every value is
labeled through `confidence.py`, and every source key is run through the license
firewall (`registry.assert_not_blocked`) as it is stamped on.
"""
from __future__ import annotations
import functools
import logging
import re

import yaml

from .confidence import label_for
from . import names, slugs, categories, hooks, structures, similarity, families, buckets, toxicity
from ..config import SEEDS_DIR
from ..sources.registry import assert_not_blocked

log = logging.getLogger("mfetl")

# PubChem renamed these properties (CanonicalSMILES→ConnectivitySMILES,
# IsomericSMILES→SMILES); read the new names, fall back to the old for safety.
_ISO_KEYS = ("SMILES", "IsomericSMILES")
_CAN_KEYS = ("ConnectivitySMILES", "CanonicalSMILES")


def _src(key: str) -> str:
    """Stamp a source key, tripping the license firewall on any BLOCKED source."""
    assert_not_blocked(key)
    return key


def _first(props: dict, keys) -> "str | None":
    for k in keys:
        if props.get(k):
            return props[k]
    return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _titleize(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip().title()


# Greek letters in chemical names. PubChem/Wikidata names arrive two broken ways: a
# mis-cased CAPITAL greek prefix (e.g. "Β-Hydroxybutyric" — that leading char is a greek
# capital beta, which reads as a latin "B"), and a spelled-out prefix ("alpha-Pinene").
# Positional/stereo prefixes are conventionally a LOWERCASE greek symbol, so normalize both.
# Capital Delta is left alone (the Δn double-bond convention, e.g. Δ9-THC). Word-bounded so
# ordinary words are safe (Betaine, Alanine, Gamma unaffected). Display title only; synonyms
# keep their spelled-out forms so "beta-..." stays searchable, and slugs are untouched.
_GREEK_WORD = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "omega": "ω"}
_GREEK_WORD_RE = re.compile(r"\b(" + "|".join(_GREEK_WORD) + r")-", re.I)


def _normalize_greek(name: "str | None") -> "str | None":
    if not name:
        return name
    out = _GREEK_WORD_RE.sub(lambda m: _GREEK_WORD[m.group(1).lower()] + "-", name)
    # Mis-cased capital greek (U+0391-03A9) -> lowercase (+0x20), except capital Delta.
    return "".join(chr(ord(c) + 0x20) if (0x391 <= ord(c) <= 0x3A9 and c != "Δ") else c
                   for c in out)


# Type slugs whose display name _titleize would mangle (acronyms).
_TYPE_NAMES = {"nsaid": "NSAID"}

# scope_family values that never become a /in/ hub. "other" is the Scope B CSV's
# explicit "no family fits" marker on 87 rows, not a family.
FAMILY_HUB_EXCLUDE = frozenset({"other"})


# Registry/cross-reference codes that make poor display or search synonyms.
_CODE_PREFIX = re.compile(
    r"^(SCHEMBL|DTXSID|DTXCID|CHEMBL|CHEBI|UNII|EINECS|NSC|AKOS|MFCD|ZINC|BDBM|"
    r"CID|SID|HMS|HY-|CAS-|EC-|RefChem|InChI|Q\d)", re.I)


def _is_code(s: str) -> bool:
    return (":" in s or bool(_CODE_PREFIX.match(s)) or bool(re.fullmatch(r"[\d\-]+", s))
            or (" " not in s and sum(c.isdigit() for c in s) >= 4))   # e.g. "SCHEMBL1055817"


def _clean_synonyms(syns, title: "str | None") -> list[str]:
    """Pick the display synonyms in PubChem's order, then STORE them in a stable one.

    Two different jobs, and conflating them is what made the snapshot churn. *Selection*
    has to follow PubChem's ordering, which is the only signal we have for which names a
    person would recognise (its head is remarkably stable: "acetaminophen, Paracetamol,
    4-Acetamidophenol..." for months). *Storage* must not, because further down that list
    PubChem freely swaps neighbours between rebuilds, and a pure re-sort of the shipped
    list removed 80 of the 156 synonym-only file changes in the 2026-09-06 weekly diff.

    So: take the first 12 non-code names the way we always did, then sort those twelve
    alphabetically with the title pinned first. An adjacent swap upstream now lands on
    the same stored list, and only a name genuinely entering or leaving the top twelve
    moves the file.
    """
    out: list[str] = []
    seen: dict[str, int] = {}          # dedup key -> slot in `out`
    for s in ([title] + list(syns or [])):
        s = (s or "").strip()
        if not s or _is_code(s):       # skip CAS/registry cross-reference codes
            continue
        low = s.lower()
        if low in seen:
            # "Advil" and "advil " are one name in two dresses. Which one PubChem happens
            # to list first is not stable, so pick the representative by the string itself.
            slot = seen[low]
            out[slot] = min(out[slot], s)
            continue
        seen[low] = len(out)
        out.append(s)
        if len(out) >= 12:
            break
    head = out[:1] if title and out and out[0].lower() == title.strip().lower() else []
    rest = out[len(head):]
    # casefold first so case alone cannot decide the order; the exact string breaks that tie.
    return head + sorted(rest, key=lambda s: (s.casefold(), s))


# ── Display synonyms (Garrett, 2026-09-12) ───────────────────────────────────────────────────
# `synonyms` above is the search list, stored alphabetically for determinism since run 3, and
# the page used to print its first four, so acetaminophen's line under the H1 led with
# "4'-Hydroxyacetanilide". This is a separate list for reading: Wikidata's English label and
# aliases in Wikidata's order, then those stored PubChem synonyms, kept only when a reader can
# use the name. Every input is deterministic (the label and aliases come in each item's own
# stored order, see sources/wikidata.py::names_for_qids), so the line is too.
DISPLAY_SYNONYMS_MAX = 4
DISPLAY_SYNONYM_MAX_LEN = 25
_NAME_PUNCTUATION = frozenset(" -'’")      # space, hyphen, straight and curly apostrophe
# A one-letter word followed by a space marks a garbled name (Garrett, 2026-09-12): a space dropped
# into a word ("C ochineal") or a hyphen lost ("N acetylcysteine", "L Thyroxin beta"). Words are
# split on spaces, so a letter joined by a hyphen or an apostrophe is not a word ("E-Z Prep",
# "baker's ammonia"), and a letter that ends the name has no space after it ("vitamin A"). The rule
# is literal: it also drops real names written that way ("neovitamin A acid", "K citrate").
_GARBLED_NAME = re.compile(r"(?:^| )[^\W\d_] ")


def _readable_name(s: str) -> bool:
    """Starts with a letter; only letters, spaces, hyphens and apostrophes; 25 characters or
    fewer; not all capitals beyond 5 characters ("APAP" stays, "CAFFEINE" does not); no
    one-letter word followed by a space ("C ochineal" is garbled)."""
    if not s or len(s) > DISPLAY_SYNONYM_MAX_LEN or not s[0].isalpha():
        return False
    if not all(c.isalpha() or c in _NAME_PUNCTUATION for c in s):
        return False
    if _GARBLED_NAME.search(s):
        return False
    return not (len(s) > 5 and s == s.upper())


# A name this many single-letter edits from the title, or fewer, is the title respelled.
NEAR_TITLE_EDITS = 2
_GREEK_SPELLED = {letter: word for word, letter in _GREEK_WORD.items()}    # "β" -> "beta"


def _title_forms(title: "str | None") -> list[str]:
    """The title as names are compared with it: casefolded, plus a copy with its Greek letters
    spelled out. The page prints "β-Alanine" (_normalize_greek) where the sources say
    "beta-alanine", and that is the title, not another name for it."""
    own = (title or "").strip().casefold()
    if not own:
        return []
    spelled = "".join(_GREEK_SPELLED.get(c, c) for c in own)
    return [own] if spelled == own else [own, spelled]


def _within_edits(a: str, b: str, limit: int) -> bool:
    """True when ``a`` and ``b`` are at most ``limit`` single-letter edits apart (Levenshtein)."""
    if abs(len(a) - len(b)) > limit:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return False
        prev = cur
    return prev[-1] <= limit


def _near_title(key: str, forms: list[str]) -> bool:
    """A casefolded name that contains the title, sits inside it, or is within two letters of it."""
    return any(t in key or key in t or _within_edits(key, t, NEAR_TITLE_EDITS) for t in forms)


def display_synonyms(title: "str | None", wikidata_names, pubchem_synonyms,
                     do_not_use=None) -> list[str]:
    """Up to four names for the line under the H1; the title's parenthetical is one of them.

    ``wikidata_names`` is the chosen item's English label followed by its aliases, in that
    order; ``pubchem_synonyms`` the stored synonym list. A near duplicate of the title is
    dropped (Garrett, 2026-09-12), case-insensitively: a name that contains the title
    ("Aluminium flake"), sits inside it ("Al"), or is within two letters of it ("aluminum" under
    Aluminium, "acyclovir" under Aciclovir). So is a name on the do-not-use list, which names
    something other than the molecule ("chamomile" under Apigenin): ``do_not_use`` is the
    casefolded list, the seed file by default (see synonym_do_not_use). Duplicates are compared
    case-insensitively and the first one kept. The four are counted after the filters, so a
    dropped name makes room.
    """
    forms = _title_forms(title)
    skip = synonym_do_not_use() if do_not_use is None else do_not_use
    out: list[str] = []
    seen: set[str] = set()
    for raw in [*(wikidata_names or []), *(pubchem_synonyms or [])]:
        name = (raw or "").strip()
        key = name.casefold()
        if not _readable_name(name) or key in seen or key in skip or _near_title(key, forms):
            continue
        seen.add(key)
        out.append(name)
        if len(out) == DISPLAY_SYNONYMS_MAX:
            break
    return out


def _wikidata_names(row: dict) -> list:
    """The canon row's Wikidata label, then its aliases."""
    return [row.get("wikidata_label"), *(row.get("wikidata_aliases") or [])]


# ── Names that are not the molecule (Garrett, 2026-09-12) ────────────────────────────────────
# PubChem lists some synonyms that name something else: the plant a compound is found in, the
# insect a pigment is made from, a class of compounds, a material. They stay off the synonym line
# (display_synonyms) and out of the title's parenthetical (title_synonym).
SYNONYM_DO_NOT_USE = SEEDS_DIR / "synonym_do_not_use.yaml"


@functools.lru_cache(maxsize=1)
def synonym_do_not_use() -> frozenset:
    """The casefolded names never shown as another name for a molecule (seeds/synonym_do_not_use.yaml):
    not on the synonym line and not in the title's parenthetical. Every entry needs a name and a
    reason, and a duplicate fails the run."""
    if not SYNONYM_DO_NOT_USE.exists():
        return frozenset()
    names: list[str] = []
    problems: list[str] = []
    for entry in yaml.safe_load(SYNONYM_DO_NOT_USE.read_text()) or []:
        name = str((entry or {}).get("name") or "").strip()
        if not name or not str((entry or {}).get("why") or "").strip():
            problems.append(f"an entry needs a name and a why: {entry!r}")
            continue
        names.append(name.casefold())
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        problems.append("listed twice: " + ", ".join(dupes))
    if problems:
        raise SystemExit(f"{SYNONYM_DO_NOT_USE.name}: " + "; ".join(problems))
    return frozenset(names)


# ── The title's parenthetical (Garrett, 2026-09-12) ──────────────────────────────────────────
# Run 6 put the first display synonym in the title wherever it fit: 608 of 788, including
# "Caffeine (Guaranine)", "Sucrose (Saccharose)" and "Aciclovir (Acyclovir)". It is selective
# now, and chosen here because its first rule needs the Wikidata label, which the web never sees.
def title_synonym(title: "str | None", label: "str | None", names, texts,
                  do_not_use=frozenset()) -> "str | None":
    """The name in the title's parenthetical, or None.

    Never when the title already has a parenthesis ("Estradiol (medication)"). Otherwise the
    Wikidata English label when it differs from our title: "Acetaminophen (Paracetamol)". The
    label differs when it survived display_synonyms, which drops the title and its near
    duplicates, so a respelled or unreadable label does not count. Otherwise the first display
    synonym that the page's own description or why_it_matters text also uses, as a whole word
    in any case: "Sodium bicarbonate (Baking soda)". Otherwise None. A name on the do-not-use
    list (casefolded, see synonym_do_not_use) is passed over by both rules, even though
    display_synonyms has already dropped it. ``names`` is the display list and the name comes
    back spelled as it is there; the web capitalises it.
    """
    if not title or "(" in title:
        return None
    names = [n for n in (names or []) if n and n.casefold() not in do_not_use]
    key = (label or "").strip().casefold()
    for n in names:
        if key and n.casefold() == key:
            return n
    for n in names:
        if any(_uses_name(text, n) for text in (texts or []) if text):
            return n
    return None


def _uses_name(text: str, name: str) -> bool:
    """``name`` appears in ``text`` as a whole word or phrase, in any case: "baking soda" is in
    "Baking soda. It releases...", and "tea" is not in "steam"."""
    return re.search(rf"(?<![^\W\d_]){re.escape(name)}(?![^\W\d_])", text, re.IGNORECASE) is not None


def attach_title_synonyms(records: list[dict], labels: dict, do_not_use=None) -> None:
    """Stamp ``rec['title_synonym']`` on every record. Call after attach_descriptions, because
    the second rule reads the description. ``labels`` maps a CID to its Wikidata English label;
    ``do_not_use`` defaults to the seed list."""
    skip = synonym_do_not_use() if do_not_use is None else do_not_use
    for rec in records:
        why = (rec.get("why_it_matters") or {}).get("text")
        rec["title_synonym"] = title_synonym(rec.get("title"), labels.get(rec["cid"]),
                                             rec.get("display_synonyms"), [rec.get("description"), why],
                                             skip)


# A CAS Registry Number is 2–7 + 2 + 1 digits. The last digit is a checksum, which we verify
# so a same-shaped code (an EC number, a random dashed id) is never mistaken for a CAS.
_CAS_RE = re.compile(r"\b(\d{2,7}-\d{2}-\d)\b")


def _cas_checksum_ok(cas: str) -> bool:
    body, check = cas.replace("-", "")[:-1], int(cas[-1])
    return sum(int(d) * i for i, d in enumerate(reversed(body), start=1)) % 10 == check


def _extract_cas(syns) -> "str | None":
    """First checksum-valid CAS Registry Number among the PubChem synonyms (else None).
    ``_clean_synonyms`` drops CAS strings from the display list; this pulls the real one out
    so the web can show it beside the PubChem CID as an identity code."""
    for s in syns or []:
        m = _CAS_RE.search(str(s))
        if m and _cas_checksum_ok(m.group(1)):
            return m.group(1)
    return None


def _descriptors(props: dict) -> dict:
    return {
        "xlogp": props.get("XLogP"), "tpsa": props.get("TPSA"),
        "h_bond_donors": props.get("HBondDonorCount"),
        "h_bond_acceptors": props.get("HBondAcceptorCount"),
        "rotatable_bonds": props.get("RotatableBondCount"),
        "complexity": props.get("Complexity"), "formal_charge": props.get("Charge"),
        "confidence": label_for("descriptor"),
    }


def _prop(key: str, value, unit: "str | None", kind: str, source: str) -> dict:
    numeric = isinstance(value, (int, float))
    return {"key": key, "value_num": value if numeric else None,
            "value_text": None if numeric else str(value), "unit": unit,
            "confidence": label_for(kind), "source": _src(source)}


def _route(raw: "str | None") -> str:
    r = (raw or "oral").lower()
    return r if r in {"oral", "dermal", "inhalation", "iv"} else "other"


def _merge_curated(rec: dict, curated: dict) -> None:
    """Fold a curated YAML overlay into the record (hooks inputs, foods, editorial)."""
    cur: dict = {}
    hooks_c = curated.get("hooks") or {}

    sis = hooks_c.get("still_in_system") or {}
    if sis.get("half_life_hours") is not None:
        rec["half_life_hours"] = sis["half_life_hours"]
        rec["properties"].append(_prop("half_life_hours", sis["half_life_hours"], "h", "curated_fact", "curated"))
    if sis.get("serving_mg") is not None:
        cur["serving_mg"] = sis["serving_mg"]
        rec["properties"].append(_prop("serving_mg", sis["serving_mg"], "mg", "curated_fact", "curated"))

    dp = hooks_c.get("dose_poison") or {}
    if dp.get("ld50_mg_per_kg") is not None:
        row = {"endpoint": "LD50", "species": (dp.get("species") or "rat"),
               "route": _route(dp.get("route", "oral")), "value_num": dp["ld50_mg_per_kg"],
               "unit": "mg/kg", "confidence": label_for("ld50_raw")}
        key = (row["species"], row["route"], row["value_num"])
        rec["toxicity"] = [row] + [t for t in rec["toxicity"]
                                   if (t["species"], t["route"], t["value_num"]) != key]
        # A curated dose_poison overlay is hand-decided, so it wins outright over the
        # parsed rows, route and all. _apply_best_oral_ld50 leaves it alone.
        rec["ld50_mg_per_kg"] = dp["ld50_mg_per_kg"]
        rec["ld50_route"] = row["route"]
        rec["ld50_species"] = row["species"]

    if curated.get("capsaicinoid_ppm") is not None:
        ppm = curated["capsaicinoid_ppm"]
        cur["capsaicinoid_ppm"] = ppm
        rec["scoville_shu"] = round(ppm * 16)            # SHU ≈ ppm × 16 (plan §7)
        rec["properties"].append(_prop("scoville_shu", rec["scoville_shu"], "SHU", "scoville", "curated"))
    elif curated.get("scoville_shu") is not None:
        # Direct pure-compound Scoville for pungent molecules that aren't capsaicinoids
        # (e.g. piperine), where a capsaicinoid ppm would be meaningless.
        rec["scoville_shu"] = curated["scoville_shu"]
        rec["properties"].append(_prop("scoville_shu", rec["scoville_shu"], "SHU", "scoville", "curated"))

    if curated.get("relative_sweetness") is not None:
        rs = curated["relative_sweetness"]
        cur["relative_sweetness"] = rs
        rec["relative_sweetness"] = rs
        rec["properties"].append(_prop("relative_sweetness", rs, "x sugar", "relative_sweetness", "curated"))

    if curated.get("smell_card"):
        cur["smell_card"] = curated["smell_card"]

    for food in curated.get("foods") or []:
        fslug = food.get("category")
        if fslug:
            rec["categories"].append({"slug": fslug, "name": _titleize(fslug), "kind": "food",
                                      "note": food.get("note"), "confidence": label_for("curated_fact"),
                                      "source": _src("curated")})

    # Type / role tags (stimulant, methylxanthine, sweetener, ...): a curated
    # "what kind of molecule is this" membership that powers the roam role pills
    # and its own /in/<type> page.
    for tslug in curated.get("types") or []:
        rec["categories"].append({"slug": tslug, "name": _TYPE_NAMES.get(tslug, _titleize(tslug)), "kind": "type",
                                  "confidence": label_for("curated_fact"), "source": _src("curated")})

    if curated.get("editorial"):
        rec["content_blocks"].append({"block_type": "editorial", "body_md": curated["editorial"].strip()})

    if curated.get("tier"):
        rec["tier"] = curated["tier"]
    rec["curated"] = cur


def _apply_primary_ld50(rec: dict) -> None:
    """Stamp the molecule's one LD50 (value, route, species) and lead the toxicity list with it.

    toxicity.primary_ld50 chooses it; a curated dose_poison overlay has already pinned one by
    hand and keeps it (caffeine and capsaicin, each the row the rule would choose anyway).
    Leading the list with that row is what makes the Safety panel's first row the same LD50
    the dose hook, the boards and the /vs tables read. The other rows keep their order."""
    if rec.get("ld50_mg_per_kg") is None:
        row = toxicity.primary_ld50(rec.get("toxicity"), rec.get("slug"))
        if row:
            rec["ld50_mg_per_kg"] = row["value_num"]
            rec["ld50_route"] = row["route"]
            rec["ld50_species"] = row["species"]
    if rec.get("ld50_mg_per_kg") is None:
        return
    chosen = (rec["ld50_mg_per_kg"], rec["ld50_route"], rec["ld50_species"])
    rows = rec["toxicity"]
    at = next((i for i, t in enumerate(rows)
               if (t.get("value_num"), t.get("route"), t.get("species")) == chosen), None)
    if at:
        rows.insert(0, rows.pop(at))


def apply_scope_bucket(rec: dict, bucket: "str | None", family: "str | None") -> None:
    """Stamp a record's Scope B bucket + family, and add a kind:"bucket" category so the
    bucket is roamable (its own /in/<bucket> page) and drives the primary color. Idempotent."""
    rec["scope_bucket"] = bucket
    rec["scope_family"] = family
    if bucket:
        # Drop a curated type tag that duplicates the bucket slug (e.g. a type:"sweetener"
        # alongside bucket:"sweetener"): the web shows buckets under "Category" and types under
        # "Type", so the same word would appear twice. The bucket is the canonical membership.
        rec["categories"] = [c for c in rec["categories"]
                             if not (c.get("kind") == "type" and c.get("slug") == bucket)]
        if not any(c.get("kind") == "bucket" for c in rec["categories"]):
            rec["categories"].append({"slug": bucket, "name": buckets.bucket_label(bucket) or _titleize(bucket),
                                      "kind": "bucket", "confidence": label_for("curated_fact"),
                                      "source": _src("curated")})
    # kind:"family" (build plan 2026-09-05, phase 3). scope_family is set on 100% of
    # records and was never emitted as a category, so 36 ready-made groupings existed in
    # the data and none of them had a page. Thin ones are pruned later by
    # prune_thin_categories, so a one-member family never becomes a hub.
    #
    # "other" is the CSV's explicit "no family fits" value on 87 rows. A hub called
    # Other compounds holding a sixth of the canon would be a page about nothing, so it
    # is the one family that never gets one.
    if family and family not in FAMILY_HUB_EXCLUDE:
        label = ((_phrases().get("families") or {}).get(family) or {}).get("hub") or _titleize(family)
        if not any(c.get("kind") == "family" for c in rec["categories"]):
            rec["categories"].append({"slug": family, "name": label, "kind": "family",
                                      "confidence": label_for("curated_fact"),
                                      "source": _src("curated")})


# ── Descriptions (build plan 2026-09-05, phase 1) ────────────────────────────
# Until 2026-09 the meta description, the on-page "What is X?" answer and the
# FAQPage JSON-LD all read from Wikidata's one-line description, which for 292 of
# 498 molecules is the string "chemical compound": 498 pages, 164 distinct
# descriptions, mean length 30 characters. Search engines correctly read that as
# thin duplicated content.
#
# `build_description` composes a specific, unique sentence for EVERY record out of
# fields every record already has. The wording lives in
# sources/seeds/description_phrases.yaml so it stays consistent and editable.
#
# A curated `why_it_matters` line, when present, LEADS the description: it is the
# better sentence and it is the site's own voice. The template then supplies the
# identity clause behind it. That composition (rather than the plan's plain
# fallback chain) is deliberate: many curated lines are short by design, because
# they are also the roam SELECTED panel's caption, and a 41-character meta
# description is the exact failure this phase exists to fix. Composing keeps the
# curated voice AND clears the floor; a future short curated line cannot
# reintroduce the problem.
DESCRIPTION_PHRASES = SEEDS_DIR / "description_phrases.yaml"
MIN_DESCRIPTION = 100          # the floor verify-snapshot.mjs enforces on the web side
_warned_families: set = set()


@functools.lru_cache(maxsize=1)
def _phrases() -> dict:
    if not DESCRIPTION_PHRASES.exists():
        return {"families": {}, "buckets": {}, "ghs_pictograms": {}, "functional_groups": {}}
    return yaml.safe_load(DESCRIPTION_PHRASES.read_text()) or {}


def _fmt_num(v: float) -> str:
    """1580.0 -> '1,580'; 152.15 -> '152'; 0.0006 -> '0.0006'."""
    if v is None:
        return ""
    if abs(v) >= 10:
        return f"{round(v):,}"
    if abs(v) >= 1:
        return f"{v:.1f}".rstrip("0").rstrip(".")
    return f"{v:g}"


def _family_phrase(rec: dict) -> tuple[str, str]:
    """(article, noun phrase) for the record's scope family."""
    fam = (rec.get("scope_family") or "").strip().lower()
    entry = (_phrases().get("families") or {}).get(fam)
    if entry:
        return entry.get("article", "a"), entry.get("phrase", "compound")
    if fam and fam not in _warned_families:
        _warned_families.add(fam)
        log.warning("  description: no phrase for scope_family %r (falling back to 'compound'); "
                    "add it to description_phrases.yaml", fam)
    return "a", "compound"


def _identity_clause(rec: dict) -> str:
    """'Vanillin (C8H8O3, 152 g/mol) is a phenolic compound found in everyday food
    and flavor.' Hand-modeled macromolecules have no formula or weight, so they get
    the same sentence without the parenthetical."""
    article, phrase = _family_phrase(rec)
    bucket = (_phrases().get("buckets") or {}).get(rec.get("scope_bucket") or "")
    ident = rec["title"]
    formula, mw = rec.get("molecular_formula"), rec.get("molecular_weight")
    if formula and mw:
        ident = f"{ident} ({formula}, {_fmt_num(mw)} g/mol)"
    elif formula:
        ident = f"{ident} ({formula})"
    return f"{ident} is {article} {phrase}" + (f" {bucket}." if bucket else ".")


def _hazard_clause(rec: dict) -> str:
    """'Labeled GHS Danger: corrosive and acutely toxic.' Factual label reporting,
    never a handling instruction (house rule: no advice)."""
    ghs = rec.get("ghs") or {}
    word = ghs.get("signal_word")
    if not word:
        return ""
    table = _phrases().get("ghs_pictograms") or {}
    words = [table[p] for p in table if p in set(ghs.get("pictograms") or [])][:2]
    if not words:
        return f"Labeled GHS signal word {word}."
    return f"Labeled GHS {word}: {' and '.join(words)}."


def _measure_clause(rec: dict) -> str:
    """The one measured number this molecule actually carries, if any. Ordered by
    how distinctive it is, so a sweetener leads with sweetness rather than LD50."""
    if rec.get("relative_sweetness"):
        return f"About {_fmt_num(rec['relative_sweetness'])} times as sweet as table sugar."
    if rec.get("scoville_shu"):
        return f"Rated {_fmt_num(rec['scoville_shu'])} Scoville heat units as a pure compound."
    if rec.get("odor_threshold"):
        return f"Detectable by smell at about {_fmt_num(rec['odor_threshold'])} ng per cubic metre of air."
    if rec.get("half_life_hours"):
        return f"Its reported half-life in the body is about {_fmt_num(rec['half_life_hours'])} hours."
    # The molecule's one LD50, and only an oral one, since the sentence says oral. This used to
    # read the first oral row and call it the lowest; no current description reaches the clause.
    if rec.get("ld50_mg_per_kg") is not None and rec.get("ld50_route") == "oral":
        return (f"Its reported oral LD50 is {_fmt_num(rec['ld50_mg_per_kg'])} mg/kg "
                f"in the {rec['ld50_species']}.")
    return ""


def _structure_clause(rec: dict) -> str:
    """'Its structure carries an aromatic ring and a hydroxyl group.' Used only when
    the sentences above leave the description under the floor."""
    table = _phrases().get("functional_groups") or {}
    groups = [table[c["slug"]] for c in rec.get("categories") or []
              if c.get("kind") == "functional_group" and c.get("slug") in table][:2]
    if not groups:
        return ""
    return f"Its structure carries {' and '.join(groups)}."


def _food_clause(rec: dict) -> str:
    foods = [c["name"].lower() for c in rec.get("categories") or [] if c.get("kind") == "food"][:3]
    if not foods:
        return ""
    if len(foods) == 1:
        return f"On MoleculeFinder it is mapped to {foods[0]}."
    return f"On MoleculeFinder it is mapped to {', '.join(foods[:-1])} and {foods[-1]}."


def _synonym_clause(rec: dict) -> str:
    """'Also known as vanillic aldehyde.' Padding that earns its place: the synonym
    is a real query a reader might type."""
    syns = [x for x in (rec.get("synonyms") or []) if x and x.lower() != (rec["title"] or "").lower()][:2]
    if not syns:
        return ""
    return f"Also known as {' and '.join(syns).lower()}."


def _neighbor_clause(rec: dict) -> str:
    """'Its closest structural neighbor in the canon is ferulic acid.' Last padding
    clause, and the one that most invites a second page view."""
    edges = rec.get("edges") or []
    if not edges:
        return ""
    return f"Its closest structural neighbor in the MoleculeFinder canon is {edges[0]['neighbor_title'].lower()}."


def _provenance_clause(rec: dict) -> str:
    """The terminal clause, and the reason the floor is structurally guaranteed rather
    than merely observed. Every clause above depends on data a record MIGHT lack; a
    sparsely populated molecule (no GHS, no measured value, no foods, no matched
    functional group, no synonym, no neighbor) could otherwise land under the floor and
    hard-fail the build on a data refresh. This one is always true and always available.
    It is generic, so it fires last and only when nothing better is left."""
    return ("Every value on its MoleculeFinder page carries a source and a confidence "
            "label saying whether it was measured, computed, or inferred.")


def _macromolecule_clause(rec: dict) -> str:
    if not rec.get("macromolecule"):
        return ""
    return ("It has no single molecular formula, so MoleculeFinder carries it as a "
            "hand-modeled entry rather than one PubChem compound.")


def build_description(rec: dict) -> str:
    """The page description: unique per molecule, never under MIN_DESCRIPTION chars.

    Feeds the meta description, the on-page "What is X?" answer and the FAQPage
    acceptedAnswer (one string, so structured data can never drift from the visible
    page). Clauses are appended in order of value to a reader and stop as soon as
    the floor is cleared, so a molecule with a rich record does not get a padded
    sentence it does not need.
    """
    curated = ((rec.get("why_it_matters") or {}).get("text") or "").strip()
    if curated:
        # The curated line leads and, when it already clears the floor, stands alone.
        # A search snippet is cut around 155-160 characters, so bolting the identity
        # clause onto an already-good sentence would only push the interesting half
        # out of the snippet. The identity clause is the FIRST filler below instead.
        parts = [curated if curated.endswith((".", "!", "?")) else curated + "."]
        filler = (_identity_clause(rec),)
    else:
        parts = [_identity_clause(rec)]
        filler = ()

    # Optional clauses, best first. Appended only while the text is under the floor,
    # so a description stays a description and not a data dump.
    for clause in filler + (_macromolecule_clause(rec), _hazard_clause(rec),
                            _measure_clause(rec), _food_clause(rec), _structure_clause(rec),
                            _synonym_clause(rec), _neighbor_clause(rec),
                            _provenance_clause(rec)):
        if len(" ".join(parts)) >= MIN_DESCRIPTION:
            break
        if clause:
            parts.append(clause)
    return " ".join(p for p in parts if p)


def attach_descriptions(records: list[dict]) -> None:
    """Stamp ``rec['description']`` on every record. Call after the curated overlays
    (why_it_matters, foods, odor thresholds) are attached, so they can feed it.

    Uniqueness is a build-time guarantee, not a hope: every description opens with
    the molecule's own title, and titles are unique across the canon. This asserts
    it anyway, because a duplicate description is the precise defect phase 1 exists
    to remove and a silent regression would be invisible until Bing flagged it.
    """
    seen: dict[str, str] = {}
    clashes: list[str] = []
    short: list[str] = []
    for rec in records:
        d = build_description(rec)
        rec["description"] = d
        rec["description_source"] = ("MoleculeFinder curated"
                                     if (rec.get("why_it_matters") or {}).get("text")
                                     else "MoleculeFinder generated")
        if len(d) < MIN_DESCRIPTION:
            short.append(f"{rec['slug']} ({len(d)}): {d}")
        if d in seen:
            clashes.append(f"{rec['slug']} duplicates {seen[d]}: {d[:80]}")
        seen[d] = rec["slug"]
    if clashes:
        raise SystemExit("description build failed, duplicate description(s):\n  "
                         + "\n  ".join(clashes))
    if short:
        raise SystemExit(f"description build failed, {len(short)} under {MIN_DESCRIPTION} chars:\n  "
                         + "\n  ".join(short))
    # House rule (137 web standards): no em-dashes in visible site copy. The description
    # is visible copy on every molecule page, so enforce it where it is built.
    dashes = [r["slug"] for r in records if "\u2014" in r["description"]]
    if dashes:
        raise SystemExit("description build failed, em-dash in visible copy: " + ", ".join(dashes))
    lengths = sorted(len(r["description"]) for r in records)
    log.info("  descriptions: %d unique, %d..%d chars (mean %d)", len(seen), lengths[0],
             lengths[-1], sum(lengths) // len(lengths))


# ── Derived hubs (build plan 2026-09-05, phase 3) ────────────────────────────
# Three more groupings that are already implicit in every record and cost nothing but
# a pass over the snapshot: which elements a formula contains, which GHS hazard label
# a molecule carries, and how big it is. Each becomes its own /in/<slug> page through
# the existing category inversion, with no web change at all.

# Elements worth a hub. Carbon, hydrogen and oxygen are deliberately absent: they are
# in nearly every record, so a hub for them would list the whole canon and mean
# nothing. What is left is the heteroatoms and metals a reader can actually use as a
# filter.
ELEMENT_HUBS: dict[str, str] = {
    "N": "Nitrogen", "S": "Sulfur", "P": "Phosphorus",
    "F": "Fluorine", "Cl": "Chlorine", "Br": "Bromine", "I": "Iodine",
    "Na": "Sodium", "K": "Potassium", "Ca": "Calcium", "Mg": "Magnesium",
    "Fe": "Iron", "Zn": "Zinc", "Se": "Selenium", "Co": "Cobalt",
    "Cr": "Chromium", "Al": "Aluminium", "Bi": "Bismuth", "Li": "Lithium",
}
# Two-letter symbols must be tried before one-letter ones, or "Na" reads as N + a.
_FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?)")

# GHS pictogram / signal word -> hub. The wording is the label's own, reported as a
# fact about what suppliers filed, never as advice.
GHS_HUBS: dict[str, tuple[str, str]] = {
    "GHS01": ("explosive", "Explosive"),
    "GHS02": ("flammable", "Flammable"),
    "GHS03": ("oxidizing", "Oxidizing"),
    "GHS04": ("compressed-gas", "Compressed gas"),
    "GHS05": ("corrosive", "Corrosive"),
    "GHS06": ("acutely-toxic", "Acutely toxic"),
    "GHS07": ("irritant", "Irritant"),
    "GHS08": ("health-hazard", "Health hazard"),
    "GHS09": ("environmental-hazard", "Environmental hazard"),
}
SIGNAL_WORD_HUBS: dict[str, tuple[str, str]] = {
    "Danger": ("ghs-danger", "GHS Danger"),
    "Warning": ("ghs-warning", "GHS Warning"),
}

# Molecular-weight bands. Only the two ends: the middle of the distribution is where
# almost everything sits, so a band there would be a hub of 400 molecules.
SIZE_BANDS: list[tuple[str, str, float, float]] = [
    ("under-100-g-mol", "Under 100 g/mol", 0.0, 100.0),
    ("over-1000-g-mol", "Over 1000 g/mol", 1000.0, float("inf")),
]


def _elements_in(formula: "str | None") -> list[str]:
    """Element symbols present in a molecular formula, hub-worthy ones only."""
    if not formula:
        return []
    seen, out = set(), []
    for sym in _FORMULA_TOKEN.findall(formula):
        if sym in ELEMENT_HUBS and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def attach_derived_categories(records: list[dict]) -> None:
    """Stamp the element, GHS-hazard and size-band hubs on every record."""
    for rec in records:
        cats = rec["categories"]
        have = {(c.get("kind"), c.get("slug")) for c in cats}

        for sym in _elements_in(rec.get("molecular_formula")):
            # Prefix the slug so an element can never collide with a family or bucket of
            # the same name: /in/sulfur the family (9 sulfur compounds) and /in/sulfur the
            # element (55 molecules containing an S) are different questions.
            slug = "element-" + ELEMENT_HUBS[sym].lower()
            if ("element", slug) not in have:
                cats.append({"slug": slug, "name": ELEMENT_HUBS[sym], "kind": "element",
                             "confidence": label_for("functional_group"), "source": _src("pubchem")})

        ghs = rec.get("ghs") or {}
        for pic in ghs.get("pictograms") or []:
            hub = GHS_HUBS.get(pic)
            if hub and ("poison", hub[0]) not in have:
                cats.append({"slug": hub[0], "name": hub[1], "kind": "poison",
                             "confidence": label_for("ld50_raw"), "source": _src("pubchem")})
        word = SIGNAL_WORD_HUBS.get(ghs.get("signal_word") or "")
        if word and ("poison", word[0]) not in have:
            cats.append({"slug": word[0], "name": word[1], "kind": "poison",
                         "confidence": label_for("ld50_raw"), "source": _src("pubchem")})

        mw = rec.get("molecular_weight")
        if isinstance(mw, (int, float)):
            for slug, label, lo, hi in SIZE_BANDS:
                if lo <= mw < hi and ("size", slug) not in have:
                    cats.append({"slug": slug, "name": label, "kind": "size",
                                 "confidence": label_for("descriptor"), "source": _src("pubchem")})


# One /in/<slug> page can only be one kind. The web inverts categories BY SLUG, so a
# slug appearing under two kinds (family:"amino-acid" beside a curated
# type:"amino-acid") yields a single hub with an arbitrary label and an arbitrary
# confidence chip, depending only on which molecule file was read first. That was
# harmless while every kind used its own vocabulary; phase 3's family hubs put 11
# slugs into collision at once, so it is settled here instead of left to file order.
#
# Highest priority wins and the other memberships are rewritten onto it, so no
# molecule ever falls out of a hub it belonged in.
KIND_PRIORITY = ("bucket", "food", "product", "use", "family", "type", "drug_class",
                 "functional_group", "element", "poison", "size")


def unify_category_kinds(records: list[dict]) -> None:
    """Force every category slug to exactly one kind, corpus-wide."""
    kinds_by_slug: dict[str, set] = {}
    for rec in records:
        for c in rec["categories"]:
            kinds_by_slug.setdefault(c["slug"], set()).add(c.get("kind"))
    rank = {k: i for i, k in enumerate(KIND_PRIORITY)}
    winners = {slug: min(kinds, key=lambda k: rank.get(k, len(rank)))
               for slug, kinds in kinds_by_slug.items() if len(kinds) > 1}
    if not winners:
        return
    # The label to keep is the winning kind's own label, so /in/sweetener reads
    # "Sweetener" (the bucket) and not "Sweeteners" (the family).
    names = {}
    for rec in records:
        for c in rec["categories"]:
            if c["slug"] in winners and c.get("kind") == winners[c["slug"]]:
                names[c["slug"]] = c.get("name")
    for rec in records:
        out, seen = [], set()
        for c in rec["categories"]:
            slug = c["slug"]
            if slug in winners:
                c = {**c, "kind": winners[slug], "name": names.get(slug, c.get("name"))}
            key = (c["kind"], slug)
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
        rec["categories"] = out
    log.info("  hubs: unified %d slug(s) onto one kind (%s)", len(winners),
             ", ".join(f"{s}->{k}" for s, k in sorted(winners.items())[:6]))


# Kinds that are DERIVED (computed from data, not hand-curated) and therefore safe to
# prune when they would make a near-empty page. A curated food or type membership is
# never pruned: it was written on purpose and a small curated hub is still a real one.
PRUNABLE_KINDS = ("family", "element", "poison", "size", "functional_group")
MIN_HUB_MEMBERS = 3


def prune_thin_categories(records: list[dict], min_members: int = MIN_HUB_MEMBERS) -> None:
    """Drop derived memberships whose hub would have fewer than `min_members` molecules.

    A one-member /in/<x> page is the thin content this whole build plan is about; it
    would be published, indexed, and hold nothing. Curated kinds are exempt."""
    counts: dict[tuple, int] = {}
    for rec in records:
        for c in rec["categories"]:
            if c.get("kind") in PRUNABLE_KINDS:
                counts[(c["kind"], c["slug"])] = counts.get((c["kind"], c["slug"]), 0) + 1
    dropped = {k for k, n in counts.items() if n < min_members}
    if not dropped:
        return
    for rec in records:
        rec["categories"] = [c for c in rec["categories"]
                             if (c.get("kind"), c.get("slug")) not in dropped]
    log.info("  hubs: pruned %d derived hub(s) under %d members (%s)", len(dropped), min_members,
             ", ".join(sorted(f"{k}:{s}" for k, s in dropped)[:8]))


def _carried_svg(smiles: "str | None", prior: dict | None) -> dict:
    """``structure_svg`` + the fingerprint that says when it may be reused.

    RDKit lays the same molecule out differently on macOS and on Linux for the ~7% of the
    catalog whose depiction goes through a numerical minimiser (``structures`` docstring has
    the measurements). Re-rendering every week therefore rewrote 53 files on any run that
    happened on the other platform, for no change a reader could see. A record whose SMILES
    and recipe version are unchanged now keeps the exact SVG it shipped with.
    """
    if not smiles:
        return {"structure_svg": None, "structure_svg_key": None}
    key = structures.svg_key(smiles)
    if prior and prior.get("structure_svg"):
        # Normal path: the fingerprint says the structure and the recipe are both unchanged.
        # Adoption path: records exported before the key existed carry no fingerprint, so
        # fall back to comparing the SMILES they were drawn from. Without it the very run
        # that introduces the key would redraw all 769 structures on whatever platform it
        # happened to run on, which is the churn this exists to stop.
        unchanged = (prior.get("structure_svg_key") == key
                     or (prior.get("structure_svg_key") is None
                         and prior.get("isomeric_smiles") == smiles))
        if unchanged:
            return {"structure_svg": prior["structure_svg"], "structure_svg_key": key}
    return {"structure_svg": structures.svg_for(smiles), "structure_svg_key": key}


def assemble_record(row: dict, fetched: dict, taken: set, prior: dict | None = None) -> dict:
    """Build one molecule record from a canon row + its fetched PubChem payload.

    ``prior`` is this molecule's record from the last exported snapshot, when there is one.
    It is used for exactly one thing: carrying the drawn structure forward (see
    ``_carried_svg``). Nothing else reads it, so a missing prior only means a redraw.
    """
    cid = row["cid"]
    props = fetched.get("props") or {}
    curated = fetched.get("curated") or {}
    syns = fetched.get("synonyms") or []

    iso = _first(props, _ISO_KEYS)
    can = _first(props, _CAN_KEYS)
    title = row.get("enwiki_title") or names.preferred_name(cid, None, syns)
    pref = names.preferred_name(cid, row.get("enwiki_title"), syns)
    # Curated display-name override: PubChem/Wikidata sometimes prefer a non-US name
    # (e.g. "Paracetamol"); a US audience wants "Acetaminophen". Set before _clean_synonyms
    # so the overridden name is the title and the old name falls back into synonyms.
    if curated.get("display_name"):
        title = curated["display_name"]
    slug = slugs.unique_slug(curated.get("slug") or pref or title or f"cid-{cid}", taken)

    rec = {
        "cid": cid, "slug": slug, "title": _normalize_greek(title), "preferred_name": pref,
        "tier": row.get("tier", "canon"),
        "wikidata_qid": row.get("wikidata_qid"), "wikipedia_title": row.get("enwiki_title"),
        "pageviews_monthly": int(row.get("pageviews") or 0),
        "summary": row.get("summary"),
        "summary_source": _src("wikidata") if row.get("summary") else None,
        "iupac_name": None,
        "molecular_formula": props.get("MolecularFormula"),
        "molecular_weight": _to_float(props.get("MolecularWeight")),
        "canonical_smiles": can, "isomeric_smiles": iso,
        "inchi": props.get("InChI"), "inchikey": props.get("InChIKey"),
        "cas": _extract_cas(syns),
        "synonyms": _clean_synonyms(syns, title),
        # The line under the H1 (see display_synonyms) and the title's parenthetical, which
        # attach_title_synonyms fills in once the description exists.
        "display_synonyms": display_synonyms(_normalize_greek(title), _wikidata_names(row),
                                             _clean_synonyms(syns, title)),
        "title_synonym": None,
        **_carried_svg(iso, prior),
        # PubChem returns Volume3D only when a 3D conformer exists; the web hides the 3D toggle
        # when this is false (e.g. large peptides / polymers have a 2D depiction but no 3D).
        "has_3d": props.get("Volume3D") is not None,
        "descriptors": _descriptors(props),
        "toxicity": list(fetched.get("toxicity") or []),
        "ghs": fetched.get("ghs"),
        "properties": [], "categories": [], "hooks": [], "edges": [], "content_blocks": [],
        "half_life_hours": None,
        # The molecule's one LD50 (_apply_primary_ld50 -> toxicity.primary_ld50), which also
        # leads `toxicity`, so the Safety panel, the dose hook, the boards and the /vs tables
        # read the same row. Route and species ride alongside the number so each of them can
        # show them; the boards and the hook take it only when it is oral.
        "ld50_mg_per_kg": None, "ld50_route": None, "ld50_species": None,
        "relative_sweetness": None, "scoville_shu": None,
        # Scope B grouping (populated for must-include seed molecules); hand_model flags
        # the structureless macromolecule variant. Uniform keys so every record has them.
        "scope_bucket": None, "scope_family": None,
        "hand_model": False, "macromolecule": False,
        # Carried off the canon row (the Scope B CSV columns). These were dropped here
        # until 2026-09: `assemble_handmodel` copied them, `assemble_record` did not, so
        # 480 of 498 records shipped without the flags the CSV had set for them.
        "is_otc": bool(row.get("is_otc")), "dual_use": bool(row.get("dual_use")),
        # Which catalog tranche this molecule arrived in (None for the original core).
        # Provenance only; nothing branches on it.
        "batch": row.get("batch") or None,
    }

    if curated:
        _merge_curated(rec, curated)

    # A fetched compound with no SMILES has nothing to draw: PubChem carries the record
    # but not a depictable structure (monoclonal antibodies and other biologics). Flag it
    # so the web uses the structureless page variant instead of rendering an empty figure.
    # `hand_model` stays False: this molecule DOES have a real PubChem CID, and the sheet
    # line keys its "no single PubChem compound" wording off hand_model, not this flag.
    if not iso and not can:
        rec["macromolecule"] = True

    _apply_primary_ld50(rec)

    # Functional-group categories (RDKit SMARTS → computed membership).
    for fg in categories.functional_groups(iso or ""):
        rec["categories"].append({"slug": fg, "name": _titleize(fg), "kind": "functional_group",
                                  "confidence": label_for("functional_group"), "source": _src("rdkit")})

    # Primary family (Color System Brief §2b): first kind:type membership that maps
    # to a hued family. Consumed by the family pills/cards/neighbors/roam on the web.
    rec["family"] = families.family_of(rec["categories"])

    # Scope B bucket (the primary color/roam dimension): from the canon row when the core
    # list supplies it. No-op for rows without one; the hand-model path stamps its own.
    apply_scope_bucket(rec, row.get("scope_bucket"), row.get("scope_family"))

    # Hooks (plan §7.1). hooks.hooks_for reads these exact keys.
    rec["hooks"] = hooks.hooks_for({
        "cid": cid, "isomeric_smiles": iso, "half_life_hours": rec["half_life_hours"],
        "ld50_mg_per_kg": rec["ld50_mg_per_kg"], "ld50_route": rec["ld50_route"],
        "ld50_species": rec["ld50_species"], "curated": rec.get("curated") or {},
    })

    used = {"pubchem", "rdkit"}
    if rec["summary"] or rec["wikidata_qid"]:
        used.add("wikidata")
    if rec["pageviews_monthly"]:
        used.add("wikimedia_pageviews")
    if curated:
        used.add("curated")
    rec["sources"] = sorted(_src(k) for k in used)

    rec.pop("curated", None)   # internal to assembly; its data now lives in hooks/props/categories
    return rec


def assemble_handmodel(row: dict, meta: dict, taken: set) -> dict:
    """Structureless record for a hand-modeled macromolecule / mixture (collagen, starch,
    gluten, hemoglobin...) that has NO single PubChem compound.

    These are force-included from the household must-include seed (`hand-model` handling).
    We deliberately DO NOT fabricate a structure, molecular weight or SMILES: the record
    carries curated identity + Scope B family/bucket only, every value confidence-labeled,
    and the web renders it with the macromolecule page variant (no 2D/3D). It gets no
    similarity edges (no fingerprint) and never qualifies for a numeric leaderboard.
    """
    cid = int(row["cid"])
    name = meta.get("name") or row.get("enwiki_title") or f"CID {cid}"
    slug = slugs.unique_slug(meta.get("slug") or name, taken)
    fam_slug = (meta.get("family") or "").strip().lower()

    rec = {
        "cid": cid, "slug": slug, "title": _normalize_greek(name), "preferred_name": name,
        "tier": row.get("tier", "marquee"),
        "wikidata_qid": row.get("wikidata_qid"), "wikipedia_title": row.get("enwiki_title"),
        "pageviews_monthly": int(row.get("pageviews") or 0),
        "summary": row.get("summary"),
        "summary_source": _src("wikidata") if row.get("summary") else None,
        "iupac_name": None, "molecular_formula": None, "molecular_weight": None,
        "canonical_smiles": None, "isomeric_smiles": None, "inchi": None, "inchikey": None,
        "cas": None,                 # no single compound ⇒ no CAS Registry Number
        "synonyms": [name],
        "display_synonyms": display_synonyms(_normalize_greek(name), _wikidata_names(row), []),
        "title_synonym": None,       # attach_title_synonyms; a macromolecule's title never shows it
        "structure_svg": None,       # no single structure — the web variant omits the render
        "structure_svg_key": None,
        "descriptors": {"xlogp": None, "tpsa": None, "h_bond_donors": None,
                        "h_bond_acceptors": None, "rotatable_bonds": None,
                        "complexity": None, "formal_charge": None,
                        "confidence": label_for("descriptor")},
        "toxicity": [], "ghs": None,
        "properties": [], "categories": [], "hooks": [], "edges": [], "content_blocks": [],
        "half_life_hours": None, "ld50_mg_per_kg": None,
        "ld50_route": None, "ld50_species": None,
        "relative_sweetness": None, "scoville_shu": None,
        "scope_bucket": meta.get("bucket"), "scope_family": meta.get("family"),
        "hand_model": True, "macromolecule": True,
        "is_otc": bool(meta.get("is_otc")), "dual_use": bool(meta.get("dual_use")),
        "batch": row.get("batch") or None,
    }
    # The curated family becomes a kind:"type" membership, so the molecule groups on its
    # own /in/<family> page and survives filter-4. Confidence: hand-authored (from_source).
    if fam_slug:
        rec["categories"].append({"slug": fam_slug, "name": _TYPE_NAMES.get(fam_slug, _titleize(fam_slug)),
                                  "kind": "type", "confidence": label_for("curated_fact"),
                                  "source": _src("curated")})
    rec["family"] = families.family_of(rec["categories"])
    apply_scope_bucket(rec, meta.get("bucket"), meta.get("family"))
    rec["sources"] = ["curated"] + (["wikidata"] if rec["summary"] else [])
    return rec


def attach_edges(records: list[dict], top_n: int | None = None, floor: float | None = None) -> None:
    """Compute Morgan fingerprints once and attach each record's top-N neighbors."""
    kwargs = {}
    if top_n is not None:
        kwargs["top_n"] = top_n
    if floor is not None:
        kwargs["floor"] = floor
    smiles = [r["isomeric_smiles"] or "" for r in records]
    fps, index_map = similarity.morgan_fingerprints(smiles)
    for i, j, score in similarity.top_edges(fps, index_map, **kwargs):
        nbr = records[j]
        records[i]["edges"].append({
            "neighbor_cid": nbr["cid"], "neighbor_slug": nbr["slug"], "neighbor_title": nbr["title"],
            "neighbor_family": nbr.get("family"), "neighbor_bucket": nbr.get("scope_bucket"),
            "tanimoto": score, "method": "morgan_r2_2048", "confidence": label_for("similarity"),
        })


def apply_filter4(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Filter-4 (plan §4): demote orphans with zero hooks AND zero edges AND no category.
    Hand-modeled must-include molecules are always kept (they are curated on purpose and
    have no structure to earn edges)."""
    kept, deferred = [], []
    for r in records:
        (kept if (r.get("hand_model") or r["hooks"] or r["edges"] or r["categories"]) else deferred).append(r)
    return kept, deferred
