"""Molecules in the news: the catalogue's molecules named in recent headlines, every six hours.

Run A of BUILD-PLAN-growth-2026-10-18, on PolitiFinder's pattern (politifinder/repo/
scripts/news-politicians.mjs): Google News RSS, a matcher that prefers a miss to a wrong match,
a names-only table, one public JSON in Storage that the static site fetches in the browser, and an
IndexNow ping for the pages new to the list. It builds nothing and deploys nothing.

WHAT IS DIFFERENT FROM PF, AND WHY
1. Standard library only (Python 3.11 or later). PF keeps its job dependency-free so a six-hourly cron never pays an
   install; this repo's package needs rdkit, so the job imports nothing outside the standard
   library and runs as ``python -m moleculefinder_etl.news`` on the runner's own Python.
2. NAMES ONLY, IN THE TABLE TOO. PF's table keeps the latest headline, outlet and link "for
   auditing". MoleculeFinder's keeps slug, name, first and last seen, and a headline count, and
   nothing else (Garrett's spec, 2026-10-20). The audit view is ``--show-headlines`` on a local dry
   run; the cron never prints or stores headline text (this repo and its logs are public).
3. WHAT MATCHES. PF keys on a title ("Sen.", "Gov.") before a name. A molecule has no title, so
   the match is exact on the molecule's own names: the page title, the name in its <title>
   parenthetical, its curated brands, a few curated news names (``ALIASES``: "Red 40", "Ozempic"),
   and those of its display synonyms that are shaped like chemical names. Never the raw PubChem
   synonym list: lead's carries "Glover", monosodium glutamate's "Accent".
4. THE STOP LIST. A name that is also an everyday word (iron, lead, salt, water, gold...) never
   matches on its own; a few match in fixed phrases ("lead poisoning", "iron deficiency"). A
   short all-capitals name matches only when allowlisted (CBD, THC, BPA, DHA; never EPA, MSG).
5. THE QUERIES. PF's eleven title queries find headlines that carry a title. Molecules are named
   without one, so the catalogue's own names are the queries, in OR batches, plus a few topic
   queries (recalls, bans, food dyes) whose headlines are matched the same way.

THE LIST. hits = distinct headlines in this run's window naming the molecule. The feed carries
every molecule whose latest headline is inside seven days, most headlines first; the home page
shows eight. Rows are pruned 21 days after their last headline.

Usage:
  python -m moleculefinder_etl.news                  # match, write table + feed, ping IndexNow
  python -m moleculefinder_etl.news --dry-run        # match and print; write and submit nothing
  python -m moleculefinder_etl.news --dry-run --show-headlines   # local audit only
  python -m moleculefinder_etl.news --fixture tests/fixtures/news-headlines.txt   # always dry
"""
from __future__ import annotations

import argparse
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MOLECULES_DIR = REPO / "data" / "snapshots" / "molecules"
SITE = "https://moleculefinder.com"
# Public by design: moleculefinder.com serves it at /86a211e892b41d0ab5c34f55d66184e5.txt.
INDEXNOW_KEY = "86a211e892b41d0ab5c34f55d66184e5"
TABLE = "molecule_news"
BUCKET = "public-data"
OBJECT = "news/in-the-news.json"
CACHE_SECONDS = 300
WINDOW_DAYS = 7          # a headline counts as this week's news, and the feed's window
RETAIN_DAYS = 21         # rows are deleted this long after their last headline
LIST_CAP = 8             # what the home page shows; printed so a dry run reads the same way
FEED_CAP = 200           # the feed carries every molecule in the window, up to this
USER_AGENT = "MoleculeFinderNewsBot/1.0 (+https://moleculefinder.com)"

