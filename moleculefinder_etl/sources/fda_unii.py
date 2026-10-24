"""The FDA's UNII table: the code a DailyMed label carries, with the FDA's own PubChem link.

WHY (trust run 3, 2026-10-24). A label ingredient is matched to a molecule by its FDA UNII code
(``transform/products.py``), and until this run the only source of a molecule's UNII was
PubChem's synonym list, read for the ``UNII-XXXXXXXXXX`` entries. PubChem files many UNIIs
bare (tirzepatide: ``OYN3CCI6QE``), some under a different compound, and some not at all
(minoxidil's 261 synonyms hold none), so 23 label ingredients that ARE MoleculeFinder molecules
were shown as "not yet MoleculeFinder molecules" on 118 pages. The FDA publishes the table
itself: every UNII with its display name, the PubChem CID and the InChIKey the FDA records for
the substance. That is the authority on what a UNII means, so the molecule-side index is built
from it first (``products.unii_index``), and PubChem's synonym read is only a fallback for a
record the table does not link.

THE DOWNLOAD. ``precision.fda.gov/uniisearch/archive/latest/UNII_Data.zip`` (redirects to the
newest dated edition; 14.5 MB) holds ``UNII_Records_<date>.txt``, tab-separated, UTF-8, one row
per UNII, with the columns the enclosed README documents: UNII, DISPLAY_NAME, RN, EC, NCIT,
RXCUI, PUBCHEM, SMSID, EPA_CompTox, ..., MF, INCHIKEY, SMILES, INGREDIENT_TYPE, UTF8_DISPLAY_NAME,
SUBSTANCE_TYPE. Verified 2026-10-24 (edition 4 Aug 2026: 171,912 rows, no UNII twice, 126,672
with a PubChem CID, 129,398 with an InChIKey). The parser reads columns BY NAME and refuses an
edition that lacks one of the four it needs, so a format change fails the run instead of
matching nothing. Licence: FDA website policies, "in the public domain and may be republished,
reprinted and otherwise used freely" (registry key ``fda_unii``, class ``public_domain``).

THE CACHE. The four columns of every row, parsed, in one dated envelope under
``data/raw_cache/fda/`` (13.7 MB, like the parsed DailyMed labels; ``RECORDS_PREFIX`` is bumped
when the kept columns change), so the table travels with the snapshot through the inputs
artifact (``moleculefinder_etl/inputs.py``) and a pinned build reads exactly the edition main
was built from. The weekly refresh re-reads it every run (``FDA_UNII_CACHE_TTL_DAYS``, 6 days,
like the labels and Wikidata): the FDA publishes a new edition every month or two.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from dataclasses import dataclass

import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from ..config import FDA_UNII_CACHE_TTL_DAYS, FDA_UNII_URL, RAW_CACHE, USER_AGENT
from . import cache
from .registry import assert_not_blocked

log = logging.getLogger("mfetl.fda_unii")

SOURCE_KEY = "fda_unii"
RECORDS_PREFIX = "unii-records-v2"           # bump when the kept columns change (v2: SUBSTANCE_TYPE)
CACHE_PATH = RAW_CACHE / "fda" / f"{RECORDS_PREFIX}.json"
RECORDS_MEMBER = re.compile(r"(^|/)UNII_Records_[^/]*\.txt$", re.IGNORECASE)
COLUMNS = ("UNII", "DISPLAY_NAME", "PUBCHEM", "INCHIKEY", "SUBSTANCE_TYPE")
UNII_RE = re.compile(r"^[0-9A-Z]{10}$")
INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
# ISO 11238 substance types the FDA defines by their SOURCE rather than a structure (a plant
# extract, an insect, a syrup). The FDA may still record a PubChem CID for one (COCHINEAL ->
# carminic acid, CORN SYRUP -> a glucose), but that is a reference, not an identity: such a code
# reaches a molecule only through the hand list, never through the table's link or a rule.
SOURCE_DEFINED_KINDS = frozenset({"structurallydiverse"})

_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


class FdaUniiFormatError(RuntimeError):
    """The download is not the table this module knows how to read (a column renamed, no
    records file in the zip). The run stops rather than matching nothing."""


@dataclass(frozen=True)
class Row:
    unii: str
    name: str
    cid: int | None
    inchikey: str | None
    kind: str = ""                            # the FDA's ISO 11238 substance type, as written

    @property
    def defined_by_structure(self) -> bool:
        return self.kind.lower() not in SOURCE_DEFINED_KINDS


class Table:
    """The parsed table, indexed three ways. ``by_cid`` and ``by_inchikey`` keep the FDA's own
    row order so a lookup is deterministic."""

    def __init__(self, data: dict):
        self.file: str = str(data.get("file") or "")
        self.rows: dict[str, Row] = {}
        self.by_cid: dict[int, list[str]] = {}
        self.by_inchikey: dict[str, list[str]] = {}
        for unii, name, cid, inchikey, kind in data.get("rows") or []:
            row = Row(str(unii), str(name), int(cid) if cid is not None else None, inchikey or None, str(kind or ""))
            self.rows[row.unii] = row
            if row.cid is not None:
                self.by_cid.setdefault(row.cid, []).append(row.unii)
            if row.inchikey:
                self.by_inchikey.setdefault(row.inchikey, []).append(row.unii)

    def defined_by_structure(self, unii: str | None) -> bool:
        """False only for a code the FDA registers as a source-defined substance (``SOURCE_DEFINED_KINDS``);
        a code the table does not know is not held against it."""
        row = self.row(unii)
        return row is None or row.defined_by_structure

    def __len__(self) -> int:
        return len(self.rows)

    def __contains__(self, unii: object) -> bool:
        return unii in self.rows

    def row(self, unii: str | None) -> Row | None:
        return self.rows.get(unii or "")

    def cid(self, unii: str | None) -> int | None:
        row = self.row(unii)
        return row.cid if row else None

    def inchikey(self, unii: str | None) -> str | None:
        row = self.row(unii)
        return row.inchikey if row else None

    def name(self, unii: str | None) -> str | None:
        row = self.row(unii)
        return row.name if row else None


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True
    resp = getattr(exc, "response", None)
    return resp is not None and resp.status_code in (429, 500, 502, 503, 504)


def parse(zip_bytes: bytes) -> dict:
    """The compact table from the zip: ``{"file": <records member>, "rows": [[UNII, DISPLAY_NAME,
    PUBCHEM or None, INCHIKEY or None, SUBSTANCE_TYPE], ...]}`` in the FDA's row order. Columns
    are found by name; a missing one, or no records member, is a format error. A row whose UNII
    is not ten capitals and digits is skipped; one whose PUBCHEM is not an integer (one row
    carries a CAS number there) or whose INCHIKEY is malformed keeps the row with that field
    dropped."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        members = [i.filename for i in z.infolist() if RECORDS_MEMBER.search(i.filename)]
        if len(members) != 1:
            raise FdaUniiFormatError(f"expected one UNII_Records_*.txt in the FDA zip, found {members}")
        text = z.read(members[0]).decode("utf-8-sig")
    csv.field_size_limit(10 ** 8)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter="\t")
    header = next(reader, None) or []
    where = {h.strip(): i for i, h in enumerate(header)}
    missing = [c for c in COLUMNS if c not in where]
    if missing:
        raise FdaUniiFormatError(f"the FDA UNII table lacks column(s) {missing}; header was {header[:30]}")
    rows: list[list] = []
    skipped = 0
    at = {c: where[c] for c in COLUMNS}

    def col(rec: list[str], name: str) -> str:
        i = at[name]
        return rec[i].strip() if i < len(rec) else ""

    for rec in reader:
        unii = col(rec, "UNII")
        if not UNII_RE.match(unii):
            skipped += 1
            continue
        pubchem = col(rec, "PUBCHEM")
        inchikey = col(rec, "INCHIKEY")
        rows.append([unii, col(rec, "DISPLAY_NAME"), int(pubchem) if pubchem.isdigit() else None,
                     inchikey if INCHIKEY_RE.match(inchikey) else None, col(rec, "SUBSTANCE_TYPE")])
    if skipped:
        log.info("  fda_unii: %d row(s) without a ten-character UNII skipped", skipped)
    return {"file": members[0].rsplit("/", 1)[-1], "rows": rows}


