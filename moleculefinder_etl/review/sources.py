"""The source check: trust review 4 (`mfetl review sources`; brief ../TRUST-5-SOURCE-CHECK-PROMPT.md, 2026-11-28).

Every value on the site says where it came from, and a reader's trust rests on that source still saying it. Sources
move on their own: a DailyMed label is withdrawn or its product stops being marketed (Softsoap, 2026-11-17: the page was
held a week before anyone knew why), an approval is withdrawn, a link the page gives as its source stops answering,
PubChem detaches a record that carried a value (levonorgestrel's LD50, 2026-11-21). The weekly guards catch some of this
on Mondays and hold a page; this review looks every day and says plainly when a live page rests on a source that has gone.

READ-ONLY. It reads the snapshot ETL `main` holds (``data/snapshots``), the seeds, the live site, and the sources
themselves. Its requests to sources are its own: polite and named (``USER_AGENT``), each host held to its own pace
(``HOSTS``: PubChem's published 5 a second and 400 a minute, kept at 4 a second; DailyMed at 2 a second; Wikidata one at a
time), ONE request per address per run (a second ask is answered from memory), a HEAD where a HEAD tells the answer, a
conditional request (If-None-Match / If-Modified-Since) for the two regulators' data files, which it keeps in its OWN
cache (``--cache``; never the build's ``data/raw_cache``, never ``data/regulators``), and a per-run budget per host
(``BUDGET``), stated in the report with the requests made and the time taken per host. A request past the budget is not
made: its address is "not read". It loads no database key and writes nothing but its report (``<out>/sources-<date>.md``
and ``.json``), the heartbeat ``<out>/sources-last-run.json``, lines in ``<out>/QUEUE.md`` and its own cache. It never
blocks, stops or changes the weekly refresh, the news job or a deploy. Exit 0 when it ran, whatever it found.

WHAT IT READS. Daily: the pinned set (``PINNED_MOLECULES``, ``PINNED_LABELS``, each with its written reason, listed in
every report) plus a sample drawn by a seed made from the date (``moleculefinder-sources-<date>``: the same all day,
another tomorrow): ``SAMPLE_MEDICINES`` medicines, ``SAMPLE_OTHERS`` other molecules and ``SAMPLE_LABELS`` DailyMed
labels. **On Tuesdays (the day after Monday's refresh) everything**: every molecule, every DailyMed label, every page.
Every count states its denominator; a source it could not read is "not read", never "fine".

THE CHECKS (the brief's numbering; each finding goes in a named CLASS: the check, the surface and the shape):
 1. links answer       every external address a page gives as a source: the PubChem compound, the Wikidata item, the
                       DailyMed label, the FDA application, the regulator's licence page, the citations on
                       /about/methodology and /classroom. Where a host's page answers 200 for anything (PubChem's
                       compound page, the FDA's application overview, MHRA's substance page) the host's own data is
                       asked instead and the report says so: PubChem's PUG REST, Drugs@FDA's data file; MHRA's pages are
                       built in the browser and its API needs a key, so an MHRA address is "not read". eCFR and the
                       Federal Register serve automated readers a "Request Access" page: they are asked through their
                       own APIs, with review 5's code (findings.api_for, api_answers), never a fork of it. A "Request
                       Access" page with no API is "not read", never "answers". The pages read live are also checked to
                       give no source address the review does not know of.
 2. labels marketed    every DailyMed label behind a live /whats-in page (and so every label in the findings): its set
                       id still answers (DailyMed's own SPL by set id), the version on the page is the current one or
                       the difference is listed, and some product on it is still marketed (no marketing end date in the
                       past on every package). "A live page rests on a label that has ended or gone" is reported the
                       FIRST run it is seen and queued at once.
 3. approvals current  for every medicine the page states a status for or that relies on the approved-medicine rule: the
                       recorded basis still exists and is not discontinued, read from the regulator's own data file
                       (Drugs@FDA's for an application, the EMA's medicines file for a central authorisation, the label
                       for a label, the monograph order answering for a monograph). MHRA and national registers are not
                       readable here: "not read". A medicine none of whose bases is current and none "not read" is the
                       class "no current authorisation anywhere", reported at once and queued at once. Ruled exceptions
                       (approvals.yaml ``exception:``, read through relationships.ruled_exceptions: phenibut and
                       flunitrazepam, 2026-10-18; phenazopyridine, 2026-11-28) are never that class: they are listed
                       with their ruling, and an exception marketed unapproved has its label read for what its line says.
 4. value matches      PubChem's formula, weight and title for the record's CID (one batched request per 100 CIDs);
                       the hazard label's signal word, pictograms and statements (PUG-View, the ETL's own parser); the
                       LD50 the page shows still on the record it cites (PUG-View Toxicity, the ETL's own parser); the
                       Wikidata description the page shows. A difference is "upstream changed", with old and new, and
                       whether the weekly run already holds it (the LD50 hold's ld50_held.json, the Wikidata age rule's
                       wikidata_held.json or a revision under 7 days old, the snapshot guard's "chemical compound" rule),
                       so a held change is not reported as a surprise.
 5. kind and source    from the snapshot, every record and every product: each displayed value carries its kind
                       (from_source, computed or inferred) and a source the registry knows and lets be displayed, and no
                       value cites a BLOCKED source (licence_gate's own walk). On the pages read live, every Sources and
                       notes line has its chip and a named source, and the formula, the LD50, the hazard label and the
                       licence each have their kind word and their line.
 6. dataset, mirrors   the concept DOI resolves to Zenodo's latest version, which is the version the repository records;
                       Hugging Face and Kaggle hold that version (zenodo.find_record, mirrors.hf_read and kaggle_read:
                       their READ paths only, anonymous); /about/methodology and /classroom name the concept DOI.
 7. photographs        each door photograph's recorded source page (web lib/door-photos.ts on the web repository's
                       local main) answers, and its licence check (date, who, the words) is on file there and in
                       assets/doors/SOURCES.md.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import io
import json
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .. import dataset, licences, mirrors, zenodo
from ..sources import dailymed, registry
from ..transform import ghs as ghs_mod
from ..transform import licence_gate, medicine_status, relationships
from ..transform import toxicity as tox_mod
from . import drawings as shared
from . import findings as fr
from .facts import Node, parse_html

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "data" / "snapshots"
SEED_DIR = ROOT / "data" / "seed"
DEFAULT_OUT = ROOT.parent / "trust-reports"
DEFAULT_CACHE = Path.home() / "Library" / "Application Support" / "MoleculeFinder" / "trust-sources-cache"
DEFAULT_WEB = next((p for p in (Path.home() / "137" / "moleculefinder" / "moleculefinder-web", ROOT.parent / "moleculefinder-web")
                    if p.is_dir()), ROOT.parent / "moleculefinder-web")
SITE = "https://moleculefinder.com"
NAME = "sources"
USER_AGENT = "MoleculeFinder-trust-review/1 (source check; +https://moleculefinder.com/about)"
TIMEOUT = 60
SHOWN = 10
FULL_READ_WEEKDAY = 1                     # Tuesday (Monday is 0): the day after the weekly refresh
SAMPLE_MEDICINES = 20
SAMPLE_OTHERS = 20
SAMPLE_LABELS = 30
PUBCHEM_BATCH = 100
WIKIDATA_BATCH = 50
WIKIDATA_AGE_DAYS = 7

# host -> (seconds between two requests, requests at once, the published limit or the reason for the pace)
HOSTS = {
    "pubchem.ncbi.nlm.nih.gov": (0.25, 1, "PubChem's published limit is 5 requests a second and 400 a minute: 4 a second"),
    "dailymed.nlm.nih.gov": (0.5, 1, "no published limit; half the ETL's own pace (2 a second)"),
    "www.wikidata.org": (1.0, 1, "Wikimedia's API etiquette: one request at a time, maxlag=5, batched 50 items"),
    "moleculefinder.com": (0.1, 4, "our own site: four readers at once, at most 10 pages a second"),
}
DEFAULT_HOST = (1.0, 1, "one request a second")
# The per-run budget per host (a request past it is not made). The Tuesday full read needs about: PubChem 10 batches +
# 653 hazard labels + 286 LD50s; DailyMed 377 labels + 377 label pages; Wikidata 19 batches; the site about 1,400 pages.
BUDGET = {"pubchem.ncbi.nlm.nih.gov": 1500, "dailymed.nlm.nih.gov": 1000, "www.wikidata.org": 60,
          "moleculefinder.com": 1600}
DEFAULT_BUDGET = 60

PUG_PROPS = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cids}/property/MolecularFormula,MolecularWeight,Title/JSON"
PUG_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON?heading={heading}"
PUBCHEM_PAGE = "https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"
WIKIDATA_API = ("https://www.wikidata.org/w/api.php?action=wbgetentities&ids={ids}&props=descriptions%7Cinfo"
                "&languages=en&format=json&maxlag=5")
WIKIDATA_PAGE = "https://www.wikidata.org/wiki/{qid}"
DAILYMED_PAGE = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"
DOI = "https://doi.org/{doi}"

# The pinned set: each with the reason it is read every day.
PINNED_MOLECULES = {
    "phenazopyridine": "the ruled exception marketed unapproved (2026-11-28): its Pyridium label must keep saying so",
    "phenibut": "a ruled exception (2026-10-18): a Latvian licence no data file here confirms",
    "flunitrazepam": "a ruled exception (2026-10-18): an Italian licence no data file here confirms",
    "levonorgestrel": "the LD50 held since 2026-11-23 (PubChem detached it): the hold must be what the source says",
    "caffeine": "the site's best-known page: PubChem, Wikidata, an HSDB LD50 and a three-depositor hazard label",
    "sertraline": "a Drugs@FDA licence (NDA 019839) and a DailyMed label (Zoloft) on one page",
    "acetaminophen": "a status with both sides (a Drugs@FDA OTC licence, a prescription label)",
    "azelastine": "a basis recorded by hand in status_bases.yaml (ANDA 077954)",
    "avobenzone": "an FDA OTC monograph basis (M020)",
    "cyclizine": "an MHRA licence: its register cannot be read by a script (always 'not read')",
    "meldonium": "a Latvian national licence under a ruling, no exception: 'not read', never 'no authorisation'",
    "orforglipron": "the newest FDA approval (NDA 220934, 2026-04-01)",
    "titanium-dioxide": "a lattice with no drawing, a monograph basis and a hazard label",
    "collagen": "a hand-made model with no PubChem record: nothing is asked of PubChem for it",
    "2-nonenal": "a Wikidata text change the age rule held (2026-11-18): a held change is not a surprise",
}
PINNED_LABELS = {
    "pyridium": "the ruled exception's label (marketing category: unapproved drug other)",
    "softsoap-antibacterial-hand-soap": "the label whose page was held for a week on 2026-11-17 before anyone knew why",
    "differin": "repointed on 2026-11-27 to the OTC label (0739d631, version 10)",
    "zoloft": "a prescription label under an NDA",
    "advil": "a familiar over-the-counter label in the findings",
}
METHOD_PAGES = ("/about/methodology", "/classroom")

# check -> (the brief's number, heading, the recommended fix a queue item carries)
CHECKS = {
    "gone": (2, "a live page rests on a label that has ended or gone",
             ("Tell Cowork the same day: find the label's successor on DailyMed (the same product, the brand owner's) and "
              "repoint the products.yaml row, or remove the row (the page then answers 410). Never edit the label by hand.")),
    "unauthorised": (3, "no current authorisation anywhere",
                     ("Tell Cowork the same day: the approved-medicine rule no longer holds for a live page. Read the "
                      "regulators again by hand; Garrett rules (an exception in approvals.yaml, or the row is deferred).")),
    "links": (1, "a source link", "Fix the link the page gives (the record's source address), or the host's address scheme."),
    "labels": (2, "a label's version or marketing", "Let Monday's refresh read the new version; if the page lags, find why."),
    "approvals": (3, "an approval's basis", "Read the regulator's record again and update licences.yaml or status_bases.yaml."),
    "exception": (3, "a ruled exception", "Read the exception's label again; Garrett rules again if it no longer holds."),
    "values": (4, "upstream changed", "Let the weekly guards act on it; if no guard holds it, read the source by hand."),
    "kinds": (5, "a value's kind or source", "Give the value its kind and a registered, displayable source (licence_gate)."),
    "dataset": (6, "the dataset and its mirrors", "Run `mfetl mirrors --check`; publish the mirror with `mfetl mirrors`."),
    "photos": (7, "a door photograph's source", "Open the source page in a real browser and record the check again."),
}
IMMEDIATE = {"gone", "unauthorised"}       # reported and queued the first run seen; every other class on two runs
ORDER = {k: i for i, k in enumerate(CHECKS)}


def is_full_read(day: dt.date) -> bool:
    return day.weekday() == FULL_READ_WEEKDAY


def seeded(pool: list[str], day: dt.date, k: int, what: str) -> list[str]:
    """``k`` of ``pool`` drawn by a seed made from the date: the same list all day, another tomorrow."""
    seed = int(hashlib.sha256(f"moleculefinder-sources-{what}-{day.isoformat()}".encode()).hexdigest()[:16], 16)
    pool = sorted(pool)
    return sorted(random.Random(seed).sample(pool, min(k, len(pool))))


# ── the network: one throttle per host, one request per address, a budget per host ─────────────────────────────────
@dataclass
class Resp:
    status: int
    headers: dict
    body: bytes = b""
    why: str | None = None                # set when there was no answer at all (a network error, the budget spent)

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.body.decode("utf-8", "replace"))


def urllib_transport(url: str, method: str, headers: dict) -> Resp:
    """The real transport: no redirect followed (a redirect is an answer to read), two tries on a network error."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT, **headers})
    for attempt in (1, 2):
        try:
            with opener.open(req, timeout=TIMEOUT) as r:
                return Resp(r.status, {k.lower(): v for k, v in r.headers.items()}, b"" if method == "HEAD" else r.read())
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read() if method != "HEAD" else b""
            except (OSError, ValueError):
                body = b""
            return Resp(e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, body)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == 2:
                return Resp(0, {}, b"", f"{type(e).__name__}: {e}"[:160])
            time.sleep(5)
    return Resp(0, {}, b"", "unreachable")


