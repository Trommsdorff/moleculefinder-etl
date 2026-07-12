"""Build-time roam constellation (Color System Brief §5).

Molecules are positioned in family clusters, sized by popularity, with near-neighbor
edges. Positions are baked into roam.json so the web renders a *static* SVG on first
paint — no client-side force simulation on the hot path. Deterministic (a golden-angle
sunflower spiral per cluster), so the layout is stable across runs.
"""
from __future__ import annotations
import math

# SVG viewBox units; nodes stay inside the margin.
W, H = 1000, 680
MARGIN = 56

# Cluster order around the ring (mirrors lib/families FAMILIES); uncategorized ("none")
# forms a looser central blob rather than a labeled cluster.
FAMILY_ORDER = ["stimulant", "depressant", "analgesic", "opioid", "neuro",
                "hormone", "vitamin", "nucleobase", "amino"]
GOLDEN = math.pi * (3 - math.sqrt(5))


def _radius(pageviews: int, pv_max: int) -> float:
    if pv_max <= 0:
        return 6.0
    t = math.log10(max(pageviews, 1) + 1) / math.log10(pv_max + 1)
    return round(5.0 + 8.0 * max(0.0, min(1.0, t)), 1)


def build_roam(molecules: list[dict]) -> dict:
    groups: dict[str, list[dict]] = {}
    for m in molecules:
        groups.setdefault(m.get("family") or "none", []).append(m)
    fam_keys = [f for f in FAMILY_ORDER if f in groups] + (["none"] if "none" in groups else [])
    pv_max = max((m.get("pageviews_monthly") or 0) for m in molecules) if molecules else 0

    cx, cy = W / 2, H / 2
    ring_rx, ring_ry = (W / 2 - MARGIN - 70), (H / 2 - MARGIN - 40)
    n_ring = max(1, len([f for f in fam_keys if f != "none"]))

    nodes: list[dict] = []
    pos: dict[str, tuple[float, float]] = {}
    ring_i = 0
    for fam in fam_keys:
        members = sorted(groups[fam], key=lambda m: -(m.get("pageviews_monthly") or 0))
        if fam == "none":
            fcx, fcy = cx, cy
            spread = min(ring_rx, ring_ry) * 0.85   # loose central field, low overlap
        else:
            ang = (2 * math.pi * ring_i / n_ring) - math.pi / 2
            fcx, fcy = cx + ring_rx * math.cos(ang), cy + ring_ry * math.sin(ang)
            spread = 22 + 13 * math.sqrt(len(members))
            ring_i += 1
        for k, m in enumerate(members):
            r = spread * math.sqrt((k + 0.5) / max(1, len(members)))
            a = k * GOLDEN
            x = max(MARGIN, min(W - MARGIN, fcx + r * math.cos(a)))
            y = max(MARGIN, min(H - MARGIN, fcy + r * math.sin(a)))
            pos[m["slug"]] = (x, y)
            nodes.append({
                "slug": m["slug"], "title": m["title"], "family": m.get("family") or None,
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
                              "family": m.get("family") or None})

    legend = [{"key": f, "count": len(groups[f])} for f in fam_keys if f != "none"]
    return {"width": W, "height": H, "count": len(nodes),
            "nodes": nodes, "edges": edges, "families": legend}
