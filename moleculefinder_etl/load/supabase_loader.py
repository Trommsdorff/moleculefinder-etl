"""Idempotent upserts into Supabase via the service role.

Every stage writes an `ingest_run` row for observability. Loads are idempotent:
tables with a natural key upsert `ON CONFLICT`; the few child tables without a
unique key (synonyms, toxicity rows, content) are replaced per molecule. Row
construction is a pure function (`build_db_rows`) so it can be unit-tested
without a live database.
"""
from __future__ import annotations
import logging
import os
from ..config import Settings
from ..sources.registry import source_rows

log = logging.getLogger("mfetl")


def get_client(settings: Settings | None = None):
    from supabase import create_client
    s = settings or Settings.from_env()
    if not s.has_supabase:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
    return create_client(s.supabase_url, s.supabase_service_key)


def upsert(client, table: str, rows: list[dict], on_conflict: str) -> int:
    if not rows:
        return 0
    client.table(table).upsert(rows, on_conflict=on_conflict).execute()
    return len(rows)


def load_sources(client) -> int:
    return upsert(client, "source", source_rows(), on_conflict="key")


def record_run(client, stage: str, status: str, rows: int, notes: str = "") -> None:
    client.table("ingest_run").insert({
        "git_sha": os.getenv("GITHUB_SHA"), "stage": stage,
        "status": status, "rows_upserted": rows, "notes": notes,
    }).execute()


# ── Row construction (pure; unit-tested) ─────────────────────────────────────
def build_db_rows(molecules: list[dict]) -> dict[str, list[dict]]:
    """Turn assembled molecule records into per-table rows keyed by natural keys.

    FKs are left as natural keys (`cid`, `neighbor_cid`, `category_slug`,
    `_source`) here; `load_all` resolves them to surrogate ids after the parent
    upserts. Deterministic and side-effect free.
    """
    out: dict[str, list[dict]] = {k: [] for k in (
        "molecule", "descriptor", "synonym", "property", "toxicity_value",
        "ghs_classification", "category", "molecule_category", "similarity_edge",
        "hook", "content_block")}
    categories: dict[str, dict] = {}
    cids = {m["cid"] for m in molecules}

    for m in molecules:
        cid = m["cid"]
        out["molecule"].append({
            "cid": cid, "slug": m["slug"], "title": m["title"],
            "preferred_name": m.get("preferred_name"), "iupac_name": m.get("iupac_name"),
            "molecular_formula": m.get("molecular_formula"), "molecular_weight": m.get("molecular_weight"),
            "canonical_smiles": m.get("canonical_smiles"), "isomeric_smiles": m.get("isomeric_smiles"),
            "inchi": m.get("inchi"), "inchikey": m.get("inchikey"), "tier": m.get("tier", "canon"),
            "summary": m.get("summary"), "wikidata_qid": m.get("wikidata_qid"),
            "wikipedia_title": m.get("wikipedia_title"), "pageviews_monthly": m.get("pageviews_monthly", 0),
            "structure_svg": m.get("structure_svg"), "_summary_source": "wikidata" if m.get("summary") else None,
        })
        d = m.get("descriptors") or {}
        if any(d.get(k) is not None for k in ("xlogp", "tpsa", "complexity")):
            out["descriptor"].append({
                "cid": cid, "xlogp": d.get("xlogp"), "tpsa": d.get("tpsa"),
                "h_bond_donors": d.get("h_bond_donors"), "h_bond_acceptors": d.get("h_bond_acceptors"),
                "rotatable_bonds": d.get("rotatable_bonds"), "heavy_atoms": None,
                "complexity": d.get("complexity"), "formal_charge": d.get("formal_charge"),
                "_source": "pubchem"})
        for i, s in enumerate(m.get("synonyms") or []):
            out["synonym"].append({"cid": cid, "name": s, "kind": "common",
                                   "is_primary": i == 0, "_source": "pubchem"})
        for p in m.get("properties") or []:
            out["property"].append({"cid": cid, "key": p["key"], "value_num": p.get("value_num"),
                                    "value_text": p.get("value_text"), "unit": p.get("unit"),
                                    "confidence": p["confidence"], "_source": p.get("source", "curated")})
        for t in m.get("toxicity") or []:
            out["toxicity_value"].append({"cid": cid, "endpoint": t.get("endpoint", "LD50"),
                                          "value_num": t.get("value_num"), "unit": t.get("unit", "mg/kg"),
                                          "route": t.get("route", "oral"), "species": t.get("species"),
                                          "confidence": t.get("confidence", "from_source"), "_source": "pubchem"})
        g = m.get("ghs")
        if g:
            out["ghs_classification"].append({"cid": cid, "signal_word": g.get("signal_word"),
                                              "pictograms": g.get("pictograms") or [],
                                              "h_statements": g.get("h_statements") or [], "_source": "pubchem"})
        seen_cat: set[str] = set()          # a molecule can list one slug under two kinds
        for c in m.get("categories") or []:
            categories.setdefault(c["slug"], {"slug": c["slug"], "name": c["name"], "kind": c["kind"],
                                              "_source": c.get("source", "curated")})
            if c["slug"] in seen_cat:       # e.g. bucket 'sweetener' + type 'sweetener' → one membership
                continue                    # (else a duplicate (molecule_id, category_id) breaks the upsert)
            seen_cat.add(c["slug"])
            out["molecule_category"].append({"cid": cid, "category_slug": c["slug"],
                                             "confidence": c["confidence"], "_source": c.get("source", "curated")})
        for e in m.get("edges") or []:
            if e["neighbor_cid"] in cids:                 # only intra-canon edges
                out["similarity_edge"].append({"cid": cid, "neighbor_cid": e["neighbor_cid"],
                                               "tanimoto": e["tanimoto"], "method": e.get("method", "morgan_r2_2048")})
        for h in m.get("hooks") or []:
            out["hook"].append({"cid": cid, "type": h["type"], "enabled": h.get("enabled", True),
                                "params": h.get("params") or {}, "confidence": h["confidence"],
                                "_source": "curated" if h["type"] in ("smell_card", "sweetness") else "rdkit"})
        for b in m.get("content_blocks") or []:
            out["content_block"].append({"cid": cid, "block_type": b["block_type"], "body_md": b["body_md"]})

    out["category"] = list(categories.values())
    return out