class Net:
    """Every request the review makes goes through here: the host's pace, one request per address, the budget."""

    def __init__(self, transport=urllib_transport, budget: dict | None = None, hosts: dict | None = None,
                 sleep=time.sleep, clock=time.monotonic):
        self.transport, self.sleep, self.clock = transport, sleep, clock
        self.budget = {**BUDGET, **(budget or {})}
        self.hosts = {**HOSTS, **(hosts or {})}
        self.memo: dict[tuple[str, str], Resp] = {}
        self.made: Counter = Counter()          # host -> requests made
        self.refused: Counter = Counter()       # host -> requests not made (the budget)
        self.seconds: Counter = Counter()       # host -> seconds spent waiting for answers
        self.not_modified: Counter = Counter()
        self._lock = threading.Lock()
        self._host_locks: dict[str, threading.Semaphore] = {}
        self._last: dict[str, float] = {}

    def _host(self, url: str) -> str:
        return urllib.parse.urlparse(url).netloc.lower()

    def get(self, url: str, head: bool = False, headers: dict | None = None) -> Resp:
        method = "HEAD" if head else "GET"
        host = self._host(url)
        with self._lock:
            if (method, url) in self.memo:
                return self.memo[(method, url)]
            if self.made[host] >= self.budget.get(host, DEFAULT_BUDGET):
                self.refused[host] += 1
                r = Resp(0, {}, b"", f"not asked: the run's budget for {host} ({self.budget.get(host, DEFAULT_BUDGET)}) was spent")
                self.memo[(method, url)] = r
                return r
            self.made[host] += 1
            gap, at_once, _why = self.hosts.get(host, DEFAULT_HOST)
            sem = self._host_locks.setdefault(host, threading.Semaphore(at_once))
        with sem:
            with self._lock:
                wait = gap - (self.clock() - self._last.get(host, -1e9))
                self._last[host] = self.clock() + max(0.0, wait)
            if wait > 0:
                self.sleep(wait)
            t0 = self.clock()
            r = self.transport(url, method, headers or {})
            with self._lock:
                self.seconds[host] += self.clock() - t0
                self._last[host] = max(self._last.get(host, 0.0), self.clock())
                if r.status == 304:
                    self.not_modified[host] += 1
                self.memo[(method, url)] = r
        return r

    def answered(self) -> int:
        """Distinct addresses that answered (any HTTP status): what was read."""
        return sum(1 for r in self.memo.values() if not r.why)

    def report(self) -> dict:
        hosts = sorted(set(self.made) | set(self.refused))
        return {h: {"requests": self.made[h], "not_made_budget": self.refused[h], "budget": self.budget.get(h, DEFAULT_BUDGET),
                    "not_modified": self.not_modified[h], "seconds_answering": round(self.seconds[h], 1),
                    "pace": self.hosts.get(h, DEFAULT_HOST)[2]} for h in hosts}


