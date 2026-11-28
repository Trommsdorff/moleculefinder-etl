"""Findings arithmetic: trust review 5 (`mfetl review findings`; brief ../TRUST-4-FINDINGS-ARITHMETIC-PROMPT.md, 2026-11-28).

The findings pages are the pages sent to reporters ("112 of the 300 medicine labels list one of the six dyes", with a
table, per-dye pages and downloads). A reporter adds the columns up. If a headline does not equal its own table, or its
CSV, or a per-dye page, or a weekly refresh quietly moves a number that was pitched, the finding loses its standing in
one email. This review reads every findings address from the LIVE site every day and checks the arithmetic.

READ-ONLY. It reads https://moleculefinder.com (the 14 findings addresses, each finding's data.csv and data.json, a HEAD
of every label page the table links, each page's share image and feeds), the links the pages cite, and the snapshot ETL
`main` holds (``data/snapshots``: products.json, the findings files and meta.json) with the two code tables the findings
are defined by (``sources/seeds/colour_additives.yaml``, ``inactive_groups.yaml``). It makes no PubChem request, loads no
database key and writes nothing but its report: ``<out>/findings-<date>.md`` and ``.json``, the heartbeat
``<out>/findings-last-run.json`` and lines in ``<out>/QUEUE.md``. It never blocks, stops or changes the weekly refresh,
the news job or a deploy. Exit 0 when it ran, whatever it found. NO SAMPLING: every address, every row, every label.

THE CHECKS (the brief's numbering; each finding goes in a named CLASS, the check, the surface and the shape):
 1. page equals its data   every count a page prints (title, description, headline, the over-the-counter and
                           prescription split, the by-mouth split, each dye's count, each chart bar, each "N of M", each
                           list heading, each form and code count) equals the count made from that page's data.json
                           ROWS (labels[], never its totals), and the denominators are the data's (labels, over the
                           counter, prescription, taken by mouth).
 2. the three forms agree  the main table's rows, the CSV's rows and the JSON's labels are the same set with the same
                           value in every column; the CSV's header is the documented one (web lib/findings.ts
                           CSV_COLUMNS; lib/inactive.ts CSV_FIXED plus one lists_<group> per charted group); the licence
                           (CC0 1.0) on the page, in the JSON and in the page's Dataset; each download's type.
 3. the parts add up       over the counter plus prescription is the total; a sub-page's "lists it" and "does not"
                           lists are disjoint and make the whole; each sub-page's list is the main table filtered on its
                           column; the "no dye listed" page is exactly the labels with no FD&C or D&C colour (the page's
                           own definition) and none of them lists one of the six; a label listing two dyes is once in the
                           headline; the forms of an ingredient cover its count; the JSON's totals equal its own rows.
 4. recomputed             every headline and every per-dye and per-ingredient count rebuilt from the labels'
                           own ingredient codes in the snapshot's products.json (by UNII, against the two code tables),
                           written here and NOT importing transform/findings.py, compared with the live data.json. A
                           difference is a finding against the transform: the most serious class, queued at once.
                           (The routes are not in products.json, so the by-mouth counts are checked by 1 and 3 only.)
 5. the label set          exactly the declared set (the snapshot's DailyMed medicine products), no label twice, each
                           row's /whats-in page answers 200 and its DailyMed link carries the label's own set id; each
                           label's set id, version and class on the page equal the snapshot's; a route reading "Not
                           read" is listed.
 6. named labels           the familiar labels the text names ("Among the 112: ...", "Among the 188 that list none of
                           the six: ...", the Red No. 3 labels, the labels listing no inactive ingredient) are in the
                           data, and in the recomputation, with that status.
 7. the date               the date each page states (data refreshed, the FDA pages read, the registry checked) equals
                           the data's own and the snapshot's.
 8. pitched numbers        review/pitched_numbers.yaml records what was told to people outside, with the date, to
                           whom and the evidence. A live number no longer equal to a pitched one is the loud class "a
                           pitched number moved": reported on the first run it is seen, at the top of the report and in
                           the queue, with the labels that changed and why (against the labels as they stood when sent).
 9. citations              each rule or guidance the pages cite is linked, its link names the section its text cites,
                           and the link answers. eCFR and the Federal Register serve automated readers a "Request
                           Access" page, so for those two the publisher's own API is asked instead and that is said; a
                           link that answers neither way is "not read", reported.
10. share images, feeds    each page's share image (og:image, twitter:image) answers 200 as an image; each feed a page
                           names answers 200 as XML; a findings page with no share image is listed.

A page it could not read is "not read" and contributes nothing: it is never counted as agreeing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from . import drawings as shared
from .facts import Node, _Builder, href_of, read_all, sitemap_paths

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "data" / "snapshots"
SEEDS = ROOT / "moleculefinder_etl" / "sources" / "seeds"
PITCHED = Path(__file__).with_name("pitched_numbers.yaml")
# The DailyMed labels as the weekly job read them (its canonical input cache, read only), then this checkout's own.
LABEL_CACHES = (Path.home() / "Library" / "Application Support" / "MoleculeFinder" / "raw_cache", ROOT / "data" / "raw_cache")
DEFAULT_OUT = ROOT.parent / "trust-reports"
SITE = "https://moleculefinder.com"
NAME = "findings"
USER_AGENT = shared.USER_AGENT
FETCH_SECONDS = 60
WORKERS = 4
PAUSE = 0.25
SHOWN = 10

FINDINGS = "/findings"
DYES = "/findings/dyes-in-medicines"
INACTIVE = "/findings/inactive-ingredients"
NONE = f"{DYES}/none-listed"
DOWNLOADS = tuple(f"{p}/data.{x}" for p in (DYES, INACTIVE) for x in ("csv", "json"))
SIX = ("blue-1", "blue-2", "green-3", "red-40", "yellow-5", "yellow-6")
DYE_PAGES = ("red-40", "yellow-5", "yellow-6", "blue-1", "blue-2", "green-3", "red-3")   # web lib/dye-pages.ts
SHORT = {"blue-1": "Blue 1", "blue-2": "Blue 2", "green-3": "Green 3", "red-40": "Red 40", "yellow-5": "Yellow 5",
         "yellow-6": "Yellow 6", "red-3": "Red 3"}
# web lib/dye-pages.ts: the other colours the none page names, and an FD&C or D&C name among the inactive groups
OTHER_COLOURS = ("iron-oxides", "titanium-dioxide", "code-t9d99g2b1r", "code-01yae03m7j", "code-cid8z8n95n",
                 "code-tz8z31b35m", "code-v8a1aw0880")
CERTIFIED = re.compile(r"^(FD&C|D&C|EXT\.? ?D&C)\b", re.IGNORECASE)
# The CSV headers as documented (web lib/findings.ts CSV_COLUMNS; lib/inactive.ts CSV_FIXED, then one lists_<group>
# column per charted group). A test holds these equal to the web's constants where the web repo is beside this one.
DYES_CSV = ("medicine", "moleculefinder_page", "class", "lists_any_of_six", "blue_1", "blue_2", "green_3", "red_40",
            "yellow_5", "yellow_6", "red_3", "d_and_c_colors", "dye_codes_listed", "routes", "taken_by_mouth",
            "dailymed_set_id", "label_version", "label_effective_date", "dailymed_url")
INACTIVE_CSV = ("medicine", "moleculefinder_page", "class", "taken_by_mouth", "inactive_ingredients", "inactive_codes",
                "routes", "dailymed_set_id", "label_version", "label_effective_date", "dailymed_url")
LICENCE = "CC0 1.0"
CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
CITED = {   # the rules and the guidance the brief names, each with the address its link must point at
    "21 CFR 201.66(c)(8)": "section-201.66", "21 CFR 201.100(b)(5)": "section-201.100",
    "21 CFR 201.20(a)": "section-201.20", "FDA-2025-D-0507": "replacing-color-additives-approved-or-marketed-drug-products",
}
CITATION_HOSTS = ("ecfr.gov", "fda.gov", "federalregister.gov", "regulations.gov")
BOT_PAGE = re.compile(r"<title>[^<]*Request Access[^<]*</title>", re.IGNORECASE)
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"], 1)}

# check -> (the brief's number, heading, the recommended fix a queue item carries)
CHECKS = {
    "pitched": (8, "a pitched number moved",
                ("Tell Cowork the same day: the number a reporter was given no longer stands. Say which labels moved and "
                "why before the follow-up email; never change the page back by hand.")),
    "recomputed": (4, "recomputed from the source",
                   ("A finding against transform/findings.py: rebuild the count by hand from products.json, find which "
                   "label or code the transform counts differently, fix the transform on a branch with a test.")),
    "page": (1, "a number on a page against its own data",
             "Make the page print the count made from its data (web lib/findings.ts, lib/dye-pages.ts, lib/inactive.ts)."),
    "forms": (2, "the table, the CSV and the JSON",
              "Make the three forms come from one list of rows (web lib/findings.ts dyesCsv, lib/inactive.ts inactiveCsv)."),
    "parts": (3, "the parts against the whole",
              "Make each part a filter of the one table, so the parts cannot fail to add up."),
    "labels": (5, "the label set", "Fix the label's row in products.yaml or its page; a label leaves only by its row."),
    "named": (6, "a label named in the text",
              "Correct the hand list of familiar labels (findings_dyes.yaml examples) or the sentence."),
    "date": (7, "the date a page states", "Print the data's own date (meta.json refreshed; the finding's read dates)."),
    "citations": (9, "a cited rule or guidance",
                  "Fix the link or the text naming it; a link that does not answer is checked by hand before a pitch."),
    "share": (10, "share images and feeds", "Give the page a share image, or fix the image or feed route."),
}
IMMEDIATE = {"pitched", "recomputed"}      # queued the first day seen; every other class on two consecutive runs
ORDER = {k: i for i, k in enumerate(CHECKS)}


# ── reading ─────────────────────────────────────────────────────────────────────────────────────
def fetch(url: str, head: bool = False) -> tuple[int, str, str]:
    """(status, content type, body). A HEAD reads no body. Two tries on a network error."""
    req = urllib.request.Request(url, method="HEAD" if head else "GET",
                                 headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=FETCH_SECONDS) as r:
                return r.status, r.headers.get("content-type") or "", "" if head else r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, (e.headers.get("content-type") if e.headers else "") or "", ""
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise
            time.sleep(5)
    raise OSError("unreachable")


def _getter(fetch_fn, head: bool = False):
    """facts.read_all's fetch shape (status, body), with the content type kept in the body slot's companion dict."""
    types: dict[str, str] = {}

    def one(url: str):
        status, ctype, body = fetch_fn(url, head)
        types[url] = ctype
        return status, body
    return one, types


def read_many(urls: list[str], fetch_fn, head: bool = False, workers: int = WORKERS, pause: float = PAUSE) -> dict:
    """url -> {"status", "type", "body"} or {"why"}."""
    one, types = _getter(fetch_fn, head)
    got = read_all(urls, one, "", workers, pause)
    for u, r in got.items():
        if "why" not in r:
            r["type"] = types.get(u, "")
    return got


# ── a page, taken apart ─────────────────────────────────────────────────────────────────────────
_NONLD_SCRIPT = re.compile(r"<script\b(?![^>]*application/ld\+json)[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)


def parse(raw: str) -> Node:
    b = _Builder()
    b.feed(_NONLD_SCRIPT.sub("", raw))      # the SVG is kept: the dyes chart's bars are text in it
    b.close()
    return b.root


def all_text(n: Node) -> str:
    """Every string under the node, scripts aside, the SVG's text included."""
    parts: list[str] = []

    def walk(x: Node) -> None:
        for k in x.kids:
            if isinstance(k, str):
                parts.append(k)
            elif k.tag not in ("script", "style"):
                parts.append("" if k.tag in ("sub", "sup", "b", "a", "span") else " ")
                walk(k)
    walk(n)
    return " ".join("".join(parts).split())


def words(n: Node) -> str:
    """The text with the space before a full stop, comma or bracket closed up (a link's text is set apart)."""
    return re.sub(r"\s+([.,;:)])", r"\1", re.sub(r"\(\s+", "(", all_text(n)))


class FPage:
    def __init__(self, path: str, raw: str):
        self.path, self.raw = path, raw
        self.root = parse(raw)
        self.main = next((n for n in self.root.iter() if n.tag == "main"), self.root)
        self.title = self.description = ""
        self.meta: dict[str, str] = {}
        self.jsonld: list = []
        self.alternates: list[tuple[str, str]] = []
        for n in self.root.iter():
            if n.tag == "title" and not self.title and n.parent is not None and n.parent.tag == "head":
                self.title = all_text(n)
            elif n.tag == "meta":
                key = n.attrs.get("property") or n.attrs.get("name")
                if key and key not in self.meta:
                    self.meta[key] = n.attrs.get("content") or ""
            elif n.tag == "script" and "ld+json" in (n.attrs.get("type") or ""):
                try:
                    self.jsonld.append(json.loads("".join(k for k in n.kids if isinstance(k, str))))
                except ValueError:
                    pass
            elif n.tag == "link" and n.attrs.get("rel") == "alternate" and n.attrs.get("href"):
                self.alternates.append((n.attrs["href"], n.attrs.get("type") or ""))
        if not self.title:
            self.title = next((all_text(n) for n in self.root.iter() if n.tag == "title"), "")
        self.description = self.meta.get("description", "")

    def by_class(self, cls: str, within: Node | None = None) -> list[Node]:
        return [n for n in (within or self.main).iter() if cls in n.classes]

    def first(self, cls: str) -> str | None:
        xs = self.by_class(cls)
        return words(xs[0]) if xs else None

    def section(self, heading_id: str) -> Node | None:
        """The <section> labelled by the heading with this id."""
        for n in self.main.iter():
            if n.tag == "section" and n.attrs.get("aria-labelledby") == heading_id:
                return n
        return None

    def heading(self, heading_id: str) -> str | None:
        for n in self.main.iter():
            if n.attrs.get("id") == heading_id:
                return words(n)
        return None

    def items(self, within: Node | None = None) -> list[str]:
        return [words(n) for n in (within or self.main).iter() if n.tag == "li"]

    def tables(self) -> list[list[Row]]:
        out = []
        for tb in (n for n in self.main.iter() if n.tag == "tbody"):
            out.append([Row(tr) for tr in tb.kids if isinstance(tr, Node) and tr.tag == "tr"])
        return out


