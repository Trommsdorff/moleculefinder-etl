"""Wikidata SPARQL: the notability filter + CC0 descriptions.

We only take CC0 fields (labels, descriptions, external IDs). Never Wikipedia
article prose (CC BY-SA).
"""
from __future__ import annotations
import requests
from ..config import WDQS_ENDPOINT, USER_AGENT

# Notable = a chemical compound with an English Wikipedia article and a PubChem CID.
NOTABLE_COMPOUNDS_SPARQL = """
SELECT ?compound ?compoundLabel ?desc ?cid ?formula ?inchikey ?cas WHERE {
  ?compound wdt:P31 wd:Q11173 .            # instance of chemical compound
  ?compound wdt:P662 ?cid .                # PubChem CID (join key)
  OPTIONAL { ?compound wdt:P274 ?formula. }
  OPTIONAL { ?compound wdt:P235 ?inchikey. }
  OPTIONAL { ?compound wdt:P231 ?cas. }
  ?article schema:about ?compound ;
           schema:isPartOf <https://en.wikipedia.org/> .   # notability
  OPTIONAL { ?compound schema:description ?desc . FILTER(LANG(?desc)="en") }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""


class WikidataQueryError(RuntimeError):
    """WDQS did not answer. Raised so a run fails loudly instead of skipping quietly."""


def sparql(query: str, timeout: int = 120, method: str = "GET") -> list[dict]:
    """Run a SPARQL query against WDQS, return simplified bindings.

    ``method="POST"`` sends the query in the request BODY instead of the URL. WDQS accepts
    both and returns the same answer; the difference is that a GET carries the whole query
    in the query string, and WDQS rejects the request with **HTTP 414 URI Too Long** once
    that gets big. Measured on the real catalog: the descriptions query breaks between 612
    and 613 CIDs (about 4,757 characters of query). Any caller whose query grows with the
    catalog must POST, or it works until the catalog crosses a line and then stops.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
    if method.upper() == "POST":
        r = requests.post(
            WDQS_ENDPOINT,
            data={"query": query, "format": "json"},
            headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
    else:
        r = requests.get(
            WDQS_ENDPOINT,
            params={"query": query, "format": "json"},
            headers=headers,
            timeout=timeout,
        )
    r.raise_for_status()
    rows = []
    for b in r.json()["results"]["bindings"]:
        rows.append({k: v["value"] for k, v in b.items()})
    return rows


def notable_compounds() -> list[dict]:
    """Return notable compounds: cid, label, description, formula, inchikey, cas."""
    return sparql(NOTABLE_COMPOUNDS_SPARQL)


# CC0 descriptions + QIDs for a known set of PubChem CIDs. Used to give the
# marquee molecules (which the narrow notability query above misses) their CC0
# summary and Wikidata id. P662 is an external-identifier (string) property.
DESCRIPTIONS_BY_CID_SPARQL = """
SELECT ?cid ?desc ?compound WHERE {
  VALUES ?cid { %s }
  ?compound wdt:P662 ?cid .
  OPTIONAL { ?compound schema:description ?desc . FILTER(LANG(?desc)="en") }
}
"""


def descriptions_for_cids(cids: list[int]) -> dict[int, dict]:
    """Return {cid: {"desc", "qid", "label", "aliases"}} for the given CIDs: the CC0
    description and QID of the item chosen for each CID, and that item's English label and
    aliases in Wikidata's order (see ``names_for_qids``).

    **POSTed, always.** This query inlines one ``VALUES`` entry per CID, so its length is
    the size of the catalog. As a GET it returned HTTP 414 above ~612 CIDs, and the catalog
    is 770: on 2026-09-09 every Wikidata refresh was failing for this reason and the run
    logged a warning and carried on with cached values. POST puts the query in the body,
    where there is no such ceiling, and it stays correct as the catalog grows.
    """
    if not cids:
        return {}
    values = " ".join(f'"{int(c)}"' for c in cids)
    candidates: dict[int, list[tuple[str, str | None]]] = {}
    for row in sparql(DESCRIPTIONS_BY_CID_SPARQL % values, method="POST"):
        c = row.get("cid")
        if not c:
            continue
        candidates.setdefault(int(c), []).append(
            (row["compound"].rsplit("/", 1)[-1], row.get("desc")))
    chosen = {c: _choose_item(items) for c, items in candidates.items()}
    # The chosen item's English label and aliases ride along (display synonyms, 2026-09-12).
    # They are read by QID AFTER selection, so which item a CID maps to is decided exactly as
    # before and never by its names.
    names = names_for_qids([d["qid"] for d in chosen.values()])
    return {c: {**d, **names.get(d["qid"], {"label": None, "aliases": []})}
            for c, d in chosen.items()}


# An item's English label and aliases, IN THE ORDER WIKIDATA STORES THEM, from the Wikidata API
# rather than from SPARQL. The obvious route was GROUP_CONCAT(skos:altLabel) inside the query
# above, and it cannot give that order: RDF has no order for an item's aliases, so WDQS
# concatenates them in whatever order its index yields, and that differs between its backend
# servers. Measured 2026-09-12: the same query three times, a minute apart, answered by three
# servers, came back with a different alias order for 13 of 136 items (the same set every
# time). A synonym line built on it would reshuffle on about one page in ten every week, which
# is the churn run 3 removed. wbgetentities returns each item's own stored order; it is CC0 like
# everything else here and is keyed by the QID the query above already chose.
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
NAMES_BATCH = 50                        # wbgetentities accepts at most 50 ids per request


def names_for_qids(qids: list[str]) -> dict[str, dict]:
    """Return {qid: {"label": <English label|None>, "aliases": [<English aliases>]}}, aliases
    in the item's own order. An id Wikidata reports missing is left out."""
    ids = sorted({q for q in qids if q}, key=lambda q: (_qid_sort_key(q), q))
    out: dict[str, dict] = {}
    for i in range(0, len(ids), NAMES_BATCH):
        r = requests.get(
            WIKIDATA_API,
            params={"action": "wbgetentities", "ids": "|".join(ids[i:i + NAMES_BATCH]),
                    "props": "labels|aliases", "languages": "en", "format": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=60,
        )
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            err = body["error"]
            raise RuntimeError(f"wbgetentities {err.get('code')}: {err.get('info')}")
        for qid, entity in (body.get("entities") or {}).items():
            if "missing" in entity:
                continue
            label = ((entity.get("labels") or {}).get("en") or {}).get("value")
            aliases = [a["value"] for a in ((entity.get("aliases") or {}).get("en") or [])
                       if a.get("value")]
            out[qid] = {"label": label, "aliases": aliases}
    return out


PLACEHOLDER_DESCRIPTION = "chemical compound"


def _choose_item(items: list[tuple[str, str | None]]) -> dict:
    """Pick ONE Wikidata item for a PubChem CID, deterministically.

    A PubChem CID does not identify a Wikidata item: **70 of the catalog's 769 CIDs have two
    items carrying the same P662**, because Wikidata models the element and its allotrope,
    or the hormone and the compound, as separate things that share a PubChem entry. The old
    rule was "first binding wins", i.e. whatever order WDQS happened to return, which is
    arbitrary and moves when Wikidata's index is rebuilt. Measured on 2026-09-09 it had
    moved for 15 of them since the snapshot was built, and would have written
    ``"chemical compound"`` over the real summaries of fluorine, mercury and vasopressin,
    and swapped carbon, phosphorus and lead off their element items onto allotropes.

    Two rules, in order:

    1. **Never pick a placeholder over a real description.** ``"chemical compound"`` is the
       string phase 1 exists to remove from the site; it is never the better answer.
    2. **Then the lowest Q-number**, which is the oldest item. Older is a good proxy for
       canonical: the element items (Q623 carbon, Q650 fluorine, Q674 phosphorus, Q708 lead,
       Q925 mercury) all long predate the allotrope and bulk-import items that shadow them,
       and the bulk-batch ``Q1063456xx`` items behind the 2026-09-08 regression sort last by
       construction.

    Measured against the committed snapshot: 759 of 769 CIDs keep the QID they already had,
    7 of the 10 changes replace a ``"chemical compound"`` summary with a real one, and none
    introduce a placeholder. Repeating the query returns the same choice for all 769.
    """
    def is_placeholder(desc: str | None) -> bool:
        return bool(desc) and desc.strip().lower().rstrip(".") == PLACEHOLDER_DESCRIPTION

    real = [i for i in items if i[1] and not is_placeholder(i[1])] or items
    qid, desc = min(real, key=lambda i: (_qid_sort_key(i[0]), i[0]))
    return {"desc": desc, "qid": qid}


def _qid_sort_key(qid: str) -> int:
    """Numeric part of a Qid, so Q925 sorts before Q6818555 (string order would not)."""
    try:
        return int(qid.lstrip("Qq"))
    except ValueError:
        return 1 << 62                      # an unparseable id sorts last, never chosen first
