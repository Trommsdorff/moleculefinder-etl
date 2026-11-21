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
