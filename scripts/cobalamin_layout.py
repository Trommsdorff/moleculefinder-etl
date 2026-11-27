"""Lay out the four cobalamins once, by hand, and print the display SMILES (CXSMILES) for structure_display.yaml.

    ./.venv/bin/python3 scripts/cobalamin_layout.py            # prints the four `smiles:` lines
    ./.venv/bin/python3 scripts/cobalamin_layout.py --svg DIR  # also writes each drawing to DIR/<slug>.svg

The cobalamins pass (2026-11-26, brief ../COBALAMINS-PROMPT.md). Not run by the build: its output is the four
`smiles:` values in seeds/structure_display.yaml `metal_bonds`, which ARE the layout from then on (the key covers the
whole string, so no machine lays them out again). Kept so the layout can be read and made again.

Cowork's rulings this follows:
1. One skeleton, one hand layout, four drawings. The skeleton (the corrin, its side chains, the nucleotide loop and the
   cobalt) is laid out ONCE, on hydroxocobalamin's record, and every drawing takes that skeleton's coordinates atom for
   atom; only the group on top of the cobalt differs, and it sits in the same place in all four.
2. The cobalt's six bonds: the four corrin nitrogens, the benzimidazole's free ring nitrogen (not the one bonded to the
   ribose) and the top group's first atom (the cyanide's CARBON, the hydroxide's oxygen, the methyl carbon). A partner
   PubChem writes with a negative charge gets a plain bond (the charges pair off on the cobalt); a neutral one a dative
   arrow.
3. Stereo: hydroxocobalamin's record is the reference (every carbon centre specified, the ribose's anomeric carbon
   included). Each drawing is built from the reference skeleton itself, so it carries the reference's centres; the
   build's check (structures.metal_bonds_problems) proves each record's own centres agree.
4. Each record's OWN double-bond placement: the corrin's double bonds and its N- are set from the record's own SMILES
   (cyanocobalamin's record writes them in other, equivalent places; nothing is moved to match the reference).

The layout (units: RDKit's 1.5 per bond):
- The corrin: the cobalt at the origin; the four nitrogens on a circle of radius 2.0 (four equal Co-N bonds); each
  five-membered ring a regular pentagon pointing its nitrogen at the cobalt; the three meso carbons on the bisectors,
  1.5 from their neighbours; the rings spaced so the direct ring A-ring D bond is 1.5 long and the three meso gaps are
  equal (the meso angles come out near 123 degrees).
- The bond to the benzimidazole runs due east from the cobalt and crosses the ring's edge once, at the C14-C15 bond
  (the one crossing every flat drawing of a cobalamin has); the C15 methyl sits above it.
- The top group points due west, into the ring's cavity: its first atom 1.4 from the cobalt, a cyanide's nitrogen 2.5.
- The nucleotide loop: the benzimidazole's free nitrogen 7.6 east of the cobalt, its ring and the ribose drawn as
  regular pentagons, the chain from C17 to the ribose's 3'-oxygen on an arc above.
- The substituents of every corrin atom pinned on its ring's outside (C1's methyl turned 12 degrees towards ring A, the
  pair on C2 20 degrees away from C1, so neither meets the hydrogen RDKit draws on C19); RDKit places the rest
  (Compute2DCoords with the above locked), then a short relaxation (numpy: bond and angle springs, soft repulsion)
  moves only the side chains and the linker chain.
Every coordinate is written to three decimals.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from rdkit import Chem
from rdkit.Chem import rdDepictor
from rdkit.Geometry import Point2D, Point3D

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "data" / "snapshots" / "molecules"
SLUGS = ("cyanocobalamin", "vitamin-b12", "hydroxocobalamin", "methylcobalamin")
REFERENCE = "hydroxocobalamin"
B = 1.5                       # RDKit's bond length
RN = 2.0                      # Co-N
ROT = 10.7                    # the C15 meso carbon's bearing from the cobalt (degrees); the long bond runs at 0
TOP_DIR, TOP1, TOP2 = 180.0, 1.4, 2.5
N3_AT = (7.6, 0.0)
ARC = 1.15                    # the linker arc's length over a straight zigzag
TURN = {"C1": 12.0, "C2": 20.0}
LINKER = ("b", "c", "Nam", "d", "e", "Oe", "P", "O3")   # relaxed; every other placed atom stays where it is put


def record(slug: str) -> Chem.Mol:
    return Chem.MolFromSmiles(json.loads((SNAP / f"{slug}.json").read_text())["isomeric_smiles"])


def roles(m: Chem.Mol) -> dict:
    """The cobalt, the four corrin nitrogens, the benzimidazole's free nitrogen and the top group's first atom, in a
    record (the cobalt and the top group are separate pieces there) or a display mol."""
    co = next(a.GetIdx() for a in m.GetAtoms() if a.GetSymbol() == "Co")
    ri = m.GetRingInfo()
    corrin_n = [a.GetIdx() for a in m.GetAtoms() if a.GetSymbol() == "N" and not a.GetIsAromatic()
                and any(len(r) == 5 and a.GetIdx() in r for r in ri.AtomRings())
                and not any(n.GetSymbol() == "C" and n.GetDegree() == 3 and any(
                    x.GetSymbol() == "O" and m.GetBondBetweenAtoms(n.GetIdx(), x.GetIdx()).GetBondTypeAsDouble() == 2
                    for x in n.GetNeighbors()) for n in a.GetNeighbors())]
    bzm = [a.GetIdx() for a in m.GetAtoms() if a.GetSymbol() == "N" and a.GetIsAromatic()
           and not any(n.GetSymbol() == "C" and not n.GetIsAromatic() for n in a.GetNeighbors())]
    main = max(Chem.GetMolFrags(Chem.RWMol(m)), key=len)
    top = [a.GetIdx() for a in m.GetAtoms() if a.GetFormalCharge() < 0 and a.GetIdx() not in main]
    assert len(corrin_n) == 4 and len(bzm) == 1 and len(top) == 1, (corrin_n, bzm, top)
    return {"co": co, "corrin_n": corrin_n, "bzm": bzm[0], "top": top[0]}


def bonded(rec: Chem.Mol) -> tuple[Chem.Mol, dict]:
    """The record with the cobalt's six bonds drawn in (ruling 2), its own bond orders and charges otherwise."""
    info = roles(rec)
    rw = Chem.RWMol(rec)
    co = rw.GetAtomWithIdx(info["co"])
    for n in [*info["corrin_n"], info["bzm"], info["top"]]:
        a = rw.GetAtomWithIdx(n)
        if a.GetFormalCharge() < 0:
            rw.AddBond(n, info["co"], Chem.BondType.SINGLE)
            a.SetFormalCharge(a.GetFormalCharge() + 1)
            co.SetFormalCharge(co.GetFormalCharge() - 1)
        else:
            rw.AddBond(n, info["co"], Chem.BondType.DATIVE)
    m = rw.GetMol()
    Chem.SanitizeMol(m)
    return m, info