# ── names ────────────────────────────────────────────────────────────────────
# Never match on their own. Most are everyday words or name something else as often as the
# element (Mercury, Chrome, Silicon Valley); the metals are mostly commodity prices.
STOP = {
    "iron", "lead", "salt", "water", "gold", "silver", "copper", "tin", "zinc", "mercury",
    "nickel", "cobalt", "chrome", "carbon", "silicon", "neon", "platinum", "titanium",
    "adrenaline", "amaranth", "retinal", "bleach", "poly", "lye", "starch", "sugar", "alcohol",
    "table salt", "common salt", "fad", "agar", "urea", "argon", "radium", "helium", "boron",
    # Brand or molecule names that are also people, companies or products (first dry run,
    # 2026-10-20: 5 of fexofenadine's 7 matches were people called Allegra, all 3 of endorphin's
    # a Saucony running shoe).
    "allegra", "endorphin", "bayer", "actos", "phillips'", "tungsten",
}
# Phrases in which a name is the title of something else (an album, a trend), not the molecule.
EXCLUDE = {
    "dopamine": ["dopamine chamber", "dopamine dressing", "dopamine decor", "dopamine menu"],
    "arsenic": ["arsenic and old lace"],
}
# The only forms in which a stop-listed name matches.
QUALIFIED = {
    "lead": ["lead poisoning", "lead exposure", "lead contamination", "lead levels", "lead pipes",
             "lead pipe", "lead paint", "blood lead", "lead-tainted", "lead tainted"],
    "mercury": ["mercury poisoning", "mercury exposure", "mercury levels", "mercury contamination"],
    "iron": ["iron deficiency", "iron-deficiency", "iron supplements", "iron supplement",
             "iron levels", "iron overload"],
    "sodium-chloride": ["salt intake", "dietary salt", "road salt", "salt consumption"],
    "zinc": ["zinc supplements", "zinc supplement", "zinc deficiency"],
}
# Curated news names, by slug: the forms headlines actually use. Facts, not prose.
ALIASES = {
    "allura-red-ac": ["Red 40", "Red Dye 40", "Red No. 40", "Red Dye No. 40"],
    "erythrosine": ["Red 3", "Red Dye 3", "Red No. 3", "Red Dye No. 3"],
    "tartrazine": ["Yellow 5", "Yellow Dye 5", "Yellow No. 5", "Yellow Dye No. 5"],
    "sunset-yellow-fcf": ["Yellow 6", "Yellow Dye 6", "Yellow No. 6", "Yellow Dye No. 6"],
    "brilliant-blue-fcf": ["Blue 1", "Blue Dye 1", "Blue No. 1", "Blue Dye No. 1"],
    "bisphenol-a": ["BPA"],
    "cannabidiol": ["CBD"],
    "tetrahydrocannabinol": ["THC"],
    "semaglutide": ["Ozempic", "Wegovy", "Rybelsus"],
    "tirzepatide": ["Mounjaro", "Zepbound"],
    "orforglipron": ["Foundayo"],
}
# A dye number only counts beside a word that says it is a dye ("Red 3" is also a team colour).
CONTEXT = {
    "allura-red-ac": r"\b(?:dye|dyes|food|foods|color|colors|colour|colours|fda|candy|ban|banned|bans)\b",
    "erythrosine": r"\b(?:dye|dyes|food|foods|color|colors|colour|colours|fda|candy|ban|banned|bans)\b",
    "tartrazine": r"\b(?:dye|dyes|food|foods|color|colors|colour|colours|fda|candy|ban|banned|bans)\b",
    "sunset-yellow-fcf": r"\b(?:dye|dyes|food|foods|color|colors|colour|colours|fda|candy|ban|banned|bans)\b",
    "brilliant-blue-fcf": r"\b(?:dye|dyes|food|foods|color|colors|colour|colours|fda|candy|ban|banned|bans)\b",
}
_DYE_NUMBER = re.compile(r"^(?:red|yellow|blue|green)\b", re.IGNORECASE)
# DHA is not here: it names three catalogue molecules (DHEA, dihydroxyacetone, docosahexaenoic acid).
ACRONYMS = {"CBD", "THC", "BPA", "GABA"}
# A display synonym is used only when it is shaped like a chemical name.
_CHEMICAL = re.compile(
    r"(?:ine|ol|ide|ate|ane|ene|one|ose|yl|ium|ite|amide|azole|mycin|cillin|pril|sartan|statin|"
    r"olol|azepam|oxacin|tidine|prazole|vir|ase|in)$|\b(?:acid|oxide|chloride|sulfate|sulphate|"
    r"nitrate|phosphate|carbonate|hydroxide|peroxide|acetate|citrate)\b", re.IGNORECASE)
_GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ω": "omega", "κ": "kappa"}


def normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("‐", "-").replace("‑", "-")
    for g, word in _GREEK.items():
        text = text.replace(g, word)
    return re.sub(r"\s+", " ", text).strip().lower()


def _usable(term: str, *, core: bool) -> bool:
    t = term.strip()
    letters = re.sub(r"[^A-Za-z]", "", t)
    if t.upper() in ACRONYMS:
        return True
    if len(letters) < 4 or (t.isupper() and len(t) <= 5):
        return False
    if re.search(r"[\d,\[\]();#|?]", t) or len(t) > 40 or len(t.split()) > 4:
        return False
    if normalize(t) in STOP:
        return False
    if core:
        return True
    # A display synonym only when it is shaped like a chemical name, and, as one word, at least
    # seven letters: the shorter ones that pass the suffix test read as surnames ("Melin").
    return bool(_CHEMICAL.search(t)) and (" " in t or len(letters) >= 7)


def load_molecules(directory: Path = MOLECULES_DIR) -> list[dict]:
    mols = [json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))]
    if not mols:
        raise SystemExit(f"{directory}: no molecule files")
    return mols


def build_index(molecules: list[dict]) -> dict:
    """{normalized term: slug} plus the compiled matcher. A term two molecules share matches
    neither (a wrong match is worse than a missed one), unless it is one of them's title."""
    claims: dict[str, set[str]] = {}
    titles: dict[str, str] = {}
    names: dict[str, str] = {}
    slugs = {m["slug"] for m in molecules}
    for m in molecules:
        slug = m["slug"]
        names[slug] = m["title"]
        core = {m["title"], m.get("preferred_name") or "", m.get("title_synonym") or "",
                re.sub(r"\s*\(.*\)$", "", m.get("wikipedia_title") or ""), *(m.get("brands") or [])}
        terms = {t for t in core if t and _usable(t, core=True)}
        terms |= {t for t in (m.get("display_synonyms") or []) if _usable(t, core=False)}
        for t in terms:
            claims.setdefault(normalize(t), set()).add(slug)
        titles[normalize(m["title"])] = slug
    for slug, aliases in ALIASES.items():
        if slug in slugs:
            for a in aliases:
                claims.setdefault(normalize(a), set()).add(slug)
    for key, phrases in QUALIFIED.items():
        slug = key if key in slugs else next((s for s, n in names.items() if normalize(n) == key), None)
        if slug:
            for p in phrases:
                claims.setdefault(normalize(p), set()).add(slug)
    terms: dict[str, str] = {}
    for term, owners in claims.items():
        if len(owners) == 1:
            terms[term] = next(iter(owners))
        elif term in titles and titles[term] in owners:
            terms[term] = titles[term]
    ordered = sorted(terms, key=len, reverse=True)       # longest first: "sodium chloride" before "sodium"
    pattern = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(t) for t in ordered) + r")(?![a-z0-9])")
    context = {slug: re.compile(rx) for slug, rx in CONTEXT.items()}
    queried = {normalize(b) for m in molecules for b in (m.get("brands") or [])}
    queried |= {normalize(a) for v in ALIASES.values() for a in v}
    queried |= {normalize(p) for v in QUALIFIED.values() for p in v}
    rank = {m["slug"]: int(m.get("pageviews_monthly") or 0) for m in molecules}
    return {"terms": terms, "pattern": pattern, "names": names, "context": context,
            "queried": queried & set(terms), "rank": rank}


def strip_source(title: str, source: str = "") -> str:
    """Google News appends " - Outlet" to every title; it comes off before anything reads it, so
    an outlet's name ("Chemical & Engineering News") can never match."""
    if source and title.endswith(f" - {source}"):
        return title[: -(len(source) + 3)].strip()
    if not source:
        i = title.rfind(" - ")
        if i > 0 and len(title) - i - 3 <= 60:
            return title[:i].strip()
    return title.strip()


# A name followed by one of these is a different compound ("ethylene oxide", "sodium alginate",
# "cellulose acetate"), unless the whole phrase is a name in the catalogue, which matches first.
_COMPOUND_WORD = re.compile(
    r"[\s-]+(?:oxide|dioxide|monoxide|trioxide|glycol|acid|ester|ether|amine|gum|resin|"
    r"[a-z]{3,}(?:ate|ide|ite))\b")
