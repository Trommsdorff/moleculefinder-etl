"""Read where each atom sits in a shipped structure drawing, and prove the reading.

Phase 5A (2026-11-12). The highlight layers, the aligned comparison pairs and the repeat units
all have to land on the atoms of the drawing that is actually shipped, and the shipped drawings
are stored artifacts: about 400 of the 896 were laid out by a machine or an RDKit release that
lays the same molecule out differently from this one (``structures`` docstring, trust run 6).
So nothing here lays a shipped molecule out again. Every position is read from the shipped SVG
itself, and ``redraw_matches`` proves the reading: the molecule redrawn by the shipped recipe from
the read positions alone must come out as the shipped drawing, path for path, every coordinate
within ``REDRAW_TOLERANCE``. A wrong position, a mirror image or a misattributed bond cannot pass.

What RDKit writes (rdkit 2026.03 and 2026.09, the releases behind every shipped drawing; checked
on all 896): only ``<path>`` elements. A bond is ``class='bond-K atom-I atom-J'`` with its lines
drawn from atom I towards atom J: one line for a single bond (it reaches an unlabelled atom
exactly and stops short of a labelled one), two for a double (either a full line on the axis plus
a shorter one beside it, or two lines either side of the axis when the bond is drawn centred),
three for a triple, a filled 3- or 4-point polygon for a solid wedge (its narrow end at atom I),
and 3 to 35 short cross lines for a hashed wedge. A label is ``class='atom-N'``, one path per
character, plus any radical dots. Unclassed paths join bonds at a vertex. Bonds and atoms past
the parsed molecule's count belong to hydrogens RDKit adds to show stereo, and are not read.

How the reading works (``atom_positions``): an unlabelled atom (a skeleton carbon) is the point
where its bonds' lines meet, which the SVG states exactly to 0.1 px. A labelled atom lies on the
axis of each of its bonds: the crossing of two axes, or one axis out from its known neighbour by
the drawing's bond length. An isolated atom (an ion, a lone element) is placed from its label.
The positions are then refined against a redraw (``refine``): every coordinate a redraw puts in
a different place from the shipped drawing moves its atom by the difference, until they agree.
Pure Python on the SVG text and RDKit's own substructure-free redraw; no layout is ever computed
for a shipped molecule.
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field

# A coordinate of the redraw may differ from the shipped drawing's by this much and still be the
# same drawing: RDKit writes coordinates to 0.1 px, so a position read from them is good to about
# 0.05 px, and a redraw from it rounds again.
REDRAW_TOLERANCE = 0.35

_PATH = re.compile(r"<path\b([^>]*?)/?>")
_ATTR = re.compile(r"(\w[\w:-]*)='([^']*)'")
_TOKEN = re.compile(r"[MLQZ]|-?\d+(?:\.\d+)?")


@dataclass
class Path:
    cls: str | None
    d: str
    style: str
    subpaths: list[list[tuple[float, float]]]   # points of each M..., in order
    closed: bool
    commands: str                               # the command letters, in order


def parse_d(d: str) -> tuple[list[list[tuple[float, float]]], bool, str]:
    subpaths: list[list[tuple[float, float]]] = []
    nums: list[float] = []
    cmds = ""
    closed = False
    for tok in _TOKEN.findall(d):
        if tok in "MLQZ":
            cmds += tok
            if tok == "M":
                subpaths.append([])
            if tok == "Z":
                closed = True
            continue
        nums.append(float(tok))
        if len(nums) == 2:
            subpaths[-1].append((nums[0], nums[1]))
            nums = []
    return subpaths, closed, cmds


def parse_svg(svg: str) -> list[Path]:
    out = []
    for m in _PATH.finditer(svg):
        attrs = dict(_ATTR.findall(m.group(1)))
        sub, closed, cmds = parse_d(attrs.get("d", ""))
        out.append(Path(attrs.get("class"), attrs.get("d", ""), attrs.get("style", ""),
                        sub, closed, cmds))
    return out


@dataclass
class Bond:
    idx: int
    a: int                 # the atom the lines start at (first in the class)
    b: int
    lines: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)
    polygon: list[tuple[float, float]] | None = None


def _bonds_and_labels(paths: list[Path], n_atoms: int):
    bonds: dict[int, Bond] = {}
    labels: dict[int, list[Path]] = {}
    for p in paths:
        if not p.cls:
            continue
        parts = p.cls.split()
        if parts[0].startswith("bond-"):
            k = int(parts[0][5:])
            a, b = (int(x[5:]) for x in parts[1:3])
            if a >= n_atoms or b >= n_atoms:
                continue                      # a bond to a hydrogen added for stereo
            bd = bonds.setdefault(k, Bond(k, a, b))
            if p.closed:
                bd.polygon = p.subpaths[0]
            else:
                for sp in p.subpaths:
                    bd.lines.append((sp[0], sp[-1]))
        elif parts[0].startswith("atom-"):
            i = int(parts[0][5:])
            if i < n_atoms and not _is_contact_flag(p):
                labels.setdefault(i, []).append(p)
    return bonds, labels


def _is_contact_flag(p: Path) -> bool:
    """RDKit's close-contact flag: a pure red, unfilled box round an atom the layout put too
    close to another (14 shipped drawings). It marks the layout, not the atom's label."""
    return "#FF0000" in p.style and "fill:none" in p.style


