"""PubChem access: batched PUG-REST properties + PUG-View annotations.

Rate-limited to well under PubChem's published limits (<=5 req/s, <=400/min).
Raw responses are cached to disk so re-runs are cheap and resumable.
"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests
from tenacity import retry, wait_exponential, stop_after_attempt

from ..config import PUBCHEM_REST, PUBCHEM_VIEW, PUBCHEM_BATCH, PUBCHEM_MAX_RPS, USER_AGENT, RAW_CACHE

PROPERTIES = (
    "MolecularFormula,MolecularWeight,CanonicalSMILES,IsomericSMILES,InChI,InChIKey,"
    "XLogP,TPSA,HBondDonorCount,HBondAcceptorCount,RotatableBondCount,Complexity,Charge,"
    # Volume3D is a computed 3D property PubChem returns ONLY when the compound has a 3D
    # conformer, so its presence is our build-time "has a 3D structure" signal (the web hides
    # the 3D toggle when absent). Large peptides / polymers (insulin, inulin) have no 3D.
    "Volume3D"
)

_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT
_min_interval = 1.0 / PUBCHEM_MAX_RPS
_last_call = 0.0


def _throttle() -> None:
    global _last_call
    dt = time.monotonic() - _last_call
    if dt < _min_interval:
        time.sleep(_min_interval - dt)
    _last_call = time.monotonic()


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


@retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
def properties(cids: list[int]) -> list[dict]:
    """Batched property fetch. Returns one dict per CID."""
    out: list[dict] = []
    for chunk in _chunks(cids, PUBCHEM_BATCH):
        _throttle()
        # PUG-REST wants ONE comma-separated cid parameter; repeated `cid=`
        # params silently return only the first CID.
        body = "cid=" + ",".join(str(c) for c in chunk)
        url = f"{PUBCHEM_REST}/compound/cid/property/{PROPERTIES}/JSON"
        r = _session.post(url, data=body,
                          headers={"Content-Type": "application/x-www-form-urlencoded"},
                          timeout=60)
        r.raise_for_status()
        out.extend(r.json()["PropertyTable"]["Properties"])
    return out


def _cache_dir() -> Path:
    d = RAW_CACHE / "pubchem"
    d.mkdir(parents=True, exist_ok=True)
    return d


@retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(4))
def name_to_cid(name: str) -> int | None:
    """Resolve a common/chemical name to its primary PubChem CID (cached).

    This is filter-2 from the build plan (§4): it maps a bounded marquee list to
    CIDs so the famous molecules are *guaranteed* in the canon, independent of
    whatever the Wikidata notability net happens to catch.
    """
    cache = _cache_dir() / f"name-{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    _throttle()
    url = f"{PUBCHEM_REST}/compound/name/{quote(name)}/cids/JSON"
    r = _session.get(url, timeout=30)
    if r.status_code == 404:
        cache.write_text("null")
        return None
    r.raise_for_status()
    cids = r.json().get("IdentifierList", {}).get("CID", [])
    cid = int(cids[0]) if cids else None
    cache.write_text(json.dumps(cid))
    return cid


@retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
def synonyms(cids: list[int], limit: int = 20) -> dict[int, list[str]]:
    """Batched synonym fetch. Returns {cid: [name, ...]} (at most `limit` each)."""
    out: dict[int, list[str]] = {}
    for chunk in _chunks(cids, PUBCHEM_BATCH):
        _throttle()
        body = "cid=" + ",".join(str(c) for c in chunk)     # comma-separated, not repeated params
        url = f"{PUBCHEM_REST}/compound/cid/synonyms/JSON"
        r = _session.post(url, data=body,
                          headers={"Content-Type": "application/x-www-form-urlencoded"},
                          timeout=60)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        for info in r.json().get("InformationList", {}).get("Information", []):
            out[int(info["CID"])] = (info.get("Synonym") or [])[:limit]
    return out


@retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(4))
def pug_view(cid: int, heading: str) -> dict | None:
    """Fetch a PUG-View annotation heading (e.g. 'GHS Classification', 'Toxicity').

    Cached under data/raw_cache/pubchem/<cid>-<heading>.json.
    """
    RAW_CACHE.joinpath("pubchem").mkdir(parents=True, exist_ok=True)
    cache = RAW_CACHE / "pubchem" / f"{cid}-{heading.replace(' ', '_')}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    _throttle()
    url = f"{PUBCHEM_VIEW}/data/compound/{cid}/JSON"
    r = _session.get(url, params={"heading": heading}, timeout=60)
    if r.status_code == 404:
        cache.write_text("null")
        return None
    r.raise_for_status()
    data = r.json()
    cache.write_text(json.dumps(data))
    return data