# Headlines about markets and mining, not the molecule: share prices, drilling programmes,
# "market size" reports (first dry run: antimony's 29 matches were nearly all of these).
_MARKET = re.compile(
    r"\b(?:shares?|stocks|stock price|ticker|nasdaq|nyse|tsx|tsxv|asx|otcqb|lse|ipo|futures|"
    r"market (?:size|share|report|forecast|outlook|analysis|growth|trends?)|mines|mining|miners?|"
    r"drill(?:ing|ed|s)?|exploration|porphyry|npv|flow-through|financing|tonnes?|smelter|offtake|"
    r"rare earths?|(?:critical|strategic) minerals?|mineral (?:system|resource|property)|"
    r"project in|claims? package|forecast|market (?:to|by|in) 20\d\d|market to reach|"
    r"private placement|placement|corp|ltd|plc|mineraliz(?:ed|ation)|stibnite|concentrate)\b"
    # Money in the headline: "...Market to Reach USD 5.10 Billion", "CA$3 Million Placement".
    r"|(?:usd|us\$|ca\$|a\$|\$)\s?[\d.,]+\s?(?:billion|million|bn|m)\b"
    # A price move: "United States Antimony Jumps 10%".
    r"|\b(?:jumps?|gains?|soars?|rises?|falls?|drops?|slides?|surges?|plunges?|climbs?|tumbles?|"
    r"rall(?:y|ies))\b[^%]{0,40}\d+(?:\.\d+)?%")
# Text in quotation marks, which is usually the title of a work ('Dopamine Chamber').
_QUOTED = re.compile(r"[\"'“‘]([^\"”’]{2,80}?)[\"'”’](?![a-z])")


def match_headline(headline: str, index: dict) -> list[str]:
    text = normalize(headline)
    if _MARKET.search(text):
        return []
    quoted = [q.span(1) for q in _QUOTED.finditer(text)]
    found = []
    for m in index["pattern"].finditer(text):
        term = m.group(0)
        slug = index["terms"][term]
        if any(a <= m.start() and m.end() <= b for a, b in quoted):
            continue
        if any(text.startswith(x, m.start()) for x in EXCLUDE.get(term, ())):
            continue
        ctx = index["context"].get(slug)
        if ctx and _DYE_NUMBER.match(term) and not ctx.search(text):
            continue
        if _COMPOUND_WORD.match(text, m.end()):
            continue
        if slug not in found:
            found.append(slug)
    return sorted(found)


# ── the news ─────────────────────────────────────────────────────────────────
TOPICS = ['"recall" contamination', '"food dye"', '"FDA" ban chemical', '"carcinogen"',
          '"drug shortage"', '"poisoning" chemical']


def rotate(qs: list[str], slot: int, slots: int = 4) -> list[str]:
    """The day's four runs start from four different points in the batch list, so the request
    budget splits different full batches each time and the runs together cover the catalogue.
    A molecule any run finds stays on the list until its last headline is a week old."""
    if not qs:
        return qs
    k = (slot % slots) * len(qs) // slots
    return qs[k:] + qs[:k]


def queries(index: dict, max_len: int = 700) -> list[str]:
    """What to ask Google News: each molecule's title, plus its brands, curated news names and
    qualified phrases, in OR batches (multiword names quoted), then the topic queries. Display
    synonyms are not queried; they still match inside whatever comes back.

    A query returns at most 100 items however long it is (measured 2026-10-20), so batches stay
    near 40 names, and they are filled in order of the molecule's page views: the names that are
    always in the news share batches with each other instead of crowding a rare name out of its
    only hundred slots."""
    rank = index.get("rank", {})
    wanted = {t for t, slug in index["terms"].items()
              if t == normalize(index["names"][slug]) or t in index.get("queried", set())}
    ordered = sorted(wanted, key=lambda t: (-rank.get(index["terms"][t], 0), t))
    out, batch = [], []
    for t in ordered:
        q = f'"{t}"' if " " in t or "-" in t else t
        if batch and len(" OR ".join(batch + [q])) > max_len:
            out.append(" OR ".join(batch))
            batch = []
        batch.append(q)
    if batch:
        out.append(" OR ".join(batch))
    return out + TOPICS


