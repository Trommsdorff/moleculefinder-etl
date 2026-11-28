"""One rule for "over the counter", "prescription" or both (brief ../TRUST-3C-STATUS-AND-ROUNDING-PROMPT.md, 2026-11-27).

A medicine's page says one of three lines: "Sold over the counter, without a prescription.", "Dispensed on
prescription, not sold on a shelf." or "Sold over the counter in some products and on prescription in others."
Until this run the line came from the molecule's group (its scope bucket) and, since 2026-11-27, from a web function
reading the labels and the licence record. Now the rule is written ONCE, here, as data: every medicine's record carries
``medicine_status``, the line it supports and the evidence for each side, and the page (web ``lib/molecule-page.ts``)
and the one-fact review (``review/facts.py``) both read it, so the site and its checker cannot disagree.

THE RULE
* **The over-the-counter side holds** when the record has a current FDA over-the-counter basis: its licence record
  read from Drugs@FDA as a product marketed over the counter; an FDA OTC monograph the molecule is an active
  ingredient of (``approvals.yaml``); a DailyMed label of the HUMAN OTC DRUG kind that the molecule is an active
  ingredient of, for a product marketed today under an NDA, an ANDA, a BLA or an OTC monograph; or a Drugs@FDA
  application or DailyMed label recorded for the purpose in ``status_bases.yaml``.
* **The prescription side holds** when the record has a current prescription marketing authorisation for human use:
  its licence record read from Drugs@FDA as a product marketed on prescription; a DailyMed label of the HUMAN
  PRESCRIPTION DRUG kind it is an active of, for a product marketed today under an NDA, an ANDA or a BLA; or one
  recorded in ``status_bases.yaml``. **An unapproved drug's label (marketing category "unapproved drug other" and the
  like) counts for neither side**: it is not a marketing authorisation. Nor does a label whose every product's
  marketing has ended.
* Both hold: "both". One holds: that one. Neither: the molecule is UNSETTLED; its page keeps its group's line, and the
  run lists it. A licence read from the EMA, the MHRA or another national register carries no over-the-counter or
  prescription status in the record, so on its own it settles neither side.
* **The hand-made OTC list is not evidence by itself** (``otc_allowlist.yaml``): every molecule on it must have an
  over-the-counter basis above, or the build stops and names it. A molecule listed only for what it is taken for (its
  use hub) sits under the file's ``uses_only:`` key, which makes no over-the-counter claim. ``status_bases.yaml``'s
  ``unsettled:`` key names a molecule whose two sides could not be settled from primary sources: its page is left as
  it is and every run reports it.

* **The fourth outcome, "unapproved"** (2026-11-28, Garrett's ruling, brief ../TRUST-5-SOURCE-CHECK-PROMPT.md section
  D): ONLY for a ruled exception recorded as marketed unapproved (approvals.yaml ``exception:``, read through
  ``relationships.ruled_exceptions``; today phenazopyridine). Its page says "Sold in the United States without FDA
  approval." and its evidence is the DailyMed label the exception names (at the edition the build holds), with the
  marketing category quoted as the label states it. If that label is not an active ingredient label of the record, its
  marketing is not read, a product on it is marketed today under anything but the recorded unapproved category, or the
  record has gained an over-the-counter or prescription basis, the line is NOT the fourth one: the molecule falls back
  to unsettled (its group's line), the reason is logged and written in the run's report, and the source review's check
  3 reports it the next morning. The weekly run never stops for it. A molecule with no basis and no recorded exception
  is unsettled, as before. Its ``is_otc`` is left as it is.

``is_otc`` follows the rule: for every medicine and every molecule on the OTC list it is True exactly when the
over-the-counter side holds.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable

import yaml

from ..config import SEEDS_DIR
from . import relationships

log = logging.getLogger("mfetl")

STATUS_BASES_YAML = SEEDS_DIR / "status_bases.yaml"
MEDICINE_BUCKETS = ("otc-medicine", "prescription-medicine")
GROUP_STATUS = {"otc-medicine": "otc", "prescription-medicine": "prescription"}

# DailyMed marketing categories (SPL approval/code displayName, upper case) that are a marketing authorisation.
RX_CATEGORIES = frozenset({"NDA", "ANDA", "BLA", "NDA AUTHORIZED GENERIC"})
OTC_CATEGORIES = RX_CATEGORIES | frozenset({"OTC MONOGRAPH DRUG", "OTC MONOGRAPH FINAL", "OTC MONOGRAPH NOT FINAL"})

DRUGS_AT_FDA = "Drugs@FDA"
FDA_OVERVIEW = "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={appl}"
DAILYMED_LABEL = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"
_SETID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_APPLICATION = re.compile(r"^(NDA|ANDA|BLA) \d{6}$")
_STATUS_WORDS = {"otc": "Over-the-counter", "prescription": "Prescription"}


class StatusError(SystemExit):
    """The status rule refused the build: an OTC-list entry with no basis, or a bad status_bases.yaml entry."""


UNAPPROVED = "unapproved"          # the fourth outcome: a ruled exception marketed with no authorisation


def exception_evidence(slug: str, ex: dict, rec: dict, labels: dict[str, dict],
                       marketing: Callable[[str, int | None], list[dict] | None]) -> tuple[dict | None, str | None]:
    """(the evidence the page shows, the reason it cannot be used) for a ruled exception marketed unapproved."""
    lab = ex.get("label") or {}
    setid = lab.get("setid")
    mine = [p for p in rec.get("products") or [] if p.get("role") == "active"
            and ((labels.get(p.get("slug")) or {}).get("source") or {}).get("setid") == setid]
    if not mine:
        return None, f"the label {setid} it names is not one of the record's active ingredient labels"
    prod = labels[mine[0]["slug"]]
    src = prod.get("source") or {}
    read = marketing(setid, src.get("version"))
    if read is None:
        return None, f"the label {setid}'s marketing category is not read"
    current = [p for p in read if p.get("status") == "active"]
    cats = sorted({(p.get("category") or "").upper() for p in current})
    if not current or any(not c.startswith("UNAPPROVED") for c in cats) or str(lab.get("category")).upper() not in cats:
        return None, (f"the label {setid} is marketed today as {', '.join(c.lower() for c in cats) or 'nothing'}, "
                      f"not as {lab.get('category')!r}: read the exception again")
    ev = {"kind": "label", "register": "DailyMed", "product": prod.get("name"), "slug": prod.get("slug"),
          "setid": setid, "version": src.get("version"), "category": str(lab["category"]),
          "source": src.get("url") or DAILYMED_LABEL.format(setid=setid)}
    return {"ruled": ex.get("ruled"), "by": ex.get("by"), "label": ev}, None


def decide(otc: list, prescription: list) -> str | None:
    """The three outcomes, or None when neither side has a basis (unsettled)."""
    if otc and prescription:
        return "both"
    if otc:
        return "otc"
    if prescription:
        return "prescription"
    return None


# ── the evidence, side by side ────────────────────────────────────────────────────────────────────
def licence_side(approval: dict | None) -> tuple[str | None, dict | None]:
    """The side the molecule's licence record supports: a Drugs@FDA product marketed over the counter or on
    prescription, or an FDA OTC monograph (approvals.yaml). Anything else (the EMA, the MHRA, a national
    register, a ruling) records no status: (None, None)."""
    a = approval or {}
    basis = a.get("basis") or ""
    application = a.get("application") or ""
    if a.get("register") == DRUGS_AT_FDA:
        side = "otc" if "(over-the-counter)" in basis else "prescription" if "(prescription)" in basis else None
        if side:
            return side, {k: v for k, v in (("kind", "licence"), ("register", DRUGS_AT_FDA), ("application", application),
                                            ("product", a.get("product")), ("source", a.get("source")),
                                            ("read", a.get("read"))) if v}
    if application.startswith("OTC Monograph ") and "FDA OTC monograph" in basis:
        return "otc", {k: v for k, v in (("kind", "monograph"), ("register", "OTC Monographs@FDA"),
                                         ("application", application), ("source", a.get("source"))) if v}
    return None, None


def label_side(product: dict, marketing: list[dict] | None) -> tuple[str | None, dict | None, str | None]:
    """(side, evidence, reason it does not count) for one DailyMed label the molecule is an active ingredient of."""
    src = product.get("source") or {}
    doc = (src.get("doc_type") or "").upper()
    side = "otc" if "OTC" in doc and "DRUG" in doc else "prescription" if "PRESCRIPTION" in doc and "DRUG" in doc else None
    if side is None:
        return None, None, None                                   # not a drug label: no status either way
    if marketing is None:
        return None, None, "its marketing category is not read"
    allowed = OTC_CATEGORIES if side == "otc" else RX_CATEGORIES
    current = [p for p in marketing if p.get("status") == "active"]
    if not current:
        return None, None, "no product on it is marketed today"
    ok = [p for p in current if p.get("category") in allowed]
    if not ok:
        cats = sorted({p.get("category") or "no category" for p in current})
        return None, None, f"marketed as {', '.join(c.lower() for c in cats)}, not under a marketing authorisation"
    first = ok[0]
    ev = {"kind": "label", "register": "DailyMed", "product": product.get("name"), "slug": product.get("slug"),
          "setid": src.get("setid"), "version": src.get("version"), "category": first.get("category"),
          "application": first.get("application") or None, "source": src.get("url") or DAILYMED_LABEL.format(setid=src.get("setid"))}
    return side, {k: v for k, v in ev.items() if v is not None}, None


# ── status_bases.yaml: bases recorded from the primary source, and the unsettled ────────────────────
_APP_FIELDS = {"kind", "application", "product", "holder", "form", "status", "read"}
_LABEL_FIELDS = {"kind", "setid", "version", "product", "labeler", "category", "status", "read"}


def load_recorded(path=STATUS_BASES_YAML) -> tuple[dict[str, dict[str, list[dict]]], dict[str, str]]:
    """({slug: {"otc": [evidence], "prescription": [evidence]}}, {slug: why it is unsettled}). Every problem is
    named at once; an unknown field, a missing one, an application not written "NDA 012345", a status that is not
    the side's, a set id that is not one, a date not written YYYY-MM-DD: the build stops."""
    if not path.exists():
        return {}, {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, dict[str, list[dict]]] = {}
    unsettled = {str(k): str(v) for k, v in (data.pop("unsettled", None) or {}).items()}
    problems: list[str] = []
    for slug, sides in data.items():
        out.setdefault(str(slug), {})
        for side, entries in (sides or {}).items():
            if side not in ("otc", "prescription"):
                problems.append(f"{slug}: unknown side {side!r}")
                continue
            for e in entries or []:
                e = dict(e or {})
                kind = e.get("kind")
                fields = _APP_FIELDS if kind == "application" else _LABEL_FIELDS if kind == "label" else None
                if fields is None:
                    problems.append(f"{slug} {side}: kind must be application or label, not {kind!r}")
                    continue
                extra, missing = sorted(set(e) - fields), sorted(f for f in fields - {"holder", "form", "labeler"} if not e.get(f))
                if extra:
                    problems.append(f"{slug} {side}: unknown field(s) {extra}")
                if missing:
                    problems.append(f"{slug} {side}: missing {missing}")
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(e.get("read") or "")):
                    problems.append(f"{slug} {side}: read must be YYYY-MM-DD")
                if kind == "application":
                    if not _APPLICATION.match(str(e.get("application") or "")):
                        problems.append(f"{slug} {side}: application must read 'NDA 012345', 'ANDA ...' or 'BLA ...'")
                    if e.get("status") != _STATUS_WORDS[side]:
                        problems.append(f"{slug} {side}: Drugs@FDA marketing status must be {_STATUS_WORDS[side]!r}")
                    if problems:
                        continue
                    ev = {"kind": "application", "register": DRUGS_AT_FDA, "application": e["application"],
                          "product": e["product"], "holder": e.get("holder"), "form": e.get("form"),
                          "source": FDA_OVERVIEW.format(appl=e["application"].split()[1]), "read": str(e["read"])}
                else:
                    if not _SETID.match(str(e.get("setid") or "")):
                        problems.append(f"{slug} {side}: not a DailyMed set id: {e.get('setid')!r}")
                    if not isinstance(e.get("version"), int):
                        problems.append(f"{slug} {side}: version must be the label's version number")
                    allowed = OTC_CATEGORIES if side == "otc" else RX_CATEGORIES
                    if str(e.get("category") or "").upper() not in allowed:
                        problems.append(f"{slug} {side}: category {e.get('category')!r} is not a marketing authorisation for this side")
                    if e.get("status") != "active":
                        problems.append(f"{slug} {side}: the label's marketing status must be active")
                    if problems:
                        continue
                    ev = {"kind": "label", "register": "DailyMed", "product": e["product"], "labeler": e.get("labeler"),
                          "setid": e["setid"], "version": e["version"], "category": str(e["category"]).upper(),
                          "source": DAILYMED_LABEL.format(setid=e["setid"]), "read": str(e["read"])}
                out.setdefault(str(slug), {}).setdefault(side, []).append({k: v for k, v in ev.items() if v})
    if problems:
        raise StatusError("status_bases.yaml refused:\n  " + "\n  ".join(problems))
    return out, unsettled