# ── the corrin template ───────────────────────────────────────────────────────────────────────────────────────────
def corrin(m: Chem.Mol, info: dict) -> tuple[dict, list[int]]:
    """Ring letter -> [N, C alpha towards the previous ring, C beta, C beta, C alpha towards the next ring], A to D
    counterclockwise; and the three meso carbons (C5, C10, C15). Ring D is the one whose C17 carries the chain to the
    nucleotide; ring A is bonded to ring D directly."""
    ri = m.GetRingInfo()
    rings5 = {n: next(r for r in ri.AtomRings() if len(r) == 5 and n in r and info["co"] not in r)
              for n in info["corrin_n"]}
    ring_atoms = set().union(*map(set, rings5.values()))
    meso = [a.GetIdx() for a in m.GetAtoms() if a.GetIdx() not in ring_atoms and a.GetSymbol() == "C"
            and sum(1 for nb in a.GetNeighbors() if nb.GetIdx() in ring_atoms) == 2]
    amide_n = next(a.GetIdx() for a in m.GetAtoms() if a.GetSymbol() == "N" and not a.IsInRing()
                   and a.GetDegree() == 2)
    dm = Chem.GetDistanceMatrix(m)
    c17 = min(sorted(ring_atoms), key=lambda i: dm[amide_n][i])

    def ring_of(i):
        return next(n for n, r in rings5.items() if i in r)

    def alphas(n):
        return [x.GetIdx() for x in m.GetAtomWithIdx(n).GetNeighbors() if x.GetIdx() in rings5[n]]

    d_n = ring_of(c17)
    c19 = c1 = None
    for c in alphas(d_n):
        for x in m.GetAtomWithIdx(c).GetNeighbors():
            if x.GetIdx() in ring_atoms and ring_of(x.GetIdx()) != d_n:
                c19, c1 = c, x.GetIdx()

    def listed(n, ca_prev):
        r = rings5[n]
        ca_next = next(c for c in alphas(n) if c != ca_prev)

        def beta(ca):
            return next(x.GetIdx() for x in m.GetAtomWithIdx(ca).GetNeighbors() if x.GetIdx() in r and x.GetIdx() != n)
        return [n, ca_prev, beta(ca_prev), beta(ca_next), ca_next]

    rings = {"A": listed(ring_of(c1), c1)}
    mesos, prev = [], rings["A"][4]
    for letter in "BCD":
        ms = next(x.GetIdx() for x in m.GetAtomWithIdx(prev).GetNeighbors() if x.GetIdx() in meso)
        mesos.append(ms)
        ca = next(x.GetIdx() for x in m.GetAtomWithIdx(ms).GetNeighbors() if x.GetIdx() != prev
                  and x.GetIdx() in ring_atoms)
        rings[letter] = listed(ring_of(ca), ca)
        prev = rings[letter][4]
    assert rings["D"][4] == c19 and rings["D"][2] == c17
    return rings, mesos


