"""Findings: facts MoleculeFinder computes from its own data and publishes as a page (2026-11-21).

THE FIRST FINDING, ``dyes-in-medicines``: of the medicine labels on the site, how many list one of
the six synthetic colour additives the FDA has asked food makers to stop using, and which. The
file is computed on every run from the labels the products stage already holds, so the weekly
refresh keeps it current and a pinned rebuild is byte-identical. Nothing in it is typed except
what the FDA said (``findings_dyes.yaml``, each statement with its link and the date it was read)
and the table of dyes (``colour_additives.yaml``), plus the hand list of familiar labels the page
names under its headline (``examples``), each checked against the table on every run.

A DYE IS A CODE. A label ingredient is one of the dyes when its UNII code is in the table, never
by its name (the label-ingredient rule). The straight dye and each lake have separate codes and
each is listed. A label ingredient whose NAME looks like a colour additive but whose code is not
in the table is listed under ``unrecognised`` (and logged), never counted: a person reads it.

WHAT IS COUNTED. Every product the run publishes whose ``kind`` is ``medicine`` and whose source
is a DailyMed label (so a held page counts exactly as it is live). The ingredient list is the
label's own, read from the cached label (every ingredient, with the code the label gives); when a
label is not in the cache the product's own page data (the matched molecules' and the other
ingredients' codes) stands in, the same codes. Per label the file keeps the dyes it lists, its
DailyMed set id, version and effective date, whether it is OTC or prescription, and the routes of
administration the label names (``dailymed.parse_routes``) when they are cached for that version.

NOT IN THE FILE: a timestamp (freshness lives in ``meta.json``), a ranking, or a word about
whether any dye is harmful or safe.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import yaml

from ..config import SEEDS_DIR
from ..sources import fda_unii, registry

log = logging.getLogger("mfetl")

COLOURS_YAML = SEEDS_DIR / "colour_additives.yaml"
FINDINGS_YAML = SEEDS_DIR / "findings_dyes.yaml"
DYES_FINDING = "dyes-in-medicines"
VERSION = 1

GROUPS = ("six", "red-3", "d-and-c")
FORMS = ("dye", "lake")
UNII_RE = fda_unii.UNII_RE
# The order the six are always listed in (alphabetical by colour, then number).
SIX_ORDER = ("blue-1", "blue-2", "green-3", "red-40", "yellow-5", "yellow-6")
# A label ingredient NAME that looks like a colour additive. Used only to find a code the table
# lacks (``unrecognised``); never to count anything.
DYE_NAME = re.compile(
    r"\bF\s?D\s?&\s?C\b|\bD\s?&\s?C\b|\b(?:ALUMINU?M) LAKE\b|\bERYTHROSIN|\bTARTRAZIN|\bALLURA\b|"
    r"\bSUNSET YELLOW\b|\bBRILLIANT BLUE\b|\bINDIGO ?(?:CARMINE|TIN)|\bFAST GREEN\b|\bPONCEAU\b|"
    r"\bAMARANTH\b|\bCARMOISINE\b|\bQUINOLINE YELLOW\b|\bPATENT BLUE\b|\bGREEN S\b", re.IGNORECASE)
SOURCE_KEYS = ("dailymed", "fda_unii", "fda", "federal_register", "curated")
# The familiar labels named under the headline: "lists" must list one of the six, "lists_none" none.
EXAMPLE_SIDES = ("lists", "lists_none")


class FindingsError(RuntimeError):
    """The findings seeds are wrong, or the data would make the finding false. Named, never skipped."""


# ── seeds ─────────────────────────────────────────────────────────────────────
def load_colours(path: Path | None = None) -> dict:
    """Read and validate colour_additives.yaml -> {"checked", "dyes", "not_counted", "by_unii"}.
    Every problem is named at once."""
    path = path or COLOURS_YAML
    data = yaml.safe_load(path.read_text()) or {}
    errors: list[str] = []
    dyes = data.get("dyes") or []
    seen_id: set[str] = set()
    by_unii: dict[str, tuple[dict, dict]] = {}
    for i, d in enumerate(dyes):
        where = f"dyes[{i}] {d.get('id') if isinstance(d, dict) else d!r}"
        if not isinstance(d, dict) or not d.get("id") or not d.get("name"):
            errors.append(f"{where}: needs id and name")
            continue
        if d["id"] in seen_id:
            errors.append(f"{where}: id used twice")
        seen_id.add(d["id"])
        if d.get("group") not in GROUPS:
            errors.append(f"{where}: group must be one of {GROUPS}")
        codes = d.get("codes") or []
        if not codes:
            errors.append(f"{where}: no codes")
        for j, c in enumerate(codes):
            u = str(c.get("unii") or "")
            if not UNII_RE.match(u):
                errors.append(f"{where}.codes[{j}]: {u!r} is not a UNII")
                continue
            if c.get("form") not in FORMS:
                errors.append(f"{where}.codes[{j}] {u}: form must be one of {FORMS}")
            if not c.get("gsrs_name") or not c.get("gsrs_status"):
                errors.append(f"{where}.codes[{j}] {u}: gsrs_name and gsrs_status are the recorded registry check")
            if u in by_unii:
                errors.append(f"{where}.codes[{j}]: {u} is already {by_unii[u][0]['id']}'s")
            by_unii[u] = (d, c)
    six = [d["id"] for d in dyes if isinstance(d, dict) and d.get("group") == "six"]
    if sorted(six) != sorted(SIX_ORDER):
        errors.append(f"the six group must be exactly the six {list(SIX_ORDER)}, not {six}")
    not_counted = data.get("not_counted") or []
    for n in not_counted:
        if not UNII_RE.match(str(n.get("unii") or "")) or not n.get("reason"):
            errors.append(f"not_counted {n!r}: needs a UNII and a reason")
        elif n["unii"] in by_unii:
            errors.append(f"not_counted {n['unii']} is also counted")
    if not data.get("checked"):
        errors.append("checked: the date the codes were read from the FDA's registry is required")
    if errors:
        raise FindingsError("colour_additives.yaml: " + "; ".join(errors))
    return {"checked": data["checked"], "dyes": dyes, "not_counted": not_counted, "by_unii": by_unii,
            "registry_url": data.get("registry_url")}


def load_statements(path: Path | None = None) -> dict:
    """Read and validate findings_dyes.yaml -> {"read", "statements", "selection"}."""
    path = path or FINDINGS_YAML
    data = yaml.safe_load(path.read_text()) or {}
    errors: list[str] = []
    seen: set[str] = set()
    for i, s in enumerate(data.get("statements") or []):
        where = f"statements[{i}] {s.get('id')}"
        for k in ("id", "date", "kind", "title", "publisher", "source", "url", "says", "quote"):
            if not s.get(k):
                errors.append(f"{where}: {k} is required")
        if s.get("id") in seen:
            errors.append(f"{where}: id used twice")
        seen.add(s.get("id"))
        if s.get("source") not in ("fda", "federal_register"):
            errors.append(f"{where}: an FDA statement comes from fda.gov or the Federal Register, not {s.get('source')!r}")
        url = str(s.get("url") or "")
        if not re.match(r"^https://(www\.)?(fda\.gov|federalregister\.gov)/", url):
            errors.append(f"{where}: {url!r} is not an fda.gov or federalregister.gov link")
    if not data.get("read"):
        errors.append("read: the date the pages were read is required")
    sel = data.get("selection") or {}
    for k in ("chosen_by", "gate", "not_by"):
        if not sel.get(k):
            errors.append(f"selection.{k} is required")
    ex = data.get("examples") or {}
    for side in EXAMPLE_SIDES:
        slugs = ex.get(side) or []
        if not isinstance(slugs, list) or not all(isinstance(x, str) and x for x in slugs):
            errors.append(f"examples.{side} must be a list of product slugs")
        elif len(set(slugs)) != len(slugs):
            errors.append(f"examples.{side} names a slug twice")
    if set(ex.get("lists") or []) & set(ex.get("lists_none") or []):
        errors.append("examples: a slug on both sides")
    if errors:
        raise FindingsError("findings_dyes.yaml: " + "; ".join(errors))
    return {"read": data["read"],
            "examples": {side: list(ex.get(side) or []) for side in EXAMPLE_SIDES},
            "statements": [{k: s[k] for k in ("id", "date", "kind", "title", "publisher", "source", "url", "says", "quote")}
                           for s in data["statements"]],
            "selection": {k: " ".join(str(sel[k]).split()) for k in ("chosen_by", "gate", "not_by")}}


# ── the finding ───────────────────────────────────────────────────────────────
def examples(labels: list[dict], wanted: dict) -> dict:
    """The familiar labels the page names under its headline, checked against this run's table.
    A slug stays only when the label is in the count and on the side the seed puts it; otherwise it
    drops out (logged, and kept under ``dropped`` with the reason), so the sentence never says what
    the table does not. Never stops a run: the sentence just names fewer labels."""
    by = {lb["slug"]: lb for lb in labels}
    out: dict = {side: [] for side in EXAMPLE_SIDES}
    dropped: list[dict] = []
    for side in EXAMPLE_SIDES:
        for slug in wanted.get(side) or []:
            lb = by.get(slug)
            if lb is None:
                why = "not a medicine label in this count"
            elif bool(lb["six"]) != (side == "lists"):
                why = "now lists one of the six" if lb["six"] else "now lists none of the six"
            else:
                out[side].append({"slug": slug, "name": lb["name"]})
                continue
            dropped.append({"slug": slug, "side": side, "why": why})
            log.warning("findings: example %s dropped from the %s sentence: %s", slug, side, why)
    out["dropped"] = dropped
    return out


def _class(doc_type: str | None) -> str:
    t = (doc_type or "").upper()
    if t.startswith("HUMAN OTC"):
        return "otc"
    if t.startswith("HUMAN PRESCRIPTION"):
        return "prescription"
    raise FindingsError(f"a medicine label of document type {doc_type!r}: neither OTC nor prescription")


def label_ingredients(product: dict, label: dict | None) -> tuple[list[dict], str]:
    """(ingredients as [{"unii", "name", "role"}], where they came from). The cached label's full
    list when there is one; else the page's own: every matched molecule's code and every other
    ingredient's code, which is the same list for a label that gives a code for each ingredient."""
    if label and not label.get("missing") and label.get("ingredients"):
        return ([{"unii": i.get("unii") or "", "name": i["name"], "role": i["role"]} for i in label["ingredients"]],
                "label")
    out = [{"unii": m.get("unii") or "", "name": m.get("listed_as") or m["slug"], "role": m["role"]}
           for m in product.get("molecules", [])]
    out += [{"unii": n.get("unii") or "", "name": n["name"], "role": n["role"]}
            for n in product.get("not_in_catalog", [])]
    return out, "page"