def _sub(p, q):
    return (p[0] - q[0], p[1] - q[1])


def _norm(v):
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n) if n else (0.0, 0.0)


def _mid(p, q):
    return ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)


def _dist_to_line(pt, p, u):
    v = _sub(pt, p)
    return abs(v[0] * u[1] - v[1] * u[0])


def _axes(bd: Bond) -> list[tuple[tuple[float, float], tuple[float, float], bool]]:
    """Candidate axis lines of a bond: (a point on it, unit direction a->b, exact?).

    A solid wedge's axis runs from its tip to the middle of its wide end; a hashed wedge's through
    the middles of its cross lines; a single line is its own axis; a double or triple bond offers
    each of its lines and the line midway between the outer two (the drawing says which only once
    an end atom is known).
    """
    if bd.polygon is not None:
        pts = bd.polygon
        if len(pts) == 3:
            # the tip is opposite the shortest side
            sides = [(math.dist(pts[(i + 1) % 3], pts[(i + 2) % 3]), i) for i in range(3)]
            _, tip = min(sides)
            w = _mid(pts[(tip + 1) % 3], pts[(tip + 2) % 3])
            start, end = pts[tip], w
        else:
            edges = sorted((math.dist(pts[i], pts[(i + 1) % len(pts)]), i) for i in range(len(pts)))
            (_, i1), (_, i2) = edges[0], edges[1]
            m1 = _mid(pts[i1], pts[(i1 + 1) % len(pts)])
            m2 = _mid(pts[i2], pts[(i2 + 1) % len(pts)])
            narrow, wide = (m1, m2) if edges[0][0] <= edges[1][0] else (m2, m1)
            start, end = narrow, wide
        return [(start, _norm(_sub(end, start)), True)]
    lines = bd.lines
    if not lines:
        return []
    if len(lines) == 1:
        s, e = lines[0]
        return [(s, _norm(_sub(e, s)), True)]
    lens = [math.dist(s, e) for s, e in lines]
    dirs = [_norm(_sub(e, s)) for s, e in lines]
    # Hashed wedge: three or more short cross lines; the axis runs through their middles.
    mids = [_mid(s, e) for s, e in lines]
    if len(lines) >= 3:
        spread = math.dist(mids[0], mids[-1])
        if spread > 2 * max(lens):
            u = _norm(_sub(mids[-1], mids[0]))
            return [(mids[0], u, False)]
    u = dirs[0]
    out = [(s, _norm(_sub(e, s)), True) for s, e in lines]
    # the midline of the two outermost lines
    offs = [(s[0] - lines[0][0][0]) * -u[1] + (s[1] - lines[0][0][1]) * u[0] for s, _ in lines]
    lo, hi = offs.index(min(offs)), offs.index(max(offs))
    out.append((_mid(lines[lo][0], lines[hi][0]), u, True))
    return out


def _intersect(p1, u1, p2, u2):
    den = u1[0] * u2[1] - u1[1] * u2[0]
    if abs(den) < 0.17:            # under about 10 degrees apart: no reliable crossing
        return None
    t = ((p2[0] - p1[0]) * u2[1] - (p2[1] - p1[1]) * u2[0]) / den
    return (p1[0] + t * u1[0], p1[1] + t * u1[1])


def _label_centre(paths: list[Path]) -> tuple[float, float]:
    """Centre of the first character's outline: RDKit centres an atom's element symbol on the
    atom and writes that character first (hydrogens and charges follow it or sit to one side)."""
    pts = [pt for sp in paths[0].subpaths for pt in sp]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