def polar(r: float, deg: float) -> tuple[float, float]:
    return (r * math.cos(math.radians(deg)), r * math.sin(math.radians(deg)))


def template(m: Chem.Mol, info: dict) -> tuple[dict, dict, list[int]]:
    rings, mesos = corrin(m, info)
    r5 = B / (2 * math.sin(math.radians(36)))
    cax, cay = RN + r5 + r5 * math.cos(math.radians(108)), r5 * math.sin(math.radians(108))
    rho, off = math.hypot(cax, cay), math.degrees(math.atan2(cay, cax))
    gap_direct = 2 * math.degrees(math.asin(B / 2 / rho)) + 2 * off
    gap = (360 - gap_direct) / 3
    th = {"D": ROT + gap / 2}
    th["A"] = th["D"] + gap_direct
    th["B"] = th["A"] + gap
    th["C"] = th["B"] + gap
    xy = {info["co"]: (0.0, 0.0)}
    for letter, (n, ca_p, cb_p, cb_n, ca_n) in rings.items():
        t = th[letter]
        c = polar(RN + r5, t)
        for atom, va in ((n, t + 180), (ca_p, t - 108), (cb_p, t - 36), (cb_n, t + 36), (ca_n, t + 108)):
            xy[atom] = (c[0] + r5 * math.cos(math.radians(va)), c[1] + r5 * math.sin(math.radians(va)))
    for ms in mesos:
        (x1, y1), (x2, y2) = (xy[x.GetIdx()] for x in m.GetAtomWithIdx(ms).GetNeighbors() if x.GetIdx() in xy)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        h = math.sqrt(B * B - (math.hypot(x2 - x1, y2 - y1) / 2) ** 2)
        k = math.hypot(mx, my)
        xy[ms] = (mx + h * mx / k, my + h * my / k)
    return xy, rings, mesos


# ── the nucleotide loop ───────────────────────────────────────────────────────────────────────────────────────────
LOOP = ("C17", "a", "b", "c", "Nam", "d", "e", "Oe", "P", "O3", "C3'", "C2'", "C1'", "N1", "C2", "N3")