def _routes(routes: list[dict] | None) -> tuple[list[str] | None, str | None]:
    """(route names, how the label is taken). ``oral`` when the oral route is the only one the
    label names, ``oral+other`` when it names oral and another, ``other`` when it names no oral
    route, None when the routes are not known."""
    if routes is None:
        return None, None
    names = sorted({r["name"] for r in routes})
    if not names:
        return [], None
    if names == ["ORAL"]:
        return names, "oral"
    return names, "oral+other" if "ORAL" in names else "other"


def compile_dyes(products: list[dict], *,
                 spl: Callable[[str], dict | None],
                 routes: Callable[[str, int | None], list[dict] | None],
                 colours: dict | None = None, statements: dict | None = None) -> dict:
    """The ``dyes-in-medicines`` finding for the products a run publishes (see the module docstring)."""
    colours = load_colours() if colours is None else colours
    statements = load_statements() if statements is None else statements
    for key in SOURCE_KEYS:
        if not registry.may_display(key):
            raise registry.LicenceRuleError(f"findings cite source {key!r}, which is unregistered or may not be displayed")
    by_unii = colours["by_unii"]
    skip = {n["unii"] for n in colours["not_counted"]}
    group_of = {d["id"]: d["group"] for d in colours["dyes"]}

    labels: list[dict] = []
    unrecognised: list[dict] = []
    from_page = 0
    for p in sorted((p for p in products if p.get("kind") == "medicine"
                     and (p.get("source") or {}).get("type") == "dailymed"), key=lambda x: x["slug"]):
        src = p["source"]
        label = spl(src["setid"])
        ings, origin = label_ingredients(p, label)
        from_page += origin == "page"
        found: dict[str, dict] = {}
        for ing in ings:
            u = ing["unii"]
            if u in by_unii:
                d, c = by_unii[u]
                found.setdefault(u, {"unii": u, "dye": d["id"], "form": c["form"], "listed_as": ing["name"]})
            elif DYE_NAME.search(ing["name"]) and u not in skip:
                unrecognised.append({"slug": p["slug"], "name": ing["name"], "unii": u or None})
        hits = sorted(found.values(), key=lambda h: (h["dye"], h["form"], h["unii"]))
        ids = {h["dye"] for h in hits}
        names, how = _routes(routes(src["setid"], src.get("version")))
        labels.append({
            "slug": p["slug"], "name": p["name"], "class": _class(src.get("doc_type")),
            "labeler": src.get("labeler"), "setid": src["setid"], "version": src.get("version"),
            "effective": src.get("effective"), "url": src["url"],
            "routes": names, "taken": how,
            "six": [i for i in SIX_ORDER if i in ids],
            "red_3": "red-3" in ids,
            "d_and_c": sorted(i for i in ids if group_of[i] == "d-and-c"),
            "codes": hits,
        })
    labels.sort(key=lambda lb: (lb["name"].lower(), lb["slug"]))
    if unrecognised:
        log.warning("findings: %d label ingredient(s) look like a colour additive but carry a code "
                    "colour_additives.yaml does not list (not counted): %s", len(unrecognised),
                    "; ".join(f"{u['slug']}: {u['name']} ({u['unii']})" for u in unrecognised[:8]))
    if from_page:
        log.info("findings: %d label(s) counted from the page's own data (label not in the cache)", from_page)

    def n(rows): return len(rows)
    def split(rows):
        return {"labels": n(rows), "otc": sum(lb["class"] == "otc" for lb in rows),
                "prescription": sum(lb["class"] == "prescription" for lb in rows)}
    any_six = [lb for lb in labels if lb["six"]]
    totals: dict = {
        "labels": split(labels),
        "any_of_six": split(any_six),
        "two_or_more": split([lb for lb in labels if len(lb["six"]) >= 2]),
        "three_or_more": split([lb for lb in labels if len(lb["six"]) >= 3]),
        "red_3": {**split([lb for lb in labels if lb["red_3"]]), "slugs": [lb["slug"] for lb in labels if lb["red_3"]]},
        "d_and_c_any": split([lb for lb in labels if lb["d_and_c"]]),
        "by_dye": {i: split([lb for lb in labels if i in lb["six"]]) for i in SIX_ORDER},
        "d_and_c_by_dye": {d["id"]: split([lb for lb in labels if d["id"] in lb["d_and_c"]])
                           for d in colours["dyes"] if d["group"] == "d-and-c"},
    }
    # The routes the labels name. A label whose routes are not cached for the edition of it the
    # page shows counts as "unstated" (a pinned build can hold a label one edition behind DailyMed);
    # the weekly refresh reads both together and the count falls to the labels that name no route.
    known = [lb for lb in labels if lb["routes"] is not None]
    if known:
        def route_split(rows):
            c = Counter(lb["taken"] or "unstated" for lb in rows)
            return {k: c.get(k, 0) for k in ("oral", "oral+other", "other", "unstated")}
        totals["routes"] = {"read": len(known), "all": route_split(labels), "any_of_six": route_split(any_six),
                            "red_3": route_split([lb for lb in labels if lb["red_3"]])}
    else:
        totals["routes"] = None

    # What the page says about the choice of labels, with its own numbers computed here.
    actives_all = sum(1 for p in products if p.get("kind") == "medicine" and (p.get("source") or {}).get("type") == "dailymed"
                      and not p.get("actives_not_in_catalog"))
    selection = {**statements["selection"], "labels": n(labels), "every_active_is_a_molecule": actives_all}

    def dye_row(d):
        return {"id": d["id"], "name": d["name"], "group": d["group"],
                "codes": [{k: c[k] for k in ("unii", "form", "gsrs_name", "gsrs_status")} for c in d["codes"]]}
    return {
        "id": DYES_FINDING, "version": VERSION,
        "question": "Which medicine labels on MoleculeFinder list one of the six synthetic colour additives the FDA has asked food makers to stop using?",
        "totals": totals,
        "dyes": [dye_row(d) for d in colours["dyes"]],
        "not_counted": colours["not_counted"],
        "registry": {"checked": colours["checked"], "url": colours.get("registry_url"),
                     "name": "FDA Global Substance Registration System (GSRS)"},
        "labels": labels,
        "examples": examples(labels, statements.get("examples") or {}),
        "unrecognised": unrecognised,
        "fda": {"read": statements["read"], "statements": statements["statements"]},
        "selection": selection,
        "sources": list(SOURCE_KEYS),
        "license": "CC0 1.0",
    }