def rss_url(q: str, days: int) -> str:
    return ("https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{q} when:{days}d")
            + "&hl=en-US&gl=US&ceid=US:en")


def parse_items(xml: str) -> list[dict]:
    items = []
    for block in re.findall(r"<item>(.*?)</item>", xml, re.DOTALL):
        def tag(name: str, block: str = block) -> str:
            m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.DOTALL)
            if not m:
                return ""
            v = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1), flags=re.DOTALL)
            return html.unescape(v).strip()
        title = tag("title")
        if title:
            items.append({"title": title, "link": tag("link"), "source": tag("source"),
                          "pubDate": tag("pubDate")})
    return items


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


FULL = 100           # Google News returns at most this many items for one query
MAX_REQUESTS = 60    # per run, four runs a day


def fetch(qs: list[str], days: int, pause: float = 1.0, budget: int = MAX_REQUESTS,
          get=None) -> tuple[list[dict], int, int]:
    """Every query's items, how many requests failed, and how many were made.

    A batch that comes back FULL may have lost names to a busier one (measured 2026-10-20:
    caffeine alone matched 48 headlines in a week and none inside its batch, which fentanyl
    filled). So a full batch is split in two and both halves asked again, until a name stands
    alone or the request budget is spent. One retry after a 429 or 503."""
    get = get or (lambda url: parse_items(_get(url)))
    queue = list(qs)
    items, failed, made = [], 0, 0
    while queue and made < budget:
        q = queue.pop(0)
        for attempt in (1, 2):
            made += 1
            try:
                got = get(rss_url(q, days))
                items.extend(got)
                parts = q.split(" OR ")
                if len(got) >= FULL and len(parts) > 1:
                    half = len(parts) // 2
                    queue += [" OR ".join(parts[:half]), " OR ".join(parts[half:])]
                break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                code = getattr(exc, "code", None)
                if attempt == 1 and code in (429, 503) and made < budget:
                    time.sleep(5)
                    continue
                failed += 1
                print(f"[news] a query failed ({code or type(exc).__name__}), skipped", flush=True)
                break
        if pause:
            time.sleep(pause)
    if queue:
        print(f"[news] request budget ({budget}) spent with {len(queue)} split batch(es) unasked", flush=True)
    return items, failed, made


def dedupe(items: list[dict]) -> list[dict]:
    """One story found by several queries is one headline."""
    seen: dict[str, dict] = {}
    for it in items:
        key = (it.get("link") or "").split("?")[0] or f"{it['title']}|{it.get('source', '')}"
        seen.setdefault(key, it)
    return list(seen.values())


def _when(pub: str, fallback: datetime) -> datetime:
    try:
        t = email.utils.parsedate_to_datetime(pub)
        t = t if t.tzinfo else t.replace(tzinfo=UTC)
        return min(t.astimezone(UTC), fallback)
    except (TypeError, ValueError):
        return fallback


def match_items(items: list[dict], index: dict, now: datetime, days: int) -> list[dict]:
    """One record per molecule: hits, first and last seen. Most hits first, then most recent."""
    since = now - timedelta(days=days)
    by: dict[str, dict] = {}
    for it in items:
        seen = _when(it.get("pubDate", ""), now)
        if it.get("pubDate") and seen < since:
            continue
        headline = strip_source(it["title"], it.get("source", ""))
        for slug in match_headline(headline, index):
            rec = by.setdefault(slug, {"slug": slug, "name": index["names"][slug], "hits": 0,
                                       "first_seen": seen, "last_seen": seen, "headlines": []})
            rec["hits"] += 1
            rec["first_seen"] = min(rec["first_seen"], seen)
            rec["last_seen"] = max(rec["last_seen"], seen)
            rec["headlines"].append(headline)      # for --show-headlines only; never written
    return sorted(by.values(), key=lambda r: (-r["hits"], -r["last_seen"].timestamp(), r["name"]))


