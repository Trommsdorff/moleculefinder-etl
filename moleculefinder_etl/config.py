"""Runtime configuration and shared constants.

Everything tunable lives here so the pipeline stages read one source of truth.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "data"
SEED_DIR = DATA / "seed"
RAW_CACHE = DATA / "raw_cache"
SNAPSHOTS = DATA / "snapshots"
CURATED_DIR = Path(__file__).resolve().parent / "sources" / "curated"
SEEDS_DIR = Path(__file__).resolve().parent / "sources" / "seeds"

# ── External endpoints ───────────────────────────────────────────────────────
WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
PUBCHEM_REST = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
WIKIMEDIA_PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"

# PubChem asks for <=5 req/s, <=400/min. We stay conservative.
PUBCHEM_MAX_RPS = 5
PUBCHEM_BATCH = 150                 # CIDs per property POST
USER_AGENT = "MoleculeFinderBot/0.1 (137 Finder LLC; contact: garrett@137finder.com)"

# ── Raw-cache expiry (sources/cache.py) ──────────────────────────────────────
# The DERIVED sources expire. Wikidata items are merged and split upstream and
# PUG-View annotations get added to, so a stale copy of either is a claim about the past
# presented as the present: that is what regressed 26 molecules on 2026-09-08. PubChem
# properties describe what a CID *is* and are cached forever, on purpose. PubChem synonyms
# were too, until 2026-09-12 (see SYNONYMS_CACHE_TTL_DAYS below).
# 6 days, not 7: the cron runs weekly and CI carries data/raw_cache forward between runs
# (actions/cache save+restore), so a 7-day window would sit exactly on the boundary and a
# few minutes of scheduler jitter would decide whether a scheduled run re-read Wikidata.
# 6 makes it unconditional, for the cost of one batched SPARQL query per run. PUG-View is
# 30 because re-warming 788 CIDs x 2 headings costs ~5 minutes of the rate limit and an
# annotation moves far more slowly than a wiki item.
WIKIDATA_CACHE_TTL_DAYS = float(os.getenv("MFETL_WIKIDATA_TTL_DAYS", "6"))
PUGVIEW_CACHE_TTL_DAYS = float(os.getenv("MFETL_PUGVIEW_TTL_DAYS", "30"))
# PubChem synonyms expire on PUG-View's schedule since 2026-09-12. A CID's name list does move
# upstream (12 molecules' lists between 2026-09-09 and 2026-09-12), and CI carries its cache
# forward, so a list that never expired there disagreed with every fresh local fetch. The cost
# is one re-fetch a month, in batched POSTs of PUBCHEM_BATCH CIDs.
SYNONYMS_CACHE_TTL_DAYS = float(os.getenv("MFETL_SYNONYMS_TTL_DAYS", "30"))

# ── Canon selection ──────────────────────────────────────────────────────────
CANON_TARGET = int(os.getenv("MFETL_CANON_TARGET", "10000"))
SIMILARITY_TOP_N = 30
SIMILARITY_FLOOR = 0.35
MORGAN_RADIUS = 2
MORGAN_NBITS = 2048


@dataclass(frozen=True)
class Settings:
    supabase_url: str | None
    supabase_service_key: str | None
    canon_target: int = CANON_TARGET

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_service_key=os.getenv("SUPABASE_SERVICE_KEY"),
            canon_target=int(os.getenv("MFETL_CANON_TARGET", str(CANON_TARGET))),
        )

    @property
    def has_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)