def loop(m: Chem.Mol, info: dict, rings: dict, xy: dict) -> tuple[dict, dict]:
    rw = Chem.RWMol(m)
    for x in [a.GetIdx() for a in rw.GetAtomWithIdx(info["co"]).GetNeighbors()]:
        rw.RemoveBond(info["co"], x)
    path = list(Chem.GetShortestPath(rw.GetMol(), rings["D"][2], info["bzm"]))
    role = dict(zip(LOOP, path, strict=True))
    out = {}
    r5 = B / (2 * math.sin(math.radians(36)))
    x3, y3 = N3_AT
    ln = math.hypot(x3, y3)
    ux, uy = x3 / ln, y3 / ln
    cx, cy = x3 + r5 * ux, y3 + r5 * uy
    base = math.degrees(math.atan2(-uy, -ux))
    c2, n1 = role["C2"], role["N1"]
    c3a = next(a.GetIdx() for a in m.GetAtomWithIdx(role["N3"]).GetNeighbors() if a.GetIdx() not in (c2, info["co"]))
    c7a = next(a.GetIdx() for a in m.GetAtomWithIdx(n1).GetNeighbors() if a.GetIdx() not in (c2, role["C1'"]))
    for atom, k in ((role["N3"], 0), (c2, -1), (n1, -2), (c7a, -3), (c3a, -4)):
        out[atom] = polar_about((cx, cy), r5, base + 72 * k)
    nx, ny = out[n1]
    vx, vy = (nx - cx) / r5, (ny - cy) / r5
    c1p = (nx + B * vx, ny + B * vy)
    rc = (c1p[0] + r5 * vx, c1p[1] + r5 * vy)
    b1 = math.degrees(math.atan2(-vy, -vx))
    c2p, c3p = role["C2'"], role["C3'"]
    o4 = next(a.GetIdx() for a in m.GetAtomWithIdx(role["C1'"]).GetNeighbors() if a.GetSymbol() == "O")
    c4p = next(a.GetIdx() for a in m.GetAtomWithIdx(c3p).GetNeighbors()
               if a.GetIdx() not in (c2p, role["O3"]) and a.GetSymbol() == "C")
    for atom, k in ((role["C1'"], 0), (c2p, -1), (c3p, -2), (c4p, -3), (o4, -4)):
        out[atom] = polar_about(rc, r5, b1 + 72 * k)
    x, y = out[c3p]
    wl = math.dist((x, y), rc)
    out[role["O3"]] = (x + B * (x - rc[0]) / wl, y + B * (y - rc[1]) / wl)
    # the chain from C17 to the 3'-oxygen, a zigzag on a circular arc above the chord
    (sx, sy), (ex, ey) = xy[role["C17"]], out[role["O3"]]
    chain = [role[k] for k in ("a", "b", "c", "Nam", "d", "e", "Oe", "P")]
    steps = len(chain) + 1
    dx, dy = ex - sx, ey - sy
    chord = math.hypot(dx, dy)
    px, py = -dy / chord, dx / chord
    target = steps * B * math.cos(math.radians(30)) * ARC
    lo, hi = 0.0, 2 * chord
    for _ in range(60):
        h = (lo + hi) / 2
        rad = (h * h + (chord / 2) ** 2) / (2 * h)
        theta = 2 * math.asin(min(1.0, chord / 2 / rad))
        if h > rad:
            theta = 2 * math.pi - theta
        lo, hi = (h, hi) if rad * theta < target else (lo, h)
    rad = (h * h + (chord / 2) ** 2) / (2 * h)
    mx, my = (sx + ex) / 2, (sy + ey) / 2
    ccx, ccy = mx + px * (h - rad), my + py * (h - rad)
    a0, a1 = math.atan2(sy - ccy, sx - ccx), math.atan2(ey - ccy, ex - ccx)
    ab = math.atan2(my + py * h - ccy, mx + px * h - ccx)
    ccw = (ab - a0) % (2 * math.pi) <= (a1 - a0) % (2 * math.pi)
    span = (a1 - a0) % (2 * math.pi) if ccw else -((a0 - a1) % (2 * math.pi))
    for i, atom in enumerate(chain, start=1):
        t = a0 + span * i / steps
        rr = rad + 0.375 * (1 if i % 2 else -1)
        out[atom] = (ccx + rr * math.cos(t), ccy + rr * math.sin(t))
    return out, role


def polar_about(c, r, deg):
    return (c[0] + r * math.cos(math.radians(deg)), c[1] + r * math.sin(math.radians(deg)))


def outside(m, xy, atom, subs, spread=38.0, first=None, turn=0.0) -> dict:
    """Positions for the exocyclic substituents `subs` (one or two) of `atom`, about the bisector of its placed
    neighbours' outside angle, turned by `turn` degrees."""
    ax, ay = xy[atom]
    nbs = [x.GetIdx() for x in m.GetAtomWithIdx(atom).GetNeighbors() if x.GetIdx() in xy and x.GetIdx() not in subs]
    vx = sum((ax - xy[n][0]) / math.dist(xy[n], (ax, ay)) for n in nbs)
    vy = sum((ay - xy[n][1]) / math.dist(xy[n], (ax, ay)) for n in nbs)
    t = math.degrees(math.atan2(vy, vx)) + turn
    if len(subs) == 1:
        return {subs[0]: polar_about((ax, ay), B, t)}
    a, b = subs if first is None else (first, next(s for s in subs if s != first))
    return {a: polar_about((ax, ay), B, t - spread), b: polar_about((ax, ay), B, t + spread)}