# ══ THE SECOND FINDING, ``inactive-ingredients`` (2026-11-22) ══════════════════
# Across the same medicine labels, which inactive ingredients the labels list, grouped by FDA code.
# A group is a hand-seeded set of UNII codes (``inactive_groups.yaml``, each code checked against
# the FDA's registry), or a colour of ``colour_additives.yaml`` (each dye with its lake, as the dyes
# finding counts it), or, for any other code, the code on its own under the FDA's name for it. So
# every inactive ingredient a label lists is in exactly one group and nothing is dropped; grouping
# only ever joins codes. Counted from the label's own list (or the page's own data when the label
# is not cached: the same codes), inactive role only. The groups at least one in ten labels list are
# the ones the page charts (``shown``); the rest are in the per-label table. Every total is computed
# here; nothing in the file is typed except the seed's names and notes.

INACTIVE_YAML = SEEDS_DIR / "inactive_groups.yaml"
INACTIVE_FINDING = "inactive-ingredients"
INACTIVE_VERSION = 1
# A group is shown (charted) when at least SHOWN_IN_TEN labels in every ten list it.
SHOWN_IN_TEN = 1
INACTIVE_SOURCE_KEYS = ("dailymed", "fda_unii", "curated")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CODE_GROUP = "code-"                       # the id prefix of a group that is one code on its own
COLOUR_MEMBER = {"dye": "the straight dye", "lake": "its lake"}