def drawing_mol(mol, svg: str):
    """``mol`` with the hydrogens the drawing shows, in the drawing's own atom order.

    To show stereo RDKit adds a hydrogen to some chiral atoms before it lays a molecule out;
    the SVG names each one (an index past the parsed molecule) and the atom it hangs on. Which
    atoms get one is decided inside RDKit's drawing code and differs once a molecule already has
    coordinates, so a redraw rebuilds exactly the drawing's set (``Chem.AddHs`` on those atoms,
    checked against the SVG) instead of asking RDKit to choose again.
    """
    from rdkit import Chem

    n = mol.GetNumAtoms()
    hs: dict[int, int] = {}
    for m in re.finditer(r"class='bond-\d+ atom-(\d+) atom-(\d+)'", svg):
        a, b = int(m.group(1)), int(m.group(2))
        if b >= n:
            hs[b] = a
        elif a >= n:
            hs[a] = b
    if not hs:
        return Chem.Mol(mol)
    out = Chem.AddHs(mol, onlyOnAtoms=sorted(set(hs.values())))
    got = {h.GetIdx(): h.GetNeighbors()[0].GetIdx() for h in out.GetAtoms() if h.GetIdx() >= n}
    if got != hs:
        raise ValueError(f"the drawing's stereo hydrogens {hs} are not RDKit's {got}")
    return out


def _lines_through(i, by_atom, pos):
    """Lines the atom ``i`` must lie on: (a point, unit direction pointing at ``i``)."""
    lines = []
    for bd in by_atom.get(i, []):
        j = bd.b if bd.a == i else bd.a
        axes = _axes(bd)
        if j in pos:
            q = pos[j]
            best = min(axes, key=lambda ax: _dist_to_line(q, ax[0], ax[1]))
            if _dist_to_line(q, best[0], best[1]) > 0.6:
                continue
            u = best[1] if bd.a == j else (-best[1][0], -best[1][1])
            lines.append((q, u, j))
        elif len(axes) == 1 and axes[0][2]:
            s, u, _ = axes[0]
            lines.append((s, u if bd.a == j else (-u[0], -u[1]), None))
    return lines


def first_guess(svg: str, dm, hash_short: bool = False) -> dict[int, tuple[float, float]]:
    """Each atom's position read from the drawing (see the module docstring). ``dm`` is
    ``drawing_mol``: the hydrogens added for stereo are read too."""
    n = dm.GetNumAtoms()
    paths = parse_svg(svg)
    bonds, labels = _bonds_and_labels(paths, n)
    labelled = set(labels)   # any label path: F and H are drawn with straight lines only
    by_atom: dict[int, list[Bond]] = {}
    for bd in bonds.values():
        by_atom.setdefault(bd.a, []).append(bd)
        by_atom.setdefault(bd.b, []).append(bd)

    pos = exact_points(svg, dm, _parsed=(bonds, labelled, by_atom))
    lengths = [math.dist(pos[bd.a], pos[bd.b]) for bd in bonds.values()
               if bd.a in pos and bd.b in pos]
    L = statistics.median(lengths) if lengths else None
    return _place_the_rest(pos, n, bonds, labels, by_atom, L, hash_short)


def exact_points(svg: str, dm, _parsed=None) -> dict[int, tuple[float, float]]:
    """The atoms a drawing states exactly: an unlabelled atom at the point where its bond lines
    meet (to RDKit's 0.1 px). No estimate, no redraw; a test reads two drawings' bytes with it."""
    n = dm.GetNumAtoms()
    if _parsed is None:
        bonds, labels = _bonds_and_labels(parse_svg(svg), n)
        labelled = set(labels)   # any label path: F and H are drawn with straight lines only
        by_atom: dict[int, list[Bond]] = {}
        for bd in bonds.values():
            by_atom.setdefault(bd.a, []).append(bd)
            by_atom.setdefault(bd.b, []).append(bd)
    else:
        bonds, labelled, by_atom = _parsed
    pos: dict[int, tuple[float, float]] = {}
    for i in range(n):
        if i in labelled or i not in by_atom:
            continue
        cands: list[tuple[tuple[float, float], int]] = []
        for bd in by_atom[i]:
            if bd.polygon is not None:
                s, u, _ = _axes(bd)[0]
                if bd.a == i:
                    pts = [s]
                else:
                    ends = sorted(bd.polygon,
                                  key=lambda q: -((q[0] - s[0]) * u[0] + (q[1] - s[1]) * u[1]))[:2]
                    pts = [_mid(*ends)]
            elif len(bd.lines) >= 3 and not _axes(bd)[0][2]:
                pts = []                           # a hashed wedge reaches neither atom
            else:
                pts = [(s if bd.a == i else e) for s, e in bd.lines]
                if len(bd.lines) == 2:
                    pts.append(_mid(pts[0], pts[1]))
            cands.extend((p, bd.idx) for p in pts)
        best, support = None, 0
        for p, _ in cands:
            s = len({k for q, k in cands if math.dist(p, q) <= 0.25})
            if s > support:
                best, support = p, s
        deg = len(by_atom[i])
        if best is not None and (support >= 2 or deg == 1 or support == deg):
            same = [q for q, _ in cands if math.dist(best, q) <= 0.25]
            pos[i] = (sum(q[0] for q in same) / len(same), sum(q[1] for q in same) / len(same))
    return pos