def relax(m, xy, movable, skip, iters=3000, step=0.02, d0=2.3, d0_label=2.6, w13=1.5) -> dict:
    """Gradient descent on the movable atoms only: bond springs (1.5), 1-3 springs (120 degrees; 90 at a four-
    connected atom), soft repulsion between atoms three or more bonds apart and between an atom and a bond's midpoint.
    The bonds to `skip` (the cobalt) take no part."""
    n = m.GetNumAtoms()
    pos = np.array([xy[i] for i in range(n)], float)
    mov = np.zeros(n, bool)
    mov[list(movable)] = True
    bonds = [(b.GetBeginAtomIdx(), b.GetEndAtomIdx()) for b in m.GetBonds()
             if b.GetBeginAtomIdx() not in skip and b.GetEndAtomIdx() not in skip]
    nb = {i: set() for i in range(n)}
    for i, j in bonds:
        nb[i].add(j)
        nb[j].add(i)
    tri = [(ns[x], ns[y], B * math.sqrt(3) if len(ns) <= 3 else B * math.sqrt(2))
           for c in range(n) for ns in [sorted(nb[c])] for x in range(len(ns)) for y in range(x + 1, len(ns))]
    dmx = Chem.GetDistanceMatrix(m)
    lab = np.array([m.GetAtomWithIdx(i).GetSymbol() != "C" for i in range(n)])
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n) if dmx[i][j] >= 3 and (mov[i] or mov[j])
             and i not in skip and j not in skip]
    pi, pj = np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs])
    pd0 = np.where(lab[pi] | lab[pj], d0_label, d0)
    bi, bj = np.array([b[0] for b in bonds]), np.array([b[1] for b in bonds])
    ti, tj, tt = (np.array([t[k] for t in tri]) for k in range(3))
    am = [(k, i, j) for k in range(n) for (i, j) in bonds if k not in (i, j) and k not in skip
          and (mov[k] or mov[i] or mov[j]) and min(dmx[k][i], dmx[k][j]) >= 2]
    ak, ai, aj = (np.array([a[x] for a in am]) for x in range(3))
    for _ in range(iters):
        grad = np.zeros_like(pos)
        for (u, v, target, w) in ((bi, bj, B, 2.0), (ti, tj, tt, w13)):
            vec = pos[u] - pos[v]
            ln = np.linalg.norm(vec, axis=1) + 1e-9
            f = (w * (ln - target) / ln)[:, None] * vec
            np.add.at(grad, u, f)
            np.add.at(grad, v, -f)
        vec = pos[pi] - pos[pj]
        ln = np.linalg.norm(vec, axis=1) + 1e-9
        f = (-2 * np.clip(pd0 - ln, 0, None) / ln)[:, None] * vec
        np.add.at(grad, pi, f)
        np.add.at(grad, pj, -f)
        vec = pos[ak] - (pos[ai] + pos[aj]) / 2
        ln = np.linalg.norm(vec, axis=1) + 1e-9
        f = (-2 * np.clip(1.4 - ln, 0, None) / ln)[:, None] * vec
        np.add.at(grad, ak, f)
        np.add.at(grad, ai, -f / 2)
        np.add.at(grad, aj, -f / 2)
        grad[~mov] = 0
        pos -= step * grad
    return {i: (float(pos[i][0]), float(pos[i][1])) for i in range(n)}