def load_inactive_groups(path: Path | None = None, colours: dict | None = None) -> dict:
    """Read and validate inactive_groups.yaml -> {"checked", "registry_url", "pages", "groups",
    "kept_apart", "by_unii"}. A code may be in one group only, never also a colour's or kept apart.
    Every problem is named at once."""
    path = path or INACTIVE_YAML
    colours = load_colours() if colours is None else colours
    data = yaml.safe_load(path.read_text()) or {}
    errors: list[str] = []
    groups = data.get("groups") or []
    ids: set[str] = set()
    by_unii: dict[str, tuple[dict, dict]] = {}
    colour_ids = {d["id"] for d in colours["dyes"]}
    for i, g in enumerate(groups):
        where = f"groups[{i}] {g.get('id') if isinstance(g, dict) else g!r}"
        if not isinstance(g, dict) or not all(g.get(k) for k in ("id", "name", "phrase", "codes")):
            errors.append(f"{where}: needs id, name, phrase and codes")
            continue
        if not SLUG_RE.match(g["id"]) or g["id"].startswith(CODE_GROUP) or g["id"] in colour_ids:
            errors.append(f"{where}: id must be a slug, not start {CODE_GROUP!r} and not be a colour's id")
        if g["id"] in ids:
            errors.append(f"{where}: id used twice")
        ids.add(g["id"])
        if g.get("watch"):
            try:
                re.compile(g["watch"])
            except re.error as e:
                errors.append(f"{where}: watch is not a pattern ({e})")
        for j, c in enumerate(g["codes"]):
            u = str(c.get("unii") or "")
            if not UNII_RE.match(u):
                errors.append(f"{where}.codes[{j}]: {u!r} is not a UNII")
                continue
            if not c.get("member") or not c.get("gsrs_name") or not c.get("gsrs_status"):
                errors.append(f"{where}.codes[{j}] {u}: member, gsrs_name and gsrs_status are required")
            if u in by_unii:
                errors.append(f"{where}.codes[{j}]: {u} is already {by_unii[u][0]['id']}'s")
            if u in colours["by_unii"]:
                errors.append(f"{where}.codes[{j}]: {u} is a colour in colour_additives.yaml")
            by_unii[u] = (g, c)
    kept = data.get("kept_apart") or []
    for k in kept:
        u = str(k.get("unii") or "")
        if not UNII_RE.match(u) or not k.get("reason") or not k.get("gsrs_name") or not k.get("gsrs_status"):
            errors.append(f"kept_apart {k!r}: needs a UNII, gsrs_name, gsrs_status and a reason")
        elif u in by_unii or u in colours["by_unii"]:
            errors.append(f"kept_apart {u} is also in a group")
        if k.get("near") not in ids:
            errors.append(f"kept_apart {u}: near must be a group id, not {k.get('near')!r}")
    if len({k.get("unii") for k in kept}) != len(kept):
        errors.append("kept_apart names a code twice")
    pages = data.get("pages") or []
    for p in pages:
        if p not in ids:
            errors.append(f"pages: {p!r} is not a group id")
    if not data.get("checked"):
        errors.append("checked: the date the codes were read from the FDA's registry is required")
    if errors:
        raise FindingsError("inactive_groups.yaml: " + "; ".join(errors))
    return {"checked": data["checked"], "registry_url": data.get("registry_url"), "pages": list(pages),
            "groups": groups, "kept_apart": kept, "by_unii": by_unii}