class Row:
    def __init__(self, tr: Node):
        self.cells = [c for c in tr.kids if isinstance(c, Node) and c.tag in ("th", "td")]
        self.texts = [words(c) for c in self.cells]
        self.links = [href_of(a) for a in tr.iter() if a.tag == "a"]
        self.raw_links = [a.attrs.get("href") or "" for a in tr.iter() if a.tag == "a"]
        self.slug = next((h[len("/whats-in/"):] for h in self.links if h.startswith("/whats-in/")), None)
        self.dailymed = next((h for h in self.raw_links if "dailymed.nlm.nih.gov" in h), None)
        self.by_label = {c.attrs.get("data-label"): words(c) for c in self.cells if c.attrs.get("data-label")}


def n_(s: str) -> int:
    return int(s.replace(",", ""))


def iso_of(words_date: str) -> str | None:
    """'23 November 2026' -> '2026-11-23'."""
    m = re.fullmatch(r"(\d{1,2}) ([A-Z][a-z]+) (\d{4})", words_date.strip())
    if not m or m.group(2) not in MONTHS:
        return None
    return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"


def full_date(iso: str | None) -> str:
    """'2026-11-23' -> '23 November 2026' (the site's dates)."""
    if not iso or not re.fullmatch(r"\d{4}-\d\d-\d\d", iso):
        return iso or ""
    y, m, d = iso.split("-")
    return f"{int(d)} {list(MONTHS)[int(m) - 1]} {y}"


def iso8(d: str | None) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if d and re.fullmatch(r"\d{8}", d) else (d or "")


# ── the review's findings ───────────────────────────────────────────────────────────────────────
class Review:
    def __init__(self):
        self.findings: list[dict] = []
        self.compared: Counter = Counter()           # (check, surface) -> comparisons
        self.notes: list[str] = []

    def check(self, check: str, surface: str, subject: str, path: str, shape: str | None, detail: str = "") -> bool:
        self.compared[(check, surface)] += 1
        if shape:
            self.findings.append({"check": check, "surface": surface, "shape": shape, "subject": subject,
                                  "path": path, "detail": detail})
        return not shape

    def eq(self, check: str, surface: str, subject: str, path: str, printed, expected, what: str,
           shape: str = "the page and its data differ") -> bool:
        ok = printed == expected
        return self.check(check, surface, subject, path, None if ok else shape,
                          "" if ok else f"{what}: printed {printed!r}, the data gives {expected!r}")

    def unread(self, check: str, surface: str, subject: str, path: str, what: str) -> None:
        """A sentence the review reads was not where it reads it: never a pass."""
        self.check(check, surface, subject, path, "the sentence is not where the review reads it", what)

    def total(self) -> int:
        return sum(self.compared.values())


# ── the data, as a page's own rows give it ─────────────────────────────────────────────────────
def split(rows: list[dict]) -> dict:
    return {"labels": len(rows), "otc": sum(r["class"] == "otc" for r in rows),
            "prescription": sum(r["class"] == "prescription" for r in rows)}


def by_mouth(r: dict) -> bool:
    return r.get("taken") in ("oral", "oral+other")


def dyes_rows(D: dict) -> dict:
    """Every count the dyes pages print, made from the data's ROWS (labels[]), never from its totals."""
    L = D["labels"]
    any6 = [r for r in L if r["six"]]
    out = {"all": split(L), "any6": split(any6), "two": len([r for r in L if len(r["six"]) >= 2]),
           "three": len([r for r in L if len(r["six"]) >= 3]), "red3": [r for r in L if r["red_3"]],
           "dc": len([r for r in L if r["d_and_c"]]), "by_mouth_all": sum(by_mouth(r) for r in L),
           "any6_taken": Counter(r.get("taken") or "unstated" for r in any6),
           "dye": {}, "lists": {}}
    for i in (*SIX, "red-3"):
        lists = [r for r in L if (r["red_3"] if i == "red-3" else i in r["six"])]
        out["lists"][i] = lists
        forms = [{c["form"] for c in r["codes"] if c["dye"] == i} for r in lists]
        out["dye"][i] = {**split(lists), "by_mouth": sum(by_mouth(r) for r in lists),
                         "dye_form": sum("dye" in f for f in forms), "lake_form": sum("lake" in f for f in forms),
                         "both": sum(f == {"dye", "lake"} for f in forms)}
    return out