# ── A slug the catalog moved to a new compound ──────────────────────────────
def _molecule_keys(client, page: int = 1000) -> list[dict]:
    """Every existing molecule row's id, cid and slug, a page at a time (PostgREST caps a response)."""
    rows: list[dict] = []
    start = 0
    while True:
        batch = (client.table("molecule").select("id,cid,slug").order("id")
                 .range(start, start + page - 1).execute().data)
        rows.extend(batch)
        if len(batch) < page:
            return rows
        start += page


def rekey_moved_slugs(client, mol_rows: list[dict]) -> list[dict]:
    """Move an existing molecule row to its new CID when the catalog re-points its slug.

    The load upserts `molecule` on `cid`, and `slug` is unique. When the catalog corrects which
    compound a molecule is (Iodine, 2026-09-12: CID 24841, hydrogen iodide, became CID 807, I2),
    the upsert inserts the new CID under a slug an existing row still holds, and the whole load
    fails on the unique constraint. That stopped the weekly loop until a person re-keyed the row
    by hand. This does the same thing first, `update molecule set cid = <new> where id = <id> and
    cid = <old>`, so the upsert that follows refreshes the row in place and its child rows stay
    attached. A new CID that another row already holds is ambiguous (two rows would claim one
    compound), so it fails loudly instead of guessing. Returns the moves it made.
    """
    existing = _molecule_keys(client)
    by_slug = {r["slug"]: r for r in existing}
    by_cid = {r["cid"]: r for r in existing}
    moves: list[dict] = []
    for r in mol_rows:
        old = by_slug.get(r["slug"])
        if old is None or old["cid"] == r["cid"]:
            continue
        holder = by_cid.get(r["cid"])
        if holder is not None:
            raise RuntimeError(
                f"cannot re-key slug {r['slug']!r} from CID {old['cid']} to {r['cid']}: CID {r['cid']} "
                f"already belongs to molecule id {holder['id']} (slug {holder['slug']!r}); resolve by hand")
        moves.append({"id": old["id"], "slug": r["slug"], "from": old["cid"], "to": r["cid"]})
    for m in moves:
        changed = (client.table("molecule").update({"cid": m["to"]})
                   .eq("id", m["id"]).eq("cid", m["from"]).execute().data)
        if len(changed) != 1:
            raise RuntimeError(f"re-keying {m['slug']!r} changed {len(changed)} rows, expected 1")
        log.info("  re-keyed molecule %s (%s) from CID %s to %s", m["id"], m["slug"], m["from"], m["to"])
    return moves