def _selection(products: list[dict], statements: dict, labels: int) -> dict:
    """What a findings page says about the choice of labels, with its numbers computed here."""
    actives_all = sum(1 for p in products if p.get("kind") == "medicine" and (p.get("source") or {}).get("type") == "dailymed"
                      and not p.get("actives_not_in_catalog"))
    return {**statements["selection"], "labels": labels, "every_active_is_a_molecule": actives_all}


_GREEK = re.compile(r"\.(ALPHA|BETA|GAMMA|DELTA|OMEGA)\.", re.IGNORECASE)


def registry_words(name: str) -> str:
    """An FDA registry name as a page prints it among other ingredients: lower case, its notation
    in words (".ALPHA." -> "alpha", ".MU.M" -> "micrometres"), a colour's "D&C"/"FD&C" kept."""
    s = _GREEK.sub(lambda m: m.group(1).lower(), name)
    s = re.sub(r"\.MU\.M\b", " micrometres", s, flags=re.IGNORECASE).lower()
    return re.sub(r"\b(fd&c|d&c)\b", lambda m: m.group(1).upper(), " ".join(s.split()))


def compile_inactive(products: list[dict], *,
                     spl: Callable[[str], dict | None],
                     routes: Callable[[str, int | None], list[dict] | None],
                     fda_name: Callable[[str], str | None] | None = None,
                     groups: dict | None = None, colours: dict | None = None,
                     statements: dict | None = None) -> dict:
    """The ``inactive-ingredients`` finding for the products a run publishes (see the block above).
    ``fda_name`` gives the FDA UNII table's name for a code (a code in no seeded group is named by
    it); without it, or for a code the table lacks, the label's own words name it."""
    colours = load_colours() if colours is None else colours
    groups = load_inactive_groups(colours=colours) if groups is None else groups
    statements = load_statements() if statements is None else statements
    for key in INACTIVE_SOURCE_KEYS:
        if not registry.may_display(key):
            raise registry.LicenceRuleError(f"findings cite source {key!r}, which is unregistered or may not be displayed")
    seeded = groups["by_unii"]
    kept = {k["unii"] for k in groups["kept_apart"]}
    watches = [(g["id"], re.compile(g["watch"], re.IGNORECASE)) for g in groups["groups"] if g.get("watch")]

    def group_of(u: str) -> str:
        if u in seeded:
            return seeded[u][0]["id"]
        if u in colours["by_unii"]:
            return colours["by_unii"][u][0]["id"]
        return CODE_GROUP + u.lower()

    labels: list[dict] = []
    unrecognised: dict[tuple[str, str], dict] = {}
    listed: dict[str, Counter] = {}           # code -> the label's own words for it, counted
    molecules: dict[str, set[str]] = {}       # code -> the molecule pages it matched to
    uncoded = 0
    for p in sorted((p for p in products if p.get("kind") == "medicine"
                     and (p.get("source") or {}).get("type") == "dailymed"), key=lambda x: x["slug"]):
        src = p["source"]
        ings, _origin = label_ingredients(p, spl(src["setid"]))
        for m in p.get("molecules", []):
            if m.get("role") == "inactive" and m.get("unii"):
                molecules.setdefault(m["unii"], set()).add(m["slug"])
        seen: dict[str, dict] = {}
        for ing in ings:
            if ing["role"] != "inactive":
                continue
            u = ing["unii"]
            if not u:
                uncoded += 1
                continue
            if u in seen:
                continue
            name = " ".join(str(ing["name"]).split())
            listed.setdefault(u, Counter())[name.upper()] += 1
            seen[u] = {"unii": u, "listed_as": name, "group": group_of(u)}
            if u not in seeded and u not in colours["by_unii"] and u not in kept:
                for gid, pat in watches:
                    if pat.search(name):
                        unrecognised.setdefault((u, gid), {"unii": u, "name": name, "looks_like": gid, "slugs": []})["slugs"].append(p["slug"])
        rows = sorted(seen.values(), key=lambda r: r["unii"])
        names, how = _routes(routes(src["setid"], src.get("version")))
        labels.append({
            "slug": p["slug"], "name": p["name"], "class": _class(src.get("doc_type")),
            "labeler": src.get("labeler"), "setid": src["setid"], "version": src.get("version"),
            "effective": src.get("effective"), "url": src["url"],
            "routes": names, "taken": how,
            "groups": sorted({r["group"] for r in rows}),
            "codes": [r["unii"] for r in rows],
        })
    labels.sort(key=lambda lb: (lb["name"].lower(), lb["slug"]))
    if unrecognised:
        log.warning("findings: %d inactive code(s) look like a group's by name but are in no group and not kept apart "
                    "(counted on their own): %s", len(unrecognised),
                    "; ".join(f"{u['unii']} {u['name']} (like {u['looks_like']})" for u in list(unrecognised.values())[:8]))

    def by_mouth(lb): return lb["taken"] in ("oral", "oral+other")
    def split(rows):
        return {"labels": len(rows), "otc": sum(lb["class"] == "otc" for lb in rows),
                "prescription": sum(lb["class"] == "prescription" for lb in rows),
                "by_mouth": sum(by_mouth(lb) for lb in rows)}
    total = len(labels)
    with_group: dict[str, list[dict]] = {}
    with_code: Counter = Counter()
    for lb in labels:
        for g in lb["groups"]:
            with_group.setdefault(g, []).append(lb)
        for u in lb["codes"]:
            with_code[u] += 1

    def code_row(u: str, member: str, gsrs_name: str | None, gsrs_status: str | None, form: str | None = None) -> dict:
        row = {"unii": u, "member": member, "gsrs_name": gsrs_name, "gsrs_status": gsrs_status, "labels": with_code[u]}
        if form:
            row["form"] = form
        return row

    def common_words(u: str) -> str:
        c = listed.get(u) or Counter()
        return min(c.items(), key=lambda kv: (-kv[1], kv[0]))[0] if c else u

    def mols(codes: list[str]) -> list[str]:
        return sorted(set().union(*(molecules.get(u, set()) for u in codes))) if codes else []

    out_groups: list[dict] = []
    for g in groups["groups"]:
        codes = [c["unii"] for c in g["codes"]]
        out_groups.append({"id": g["id"], "kind": "group", "name": g["name"], "phrase": g["phrase"], "note": g.get("note"),
                           "codes": [code_row(c["unii"], c["member"], c["gsrs_name"], c["gsrs_status"]) for c in g["codes"]],
                           "molecules": mols(codes), **split(with_group.get(g["id"], []))})
    for d in colours["dyes"]:
        codes = [c["unii"] for c in d["codes"]]
        out_groups.append({"id": d["id"], "kind": "colour", "name": d["name"], "phrase": d["name"], "note": None,
                           "codes": [code_row(c["unii"], COLOUR_MEMBER[c["form"]], c["gsrs_name"], c["gsrs_status"], c["form"])
                                     for c in d["codes"]],
                           "molecules": mols(codes), **split(with_group.get(d["id"], []))})
    for gid in sorted(g for g in with_group if g.startswith(CODE_GROUP)):
        u = gid[len(CODE_GROUP):].upper()
        official = fda_name(u) if fda_name else None
        words = registry_words(official or common_words(u))
        out_groups.append({"id": gid, "kind": "code", "name": words[:1].upper() + words[1:], "phrase": words, "note": None,
                           "codes": [code_row(u, words, official, None)],
                           "molecules": mols([u]), **split(with_group[gid])})
    floor = -(-total * SHOWN_IN_TEN // 10)          # at least one label in ten: ceil(total / 10)
    order = sorted(out_groups, key=lambda g: (-g["labels"], g["name"].lower(), g["id"]))
    shown = [g["id"] for g in order if total and g["labels"] >= floor]
    for g in out_groups:
        g["shown"] = g["id"] in shown
    out_groups.sort(key=lambda g: (-g["labels"], g["name"].lower(), g["id"]))

    none = [lb for lb in labels if not lb["codes"]]
    known = [lb for lb in labels if lb["routes"] is not None]
    totals = {
        "labels": split(labels),
        "lists_none": {**split(none), "slugs": [lb["slug"] for lb in none]},
        "codes": len(with_code),
        "groups": len(with_group),
        "uncoded": uncoded,
        "shown": {"floor": floor, "in_ten": SHOWN_IN_TEN, "groups": shown},
        "routes_read": len(known),
    }
    kept_rows = [{**{k: x[k] for k in ("unii", "near", "gsrs_name", "gsrs_status", "reason")},
                  "arguable": bool(x.get("arguable")), "labels": with_code[x["unii"]],
                  "group": group_of(x["unii"])} for x in groups["kept_apart"]]
    return {
        "id": INACTIVE_FINDING, "version": INACTIVE_VERSION,
        "question": "Which inactive ingredients do the medicine labels on MoleculeFinder list, and which labels list each?",
        "totals": totals,
        "pages": groups["pages"],
        "groups": out_groups,
        "kept_apart": kept_rows,
        "registry": {"checked": groups["checked"], "url": groups.get("registry_url"),
                     "name": "FDA Global Substance Registration System (GSRS)"},
        "labels": labels,
        "unrecognised": sorted(({**u, "slugs": sorted(u["slugs"])} for u in unrecognised.values()),
                               key=lambda u: (u["unii"], u["looks_like"])),
        "selection": _selection(products, statements, total),
        "sources": list(INACTIVE_SOURCE_KEYS),
        "license": "CC0 1.0",
    }


# ── the run's report ──────────────────────────────────────────────────────────
def summary_lines(name: str, f: dict, state: str) -> list[str]:
    """The log and weekly-summary lines for one finding rebuilt (``state``: new, changed or unchanged
    from the shipped file). Words only: a finding never stops a run."""
    t = f["totals"]
    if name == DYES_FINDING:
        ex = f.get("examples") or {}
        line = (f"{name}: rebuilt ({state} from the shipped file): {t['any_of_six']['labels']} of the "
                f"{t['labels']['labels']} medicine labels list one of the six; familiar labels named "
                f"{len(ex.get('lists') or [])} and {len(ex.get('lists_none') or [])}, "
                f"{len(ex.get('dropped') or [])} left out")
        return [line] + [f"{name}: {d['slug']} left out of the {d['side']} sentence: {d['why']}" for d in ex.get("dropped") or []]
    if name == INACTIVE_FINDING:
        by = {g["id"]: g for g in f["groups"]}
        pages = ", ".join(f"{by[p]['phrase']} {by[p]['labels']}" for p in f.get("pages") or [] if p in by)
        un = f.get("unrecognised") or []
        line = (f"{name}: rebuilt ({state} from the shipped file): {t['labels']['labels']} medicine labels, "
                f"{t['codes']} inactive codes in {t['groups']} groups, {len(t['shown']['groups'])} listed by at least "
                f"{t['shown']['floor']} labels; {pages}; {len(un)} code(s) look like a group's and are in none")
        return [line] + [f"{name}: {u['unii']} {u['name']} looks like {u['looks_like']} and is counted on its own "
                         f"({len(u['slugs'])} label(s)); add it to inactive_groups.yaml or kept_apart" for u in un]
    return [f"{name}: rebuilt ({state} from the shipped file)"]