def _place_the_rest(pos, n, bonds, labels, by_atom, L, hash_short):
    # 2. labelled and unresolved atoms: candidates, scored by how well they sit on every line
    #    the atom must lie on; repeated while each pass places something
    for _ in range(n + 1):
        placed = False
        for i in range(n):
            if i in pos or i not in by_atom:
                continue
            lines = _lines_through(i, by_atom, pos)
            if not lines:
                continue
            cands = []
            if i in labels:
                cands.append(_label_centre(labels[i]))
            for k, (p1, u1, _) in enumerate(lines):
                for p2, u2, _ in lines[k + 1:]:
                    x = _intersect(p1, u1, p2, u2)
                    if x is not None:
                        cands.append(x)
            for bd in by_atom[i]:
                if bd.polygon is None and len(bd.lines) == 1:
                    s, e = bd.lines[0]
                    cands.append(s if bd.a == i else e)
            if L is not None and i in labels:
                # a label stops its bond lines short, so the lines give a direction, not a length
                for q, u, j in lines:
                    if j is not None:
                        cands.append((q[0] + L * u[0], q[1] + L * u[1]))
            # A hashed wedge's cross lines sit one spacing apart from one spacing past its narrow
            # end; the last lands on the far atom or one spacing short of it (measured on every
            # hashed bond of the drawings this machine reproduces).
            for bd in by_atom[i]:
                if bd.polygon is None and len(bd.lines) >= 3 and not _axes(bd)[0][2]:
                    mids = [_mid(s_, e_) for s_, e_ in bd.lines]
                    step = math.dist(mids[0], mids[-1]) / (len(mids) - 1)
                    u = _norm(_sub(mids[-1], mids[0]))
                    if bd.a == i:
                        cands.append((mids[0][0] - step * u[0], mids[0][1] - step * u[1]))
                    elif hash_short:
                        cands.append((mids[-1][0] + step * u[0], mids[-1][1] + step * u[1]))
                    else:
                        cands.append(mids[-1])
            anchored = [(pos[j], j) for j in (bd.b if bd.a == i else bd.a for bd in by_atom[i])
                        if j in pos]

            def score(c, lines=lines, anchored=anchored):
                # on every line it must lie on; between equally good points, the one nearest the
                # drawing's bond length from its placed neighbours (a tie-break only: 0.01 px a px)
                on = sum(_dist_to_line(c, q, u) for q, u, _ in lines)
                return on + 0.01 * sum(abs(math.dist(c, q) - L) for q, _ in anchored) if L else on
            known = [ln for ln in lines if ln[2] is not None]
            if len(lines) < 2 and not known:
                continue                      # one free line and no anchor: wait for a neighbour
            if not cands:
                continue
            best = min(cands, key=score)
            pos[i] = best
            placed = True
        if not placed:
            break
    # 3. anything left (lone atoms and ions, or a fragment with no unlabelled atom): its label
    for i in range(n):
        if i not in pos and i in labels:
            pos[i] = _label_centre(labels[i])
    return pos


# ── The proof: redraw from the read positions with the shipped recipe ───────────────────────
def drawing_difference(a: str, b: str) -> float:
    """Largest coordinate difference between two drawings of the same molecule, in px, or
    infinity when they differ in anything else (a path more or less, another class, another
    command, another style)."""
    pa, pb = parse_svg(a), parse_svg(b)
    if len(pa) != len(pb):
        return math.inf
    worst = 0.0
    for x, y in zip(pa, pb):
        if x.cls != y.cls or x.commands != y.commands or x.style != y.style:
            return math.inf
        nx = [c for sp in x.subpaths for c in sp]
        ny = [c for sp in y.subpaths for c in sp]
        if len(nx) != len(ny):
            return math.inf
        for u, v in zip(nx, ny):
            worst = max(worst, abs(u[0] - v[0]), abs(u[1] - v[1]))
    return worst