# ── the rule over the catalog ─────────────────────────────────────────────────────────────────────
def bases(rec: dict, labels: dict[str, dict], marketing: Callable[[str, int | None], list[dict] | None],
          recorded: dict[str, list[dict]] | None = None) -> tuple[dict[str, list[dict]], list[str]]:
    """({"otc": [...], "prescription": [...]}, the labels that did not count and why) for one record."""
    sides: dict[str, list[dict]] = {"otc": [], "prescription": []}
    skipped: list[str] = []
    side, ev = licence_side(rec.get("approval"))
    if side:
        sides[side].append(ev)
    for side, evs in (recorded or {}).items():
        sides[side].extend(evs)
    for p in rec.get("products") or []:
        if p.get("role") != "active":
            continue
        prod = labels.get(p.get("slug"))
        if not prod or (prod.get("source") or {}).get("type") != "dailymed":
            continue
        src = prod["source"]
        side, ev, why = label_side(prod, marketing(src.get("setid"), src.get("version")))
        if side:
            sides[side].append(ev)
        elif why:
            skipped.append(f"the {prod.get('name')} label ({why})")
    return sides, skipped


def attach(molecules: list[dict], products: list[dict], marketing: Callable[[str, int | None], list[dict] | None],
           listed: set[str], uses_only: set[str], path=STATUS_BASES_YAML) -> dict:
    """Write ``medicine_status`` on every medicine and set ``is_otc`` by the rule (see the module docstring).
    ``listed``: the slugs the OTC list names; ``uses_only``: the slugs it names for their use alone. Refuses the build
    (StatusError) on an OTC-list entry with no over-the-counter basis, or a status_bases.yaml entry for an unknown slug.
    Returns the run's report: each medicine's status, the unsettled, and the labels that did not count."""
    recorded, unsettled = load_recorded(path)
    unapproved = {s: e for s, e in relationships.ruled_exceptions().items() if e.get("marketed") == UNAPPROVED}
    labels = {p["slug"]: p for p in products}
    by_slug = {m["slug"]: m for m in molecules}
    unknown = sorted(s for s in [*recorded, *unsettled] if s not in by_slug)
    if unknown:
        raise StatusError("status_bases.yaml names molecule(s) the catalog does not hold: " + ", ".join(unknown))
    both_ways = sorted(set(unapproved) & (set(unsettled) | set(recorded)))
    if both_ways:
        raise StatusError("a ruled exception marketed unapproved is also in status_bases.yaml: " + ", ".join(both_ways))
    report: dict = {"status": {}, "unsettled": {}, "not_counted": {}, "exceptions": {}}
    no_basis: list[str] = []
    for m in molecules:
        slug = m["slug"]
        medicine = m.get("scope_bucket") in MEDICINE_BUCKETS
        on_list = slug in listed
        if not (medicine or on_list or slug in recorded or slug in uses_only):
            m.pop("medicine_status", None)
            continue
        sides, skipped = bases(m, labels, marketing, recorded.get(slug))
        if skipped:
            report["not_counted"][slug] = skipped
        status = decide(sides["otc"], sides["prescription"])
        if slug in unapproved and medicine:
            ev, why = (None, f"it now has a basis ({status}): read the exception again") if status is not None else \
                exception_evidence(slug, unapproved[slug], m, labels, marketing)
            if ev:
                m["medicine_status"] = {"status": UNAPPROVED, "otc": [], "prescription": [], "exception": ev}
                report["status"][slug] = UNAPPROVED
                report["exceptions"][slug] = f"ruled {ev['ruled']}: the {ev['label']['product']} label, {ev['label']['category']}"
                continue                               # is_otc left as it is
            log.warning("  status: the ruled exception %s is NOT given the fourth line: %s", slug, why)
            report["exceptions"][slug] = f"NOT APPLIED: {why}"
            unsettled = {**unsettled, slug: f"A ruled exception (approvals.yaml) whose label no longer supports its line: {why}"}
        if on_list and not sides["otc"] and slug not in unsettled:
            no_basis.append(slug)
        if medicine:
            entry: dict = {"status": status or GROUP_STATUS[m["scope_bucket"]], "otc": sides["otc"],
                           "prescription": sides["prescription"]}
            if slug in unsettled or status is None:
                entry["status"] = GROUP_STATUS[m["scope_bucket"]]
                entry["unsettled"] = unsettled.get(slug) or "no over-the-counter or prescription basis in the record"
                report["unsettled"][slug] = entry["unsettled"]
            m["medicine_status"] = entry
            report["status"][slug] = entry["status"]
        else:
            m.pop("medicine_status", None)
        if slug in unsettled:
            continue                                   # left as it is
        if medicine or on_list or slug in uses_only:
            m["is_otc"] = bool(sides["otc"])
    if no_basis:
        raise StatusError(
            "the OTC list names molecule(s) with no over-the-counter basis in the record (an FDA OTC licence, an OTC "
            "monograph, a current OTC label under an NDA, ANDA or monograph, or one recorded in status_bases.yaml): "
            + ", ".join(sorted(no_basis)) + ". Record the basis, move the entry under uses_only:, or name it under "
            "unsettled: in status_bases.yaml.")
    counts = {k: sum(1 for v in report["status"].values() if v == k) for k in ("otc", "prescription", "both", UNAPPROVED)}
    log.info("  status: %d medicine(s): %d over the counter, %d prescription, %d both, %d sold without approval "
             "(ruled exceptions: %s); %d unsettled (%s); %d label(s) not counted", len(report["status"]), counts["otc"],
             counts["prescription"], counts["both"], counts[UNAPPROVED], ", ".join(sorted(report["exceptions"])) or "none",
             len(report["unsettled"]), ", ".join(sorted(report["unsettled"])) or "none",
             sum(len(v) for v in report["not_counted"].values()))
    return report
