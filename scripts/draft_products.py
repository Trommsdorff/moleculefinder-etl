"""Draft products.yaml rows from DailyMed (growth plan run C1). A helper for the HAND-MAINTAINED seed:
it never writes the seed, it prints candidate rows for a person to check and paste.

    ./.venv/bin/python3 scripts/draft_products.py licences            # every NDA brand in licences.yaml
    ./.venv/bin/python3 scripts/draft_products.py names list.txt      # one "Name|kind|QUERY" per line

For each candidate it asks DailyMed for the labels whose title starts with the brand ("ZOLOFT (",
the exact product, before "ZOLOFT " plus a variant), keeps the brand owner's label (the Drugs@FDA
holder where licences.yaml names one) over a repackager's, and takes the newest. A row is printed
with the label's own title as a comment, so the check is reading two lines. A brand found only on
a repackager's label is printed commented out: run C1 kept none of those.

Network: DailyMed's public web service, about three requests a second. Writes nothing.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

API = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"
UA = "MoleculeFinderBot/0.1 (137 Finder LLC; contact: garrett@137finder.com)"
LICENCES = Path(__file__).resolve().parent.parent / "moleculefinder_etl" / "sources" / "seeds" / "licences.yaml"
# Labelers that relabel another company's product (repackagers, distributors, travel sizes, stores).
REPACKAGER = re.compile(
    r"REPACK|PHARMA SOLUTIONS|MEDICAL SUPPLY|PHYSICIANS TOTAL CARE|REBEL DISTRIBUTORS|STAT RX|"
    r"A-S MEDICATION|BRYANT RANCH|PROFICIENT RX|DIRECT[ _]RX|NUCARE|QUALITY CARE|PD-RX|LAKE ERIE|"
    r"PREFERRED PHARMACEUTICALS|HARKINS|RPK PHARMA|HENRY SCHEIN|CARDINAL HEALTH|MCKESSON|"
    r"AMERICAN HEALTH PACKAGING|MAJOR PHARMACEUTICALS|AIDAREX|NORTHWIND|MEDSOURCE|UNIT DOSE|"
    r"STATE OF FLORIDA|CLINICAL SOLUTIONS|CONTRACT PHARMACY|QPHARMA|ADVANCED RX|ASCLEMED|ENOVACHEM|"
    r"GOLDEN STATE|APHENA|PACKAG|DISTRIBUT|WHOLESALE|SAFECOR|CARILION|REDPHARM|THOMPSON MEDICAL|"
    r"LIL'? DRUG|ALLEGIS|NORTHSTAR|PRASCO|PRECISION DOSE|AVKARE|AVPAK|PREPAK|READYMEDS|"
    r"SELECT CONSUMER|NAVAJO|R J GENERAL|SPORTPHARM|TRAVEL|CVS|WALGREEN|MEIJER|KROGER|RITE AID|"
    r"WAL-?MART|DOLGENCORP|DOLLAR|AMAZON|PUBLIX|MEDIQUE|FIRST AID|MEDLINE", re.IGNORECASE)


def _get(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                time.sleep(0.3)
                return json.load(r)
        except OSError:
            time.sleep(3 * (attempt + 1))
    raise SystemExit(f"DailyMed did not answer: {url}")


def _labels(params: dict, pages: int = 3) -> list[dict]:
    out: list[dict] = []
    for page in range(1, pages + 1):
        body = _get({**params, "pagesize": 100, "page": page})
        out += body["data"]
        if body["metadata"]["current_page"] >= body["metadata"]["total_pages"]:
            break
    return out


def _labeler(row: dict) -> str:
    t = row["title"]
    return t[t.rfind("[") + 1:t.rfind("]")] if "[" in t else ""


def pick(rows: list[dict], brand: str, holder: str | None = None) -> tuple[dict | None, bool]:
    """(the label to use, whether its labeler is the brand owner rather than a repackager)."""
    q = brand.upper()
    pool = [r for r in rows if r["title"].upper().startswith(q + " (")] or \
           [r for r in rows if r["title"].upper().startswith(q + " ")]
    if holder:
        word = holder.split()[0].upper()
        pool = [r for r in pool if word in _labeler(r).upper()] or pool
    owners = [r for r in pool if not REPACKAGER.search(_labeler(r))]
    chosen = owners or pool
    if not chosen:
        return None, False
    newest = max(chosen, key=lambda r: (dt.datetime.strptime(r["published_date"], "%b %d, %Y"), r["spl_version"]))
    return newest, bool(owners)


def slug(name: str) -> str:
    s = name.lower().replace("&", " and ").replace("+", " plus ").replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("licences", "names"):
        print(__doc__)
        return 2
    items: list[tuple[str, str, str, str | None, str | None]] = []      # name, kind, query, appl, holder
    if argv[0] == "licences":
        for _, rec in sorted((yaml.safe_load(LICENCES.read_text()) or {}).items()):
            if rec.get("register") == "Drugs@FDA" and rec.get("product") and not str(rec["application"]).startswith("ANDA"):
                items.append((rec["product"], "medicine", rec["product"], rec["application"].replace(" ", ""), rec.get("holder")))
    else:
        for line in Path(argv[1]).read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                name, kind, query = (line.split("|") + ["", ""])[:3]
                items.append((name, kind or "medicine", query or name, None, None))
    for name, kind, query, appl, holder in items:
        rows = _labels({"application_number": appl} if appl else {"drug_name": query})
        row, owner = pick(rows, query, holder)
        if row is None:
            print(f"  # {name}: no DailyMed label titled {query.upper()!r}")
            continue
        line = f'  - {{slug: {slug(name)}, name: {json.dumps(name)}, kind: {kind}, dailymed: {row["setid"]}}}'
        print(f"  # {row['title'][:150]}")
        print(line if owner else f"  # REPACKAGER ONLY, not used: {line.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