def conditional(net: Net, url: str, cache_dir: Path) -> tuple[bytes | None, str]:
    """A data file by a conditional request, kept in the review's OWN cache. (bytes, how it was read)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    body_p, meta_p = cache_dir / f"{key}.bin", cache_dir / f"{key}.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() and body_p.exists() else {}
    h = {}
    if meta.get("etag"):
        h["If-None-Match"] = meta["etag"]
    if meta.get("last_modified"):
        h["If-Modified-Since"] = meta["last_modified"]
    r = net.get(url, headers=h)
    if r.status == 304 and body_p.exists():
        return body_p.read_bytes(), f"not modified since {meta.get('last_modified') or meta.get('etag')} (the review's cache)"
    if r.status == 200 and r.body:
        body_p.write_bytes(r.body)
        meta_p.write_text(json.dumps({"url": url, "etag": r.headers.get("etag"), "last_modified": r.headers.get("last-modified"),
                                      "read": dt.datetime.now().astimezone().isoformat(timespec="seconds")}))
        return r.body, f"read ({len(r.body):,} bytes, last modified {r.headers.get('last-modified') or 'not stated'})"
    return None, r.why or f"HTTP {r.status}"


# ── the review's findings ───────────────────────────────────────────────────────────────────────────────────────────
class Review:
    def __init__(self):
        self.findings: list[dict] = []
        self.compared: Counter = Counter()           # (check, surface) -> things checked
        self.unread: list[dict] = []                 # {check, surface, subject, url, why}
        self.notes: list[str] = []

    def check(self, check: str, surface: str, subject: str, where: str, shape: str | None, detail: str = "") -> bool:
        self.compared[(check, surface)] += 1
        if shape:
            self.findings.append({"check": check, "surface": surface, "shape": shape, "subject": subject,
                                  "path": where, "detail": detail})
        return not shape

    def not_read(self, check: str, surface: str, subject: str, url: str, why: str) -> None:
        """Never a pass and never a finding: counted and listed as not read."""
        self.unread.append({"check": check, "surface": surface, "subject": subject, "url": url, "why": why})

    def total(self) -> int:
        return sum(self.compared.values())


# ── the snapshot ────────────────────────────────────────────────────────────────────────────────────────────────────
def load_snapshot(snap: Path) -> dict:
    recs = {}
    for p in sorted((snap / "molecules").glob("*.json")):
        r = json.loads(p.read_text())
        recs[r["slug"]] = r
    products = json.loads((snap / "products.json").read_text())["products"]
    meta = json.loads((snap / "meta.json").read_text())
    return {"recs": recs, "products": {p["slug"]: p for p in products}, "meta": meta}


def is_dailymed(p: dict) -> bool:
    return (p.get("source") or {}).get("type") == "dailymed" and bool((p.get("source") or {}).get("setid"))


def has_pubchem(r: dict) -> bool:
    return isinstance(r.get("cid"), int) and r["cid"] > 0 and not r.get("hand_model")


def page_addresses(r: dict) -> dict[str, str]:
    """The external source addresses a molecule page gives (the web's Sources and notes and its footer line):
    address -> what it is."""
    out = {}
    if has_pubchem(r):
        out[PUBCHEM_PAGE.format(cid=r["cid"])] = "pubchem compound"
    if r.get("wikidata_qid"):
        out[WIKIDATA_PAGE.format(qid=r["wikidata_qid"])] = "wikidata item"
    a = r.get("approval") or {}
    if a.get("register") in ("Drugs@FDA", "MHRA Products", "European Medicines Agency") and a.get("source"):
        out[a["source"]] = {"Drugs@FDA": "fda application", "MHRA Products": "mhra licence",
                            "European Medicines Agency": "ema authorisation"}[a["register"]]
    return out


def held_ledgers(seed_dir: Path) -> dict:
    def read(name):
        p = seed_dir / name
        try:
            return json.loads(p.read_text()) if p.exists() else []
        except ValueError:
            return []
    return {"ld50": {h.get("slug"): h for h in read("ld50_held.json")},
            "wikidata": {(h.get("slug"), h.get("field")) for h in read("wikidata_held.json")}}


# ── DailyMed: one label's SPL, its products and their marketing ─────────────────────────────────────────────────────
NS = dailymed._NS


def spl_facts(xml: bytes) -> dict:
    """{version, effective, products: [{name, category, status, start, end}]} from an SPL document."""
    root = ET.fromstring(xml)
    v = root.find(f"{NS}versionNumber")
    eff = root.find(f"{NS}effectiveTime")
    out = {"version": int(v.get("value")) if v is not None and (v.get("value") or "").isdigit() else None,
           "effective": eff.get("value") if eff is not None else None, "products": []}
    for subj in root.iter(f"{NS}subject"):
        mp = subj.find(f"{NS}manufacturedProduct")
        if mp is None:
            continue
        inner = mp.find(f"{NS}manufacturedProduct")
        name = dailymed._text(inner.find(f"{NS}name")) if inner is not None else ""
        cat = status = start = end = ""
        for so in mp.findall(f"{NS}subjectOf"):
            ap = so.find(f"{NS}approval")
            if ap is not None and not cat:
                c = ap.find(f"{NS}code")
                cat = dailymed._clean(c.get("displayName") or "") if c is not None else ""
            ma = so.find(f"{NS}marketingAct")
            if ma is not None and not status:
                st = ma.find(f"{NS}statusCode")
                status = ((st.get("code") or "") if st is not None else "").lower()
                et = ma.find(f"{NS}effectiveTime")
                if et is not None:
                    lo, hi = et.find(f"{NS}low"), et.find(f"{NS}high")
                    start = (lo.get("value") or "") if lo is not None else ""
                    end = (hi.get("value") or "") if hi is not None else ""
        if name or cat or status:
            out["products"].append({"name": name, "category": cat, "status": status, "start": start, "end": end})
    return out


def marketed_today(prod: dict, today: str) -> bool:
    """A product is marketed today unless its marketing end date has passed, or its marketing is over with no end date
    stated (statusCode completed, no high). An end date still to come is marketed today (the brief: "no marketing end
    date in the past")."""
    end = (prod.get("end") or "")[:8]
    if end:
        return end >= today
    return prod.get("status") in ("active", "")


def check_labels(rv: Review, labels: dict[str, dict], spl: dict[str, Resp], page: dict[str, Resp], today: str,
                 in_findings: set[str]) -> dict:
    """Check 2 over the labels read. ``spl``: set id -> the SPL answer; ``page``: set id -> the drugInfo HEAD."""
    out = {"read": 0, "not_read": 0, "facts": {}}
    for slug, p in sorted(labels.items()):
        src = p["source"]
        setid, url = src["setid"], src.get("url") or DAILYMED_PAGE.format(setid=src["setid"])
        r = spl.get(setid)
        tag = f"/whats-in/{slug}" + (" (in the findings)" if slug in in_findings else "")
        if r is None or r.why or r.status not in (200, 404):
            rv.not_read("labels", "a DailyMed label", slug, url, (r.why if r else "not asked") or f"HTTP {r.status}")
            out["not_read"] += 1
            continue
        out["read"] += 1
        if r.status == 404:
            rv.check("gone", "a DailyMed label behind a live page", slug, tag, "the set id no longer answers",
                     f"DailyMed has no label {setid} (the SPL answers 404); the page cites version {src.get('version')}")
            continue
        try:
            f = spl_facts(r.body)
        except ET.ParseError as e:
            rv.not_read("labels", "a DailyMed label", slug, url, f"the SPL did not parse: {e}")
            continue
        out["facts"][setid] = f
        live = [x for x in f["products"] if marketed_today(x, today)]
        ended = sorted({x.get("end") for x in f["products"] if x.get("end")})
        rv.check("gone", "a DailyMed label behind a live page", slug, tag,
                 None if live or not f["products"] else "every product on the label has ended",
                 f"{len(f['products'])} product(s), none marketed today; marketing ended {', '.join(ended) or 'with no end date stated'}")
        ending = sorted({x["end"][:8] for x in live if x.get("end")})
        rv.check("labels", "a label's marketing end", slug, tag,
                 "every product on the label has a marketing end date to come" if live and len(ending) and
                 all(x.get("end") for x in live) else None,
                 f"marketing ends {', '.join(ending)} (still marketed today)")
        rv.check("labels", "a label's version", slug, tag,
                 None if f["version"] == src.get("version") else "the page cites an older version",
                 f"the page: version {src.get('version')} ({src.get('effective')}); DailyMed today: version "
                 f"{f['version']} ({f['effective']})")
        if live and len(live) < len(f["products"]):
            rv.check("labels", "a label's products", slug, tag, "some products on the label have ended",
                     f"{len(f['products']) - len(live)} of {len(f['products'])} product(s) no longer marketed")
        else:
            rv.compared[("labels", "a label's products")] += 1
        pg = page.get(setid)
        if pg is not None:
            if pg.why:
                rv.not_read("links", "a DailyMed label page", slug, url, pg.why)
            else:
                rv.check("links", "a DailyMed label page", slug, tag,
                         None if pg.status == 200 else "the link does not answer",
                         f"{url}: HTTP {pg.status}" + (" (DailyMed sends an unknown set id to its search)" if pg.status in (301, 302) else ""))
    return out


# ── the regulators' data files ──────────────────────────────────────────────────────────────────────────────────────
def parse_fda_status(zip_bytes: bytes) -> dict[str, dict]:
    """ApplNo -> {"type", "statuses": {product: status}} from the Drugs@FDA data file (every product, discontinued too)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        apps = {r["ApplNo"]: (r.get("ApplType") or "").strip() for r in licences._read_tsv(zf, "Applications.txt")}
        names = {r["MarketingStatusID"]: r["MarketingStatusDescription"].strip()
                 for r in licences._read_tsv(zf, "MarketingStatus_Lookup.txt")}
        out = {a: {"type": t, "statuses": {}} for a, t in apps.items()}
        for r in licences._read_tsv(zf, "MarketingStatus.txt"):
            out.setdefault(r["ApplNo"], {"type": "", "statuses": {}})["statuses"][r["ProductNo"]] = names.get(r["MarketingStatusID"], "")
    return out


def appl_no(application: str | None) -> str | None:
    m = re.search(r"(\d{6})", application or "")
    return m.group(1) if m else None


def fda_state(fda: dict | None, application: str | None) -> tuple[str, str]:
    """("current" | "discontinued" | "missing" | "not read", words)."""
    if fda is None:
        return "not read", "the Drugs@FDA data file was not read"
    a = appl_no(application)
    e = fda.get(a or "")
    if not e:
        return "missing", f"{application}: not in the Drugs@FDA data file"
    st = Counter(e["statuses"].values())
    cur = st.get("Prescription", 0) + st.get("Over-the-counter", 0)
    words = ", ".join(f"{n} {s.lower() or 'no status'}" for s, n in sorted(st.items())) or "no products"
    return ("current" if cur else "discontinued"), f"{application}: {words} in the Drugs@FDA data file"


def ema_state(ema: list[dict] | None, approval: dict) -> tuple[str, str]:
    if ema is None:
        return "not read", "the EMA's medicines file was not read"
    num, prod = (approval.get("application") or "").strip(), (approval.get("product") or "").strip().lower()
    hits = [m for m in ema if (num and m.get("number") == num) or (prod and m.get("name", "").lower() == prod)]
    if hits:
        return "current", f"{num or prod}: status Authorised in the EMA's medicines file"
    return "missing", f"{num or prod}: no authorised human medicine of that number or name in the EMA's medicines file"


def check_approvals(rv: Review, recs: dict[str, dict], chosen: list[str], fda: dict | None, ema: list[dict] | None,
                    label_facts: dict[str, dict], label_unread: set[str], monograph: dict[str, Resp], today: str,
                    exceptions: dict[str, dict]) -> dict:
    """Check 3 over the medicines chosen today."""
    out = {"medicines": 0, "current": 0, "not_read": 0, "exceptions": {}}
    for slug in chosen:
        r = recs[slug]
        st = r.get("medicine_status")
        appr = r.get("approval") or {}
        if not (isinstance(st, dict) or appr):
            continue
        out["medicines"] += 1
        bases: list[tuple[str, str, str]] = []           # (what, state, words)
        reg = appr.get("register") or ""
        if reg == "Drugs@FDA":
            s, w = fda_state(fda, appr.get("application"))
            bases.append(("its licence record (Drugs@FDA)", s, w))
        elif reg == "European Medicines Agency":
            s, w = ema_state(ema, appr)
            bases.append(("its licence record (the EMA)", s, w))
        elif reg == "MHRA Products":
            bases.append(("its licence record (MHRA)", "not read", "the MHRA register is built in the browser and its API needs a key"))
        elif appr.get("application", "").startswith("OTC Monograph"):
            mr = monograph.get(appr.get("source") or "")
            if mr is None or mr.why:
                bases.append((f"FDA {appr['application']}", "not read", (mr.why if mr else "not asked") or ""))
            else:
                bases.append((f"FDA {appr['application']}", "current" if mr.status == 200 else "missing",
                              f"the order {appr.get('source')} answers HTTP {mr.status} (the order itself is not read)"))
        elif appr.get("regulator") == licences.FDA and re.match(r"(NDA|ANDA|BLA) \d{6}", appr.get("application") or ""):
            s, w = fda_state(fda, appr.get("application"))
            bases.append(("its licence record (FDA, ruled)", s, w))
        elif appr:
            bases.append((f"its licence record ({appr.get('regulator')})", "not read",
                          "a national register the review does not read (a ruling recorded in approvals.yaml)"))
        for side in ("otc", "prescription"):
            for e in (st or {}).get(side) or []:
                if e.get("kind") in ("licence",):
                    continue                              # the licence record, above
                if e.get("kind") == "application":
                    s, w = fda_state(fda, e.get("application"))
                    bases.append((f"{e.get('application')} (recorded, {side})", s, w))
                elif e.get("kind") == "monograph":
                    continue                              # the same monograph as the licence record
                elif e.get("kind") == "label":
                    sid = e.get("setid")
                    f = label_facts.get(sid)
                    if f is None:
                        bases.append((f"the {e.get('product')} label ({side})", "not read",
                                      "the label was not read today" if sid not in label_unread else "DailyMed did not answer"))
                    else:
                        live = [x for x in f["products"] if marketed_today(x, today)
                                and x["category"].upper() in (medicine_status.OTC_CATEGORIES if side == "otc" else medicine_status.RX_CATEGORIES)]
                        bases.append((f"the {e.get('product')} label ({side})", "current" if live else "ended",
                                      f"{sid} version {f['version']}: {len(live)} product(s) marketed today under an authorisation"))
        for what, s, w in bases:
            if s in ("current", "not read"):
                rv.compared[("approvals", "a medicine's recorded basis")] += 1
                if s == "not read":
                    rv.not_read("approvals", "a medicine's recorded basis", slug, what, w)
            else:
                rv.check("approvals", "a medicine's recorded basis", slug, f"/m/{slug}", f"a basis is {s}", f"{what}: {w}")
        ex = exceptions.get(slug)
        any_current = any(s == "current" for _, s, _w in bases)
        any_unread = any(s == "not read" for _, s, _w in bases)
        if ex:
            out["exceptions"][slug] = {"ruled": ex.get("ruled"), "by": ex.get("by"), "why": ex.get("why"),
                                       "marketed": ex.get("marketed"), "bases": [f"{a}: {c}" for a, b, c in bases]}
            if ex.get("marketed") == medicine_status.UNAPPROVED:
                lab = ex.get("label") or {}
                f = label_facts.get(lab.get("setid"))
                if f is None:
                    rv.not_read("exception", "a ruled exception's label", slug, DAILYMED_PAGE.format(setid=lab.get("setid")),
                                "the label was not read")
                else:
                    live = [x for x in f["products"] if marketed_today(x, today)]
                    cats = sorted({x["category"] for x in live})
                    ok = live and all(c.lower() == str(lab.get("category")).lower() for c in cats)
                    rv.check("exception", "a ruled exception's label", slug, f"/m/{slug}",
                             None if ok else "the label no longer says what the line says",
                             f"{lab.get('setid')} version {f['version']}: marketed today as {', '.join(cats) or 'nothing'}; "
                             f"the exception records {lab.get('category')!r}")
                    out["exceptions"][slug]["label_today"] = f"version {f['version']}, marketed as {', '.join(cats) or 'nothing'}"
                shown = (st or {}).get("status")
                rv.check("exception", "a ruled exception's status line", slug, f"/m/{slug}",
                         None if shown == medicine_status.UNAPPROVED else "the record does not carry the exception's line",
                         f"the record's status is {shown!r}")
            continue
        if any_current:
            out["current"] += 1
            rv.compared[("unauthorised", "a medicine page")] += 1
        elif any_unread:
            out["not_read"] += 1
            rv.not_read("unauthorised", "a medicine page", slug, f"/m/{slug}",
                        "no basis confirmed current; at least one could not be read")
        elif not bases:
            # nothing recorded to check: not "no authorisation anywhere" (nothing was looked up), but a fact about the page
            rv.check("approvals", "a medicine page's basis", slug, f"/m/{slug}", "the record names no basis to check",
                     f"status {(st or {}).get('status')!r}" + (f" ({(st or {}).get('unsettled')})" if (st or {}).get("unsettled") else "")
                     + "; no licence record, no recorded application, no current label")
        else:
            rv.check("unauthorised", "a medicine page", slug, f"/m/{slug}", "no basis is current",
                     "; ".join(f"{a}: {c}" for a, b, c in bases))
    return out


# ── PubChem and Wikidata: the values ────────────────────────────────────────────────────────────────────────────────
def record_names(r: dict) -> set[str]:
    names = {r.get("title"), r.get("preferred_name"), r.get("iupac_name"), r.get("wikipedia_title")}
    names |= set(r.get("synonyms") or []) | set(r.get("display_synonyms") or []) | set(r.get("wikidata_names") or [])
    return {str(n).strip().casefold() for n in names if n}


def check_props(rv: Review, recs: dict, props: dict[int, dict], unread: dict[int, str]) -> None:
    for slug, r in sorted(recs.items()):
        cid = r["cid"]
        where = f"/m/{slug}"
        url = PUBCHEM_PAGE.format(cid=cid)
        if cid in unread:
            rv.not_read("links", "a PubChem compound", slug, url, unread[cid])
            continue
        p = props.get(cid)
        rv.check("links", "a PubChem compound", slug, where,
                 None if p and p.get("MolecularFormula") else "the record no longer answers",
                 f"{url}: PUG REST gives {'nothing' if not p else 'no formula'} for CID {cid} (the compound page answers 200 for any number, so PubChem's own data is asked)")
        if not p or not p.get("MolecularFormula"):
            continue
        if r.get("molecular_formula"):
            rv.check("values", "PubChem's formula", slug, where,
                     None if p["MolecularFormula"] == r["molecular_formula"] else "the formula changed",
                     f"shipped {r['molecular_formula']}, PubChem today {p['MolecularFormula']}")
        if r.get("molecular_weight") is not None:
            try:
                same = abs(float(p.get("MolecularWeight")) - float(r["molecular_weight"])) < 1e-6
            except (TypeError, ValueError):
                same = False
            rv.check("values", "PubChem's weight", slug, where, None if same else "the weight changed",
                     f"shipped {r['molecular_weight']}, PubChem today {p.get('MolecularWeight')}")
        title = (p.get("Title") or "").strip()
        rv.check("values", "PubChem's title", slug, where,
                 None if title.casefold() in record_names(r) else "PubChem's title is not a name the record carries",
                 f"PubChem today titles CID {cid} {title!r}; the record's first PubChem name is {(r.get('synonyms') or [''])[0]!r}")


def check_ghs(rv: Review, slug: str, r: dict, resp: Resp | None) -> None:
    where = f"/m/{slug}"
    if resp is None or resp.why or resp.status not in (200, 404):
        rv.not_read("values", "the hazard label", slug, PUG_VIEW.format(cid=r["cid"], heading="GHS+Classification"),
                    (resp.why if resp else "not asked") or f"HTTP {resp.status}")
        return
    fresh = ghs_mod.parse_ghs(resp.json()) if resp.status == 200 else None
    old = r.get("ghs") or {}
    if fresh is None:
        rv.check("values", "the hazard label", slug, where, "the record no longer carries a hazard label",
                 f"shipped {old.get('signal_word')} {', '.join(old.get('h_statements') or [])}; PubChem today: none a displayable source gives")
        return
    diffs = [f"{k}: shipped {old.get(k)!r}, today {fresh.get(k)!r}" for k in ("signal_word", "pictograms", "h_statements")
             if (old.get(k) or None) != (fresh.get(k) or None)]
    rv.check("values", "the hazard label", slug, where, "the hazard label changed" if diffs else None, "; ".join(diffs))


def check_ld50(rv: Review, slug: str, r: dict, resp: Resp | None, held: dict) -> None:
    where = f"/m/{slug}"
    if resp is None or resp.why or resp.status not in (200, 404):
        rv.not_read("values", "the LD50", slug, PUG_VIEW.format(cid=r["cid"], heading="Toxicity"),
                    (resp.why if resp else "not asked") or f"HTTP {resp.status}")
        return
    rows = tox_mod.parse_ld50(resp.json()) if resp.status == 200 else []
    key = (r.get("ld50_species"), r.get("ld50_route"), float(r["ld50_mg_per_kg"]), r.get("ld50_qualifier"))
    present = any((x["species"], x["route"], float(x["value_num"]), x.get("qualifier")) == key for x in rows)
    h = held.get(slug)
    rv.check("values", "the LD50", slug, where, None if present else "the LD50 the page shows is no longer on the record",
             f"shipped {key[3] or ''}{r['ld50_mg_per_kg']} mg/kg ({key[0]}, {key[1]}); PubChem today: "
             f"{len(rows)} displayable LD50 row(s)" + (f"; KNOWN to the weekly run: the LD50 hold holds it since {h.get('since')}"
                                                         if h else "; the LD50 hold does not hold it"))


def check_wikidata(rv: Review, recs: dict, ents: dict[str, dict], unread: dict[str, str], held: set, now: dt.datetime) -> None:
    for slug, r in sorted(recs.items()):
        q = r["wikidata_qid"]
        url = WIKIDATA_PAGE.format(qid=q)
        if q in unread:
            rv.not_read("links", "a Wikidata item", slug, url, unread[q])
            continue
        e = ents.get(q)
        if e is None or "missing" in e:
            rv.check("links", "a Wikidata item", slug, f"/m/{slug}", "the item no longer exists", f"{url}: missing")
            continue
        if e.get("id") and e["id"] != q:
            rv.check("links", "a Wikidata item", slug, f"/m/{slug}", "the item now redirects to another", f"{q} -> {e['id']}")
            continue
        rv.check("links", "a Wikidata item", slug, f"/m/{slug}", None, url)
        if r.get("summary_source") != "wikidata":
            continue
        today = (((e.get("descriptions") or {}).get("en") or {}).get("value") or "").strip()
        if today == (r.get("summary") or "").strip():
            rv.check("values", "the Wikidata description", slug, f"/m/{slug}", None)
            continue
        why = []
        if (slug, "description") in held or (slug, "desc") in held:
            why.append("the Wikidata age rule holds it (wikidata_held.json)")
        try:
            mod = dt.datetime.fromisoformat(e.get("modified") or "")
            if now - mod < dt.timedelta(days=WIKIDATA_AGE_DAYS):
                why.append(f"the item was last edited {mod.date()}, under {WIKIDATA_AGE_DAYS} days ago: the age rule may hold it")
        except ValueError:
            pass
        if today.casefold() in ("chemical compound", "chemical substance", ""):
            why.append("the snapshot guard never lets a summary revert to a bare 'chemical compound'")
        rv.check("values", "the Wikidata description", slug, f"/m/{slug}",
                 "the description changed, held by the weekly run" if why else "the description changed",
                 f"shipped {r.get('summary')!r}, Wikidata today {today!r}" + (f"; KNOWN: {'; '.join(why)}" if why else ""))


# ── check 5: kinds and sources ──────────────────────────────────────────────────────────────────────────────────────
KINDS = {"from_source", "computed", "inferred"}


def kind_problems(r: dict) -> list[tuple[str, str]]:
    """(where, what) for every displayed value with no kind, or a kind outside the three."""
    slug = r.get("slug")
    out = []

    def need(where: str, c) -> None:
        if c not in KINDS:
            out.append((where, f"kind {c!r}" if c else "no kind"))
    for i, t in enumerate(r.get("toxicity") or []):
        need(f"{slug}.toxicity[{i}]", t.get("confidence"))
    if r.get("ghs"):
        need(f"{slug}.ghs", r["ghs"].get("confidence"))
    d = r.get("descriptors") or {}
    if any(v is not None for k, v in d.items() if k != "confidence"):
        need(f"{slug}.descriptors", d.get("confidence"))
    for p in r.get("properties") or []:
        need(f"{slug}.properties.{p.get('key')}", p.get("confidence"))
    for p in r.get("products") or []:
        if p.get("presence"):
            need(f"{slug}.products.{p.get('slug')}.presence", p["presence"].get("confidence"))
    for c in r.get("categories") or []:
        if c.get("presence"):
            need(f"{slug}.categories.{c.get('slug')}.presence", c["presence"].get("confidence"))
    for e in r.get("edges") or []:
        need(f"{slug}.edges.{e.get('neighbor_slug')}", e.get("confidence"))
    for h in r.get("hooks") or []:
        need(f"{slug}.hooks.{h.get('type')}", h.get("confidence"))
    return out


def check_kinds(rv: Review, recs: dict, products: dict) -> dict:
    n_values = 0
    for slug, r in sorted(recs.items()):
        for where, what in kind_problems(r):
            rv.check("kinds", "a value's kind", slug, f"/m/{slug}", "a value with no kind", f"{where}: {what}")
        for where, key in licence_gate.molecule_citations(r):
            n_values += 1
            check_source(rv, slug, f"/m/{slug}", where, key)
    for slug, p in sorted(products.items()):
        if p.get("confidence") not in KINDS:
            rv.check("kinds", "a value's kind", slug, f"/whats-in/{slug}", "a value with no kind", f"product:{slug}: {p.get('confidence')!r}")
        else:
            rv.compared[("kinds", "a value's kind")] += 1
        for where, key in licence_gate.product_citations(p):
            n_values += 1
            check_source(rv, slug, f"/whats-in/{slug}", where, key)
    return {"citations": n_values}


def check_source(rv: Review, slug: str, path: str, where: str, key: str | None) -> None:
    if key in registry.BLOCKED:
        shape = "a value from a BLOCKED source"
    elif key is None:
        shape = "a value that cites no source"
    elif key not in registry.SOURCES:
        shape = "a source the registry does not know"
    elif not registry.may_display(key):
        shape = "a source whose licence does not allow display"
    else:
        shape = None
    rv.check("kinds", "a value's source", slug, path, shape, f"{where}: {key!r}")


def srcnote_lines(root: Node) -> list[dict]:
    out = []
    for d in root.find_all(lambda n: n.tag == "details" and "srcnote" in n.classes):
        for li in d.find_all(lambda n: n.tag == "li"):
            b = next((k for k in li.kids if isinstance(k, Node) and k.tag == "b"), None)
            chip = next((k for k in li.kids if isinstance(k, Node) and "mf-chip" in k.classes), None)
            src = next((k for k in li.kids if isinstance(k, Node) and "srcnote__src" in k.classes), None)
            out.append({"label": b.text().strip() if b else "", "chip": (chip.text().strip() if chip else ""),
                        "source": src.text().strip() if src else ""})
    return out


LINE_FOR = {"formula": ("Formula and weight", "calculated"), "ld50": ("LD50", "measured"),
            "ghs": ("Hazard label", "reported"), "licence": ("Licence", "reported"), "status": ("The line above", None)}


def check_page_kinds(rv: Review, slug: str, r: dict, raw: str) -> None:
    root = parse_html(raw)
    lines = srcnote_lines(root)
    kinds = Counter(c.replace("kind--", "") for n in root.iter() for c in n.classes if c.startswith("kind--"))
    path = f"/m/{slug}"
    for ln in lines:
        ok = ln["chip"] in ("from source", "computed", "inferred") and bool(ln["source"])
        rv.check("kinds", "a Sources and notes line on the live page", slug, path,
                 None if ok else "a line with no chip or no named source", f"{ln['label']!r}: chip {ln['chip']!r}, source {ln['source']!r}")
    want = []
    if r.get("molecular_formula"):
        want.append("formula")
    if r.get("ld50_mg_per_kg") is not None:
        want.append("ld50")
    if r.get("ghs"):
        want.append("ghs")
    if (r.get("approval") or {}).get("register"):
        want.append("licence")
    if r.get("medicine_status"):
        want.append("status")
    labels = {ln["label"] for ln in lines}
    for w in want:
        label, kind = LINE_FOR[w]
        has_line = any(lb == label or lb.startswith(label) for lb in labels)
        has_kind = kind is None or kinds.get(kind, 0) > 0
        rv.check("kinds", "a value's kind and source on the live page", slug, path,
                 None if has_line and has_kind else "a value shown without its kind or its line",
                 f"{label}: line {'present' if has_line else 'MISSING'}" + (f", kind word {kind} {'present' if has_kind else 'MISSING'}" if kind else ""))


def external_links(raw: str) -> set[str]:
    root = parse_html(raw)
    out = set()
    for n in root.iter():
        if n.tag == "a":
            h = (n.attrs.get("href") or "").strip()
            if h.startswith("http") and "moleculefinder.com" not in urllib.parse.urlparse(h).netloc:
                out.add(h)
    return out


# ── check 6: the dataset and its mirrors ────────────────────────────────────────────────────────────────────────────
def check_dataset(rv: Review, net: Net, pages: dict[str, str]) -> dict:
    pub = dataset.published()
    latest_v = list(pub["versions"])[-1]
    out = {"concept_doi": pub["concept_doi"], "repo_latest": latest_v}
    r = net.get(DOI.format(doi=pub["concept_doi"]), head=True)
    if r.why:
        rv.not_read("dataset", "the concept DOI", pub["concept_doi"], DOI.format(doi=pub["concept_doi"]), r.why)
    else:
        loc = r.headers.get("location") or ""
        rv.check("dataset", "the concept DOI", pub["concept_doi"], DOI.format(doi=pub["concept_doi"]),
                 None if r.status in (301, 302, 303, 307, 308) and "zenodo.org" in loc else "the concept DOI does not resolve to Zenodo",
                 f"HTTP {r.status} to {loc or 'nowhere'}")
    rec = None
    try:
        c = zenodo.Client(None, session=_Session(net))
        rec = zenodo.find_record(c, pub)
        out["zenodo_latest"] = rec.latest_version
        rv.check("dataset", "Zenodo's latest version", pub["concept_doi"], pub.get("zenodo_record") or "",
                 None if rec.latest_version == latest_v and rec.versions == pub["versions"] else "Zenodo and the repository disagree",
                 f"Zenodo's latest {rec.latest_version} (record {rec.latest_id}); the repository records {latest_v}; versions "
                 f"{sorted(rec.versions)} against {sorted(pub['versions'])}")
    except Exception as e:                         # noqa: BLE001 (a source it could not read is "not read")
        rv.not_read("dataset", "Zenodo's latest version", pub["concept_doi"], "https://zenodo.org", f"{type(e).__name__}: {e}"[:200])
    for which, ident, read in (("Hugging Face", pub.get("huggingface"), lambda h, i: mirrors.hf_read(h, i)),
                               ("Kaggle", pub.get("kaggle"), lambda h, i: mirrors.kaggle_read(h, i))):
        if not ident:
            continue
        try:
            held = read(mirrors.Http(session=_Session(net)), ident)
            out[which] = held.version
            want = rec.latest_version if rec else latest_v
            rv.check("dataset", f"the {which} mirror", ident, ident,
                     None if held.version == want else "the mirror does not hold Zenodo's latest version",
                     f"{which} holds {held.version}; Zenodo's latest {want}" + (" (Kaggle's public view can trail a new version by hours)" if which == "Kaggle" else ""))
        except Exception as e:                     # noqa: BLE001
            rv.not_read("dataset", f"the {which} mirror", ident, ident, f"{type(e).__name__}: {e}"[:200])
    concept = DOI.format(doi=pub["concept_doi"])
    for path in METHOD_PAGES:
        raw = pages.get(path)
        if raw is None:
            rv.not_read("dataset", "a page naming the dataset", path, SITE + path, "the page was not read")
            continue
        version_dois = [v for v in pub["versions"].values() if v in raw]
        rv.check("dataset", "a page naming the dataset", path, path,
                 None if concept in raw and not version_dois else "the page does not name the concept DOI alone",
                 f"concept DOI {'named' if concept in raw else 'NOT named'}; version DOIs named: {', '.join(version_dois) or 'none'}")
    return out


class _Session:
    """A requests-like session over Net, for zenodo.Client and mirrors.Http (their read paths), so every request they
    make is paced, counted and held to the budget. Redirects are followed here (up to five)."""

    def __init__(self, net: Net):
        self.net, self.headers = net, {}

    def request(self, method: str, url: str, timeout: int = TIMEOUT, **kw):
        if method != "GET" or kw.get("json") or kw.get("data"):
            raise RuntimeError(f"the review only reads: refused {method} {url}")
        if kw.get("params"):
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(kw["params"])
        for _ in range(5):
            r = self.net.get(url)
            if r.why:
                raise OSError(r.why)
            if r.status in (301, 302, 303, 307, 308) and r.headers.get("location"):
                url = urllib.parse.urljoin(url, r.headers["location"])
                continue
            return _Answer(r)
        raise OSError(f"too many redirects from {url}")


class _Answer:
    def __init__(self, r: Resp):
        self.status_code, self.content, self.text = r.status, r.body, r.text()

    def json(self):
        return json.loads(self.text)


# ── check 7: the door photographs ───────────────────────────────────────────────────────────────────────────────────
_PHOTO = re.compile(r"door:\s*\"([^\"]+)\".*?licence:\s*\"([^\"]+)\".*?sourcePage:\s*\"([^\"]+)\".*?check:\s*\{(.*?)\}", re.DOTALL)


def door_photos(web: Path) -> tuple[list[dict] | None, str, str | None]:
    """(photos, where read, SOURCES.md text) from the web repository's local main, read only (git show)."""
    def show(path: str) -> str | None:
        try:
            r = subprocess.run(["git", "-C", str(web), "show", f"main:{path}"], capture_output=True, text=True, timeout=20, check=False)
            return r.stdout if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None
    ts = show("lib/door-photos.ts")
    if ts is None:
        return None, f"{web} (main) could not be read", None
    photos = []
    for m in _PHOTO.finditer(ts):
        chk = m.group(4)

        def get(k: str, chk: str = chk) -> str | None:
            hit = re.search(rf"{k}:\s*(\"(?:[^\"\\]|\\.)*\"|'[^']*')", chk)
            return hit.group(1) if hit else None
        photos.append({"door": m.group(1), "licence": m.group(2), "source": m.group(3),
                       "date": (get("date") or "").strip("\"'"), "by": (get("by") or "").strip("\"'"),
                       "words": (get("words") or "").strip("\"'")})
    return photos, f"{web}: main:lib/door-photos.ts", show("assets/doors/SOURCES.md")


def check_photos(rv: Review, net: Net, web: Path) -> dict:
    photos, where, sources_md = door_photos(web)
    if photos is None:
        rv.not_read("photos", "a door photograph", "all", where, "the web repository is not beside this one")
        return {"read_from": where, "photos": 0}
    for p in photos:
        on_file = all(p.get(k) for k in ("date", "by", "words")) and bool(sources_md and p["source"] in sources_md)
        rv.check("photos", "a door photograph's licence check", p["door"], p["source"],
                 None if on_file else "the licence check is not on file",
                 f"{p['licence']}: checked {p.get('date') or '?'} by {p.get('by') or '?'}; in SOURCES.md: {bool(sources_md and p['source'] in sources_md)}")
        r = net.get(p["source"])
        if r.why or r.status in (202, 401, 403, 429) or fr.BOT_PAGE.search(r.text()[:5000]) or "challenge" in r.text()[:3000].lower():
            rv.not_read("photos", "a door photograph's source page", p["door"], p["source"],
                        r.why or f"HTTP {r.status}: the host turns scripts away (a browser check), so it was not read")
        else:
            rv.check("photos", "a door photograph's source page", p["door"], p["source"],
                     None if r.status == 200 else "the source page does not answer", f"{p['source']}: HTTP {r.status}")
    return {"read_from": where, "photos": len(photos)}


# ── check 1: the citations on the method pages ──────────────────────────────────────────────────────────────────────
def check_citations(rv: Review, net: Net, pages: dict[str, str]) -> int:
    urls: dict[str, str] = {}
    for path in METHOD_PAGES:
        if pages.get(path):
            for u in sorted(external_links(pages[path])):
                urls.setdefault(u, path)
    for u, path in sorted(urls.items()):
        if "doi.org/" in u or "huggingface.co/datasets" in u or "kaggle.com/datasets" in u:
            continue                                      # check 6 reads the dataset's addresses
        r = net.get(u)
        body = r.text()[:20000]
        bot = bool(fr.BOT_PAGE.search(body))
        api = fr.api_for(u)
        if (bot or r.status in (403, 429)) and api:
            a = net.get(api)
            ok = fr.api_answers(u, {"status": a.status, "body": a.text()}) if not a.why else False
            if a.why or not ok and a.status != 200:
                rv.not_read("links", "a citation on a method page", u, u, "a Request Access page, and the publisher's API did not answer")
            else:
                rv.check("links", "a citation on a method page", u, path, None if ok else "the citation is gone",
                         f"{u}: through the publisher's API ({api}): {'answers' if ok else 'no such section or document'}")
        elif r.why or bot or r.status in (202, 401, 403, 429):
            rv.not_read("links", "a citation on a method page", u, u, r.why or ("a Request Access page" if bot else
                        f"HTTP {r.status}: the host answers scripts with a browser check"))
        else:
            rv.check("links", "a citation on a method page", u, path,
                     None if r.status == 200 or r.status in (301, 302, 307, 308) else "the link does not answer",
                     f"{u}: HTTP {r.status}" + (f" to {r.headers.get('location')}" if r.status in (301, 302, 307, 308) else ""))
    return len(urls)


# ── the report ──────────────────────────────────────────────────────────────────────────────────────────────────────
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
        c["queue"] = "at once" if c["check"] in IMMEDIATE else "on two consecutive runs"
    return dict(sorted(classes.items(), key=lambda kv: (ORDER[kv[1]["check"]], -kv[1]["count"], kv[0])))


def queue(out: Path, classes: dict, prev: dict | None, day: dt.date) -> list[str]:
    """QUEUE.md, once per class: the two IMMEDIATE classes the first day seen, every other on the second run."""
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
            loud = "**A LIVE PAGE RESTS ON A SOURCE THAT HAS GONE** " if c["check"] in IMMEDIATE else ""
            text += (f"- [ ] {day.isoformat()} {NAME}: {loud}**{k}**: {c['count']} of {c['of']} "
                     f"({', '.join(str(x) for x in c['records'][:5])}{', ...' if len(c['records']) > 5 else ''}). "
                     f"Recommended: {CHECKS[c['check']][2]} {marker}\n")
            added.append(k)
    if added:
        q.write_text(text)
    return added


def verdict_line(classes: dict, checked: int, read: int, not_read: int, requests: int) -> str:
    loud = [r for c in classes.values() if c["check"] in IMMEDIATE for r in c["records"]]
    head = f"VERDICT: A LIVE PAGE RESTS ON A SOURCE THAT HAS GONE ({', '.join(map(str, loud))}). " if loud else "VERDICT: "
    return (f"{head}{len(classes)} finding class{'es' if len(classes) != 1 else ''} found "
            f"({sum(c['count'] for c in classes.values()):,} findings); {checked:,} things checked; {read:,} sources "
            f"read; {not_read:,} not read; {requests:,} requests.")


def render_md(d: dict) -> str:
    L = [d["verdict"], "", f"# The source check, {d['date']}", ""]
    w = L.append
    w(f"Trust review 4 (`mfetl review sources`, ETL `moleculefinder_etl/review/sources.py`), run {d['time']} against the "
      f"snapshot ETL `{d['etl_commit']}` holds (refreshed {d['snapshot_refreshed']}). Read-only: it changed nothing. "
      f"{'THE TUESDAY FULL READ: everything' if d['full'] else 'The daily read: the pinned set and the day sample'}. "
      f"{d['seconds']:.0f} seconds. Previous run: {d['previous_run'] or 'none (this is the first)'}.")
    w("")
    w("## Findings, class by class")
    w("")
    w("Each class is the check, the surface it was read on, and the shape. The count is over the things of that kind "
      "checked on that surface. A class is queued on two consecutive runs, except \"a live page rests on a label that has "
      "ended or gone\" and \"no current authorisation anywhere\", which are queued the day they are seen.")
    w("")
    if not d["classes"]:
        w("None.")
        w("")
    for k, c in d["classes"].items():
        w(f"### {c['number']}. {k}")
        w(f"- **{c['count']:,} of {c['of']:,}**, on {len(c['addresses']):,} address(es); since the last run: {c['change']}"
          + (f" (in: {', '.join(map(str, c['added']))})" if c.get("added") else "")
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
    w("## Not read (never counted as fine)")
    w("")
    nr = Counter((u["check"], u["surface"], u["why"].split(":")[0][:90]) for u in d["not_read"])
    if not nr:
        w("Nothing.")
    for (ck, s, why), n in sorted(nr.items(), key=lambda kv: (-kv[1], kv[0])):
        ex = [u for u in d["not_read"] if (u["check"], u["surface"], u["why"].split(":")[0][:90]) == (ck, s, why)]
        w(f"- {CHECKS[ck][0]}. {s}: **{n}** not read: {why} (e.g. {', '.join(str(u['subject']) for u in ex[:5])})")
    w("")
    w("## Ruled exceptions (approvals.yaml `exception:`; never reported as \"no current authorisation\")")
    w("")
    for s, e in d["exceptions"].items():
        w(f"- **{s}**: ruled {e['ruled']} by {e['by']}: {e['why']}" + (f" Marketed: {e['marketed']}." if e.get("marketed") else "")
          + (f" Its label today: {e['label_today']}." if e.get("label_today") else "") + (" Its bases: " + "; ".join(e["bases"]) + "." if e.get("bases") else ""))
    if not d["exceptions"]:
        w("None read today.")
    w("")
    w("## What was read, and what was not covered")
    w("")
    for k, v in d["coverage"].items():
        w(f"- {k}: {v}")
    w("")
    w("## Requests, per host (the run's budget, its pace)")
    w("")
    w("| host | requests | not made (budget) | budget | 304 not modified | seconds answering | pace |")
    w("|---|---|---|---|---|---|---|")
    for h, v in d["requests"].items():
        w(f"| {h} | {v['requests']:,} | {v['not_made_budget']:,} | {v['budget']:,} | {v['not_modified']:,} | {v['seconds_answering']:,} | {v['pace']} |")
    w("")
    w("## Checked, by check")
    w("")
    w("| # | surface | checked | findings |")
    w("|---|---|---|---|")
    for k, v in d["surfaces"].items():
        w(f"| {k} | {v['surface']} | {v['checked']:,} | {v['findings']:,} |")
    w("")
    w("## The pinned set (read every day)")
    w("")
    for s, why in PINNED_MOLECULES.items():
        w(f"- /m/{s}: {why}")
    for s, why in PINNED_LABELS.items():
        w(f"- /whats-in/{s}: {why}")
    w("")
    w(f"Sampled today (seed `moleculefinder-sources-<what>-{d['date']}`): {len(d['sample']['molecules'])} molecules, "
      f"{len(d['sample']['labels'])} labels" + ("" if d["full"] else f": {', '.join(d['sample']['molecules'][:40])}; labels {', '.join(d['sample']['labels'][:30])}") + ".")
    for n in d["notes"]:
        w("")
        w(f"Note: {n}")
    return "\n".join(L).rstrip() + "\n"


# ── the run ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def choose(S: dict, day: dt.date, full: bool) -> tuple[list[str], list[str]]:
    recs, prods = S["recs"], S["products"]
    if full:
        return sorted(recs), sorted(s for s, p in prods.items() if is_dailymed(p))
    meds = [s for s, r in recs.items() if r.get("medicine_status") and s not in PINNED_MOLECULES]
    others = [s for s, r in recs.items() if not r.get("medicine_status") and s not in PINNED_MOLECULES]
    mols = sorted({*[s for s in PINNED_MOLECULES if s in recs], *seeded(meds, day, SAMPLE_MEDICINES, "medicines"),
                   *seeded(others, day, SAMPLE_OTHERS, "molecules")})
    labs = [s for s, p in prods.items() if is_dailymed(p) and s not in PINNED_LABELS]
    labels = sorted({*[s for s in PINNED_LABELS if s in prods and is_dailymed(prods[s])],
                     *seeded(labs, day, SAMPLE_LABELS, "labels")})
    return mols, labels


def run(snap: Path = SNAP, out: Path = DEFAULT_OUT, day: dt.date | None = None, net: Net | None = None, site: str = SITE,
        full: bool | None = None, cache_dir: Path = DEFAULT_CACHE, web: Path = DEFAULT_WEB, seed_dir: Path = SEED_DIR,
        now: dt.datetime | None = None) -> dict:
    day = day or dt.date.today()
    now = now or dt.datetime.now(dt.UTC)
    full = is_full_read(day) if full is None else full
    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    net = net or Net()
    rv = Review()
    S = load_snapshot(snap)
    recs, prods = S["recs"], S["products"]
    today = day.strftime("%Y%m%d")
    mols, labs = choose(S, day, full)
    exceptions = relationships.ruled_exceptions()
    held = held_ledgers(seed_dir)
    try:
        findings_labels = {r["slug"] for r in json.loads((snap / "findings" / "dyes-in-medicines.json").read_text())["labels"]}
    except (OSError, ValueError, KeyError):
        findings_labels = set()
    # the DailyMed labels read today: the labels chosen, plus every label a chosen medicine's status rests on, plus
    # each exception's label
    label_set = {s: prods[s] for s in labs}
    by_setid = {p["source"]["setid"]: s for s, p in prods.items() if is_dailymed(p)}
    evidence_setids = {e.get("setid") for s in mols for side in ("otc", "prescription")
                       for e in ((recs[s].get("medicine_status") or {}).get(side) or []) if e.get("kind") == "label"}
    evidence_setids |= {(e.get("label") or {}).get("setid") for e in exceptions.values() if e.get("label")}
    extra_setids = set()
    for sid in evidence_setids:
        if sid in by_setid:
            label_set.setdefault(by_setid[sid], prods[by_setid[sid]])
        elif sid and dailymed.SETID_RE.match(sid):
            extra_setids.add(sid)
    # ── read everything, each host on its own thread at its own pace ──
    pages_m = [f"/m/{s}" for s in mols]
    pages_w = [f"/whats-in/{s}" for s in sorted(label_set)]
    site_paths = sorted(set(pages_m) | set(pages_w) | set(METHOD_PAGES))
    pub_recs = {s: recs[s] for s in mols if has_pubchem(recs[s])}
    wd_recs = {s: recs[s] for s in mols if recs[s].get("wikidata_qid")}

    def read_site():
        got = {}
        with cf.ThreadPoolExecutor(max_workers=HOSTS["moleculefinder.com"][1]) as ex:
            for p, r in zip(site_paths, ex.map(lambda p: net.get(site + p), site_paths), strict=True):
                got[p] = r
        return got

    def read_pubchem():
        props, unread, ghs_r, tox_r = {}, {}, {}, {}
        cids = sorted({r["cid"] for r in pub_recs.values()})
        for i in range(0, len(cids), PUBCHEM_BATCH):
            chunk = cids[i:i + PUBCHEM_BATCH]
            r = net.get(PUG_PROPS.format(cids=",".join(map(str, chunk))))
            if r.why or r.status != 200:
                for c in chunk:
                    unread[c] = r.why or f"PUG REST answered HTTP {r.status}"
                continue
            for p in (r.json().get("PropertyTable") or {}).get("Properties") or []:
                props[int(p["CID"])] = p
        for s, r in sorted(pub_recs.items()):
            if r.get("ghs"):
                ghs_r[s] = net.get(PUG_VIEW.format(cid=r["cid"], heading="GHS+Classification"))
            if r.get("ld50_mg_per_kg") is not None:
                tox_r[s] = net.get(PUG_VIEW.format(cid=r["cid"], heading="Toxicity"))
        return props, unread, ghs_r, tox_r

    def read_wikidata():
        ents, unread = {}, {}
        qids = sorted({r["wikidata_qid"] for r in wd_recs.values()})
        for i in range(0, len(qids), WIKIDATA_BATCH):
            chunk = qids[i:i + WIKIDATA_BATCH]
            r = net.get(WIKIDATA_API.format(ids="%7C".join(chunk)))
            if r.why or r.status != 200:
                for q in chunk:
                    unread[q] = r.why or f"the API answered HTTP {r.status}"
                continue
            try:
                body = r.json()
            except ValueError:
                body = {}
            if "error" in body:
                for q in chunk:
                    unread[q] = f"the API answered {body['error'].get('code')}"
                continue
            for q, e in (body.get("entities") or {}).items():
                ents[q] = e
            for frm, to in ((body.get("redirects") or {}).items() if isinstance(body.get("redirects"), dict) else []):
                ents[frm] = {**ents.get(to, {}), "id": to}
        for q in qids:
            if q not in ents and q not in unread:
                unread[q] = "the API's answer did not mention it"
        return ents, unread

    def read_dailymed():
        spl, page = {}, {}
        for s, p in sorted(label_set.items()):
            sid = p["source"]["setid"]
            spl[sid] = net.get(dailymed.SPL_URL.format(setid=sid))
            if full or s in labs:
                page[sid] = net.get(p["source"].get("url") or DAILYMED_PAGE.format(setid=sid), head=True)
        for sid in sorted(extra_setids):               # labels recorded by hand (status_bases.yaml): no page of their own
            spl[sid] = net.get(dailymed.SPL_URL.format(setid=sid))
        return spl, page

    def read_registers():
        fda_b, fda_how = conditional(net, licences.FDA_ZIP_URL, cache_dir)
        ema_b, ema_how = conditional(net, licences.EMA_JSON_URL, cache_dir)
        fda = ema = None
        if fda_b:
            try:
                fda = parse_fda_status(fda_b)
            except (zipfile.BadZipFile, KeyError) as e:
                fda_how = f"did not parse: {e}"
        if ema_b:
            try:
                tmp = cache_dir / "ema-parse.json"
                tmp.write_bytes(ema_b)
                ema = licences.parse_ema(tmp)
            except (ValueError, KeyError) as e:
                ema_how = f"did not parse: {e}"
        mono = {}
        for s in mols:
            a = recs[s].get("approval") or {}
            if (a.get("application") or "").startswith("OTC Monograph") and a.get("source"):
                mono[a["source"]] = net.get(a["source"], head=True)
        return fda, fda_how, ema, ema_how, mono

    with cf.ThreadPoolExecutor(max_workers=5) as ex:
        f_site, f_pc, f_wd, f_dm, f_reg = (ex.submit(read_site), ex.submit(read_pubchem), ex.submit(read_wikidata),
                                           ex.submit(read_dailymed), ex.submit(read_registers))
        site_r, (props, pc_unread, ghs_r, tox_r), (ents, wd_unread), (spl, dm_page), (fda, fda_how, ema, ema_how, mono) = (
            f_site.result(), f_pc.result(), f_wd.result(), f_dm.result(), f_reg.result())
    pages = {p: r.text() for p, r in site_r.items() if not r.why and r.status == 200}
    for p, r in site_r.items():
        if p not in pages:
            rv.not_read("kinds", "a live page", p, SITE + p, r.why or f"HTTP {r.status}")
    # ── the checks ──
    lab = check_labels(rv, label_set, spl, dm_page, today, findings_labels)
    for sid in sorted(extra_setids):
        r = spl.get(sid)
        if r is not None and not r.why and r.status == 200:
            try:
                lab["facts"][sid] = spl_facts(r.body)
            except ET.ParseError:
                pass
    label_unread = {p["source"]["setid"] for p in label_set.values() if p["source"]["setid"] not in lab["facts"]}
    appr = check_approvals(rv, recs, mols, fda, ema, lab["facts"], label_unread, mono, today, exceptions)
    check_props(rv, pub_recs, props, pc_unread)
    for s, r in sorted(pub_recs.items()):
        if r.get("ghs"):
            check_ghs(rv, s, r, ghs_r.get(s))
        if r.get("ld50_mg_per_kg") is not None:
            check_ld50(rv, s, r, tox_r.get(s), held["ld50"])
    check_wikidata(rv, wd_recs, ents, wd_unread, held["wikidata"], now)
    # check 1: the FDA application addresses (through the data file) and the MHRA and EMA ones
    for s in mols:
        for url, what in page_addresses(recs[s]).items():
            if what == "fda application":
                st, words = fda_state(fda, (recs[s].get("approval") or {}).get("application"))
                if st == "not read":
                    rv.not_read("links", "an FDA application", s, url, words)
                else:
                    rv.check("links", "an FDA application", s, f"/m/{s}", None if st != "missing" else "the application is gone",
                             f"{url}: {words} (the overview page answers 200 for any number, so the data file is asked)")
            elif what == "mhra licence":
                rv.not_read("links", "an MHRA licence page", s, url, "the MHRA's pages are built in the browser: any address answers the same bytes")
            elif what == "ema authorisation":
                r = net.get(url, head=True)
                if r.why:
                    rv.not_read("links", "an EMA medicine page", s, url, r.why)
                else:
                    rv.check("links", "an EMA medicine page", s, f"/m/{s}", None if r.status == 200 else "the link does not answer", f"{url}: HTTP {r.status}")
    # the live pages: no source address the review does not know; check 5's kinds on the page
    for s in mols:
        raw = pages.get(f"/m/{s}")
        if raw is None:
            continue
        known = set(page_addresses(recs[s]))
        for u in sorted(external_links(raw) - known):
            rv.check("links", "a source address on a live page", s, f"/m/{s}", "an address the review does not know of", u)
        rv.compared[("links", "a source address on a live page")] += len(known)
        try:
            check_page_kinds(rv, s, recs[s], raw)
        except Exception as e:                    # noqa: BLE001
            rv.not_read("kinds", "a live page", f"/m/{s}", SITE + f"/m/{s}", f"could not be taken apart: {e}"[:160])
    for s in sorted(label_set):
        raw = pages.get(f"/whats-in/{s}")
        if raw is None:
            continue
        want = {prods[s]["source"].get("url") or DAILYMED_PAGE.format(setid=prods[s]["source"]["setid"])}
        want |= {a.get("url") for a in prods[s].get("also") or [] if a.get("url")}
        for u in sorted(external_links(raw) - want):
            rv.check("links", "a source address on a live page", s, f"/whats-in/{s}", "an address the review does not know of", u)
        rv.compared[("links", "a source address on a live page")] += 1
    kinds = check_kinds(rv, recs, prods)
    n_cit = check_citations(rv, net, pages)
    ds = check_dataset(rv, net, pages)
    ph = check_photos(rv, net, web)
    # ── the report ──
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
    reqs = net.report()
    n_req = sum(v["requests"] for v in reqs.values())
    n_read = net.answered()
    verdict = verdict_line(classes, rv.total(), n_read, len(rv.unread), n_req)
    queued = queue(out, classes, prev, day)
    surfaces = {f"{CHECKS[ck][0]} / {s}": {"surface": s, "checked": n,
                                          "findings": sum(1 for f in rv.findings if f["check"] == ck and f["surface"] == s)}
                for (ck, s), n in sorted(rv.compared.items(), key=lambda kv: (ORDER[kv[0][0]], kv[0][1]))}
    n_dm = sum(1 for p in prods.values() if is_dailymed(p))
    n_med = sum(1 for r in recs.values() if r.get("medicine_status") or r.get("approval"))
    coverage = {
        "molecules": f"{len(mols):,} of {len(recs):,} read ({len(pub_recs):,} with a PubChem record, {len(wd_recs):,} with a Wikidata item)",
        "DailyMed labels": f"{len(label_set):,} of {n_dm:,} DailyMed labels behind live /whats-in pages read ({lab['read']:,} answered, "
                           f"{lab['not_read']:,} not read; {len(findings_labels & set(label_set)):,} of the {len(findings_labels):,} in the findings). "
                           f"The other {len(prods) - n_dm:,} of the {len(prods):,} label pages are curated or Wikidata lists, with no label to check",
        "DailyMed label pages (drugInfo, HEAD)": f"{len(dm_page):,}" + ("" if full else " (the chosen labels; the evidence labels are read through the SPL only)"),
        "medicines": f"{appr['medicines']:,} of {n_med:,} read for check 3: {appr['current']:,} with a basis confirmed current, "
                     f"{appr['not_read']:,} with none confirmed and one not read, {len(appr['exceptions']):,} ruled exceptions",
        "Drugs@FDA data file": fda_how, "the EMA's medicines file": ema_how,
        "hazard labels (PUG-View)": f"{len(ghs_r):,} of {sum(1 for r in pub_recs.values() if r.get('ghs')):,} chosen records with one",
        "LD50s (PUG-View)": f"{len(tox_r):,} of {sum(1 for r in pub_recs.values() if r.get('ld50_mg_per_kg') is not None):,} chosen records showing one",
        "values and sources (check 5, the snapshot)": f"every record ({len(recs):,}) and product ({len(prods):,}): {kinds['citations']:,} citations",
        "live pages": f"{len(pages):,} of {len(site_paths):,} read",
        "citations on the method pages": f"{n_cit:,}",
        "door photographs": f"{ph['photos']} from {ph['read_from']}",
        "not covered": ("a hazard label or LD50 PubChem ADDED to a record whose page shows none (only shown values are "
                        "checked); the depositors' wording of each statement (the codes are compared); MHRA and national "
                        "registers (not readable by a script); an OTC monograph's text (the order is checked to answer); "
                        "Wikidata labels and aliases (the description only)"),
    }
    data = {
        "verdict": verdict, "date": day.isoformat(), "time": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "etl_commit": shared.etl_commit(), "snapshot_refreshed": S["meta"].get("refreshed"), "full": full,
        "seconds": time.monotonic() - started, "classes": classes, "gone_since_last_run": gone,
        "previous_run": (prev or {}).get("date"), "not_read": rv.unread, "exceptions": appr["exceptions"],
        "coverage": coverage, "requests": reqs, "surfaces": surfaces, "dataset": ds,
        "sample": {"molecules": [m for m in mols if m not in PINNED_MOLECULES], "labels": [s for s in labs if s not in PINNED_LABELS]},
        "queued_today": queued, "notes": rv.notes,
    }
    (out / f"{NAME}-{day.isoformat()}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str) + "\n")
    (out / f"{NAME}-{day.isoformat()}.md").write_text(render_md(data))
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mfetl review sources", description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="the reports folder (default: ../trust-reports)")
    p.add_argument("--snapshot", type=Path, default=SNAP, help="the snapshot to read (default: this checkout's)")
    p.add_argument("--date", type=dt.date.fromisoformat, default=None, help="the run's date (default: today)")
    p.add_argument("--site", default=SITE, help="the site to read (default: the live site)")
    p.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="the review's own cache for the regulators' data files")
    p.add_argument("--web", type=Path, default=DEFAULT_WEB, help="the web repository (its local main is read for the photographs)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--full", action="store_true", help="read everything (the Tuesday read), any day")
    g.add_argument("--sample", action="store_true", help="the pinned set and the day's sample, even on a Tuesday")
    a = p.parse_args(argv)
    try:
        a.out.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"review sources: could not run: the reports folder {a.out}: {e}", file=sys.stderr)
        return 2
    try:
        data = run(snap=a.snapshot, out=a.out, day=a.date, site=a.site.rstrip("/"), cache_dir=a.cache, web=a.web,
                   full=True if a.full else False if a.sample else None)
    except Exception as e:                          # noqa: BLE001 (could not run: say why, exit non-zero)
        why = f"{type(e).__name__}: {e}"
        shared.heartbeat(a.out, "could not run", f"COULD NOT RUN: {why}"[:400], 2, reason=why[:400], name=NAME)
        print(f"review sources: could not run: {why}", file=sys.stderr)
        return 2
    report = str(a.out / f"{NAME}-{data['date']}.md")
    shared.heartbeat(a.out, "ran", data["verdict"], 0, report=report, name=NAME)
    print(data["verdict"])
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