def bond_px(dm, pos) -> float | None:
    """The drawing's bond length: the median over bonds between heavy atoms whose ends are read.
    RDKit's depictor draws a bond 1.5 units long, so this fixes the drawing's scale."""
    ls = [math.dist(pos[b.GetBeginAtomIdx()], pos[b.GetEndAtomIdx()]) for b in dm.GetBonds()
          if b.GetBeginAtom().GetAtomicNum() != 1 and b.GetEndAtom().GetAtomicNum() != 1
          and b.GetBeginAtomIdx() in pos and b.GetEndAtomIdx() in pos]
    return statistics.median(ls) if ls else None


def mol_at(dm, pos: dict[int, tuple[float, float]], scale_px: float):
    """A copy of ``dm`` (``drawing_mol``) whose 2D conformer puts each atom at its drawing
    position in RDKit's own units (a bond is 1.5 long, ``scale_px`` pixels), y flipped back up,
    prepared for drawing as RDKit prepares any molecule (Kekulé bonds, wedges chosen from these
    coordinates) but adding no hydrogen of its own. RDKit then fits it to the canvas exactly as it
    fitted the original layout, which is how a redraw reproduces a drawing."""
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D
    from rdkit.Geometry import Point3D

    k = 1.5 / scale_px
    m = Chem.Mol(dm)
    m.RemoveAllConformers()
    conf = Chem.Conformer(m.GetNumAtoms())
    for i in range(m.GetNumAtoms()):
        x, y = pos.get(i, (0.0, 0.0))
        conf.SetAtomPosition(i, Point3D(x * k, -y * k, 0.0))
    conf.Set3D(False)
    m.AddConformer(conf, assignId=True)
    return rdMolDraw2D.PrepareMolForDrawing(m, kekulize=True, addChiralHs=False,
                                            wedgeBonds=True, forceCoords=False)


def draw_prepared(pm, width: int = 400, height: int = 300, **kw):
    """(svg, drawer) for a molecule ``mol_at`` prepared, in the shipped recipe."""
    from . import structures
    d = structures.drawer(width, height, **kw)
    d.drawOptions().prepareMolsBeforeDrawing = False
    d.DrawMolecule(pm)
    d.FinishDrawing()
    return structures._paint(d.GetDrawingText(), pm), d


def redraw(dm, pos, scale_px: float):
    return draw_prepared(mol_at(dm, pos, scale_px))


def anchors(svg: str, dm) -> dict[int, list[tuple[float, float]]]:
    """The marks a drawing pins to each atom alone: every coordinate of its label (glyphs and
    dots), or, for an unlabelled atom, the point its bond lines meet (``first_guess`` step 1, or
    its crossing of lines where they do not meet). Bond decorations that RDKit releases draw
    differently without moving any atom (which side of a ring a double bond's second line goes,
    how many cross lines a hashed wedge has, a wedge's width) are not anchors."""
    n = dm.GetNumAtoms()
    out: dict[int, list[tuple[float, float]]] = {}
    labelled = set()
    for p in parse_svg(svg):
        if p.cls and p.cls.startswith("atom-") and not _is_contact_flag(p):
            i = int(p.cls.split()[0][5:])
            if i < n:
                labelled.add(i)
                out.setdefault(i, []).extend(pt for sp in p.subpaths for pt in sp)
    for i, xy in first_guess(svg, dm).items():
        if i not in labelled:
            out[i] = [xy]
    # A hashed wedge's last cross line is drawn at its far atom or one spacing short of it, so it
    # pins a far atom that no line reaches (a methyl on a hash) to one of two places.
    bonds, _ = _bonds_and_labels(parse_svg(svg), n)
    for bd in bonds.values():
        if bd.polygon is None and len(bd.lines) >= 3 and not _axes(bd)[0][2] \
                and bd.b not in labelled and bd.b in out:
            out[bd.b] = out[bd.b] + [_mid(*bd.lines[-1])]
    return out


