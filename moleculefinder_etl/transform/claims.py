"""The claim rule for curated copy (build plan everyday chemistry 2026-11, phase 2, the copy sweep).

A curated line may say "only", "first", "most", "leading", "largest", "world's", "never" or "always"
when (a) our own data shows it and the build asserts it, or (b) it is a standard, datable fact of
chemistry, biology or history (the first benzodiazepine, the only metal liquid at room temperature),
or (c) the word ranks nothing ("only about two hours", "the first half of the cycle"). A claim about
how common something is, what people do, or a health outcome is rewritten to what our data supports,
or loses the word. A finding of a US government agency counts under (b), basis ``history``, when the
line names the agency as its source (Garrett, 2026-11-10): "the FDA called it the first new class of
pain medicine in over 20 years" (suzetrigine), "the US EPA ranks it second only to smoking as a cause
of lung cancer" (radon). The same finding with no agency named is a health-outcome claim and is not.

Every curated line that keeps such a word has an entry in ``sources/seeds/claims_allowed.yaml`` with
its basis, pinned to the exact text of the line by a short hash. So a NEW line carrying a word, or an
EDITED line that carries one, has no matching entry and stops the build (``check_lines``, at the start
of ``stage_transform``, and in pytest) until someone writes down why it stands. A ``data`` basis names
a check in ``DATA_CHECKS``, which the export preflight runs against the built catalog
(``check_data_claims``): if the data stops showing the claim, the run refuses.

The lines covered: every why-it-matters line, every editorial paragraph, every comparison paragraph
and every comparison answer line. Answer lines are never edited by the sweep (they are the /vs pages'
descriptions); an answer line that overreaches is held with basis ``held`` and listed for Garrett.

The web repo's ``lib/copy-rules.ts`` carries the same word list (``CLAIM_WORDS``) for strings written
there; a test in each repo pins the list, so a change has to be made in both.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

SOURCES = Path(__file__).resolve().parent.parent / "sources"
SEEDS_DIR = SOURCES / "seeds"
CURATED_DIR = SOURCES / "curated"
CLAIMS_ALLOWED = SEEDS_DIR / "claims_allowed.yaml"

# The words, in the plan's order. The web's lib/copy-rules.ts CLAIM_WORDS must equal this list.
CLAIM_WORDS = ("only", "first", "most", "leading", "largest", "world's", "never", "always")
# Curly and straight apostrophes both count as "world's"; "first" inside "twenty-first" or
# "first-line" counts too (a hyphen is a word boundary), and the entry says why it stands.
CLAIM_RE = re.compile(r"\b(only|first|most|leading|largest|world[’']s|never|always)\b", re.IGNORECASE)

# Phrases a curated-list page may not use (decision 8): a curated list is a selection, never all.
# The web's lib/copy-rules.ts COMPLETENESS holds the same phrases.
COMPLETENESS = ("every molecule in", "all the molecules in", "the molecules in it")

# The bases an entry may give. `data` must also name a check in DATA_CHECKS.
BASES = {
    "data": "our own data shows it, and the build asserts it",
    "science": "a standard fact of chemistry, biology or pharmacology",
    "history": "a standard, datable fact of history, regulation or discovery, or a US government agency's finding the line attributes to it by name",
    "ordinary": "the word ranks nothing (\"only about\", \"the first half\", \"first-line\")",
    "held": "a comparison answer line, never edited by the sweep; listed for Garrett",
}

KINDS = ("why_it_matters", "editorial", "comparison", "answer")


class ClaimError(SystemExit):
    """A curated line carries a claim word with no entry, or an entry no longer matches its line."""


def normalise(text: str) -> str:
    return " ".join((text or "").split())


def line_id(text: str) -> str:
    """The short hash an entry pins its line by: sha256 of the whitespace-normalised text."""
    return hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()[:12]


def words_in(text: str) -> list[str]:
    """The claim words a line carries, lower-cased, apostrophe straightened, once each, sorted."""
    return sorted({m.lower().replace("’", "'") for m in CLAIM_RE.findall(text or "")})


def corpus(seeds: Path = SEEDS_DIR, curated: Path = CURATED_DIR) -> list[tuple[str, str, str]]:
    """Every curated line the rule covers, as (kind, key, text)."""
    out: list[tuple[str, str, str]] = []
    wim = yaml.safe_load((seeds / "why_it_matters.yaml").read_text()) or {}
    out += [("why_it_matters", str(k), normalise(v)) for k, v in wim.items()]
    for f in sorted(curated.glob("*.yaml")):
        d = yaml.safe_load(f.read_text()) or {}
        if d.get("editorial"):
            out.append(("editorial", str(d.get("slug") or f.stem), normalise(d["editorial"])))
    cmp = yaml.safe_load((seeds / "comparisons.yaml").read_text()) or {}
    for pair, v in cmp.items():
        out.append(("comparison", str(pair), normalise(v.get("text"))))
        if v.get("answer"):
            out.append(("answer", str(pair), normalise(v["answer"])))
    return out


def load_allowed(path: Path = CLAIMS_ALLOWED) -> dict[tuple[str, str], dict]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    out: dict[tuple[str, str], dict] = {}
    for kind in KINDS:
        for key, entry in (data.get(kind) or {}).items():
            out[(kind, str(key))] = entry or {}
    return out


def line_problems(lines=None, allowed=None) -> list[str]:
    """Every way the curated copy and claims_allowed.yaml disagree, one line each."""
    lines = corpus() if lines is None else lines
    allowed = load_allowed() if allowed is None else allowed
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    for kind, key, text in lines:
        found = words_in(text)
        if not found:
            continue
        seen.add((kind, key))
        entry = allowed.get((kind, key))
        where = f"{kind} {key}"
        if entry is None:
            problems.append(f"{where}: carries {', '.join(found)} with no entry in claims_allowed.yaml "
                            f"(line {line_id(text)})")
            continue
        if entry.get("line") != line_id(text):
            problems.append(f"{where}: the line was edited since its entry was written (entry "
                            f"{entry.get('line')}, line now {line_id(text)}); re-check its basis")
        if sorted(entry.get("words") or []) != found:
            problems.append(f"{where}: entry lists {sorted(entry.get('words') or [])}, the line carries {found}")
        basis = entry.get("basis")
        if basis not in BASES:
            problems.append(f"{where}: basis {basis!r} is not one of {sorted(BASES)}")
        if not normalise(entry.get("why")):
            problems.append(f"{where}: no written reason (why)")
        if basis == "data" and entry.get("check") not in DATA_CHECKS:
            problems.append(f"{where}: a data basis must name a check in DATA_CHECKS, not {entry.get('check')!r}")
        if basis == "held" and kind != "answer":
            problems.append(f"{where}: only an answer line may be held")
    for kind, key in sorted(set(allowed) - seen):
        problems.append(f"{kind} {key}: entry in claims_allowed.yaml for a line that no longer carries a claim word")
    return problems


def check_lines() -> None:
    """Stop the build on any problem (start of stage_transform; pytest runs the same)."""
    problems = line_problems()
    if problems:
        raise ClaimError("claim check failed (sources/seeds/claims_allowed.yaml):\n  " + "\n  ".join(problems))


# ── Claims our own data must keep showing ─────────────────────────────────────
def _board_rank(boards: dict, board: str, slug: str) -> int | None:
    for e in (boards.get(board) or {}).get("entries") or []:
        if e.get("slug") == slug:
            return e.get("rank")
    return None


def _rtx(by_slug: dict, boards: dict) -> str | None:
    rtx, cap = by_slug.get("resiniferatoxin") or {}, by_slug.get("capsaicin") or {}
    if _board_rank(boards, "spiciest", "resiniferatoxin") != 1:
        return "resiniferatoxin is no longer first on the Spiciest board"
    a, b = rtx.get("scoville_shu"), cap.get("scoville_shu")
    if not a or not b or not 500 <= a / b <= 2000:
        return f"resiniferatoxin is no longer roughly a thousand times capsaicin ({a} against {b} SHU)"
    return None


def _ethanethiol(by_slug: dict, boards: dict) -> str | None:
    r = _board_rank(boards, "pungent", "ethanethiol")
    return None if r is not None and r <= 3 else f"ethanethiol is not in the Most pungent board's top three (rank {r})"


def _glucose(by_slug: dict, boards: dict) -> str | None:
    v = (by_slug.get("glucose") or {}).get("relative_sweetness")
    return None if v is not None and 0.7 <= v <= 0.8 else f"glucose's relative sweetness is {v}, not about three quarters"


def _nicotine(by_slug: dict, boards: dict) -> str | None:
    hl = [h.get("params", {}).get("half_life_hours") for h in (by_slug.get("nicotine") or {}).get("hooks") or []]
    hl = [x for x in hl if x is not None]
    return None if hl and 1.5 <= hl[0] <= 2.5 else f"nicotine's half-life is {hl}, not about two hours"


DATA_CHECKS = {
    "rtx_tops_spiciest": _rtx,
    "ethanethiol_tops_pungent": _ethanethiol,
    "glucose_three_quarters_sweet": _glucose,
    "nicotine_half_life_two_hours": _nicotine,
}


def data_problems(molecules: list[dict], boards: dict, allowed=None) -> list[str]:
    allowed = load_allowed() if allowed is None else allowed
    by_slug = {m["slug"]: m for m in molecules}
    out = []
    for (kind, key), entry in sorted(allowed.items()):
        if entry.get("basis") != "data":
            continue
        # A line ships only on its own molecule's page; with that molecule out of the catalog (a
        # test fixture, a removed row) there is no page, so nothing to hold true.
        if kind in ("why_it_matters", "editorial") and key not in by_slug:
            continue
        fn = DATA_CHECKS.get(entry.get("check"))
        err = fn(by_slug, boards) if fn else f"unknown check {entry.get('check')!r}"
        if err:
            out.append(f"{kind} {key}: {err}")
    return out


def check_data_claims(molecules: list[dict], boards: dict) -> None:
    """The export preflight: refuse a catalog that no longer shows a claim a line rests on."""
    problems = data_problems(molecules, boards)
    if problems:
        raise ClaimError("claim check failed, a line's data no longer holds (claims_allowed.yaml):\n  "
                         + "\n  ".join(problems))