def inactive_rows(F: dict) -> dict:
    L = F["labels"]
    by_group: dict[str, list[dict]] = defaultdict(list)
    by_code: Counter = Counter()
    for r in L:
        for g in r["groups"]:
            by_group[g].append(r)
        for u in r["codes"]:
            by_code[u] += 1
    floor = -(-len(L) // 10)
    return {"all": {**split(L), "by_mouth": sum(by_mouth(r) for r in L)}, "by_group": by_group, "by_code": by_code,
            "codes": len(by_code), "groups": len(by_group), "none": [r for r in L if not r["codes"]], "floor": floor}


def none_rows(D: dict, F: dict) -> list[dict]:
    """The none page's set, by the page's own rule (web lib/dye-pages.ts listsCertified): no one of the six, no Red 3,
    no D&C colour the dyes finding counts, and no inactive group named as an FD&C or D&C colour."""
    names = {g["id"]: g["name"] for g in F["groups"]}
    groups = {r["slug"]: r["groups"] for r in F["labels"]}
    return [r for r in D["labels"] if not (r["six"] or r["red_3"] or r["d_and_c"])
            and not any(CERTIFIED.match(names.get(g, "")) for g in groups.get(r["slug"], []))]


# ── words the pages print, the same rules as the web (lib/findings.ts) ─────────────────────────
def class_word(c: str) -> str:
    return "Over the counter" if c == "otc" else "Prescription"


def taken_words(r: dict) -> str:
    routes = r.get("routes")
    if routes is None:
        return "Not read"
    if not routes:
        return "None named"
    ws = [("by mouth" if x == "ORAL" else x.lower()) for x in sorted(routes, key=lambda x: x != "ORAL")]
    s = ", ".join(ws)
    return s[:1].upper() + s[1:]


def taken_cell(r: dict) -> str:
    if r.get("routes") is None:
        return "not read"
    return {"oral": "yes", "oral+other": "yes, and another route", "other": "no, another route"}.get(r.get("taken"),
                                                                                                    "no route named")


def dye_text(r: dict) -> str:
    out = []
    for i in r["six"]:
        forms = {c["form"] for c in r["codes"] if c["dye"] == i}
        out.append(SHORT[i] if "dye" in forms else f"{SHORT[i]} (lake)")
    return ", ".join(out)


def version_words(r: dict) -> str:
    v = "Label" if r.get("version") is None else f"Version {r['version']}"
    return v + (f", {full_date(iso8(r.get('effective')))}" if r.get("effective") else "")


def yn(b: bool) -> str:
    return "yes" if b else "no"


# ── the recomputation (check 4): written here, from the labels' own codes; never transform/findings.py ─
def load_tables(seeds: Path = SEEDS) -> dict:
    """The two code tables that DEFINE the findings (which codes are a dye, which codes are one ingredient)."""
    col = yaml.safe_load((seeds / "colour_additives.yaml").read_text()) or {}
    grp = yaml.safe_load((seeds / "inactive_groups.yaml").read_text()) or {}
    dye_of: dict[str, tuple[str, str, str]] = {}            # unii -> (dye id, group, form)
    for d in col.get("dyes") or []:
        for c in d.get("codes") or []:
            dye_of[str(c["unii"])] = (d["id"], d["group"], c["form"])
    group_of = {str(c["unii"]): g["id"] for g in grp.get("groups") or [] for c in g.get("codes") or []}
    return {"dye_of": dye_of, "group_of": group_of,
            "dc_ids": [d["id"] for d in col.get("dyes") or [] if d.get("group") == "d-and-c"]}


def medicine_labels(products: dict) -> list[dict]:
    ps = products.get("products", products)
    ps = list(ps.values()) if isinstance(ps, dict) else list(ps)
    return sorted((p for p in ps if p.get("kind") == "medicine" and (p.get("source") or {}).get("type") == "dailymed"),
                  key=lambda p: p["slug"])


def label_class(doc_type: str | None) -> str | None:
    t = (doc_type or "").upper()
    return "otc" if t.startswith("HUMAN OTC") else "prescription" if t.startswith("HUMAN PRESCRIPTION") else None


def label_cache(dirs=LABEL_CACHES):
    """setid -> the cached DailyMed label (its own ingredient list), read straight from the cache files; None when
    no cache folder holds it. The first folder that exists is used, and it is named in the report."""
    root = next((d / "dailymed" for d in dirs if (d / "dailymed").is_dir()), None)

    def spl(setid: str) -> dict | None:
        if root is None:
            return None
        f = root / f"spl1-{setid}.json"
        try:
            v = json.loads(f.read_text()).get("value")
        except (OSError, ValueError):
            return None
        return v if isinstance(v, dict) and not v.get("missing") and v.get("ingredients") else None
    spl.root = root
    return spl


def ingredients(p: dict, label: dict | None = None) -> list[tuple[str, str, str]]:
    """(unii, role, the label's own name) for every ingredient: the label's own list when it is cached, else what the
    product's page data carries (which keeps one row per molecule, so a second code of one molecule is not there)."""
    if label:
        return [(i.get("unii") or "", i.get("role") or "", i.get("name") or "") for i in label["ingredients"]]
    out = [(m.get("unii") or "", m.get("role") or "", m.get("listed_as") or m.get("slug") or "") for m in p.get("molecules") or []]
    out += [(n.get("unii") or "", n.get("role") or "", n.get("name") or "") for n in p.get("not_in_catalog") or []]
    return out


def recompute(products: dict, tables: dict, spl=None) -> dict:
    """Every count of both findings, rebuilt by UNII from each label's own ingredient list (the cached DailyMed label,
    ``spl``; the snapshot's page data where a label is not cached). Returns per-label facts and the totals."""
    dye_of, group_of = tables["dye_of"], tables["group_of"]
    labels = {}
    origin = Counter()
    gaps = []
    for p in medicine_labels(products):
        label = spl(p["source"]["setid"]) if spl else None
        if label and label.get("version") != p["source"].get("version"):
            gaps.append(f"{p['slug']}: the cached label is version {label.get('version')}, the snapshot's {p['source'].get('version')}")
        ing = ingredients(p, label)
        origin["the cached label" if label else "the page data"] += 1
        if not label and p.get("listed") is not None and len(ing) != p["listed"]:
            gaps.append(f"{p['slug']}: not cached, and the page data holds {len(ing)} of the {p['listed']} ingredients it lists")
        six, red3, dc = set(), False, set()
        for u, _role, _name in ing:
            if u in dye_of:
                did, grp, _form = dye_of[u]
                if grp == "six":
                    six.add(did)
                elif grp == "red-3":
                    red3 = True
                else:
                    dc.add(did)
        inactive = sorted({u for u, role, _n in ing if role == "inactive" and u})
        groups = sorted({group_of.get(u) or (dye_of[u][0] if u in dye_of else "code-" + u.lower()) for u in inactive})
        certified_name = any(role == "inactive" and u not in dye_of and CERTIFIED.match(" ".join(name.split()))
                             for u, role, name in ing)
        src = p["source"]
        labels[p["slug"]] = {"slug": p["slug"], "class": label_class(src.get("doc_type")), "setid": src.get("setid"),
                             "version": src.get("version"), "six": sorted(six), "red_3": red3, "d_and_c": sorted(dc),
                             "codes": inactive, "groups": groups, "certified_name": certified_name,
                             "every_active": not p.get("actives_not_in_catalog")}
    L = list(labels.values())
    by_group: dict[str, list[dict]] = defaultdict(list)
    by_code: Counter = Counter()
    for r in L:
        for g in r["groups"]:
            by_group[g].append(r)
        for u in r["codes"]:
            by_code[u] += 1
    floor = -(-len(L) // 10)
    dyes = {"labels": split(L), "any_of_six": split([r for r in L if r["six"]]),
            "two_or_more": split([r for r in L if len(r["six"]) >= 2]),
            "three_or_more": split([r for r in L if len(r["six"]) >= 3]),
            "red_3": {**split([r for r in L if r["red_3"]]), "slugs": sorted(r["slug"] for r in L if r["red_3"])},
            "d_and_c_any": split([r for r in L if r["d_and_c"]]),
            "by_dye": {i: split([r for r in L if i in r["six"]]) for i in SIX},
            "d_and_c_by_dye": {i: split([r for r in L if i in r["d_and_c"]]) for i in tables["dc_ids"]},
            "every_active_is_a_molecule": sum(r["every_active"] for r in L),
            "none_listed": sorted(r["slug"] for r in L if not (r["six"] or r["red_3"] or r["d_and_c"] or r["certified_name"]))}
    inactive = {"labels": split(L), "lists_none": sorted(r["slug"] for r in L if not r["codes"]),
                "codes": len(by_code), "groups": len(by_group), "floor": floor,
                "shown": sorted(g for g, rs in by_group.items() if len(rs) >= floor),
                "by_group": {g: split(rs) for g, rs in by_group.items()}, "by_code": dict(by_code)}
    return {"labels": labels, "dyes": dyes, "inactive": inactive, "origin": dict(origin), "gaps": gaps}


def compare_recomputed(rv: Review, rec: dict, D: dict | None, F: dict | None, path_d: str, path_i: str) -> list[str]:
    """Each count of the recomputation against the live data.json. Returns the counts compared, for the report."""
    compared: list[str] = []

    def one(surface: str, subject: str, path: str, mine, theirs, what: str) -> None:
        compared.append(f"{surface}: {what}")
        rv.check("recomputed", surface, subject, path, None if mine == theirs else "the transform's count differs",
                 "" if mine == theirs else f"{what}: recomputed {mine!r}, the published file says {theirs!r}")
    if D:
        t = D["totals"]
        r = rec["dyes"]
        for k in ("labels", "any_of_six", "two_or_more", "three_or_more", "d_and_c_any"):
            for x in ("labels", "otc", "prescription"):
                one("the dyes finding", k, path_d, r[k][x], t[k][x], f"{k}.{x}")
        for x in ("labels", "otc", "prescription"):
            one("the dyes finding", "red_3", path_d, r["red_3"][x], t["red_3"][x], f"red_3.{x}")
        one("the dyes finding", "red_3", path_d, r["red_3"]["slugs"], sorted(t["red_3"]["slugs"]), "red_3.slugs")
        for i in SIX:
            for x in ("labels", "otc", "prescription"):
                one("the dyes finding", i, path_d, r["by_dye"][i][x], t["by_dye"][i][x], f"by_dye.{i}.{x}")
        for i, v in r["d_and_c_by_dye"].items():
            for x in ("labels", "otc", "prescription"):
                one("the dyes finding", i, path_d, v[x], (t["d_and_c_by_dye"].get(i) or {}).get(x), f"d_and_c_by_dye.{i}.{x}")
        one("the dyes finding", "selection", path_d, r["labels"]["labels"], D["selection"]["labels"], "selection.labels")
        one("the dyes finding", "selection", path_d, r["every_active_is_a_molecule"],
            D["selection"]["every_active_is_a_molecule"], "selection.every_active_is_a_molecule")
        live = {x["slug"]: x for x in D["labels"]}
        for slug, mine in sorted(rec["labels"].items()):
            x = live.get(slug)
            if x is None:
                continue                                # the label set's own check names it
            for k in ("six", "red_3", "d_and_c"):
                one("the dyes finding's rows", slug, path_d, mine[k], sorted(x[k]) if isinstance(x[k], list) else x[k], f"{slug} {k}")
        if F:
            one("the none page", "none listed", f"{DYES}/none-listed", r["none_listed"],
                sorted(x["slug"] for x in none_rows(D, F)), "the labels with no FD&C or D&C colour")
    if F:
        t = F["totals"]
        r = rec["inactive"]
        for x in ("labels", "otc", "prescription"):
            one("the inactive finding", "labels", path_i, r["labels"][x], t["labels"][x], f"labels.{x}")
        one("the inactive finding", "lists_none", path_i, r["lists_none"], sorted(t["lists_none"]["slugs"]), "lists_none.slugs")
        for k in ("codes", "groups"):
            one("the inactive finding", k, path_i, r[k], t[k], k)
        one("the inactive finding", "shown", path_i, r["floor"], t["shown"]["floor"], "shown.floor")
        one("the inactive finding", "shown", path_i, r["shown"], sorted(t["shown"]["groups"]), "shown.groups")
        groups = {g["id"]: g for g in F["groups"]}
        for gid in sorted(set(r["by_group"]) | set(groups)):
            mine = r["by_group"].get(gid, {"labels": 0, "otc": 0, "prescription": 0})
            g = groups.get(gid) or {}
            for x in ("labels", "otc", "prescription"):
                one("the inactive finding's groups", gid, path_i, mine[x], g.get(x, 0), f"{gid}.{x}")
            for c in g.get("codes") or []:
                one("the inactive finding's codes", gid, path_i, r["by_code"].get(c["unii"], 0), c["labels"],
                    f"{gid} code {c['unii']}")
        live = {x["slug"]: x for x in F["labels"]}
        for slug, mine in sorted(rec["labels"].items()):
            x = live.get(slug)
            if x is None:
                continue
            one("the inactive finding's rows", slug, path_i, mine["codes"], sorted(x["codes"]), f"{slug} codes")
            one("the inactive finding's rows", slug, path_i, mine["groups"], sorted(x["groups"]), f"{slug} groups")
    return compared


# ── check 1 and 3: the pages ────────────────────────────────────────────────────────────────────
def match(rv: Review, check: str, surface: str, path: str, pattern: str, text: str | None, what: str):
    m = re.search(pattern, text or "")
    if not m:
        rv.unread(check, surface, what, path, f"{what}: {(text or '(absent)')[:160]!r}")
    return m


def check_title_count(rv: Review, pg: FPage, pattern: str, n: int, what: str = "title") -> None:
    m = match(rv, "page", "title", pg.path, pattern, pg.title, what)
    if m:
        rv.eq("page", "title", what, pg.path, n_(m.group(1)), n, "the labels in the count")


def check_dyes_main(rv: Review, pg: FPage, D: dict, R: dict) -> None:
    p, a, t6 = pg.path, R["all"], R["any6"]
    check_title_count(rv, pg, r"^Food dyes in medicines: what ([\d,]+) labels list", a["labels"])
    m = match(rv, "page", "description", p, r"^([\d,]+) of the ([\d,]+) medicine labels on MoleculeFinder list one of the six",
              pg.description, "description")
    if m:
        rv.eq("page", "description", "headline", p, (n_(m.group(1)), n_(m.group(2))), (t6["labels"], a["labels"]), "N of M")
    lede = pg.first("fd-lede")
    m = match(rv, "page", "headline", p, r"^([\d,]+) of the ([\d,]+) medicine labels on MoleculeFinder list at least one of the six", lede, "headline")
    if m:
        rv.eq("page", "headline", "headline", p, n_(m.group(1)), t6["labels"], "labels listing one of the six")
        rv.eq("page", "headline", "denominator", p, n_(m.group(2)), a["labels"], "the labels in the count")
    check_split(rv, pg, pg.first("fd-split"), t6, a, "headline split")
    ex = pg.first("fd-examples")
    m = re.search(r"Among the ([\d,]+):", ex or "")
    if m:
        rv.eq("page", "examples", "lists", p, n_(m.group(1)), t6["labels"], "Among the N")
    m = re.search(r"Among the ([\d,]+) that list none of the six", ex or "")
    if m:
        rv.eq("page", "examples", "lists none", p, n_(m.group(1)), a["labels"] - t6["labels"], "Among the N that list none")
    facts = pg.items(pg.section("fd-numbers"))
    two = next((x for x in facts if "two or more" in x), None)
    m = match(rv, "page", "the numbers", p, r"^([\d,]+) of the ([\d,]+) labels list two or more of the six, and ([\d,]+) list three or more", two, "two or more")
    if m:
        rv.eq("page", "the numbers", "two or more", p, (n_(m.group(1)), n_(m.group(2)), n_(m.group(3))),
              (R["two"], a["labels"], R["three"]), "two or more, of, three or more")
    rs = next((x for x in facts if "taken by mouth" in x), None)
    m = match(rv, "page", "the numbers", p, r"^([\d,]+) of the ([\d,]+) are taken by mouth", rs, "routes sentence")
    if m:
        tk = R["any6_taken"]
        rv.eq("page", "the numbers", "by mouth", p, n_(m.group(1)), tk["oral"] + tk["oral+other"], "taken by mouth")
        rv.eq("page", "the numbers", "by mouth", p, n_(m.group(2)), t6["labels"], "of the N")
        for pat, key in ((r"\(([\d,]+) of them names? another route as well\)", "oral+other"),
                         (r"([\d,]+) names? another route instead", "other"), (r"([\d,]+) names? no route", "unstated")):
            mm = re.search(pat, rs)
            rv.eq("page", "the numbers", "by mouth", p, n_(mm.group(1)) if mm else 0, tk.get(key, 0), key)
        whole = sum(tk.get(k, 0) for k in ("oral", "oral+other", "other", "unstated"))
        rv.check("parts", "the routes sentence", "by mouth", p, None if whole == t6["labels"] else "the parts do not make the whole",
                 f"the routes of the {t6['labels']} add to {whole}")
    dc = next((x for x in facts if "D&C color" in x), None)
    m = match(rv, "page", "the numbers", p, r"^([\d,]+) labels list a D&C color", dc, "D&C sentence")
    if m:
        rv.eq("page", "the numbers", "D&C", p, n_(m.group(1)), R["dc"], "labels listing a D&C colour")
    # the chart: each bar against its dye's count, the order by count (ties in the colours' own order)
    bars = chart_bars(pg)
    want = sorted(SIX, key=lambda i: (-R["dye"][i]["labels"], SIX.index(i)))
    if not bars:
        rv.unread("page", "chart", "bars", p, "no chart bars")
    else:
        short_to = {v: k for k, v in SHORT.items()}
        for name, val in bars:
            i = short_to.get(name)
            rv.eq("page", "chart", i or name, p, val, R["dye"][i]["labels"] if i else None, f"the {name} bar")
        rv.eq("page", "chart", "order", p, [short_to.get(nm) for nm, _ in bars], want, "the bars' order")
    desc = next((all_text(n) for n in pg.main.iter() if n.tag == "desc"), None)
    m = match(rv, "page", "chart", p, r"^Of the ([\d,]+) medicine labels: (.+)\.$", desc, "chart description")
    if m:
        rv.eq("page", "chart", "denominator", p, n_(m.group(1)), a["labels"], "the chart's denominator")
        got = {nm: n_(v) for nm, v in re.findall(r"([A-Z][a-z]+ \d+) ([\d,]+)", m.group(2))}
        rv.eq("page", "chart", "description", p, got, {SHORT[i]: R["dye"][i]["labels"] for i in SIX}, "the chart's text")
    cap = pg.first("fd-chart__cap")
    m = match(rv, "page", "chart", p, r"^Number of the ([\d,]+) medicine labels", cap, "chart caption")
    if m:
        rv.eq("page", "chart", "caption", p, n_(m.group(1)), a["labels"], "the caption's denominator")
    red = pg.section("fd-red3")
    rt = words(red) if red else None
    m = match(rv, "page", "Red No. 3", p, r"([\d,]+) labels? lists? FD&C Red No\. 3|No label in this count lists FD&C Red No\. 3", rt, "Red 3 sentence")
    if m:
        rv.eq("page", "Red No. 3", "red 3", p, n_(m.group(1)) if m.group(1) else 0, len(R["red3"]), "labels listing Red 3")
        if "each taken by mouth" in rt:
            rv.eq("page", "Red No. 3", "by mouth", p, all(by_mouth(r) for r in R["red3"]), True, "each taken by mouth")
    note = pg.section("fd-table")
    nt = pg.first_in(note, "fd-note") if note else None
    m = match(rv, "page", "table", p, r"^([\d,]+) labels\.", nt, "table note")
    if m:
        rv.eq("page", "table", "count", p, n_(m.group(1)), a["labels"], "the table's stated count")
    check_methods(rv, pg, D)
    tabs = pg.tables()
    if tabs:
        rv.eq("page", "table", "rows", p, len(tabs[0]), a["labels"], "the table's rows")


def first_in(self: FPage, node: Node | None, cls: str) -> str | None:
    xs = self.by_class(cls, node) if node else []
    return words(xs[0]) if xs else None


FPage.first_in = first_in


def chart_bars(pg: FPage) -> list[tuple[str, int]]:
    out = []
    for g in (n for n in pg.main.iter() if n.tag == "g"):
        nm = next((all_text(t) for t in g.iter() if "fd-chart__name" in t.classes), None)
        val = next((all_text(t) for t in g.iter() if "fd-chart__val" in t.classes), None)
        if nm and val and re.fullmatch(r"[\d,]+", val):
            out.append((nm, n_(val)))
    return out


def check_split(rv: Review, pg: FPage, text: str | None, part: dict, whole: dict, what: str) -> None:
    p = pg.path
    m = match(rv, "page", what, p, r"([\d,]+) of the ([\d,]+) over-the-counter labels and ([\d,]+) of the ([\d,]+) prescription labels", text, what)
    if m:
        got = tuple(n_(m.group(i)) for i in range(1, 5))
        rv.eq("page", what, "split", p, got, (part["otc"], whole["otc"], part["prescription"], whole["prescription"]),
              "OTC of OTC, prescription of prescription")
        rv.check("parts", what, "split", p, None if got[0] + got[2] == part["labels"] else "the parts do not make the whole",
                 f"{got[0]} + {got[2]} against {part['labels']}")
        rv.check("parts", what, "denominators", p, None if got[1] + got[3] == whole["labels"] else "the parts do not make the whole",
                 f"{got[1]} + {got[3]} against {whole['labels']}")


def check_methods(rv: Review, pg: FPage, data: dict) -> None:
    p = pg.path
    which = next((x for x in pg.items(pg.section("fd-methods") or pg.section("dp-methods") or pg.section("fi-methods") or pg.main)
                  if x.startswith("Which labels.")), None)
    m = match(rv, "page", "methods", p, r"These are ([\d,]+) well-known brand labels", which, "Which labels")
    if m:
        rv.eq("page", "methods", "labels", p, n_(m.group(1)), len(data["labels"]), "Which labels: the count")
    m = re.search(r"In ([\d,]+) of the ([\d,]+), every active ingredient", which or "")
    if m:
        rv.eq("page", "methods", "every active", p, (n_(m.group(1)), n_(m.group(2))),
              (data["selection"]["every_active_is_a_molecule"], len(data["labels"])), "every active ingredient a molecule")


def check_dye_page(rv: Review, pg: FPage, D: dict, R: dict, i: str, main_table: list[Row] | None) -> None:
    p, a, d = pg.path, R["all"], R["dye"][i]
    name = next((x["name"] for x in D["dyes"] if x["id"] == i), i)
    check_title_count(rv, pg, r"^Medicines with .+?: which of ([\d,]+) labels list it", a["labels"])
    m = match(rv, "page", "description", p, r"^([\d,]+) of the ([\d,]+) medicine labels on MoleculeFinder list (.+?): ([\d,]+) over the counter, ([\d,]+) prescription\.",
              pg.description, "description")
    if m:
        rv.eq("page", "description", i, p, (n_(m.group(1)), n_(m.group(2)), m.group(3), n_(m.group(4)), n_(m.group(5))),
              (d["labels"], a["labels"], name, d["otc"], d["prescription"]), "N of M, the dye, OTC, prescription")
    m = match(rv, "page", "headline", p, r"^([\d,]+) of the ([\d,]+) medicine labels on MoleculeFinder list (.+)\.$", pg.first("fd-lede"), "headline")
    if m:
        rv.eq("page", "headline", i, p, (n_(m.group(1)), n_(m.group(2)), m.group(3)), (d["labels"], a["labels"], name), "N of M, the dye")
    sp = pg.first("fd-split")
    check_split(rv, pg, sp, d, a, "headline split")
    m = match(rv, "page", "by mouth", p, r"([\d,]+) of the ([\d,]+) labels taken by mouth list", sp, "by-mouth sentence")
    if m:
        rv.eq("page", "by mouth", i, p, (n_(m.group(1)), n_(m.group(2))), (d["by_mouth"], R["by_mouth_all"]), "by mouth, of all taken by mouth")
    forms = next((words(n) for n in pg.by_class("fd-examples") if re.search(r"straight dye", words(n))), None)
    m = re.search(r"^([\d,]+) lists? the straight dye and ([\d,]+) lists? its lake(?:; ([\d,]+) lists? both)?", forms or "")
    m2 = re.search(r"^The count takes the straight dye, (?:which the label lists|which all ([\d,]+) labels list)", forms or "")
    if m:
        got = (n_(m.group(1)), n_(m.group(2)), n_(m.group(3)) if m.group(3) else 0)
        rv.eq("page", "forms", i, p, got, (d["dye_form"], d["lake_form"], d["both"]), "straight dye, lake, both")
        rv.check("parts", "forms", i, p, None if got[0] + got[1] - got[2] == d["labels"] else "the forms do not cover the count",
                 f"{got[0]} + {got[1]} - {got[2]} against {d['labels']}")
    elif m2:
        rv.eq("page", "forms", i, p, n_(m2.group(1)) if m2.group(1) else 1, d["labels"], "the straight dye on every label")
        rv.eq("page", "forms", i, p, d["lake_form"], 0, "no lake listed")
    else:
        rv.unread("page", "forms", i, p, f"forms sentence: {forms!r}")
    check_lists(rv, pg, i, R["lists"][i], D["labels"], "dp-lists", "dp-lists-not", main_table,
                lambda row: SHORT[i] in [x.strip() for x in re.sub(r"\(lake\)", "", row.texts[2] if len(row.texts) > 2 else "").replace("Also lists Red 3", ",").split(",")]
                if i != "red-3" else "Also lists Red 3" in (row.texts[2] if len(row.texts) > 2 else ""))
    tabs = pg.tables()
    if tabs:
        by = {r["slug"]: r for r in R["lists"][i]}
        for row in tabs[0]:
            r = by.get(row.slug)
            if r:
                f = {c["form"] for c in r["codes"] if c["dye"] == i}
                want = "Straight dye and lake" if f == {"dye", "lake"} else "Lake" if f == {"lake"} else "Straight dye"
                rv.eq("page", "the Listed as column", row.slug, p, row.by_label.get("Listed as"), want, "listed as")
    check_methods(rv, pg, D)


def check_lists(rv: Review, pg: FPage, gid: str, lists: list[dict], every: list[dict], h_lists: str, h_not: str,
                main_table: list[Row] | None, in_main) -> None:
    """A sub-page's two lists: their headings and rows against the data; disjoint; the whole; the main table's filter."""
    p = pg.path
    tabs = pg.tables()
    if len(tabs) < 2:
        rv.unread("page", "lists", gid, p, f"{len(tabs)} tables on the page, two expected")
        return
    yes, no = [r.slug for r in tabs[0]], [r.slug for r in tabs[1]]
    for hid, rows, want in ((h_lists, yes, len(lists)), (h_not, no, len(every) - len(lists))):
        m = match(rv, "page", "list heading", p, r"^The ([\d,]+) labels? that", pg.heading(hid), hid)
        if m:
            rv.eq("page", "list heading", gid, p, n_(m.group(1)), want, f"the heading {hid}")
            rv.eq("parts", "list heading", gid, p, n_(m.group(1)), len(rows), f"the heading {hid} against its rows",
                  shape="a heading's count is not its rows")
    rv.eq("page", "lists", gid, p, sorted(yes), sorted(r["slug"] for r in lists), "the labels that list it")
    both = sorted(set(yes) & set(no))
    rv.check("parts", "a sub-page's two lists", gid, p, "a label in both lists" if both else None, ", ".join(both[:10]))
    whole = sorted(yes + no) == sorted(r["slug"] for r in every)
    rv.check("parts", "a sub-page's two lists", gid, p, None if whole else "the two lists are not the whole",
             "" if whole else f"{len(yes)} + {len(no)} rows against {len(every)} labels; missing "
             f"{sorted({r['slug'] for r in every} - set(yes) - set(no))[:10]}")
    if main_table is not None:
        filt = sorted(r.slug for r in main_table if in_main(r))
        rv.check("parts", "a sub-page against the main table", gid, p, None if filt == sorted(yes) else "the list is not the main table's filter",
                 "" if filt == sorted(yes) else f"only on the sub-page {sorted(set(yes) - set(filt))[:10]}, only in the filter {sorted(set(filt) - set(yes))[:10]}")


def check_none_page(rv: Review, pg: FPage, D: dict, F: dict, R: dict) -> None:
    p, a = pg.path, R["all"]
    none = none_rows(D, F)
    otc = [r for r in none if r["class"] == "otc"]
    rx = [r for r in none if r["class"] == "prescription"]
    rx_mouth = sum(by_mouth(r) for r in rx)
    check_title_count(rv, pg, r"which of ([\d,]+) labels", a["labels"])
    m = match(rv, "page", "description", p, r"^([\d,]+) of the ([\d,]+) over-the-counter labels on MoleculeFinder list no FD&C or D&C color, and ([\d,]+) of the ([\d,]+) prescription labels",
              pg.description, "description")
    if m:
        rv.eq("page", "description", "none", p, tuple(n_(m.group(k)) for k in range(1, 5)),
              (len(otc), a["otc"], len(rx), a["prescription"]), "OTC of OTC, prescription of prescription")
    m = match(rv, "page", "headline", p, r"^([\d,]+) of the ([\d,]+) over-the-counter medicine labels on MoleculeFinder list no FD&C or D&C color", pg.first("fd-lede"), "headline")
    if m:
        rv.eq("page", "headline", "none", p, (n_(m.group(1)), n_(m.group(2))), (len(otc), a["otc"]), "OTC none of OTC")
    for txt in [pg.first("fd-split")] + [x for x in (words(n) for n in pg.by_class("fd-note")) if x.startswith("Read these")]:
        m = match(rv, "page", "prescription sentence", p, r"([\d,]+) of the ([\d,]+) prescription labels list none, ([\d,]+) of them for a medicine taken by mouth", txt, "prescription sentence")
        if m:
            rv.eq("page", "prescription sentence", "none", p, tuple(n_(m.group(k)) for k in range(1, 4)),
                  (len(rx), a["prescription"], rx_mouth), "prescription none, of, by mouth")
    m = re.search(r"Red 3 and ([\d,]+) D&C colors", pg.first("fd-examples") or "")
    if m:
        rv.eq("page", "what none covers", "D&C colours", p, n_(m.group(1)),
              len([d for d in D["dyes"] if d["group"] == "d-and-c"]), "the D&C colours counted")
    for hid, rows in (("nl-otc", otc), ("nl-rx", rx)):
        m = match(rv, "page", "list heading", p, r"^The ([\d,]+) ", pg.heading(hid), hid)
        if m:
            rv.eq("page", "list heading", hid, p, n_(m.group(1)), len(rows), f"the heading {hid}")
    sec = pg.section("nl-otc")
    nt = pg.first_in(sec, "fd-note") if sec else None
    m = match(rv, "page", "the OTC note", p, r"Of the ([\d,]+) over-the-counter labels, ([\d,]+) list none of the FD&C or D&C colors and ([\d,]+) list at least one\. ([\d,]+) of the ([\d,]+) list another color", nt, "OTC note")
    groups = {r["slug"]: r["groups"] for r in F["labels"]}
    names = {g["id"]: g["name"] for g in F["groups"]}
    if m:
        other = sum(any(g in groups.get(r["slug"], []) for g in OTHER_COLOURS) for r in otc)
        got = tuple(n_(m.group(k)) for k in range(1, 6))
        rv.eq("page", "the OTC note", "none", p, got, (a["otc"], len(otc), a["otc"] - len(otc), other, len(otc)),
              "of OTC, none, at least one, another colour, of none")
        rv.check("parts", "the OTC note", "none", p, None if got[1] + got[2] == got[0] else "the parts do not make the whole",
                 f"{got[1]} + {got[2]} against {got[0]}")
    no_inactive = sum(not groups.get(r["slug"]) for r in none)
    m = re.search(r"([\d,]+) labels? here lists? no inactive ingredient at all", nt or "")
    rv.eq("page", "the OTC note", "no inactive", p, n_(m.group(1)) if m else 0, no_inactive, "labels here listing no inactive ingredient")
    sec = pg.section("nl-rx")
    nt = pg.first_in(sec, "fd-note") if sec else None
    m = match(rv, "page", "the prescription note", p, r"([\d,]+) of these ([\d,]+) (?:is|are) not taken by mouth", nt, "prescription note")
    if m:
        rv.eq("page", "the prescription note", "not by mouth", p, (n_(m.group(1)), n_(m.group(2))), (len(rx) - rx_mouth, len(rx)), "not by mouth, of")
    tabs = pg.tables()
    if len(tabs) < 2:
        rv.unread("page", "lists", "none", p, f"{len(tabs)} tables on the page, two expected")
        return
    for rows, want, what in ((tabs[0], otc, "the OTC list"), (tabs[1], rx, "the prescription list")):
        rv.eq("page", "lists", what, p, sorted(r.slug for r in rows), sorted(r["slug"] for r in want), what)
        by = {r["slug"]: r for r in want}
        for row in rows:
            if row.slug not in by:
                continue
            gs = groups.get(row.slug, [])
            oth = [names.get(g, g) for g in OTHER_COLOURS if g in gs]
            rv.eq("page", "the none columns", row.slug, p, row.by_label.get("Other colors listed"),
                  ", ".join(oth) if oth else "None of those", "other colours listed")
            rv.eq("page", "the none columns", row.slug, p, row.by_label.get("Inactive ingredients listed"),
                  f"{len(gs):,}" if gs else "None", "inactive ingredients listed")
    yes = {r.slug for r in tabs[0]} | {r.slug for r in tabs[1]}
    both = sorted({r.slug for r in tabs[0]} & {r.slug for r in tabs[1]})
    rv.check("parts", "the none page's lists", "none", p, "a label in both lists" if both else None, ", ".join(both))
    six = sorted(s for s in yes if any(r["slug"] == s and (r["six"] or r["red_3"] or r["d_and_c"]) for r in D["labels"]))
    rv.check("parts", "the none page's lists", "none", p, "a label on the none page lists a counted colour" if six else None,
             ", ".join(six[:10]))
    rv.eq("parts", "the none page's lists", "none", p, sorted(yes), sorted(r["slug"] for r in none),
          "the none page against the labels with no FD&C or D&C colour", shape="the list is not the labels with none")
    check_methods(rv, pg, D)


def check_inactive_main(rv: Review, pg: FPage, F: dict, R: dict) -> None:
    p, a = pg.path, R["all"]
    groups = {g["id"]: g for g in F["groups"]}
    shown = sorted((g for g, rs in R["by_group"].items() if len(rs) >= R["floor"]),
                   key=lambda g: (-len(R["by_group"][g]), (groups.get(g) or {}).get("name", g).lower(), g))
    check_title_count(rv, pg, r"^Inactive ingredients in medicines: what ([\d,]+) labels list", a["labels"])
    m = match(rv, "page", "description", p, r"^([\d,]+) of the ([\d,]+) medicine labels on MoleculeFinder list (.+?), ([\d,]+) (.+?)\.(?= Every| Counted|$)", pg.description, "description")
    if m and len(shown) >= 2:
        rv.eq("page", "description", "top two", p, (n_(m.group(1)), n_(m.group(2)), m.group(3), n_(m.group(4)), m.group(5)),
              (len(R["by_group"][shown[0]]), a["labels"], groups[shown[0]]["phrase"], len(R["by_group"][shown[1]]), groups[shown[1]]["phrase"]),
              "the two most listed")
    lede = pg.first("fd-lede")
    m = match(rv, "page", "headline", p, r"^([\d,]+) of the ([\d,]+) medicine labels on MoleculeFinder list (.+?) as an inactive ingredient(?:, ([\d,]+) list (.+?) and ([\d,]+) list (.+?))?\.$", lede, "headline")
    if m and len(shown) >= 3:
        got = (n_(m.group(1)), n_(m.group(2)), m.group(3), n_(m.group(4) or "0"), m.group(5), n_(m.group(6) or "0"), m.group(7))
        want = (len(R["by_group"][shown[0]]), a["labels"], groups[shown[0]]["phrase"], len(R["by_group"][shown[1]]),
                groups[shown[1]]["phrase"], len(R["by_group"][shown[2]]), groups[shown[2]]["phrase"])
        rv.eq("page", "headline", "top three", p, got, want, "the three most listed")
    m = match(rv, "page", "headline second line", p, r"^([\d,]+) ingredients? (?:is|are) each listed by at least ([\d,]+) of the ([\d,]+) labels, one in ten\. In all the labels list ([\d,]+) different inactive ingredient codes", pg.first("fd-split"), "second line")
    if m:
        rv.eq("page", "headline second line", "shown", p, tuple(n_(m.group(k)) for k in range(1, 5)),
              (len(shown), R["floor"], a["labels"], R["codes"]), "charted groups, the floor, of, codes")
    rows = []
    for li in (n for n in pg.main.iter() if "fi-chart__row" in n.classes):
        nm = next((all_text(x) for x in li.iter() if "fi-chart__name" in x.classes), None)
        val = next((all_text(x) for x in li.iter() if "fi-chart__val" in x.classes), None)
        if nm and val:
            rows.append((nm, n_(val)))
    if not rows:
        rv.unread("page", "chart", "bars", p, "no chart rows")
    else:
        by_name = {(groups.get(g) or {}).get("name"): g for g in R["by_group"]}
        for nm, val in rows:
            g = by_name.get(nm)
            rv.eq("page", "chart", g or nm, p, val, len(R["by_group"][g]) if g else None, f"the {nm} bar")
        rv.eq("page", "chart", "bars", p, [by_name.get(nm) for nm, _ in rows], shown, "the bars and their order")
    m = match(rv, "page", "chart", p, r"^Number of the ([\d,]+) medicine labels .*? at least ([\d,]+) labels list", pg.first("fd-chart__cap"), "chart caption")
    if m:
        rv.eq("page", "chart", "caption", p, (n_(m.group(1)), n_(m.group(2))), (a["labels"], R["floor"]), "of, the floor")
    facts = pg.items(pg.section("fi-numbers"))
    cov = next((x for x in facts if x.startswith("The count covers")), None)
    m = match(rv, "page", "the numbers", p, r"covers ([\d,]+) over-the-counter and ([\d,]+) prescription labels; ([\d,]+) of the ([\d,]+) are taken by mouth", cov, "the count covers")
    if m:
        got = tuple(n_(m.group(k)) for k in range(1, 5))
        rv.eq("page", "the numbers", "covers", p, got, (a["otc"], a["prescription"], a["by_mouth"], a["labels"]), "OTC, prescription, by mouth, of")
        rv.check("parts", "the numbers", "covers", p, None if got[0] + got[1] == got[3] else "the parts do not make the whole", f"{got[0]} + {got[1]} against {got[3]}")
    nonel = next((x for x in facts if "no inactive ingredient" in x), None)
    m = re.search(r"^([\d,]+) labels? lists? no inactive ingredient", nonel or "")
    rv.eq("page", "the numbers", "lists none", p, n_(m.group(1)) if m else 0, len(R["none"]), "labels listing no inactive ingredient")
    sec = pg.section("fi-table")
    m = match(rv, "page", "table", p, r"^([\d,]+) labels, each", pg.first_in(sec, "fd-note") if sec else None, "table note")
    if m:
        rv.eq("page", "table", "count", p, n_(m.group(1)), a["labels"], "the table's stated count")
    tabs = pg.tables()
    if tabs:
        rv.eq("page", "table", "rows", p, len(tabs[0]), a["labels"], "the table's rows")
    if len(tabs) > 1:                                # the codes table: each code's label count
        for row in tabs[1]:
            if len(row.texts) >= 6 and re.fullmatch(r"[A-Z0-9]{10}", row.texts[1]):
                rv.eq("page", "the codes table", row.texts[1], p, n_(row.texts[5]), R["by_code"].get(row.texts[1], 0), f"{row.texts[1]} labels")
    kept = next((x for x in pg.items(pg.main) if x.startswith("Kept apart.")), None)
    for u, n in re.findall(r"\(\s*([A-Z0-9]{10})\s*\), near [^,]+, ([\d,]+) labels?", kept or ""):
        rv.eq("page", "kept apart", u, p, n_(n), R["by_code"].get(u, 0), f"{u} kept apart")
    check_methods(rv, pg, F)


def check_group_page(rv: Review, pg: FPage, F: dict, R: dict, gid: str, main_table: list[Row] | None) -> None:
    p, a = pg.path, R["all"]
    g = next((x for x in F["groups"] if x["id"] == gid), None)
    if not g:
        rv.check("page", "the group", gid, p, "the page's group is not in its data", gid)
        return
    lists = R["by_group"].get(gid, [])
    s = {**split(lists), "by_mouth": sum(by_mouth(r) for r in lists)}
    check_title_count(rv, pg, r"^Medicines with .+?: which of ([\d,]+) labels list it", a["labels"])
    m = match(rv, "page", "description", p, r"^([\d,]+) of the ([\d,]+) medicine labels on MoleculeFinder list (.+?): ([\d,]+) over the counter, ([\d,]+) prescription\.", pg.description, "description")
    if m:
        rv.eq("page", "description", gid, p, (n_(m.group(1)), n_(m.group(2)), m.group(3), n_(m.group(4)), n_(m.group(5))),
              (s["labels"], a["labels"], g["phrase"], s["otc"], s["prescription"]), "N of M, the ingredient, OTC, prescription")
    m = match(rv, "page", "headline", p, r"^([\d,]+) of the ([\d,]+) medicine labels on MoleculeFinder list (.+)\.$", pg.first("fd-lede"), "headline")
    if m:
        rv.eq("page", "headline", gid, p, (n_(m.group(1)), n_(m.group(2)), m.group(3)), (s["labels"], a["labels"], g["phrase"]), "N of M")
    sp = pg.first("fd-split")
    check_split(rv, pg, sp, s, a, "headline split")
    m = match(rv, "page", "by mouth", p, r"([\d,]+) of the ([\d,]+) labels taken by mouth list", sp, "by-mouth sentence")
    if m:
        rv.eq("page", "by mouth", gid, p, (n_(m.group(1)), n_(m.group(2))), (s["by_mouth"], a["by_mouth"]), "by mouth, of all taken by mouth")
    forms = pg.items(next(iter(pg.by_class("fi-forms")), None)) if pg.by_class("fi-forms") else []
    members = {c["member"]: c["unii"] for c in g["codes"]}
    covered = set()
    for f in forms:
        m = re.fullmatch(r"(.+?): ([\d,]+) labels?", f)
        if not m or m.group(1) not in members:
            rv.unread("page", "forms", gid, p, f"form line {f!r}")
            continue
        u = members[m.group(1)]
        rv.eq("page", "forms", gid, p, n_(m.group(2)), R["by_code"].get(u, 0), f"{m.group(1)}")
        covered |= {r["slug"] for r in lists if u in r["codes"]}
    if forms:
        rv.check("parts", "forms", gid, p, None if covered == {r["slug"] for r in lists} else "the forms do not cover the count",
                 f"the forms cover {len(covered)} of {len(lists)} labels")
    check_lists(rv, pg, gid, lists, F["labels"], "fi-lists", "fi-lists-not", main_table,
                lambda row: cell_lists(row.by_label.get("Inactive ingredients") or "", g["phrase"]))
    check_methods(rv, pg, F)


def check_index(rv: Review, pg: FPage, D: dict | None, F: dict | None, RD: dict | None, RF: dict | None) -> None:
    p = pg.path
    items = [n for n in pg.main.iter() if n.tag == "li" and n.parent is not None and "fd-index" in n.parent.classes]
    texts = [words(n) for n in items]
    if D and RD:
        t = next((x for x in texts if x.startswith("Food dyes")), None)
        m = match(rv, "page", "index", p, r"what ([\d,]+) labels list ([\d,]+) of the ([\d,]+) medicine labels on MoleculeFinder list at least one", t, "the dyes entry")
        if m:
            rv.eq("page", "index", "dyes", p, tuple(n_(m.group(k)) for k in range(1, 4)),
                  (RD["all"]["labels"], RD["any6"]["labels"], RD["all"]["labels"]), "title count, headline, of")
    if F and RF:
        t = next((x for x in texts if x.startswith("Inactive ingredients")), None)
        m = match(rv, "page", "index", p, r"what ([\d,]+) labels list ([\d,]+) of the ([\d,]+) medicine labels", t, "the inactive entry")
        if m:
            top = max((len(rs) for rs in RF["by_group"].values()), default=0)
            rv.eq("page", "index", "inactive", p, tuple(n_(m.group(k)) for k in range(1, 4)),
                  (RF["all"]["labels"], top, RF["all"]["labels"]), "title count, headline, of")


# ── check 2: the three forms ────────────────────────────────────────────────────────────────────
def csv_rows(text: str) -> tuple[list[str], list[dict]]:
    import csv
    import io
    rd = list(csv.reader(io.StringIO(text)))
    if not rd:
        return [], []
    head = rd[0]
    return head, [dict(zip(head, r, strict=False)) for r in rd[1:] if r]


def check_forms(rv: Review, which: str, pg: FPage | None, csv_text: str | None, data: dict, site: str) -> None:
    path = DYES if which == "dyes" else INACTIVE
    surface = f"the {which} finding"
    J = {r["slug"]: r for r in data["labels"]}
    rv.check("forms", surface, "JSON", f"{path}/data.json", "a label twice in the JSON" if len(J) != len(data["labels"]) else None)
    rv.eq("forms", surface, "licence", f"{path}/data.json", data.get("license"), LICENCE, "the JSON's licence", shape="the licence is not stated")
    if pg is not None:
        sec = pg.section("fd-data" if which == "dyes" else "fi-data")
        rv.check("forms", surface, "licence", path, None if sec is not None and LICENCE in words(sec) else "the licence is not stated",
                 "the page's data section")
        ds = next((x for x in pg.jsonld if isinstance(x, dict) and x.get("@type") == "Dataset"), None)
        rv.eq("forms", surface, "licence", path, (ds or {}).get("license"), CC0_URL, "the page's Dataset licence", shape="the licence is not stated")
        dl = {d.get("encodingFormat"): urllib.parse.urlparse(d.get("contentUrl") or "").path for d in (ds or {}).get("distribution") or []}
        rv.eq("forms", surface, "Dataset", path, dl, {"text/csv": f"{path}/data.csv", "application/json": f"{path}/data.json"}, "the Dataset's downloads")
    if csv_text is not None:
        head, rows = csv_rows(csv_text)
        want_head = list(DYES_CSV) if which == "dyes" else list(INACTIVE_CSV) + [f"lists_{g.replace('-', '_')}" for g in data["totals"]["shown"]["groups"]]
        rv.eq("forms", surface, "CSV header", f"{path}/data.csv", head, want_head, "the CSV's columns", shape="the CSV header is not the documented one")
        slugs = [urllib.parse.urlparse(r.get("moleculefinder_page", "")).path.removeprefix("/whats-in/") for r in rows]
        dup = sorted(s for s, c in Counter(slugs).items() if c > 1)
        rv.check("forms", surface, "CSV", f"{path}/data.csv", "a label twice in the CSV" if dup else None, ", ".join(dup[:10]))
        missing, extra = sorted(set(J) - set(slugs)), sorted(set(slugs) - set(J))
        rv.check("forms", surface, "CSV rows", f"{path}/data.csv", "a JSON label missing from the CSV" if missing else None, ", ".join(missing[:10]))
        rv.check("forms", surface, "CSV rows", f"{path}/data.csv", "a CSV row not in the JSON" if extra else None, ", ".join(extra[:10]))
        names = {d["id"]: d["name"] for d in data.get("dyes") or []}
        gph = {g["id"]: g["phrase"] for g in data.get("groups") or []}
        for slug, r in zip(slugs, rows, strict=False):
            j = J.get(slug)
            if not j:
                continue
            want = {"medicine": j["name"], "moleculefinder_page": f"{SITE}/whats-in/{slug}",
                    "class": "over the counter" if j["class"] == "otc" else "prescription",
                    "routes": "; ".join(j.get("routes") or []).lower(), "taken_by_mouth": taken_cell(j),
                    "dailymed_set_id": j["setid"], "label_version": "" if j.get("version") is None else str(j["version"]),
                    "label_effective_date": iso8(j.get("effective")), "dailymed_url": j["url"]}
            if which == "dyes":
                want |= {"lists_any_of_six": yn(bool(j["six"])), **{i.replace("-", "_"): yn(i in j["six"]) for i in SIX},
                         "red_3": yn(j["red_3"]), "d_and_c_colors": "; ".join(names.get(x, x) for x in j["d_and_c"]),
                         "dye_codes_listed": "; ".join(c["unii"] for c in j["codes"])}
            else:
                want |= {"inactive_ingredients": " | ".join(gph.get(x, x) for x in j["groups"]),
                         "inactive_codes": "; ".join(j["codes"]),
                         **{f"lists_{g.replace('-', '_')}": yn(g in j["groups"]) for g in data["totals"]["shown"]["groups"]}}
            multi = {"inactive_ingredients": " | ", "inactive_codes": "; ", "dye_codes_listed": "; ", "d_and_c_colors": "; ",
                     "routes": "; "}
            bad = [f"{k}: CSV {r.get(k)!r}, JSON {v!r}" for k, v in want.items()
                   if (sorted((r.get(k) or "").split(multi[k])) != sorted(v.split(multi[k])) if k in multi else r.get(k) != v)]
            rv.check("forms", surface, "CSV values", f"{path}/data.csv", "a CSV value differs from the JSON" if bad else None,
                     f"{slug}: " + "; ".join(bad[:3]))
    if pg is not None:
        tabs = pg.tables()
        if not tabs:
            rv.unread("forms", surface, "table", path, "no table on the page")
            return
        T = tabs[0]
        ts = [r.slug for r in T]
        missing, extra = sorted(set(J) - set(ts)), sorted(set(ts) - set(J))
        rv.check("forms", surface, "table rows", path, "a JSON label missing from the table" if missing else None, ", ".join(missing[:10]))
        rv.check("forms", surface, "table rows", path, "a table row not in the JSON" if extra else None, ", ".join(extra[:10]))
        dup = sorted(s for s, c in Counter(ts).items() if c > 1)
        rv.check("forms", surface, "table rows", path, "a label twice in the table" if dup else None, ", ".join(dup[:10]))
        gph = {g["id"]: g["phrase"] for g in data.get("groups") or []}
        for row in T:
            j = J.get(row.slug)
            if not j:
                continue
            got = {"name": row.texts[0] if row.texts else None, "type": row.by_label.get("Type"), "route": row.by_label.get("Route"),
                   "label": row.by_label.get("DailyMed label"), "link": row.dailymed}
            want = {"name": j["name"], "type": class_word(j["class"]), "route": taken_words(j), "label": version_words(j), "link": j["url"]}
            if which == "dyes":
                got["dyes"] = row.by_label.get("Dyes listed")
                want["dyes"] = (dye_text(j) or "None of the six") + ("Also lists Red 3" if j["red_3"] else "")
            else:
                cell = row.by_label.get("Inactive ingredients") or ""
                names = [gph.get(x, x) for x in j["groups"]]
                ok = cell_holds(cell, names) if names else cell == "None listed"
                got["ingredients"] = "the JSON's groups" if ok else cell
                want["ingredients"] = "the JSON's groups" if ok else ("; ".join(sorted(names)) or "None listed")
            bad = [f"{k}: table {got[k]!r}, JSON {want[k]!r}" for k in want if got[k] != want[k]]
            rv.check("forms", surface, "table values", path, "a table value differs from the JSON" if bad else None,
                     f"{row.slug}: " + "; ".join(bad[:3]))


def cell_holds(cell: str, names: list[str]) -> bool:
    """Whether a table cell lists exactly these names, separated by "; " (a registry name may hold a semicolon itself,
    so the cell is not split: each name is taken out, longest first, and only separators may be left)."""
    rest = re.sub(r";(?=\S)", "; ", cell)          # words() closes up a space before a full stop (".iota.")
    for nm in sorted(names, key=len, reverse=True):
        m = re.search(r"(?:^|(?<=; ))" + re.escape(nm) + r"(?=;|$)", rest)
        if not m:
            return False
        rest = rest[:m.start()] + rest[m.end():]
    return not re.sub(r"[;\s]", "", rest)


def cell_lists(cell: str, name: str) -> bool:
    return bool(re.search(r"(?:^|; )" + re.escape(name) + r"(?=;|$)", re.sub(r";(?=\S)", "; ", cell or "")))


def check_totals(rv: Review, which: str, data: dict) -> None:
    """Check 3 inside a JSON: its totals equal its own rows, and each split adds up."""
    p = f"{DYES if which == 'dyes' else INACTIVE}/data.json"
    surface = f"the {which} JSON's totals"
    t = data["totals"]

    def same(k, mine, theirs):
        rv.check("parts", surface, k, p, None if mine == theirs else "the totals are not the rows' count",
                 "" if mine == theirs else f"{k}: rows give {mine!r}, totals say {theirs!r}")

    def adds(k, s):
        rv.check("parts", surface, k, p, None if s["otc"] + s["prescription"] == s["labels"] else "the parts do not make the whole",
                 f"{k}: {s['otc']} + {s['prescription']} against {s['labels']}")
    if which == "dyes":
        R = dyes_rows(data)
        for k, mine in (("labels", R["all"]), ("any_of_six", R["any6"])):
            same(k, mine, {x: t[k][x] for x in ("labels", "otc", "prescription")})
        same("two_or_more", R["two"], t["two_or_more"]["labels"])
        same("three_or_more", R["three"], t["three_or_more"]["labels"])
        same("red_3", sorted(r["slug"] for r in R["red3"]), sorted(t["red_3"]["slugs"]))
        same("d_and_c_any", R["dc"], t["d_and_c_any"]["labels"])
        for i in SIX:
            same(f"by_dye.{i}", {x: R["dye"][i][x] for x in ("labels", "otc", "prescription")}, t["by_dye"][i])
        for k in ("labels", "any_of_six", "two_or_more", "three_or_more", "red_3", "d_and_c_any"):
            adds(k, t[k])
        for i in SIX:
            adds(f"by_dye.{i}", t["by_dye"][i])
        if t.get("routes"):
            for k in ("all", "any_of_six", "red_3"):
                base = {"all": t["labels"], "any_of_six": t["any_of_six"], "red_3": t["red_3"]}[k]["labels"]
                rv.check("parts", surface, f"routes.{k}", p, None if sum(t["routes"][k].values()) == base else "the parts do not make the whole",
                         f"routes.{k}: {sum(t['routes'][k].values())} against {base}")
        union = {r["slug"] for i in SIX for r in R["lists"][i]}
        rv.check("parts", "the headline against the dyes", "once", p, None if len(union) == t["any_of_six"]["labels"]
                 else "a label is counted twice in the headline", f"{len(union)} labels list a dye; the headline says {t['any_of_six']['labels']}")
    else:
        R = inactive_rows(data)
        same("labels", {**R["all"]}, {x: t["labels"][x] for x in ("labels", "otc", "prescription", "by_mouth")})
        same("lists_none", sorted(r["slug"] for r in R["none"]), sorted(t["lists_none"]["slugs"]))
        same("codes", R["codes"], t["codes"])
        same("groups", R["groups"], t["groups"])
        same("shown.floor", R["floor"], t["shown"]["floor"])
        adds("labels", t["labels"])
        for g in data["groups"]:
            rs = R["by_group"].get(g["id"], [])
            same(f"group {g['id']}", {**split(rs), "by_mouth": sum(by_mouth(r) for r in rs)},
                 {x: g[x] for x in ("labels", "otc", "prescription", "by_mouth")})
        rv.check("parts", surface, "lists none", p, None if len(R["none"]) + sum(1 for r in data["labels"] if r["codes"]) == len(data["labels"])
                 else "the parts do not make the whole")


# ── check 5: the label set ──────────────────────────────────────────────────────────────────────
def check_label_set(rv: Review, products: dict, D: dict | None, F: dict | None, pages: dict[str, FPage],
                    whats_in: dict[str, dict]) -> list[str]:
    declared = {p["slug"]: p for p in medicine_labels(products)}
    not_read_route: list[str] = []
    for which, data, path in (("dyes", D, DYES), ("inactive", F, INACTIVE)):
        if not data:
            continue
        surface = f"the {which} finding"
        slugs = [r["slug"] for r in data["labels"]]
        rv.eq("labels", surface, "count", path, len(slugs), len(declared), "the labels against the declared set",
              shape="the label set is not the declared set")
        missing, extra = sorted(set(declared) - set(slugs)), sorted(set(slugs) - set(declared))
        rv.check("labels", surface, "set", path, "a declared label is not in the finding" if missing else None, ", ".join(missing[:10]))
        rv.check("labels", surface, "set", path, "a label not in the declared set" if extra else None, ", ".join(extra[:10]))
        for k in ("slug", "setid"):
            dup = sorted(v for v, c in Counter(r[k] for r in data["labels"]).items() if c > 1)
            rv.check("labels", surface, f"no {k} twice", path, f"a {k} twice" if dup else None, ", ".join(dup[:10]))
        for r in data["labels"]:
            src = (declared.get(r["slug"]) or {}).get("source") or {}
            if not src:
                continue
            got = (r["setid"], r.get("version"), r["class"])
            want = (src.get("setid"), src.get("version"), label_class(src.get("doc_type")))
            rv.check("labels", surface, r["slug"], path, None if got == want else "the label is not the snapshot's",
                     "" if got == want else f"{r['slug']}: set id, version, class {got} against the snapshot's {want}")
            if r.get("routes") is None and which == "dyes":
                not_read_route.append(r["slug"])
    for path, pg in sorted(pages.items()):
        for t in pg.tables():
            for row in t:
                if not row.slug:
                    continue
                src = (declared.get(row.slug) or {}).get("source") or {}
                if not src:
                    rv.check("labels", "a label row", row.slug, path, "a row names a label not in the snapshot", row.slug)
                    continue
                q = urllib.parse.parse_qs(urllib.parse.urlparse(row.dailymed or "").query)
                rv.eq("labels", "a label row's DailyMed link", row.slug, path, (q.get("setid") or [None])[0], src.get("setid"),
                      f"{row.slug} set id", shape="the link is not the label's own record")
                lab = row.by_label.get("DailyMed label") or ""
                m = re.match(r"Version (\d+)", lab)
                rv.eq("labels", "a label row's version", row.slug, path, int(m.group(1)) if m else None, src.get("version"),
                      f"{row.slug} version", shape="the version is not the snapshot's")
                if row.by_label.get("Route") == "Not read":
                    rv.check("labels", "a label row's route", row.slug, path, "the route reads Not read", row.slug)
                else:
                    rv.check("labels", "a label row's route", row.slug, path, None)
    for slug, r in sorted(whats_in.items()):
        st = r.get("status")
        rv.check("labels", "the label's page", slug, f"/whats-in/{slug}",
                 None if st == 200 else "the label's page does not answer" if "why" not in r else "the label's page was not read",
                 f"/whats-in/{slug}: {st if st else r.get('why')}")
    return not_read_route


# ── check 6: the labels the text names ──────────────────────────────────────────────────────────
def check_named(rv: Review, pages: dict[str, FPage], D: dict | None, F: dict | None, rec: dict) -> None:
    pg = pages.get(DYES)
    if pg is not None and D:
        J = {r["slug"]: r for r in D["labels"]}
        ex = next(iter(pg.by_class("fd-examples")), None)
        sides: dict[str, list[str]] = {"lists": [], "lists_none": []}
        if ex is not None:
            for span in (k for k in ex.kids if isinstance(k, Node)):
                t = words(span)
                side = "lists_none" if "list none of the six" in t else "lists"
                sides[side] += [href_of(a)[len("/whats-in/"):] for a in span.iter() if a.tag == "a" and href_of(a).startswith("/whats-in/")]
        want = (D.get("examples") or {})
        for side in ("lists", "lists_none"):
            rv.eq("named", "the familiar labels", side, DYES, sides[side], [e["slug"] for e in want.get(side) or []],
                  f"the {side} sentence against the data's examples", shape="the sentence names other labels than the data")
            for s in sides[side]:
                j, mine = J.get(s), rec["labels"].get(s)
                ok = j is not None and bool(j["six"]) == (side == "lists")
                rv.check("named", "the familiar labels", s, DYES, None if ok else "a named label does not have that status",
                         f"{s} named under {side}: " + ("not in the data" if j is None else f"lists {j['six'] or 'none of the six'}"))
                ok = mine is not None and bool(mine["six"]) == (side == "lists")
                rv.check("named", "the familiar labels, recomputed", s, DYES, None if ok else "a named label does not have that status",
                         f"{s} named under {side}: recomputed " + ("absent" if mine is None else f"{mine['six'] or 'none of the six'}"))
        red = pg.section("fd-red3")
        named = [href_of(a)[len("/whats-in/"):] for a in (red.iter() if red else []) if a.tag == "a" and href_of(a).startswith("/whats-in/")]
        rv.eq("named", "the Red No. 3 labels", "red 3", DYES, sorted(named), sorted(r["slug"] for r in D["labels"] if r["red_3"]),
              "the labels the Red No. 3 sentence names", shape="the sentence names other labels than the data")
        for s in named:
            rv.check("named", "the Red No. 3 labels, recomputed", s, DYES, None if (rec["labels"].get(s) or {}).get("red_3") else "a named label does not have that status", s)
    pg = pages.get(INACTIVE)
    if pg is not None and F:
        li = next((n for n in pg.section("fi-numbers").iter() if n.tag == "li" and "no inactive ingredient" in words(n)), None) if pg.section("fi-numbers") else None
        named = [href_of(a)[len("/whats-in/"):] for a in (li.iter() if li else []) if a.tag == "a" and href_of(a).startswith("/whats-in/")]
        rv.eq("named", "the labels listing no inactive ingredient", "lists none", INACTIVE, sorted(named),
              sorted(r["slug"] for r in F["labels"] if not r["codes"]), "the labels named", shape="the sentence names other labels than the data")
        for s in named:
            rv.check("named", "the labels listing no inactive ingredient, recomputed", s, INACTIVE,
                     None if not (rec["labels"].get(s) or {"codes": [1]})["codes"] else "a named label does not have that status", s)


# ── check 7: the dates ──────────────────────────────────────────────────────────────────────────
def check_dates(rv: Review, pages: dict[str, FPage], D: dict | None, F: dict | None, refreshed: str | None) -> None:
    for path, pg in sorted(pages.items()):
        if path == FINDINGS:
            continue
        data = F if path.startswith(INACTIVE) else D
        if not data:
            continue
        stated = data.get("snapshot_date")
        rv.eq("date", "the data's own date", "snapshot", path, stated, refreshed, "the JSON's snapshot date against meta.json",
              shape="the published data is not the snapshot main holds")
        text = all_text(pg.main)
        found = re.findall(r"data refreshed (\d{1,2} [A-Z][a-z]+ \d{4})", text)
        if not found:
            rv.unread("date", "data refreshed", "refreshed", path, "no 'data refreshed' date on the page")
        for w in found:
            rv.eq("date", "data refreshed", "refreshed", path, iso_of(w), stated, "the date the page states", shape="the page's date is not the data's")
        if data is D:
            for w in re.findall(r"read on fda\.gov or in the Federal Register on (\d{1,2} [A-Z][a-z]+ \d{4})", text):
                rv.eq("date", "the FDA pages read", "fda", path, iso_of(w), str(D["fda"]["read"]), "the FDA read date", shape="the page's date is not the data's")
        for w in re.findall(r"checked against the (?:FDA's )?registry on (\d{1,2} [A-Z][a-z]+ \d{4})", text):
            rv.eq("date", "the registry checked", "registry", path, iso_of(w), str(data["registry"]["checked"]), "the registry date", shape="the page's date is not the data's")


# ── check 8: the pitched numbers ────────────────────────────────────────────────────────────────
def load_pitched(path: Path = PITCHED) -> dict:
    data = yaml.safe_load(path.read_text()) or {}
    for p in data.get("pitches") or []:
        for k in ("id", "finding", "page", "sent", "to", "figures", "baseline"):
            if not p.get(k):
                raise ValueError(f"pitched_numbers.yaml {p.get('id')}: {k} is required")
        for f in p["figures"]:
            for k in ("id", "words", "value", "data", "confirmed", "evidence"):
                if k not in f:
                    raise ValueError(f"pitched_numbers.yaml {p['id']} {f.get('id')}: {k} is required")
    return data


def dig(d: dict, path: str):
    for k in path.split("."):
        d = (d or {}).get(k) if isinstance(d, dict) else None
    return d


def check_pitched(rv: Review, pitched: dict, D: dict | None, pages: dict[str, FPage], base_dir: Path) -> list[dict]:
    """Each pitched figure against the live JSON and the live page. Returns the table the report prints."""
    table = []
    printed = page_figures(pages.get(DYES))
    for p in pitched.get("pitches") or []:
        if p["finding"] != "dyes-in-medicines":
            continue
        baseline = json.loads((base_dir / p["baseline"]).read_text())
        for f in p["figures"]:
            live = dig(D["totals"], f["data"]) if D else None
            live_of = dig(D["totals"], f["of_data"]) if D and f.get("of_data") else None
            on_page = printed.get(f["data"])
            on_page_of = printed.get(f.get("of_data")) if f.get("of_data") else None
            holds = live == f["value"] and (f.get("of") is None or live_of == f["of"])
            page_holds = on_page is None or (on_page == f["value"] and (f.get("of") is None or on_page_of in (None, f["of"])))
            row = {"pitch": p["id"], "figure": f["id"], "words": f["words"], "value": f["value"], "of": f.get("of"),
                   "sent": str(p["sent"]), "to": p["to"], "confirmed": f["confirmed"], "evidence": f["evidence"],
                   "live": live, "live_of": live_of, "on_page": on_page, "on_page_of": on_page_of,
                   "holds": bool(D) and holds and page_holds}
            if not D:
                row["holds"] = None
                rv.notes.append(f"Pitched {f['id']}: the dyes data.json was not read, so the pitched number was not checked.")
            elif not (holds and page_holds):
                why = moved_labels(baseline, D, f["data"])
                row["why"] = why
                rv.check("pitched", "the dyes finding", f["id"], p["page"], "a pitched number moved",
                         f"pitched {f['words']} on {p['sent']} ({'confirmed' if f['confirmed'] else 'UNCONFIRMED'}) to {p['to']}; "
                         f"live: {live}" + (f" of {live_of}" if f.get("of_data") else "") + f", the page prints {on_page}"
                         + (f" of {on_page_of}" if on_page_of is not None else "") + f". Labels that changed: {why or 'none named'}")
            else:
                rv.check("pitched", "the dyes finding", f["id"], p["page"], None)
            table.append(row)
    return table


def page_figures(pg: FPage | None) -> dict:
    """The dyes page's printed headline figures, keyed by the totals path they state."""
    if pg is None:
        return {}
    out = {}
    m = re.search(r"^([\d,]+) of the ([\d,]+) medicine labels", pg.first("fd-lede") or "")
    if m:
        out["any_of_six.labels"], out["labels.labels"] = n_(m.group(1)), n_(m.group(2))
    m = re.search(r"([\d,]+) of the ([\d,]+) over-the-counter labels and ([\d,]+) of the ([\d,]+) prescription labels", pg.first("fd-split") or "")
    if m:
        out["any_of_six.otc"], out["labels.otc"] = n_(m.group(1)), n_(m.group(2))
        out["any_of_six.prescription"], out["labels.prescription"] = n_(m.group(3)), n_(m.group(4))
    red = pg.section("fd-red3")
    m = re.search(r"([\d,]+) labels? lists? FD&C Red No\. 3", words(red) if red else "")
    if m:
        out["red_3.labels"] = n_(m.group(1))
    return out


def moved_labels(baseline: dict, D: dict, figure: str) -> list[str]:
    """Which labels moved since the pitch, and why: a label that joined or left the count, one whose class or dyes
    changed (with its new label version, when it has one); then, in one line, the labels with a new version only."""
    was = baseline["labels"]
    now = {r["slug"]: r for r in D["labels"]}
    out = [f"{s} left the count" for s in sorted(set(was) - set(now))]
    out += [f"{s} joined the count ({'lists ' + ', '.join(now[s]['six']) if now[s]['six'] else 'none of the six'})"
            for s in sorted(set(now) - set(was))]
    version_only = []
    for s in sorted(set(was) & set(now)):
        w, n = was[s], now[s]
        why = []
        if n["class"] != w["class"]:
            why.append(f"class {w['class']} to {n['class']}")
        if sorted(n["six"]) != sorted(w["six"]) or bool(n["red_3"]) != bool(w["red_3"]):
            why.append(f"dyes {w['six'] or 'none'}{' + Red 3' if w['red_3'] else ''} to "
                       f"{n['six'] or 'none'}{' + Red 3' if n['red_3'] else ''}")
        if why:
            if n.get("version") != w.get("version"):
                why.append(f"label version {w.get('version')} to {n.get('version')}")
            out.append(f"{s}: " + "; ".join(why))
        elif n.get("version") != w.get("version"):
            version_only.append(s)
    if version_only:
        out.append(f"a new label version with the same dyes and class: {', '.join(version_only[:20])}"
                   + (f" and {len(version_only) - 20} more" if len(version_only) > 20 else ""))
    return out


# ── check 9: citations; check 10: share images and feeds ────────────────────────────────────────
def citation_links(pages: dict[str, FPage]) -> list[dict]:
    out = []
    for path, pg in sorted(pages.items()):
        for a in pg.main.iter():
            if a.tag != "a":
                continue
            h = a.attrs.get("href") or ""
            host = urllib.parse.urlparse(h).netloc
            if any(host == x or host.endswith("." + x) for x in CITATION_HOSTS):
                out.append({"page": path, "url": h, "text": all_text(a)})
    return out


def api_for(url: str) -> str | None:
    """The publisher's own API address for a page that shows automated readers a 'Request Access' page."""
    u = urllib.parse.urlparse(url)
    if u.netloc.endswith("ecfr.gov"):
        m = re.search(r"/title-(\d+)/.*section-([\d.]+)$", u.path)
        if m:
            return f"https://www.ecfr.gov/api/versioner/v1/versions/title-{m.group(1)}.json?section={m.group(2)}"
    if u.netloc.endswith("federalregister.gov"):
        m = re.search(r"/documents/\d{4}/\d\d/\d\d/([\w-]+)/", u.path)
        if m:
            return f"https://www.federalregister.gov/api/v1/documents/{m.group(1)}.json?fields[]=html_url&fields[]=title"
    return None


def api_answers(url: str, r: dict) -> bool:
    if r.get("status") != 200:
        return False
    try:
        j = json.loads(r.get("body") or "")
    except ValueError:
        return False
    if "ecfr.gov" in url:
        v = j.get("content_versions") or []
        return bool(v) and not v[-1].get("removed")
    if "federalregister.gov" in url:
        return bool(j.get("html_url"))
    return False


def check_citations(rv: Review, pages: dict[str, FPage], fetch_fn, workers: int, pause: float) -> dict:
    links = citation_links(pages)
    urls = sorted({x["url"] for x in links})
    got = read_many(urls, fetch_fn, workers=workers, pause=pause) if urls else {}
    state: dict[str, str] = {}
    apis = {u: api_for(u) for u in urls}
    need_api = [u for u in urls if "why" not in got[u] and (got[u]["status"] in (403, 429) or BOT_PAGE.search(got[u].get("body") or ""))
                and apis[u]]
    api_got = read_many([apis[u] for u in need_api], fetch_fn, workers=workers, pause=pause) if need_api else {}
    for u in urls:
        r = got[u]
        if "why" in r:
            state[u] = f"not read: {r['why']}"
        elif u in need_api:
            state[u] = ("answers through the publisher's API (the page itself serves automated readers a Request Access page)"
                        if api_answers(u, api_got.get(apis[u]) or {}) else "not read: a Request Access page, and the API did not answer")
        elif r["status"] == 200 and not BOT_PAGE.search(r.get("body") or ""):
            state[u] = "answers"
        elif BOT_PAGE.search(r.get("body") or ""):
            state[u] = "not read: a Request Access page"
        else:
            state[u] = f"does not answer: HTTP {r['status']}"
    for u in urls:
        s = state[u]
        rv.check("citations", "a cited link", u, next(x["page"] for x in links if x["url"] == u),
                 None if s.startswith("answers") else ("the link does not answer" if s.startswith("does not") else "the link was not read"),
                 f"{u}: {s}")
    for x in links:                                   # the text names the section its link points at
        m = re.search(r"\b21 CFR (\d+\.\d+)", x["text"])
        if m:
            rv.check("citations", "a citation's text and its link", x["text"], x["page"],
                     None if x["url"].endswith(f"section-{m.group(1)}") else "the text names another section than the link",
                     f"{x['text']} links {x['url']}")
    for words_, target in CITED.items():
        where = [x for x in links if words_ in x["text"] and target in x["url"]]
        rv.check("citations", "the cited rules", words_, where[0]["page"] if where else DYES,
                 None if where else "a cited rule is not linked", f"{words_}: linked on {len(where)} page(s)")
    return {"links": len(links), "urls": state}


def check_share(rv: Review, pages: dict[str, FPage], fetch_fn, workers: int, pause: float) -> int:
    want: dict[str, tuple[str, str]] = {}
    for path, pg in sorted(pages.items()):
        img = pg.meta.get("og:image")
        rv.check("share", "a page's share image", path, path, None if img else "the page has no share image", path)
        for key in ("og:image", "twitter:image"):
            if pg.meta.get(key):
                want.setdefault(pg.meta[key], (path, "image/"))
        for href, _typ in pg.alternates:
            want.setdefault(urllib.parse.urljoin(SITE, href), (path, "xml"))
    got = read_many(sorted(want), fetch_fn, workers=workers, pause=pause) if want else {}
    for u, (path, kind) in sorted(want.items()):
        r = got[u]
        surface = "a share image" if kind == "image/" else "a feed"
        if "why" in r:
            rv.check("share", surface, u, path, "it was not read", f"{u}: {r['why']}")
        else:
            ok = r["status"] == 200 and kind in (r.get("type") or "")
            rv.check("share", surface, u, path, None if ok else "it does not answer with the right type",
                     f"{u}: HTTP {r['status']}, {r.get('type')}")
    return len(want)


# ── the report ──────────────────────────────────────────────────────────────────────────────────
def class_key(f: dict) -> str:
    return f"{CHECKS[f['check']][1]} / {f['surface']} / {f['shape']}"


def summarise(rv: Review) -> dict[str, dict]:
    classes: dict[str, dict] = {}
    for f in rv.findings:
        k = class_key(f)
        c = classes.setdefault(k, {"check": f["check"], "number": CHECKS[f["check"]][0], "surface": f["surface"],
                                   "shape": f["shape"], "count": 0, "records": [], "addresses": [], "details": []})
        c["count"] += 1
        if f["subject"] not in c["records"]:
            c["records"].append(f["subject"])
        if f["path"] not in c["addresses"]:
            c["addresses"].append(f["path"])
        c["details"].append(f"{f['path']} ({f['subject']})" + (f": {f['detail']}" if f["detail"] else ""))
    for c in classes.values():
        c["of"] = rv.compared[(c["check"], c["surface"])]
        c["noun"] = f"{CHECKS[c['check']][1]} checks on {c['surface']}"
        c["queue"] = "at once" if c["check"] in IMMEDIATE else "on two consecutive runs"
    return dict(sorted(classes.items(), key=lambda kv: (ORDER[kv[1]["check"]], -kv[1]["count"], kv[0])))


def queue(out: Path, classes: dict, prev: dict | None, day: dt.date) -> list[str]:
    """QUEUE.md, once per class: "a pitched number moved" and the recomputation class the first day they are seen,
    every other class on the second consecutive run (the plan's rule; the drawing review's line format)."""
    q = out / "QUEUE.md"
    text = q.read_text() if q.exists() else ("# Trust reviews: the queue\n\nOne line per finding class seen on two "
                                             "consecutive runs, added once, the day it qualifies. Tick it when the "
                                             "fix is merged or a ruling covers it.\n\n")
    added = []
    for k, c in classes.items():
        marker = f"<!-- {NAME}: {k} -->"
        if marker in text:
            continue
        if c["check"] in IMMEDIATE or k in ((prev or {}).get("classes") or {}):
            loud = "**A PITCHED NUMBER MOVED** " if c["check"] == "pitched" else ""
            text += (f"- [ ] {day.isoformat()} {NAME}: {loud}**{k}**: {c['count']} of {c['of']} {c['noun']} "
                     f"({', '.join(str(x) for x in c['records'][:5])}{', ...' if len(c['records']) > 5 else ''}). "
                     f"Recommended: {CHECKS[c['check']][2]} {marker}\n")
            added.append(k)
    if added:
        q.write_text(text)
    return added


def verdict_line(classes: dict, numbers: int, read: int, not_read: int) -> str:
    moved = [c for c in classes.values() if c["check"] == "pitched"]
    head = (f"VERDICT: A PITCHED NUMBER MOVED ({', '.join(str(r) for c in moved for r in c['records'])}). " if moved else "VERDICT: ")
    return (f"{head}{len(classes)} finding class{'es' if len(classes) != 1 else ''} found "
            f"({sum(c['count'] for c in classes.values()):,} findings); {numbers:,} numbers checked; {read:,} addresses "
            f"read; {not_read:,} not read.")


def render_md(d: dict) -> str:
    L = [d["verdict"], "", f"# Findings arithmetic, {d['date']}", ""]
    w = L.append
    w(f"Trust review 5 (`mfetl review findings`, ETL `moleculefinder_etl/review/findings.py`), run {d['time']} against "
      f"the snapshot ETL `{d['etl_commit']}` holds (refreshed {d['snapshot_refreshed']}). Read-only: it changed nothing. "
      f"Every findings address, every row, every label: no sampling. {d['seconds']:.0f} seconds. "
      f"Previous run: {d['previous_run'] or 'none (this is the first)'}.")
    w("")
    w("## Pitched numbers")
    w("")
    w("What was told to people outside (`review/pitched_numbers.yaml`), against the live data and the live page.")
    w("")
    w("| figure | pitched | sent, to | confirmed from a file | live data | live page | holds |")
    w("|---|---|---|---|---|---|---|")
    for r in d["pitched"]:
        of = f" of {r['live_of']}" if r.get("live_of") is not None else ""
        pof = f" of {r['on_page_of']}" if r.get("on_page_of") is not None else ""
        w(f"| {r['figure']} | {r['words']} | {r['sent']}, {r['to']} | {'yes' if r['confirmed'] else 'NO (unconfirmed)'}: "
          f"{r['evidence']} | {r['live']}{of} | {r['on_page'] if r['on_page'] is not None else 'not printed'}{pof} | "
          f"{'yes' if r['holds'] else 'not checked' if r['holds'] is None else '**NO: MOVED**'} |")
    for r in d["pitched"]:
        if r.get("why"):
            w(f"- {r['figure']}: labels that changed since it was sent: {'; '.join(r['why']) or 'none named'}")
    w("")
    w("## Findings, class by class")
    w("")
    w("Each class is the check, the surface it was read on, and the shape. The count is of the checks of that kind "
      "made on that surface. A class is queued on two consecutive runs, except the pitched and the recomputed classes, "
      "which are queued the day they are seen.")
    w("")
    if not d["classes"]:
        w("None.")
    for k, c in d["classes"].items():
        w(f"### {c['number']}. {k}")
        w(f"- **{c['count']:,} of {c['of']:,} {c['noun']}**, on {len(c['addresses']):,} address(es); since the last run: "
          f"{c['change']}" + (f" (in: {', '.join(map(str, c['added']))})" if c.get("added") else "")
          + (f" (out: {', '.join(map(str, c['left']))})" if c.get("left") else "") + f"; queued {c['queue']}.")
        for det in c["details"][:SHOWN]:
            w(f"  - {det}")
        if len(c["details"]) > SHOWN:
            w(f"  - and {len(c['details']) - SHOWN:,} more (the JSON lists every one)")
        w(f"- Recommended: {CHECKS[c['check']][2]}")
        w("")
    if d["gone_since_last_run"]:
        w("Classes found last run and not this run: " + "; ".join(d["gone_since_last_run"]) + ".")
        w("")
    if d["queued_today"]:
        w("Added to QUEUE.md today: " + "; ".join(d["queued_today"]) + ".")
        w("")
    w("## The recomputation (check 4)")
    w("")
    rc = d["recomputation"]
    w(f"Rebuilt by UNII from each label's own ingredient list against `colour_additives.yaml` and `inactive_groups.yaml`, "
      f"in this module (it does not import `transform/findings.py`), for the labels the snapshot's products.json declares: **{rc['compared']:,} counts compared, "
      f"{rc['differ']:,} differ**. Each label's ingredients came from "
      + ", ".join(f"{k} ({v:,} labels)" for k, v in sorted(rc["origin"].items()))
      + f"; the cache read: `{str(rc['cache']).replace(str(Path.home()), '~')}`. Not recomputed: the by-mouth counts "
      f"(the routes are in neither the products file nor the label; checks 1 and 3 hold them to the rows).")
    for g in rc["gaps"][:20]:
        w(f"- {g}")
    w("")
    w("## Numbers checked, by check")
    w("")
    w("| # | check | numbers checked | findings |")
    w("|---|---|---|---|")
    for k, v in d["checked"].items():
        w(f"| {CHECKS[k][0]} | {CHECKS[k][1]} | {v['checked']:,} | {v['findings']:,} |")
    w("")
    w("## Denominators")
    w("")
    for k, v in d["denominators"].items():
        w(f"- {k}: {v}")
    w("")
    w("## Addresses read")
    w("")
    a = d["addresses"]
    w(f"{a['read']:,} read, {a['not_read']:,} not read: {len(a['pages'])} findings pages, {len(a['downloads'])} downloads, "
      f"{a['label_pages']:,} label pages (HEAD), {a['share']:,} share images and feeds, {a['citation_urls']:,} cited links "
      f"({a['citation_links']:,} links on the pages).")
    for p in a["pages"]:
        w(f"- {SITE}{p}")
    for p in a["downloads"]:
        w(f"- {SITE}{p}")
    for x in a["not_read_list"]:
        w(f"- NOT READ {x['url']}: {x['why']}")
    w("")
    w("Cited links:")
    for u, s in a["citations"].items():
        w(f"- {u}: {s}")
    if d["routes_not_read"]:
        w("")
        w("Labels whose route reads \"Not read\": " + ", ".join(d["routes_not_read"]) + ".")
    for n in d["notes"]:
        w("")
        w(f"Note: {n}")
    return "\n".join(L).rstrip() + "\n"


# ── the run ─────────────────────────────────────────────────────────────────────────────────────
def expected_pages(D: dict | None, F: dict | None) -> list[str]:
    out = [FINDINGS]
    if D:
        out += [DYES] + [f"{DYES}/{i}" for i in DYE_PAGES]
        if F:
            out.append(NONE)
    if F:
        out += [INACTIVE] + [f"{INACTIVE}/{g}" for g in F.get("pages") or []]
    return out


def run(snap: Path = SNAP, out: Path = DEFAULT_OUT, day: dt.date | None = None, fetch_fn=fetch, site: str = SITE,
        workers: int = WORKERS, pause: float = PAUSE, pitched_path: Path = PITCHED, seeds: Path = SEEDS,
        label_caches=None) -> dict:
    day = day or dt.date.today()
    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    rv = Review()
    meta = {"time": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "commit": shared.etl_commit()}
    refreshed = json.loads((snap / "meta.json").read_text()).get("refreshed")
    products = json.loads((snap / "products.json").read_text())
    snap_d = json.loads((snap / "findings" / "dyes-in-medicines.json").read_text())
    snap_i = json.loads((snap / "findings" / "inactive-ingredients.json").read_text())
    tables = load_tables(seeds)
    spl = label_cache(label_caches) if label_caches is not None else label_cache()
    rec = recompute(products, tables, spl)
    pitched = load_pitched(pitched_path)
    not_read: list[dict] = []
    # the downloads first: they are each page's own data
    dl = read_many([site + p for p in DOWNLOADS], fetch_fn, workers=workers, pause=pause)
    body: dict[str, str] = {}
    for p in DOWNLOADS:
        r = dl[site + p]
        if "why" in r or r["status"] != 200:
            not_read.append({"url": SITE + p, "why": r.get("why") or f"HTTP {r['status']}"})
            continue
        body[p] = r["body"]
        want = "text/csv" if p.endswith(".csv") else "application/json"
        rv.check("forms", "a download's type", p, p, None if want in (r.get("type") or "") else "a download answers with another type",
                 f"{p}: {r.get('type')}")
    D = F = None
    for p, setter in ((f"{DYES}/data.json", "D"), (f"{INACTIVE}/data.json", "F")):
        if p in body:
            try:
                val = json.loads(body[p])
            except ValueError as e:
                not_read.append({"url": SITE + p, "why": f"not JSON: {e}"})
                continue
            if setter == "D":
                D = val
            else:
                F = val
    # the live file against the snapshot main holds (a deploy lag is a fact worth stating; check 4's surface)
    for name, live, mine in (("dyes", D, snap_d), ("inactive", F, snap_i)):
        if live is not None:
            same = live.get("labels") == mine.get("labels") and live.get("totals") == mine.get("totals")
            rv.check("recomputed", f"the live {name} file against the snapshot", name,
                     f"{DYES if name == 'dyes' else INACTIVE}/data.json",
                     None if same else "the live file is not the snapshot main holds",
                     "the labels or totals differ from data/snapshots/findings")
    # the pages
    sm = read_many([site + "/sitemap.xml"], fetch_fn, workers=1, pause=0)[site + "/sitemap.xml"]
    in_sitemap: list[str] = []
    if sm.get("status") == 200:
        try:
            in_sitemap = [x for x in sitemap_paths(sm["body"], site) if x == FINDINGS or x.startswith(FINDINGS + "/")]
        except Exception as e:                      # noqa: BLE001 (a sitemap it cannot read is said, not fatal)
            rv.notes.append(f"The sitemap did not parse ({e}).")
    else:
        rv.notes.append("The sitemap could not be read: the findings addresses come from the data alone.")
    want_pages = expected_pages(D or snap_d, F or snap_i)
    for p in sorted(set(in_sitemap) - set(want_pages)):
        rv.check("labels", "the findings addresses", p, "/sitemap.xml", "the sitemap lists a findings address the data does not make", p)
    for p in want_pages:
        rv.check("labels", "the findings addresses", p, "/sitemap.xml",
                 None if not in_sitemap or p in in_sitemap else "a findings address the sitemap does not list", p)
    got = read_many([site + p for p in want_pages], fetch_fn, workers=workers, pause=pause)
    pages: dict[str, FPage] = {}
    for p in want_pages:
        r = got[site + p]
        if "why" in r or r["status"] != 200 or not r.get("body"):
            not_read.append({"url": SITE + p, "why": r.get("why") or f"HTTP {r['status']}"})
            continue
        try:
            pages[p] = FPage(p, r["body"])
        except Exception as e:                      # noqa: BLE001
            not_read.append({"url": SITE + p, "why": f"could not be taken apart: {type(e).__name__}: {e}"[:200]})
    RD = dyes_rows(D) if D else None
    RF = inactive_rows(F) if F else None
    main_dyes = pages[DYES].tables()[0] if DYES in pages and pages[DYES].tables() else None
    main_inactive = pages[INACTIVE].tables()[0] if INACTIVE in pages and pages[INACTIVE].tables() else None
    for p, pg in pages.items():
        try:
            if p == FINDINGS:
                check_index(rv, pg, D, F, RD, RF)
            elif p == DYES and D:
                check_dyes_main(rv, pg, D, RD)
            elif p == NONE and D and F:
                check_none_page(rv, pg, D, F, RD)
            elif p.startswith(DYES + "/") and D:
                check_dye_page(rv, pg, D, RD, p.rsplit("/", 1)[1], main_dyes)
            elif p == INACTIVE and F:
                check_inactive_main(rv, pg, F, RF)
            elif p.startswith(INACTIVE + "/") and F:
                check_group_page(rv, pg, F, RF, p.rsplit("/", 1)[1], main_inactive)
        except Exception as e:                      # noqa: BLE001 (a page it could not check is reported)
            rv.check("page", "the page", p, p, "the review could not check the page", f"{type(e).__name__}: {e}"[:200])
    for which, data in (("dyes", D), ("inactive", F)):
        if data:
            check_forms(rv, which, pages.get(DYES if which == "dyes" else INACTIVE), body.get(f"{DYES if which == 'dyes' else INACTIVE}/data.csv"), data, site)
            check_totals(rv, which, data)
    compared = compare_recomputed(rv, rec, D, F, f"{DYES}/data.json", f"{INACTIVE}/data.json")
    # check 5: every label page the tables link (HEAD), then the set
    slugs = sorted({r["slug"] for r in (D or snap_d)["labels"]} | {r["slug"] for r in (F or snap_i)["labels"]})
    heads = read_many([f"{site}/whats-in/{s}" for s in slugs], fetch_fn, head=True, workers=workers, pause=pause / 5)
    whats_in = {s: heads[f"{site}/whats-in/{s}"] for s in slugs}
    for s, r in whats_in.items():
        if "why" in r:
            not_read.append({"url": f"{SITE}/whats-in/{s}", "why": r["why"]})
    routes_not_read = check_label_set(rv, products, D, F, pages, whats_in)
    check_named(rv, pages, D, F, rec)
    check_dates(rv, pages, D, F, refreshed)
    ptable = check_pitched(rv, pitched, D, pages, pitched_path.parent)
    cit = check_citations(rv, pages, fetch_fn, workers, pause)
    for u, s in cit["urls"].items():
        if s.startswith("not read"):
            not_read.append({"url": u, "why": s})
    n_share = check_share(rv, pages, fetch_fn, workers, pause)
    # the report
    classes = summarise(rv)
    prev = shared.previous_report(out, day, NAME)
    pc = (prev or {}).get("classes") or {}
    for k, c in classes.items():
        before = pc.get(k)
        c["change"] = "first run" if prev is None else "new" if before is None else f"{c['count'] - before['count']:+d}"
        if before:
            c["added"] = sorted(set(map(str, c["records"])) - set(map(str, before["records"])))[:20]
            c["left"] = sorted(set(map(str, before["records"])) - set(map(str, c["records"])))[:20]
    gone = sorted(set(pc) - set(classes)) if prev else []
    n_read = len(pages) + len(body) + sum("why" not in r for r in whats_in.values()) + n_share + \
        sum(1 for s in cit["urls"].values() if not s.startswith("not read"))
    verdict = verdict_line(classes, rv.total(), n_read, len(not_read))
    queued = queue(out, classes, prev, day)
    by_check: dict[str, dict] = {k: {"checked": 0, "findings": 0} for k in CHECKS}
    for (ck, _s), n in rv.compared.items():
        by_check[ck]["checked"] += n
    for f in rv.findings:
        by_check[f["check"]]["findings"] += 1
    a = RD["all"] if RD else {}
    data = {
        "verdict": verdict, "date": day.isoformat(), "time": meta["time"], "etl_commit": meta["commit"],
        "snapshot_refreshed": refreshed, "seconds": time.monotonic() - started, "classes": classes,
        "gone_since_last_run": gone, "previous_run": (prev or {}).get("date"), "pitched": ptable,
        "recomputation": {"origin": rec["origin"], "gaps": rec["gaps"], "cache": str(getattr(spl, "root", None) or "none"),
                          "compared": len(compared), "differ": sum(c["count"] for c in classes.values()
                                                                    if c["check"] == "recomputed" and "transform" in c["shape"])},
        "checked": {k: v for k, v in by_check.items() if v["checked"]},
        "surfaces": {f"{CHECKS[ck][0]}. {s}": n for (ck, s), n in sorted(rv.compared.items(), key=lambda kv: (ORDER[kv[0][0]], kv[0][1]))},
        "denominators": {"medicine labels": a.get("labels"), "over the counter": a.get("otc"),
                         "prescription": a.get("prescription"), "taken by mouth": RD["by_mouth_all"] if RD else None,
                         "labels the snapshot declares (products.json)": len(rec["labels"]),
                         "findings addresses": len(want_pages), "downloads": len(DOWNLOADS)},
        "addresses": {"read": n_read, "not_read": len(not_read), "pages": sorted(pages), "downloads": sorted(body),
                      "label_pages": len(whats_in), "share": n_share, "citation_urls": len(cit["urls"]),
                      "citation_links": cit["links"], "citations": cit["urls"], "not_read_list": not_read},
        "routes_not_read": routes_not_read, "queued_today": queued, "notes": rv.notes,
    }
    (out / f"{NAME}-{day.isoformat()}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str) + "\n")
    (out / f"{NAME}-{day.isoformat()}.md").write_text(render_md(data))
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mfetl review findings", description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="the reports folder (default: ../trust-reports)")
    p.add_argument("--snapshot", type=Path, default=SNAP, help="the snapshot to read (default: this checkout's)")
    p.add_argument("--date", type=dt.date.fromisoformat, default=None, help="the run's date (default: today)")
    p.add_argument("--site", default=SITE, help="the site to read (default: the live site)")
    a = p.parse_args(argv)
    try:
        a.out.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"review findings: could not run: the reports folder {a.out}: {e}", file=sys.stderr)
        return 2
    try:
        data = run(snap=a.snapshot, out=a.out, day=a.date, site=a.site.rstrip("/"))
    except Exception as e:                          # noqa: BLE001 (could not run: say why, exit non-zero)
        why = f"{type(e).__name__}: {e}"
        shared.heartbeat(a.out, "could not run", f"COULD NOT RUN: {why}"[:400], 2, reason=why[:400], name=NAME)
        print(f"review findings: could not run: {why}", file=sys.stderr)
        return 2
    report = str(a.out / f"{NAME}-{data['date']}.md")
    shared.heartbeat(a.out, "ran", data["verdict"], 0, report=report, name=NAME)
    print(data["verdict"])
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