# ── the table, the feed ──────────────────────────────────────────────────────
def iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan_write(found: list[dict], existing: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    """Rows to upsert (names only) and the molecules new to the list. An existing row keeps its
    first_seen and never moves last_seen backwards. Only entrants go to IndexNow: a page does not
    change because its molecule stays in the news, and re-announcing it four times a day is the
    routine resubmission that gets a site's pings discounted (PF's rule)."""
    prev = {r["slug"]: r for r in existing}
    on_list_since = now - timedelta(days=WINDOW_DAYS)
    rows, entrants = [], []
    for m in found:
        p = prev.get(m["slug"])
        first, last = m["first_seen"], m["last_seen"]
        if p:
            first = min(first, _parse(p["first_seen"]))
            last = max(last, _parse(p["last_seen"]))
        rows.append({"slug": m["slug"], "name": m["name"], "first_seen": iso(first),
                     "last_seen": iso(last), "hits": m["hits"], "updated_at": iso(now)})
        if not p or _parse(p["last_seen"]) < on_list_since:
            entrants.append(m)
    return rows, entrants


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp).astimezone(UTC)


def build_feed(rows: list[dict], known: set[str], now: datetime) -> dict:
    """The public JSON: slug, name, first and last seen (dates), headline count. Nothing else."""
    since = now - timedelta(days=WINDOW_DAYS)
    live = [r for r in rows if r["slug"] in known and _parse(r["last_seen"]) >= since]
    live.sort(key=lambda r: (-int(r["hits"]), -_parse(r["last_seen"]).timestamp(), r["name"]))
    return {"generated_at": iso(now), "window_days": WINDOW_DAYS,
            "molecules": [{"slug": r["slug"], "name": r["name"],
                           "first_seen": _parse(r["first_seen"]).date().isoformat(),
                           "last_seen": _parse(r["last_seen"]).date().isoformat(),
                           "hits": int(r["hits"])} for r in live[:FEED_CAP]]}


