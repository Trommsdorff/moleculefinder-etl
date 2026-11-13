# Drawing recipes: parts, aligned pairs, repeat units (phase 5A, 2026-11-12)

The hand-off from phase 5A (the engine) to phase 5B (content, web and deploy). Everything here is
in the ETL repo on branch `drawing-recipes-2026-11` (code `db70373`, data `8b400d3`, plus notes),
never pushed. Code: `moleculefinder_etl/transform/svg_geometry.py` (reading a shipped drawing) and
`moleculefinder_etl/transform/drawings.py` (the three recipes). Proofs: `tests/test_drawings.py`.

## The one rule

**Nothing redraws a shipped structure.** `structure_svg` is a stored artifact, laid out by
whichever machine and RDKit release drew it. This Mac lays out about 400 of the 896 shipped
drawings differently, and the platform, not the RDKit version, decides a layout (trust runs 6 and
7, run 3). So a highlight is a layer under the drawing that is actually shipped, placed where that
drawing puts each atom. The atom positions are read from the SVG itself and proven, drawing by
drawing. Nothing was redrawn in phase 5A: all 896 `structure_svg` are byte for byte what shipped
(`tests/fixtures/shipped-drawings-2026-11-12.json` holds every one's key and hash; a drawing may
change only with its own key).

## 1. Reading atom positions from a shipped drawing (`svg_geometry.read_positions`)

**Settled: yes, positions can be read reliably from the stored SVG, and each reading is proven.**

RDKit's SVG holds only `<path>` elements: a bond is `class='bond-K atom-I atom-J'`, drawn from atom
I towards atom J; a label is `class='atom-N'`, one path per character. There is no coordinate
metadata. The reading:

- A skeleton carbon (no label) sits where its bond lines meet: the SVG states that point exactly,
  to 0.1 px (`exact_points`).
- A labelled atom (O, N, Cl...) lies on the axis of each of its bonds, because the lines stop short
  of the label. Its position is where two axes cross, or one axis out from a known neighbour.
- A methyl at the end of a hashed wedge sits on the last cross line or one spacing past it.
- The stereo hydrogens RDKit adds are rebuilt exactly as the drawing shows them (`drawing_mol`).
- Then the reading is refined: the molecule is redrawn by the shipped recipe from the read positions,
  and every atom moves by how far its own marks land from the shipped drawing's.

**The proof, per drawing.** `Reading.method` says which one holds:

| method | what it proves | drawings |
|---|---|---|
| `identical` | this Mac's own draw of the SMILES *is* the shipped drawing byte for byte, so RDKit's drawer states the positions exactly | 490 |
| `read` | a redraw from the read positions *is* the shipped drawing, path for path, every coordinate within 0.35 px | 384 |
| `read-anchors` | a redraw from the read positions puts every atom's own marks (each label glyph point, each skeleton atom's line meeting point) where the shipped drawing has them, within 0.35 px; only a bond decoration differs (this RDKit release puts a ring's second line on the other side, or hashes a wedge with a different number of lines) | 17 |
| unproven | neither proof holds: no highlight, and the shipped drawing is shown as it is | 5 |

A redraw by itself cannot prove pixel positions, because RDKit refits any drawing to its canvas: a
reading that is scaled or shifted still redraws identically. So once a redraw matches, the
positions are taken from the redraw's own drawer (that drawing *is* the shipped one at every atom),
never from the estimate fed in.

**Accuracy, measured against the truth.** Wherever this Mac reproduces a drawing byte for byte, RDKit
states the true positions: 403 drawings with bonds. On the 397 of them where the reading from the
SVG alone (the `identical` route switched off) proves itself, it is never more than **0.15 px** off
(the test holds it at 0.25). The other six (cisplatin, liraglutide, potassium permanganate, silicon
dioxide, simeticone, sucralfate) do not prove themselves from the SVG alone; they are proven by
being byte-identical instead.

**The five unproven:** aldosterone, chitosan, insulin and inulin, which have bonds, and sodium
iodide, which has none. They are neither reproduced by this RDKit nor provable from the SVG (the
anchors stay 7.5 to 9 px apart, or a label glyph count differs). They keep their shipped drawing
with no highlight. Each is recorded under its key as `{key, recipe, parts: [], unread: why}`, so no
later run, on any machine, tries again and quietly starts highlighting one. **Nothing was redrawn.**
If Garrett wants parts on aldosterone (the only one on a likely door), the plan's fallback is to
redraw those four once under a new recipe version that stores positions. That moves four live
structures, so it is his call (recommended: leave them).

**Lone ions** (Na⁺, Ca²⁺ in a salt; an atom with no bond) can be placed two ways that draw
identically, so their positions are not trusted. They are never lit, never part of a pair's core,
and never counted in a threshold.

## 2. Parts of a molecule (`structure_parts` on each molecule record)

A part is **one amber path layered under the molecule's one shipped drawing**: a band along each
bond and a round dot on each atom, all in one `<path class='mf-part'>` (so overlaps never darken),
stroke `#E9A23B` (the site's `--found`) at opacity 0.55. The band is 0.4 of the drawing's bond
length, held between 3 and 24 px. To show part *n*, insert `layer` right after RDKit's
`<!-- END OF HEADER -->` line, so it sits under every bond and label (`drawings.compose`). Remove it
and you have the shipped drawing, path for path (tested on all 1,751 layers). A layer is about
0.3 KB at the median.

**Found by rule, never by atom number.** Seed: `sources/seeds/structure_parts.yaml`.

```yaml
max_parts: 3
defaults:                       # most specific first
  - {id: carboxylic-acid, group: carboxylic-acids, label: null, sentence: null}
  ...
  - {id: ring-system, rule: ring-system, label: null, sentence: null}
molecules:
  caffeine:                     # curated parts replace the defaults
    parts:
      - id: methyl-groups
        smarts: "[CH3]-[#7]"    # a pattern
        light: [0]              # which PATTERN atoms to light (not molecule atoms)
        bonds: touching         # also every matched bond with a lit end (default: within)
        expect: {matches: 3}    # the build stops if caffeine stops having three
        label: The three methyl groups
        sentence: >- ...
        from: standard chemistry for the name; the formulas are PubChem's.
```

- `group:` is a key of `categories.FUNCTIONAL_GROUPS`, the same SMARTS that build the `/in` hubs.
  `smarts:` is a pattern of its own. `rule: ring-system` lights the largest set of rings sharing
  atoms, with its ring bonds.
- **Defaults**, in order: carboxylic acid, ester, amide, aldehyde, ketone, phosphate, phenol, thiol,
  amine, alcohol, ether, halogen, benzene ring, ring system. A molecule gets at most three. A part
  is skipped when it lights nothing, the whole molecule, or only atoms an earlier part already lit.
  Result: 719 molecules have parts (417 three, 198 two, 104 one); 192 have none, and their field is
  `null`.
- **The default labels and sentences are `null`: writing them is 5B's job.** The web must show no
  default part until its label is written.
- **Caffeine's three** (the worked example and test fixture) are the approved mockup's, verbatim:
  the xanthine core (ring system, 9 atoms), the three methyl groups, and the carbonyl oxygens (each
  O with its C=O bond).
- Every label, sentence, `from` note, caption and repeat-unit label is in the claim rule's corpus as
  kind `part`. A claim word needs an entry under `part:` in `claims_allowed.yaml`. Caffeine's "it can
  only accept them" has one (basis ordinary).

Each part carries: `id`, `rule`, `label`, `sentence`, `from`, `atoms`, `bonds` (molecule atom
indices, for the web's button state only), `layer`, `confidence` (`from_source` curated,
`computed` default) and `source`.

**To add a curated part:** add the molecule under `molecules:` with its parts (curated parts replace
the defaults, so list every part it should show). Give each one an `expect:`, run `mfetl all` and
look at the layer (see "Seeing a layer" below).

## 3. Comparison pairs (`data/snapshots/compare_drawings.json`)

Kept out of `comparisons.json` so that file stays small (`compare_drawings.json` is 0.9 MB). For each
`/vs` pair:

1. **The common core**: RDKit's maximum common substructure (elements and bond orders must match,
   rings only match whole rings, stereo ignored). Of the ways the core maps onto the second
   molecule, the one that keeps the most atoms' neighbour counts, so the difference sits on as few
   atoms as it can.
2. **Align** when the core has at least `ALIGN_MIN_ATOMS = 3` atoms and at least
   `ALIGN_MIN_SHARE = 0.4` of the larger molecule's atoms. Why: three atoms fix an orientation, and
   fewer is a bond, not a shape. Below 0.4, two molecules sharing one benzene ring are not "the same
   skeleton", and turning one to match the other would say they are. 0.4 rather than 0.5 lets
   adenosine vs caffeine align on their shared purine (9 of 19 atoms) and acetaminophen vs ibuprofen
   on their benzene ring.
3. **The first molecule keeps its shipped drawing.** The second is laid out with its core atoms
   pinned to the first drawing's read positions, drawn by the shipped recipe at the first drawing's
   scale (on a canvas four times the size, so it never shrinks to fit), then moved so the core lands
   on the same pixels. Proven: every core atom is within 1 px, read back from both SVGs' bytes.
4. **Highlight** when the atoms outside the core, both sides together, number 1 to
   `HIGHLIGHT_MAX_ATOMS = 4`: a methyl, a hydroxyl, an ethyl, a halogen, a keto against a hydroxyl.
   Past four the difference is a second structure, not a group, and the eye reads it unaided. Both
   sides light their own extra atoms, the core atoms those hang on, and the matching atom on the
   other side. Caffeine vs theobromine lights caffeine's extra methyl and its nitrogen, and
   theobromine's N-H nitrogen.
5. Otherwise, **the two shipped drawings** with no highlight, and `reason` says why.
6. Molecules over `ALIGN_MAX_ATOMS = 120` heavy atoms (the large peptides) are not searched. This is
   a size rule, not a timeout, so the answer never depends on the machine's speed.

**The frame.** When the second drawing reaches past the first's 400 by 300 canvas, the pair carries
`frame: [x, y, w, h]`. **Show both drawings with that viewBox** (set the first's `viewBox`
attribute when rendering; its paths stay untouched). The second's `b_svg` already has it. 31 pairs
have a frame.

Entry fields: `mode` (`aligned`/`shipped`), `reason`, `core`, `core_map` ([first atom, second atom]
pairs), `highlight`, `extra_atoms`, `frame`, `b_svg` (the second molecule's drawing), `a_layer` and
`b_layer` (the difference layers, `class='mf-diff'`), `a_atoms`, `b_atoms`, `caption`, `key`,
`recipe`, `palette`, `confidence`, `source`. For `mode: shipped` the page uses the two records'
`structure_svg`.

**Seed:** `sources/seeds/compare_drawings.yaml`.

```yaml
captions:
  caffeine-vs-theobromine: One methyl group apart.
shipped: {}          # {pair: reason} holds a pair to its two shipped drawings whatever the rule finds
```

**To add a caption:** one short sentence under `captions:`. The build stops if the pair is not
highlighted (a caption describes a marked difference). It joins the claim corpus. Captions beyond
caffeine vs theobromine's are 5B's to write.

### The counts (147 pairs)

**Aligned and highlighted, 24** (atoms differing): acetone vs ethyl acetate (4), acetone vs isopropyl
alcohol (2), amitriptyline vs nortriptyline (1), benzene vs toluene (1), butane vs propane (1),
**caffeine vs theobromine (1)**, caffeine vs theophylline (1), cortisone vs cortisol (2), diazepam vs
lorazepam (3), dopamine vs norepinephrine (1), epinephrine vs norepinephrine (1), erythritol vs
allulose (4), ethanol vs isopropyl alcohol (1), ethylene glycol vs propylene glycol (1), fluorouracil
vs uracil (1), glycerol vs propylene glycol (1), hyoscine butylbromide vs scopolamine (4), melatonin vs
serotonin (4), nicotinamide vs niacin (2), oxazepam vs diazepam (2), oxycodone vs hydrocodone (1),
palmitic acid vs stearic acid (2), prednisone vs dexamethasone (4), xylitol vs erythritol (2).

**Aligned, nothing marked, 51.** Nine of them have 0 atoms differing: enantiomers and stereoisomers
(armodafinil/modafinil, dexmethylphenidate/methylphenidate, escitalopram/citalopram,
eszopiclone/zopiclone, levocetirizine/cetirizine, isotretinoin/tretinoin,
betamethasone/dexamethasone), where the second drawing shows its own wedges; and two salt pairs. The
other 42 differ by 5 to 36 atoms (acetaminophen/aspirin, adenosine/caffeine, the steroids, the
statins' and sartans' shared halves, the carotenoids...).

**Shipped drawings, 72**: core too small, 59 (aspartame/saccharin, glucose/fructose, ethanol/methanol
with a core of 2, ...); a polymer with no drawing, 7 (agar/gelatin, collagen/gelatin,
collagen/keratin, gelatin/pectin, maltodextrin/starch, starch/cellulose, xanthan gum/guar gum); too
large, 5 (insulin/glucagon, leptin/ghrelin, liraglutide/semaglutide, metformin/semaglutide,
semaglutide/tirzepatide); no common core, 1 (ammonia/sodium hypochlorite).

### The awkward cases, and what each does

- **Salts aligned on their anion, nothing marked:** calcium carbonate vs sodium bicarbonate and
  sodium bicarbonate vs sodium carbonate align on the carbonate and mark nothing, because their real
  difference is the ions and a hydrogen, and lone ions are never lit. Recommend
  `shipped: {pair: "the difference is the ions"}` in the seed if 5B finds the aligned view says less
  than the two apart.
- **Starch vs cellulose** shows "no drawing" by rule. Both now have a repeat unit in **one identical
  layout** (every skeleton atom on the same pixel, tested), so 5B can show the two repeat units side
  by side on that page with only the linkage differing.
- **Ethanol vs methanol and formaldehyde vs acetaldehyde** ("one carbon apart") have a core of two
  atoms, under the three-atom floor, so they show the two shipped drawings. A two-atom core fixes no
  orientation. That is the rule working, not a gap.
- **Methane vs propane:** methane is one atom with no bond, so there is no core.
- **The large peptides** are excluded by size (see 6 above).
- **A shipped drawing with no proven positions** (aldosterone, chitosan, insulin, inulin) as the
  first molecule would show the two shipped drawings. None of them is first in an aligned pair today.

## 4. Repeat units (`structure_repeat_unit` on a hand-modelled polymer's record)

Seed: `sources/seeds/repeat_units.yaml`.

```yaml
units:
  starch:
    smiles: "*O[C@H]1O[C@H](CO)[C@@H](O[C@H]2O[C@H](CO)[C@@H](O*)[C@H](O)[C@H]2O)[C@H](O)[C@H]1O"
    linkage: alpha-1,4
    linkage_smarts: "[#6;R]-[#8;!R]-[#6;R]"   # the joint; must match exactly `linkages` times
    linkages: 1
    units: 2
    label: Two units of the chain              # Garrett's ruling 5, 2026-11-09
```

`*` marks where the chain carries on. The record gets `{key, recipe, palette, smiles, label,
linkage, units, svg, layer (class='mf-linkage'), linkage_atoms, confidence, source}`. Only a record
with no `structure_svg` may have one (the build stops otherwise).

**Starch** is two alpha-D-glucose units joined 1→4, derived from the catalog's own maltose (PubChem's
4-O-alpha-D-glucopyranosyl-D-glucose). **Cellulose** is the same two units with both anomeric carbons
inverted, beta 1→4. The proof is a pattern, not a CIP label (a `*` end and the neighbouring ring both
move CIP priorities; a first attempt checked by CIP got starch's internal linkage backwards, and the
maltose test caught it). The alpha-glucosyl unit cut from that maltose matches both of starch's
units and neither of cellulose's; its inverse, the reverse. Starch with hydrogen for `*` is that
maltose, stereo included. The catalog's amylose model matches the alpha unit twice. The two drawings
share one layout to the pixel, so the linkage (a wedge in one, a hash in the other, under the amber)
is the visible difference.

**To add a repeat unit:** a unit under `units:` with a SMILES whose chain ends are `*`, a
`linkage_smarts` that finds the joint once, and the label. Prove the stereo with a pattern taken from
a catalog molecule, as the starch test does.

**Which other structureless polymers suit one** (the catalog's 19 records with no structure):

| record | repeat unit? | why |
|---|---|---|
| agar | yes | agarobiose (D-galactose and 3,6-anhydro-L-galactose) is a defined repeating disaccharide |
| pectin | yes, with a caveat | the backbone is alpha-1,4-galacturonic acid; some units are methyl esters, so the label must say "two units of the backbone" |
| guar gum | partly | a beta-1,4-mannose backbone with a galactose branch on about every second unit; two backbone units are honest, but the branching is statistical |
| xanthan gum | yes, but larger | its repeat is a defined pentasaccharide (two glucose backbone units plus a three-sugar side chain), not a two-unit fragment |
| carrageenan | only per type | kappa, iota and lambda carrageenan differ in sulfation; a drawing would have to name one type |
| collagen | arguably | the Gly-X-Y triplet repeats, but X and Y vary (often proline and hydroxyproline), so a triplet would be a typical unit, not the repeat |
| gelatin | no | a mixture of collagen fragments |
| gluten | **no** | a mixture of proteins (gliadins and glutenins), with no repeat unit; leave it without a drawing |
| albumin, casein, fibrin, hemoglobin, keratin, endorphin, pembrolizumab | no | proteins with sequences, not repeat units |
| lecithin | no | a mixture of phospholipids, not a polymer |
| melanin | no | a heterogeneous polymer with no defined repeat |
| starch, cellulose | **done** | |

## 5. Keys, versions, carry-forward, repaint

| output | recipe version | key (sha1 of) | repaint |
|---|---|---|---|
| `structure_parts` | `PARTS_RECIPE` 2026-11-12.1 | recipe, the shipped drawing's **geometry** (the SVG with its colours removed), the SMILES, the matched parts (ids, atoms, bonds, text) | none needed (amber only) |
| a pair | `PAIRS_RECIPE` 2026-11-12.1 | recipe, both slugs, the first drawing's geometry, both SMILES, the caption, the `shipped` override | `b_svg` repainted with `structures.recolour` when `palette` is not the current `structures.RECIPE_VERSION` |
| `structure_repeat_unit` | `REPEAT_RECIPE` 2026-11-12.1 | recipe, slug, the whole seed entry | `svg` repainted the same way |

A current key is carried forward byte for byte. A palette change repaints and moves no coordinate,
because the geometry key ignores colours. **Only a version bump draws again** (bump it when a
threshold, the layer's look or the matching changes). Changing the parts seed remakes only the
molecules whose matched parts changed.

## 6. The two machines

**The design.** The weekly run draws on Linux. No new output is ever derived from a fresh layout of a
shipped molecule:

- **The keys are platform-free.** They are hashes of the shipped bytes, the SMILES and the seeds.
  The parts key also includes which atoms the SMARTS rules match, and RDKit's substructure match is
  the same on any platform; a ring system is a union of rings, which is the same whichever smallest
  set of rings RDKit picks.
- **With every key current, the weekly run makes nothing.** It reads no drawing, lays nothing out,
  draws nothing and runs no common-core search.
- **A new molecule** is drawn fresh on Linux by `svg_for`. Its positions then come from that very
  drawer (`identical`, by construction), and the result is committed in the data PR.
- **A new pair** reads its first drawing on Linux and draws the second there; its proof (core within
  1 px) runs wherever it is made.
- **An unproven drawing** is recorded under its key, so Linux never retries it. Without that, a Linux
  RDKit that happened to reproduce aldosterone would start highlighting it on a Monday.

**The proof before Monday.** This Mac has no Linux runtime (no docker, colima, podman, lima or orb),
and a GitHub Actions run would need a push, so no Linux build was run. Instead
`test_a_run_with_current_keys_never_reads_lays_out_or_draws` replays what the weekly run does. It
patches every platform-dependent call to raise: the reading, `structures.draw`, RDKit's
`Compute2DCoords`, the common-core search and the repeat-unit drawing. Then it re-runs all three
recipes against the committed snapshot as the prior, and every output must come back byte for byte.
It passes, so no machine-dependent code runs for any carried output, and the platform cannot move
one. The pinned build on this Mac also carried all 719 part sets, 147 pairs and 2 repeat units on its
second run, byte-identical.

**What the first weekly run after deploy must show** (the acceptance):

- `structure parts: 719 carried, 0 made, 192 with no part, 4 drawings unreadable`
- `repeat units: 2 (0 drawn this run)`
- `compare drawings: 147 pairs (aligned 51, aligned+highlight 24, shipped 72); 147 carried, 0 repainted, 0 made`
- the data PR changes no `structure_parts`, `structure_repeat_unit` or `compare_drawings.json` byte
  and no `structure_svg`, unless a molecule or pair is new.

Any "made" count above 0 with no new molecule or pair is a key that differs on Linux. Stop and
compare that key's inputs.

## 7. What 5B must not touch

- **No shipped `structure_svg`**, and no redraw of one, by any route. A highlight is always a layer.
- **The recipe constants and versions**, unless a recipe genuinely changes. Then bump the version and
  report every output that moves, structure by structure.
- **`svg_geometry.py`'s tolerances and the unproven list**, without re-running the sweep.
- **Caffeine's three parts and the caption:** they are the approved mockup's words.
- **The web, before the ETL deploy:** the new fields must be on the IndexNow delta's ignore list
  (`structure_parts`, `structure_repeat_unit`, and `compare_drawings.json`) in the web repo **before
  or with** the deploy that brings them into the web's snapshot copy. Otherwise every molecule page
  resubmits. That is web work, so it was not done here.

## 8. What 5B does

Labels and sentences for the default parts and for any curated parts (the claim rule applies);
captions for the other highlighted pairs; deciding the awkward cases above (the two salt pairs; the
starch vs cellulose page using the repeat units); the web: render a part layer under the drawing
(`compose`), the `frame` viewBox for a pair, no default part without a label, no part section for an
`unread` record; the IndexNow ignore entries; `npm run sync-data`; the review page; the deploy on
Garrett's word (ETL `main`, then web `main`).

## Seeing a layer

`drawings.compose(record["structure_svg"], part["layer"])` returns the drawing with the part under
it. To look at one on this Mac, put a `<rect fill='#0e2233'>` after the header, write the SVG to a
file, and run `qlmanage -t -s 600 -o <dir> <file>.svg` (macOS Quick Look renders SVG to PNG; headless
Brave's `--screenshot` hangs on this Mac).
