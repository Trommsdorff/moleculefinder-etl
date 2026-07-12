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