def reference_layout() -> tuple[Chem.Mol, dict]:
    """Hydroxocobalamin with its cobalt bonded, laid out; returns (mol with a 2D conformer, roles)."""
    m, info = bonded(record(REFERENCE))
    xy, rings, mesos = template(m, info)
    t = info["top"]
    xy[t] = polar(TOP1, TOP_DIR)
    lp, role = loop(m, info, rings, xy)
    xy.update(lp)
    ring_set = {a for r in rings.values() for a in r} | set(mesos)
    for a in sorted(ring_set):
        subs = [x.GetIdx() for x in m.GetAtomWithIdx(a).GetNeighbors()
                if x.GetIdx() not in ring_set and x.GetIdx() != info["co"]]
        if not subs:
            continue
        if a == role["C17"]:       # the chain on the side nearer the arc, the methyl on the other
            here = {k: v for k, v in xy.items() if k != role["a"]}
            opts = [outside(m, here, a, subs, first=f) for f in subs]
            xy.update(min(opts, key=lambda o: math.dist(o[role["a"]], xy[role["b"]])))
            continue
        turn = TURN.get({rings["A"][1]: "C1", rings["A"][2]: "C2"}.get(a), 0.0)
        xy.update({k: v for k, v in outside(m, xy, a, subs, turn=turn).items() if k not in xy})
    p = role["P"]
    xy.update(outside(m, xy, p, [x.GetIdx() for x in m.GetAtomWithIdx(p).GetNeighbors() if x.GetIdx() not in xy],
                      spread=45.0))
    fixed = set(xy) - {role[k] for k in LINKER}
    # RDKit places the rest with everything above locked (on a copy without the cobalt's bonds)
    rw = Chem.RWMol(m)
    for x in [a.GetIdx() for a in rw.GetAtomWithIdx(info["co"]).GetNeighbors()]:
        rw.RemoveBond(info["co"], x)
    flat = rw.GetMol()
    flat.UpdatePropertyCache(False)
    rdDepictor.Compute2DCoords(flat, coordMap={i: Point2D(*v) for i, v in xy.items()}, canonOrient=False)
    conf = flat.GetConformer()
    full = {i: (conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y) for i in range(m.GetNumAtoms())}
    full.update(xy)
    full = relax(m, full, [i for i in range(m.GetNumAtoms()) if i not in fixed], skip={info["co"]})
    return with_coords(m, full), info


def with_coords(m: Chem.Mol, xy: dict) -> Chem.Mol:
    out = Chem.Mol(m)
    out.RemoveAllConformers()
    conf = Chem.Conformer(out.GetNumAtoms())
    for i, (x, y) in xy.items():
        conf.SetAtomPosition(i, Point3D(round(x, 3), round(y, 3), 0.0))
    conf.Set3D(False)
    out.AddConformer(conf, assignId=True)
    return out


def _flat(m: Chem.Mol, drop: set[int]) -> Chem.Mol:
    """A copy with `drop` removed and every bond single, every charge zero, hydrogens frozen: the skeleton as a graph,
    for matching two records whose bond orders sit in different (equivalent) places."""
    rw = Chem.RWMol(m)
    for a in rw.GetAtoms():
        a.SetNumExplicitHs(a.GetTotalNumHs())
        a.SetNoImplicit(True)
        a.SetFormalCharge(0)
        a.SetIsAromatic(False)
    for b in rw.GetBonds():
        b.SetBondType(Chem.BondType.SINGLE)
        b.SetIsAromatic(False)
    for i in sorted(drop, reverse=True):
        rw.RemoveAtom(i)
    out = rw.GetMol()
    out.UpdatePropertyCache(False)
    Chem.FastFindRings(out)
    return out


def top_group(m: Chem.Mol, info: dict) -> list[int]:
    """The top group's atoms: its first atom and everything beyond it away from the cobalt (heavy atoms)."""
    seen, todo = {info["top"]}, [info["top"]]
    while todo:
        for x in m.GetAtomWithIdx(todo.pop()).GetNeighbors():
            if x.GetIdx() not in seen and x.GetIdx() != info["co"]:
                seen.add(x.GetIdx())
                todo.append(x.GetIdx())
    return sorted(seen)


