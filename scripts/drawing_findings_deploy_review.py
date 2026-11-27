"""Add the deploy's section to the drawing-findings review page (moleculefinder-web/docs/design/
drawing-findings-review-2026-11.html), at the top of its <main>, between <!-- deploy --> markers (replaced on a rerun).

    ./.venv/bin/python3 scripts/drawing_findings_deploy_review.py <shots-dir> <facts.json> <indexnow.txt>

<shots-dir> holds Lighthouse full-page PNGs: after-acrylonitrile-butadiene-styrene-<w>, after-shellac-<w> (a local
production build of the branch, keys blanked) and before-shellac-<w> (the live site), w = 1440 or 390. <facts.json> the
session's check results; <indexnow.txt> the IndexNow dry run's changed URLs. The hub counts are counted here from the
snapshot and `git show main:`, the frozen fields read from the web's scripts/frozen-text-drawing-findings.json.
Brief: ../TRUST-2C-DRAWING-FINDINGS-DEPLOY-PROMPT.md (Garrett's word, 2026-11-27).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from drawing_findings_review import OUT, SNAP, WEB, e, fig, git, rec  # noqa: E402

HUBS = ["alcohols", "ethers", "amides", "aromatics", "carboxylic-acids", "esters", "element-nitrogen", "over-1000-g-mol"]
WHY = {
    "over-1000-g-mol": "inulin leaves: its 6,179 g/mol was the weight of PubChem's 38-sugar chain, and ruling 1 keeps the "
                       "weight dropped",
    "alcohols": "shellac leaves (ruling 4: no membership computed from PubChem's two stand-in acids)",
    "carboxylic-acids": "shellac leaves (ruling 4: no membership computed from PubChem's two stand-in acids)",
}


def counts(read) -> dict:
    out = dict.fromkeys(HUBS, 0)
    for r in read():
        for c in r.get("categories") or []:
            if c["slug"] in out:
                out[c["slug"]] += 1
    return out


def main_records():
    names = git("ls-tree", "--name-only", "main", "data/snapshots/molecules/").split()
    for n in names:
        yield json.loads(git("show", f"main:{n}"))


def branch_records():
    for p in sorted((SNAP / "molecules").glob("*.json")):
        yield json.loads(p.read_text())


def main() -> None:
    shots, facts = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text())
    changed = [u.replace("https://moleculefinder.com", "") for u in Path(sys.argv[3]).read_text().split()]
    before_n, after_n = counts(main_records), counts(branch_records)
    frozen = json.loads((WEB / "scripts" / "frozen-text-drawing-findings.json").read_text())
    p: list[str] = []
    w = p.append
    w("<!-- deploy -->")
    w('<section class="deploy"><h2>At the deploy (2026-11-27): Garrett\'s rulings applied</h2>')
    w("<p>Brief <code>TRUST-2C-DRAWING-FINDINGS-DEPLOY-PROMPT.md</code>. The eight new drawings were looked at large by "
      "Cowork and are right. This section supersedes the stops below: ruling 1 (hubs from the repeat unit), ruling 2 "
      "(the remaining frozen moves, a recorded exception), ruling 3 (glucose vs glycogen's text), ruling 4 (shellac's "
      "panel), ruling 5 (ABS's row), ruling 6 (magnesium glycinate's name), ruling 7 (sodium hyaluronate, as built). "
      "Not in this deploy: the two dots RDKit draws under \"Mg\" (ruling 8, queued by Cowork).</p>")
    # ── hubs
    w("<h3>Hub counts as they now stand (live today, then after the deploy)</h3><table><tr><th>hub</th><th>live</th>"
      "<th>after</th><th>why it moves</th></tr>")
    for h in HUBS:
        b, a = before_n[h], after_n[h]
        w(f'<tr><td>/in/{e(h)}</td><td>{b}</td><td>{a}</td><td>{e(WHY.get(h, "")) if a != b else "<span class=muted>no move</span>"}</td></tr>')
    w("</table><p class=\"muted\">The six polymers and ABS take their functional groups and elements from their repeat "
      "unit (repeat_units.yaml <code>hubs: repeat-unit</code>), each membership marked <code>from: repeat_unit</code>, and "
      "the molecule page's notes say so (\"Groups it belongs to: RDKit, from the repeat unit\"). Matched on the unit, they "
      "are the hubs the stand-in records had, so ethers, amides, aromatics, esters and nitrogen hold. PMMA's alkene "
      "and a free reducing end were never hubs. Weight, formula, SMILES, InChI, descriptors and the 3D model stay "
      "dropped.</p>")
    # ── frozen
    n_fields = sum(len(v) for v in frozen["pages"].values())
    w(f"<h3>Frozen fields that move ({n_fields} on {len(frozen['pages'])} pages), each allowed exactly in "
      "<code>frozen-text.mjs</code></h3><table><tr><th>page</th><th>field</th><th>before (main)</th><th>after</th></tr>")
    for page, fields in frozen["pages"].items():
        for f, v in fields.items():
            fmt = (lambda x: json.dumps(x, ensure_ascii=False)) if f in ("faq", "visible_faq") else str
            if f in ("og:description", "twitter:description"):
                continue
            w(f"<tr><td>/{e(page)}</td><td>{e(f)}</td><td>{e(fmt(v['before']))}</td><td>{e(fmt(v['after']))}</td></tr>")
    w("</table><p class=\"muted\">og:description and twitter:description move with each description, word for word "
      "(in the record). Why each moves: " + e("; ".join(f"/{k}: {v}" for k, v in frozen["why"].items())) + "</p>")
    # ── ABS
    abs_u = rec("acrylonitrile-butadiene-styrene")["structure_repeat_unit"]
    w("<h3>Ruling 5: ABS's three units in one tighter row</h3><p>Coordinates only: the same three units, label and line. "
      "One baseline, the nitrile up and the ring down, one bond length between units: the row is 16.3 bond lengths wide "
      "(it was 18.8), so the units draw about 15 percent larger and use about 60 percent of the panel's height (about "
      "40 before).</p>")
    w(f'<div class="panel" style="max-width:520px">{abs_u["svg"]}</div>')
    w('<div class="row">' + "".join(fig(shots, f"after-acrylonitrile-butadiene-styrene-{px}", f"After, {px} px",
                                        1100 if px == 1440 else 1500) for px in (1440, 390)) + "</div>")
    # ── shellac
    s = rec("shellac")
    w("<h3>Ruling 4: shellac, the no-structure panel</h3>"
      f"<p>The panel reads: <b>Shellac</b> is {e(s['structure_none']['line'])} Its PubChem record (CID 6850749) is two "
      "small acids, one of them 9,10,15-trihydroxypentadecanoic acid (C15), not aleuritic acid (C16). As for the "
      "polymers (structure_none.yaml <code>stand_in: true</code>): formula, weight, SMILES, identifiers, descriptors and "
      "3D dropped; its drawing and three part layers leave (the guard lists both); its two computed hubs (alcohols, "
      "carboxylic acids) go; its curated memberships (Element &amp; material, Polymers, the paint list) and its 18 product "
      "rows stay. Its description names no formula or weight, so it does not move; its title stays "
      "(<code>lib/titles.ts</code>). It leaves the weight boards (biggest, lightest), as the polymers did.</p>")
    w('<div class="row">' + "".join(fig(shots, f"{t}-shellac-{px}", f"{t.title()}, {px} px", 1100 if px == 1440 else 1500)
                                    for t in ("before", "after") for px in (1440, 390)) + "</div>")
    # ── names and text
    mg = rec("magnesium-glycinate")
    w("<h3>Ruling 6 and ruling 3</h3><p>Magnesium glycinate's \"Also called\" now reads: "
      f"<b>{e(', '.join(mg['display_synonyms']))}</b> (\"Magnesium diglyci\" is on <code>synonym_do_not_use.yaml</code>; "
      "search keeps it).</p>")
    cmp = json.loads((SNAP / "comparisons.json").read_text())["glucose-vs-glycogen"]
    first = re.split(r"(?<=\.) ", cmp["text"])[0]
    w(f"<p>Glucose vs glycogen's text now opens: <b>{e(first)}</b> (it read \"That is why glycogen's listed formula "
      "and weight represent a fragment rather than a fixed molecule.\"). Its answer line, the page's description, does "
      "not move; its claim entry is re-pinned (the \"only\" sentence is unchanged).</p>")
    # ── guard, checks, indexnow
    w(f"<h3>The drawing guard against main ({len(facts['guard'])}, nothing stopped)</h3><pre>{e(chr(10).join(facts['guard']))}</pre>"
      f"<p><b>Drawings, the next weekly run:</b> {e(facts['drawings_after'])}</p>")
    w("<h3>Checks</h3><ul>" + "".join(f"<li>{e(c)}</li>" for c in facts["checks"]) + "</ul>")
    w(f"<h3>IndexNow dry run: {len(changed)} changed</h3><p class=\"mono\">{e(' '.join(changed))}</p>")
    w("</section>\n<!-- /deploy -->")
    block = "\n".join(p)
    page = OUT.read_text()
    page = re.sub(r"<!-- deploy -->.*?<!-- /deploy -->\n?", "", page, flags=re.S)
    i = page.index("<main>") + len("<main>")
    j = page.index("</h1>", i) + len("</h1>") if "</h1>" in page[i:i + 4000] else i
    page = page[:j] + "\n" + block + "\n" + page[j:]
    OUT.write_text(page)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
