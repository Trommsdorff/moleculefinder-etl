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


def sparql(query: str, timeout: int = 120) -> list[dict]:
    """Run a SPARQL query against WDQS, return simplified bindings."""
    r = requests.get(
        WDQS_ENDPOINT,
        params={"query": query, "format": "json"},
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
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
    """Return {cid: {"desc": <CC0 description|None>, "qid": <Qxxxx>}} for the given CIDs."""
    if not cids:
        return {}
    values = " ".join(f'"{int(c)}"' for c in cids)
    out: dict[int, dict] = {}
    for row in sparql(DESCRIPTIONS_BY_CID_SPARQL % values):
        c = row.get("cid")
        if not c:
            continue
        c = int(c)
        # First binding wins, but prefer one that actually carries a description.
        if c not in out or (row.get("desc") and not out[c].get("desc")):
            out[c] = {"desc": row.get("desc"), "qid": row["compound"].rsplit("/", 1)[-1]}
    return out