def drawing_for(slug: str, ref: Chem.Mol, ref_info: dict) -> Chem.Mol:
    """The reference skeleton (its atoms, centres and coordinates) with this record's own bond orders and charges on
    every skeleton bond and atom, and this record's top group in the reference top group's place."""
    own, info = bonded(record(slug))
    ref_top, own_top = top_group(ref, ref_info), top_group(own, info)
    rf, of = _flat(ref, set(ref_top)), _flat(own, set(own_top))
    rkeep = [i for i in range(ref.GetNumAtoms()) if i not in ref_top]
    okeep = [i for i in range(own.GetNumAtoms()) if i not in own_top]

    def agreement(match):
        score = 0
        for qi, ti in enumerate(match):
            score += own.GetAtomWithIdx(okeep[qi]).GetFormalCharge() == ref.GetAtomWithIdx(rkeep[ti]).GetFormalCharge()
        for b in of.GetBonds():
            i, j = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
            ob = own.GetBondBetweenAtoms(okeep[i], okeep[j])
            rb = ref.GetBondBetweenAtoms(rkeep[match[i]], rkeep[match[j]])
            score += ob.GetBondType() == rb.GetBondType()
        return score

    matches = rf.GetSubstructMatches(of, uniquify=False, maxMatches=1000)
    assert matches and all(len(x) == of.GetNumAtoms() == rf.GetNumAtoms() for x in matches), slug
    best = max(matches, key=agreement)
    to_ref = {okeep[q]: rkeep[t] for q, t in enumerate(best)}            # own atom -> reference atom
    rw = Chem.RWMol(ref)
    # this record's own bond orders and charges on the skeleton
    for o, r in to_ref.items():
        rw.GetAtomWithIdx(r).SetFormalCharge(own.GetAtomWithIdx(o).GetFormalCharge())
        rw.GetAtomWithIdx(r).SetNumExplicitHs(own.GetAtomWithIdx(o).GetNumExplicitHs())
        rw.GetAtomWithIdx(r).SetNoImplicit(own.GetAtomWithIdx(o).GetNoImplicit())
    for b in own.GetBonds():
        i, j = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
        if i in to_ref and j in to_ref:
            rb = rw.GetBondBetweenAtoms(to_ref[i], to_ref[j])
            rb.SetBondType(b.GetBondType())
            if b.GetBondType() == Chem.BondType.DATIVE and rb.GetBeginAtomIdx() != to_ref[i]:
                rw.RemoveBond(to_ref[i], to_ref[j])
                rw.AddBond(to_ref[i], to_ref[j], Chem.BondType.DATIVE)
            rb = rw.GetBondBetweenAtoms(to_ref[i], to_ref[j])
            rb.SetStereo(Chem.BondStereo.STEREONONE)
    # swap the top group: remove the reference's, add this record's at the same place
    conf = rw.GetConformer()
    first = conf.GetAtomPosition(ref_info["top"])
    for i in sorted(ref_top, reverse=True):
        rw.RemoveAtom(i)
    co = next(a.GetIdx() for a in rw.GetAtoms() if a.GetSymbol() == "Co")
    new = {}
    for o in own_top:
        a = own.GetAtomWithIdx(o)
        na = Chem.Atom(a.GetAtomicNum())
        na.SetFormalCharge(a.GetFormalCharge())
        na.SetNumExplicitHs(a.GetTotalNumHs())
        na.SetNoImplicit(True)
        new[o] = rw.AddAtom(na)
    for b in own.GetBonds():
        i, j = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
        if i in new and j in new:
            rw.AddBond(new[i], new[j], b.GetBondType())
    tb = own.GetBondBetweenAtoms(info["top"], info["co"])
    rw.AddBond(new[info["top"]], co, tb.GetBondType())
    conf = rw.GetConformer()
    ux, uy = first.x / TOP1, first.y / TOP1
    for o, i in new.items():
        dist = TOP1 if o == info["top"] else TOP2
        conf.SetAtomPosition(i, Point3D(round(ux * dist, 3), round(uy * dist, 3), 0.0))
    out = rw.GetMol()
    Chem.SanitizeMol(out)
    Chem.AssignStereochemistry(out, cleanIt=True, force=True)
    return out


def cxsmiles(m: Chem.Mol) -> str:
    """The SMILES (Kekule form, dative bonds as ->) with the 2D coordinates appended in output order, three decimals.
    (RDKit's own CXSMILES writer moves dative bonds into a separate field, so it is not used.)"""
    k = Chem.Mol(m)
    Chem.Kekulize(k, clearAromaticFlags=True)
    smi = Chem.MolToSmiles(k, kekuleSmiles=True)
    order = list(map(int, k.GetProp("_smilesAtomOutputOrder").strip("[],").split(",")))
    conf = k.GetConformer()

    def f(v):
        s = f"{v:.3f}".rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s
    coords = ";".join(f"{f(conf.GetAtomPosition(i).x)},{f(conf.GetAtomPosition(i).y)}," for i in order)
    return f"{smi} |({coords})|"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg", type=Path)
    args = ap.parse_args()
    ref, ref_info = reference_layout()
    for slug in SLUGS:
        m = drawing_for(slug, ref, ref_info)
        smi = cxsmiles(m)
        back = Chem.MolFromSmiles(smi)
        assert Chem.MolToSmiles(back) == Chem.MolToSmiles(m), slug     # the string is the mol
        print(f"{slug}:\n  {smi}\n")
        if args.svg:
            from moleculefinder_etl.transform import structures
            args.svg.mkdir(parents=True, exist_ok=True)
            (args.svg / f"{slug}.svg").write_text(structures.svg_for(smi))


if __name__ == "__main__":
    main()