def _request(method: str, url: str, key: str, body: object = None, headers: dict | None = None) -> bytes:
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(url, data=data, method=method, headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {url.split('?')[0]}: HTTP {exc.code} {exc.read()[:300]!r}") from exc


def write(found: list[dict], known: set[str], url: str, key: str, now: datetime) -> list[dict]:
    rest = f"{url}/rest/v1/{TABLE}"
    entrants: list[dict] = []
    if found:
        inlist = ",".join(urllib.parse.quote(m["slug"]) for m in found)
        existing = json.loads(_request("GET", f"{rest}?select=slug,first_seen,last_seen&slug=in.({inlist})", key))
        rows, entrants = plan_write(found, existing, now)
        _request("POST", f"{rest}?on_conflict=slug", key, rows,
                 {"Prefer": "resolution=merge-duplicates,return=minimal"})
        print(f"[news] {TABLE}: upserted {len(rows)} row(s), {len(entrants)} new to the list", flush=True)
    cutoff = urllib.parse.quote(iso(now - timedelta(days=RETAIN_DAYS)))
    gone = json.loads(_request("DELETE", f"{rest}?last_seen=lt.{cutoff}&select=slug", key,
                               headers={"Prefer": "return=representation"}) or b"[]")
    print(f"[news] {TABLE}: pruned {len(gone)} row(s) older than {RETAIN_DAYS} days", flush=True)
    since = urllib.parse.quote(iso(now - timedelta(days=WINDOW_DAYS)))
    rows = json.loads(_request("GET", f"{rest}?select=slug,name,first_seen,last_seen,hits"
                                      f"&last_seen=gte.{since}&order=hits.desc,last_seen.desc&limit={FEED_CAP}", key))
    feed = build_feed(rows, known, now)
    _request("POST", f"{url}/storage/v1/object/{BUCKET}/{OBJECT}", key, json.dumps(feed).encode(),
             {"x-upsert": "true", "cache-control": f"max-age={CACHE_SECONDS}"})
    print(f"[news] feed: {len(feed['molecules'])} molecule(s) written to {BUCKET}/{OBJECT}", flush=True)
    return entrants


def indexnow(urls: list[str]) -> tuple[int, bool]:
    body = {"host": "moleculefinder.com", "key": INDEXNOW_KEY,
            "keyLocation": f"{SITE}/{INDEXNOW_KEY}.txt", "urlList": urls}
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.status in (200, 202)
    except urllib.error.HTTPError as exc:
        return exc.code, False


# ── main ─────────────────────────────────────────────────────────────────────
def parse_fixture(text: str) -> list[tuple[str, list[str] | None]]:
    """A fixture line is "Headline - Source", optionally " => slug, slug" or " => -" (nobody)."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        head, _, expect = line.partition(" => ")
        exp = None if not _ else ([] if expect.strip() == "-" else [s.strip() for s in expect.split(",") if s.strip()])
        out.append((head.strip(), exp))
    return out


def summary(found: list[dict], n_items: int, days: int) -> None:
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if not out:
        return
    lines = ["## Molecules in the news", "",
             (f"{n_items} headline(s) in the last {days} day(s); **{len(found)} molecule(s) matched** "
              f"(the home page shows the top {LIST_CAP}). Names and counts only."), ""]
    if found:
        lines += ["| # | Molecule | Headlines | Last seen |", "| --- | --- | --- | --- |"]
        lines += [f"| {i} | [{m['name']}]({SITE}/m/{m['slug']}) | {m['hits']} | {m['last_seen'].date()} |"
                  for i, m in enumerate(found, 1)]
    with open(out, "a") as f:
        f.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="news")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--since", type=int, default=WINDOW_DAYS)
    ap.add_argument("--fixture")
    ap.add_argument("--show-headlines", action="store_true",
                    help="local audit: print each match's headlines (never in CI, whose logs are public)")
    args = ap.parse_args(argv)
    if not 1 <= args.since <= 30:
        raise SystemExit("--since takes 1 to 30 days")
    if args.show_headlines and os.environ.get("GITHUB_ACTIONS") == "true":
        raise SystemExit("--show-headlines is for a local audit only: this repo's logs are public")
    now = datetime.now(UTC).replace(microsecond=0)
    molecules = load_molecules()
    index = build_index(molecules)
    if args.fixture:
        args.dry_run = True                   # fixture headlines never reach the table or IndexNow
        items = [{"title": h, "link": "", "source": "", "pubDate": ""}
                 for h, _ in parse_fixture(Path(args.fixture).read_text())]
        failed, n_queries = 0, 0
    else:
        qs = TOPICS + rotate(queries(index)[:-len(TOPICS)], now.hour // 6)
        raw, failed, n_queries = fetch(qs, args.since)
        items = dedupe(raw)
        print(f"[news] {len(qs)} queries, {n_queries} requests after splitting full ones ({failed} failed), "
              f"{len(raw)} item(s), {len(items)} distinct", flush=True)
        if failed > n_queries // 2:
            raise SystemExit(f"[news] {failed} of {n_queries} queries failed; not writing a list built "
                             f"from half the news")
    found = match_items(items, index, now, args.since)
    print(f"[news] {len(found)} molecule(s) matched in {len(items)} headline(s); "
          f"{len(index['terms'])} names matchable", flush=True)
    for i, m in enumerate(found):
        mark = "*" if i < LIST_CAP else " "
        print(f"  {mark} {m['name']} ({m['slug']}) x{m['hits']}, {m['first_seen'].date()} to "
              f"{m['last_seen'].date()}", flush=True)
        if args.show_headlines:
            for h in m["headlines"][:5]:
                print(f"        {h}", flush=True)
    summary(found, len(items), args.since)

    known = {m["slug"] for m in molecules}
    if args.dry_run:
        rows, _ = plan_write(found, [], now)
        print(f"[news] --dry-run: the feed ({BUCKET}/{OBJECT}) would be:")
        print(json.dumps(build_feed(rows, known, now), indent=1))
        print(f"[news] --dry-run: nothing written, nothing submitted "
              f"(would ping IndexNow for {len(found)} page(s) new to the list, plus the home page).")
        return 0
    url, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("[news] SUPABASE_URL / SUPABASE_SERVICE_KEY unset: nothing written, nothing pinged (no-op).")
        return 0
    entrants = write(found, known, url, key, now)
    if not entrants:
        print("[news] nobody new to the list: nothing to submit to IndexNow")
        return 0
    urls = [f"{SITE}/m/{m['slug']}" for m in entrants] + [f"{SITE}/"]
    status, ok = indexnow(urls)
    print(f"[news] IndexNow: {len(urls)} URL(s), HTTP {status}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