@retry(wait=wait_exponential(multiplier=2, min=2, max=120), stop=stop_after_attempt(5),
       retry=retry_if_exception(_is_transient), before_sleep=before_sleep_log(log, logging.WARNING),
       reraise=True)
def download(url: str = FDA_UNII_URL) -> bytes:
    r = _session.get(url, timeout=300)
    r.raise_for_status()
    return r.content


def cached(max_age_days: float = FDA_UNII_CACHE_TTL_DAYS) -> Table | None:
    """The cached table, or None when it is not cached (or expired)."""
    hit = cache.read_json(CACHE_PATH, max_age_days)
    return Table(hit.value) if hit is not None and isinstance(hit.value, dict) else None


def warm(fetch=None) -> Table:
    """The table, fetched into the cache when the cache does not hold it fresh (the fetch stage).
    ``fetch`` returns the zip bytes; tests pass their own."""
    assert_not_blocked(SOURCE_KEY)
    table = cached()
    if table is not None:
        return table
    data = parse((fetch or download)())
    cache.write_json(CACHE_PATH, data)
    table = Table(data)
    log.info("  fda_unii: fetched %s, %d UNIIs (%d with a PubChem CID, %d with an InChIKey)",
             data["file"], len(table), len(table.by_cid), len(table.by_inchikey))
    return table