# ── Orchestrated load (idempotent) ───────────────────────────────────────────
def load_all(client, molecules: list[dict]) -> dict[str, int]:
    """Upsert every table by natural key. Returns per-table row counts. Idempotent."""
    tables = build_db_rows(molecules)
    src_id = {r["key"]: r["id"] for r in
              client.table("source").upsert(source_rows(), on_conflict="key").execute().data}

    def sid(rows):  # resolve & strip the private _source natural key → source_id
        for r in rows:
            r["source_id"] = src_id.get(r.pop("_source", None))
        return rows

    mol_rows = tables["molecule"]
    for r in mol_rows:
        r["summary_source_id"] = src_id.get(r.pop("_summary_source", None))
    # Before the upsert: a slug the catalog re-pointed at a new CID keeps its row.
    moves = rekey_moved_slugs(client, mol_rows)
    mol_id = {r["cid"]: r["id"] for r in
              client.table("molecule").upsert(mol_rows, on_conflict="cid").execute().data}

    cat_id = {}
    if tables["category"]:
        cat_id = {r["slug"]: r["id"] for r in
                  client.table("category").upsert(sid(tables["category"]), on_conflict="slug").execute().data}

    counts = {"source": len(src_id), "molecule": len(mol_id), "category": len(cat_id),
              "rekeyed": len(moves)}

    def mol(rows):  # attach molecule_id from cid
        for r in rows:
            r["molecule_id"] = mol_id[r.pop("cid")]
        return rows

    # Parent-keyed upserts (a natural unique key exists → ON CONFLICT).
    for table, conflict in [("descriptor", "molecule_id"), ("property", "molecule_id,key"),
                            ("ghs_classification", "molecule_id"), ("hook", "molecule_id,type")]:
        rows = sid(mol(tables[table]))
        if rows:
            client.table(table).upsert(rows, on_conflict=conflict).execute()
        counts[table] = len(rows)

    # molecule_category / similarity_edge use composite PKs. Swap the natural key
    # for the surrogate id in place (a dict spread would keep the stale key).
    mc = sid(mol(tables["molecule_category"]))
    for r in mc:
        r["category_id"] = cat_id[r.pop("category_slug")]
    if mc:
        client.table("molecule_category").upsert(mc, on_conflict="molecule_id,category_id").execute()
    counts["molecule_category"] = len(mc)
    edges = mol(tables["similarity_edge"])
    for r in edges:
        r["neighbor_id"] = mol_id[r.pop("neighbor_cid")]
    if edges:
        client.table("similarity_edge").upsert(edges, on_conflict="molecule_id,neighbor_id").execute()
    counts["similarity_edge"] = len(edges)

    # Child tables without a unique key → replace per molecule (still idempotent).
    for table in ("synonym", "toxicity_value", "content_block"):
        rows = sid(mol(tables[table])) if table != "content_block" else mol(tables[table])
        for cid_mol_id in {r["molecule_id"] for r in rows}:
            client.table(table).delete().eq("molecule_id", cid_mol_id).execute()
        if rows:
            client.table(table).insert(rows).execute()
        counts[table] = len(rows)

    return counts
