"""Assemble the per-molecule record — the M1 contract that flows fetch → transform
→ load → export.

One rich, self-contained dict per molecule: identity + structure (from PubChem),
descriptors, parsed toxicity/GHS, functional-group + curated categories, curated
overlays merged, interactive hooks (`hooks.hooks_for`, plan §7.1), a build-time
2D SVG, and — attached in a second pass — top-N similarity edges. Every value is
labeled through `confidence.py`, and every source key is run through the license
firewall (`registry.assert_not_blocked`) as it is stamped on.
"""
from __future__ import annotations
import re

from .confidence import label_for
from . import names, slugs, categories, hooks, structures, similarity
from ..sources.registry import assert_not_blocked

# PubChem renamed these properties (CanonicalSMILES→ConnectivitySMILES,
# IsomericSMILES→SMILES); read the new names, fall back to the old for safety.
_ISO_KEYS = ("SMILES", "IsomericSMILES")
_CAN_KEYS = ("ConnectivitySMILES", "CanonicalSMILES")


def _src(key: str) -> str:
    """Stamp a source key, tripping the license firewall on any BLOCKED source."""
    assert_not_blocked(key)
    return key


def _first(props: dict, keys) -> "str | None":
    for k in keys:
        if props.get(k):
            return props[k]
    return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _titleize(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip().title()


# Registry/cross-reference codes that make poor display or search synonyms.
_CODE_PREFIX = re.compile(
    r"^(SCHEMBL|DTXSID|DTXCID|CHEMBL|CHEBI|UNII|EINECS|NSC|AKOS|MFCD|ZINC|BDBM|"
    r"CID|SID|HMS|HY-|CAS-|EC-|RefChem|InChI|Q\d)", re.I)


def _is_code(s: str) -> bool:
    return (":" in s or bool(_CODE_PREFIX.match(s)) or bool(re.fullmatch(r"[\d\-]+", s))
            or (" " not in s and sum(c.isdigit() for c in s) >= 4))   # e.g. "SCHEMBL1055817"


def _clean_synonyms(syns, title: "str | None") -> list[str]:
    out, seen = [], set()
    for s in ([title] + list(syns or [])):
        if not s:
            continue
        low = s.lower().strip()
        if low in seen or _is_code(s):     # skip dups + CAS/registry cross-reference codes
            continue
        seen.add(low)
        out.append(s)
        if len(out) >= 12:
            break
    return out


def _descriptors(props: dict) -> dict:
    return {
        "xlogp": props.get("XLogP"), "tpsa": props.get("TPSA"),
        "h_bond_donors": props.get("HBondDonorCount"),
        "h_bond_acceptors": props.get("HBondAcceptorCount"),
        "rotatable_bonds": props.get("RotatableBondCount"),
        "complexity": props.get("Complexity"), "formal_charge": props.get("Charge"),
        "confidence": label_for("descriptor"),
    }


def _prop(key: str, value, unit: "str | None", kind: str, source: str) -> dict:
    numeric = isinstance(value, (int, float))
    return {"key": key, "value_num": value if numeric else None,
            "value_text": None if numeric else str(value), "unit": unit,
            "confidence": label_for(kind), "source": _src(source)}


def _route(raw: "str | None") -> str:
    r = (raw or "oral").lower()
    return r if r in {"oral", "dermal", "inhalation", "iv"} else "other"


def _merge_curated(rec: dict, curated: dict) -> None:
    """Fold a curated YAML overlay into the record (hooks inputs, foods, editorial)."""
    cur: dict = {}
    hooks_c = curated.get("hooks") or {}

    sis = hooks_c.get("still_in_system") or {}
    if sis.get("half_life_hours") is not None:
        rec["half_life_hours"] = sis["half_life_hours"]
        rec["properties"].append(_prop("half_life_hours", sis["half_life_hours"], "h", "curated_fact", "curated"))
    if sis.get("serving_mg") is not None:
        cur["serving_mg"] = sis["serving_mg"]
        rec["properties"].append(_prop("serving_mg", sis["serving_mg"], "mg", "curated_fact", "curated"))

    dp = hooks_c.get("dose_poison") or {}
    if dp.get("ld50_mg_per_kg") is not None:
        row = {"endpoint": "LD50", "species": (dp.get("species") or "rat"),
               "route": _route(dp.get("route", "oral")), "value_num": dp["ld50_mg_per_kg"],
               "unit": "mg/kg", "confidence": label_for("ld50_raw")}
        key = (row["species"], row["route"], row["value_num"])
        rec["toxicity"] = [row] + [t for t in rec["toxicity"]
                                   if (t["species"], t["route"], t["value_num"]) != key]
        rec["ld50_mg_per_kg"] = dp["ld50_mg_per_kg"]

    if curated.get("capsaicinoid_ppm") is not None:
        ppm = curated["capsaicinoid_ppm"]
        cur["capsaicinoid_ppm"] = ppm
        rec["scoville_shu"] = round(ppm * 16)            # SHU ≈ ppm × 16 (plan §7)
        rec["properties"].append(_prop("scoville_shu", rec["scoville_shu"], "SHU", "scoville", "curated"))

    if curated.get("relative_sweetness") is not None:
        rs = curated["relative_sweetness"]
        cur["relative_sweetness"] = rs
        rec["relative_sweetness"] = rs
        rec["properties"].append(_prop("relative_sweetness", rs, "x sugar", "relative_sweetness", "curated"))

    if curated.get("smell_card"):
        cur["smell_card"] = curated["smell_card"]

    for food in curated.get("foods") or []:
        fslug = food.get("category")
        if fslug:
            rec["categories"].append({"slug": fslug, "name": _titleize(fslug), "kind": "food",
                                      "note": food.get("note"), "confidence": label_for("curated_fact"),
                                      "source": _src("curated")})

    if curated.get("editorial"):
        rec["content_blocks"].append({"block_type": "editorial", "body_md": curated["editorial"].strip()})

    if curated.get("tier"):
        rec["tier"] = curated["tier"]
    rec["curated"] = cur


def assemble_record(row: dict, fetched: dict, taken: set) -> dict:
    """Build one molecule record from a canon row + its fetched PubChem payload."""
    cid = row["cid"]
    props = fetched.get("props") or {}
    curated = fetched.get("curated") or {}
    syns = fetched.get("synonyms") or []

    iso = _first(props, _ISO_KEYS)
    can = _first(props, _CAN_KEYS)
    title = row.get("enwiki_title") or names.preferred_name(cid, None, syns)
    pref = names.preferred_name(cid, row.get("enwiki_title"), syns)
    slug = slugs.unique_slug(curated.get("slug") or pref or title or f"cid-{cid}", taken)

    rec = {
        "cid": cid, "slug": slug, "title": title, "preferred_name": pref,
        "tier": row.get("tier", "canon"),
        "wikidata_qid": row.get("wikidata_qid"), "wikipedia_title": row.get("enwiki_title"),
        "pageviews_monthly": int(row.get("pageviews") or 0),
        "summary": row.get("summary"),
        "summary_source": _src("wikidata") if row.get("summary") else None,
        "iupac_name": None,
        "molecular_formula": props.get("MolecularFormula"),
        "molecular_weight": _to_float(props.get("MolecularWeight")),
        "canonical_smiles": can, "isomeric_smiles": iso,
        "inchi": props.get("InChI"), "inchikey": props.get("InChIKey"),
        "synonyms": _clean_synonyms(syns, title),
        "structure_svg": structures.svg_for(iso) if iso else None,
        "descriptors": _descriptors(props),
        "toxicity": list(fetched.get("toxicity") or []),
        "ghs": fetched.get("ghs"),
        "properties": [], "categories": [], "hooks": [], "edges": [], "content_blocks": [],
        "half_life_hours": None,
        "ld50_mg_per_kg": (fetched.get("toxicity") or [{}])[0].get("value_num"),
        "relative_sweetness": None, "scoville_shu": None, "caffeine_mg": None,
    }

    if curated:
        _merge_curated(rec, curated)

    # Functional-group categories (RDKit SMARTS → computed membership).
    for fg in categories.functional_groups(iso or ""):
        rec["categories"].append({"slug": fg, "name": _titleize(fg), "kind": "functional_group",
                                  "confidence": label_for("functional_group"), "source": _src("rdkit")})

    # Hooks (plan §7.1). hooks.hooks_for reads these exact keys.
    rec["hooks"] = hooks.hooks_for({
        "cid": cid, "isomeric_smiles": iso, "half_life_hours": rec["half_life_hours"],
        "ld50": rec["toxicity"], "curated": rec.get("curated") or {},
    })

    used = {"pubchem", "rdkit"}
    if rec["summary"] or rec["wikidata_qid"]:
        used.add("wikidata")
    if rec["pageviews_monthly"]:
        used.add("wikimedia_pageviews")
    if curated:
        used.add("curated")
    rec["sources"] = sorted(_src(k) for k in used)

    rec.pop("curated", None)   # internal to assembly; its data now lives in hooks/props/categories
    return rec


def attach_edges(records: list[dict], top_n: int | None = None, floor: float | None = None) -> None:
    """Compute Morgan fingerprints once and attach each record's top-N neighbors."""
    kwargs = {}
    if top_n is not None:
        kwargs["top_n"] = top_n
    if floor is not None:
        kwargs["floor"] = floor
    smiles = [r["isomeric_smiles"] or "" for r in records]
    fps, index_map = similarity.morgan_fingerprints(smiles)
    for i, j, score in similarity.top_edges(fps, index_map, **kwargs):
        nbr = records[j]
        records[i]["edges"].append({
            "neighbor_cid": nbr["cid"], "neighbor_slug": nbr["slug"], "neighbor_title": nbr["title"],
            "tanimoto": score, "method": "morgan_r2_2048", "confidence": label_for("similarity"),
        })


def apply_filter4(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Filter-4 (plan §4): demote orphans with zero hooks AND zero edges AND no category."""
    kept, deferred = [], []
    for r in records:
        (kept if (r["hooks"] or r["edges"] or r["categories"]) else deferred).append(r)
    return kept, deferred
