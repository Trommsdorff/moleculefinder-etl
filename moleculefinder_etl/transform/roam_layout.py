"""Build-time roam constellation (Color System Brief §5).

Molecules are positioned in family clusters, sized by popularity, with near-neighbor
edges. Positions are baked into roam.json so the web renders a *static* SVG on first
paint — no client-side force simulation on the hot path. Deterministic (a golden-angle
sunflower spiral per cluster + a fixed-order separation pass), so the layout is stable
across runs.
"""
from __future__ import annotations
import itertools
import math

from . import buckets

# SVG viewBox units; nodes stay inside the margin.
W, H = 1000, 760
MARGIN = 56
CLUSTER_PAD = 4      # minimum gap between cluster bounding circles
SEPARATE_MAX = 200   # separation passes; converges in ~20, capped for safety

# Cluster order around the ring (mirrors lib/buckets BUCKET_ORDER); uncategorized ("none")
# forms a looser central blob rather than a labeled cluster.
BUCKET_ORDER = buckets.BUCKET_ORDER
GOLDEN = math.pi * (3 - math.sqrt(5))


def _radius(pageviews: int, pv_max: int) -> float:
    if pv_max <= 0:
        return 6.0
    t = math.log10(max(pageviews, 1) + 1) / math.log10(pv_max + 1)
    return round(5.0 + 8.0 * max(0.0, min(1.0, t)), 1)


def _cluster_spread(n_members: int) -> float:
    return 22 + 12 * math.sqrt(n_members)


def _fit_centers(fam_keys: list[str], spreads: dict[str, float]) -> dict[str, list[float]]:
    """Seed cluster centers on a ring, then keep every cluster fully on-canvas and
    apart from its neighbors. Without this, a big cluster seeded near the edge spills
    past the margin and its nodes get clamped into a flat band along the border.
    Fixed iteration order keeps it deterministic."""
    cx, cy = W / 2, H / 2
    ring_rx, ring_ry = (W / 2 - MARGIN - 70), (H / 2 - MARGIN - 40)
    ring = [f for f in fam_keys if f != "none"]
    centers: dict[str, list[float]] = {}
    for i, fam in enumerate(ring):
        ang = (2 * math.pi * i / max(1, len(ring))) - math.pi / 2
        centers[fam] = [cx + ring_rx * math.cos(ang), cy + ring_ry * math.sin(ang)]

    def clamp(fam: str) -> None:
        s = min(spreads[fam], min(W, H) / 2 - MARGIN)
        centers[fam][0] = min(max(centers[fam][0], MARGIN + s), W - MARGIN - s)
        centers[fam][1] = min(max(centers[fam][1], MARGIN + s), H - MARGIN - s)

    for fam in ring:
        clamp(fam)
    for _ in range(SEPARATE_MAX):
        moved = False
        for f1, f2 in itertools.combinations(ring, 2):
            (x1, y1), (x2, y2) = centers[f1], centers[f2]
            need = spreads[f1] + spreads[f2] + CLUSTER_PAD
            d = math.hypot(x1 - x2, y1 - y2)
            if d < need - 0.01:
                ux, uy = ((x1 - x2) / d, (y1 - y2) / d) if d > 1e-6 else (1.0, 0.0)
                push = (need - d) / 2
                centers[f1][0] += ux * push
                centers[f1][1] += uy * push
                centers[f2][0] -= ux * push
                centers[f2][1] -= uy * push
                clamp(f1)
                clamp(f2)
                moved = True
        if not moved:
            break
    if "none" in fam_keys:
        centers["none"] = [cx, cy]
    return centers


def build_roam(molecules: list[dict]) -> dict:
    groups: dict[str, list[dict]] = {}
    for m in molecules:
        groups.setdefault(m.get("scope_bucket") or "none", []).append(m)
    fam_keys = [b for b in BUCKET_ORDER if b in groups] + (["none"] if "none" in groups else [])
    pv_max = max((m.get("pageviews_monthly") or 0) for m in molecules) if molecules else 0

    ring_rx, ring_ry = (W / 2 - MARGIN - 70), (H / 2 - MARGIN - 40)
    spreads = {
        fam: (min(ring_rx, ring_ry) * 0.85 if fam == "none" else _cluster_spread(len(groups[fam])))
        for fam in fam_keys
    }
    centers = _fit_centers(fam_keys, spreads)

    nodes: list[dict] = []
    pos: dict[str, tuple[float, float]] = {}
    for fam in fam_keys:
        members = sorted(groups[fam], key=lambda m: -(m.get("pageviews_monthly") or 0))
        (fcx, fcy), spread = centers[fam], spreads[fam]
        for k, m in enumerate(members):
            r = spread * math.sqrt((k + 0.5) / max(1, len(members)))
            a = k * GOLDEN
            x = max(MARGIN, min(W - MARGIN, fcx + r * math.cos(a)))
            y = max(MARGIN, min(H - MARGIN, fcy + r * math.sin(a)))
            pos[m["slug"]] = (x, y)
            nodes.append({
                "slug": m["slug"], "title": m["title"],
                "bucket": m.get("scope_bucket") or None, "family": m.get("family") or None,
                "x": round(x, 1), "y": round(y, 1),
                "r": _radius(m.get("pageviews_monthly") or 0, pv_max),
            })

    # Near-neighbor edges: top-2 per node, undirected + deduped, colored by source family.
    seen: set[tuple[str, str]] = set()
    edges: list[dict] = []
    for m in molecules:
        s = m["slug"]
        for e in (m.get("edges") or [])[:2]:
            t = e.get("neighbor_slug")
            if t in pos and t != s:
                key = tuple(sorted((s, t)))
                if key in seen:
                    continue
                seen.add(key)
                (ax, ay), (bx, by) = pos[s], pos[t]
                edges.append({"x1": round(ax, 1), "y1": round(ay, 1),
                              "x2": round(bx, 1), "y2": round(by, 1),
                              "bucket": m.get("scope_bucket") or None,
                              "family": m.get("family") or None})

    legend = [{"key": f, "count": len(groups[f])} for f in fam_keys if f != "none"]
    # `groups` is the bucket legend (primary color dimension); `families` kept empty for
    # back-compat with the web's older-snapshot fallback.
    return {"width": W, "height": H, "count": len(nodes),
            "nodes": nodes, "edges": edges, "groups": legend, "families": []}