def anchor_difference(a: dict, b: dict) -> tuple[float, dict[int, tuple[float, float]]]:
    """(the largest anchor difference in px, each atom's mean shift from ``b`` to ``a``);
    infinity when an atom's anchors are not the same marks (missing, or another glyph count)."""
    worst = 0.0
    shift: dict[int, tuple[float, float]] = {}
    for i in a.keys() | b.keys():
        pa, pb = a.get(i), b.get(i)
        if not pa or not pb or len(pa) != len(pb):
            worst = math.inf
            continue
        ds = [_sub(x, y) for x, y in zip(pa, pb)]
        worst = max(worst, max(max(abs(d[0]), abs(d[1])) for d in ds))
        shift[i] = (statistics.fmean(d[0] for d in ds), statistics.fmean(d[1] for d in ds))
    return worst, shift


def refine(svg: str, dm, pos: dict[int, tuple[float, float]], rounds: int = 8):
    """Move each atom by how far a redraw puts its anchors from the shipped drawing's, until they
    agree. Returns (the redraw's own atom positions, the scale, the anchor difference, the whole
    drawing's difference); positions come from RDKit's drawer for the redraw, which is the shipped
    drawing at every anchor, so they are exact pixel centres rather than the estimate fed in."""
    target = anchors(svg, dm)
    scale = bond_px(dm, pos)
    best = (dict(pos), scale, math.inf, math.inf)
    for _ in range(rounds):
        out, d = redraw(dm, pos, scale)
        diff, shift = anchor_difference(target, anchors(out, dm))
        if diff < best[2]:
            drawn = {i: (d.GetDrawCoords(i).x, d.GetDrawCoords(i).y) for i in range(dm.GetNumAtoms())}
            best = (drawn, scale, diff, drawing_difference(svg, out))
        if diff <= 0.05:
            break
        for i, (dx, dy) in shift.items():
            if i in pos:
                pos[i] = (pos[i][0] + dx, pos[i][1] + dy)
        scale = bond_px(dm, pos) or scale
    return best


@dataclass
class Reading:
    """Where each atom of a shipped drawing sits, and how that is known.

    ``pos`` maps every atom of ``drawing_mol`` (the stereo hydrogens included) to its centre in
    the drawing's own pixels; ``scale_px`` is the drawing's bond length (None for a drawing with
    no bond). ``method``:
    - "identical": this machine's own draw of the SMILES is the shipped drawing byte for byte,
      so RDKit's drawer states the positions exactly;
    - "read": read from the SVG, and a redraw from them is the shipped drawing, path for path,
      within ``difference`` px;
    - "read-anchors": read from the SVG, and a redraw from them puts every atom's own marks
      (``anchors``) where the shipped drawing has them, within ``difference`` px, while drawing a
      bond decoration differently (this RDKit release puts a ring's second line on the other side,
      or hashes a wedge with another number of lines). The atoms are where they are shipped; only
      a redraw by this machine would look different, and nothing here redraws a shipped molecule.
    """
    pos: dict[int, tuple[float, float]]
    scale_px: float | None
    difference: float
    method: str


class UnreadableDrawing(ValueError):
    pass


def read_positions(svg: str, mol, *, use_identical: bool = True) -> Reading:
    """The atom positions of ``svg``, the shipped drawing of ``mol``, proven (see ``Reading``).
    Raises ``UnreadableDrawing`` when no proof holds. ``use_identical=False`` reads from the SVG
    only (the tests use it to measure the reading against RDKit's own positions)."""
    from rdkit import Chem

    from . import structures

    def rounded(p):
        return {i: (round(x, 2), round(y, 2)) for i, (x, y) in p.items()}

    dm = drawing_mol(mol, svg)
    if use_identical:
        fresh, d = structures.draw(Chem.Mol(mol))
        if fresh == svg:
            exact = {i: (d.GetDrawCoords(i).x, d.GetDrawCoords(i).y)
                     for i in range(dm.GetNumAtoms())}
            s = bond_px(dm, exact)
            return Reading(rounded(exact), round(s, 3) if s else None, 0.0, "identical")
    diff = math.inf
    # A methyl at the end of a hashed wedge sits on the last cross line or one spacing past it;
    # the first is the commoner, and the proof says when it is the other.
    for hash_short in (False, True):
        pos = first_guess(svg, dm, hash_short)
        if not (bond_px(dm, pos) and len(pos) == dm.GetNumAtoms()):
            break
        pos, _, diff, whole = refine(svg, dm, pos)
        if diff <= REDRAW_TOLERANCE:
            return Reading(rounded(pos), round(bond_px(dm, pos), 3), round(diff, 2),
                           "read" if whole <= REDRAW_TOLERANCE else "read-anchors")
    raise UnreadableDrawing(f"positions not proven (anchors off by {diff} px) and this machine "
                            "does not reproduce the drawing")
