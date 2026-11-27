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

**What the first weekly run after deploy must show** (the acceptance). *Superseded by 5B: the counts Monday 2026-11-16
must show are in section 9, and where to read them, what holds the data PR and what to do if they differ are in the
CLAUDE.md, "Phase 5B", recorded at the deploy of 2026-11-13. Since the drawing guard (section 10, 2026-11-13)
the counts are on the run's summary page and a change nothing explains stops the run. 5A's own counts, for the record:*

- `structure parts: 719 carried, 0 made, 192 with no part, 4 drawings unreadable`
- `repeat units: 2 (0 drawn this run)`
- `compare drawings: 147 pairs (aligned 51, aligned+highlight 24, shipped 72); 147 carried, 0 repainted, 0 made`
- the data PR changes no `structure_parts`, `structure_repeat_unit` or `compare_drawings.json` byte
  and no `structure_svg`, unless a molecule or pair is new.

Any "made" count above 0 with no new molecule or pair is a key that differs on Linux. Stop and
compare that key's inputs. (Since 2026-11-13 the drawing guard, section 10, stops the run itself.)

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

## 9. Phase 5B, what it added (2026-11-12)

The content, the first web use and the review page (`moleculefinder-web/docs/design/phase-5-review-2026-11.html`).

- **Every default rule has a label, a sentence and `from`** (standard chemistry), one sentence per rule, written to be
  true of every molecule the rule matches. 24 default rules now (14 in 5A): the contact sheet's misreadings fixed most
  specific first, new rules epoxide, barbiturate ring, imide, urea, carbamate, lactone, sulfonamide, guanidine, acetal,
  hemiacetal; ester, amide, aldehyde, amine, phenol, phosphate, halogen and ether narrowed by their own `smarts:` (the
  `/in` hubs keep `categories.FUNCTIONAL_GROUPS` untouched); a benzene ring fused to another ring belongs to the ring
  system (`[c;R1]` six-ring), so the ring system never repeats the benzene ring part. The table of what changed is at
  the top of `structure_parts.yaml`. Result: 718 molecules with parts, 193 none, 4 unread.
- **Curated parts** for caffeine (unchanged) and the door chains' stop molecules: adenosine, theobromine,
  acetaminophen, ibuprofen, dextromethorphan, doxylamine, menthol, camphor, ethanol, maltol, furaneol, sucrose,
  aspartame, sucralose, stevioside, xylitol, erythritol, sodium bicarbonate, sodium carbonate, vitamin C, citric acid,
  limonene. Each with `expect`, a sentence and its basis. No parts, on purpose: ammonia, hydrogen peroxide, sodium
  hypochlorite, sodium hydroxide (one or two atoms, or lone ions), gluten, starch and cellulose.
- **Text house rules** (`drawings.check_text`, at the start of `stage_transform`): no em or en dash, no advice or dosing
  word, no completeness phrase, no LD50, no "inferred", lengths, a full stop. The claim rule as before (kind `part`).
- **Captions for all 31 highlighted pairs.** `drawings.caption_rule` writes a caption from the computed difference (a
  methyl, a hydroxyl, a halogen in place of a hydrogen, N carbons longer, X where Y, "Two differences: ...") from
  substructure facts only, so any machine agrees. The seed holds every caption; a test holds each one not listed under
  `curated:` to the rule's text, and each curated one says why. 19 by rule, 12 curated (5 the rule cannot phrase, 7
  three-dimensional marks).
- **Three-dimensional marks (the one engine change):** `stereo:` in `compare_drawings.yaml`, a pattern matched on both
  molecules, which must light the same atoms on both sides of the core map. Seven pairs differ only in arrangement in
  space: armodafinil/modafinil, betamethasone/dexamethasone, dexmethylphenidate/methylphenidate,
  escitalopram/citalopram, eszopiclone/zopiclone, isotretinoin/tretinoin, levocetirizine/cetirizine (the two salt pairs
  also have no differing atom, but their difference is ions). The mark joins the pair's key only when present, so no
  other key moved.
- **Found and fixed: a layout can flip a double bond.** In a flat drawing the coordinates are the cis or trans
  geometry; tretinoin laid out on isotretinoin's core came out cis. `drawings._double_bonds_kept` now refuses any such
  layout (the pair falls back to its two shipped drawings), and a three-dimensional mark can sit on the two shipped
  drawings (`drawings: shipped`), each layer placed from that drawing's own proven reading
  (`_stereo_mark_shipped`). Isotretinoin vs tretinoin is the only pair affected (every other aligned pair checked).
  So a pair entry may now be `mode: shipped` WITH `a_layer` and `b_layer`: the page composes each onto the record's own
  `structure_svg`.
- **Counts:** 147 pairs: aligned 44, aligned and highlighted 30, shipped 72, shipped and highlighted 1.
- **The web** (`lib/drawings.ts`): `composeLayer` and `withFrame`, the web's one copy of `compose` and the frame,
  held to the ETL's own bytes by `lib/fixtures/drawings-compose.json` (written by `scripts/compose_fixture.py`). The home
  page's Compare two molecules is the first and only place that renders a pair; parts and repeat units are not rendered
  anywhere yet (phases 7, 8, 9).
- **Monday's acceptance** (the first weekly run after the deploy): `structure parts: 718 carried, 0 made, 193 with no
  part, 4 drawings unreadable`; `repeat units: 2 (0 drawn this run)`; `compare drawings: 147 pairs (aligned 44,
  aligned+highlight 30, shipped 72, shipped+highlight 1); 147 carried, 0 repainted, 0 made`.

## 10. The drawing guard (2026-11-13)

Found at the phase 5 deploy: the weekly run held its data PR only if caffeine's parts, the home
page's caffeine and theobromine pair or acetone vs ethyl acetate's framed drawing moved (the web's
`lib/drawings.test.ts`). Any other part layer, pair drawing or repeat unit could be made again on the
Linux runner and merge unseen. Garrett's ruling (2026-11-13): close it at the root, before Monday.
Code: `moleculefinder_etl/transform/drawing_guard.py`; tests: `tests/test_drawing_guard.py` (26).

**What it checks: every drawing output, not a sample,** against the snapshot on disk, which is what is
shipped (in the weekly run, the checkout of `main`): every `structure_svg` (with `structure_svg_key`),
every part layer in `structure_parts`, every pair in `compare_drawings.json`, every
`structure_repeat_unit`. It runs in `pipeline._preflight`, after the pairs are compiled, so before the
Supabase load and before anything is written. It only compares bytes: it reads, lays out and draws
nothing (a test makes every such call raise and runs it), so it changes no output.

**The rule, per entry:**

| case | verdict |
|---|---|
| key unchanged, output byte for byte the shipped one | carried |
| key unchanged, only the palette moved to the current recipe and only the drawing's colours with it (a pair's `b_svg`, a repeat unit's `svg`) | allowed, listed "repainted" |
| key unchanged, anything else differs | **STOP** "changed under an unchanged key (the fields)" |
| key unchanged, but an input the key covers moved (a part set's drawing or SMILES, a pair's first drawing or either SMILES, a drawing's SMILES) | **STOP** "kept under an unchanged key although ... moved" |
| a pair marked on the second molecule's SHIPPED drawing (`mode: shipped` with `b_layer`: isotretinoin vs tretinoin) whose second drawing moved while the pair's key held (the key does not cover it) | **STOP**; bump `PAIRS_RECIPE` to make it again |
| new molecule, new pair, a repeat unit added in its seed | allowed, listed "new" |
| key moved with a named input: the recipe version, a SMILES, the drawing it rests on (itself checked by its own key) | allowed, listed "remade"/"redrawn" with the reason |
| key moved and only a seed's WORDS differ (a caption; a part's label, sentence or `from`; a repeat unit's label), every drawn byte as shipped | allowed, listed "only its words ... changed" |
| key moved with none of the above moving (the parts key holds which atoms the patterns match, and a remade layer comes from reading the drawing on that machine) | **STOP** "remade with its recipe, SMILES and drawing unchanged (what differs)" |
| a molecule or pair that left the catalog | listed "removed" |

**The one release valve:** `MFETL_DRAWING_SEEDS_CHANGED=1` on a build on the Mac that carries a
deliberate change to a drawing seed's PATTERNS (a SMARTS rule in `structure_parts.yaml`, a pair's
`shipped:` or `stereo:` entry, a repeat unit's linkage pattern), committed with its data. It allows only
the last STOP row, and lists each entry with the flag. It never excuses a change under an unchanged
key. The weekly workflow never sets it (a test holds that), so on Monday such a seed committed without
its data stops the run. 5B's rule changes would have needed it; a words-only change does not.

**What a stop looks like.** The `mfetl all` step fails with `DrawingChanged: refusing to export: N
drawing(s) changed with nothing to explain it.` and one line per entry; the log has `drawing STOPPED:
<slug> (structure parts|compare drawing|structure drawing|repeat unit): <why>`; on GitHub each is an
`::error` annotation and the run's summary page opens its Drawings section with **STOPPED (N)** and the
entries. Nothing is loaded into Supabase and nothing is written; the failed-run heartbeat resets the
tree; the `alarm` job opens (or comments on) the refresh-failure issue with the Drawings block in its
body; no data PR is opened, so the live site keeps last week's data.

**What to do on a stop.** Do not re-run the job (it would stop again) and do not set the flag in the
workflow. Compare the entries named with the shipped snapshot: a STOP on Monday with no seed change is
this machine computing a key or a layer differently (the platform); fix the recipe on a branch so the
key no longer depends on it, restore the shipped entries, and deploy on Garrett's word. A seed changed
without its data: build on the Mac with the flag, commit the data, push.

**Where the counts are.** The run's summary page (the `run` job), section "Drawings": four lines, then
every drawing made or remade with its reason (or "none"). The same block, as plain text, in the
`all-clear` job's summary, the `alarm` job's summary, the alarm issue's body and its "Failed again"
comment (`Count drawings` step, from `$MFETL_DRAWINGS_REPORT` under `runner.temp`, never committed).
The parts and pairs lines are the recipes' own log lines character for character (a test holds that);
the structure drawings line is new, and the repeat units line now counts carried and repainted.

**Monday 2026-11-16's summary page must show exactly:**

- `structure drawings: 896 carried, 0 repainted, 0 drawn, 19 with no drawing`
- `structure parts: 718 carried, 0 made, 193 with no part, 4 drawings unreadable`
- `compare drawings: 147 pairs (aligned 44, aligned+highlight 30, shipped 72, shipped+highlight 1); 147 carried, 0 repainted, 0 made`
- `repeat units: 2 (2 carried, 0 repainted, 0 drawn this run)`
- **Made or remade this run: none.**

(A new molecule or pair that week adds its own lines, each named "new".) The step log keeps the
recipes' lines as before, `repeat units: 2 (0 drawn this run)` included.

**Proved on the real build (2026-11-13, pinned f69fd345c58bfa08, keys blanked).** (1) `mfetl all` with
caffeine's methyl-groups layer and caffeine vs theobromine's second drawing each moved 1 px right after
their recipes made them, keys untouched: exit 1, `caffeine (structure parts): changed under an
unchanged key (parts[methyl-groups].layer)` and `caffeine-vs-theobromine (compare drawing): changed
under an unchanged key (b_svg)`, the summary page and report as above, `data/snapshots` byte for byte
unchanged. (2) The Linux shape: the shipped key of caffeine's parts and of that pair changed in the
snapshot files, then the plain `mfetl all`: the run made both again on this Mac and stopped, each
"remade with its recipe, SMILES and drawing unchanged (only the key moved)", writing nothing; the two
files restored, a third build byte-identical to the first two.

## 11. Display structures (phase 3A, 2026-11-14)

A record's identifiers are PubChem's record of the substance. For a sugar that record is the open chain, while in water
the sugar is a ring and the site's text describes the ring. `sources/seeds/structure_display.yaml` gives the SMILES the
drawing is drawn from (`structures.drawn_smiles(rec)`: the display SMILES, else `isomeric_smiles`). Every recipe reads it:
the structure drawing's key (`svg_key`), the parts (`parts_key`, `reading_for`, `find_parts`), the pairs (`pair_key`,
`draw_pair`, `caption_rule`, the repaint) and the drawing guard, which names a change as "its display structure changed
(structure_display.yaml: drawn as ...)" and allows it like any SMILES change. Nothing else on the record moves (formula,
weight, InChI, descriptors and categories stay PubChem's).

**The proof, at every build** (`assemble.structure_display_for`): the ring has the record's formula, and opened at its
anomeric carbon (`structures.ring_opened`: the ring carbon bearing the ring oxygen and an OH) it is the record's own SMILES,
every stereocentre included; it refuses the C3 epimer and the mirror image. An entry also names `model_cid`, the PubChem
record whose 3D conformer the page shows (the web's `modelCid`), so the 3D is never the open chain.

**Today:** fructose (D-fructofuranose, model beta-D-fructofuranose 439709) and allulose (D-psicofuranose, model
alpha-D-psicofuranose 21581131). Their parts became hydroxyl, hemiacetal and ring system; erythritol vs allulose is
shipped with nothing marked (its caption left the seed), sucrose vs fructose aligned, glucose vs fructose shipped.
**After the deploy, Monday's lines:** `structure drawings: 896 carried, 0 repainted, 0 drawn, 19 with no drawing`;
`structure parts: 718 carried, 0 made, 193 with no part, 4 drawings unreadable`; `compare drawings: 147 pairs (aligned 45,
aligned+highlight 29, shipped 72, shipped+highlight 1); 147 carried, 0 repainted, 0 made`; `repeat units: 2 (2 carried, 0
repainted, 0 drawn this run)`; made or remade: none.

**To add one:** an entry with `smiles` (PubChem's ring form), `form`, `cid`, `model_cid`, `model_form`, `model_line`,
`has_3d`, `line` and `basis` (which ring and why); build on the Mac and commit the data with it (the guard lists the
molecule and its pairs as remade).

## 12. A repeat unit in place of a PubChem drawing, with an added group (phase 3B, 2026-11-14)

Garrett's ruling of 2026-11-14 (on the phase 3A review, (b)): carboxymethyl cellulose is drawn as its repeat unit. Its
PubChem record, CID 24748, is two small molecules (open-chain glucose and acetic acid), so its shipped drawing was those two
fragments. Three seed fields in `repeat_units.yaml` make that possible, none of which moves starch's or cellulose's key:

- `replaces`: why the unit takes the place of the record's drawing. `drawings.clear_replaced_drawings` (in `stage_transform`,
  before the parts) sets the record's `structure_svg` and `structure_svg_key` to null, so it gets no parts and the page shows
  the unit. Without `replaces`, a record with a drawing still cannot have a repeat unit (the build stops).
- `group`, `group_smarts`, `group_light`, `groups`: an added group, matched by pattern (exactly `groups` times) and marked
  in the same amber layer as the linkage; the record carries `group` and `group_atoms`.
- `line`: one sentence the page prints under the unit (house rules and the claim rule apply, kind `part`).

The unit is cellulose's two beta-D-glucose units with -CH2-COOH on one unit's C6 oxygen; with the group taken off it is
cellulose's unit, stereo included (`tests/test_phase3b.py`). The drawing guard lists the change as
`carboxymethyl-cellulose (structure drawing): removed, replaced by its repeat unit (repeat_units.yaml `replaces`), a
deliberate remake`, `(structure parts): dropped, its drawing was replaced by its repeat unit`, `(repeat unit): new`.
`line` and `replaces` are seed words: changing only them later is a words-only change.

**After the deploy, Monday's lines:** `structure drawings: 901 carried, 0 repainted, 0 drawn, 25 with no drawing`;
`structure parts: 721 carried, 0 made, 201 with no part, 4 drawings unreadable`; `compare drawings: 147 pairs (aligned 45,
aligned+highlight 29, shipped 72, shipped+highlight 1); 147 carried, 0 repainted, 0 made`; `repeat units: 3 (3 carried, 0
repainted, 0 drawn this run)`; made or remade: none.

## 13. A lattice drawn with nothing, and a repeat unit that replaces the record's structure (the 2026-12-care tranche, 2026-11-15)

**Titanium dioxide has no drawing.** It is an extended solid: in rutile and anatase every titanium sits among six
oxygens and every oxygen among three titaniums. PubChem's titanium dioxide (CID 26042) carries the SMILES `O=[Ti]=O`, and
the recipe would draw that as a lone molecule with two double bonds, a species known only as a gas. The FDA's code for
the substance (15FIX9V2JP) is filed under CID 162651, `[O-2].[O-2].[Ti+4]`, three loose ions, but that PubChem record's
title, CAS and Wikidata item are trititanium oxide's. Neither drawing is true of the white pigment, so the record names
itself in `sources/seeds/structure_none.yaml` (`line`, `basis`): `assemble.structure_none_for` gives it no
`structure_svg`, no key, no 3D, no computed descriptors (PubChem computes those from the same `O=[Ti]=O`), and so no parts, and the record carries `structure_none` {line, confidence, source}. The
web's "No single structure" panel prints "<title> is <line>". Its formula, weight and SMILES stay PubChem's (the formula
and weight are those of one formula unit). The `line` is checked by the claim rule (kind `part`, key `none.<slug>.line`).
A new record listed here is simply one more "with no drawing"; listing a record that has a shipped drawing would remove
it, and the guard lists that removal ("it no longer has a drawing"), so it is a reviewed change, never a silent one.
Silicon dioxide (`O=[Si]=O`) and zinc oxide (`O=[Zn]`), both lattices too, were live drawings then and were not touched.

**The extended-solids pass (2026-11-26, Garrett's ruling 2 on the 2026-12-care review):** silicon dioxide (a network
of SiO4 tetrahedra sharing every corner) and zinc oxide (wurtzite) joined titanium dioxide in `structure_none.yaml`.
The guard listed exactly two removals, `zinc-oxide (structure drawing): removed, it no longer has a drawing` and the
same for silicon dioxide; neither had a part layer, a /vs pair or a pair drawing, so nothing else moved. Silicon
dioxide also lost its 3D model (PubChem's conformer of O=Si=O); both lost their computed descriptors. Zinc oxide left
the molecule of the week (week 22, avobenzone in its place): the compiler takes only a drawable molecule. The other
extended solids in the catalog (calcium and magnesium oxide, the carbides, the ionic salts) are surveyed on the web's
`docs/design/extended-solids-review-2026-11.html` and wait for Garrett's ruling; `tests/test_extended_solids.py` pins
`structure_none.yaml` to the three, so a new entry comes only with a ruling.

**The deploy's two amendments (2026-11-26):** the three no-structure pages show the conventional formula the panel
uses. `structure_none.yaml` takes an optional `formula` per entry (TiO2, SiO2, ZnO): an editorial display form of
PubChem's calculated formula (O2Ti, O2Si, OZn); the record's `molecular_formula`, the search index and the dataset keep
PubChem's, `structure_none` carries `formula`, and the build stops if the two do not hold the same atoms. The seed's
optional `drop_names` leaves a systematic name of the molecule that does not exist out of "Also called" (silicon
dioxide's "Dioxosilane"; `display_synonyms` and `wikidata_names` only, the record's `synonyms` still hold it).

**After the pass, the weekly run's lines:** `structure drawings: 901 carried, 0 repainted, 0 drawn, 28 with no
drawing`; parts, pairs and repeat units as below; made or remade: none.

**Carboxymethyl cellulose drops its record's structure** (Garrett's decision 5 on the phase 3B review). A record whose
repeat unit `replaces` its PubChem drawing (section 12) now also drops, at assembly (`assemble._replaced_by_unit`),
everything derived from that record's SMILES: formula, weight, both SMILES, InChI and InChIKey, the computed descriptors,
3D, the functional groups (Aldehydes, Alcohols, Carboxylic acids), the similarity edges (and so its place in eight other
molecules' neighbours) and the two weight boards. It keeps its CID, title, names, Wikidata item, curated line and its
repeat unit, and reads like cellulose (`macromolecule: true`). Its repeat unit's key does not move (its seed is
unchanged), so the guard carries it.

**After this tranche, the weekly run's lines:** `structure drawings: 903 carried, 0 repainted, 0 drawn, 26 with no
drawing`; `structure parts: 723 carried, 0 made, 202 with no part, 4 drawings unreadable`; `compare drawings: 147 pairs
(aligned 45, aligned+highlight 29, shipped 72, shipped+highlight 1); 147 carried, 0 repainted, 0 made`; `repeat units: 3
(3 carried, 0 repainted, 0 drawn this run)`; made or remade: none.

## 14. Metal bonds, four more lattices and simeticone (the wrong-drawings pass, 2026-11-26)

Garrett's word on decisions (2) and (5) of the extended-solids review. Brief `../EXTENDED-SOLIDS-2-PROMPT.md`. Built on
branch `wrong-drawings-2026-11`; every change is one the drawing guard LISTS.

**Four more lattices** (`structure_none.yaml`): calcium oxide and magnesium oxide (rock salt), silicon carbide (a
network like diamond's; it also loses PubChem's 3D model of the false [C-]#[Si+]) and tungsten carbide (hexagonal),
with `formula` SiC and WC where PubChem writes CSi and CW, and `drop_names` for tungsten carbide's two
"methanidylidyne" names (not on its line today; its line is empty).

**Simeticone** (`repeat_units.yaml`, `replaces`): two dimethylsiloxane units, `*[Si](C)(C)O[Si](C)(C)O*`, the
siloxane linkage marked, in place of PubChem's CID 6433516 (a short siloxane plus a lone O=Si=O). As for carboxymethyl
cellulose (section 13) the record drops everything derived from that structure, so it leaves the biggest and lightest
boards (904 to 903 each) and its formula leaves the index. The guard names it "removed, replaced by its repeat unit"
(it named a unit whose record had also lost its SMILES "its SMILES is gone" before; the order is fixed).

**Metal bonds** (`structure_display.yaml`, a second kind of entry, `metal_bonds:`). PubChem's one-line structure keeps
a metal apart from the atoms it bonds, so the recipe drew the metal floating. An entry gives the SMILES the drawing is
drawn from, read through `structures.drawn_smiles` like a sugar's ring, so the key, the parts and the guard all follow
it; the record's identifiers stay PubChem's. Checked at every build (`assemble.metal_bonds_for` ->
`structures.metal_bonds_problems`): the record's formula and charge; the metal bonded to exactly the atoms `bonded`
names (a pattern's first atom); the record's own metal bonds kept; deleting the metal's bonds gives back the record's
own pieces (atoms, bonds, hydrogens, stereo), charges moved only as `charges` lists them. One bond rule for all: a
partner charged negative in PubChem's record shares a plain bond with the metal (the charges pair off); a neutral
partner gives a dative bond, which RDKit draws as an arrow. No 3D model (`has_3d: false`).

**Layouts in the SMILES.** RDKit does not treat a bond to a metal as a ring bond, so its own layout drew cisplatin
trans and crushed the chelate rings and the chlorin. Cisplatin, chromium(III) picolinate and chlorophyll a carry their
coordinates as CXSMILES (`... |(x,y,;...)|`): `Chem.MolFromSmiles` keeps them as the conformer and `structures.draw`
draws from it, and `svg_key` covers the whole string, so a layout is as fixed as a SMILES and no machine lays it out
again. Cisplatin is a square (ammonia left, chlorides right; a test reads the corners from the SVG); chromium
picolinate three chelate rings at 120 degrees; chlorophyll a the live drawing's own layout (read from its SVG) with the
magnesium at the centre of its four nitrogens; sodium ferrocyanide (the deploy's amendment) iron in the middle, six
straight cyanides 60 degrees apart, the four sodium ions in a column to one side. Thiomersal (PubChem's own thimerosal
record, CID 16684434, verbatim) needs no coordinates. Ferrocyanide's line also says the 4- on the iron is the whole
ion's charge (the iron is iron(II)), and simeticone's "Also called" leaves out "Simethicon - USP CRS"
(`synonym_do_not_use.yaml`).

**Stopped, not drawn: the four cobalamins.** A flat drawing of a cobalamin must cross the corrin once (the nucleotide
loop runs from the corrin's side chain back to the cobalt). The best layout tried (the live corrin, cobalt at its
centre, cyanide in the cavity, the nucleotide moved outside the rim with one crossing) still drew a close-contact flag
at a ring-junction hydrogen and depended on rounding; and vitamin B12's and methylcobalamin's records carry no
stereocentres while cyanocobalamin's do, and the corrin's double-bond geometry cannot ride in a metal-bonded SMILES
(RDKit drops it in a ring under eight atoms). Each needs a ruling first (HISTORY, 2026-11-26).

**After the pass, the weekly run's lines:** `structure drawings: 896 carried, 0 repainted, 0 drawn, 33 with no
drawing`; `structure parts: 723 carried, 0 made, 202 with no part, 4 drawings unreadable`; `compare drawings: 147
pairs (aligned 45, aligned+highlight 29, shipped 72, shipped+highlight 1); 147 carried, 0 repainted, 0 made`; `repeat
units: 4 (4 carried, 0 repainted, 0 drawn this run)`; made or remade: none.

## 15. The cobalamins drawn with their cobalt bonded (the cobalamins pass, 2026-11-26)

Brief `../COBALAMINS-PROMPT.md` (Cowork's rulings). Built on branch `cobalamins-2026-11`; every change is one the
drawing guard LISTS: four redraws, "its display structure changed (structure_display.yaml metal_bonds: drawn with the
Co bonds)", and their twelve part layers remade (the same three parts on each, the same atoms lit: amide 28, phosphate
5, hydroxyl 4).

**One skeleton, one layout, four drawings.** `scripts/cobalamin_layout.py` (not run by the build) lays hydroxocobalamin
out once: the cobalt at the origin, the four nitrogens 2.0 from it (four equal Co-N bonds), each pyrroline a regular
pentagon pointing its nitrogen at the cobalt, the meso carbons on the bisectors, the ring A-ring D bond 1.5 long; the
bond to the benzimidazole due east, crossing the ring's edge once at the C14-C15 bond (the one crossing every flat
drawing of a cobalamin has); the top group due west inside the ring (its first atom 1.4 from the cobalt, a cyanide's
nitrogen 2.5); the nucleotide loop to the right, the linker on an arc above; every corrin substituent pinned outside
its ring; RDKit places the rest with all that locked, and a short relaxation (numpy) moves only the side chains and
the linker. Each of the four drawings is that skeleton itself (its atoms, its stereocentres, its coordinates) with the
record's OWN bond orders and charges (cyanocobalamin's record writes the corrin's double bonds and N- in other,
equivalent places) and the record's own top group in the same place. Coordinates to three decimals, in the SMILES.

**The check, extended** (`structures.metal_bonds_problems`, for every entry, at every build):
- (e) a double bond whose geometry the record gives may go unmarked in the drawing only inside a ring of eight atoms
  or fewer that the metal closes (`structures.metal_ring`, which counts dative bonds RDKit's ring perception leaves
  out), and only when the record's geometry is the one that ring forces. Double bonds are now compared one by one
  (cis or trans about the same neighbours), and a drawing may give no geometry the record does not.
- (d) a stereocentre the record leaves unspecified may be drawn only when the entry names `stereo_from` (and `top`, the
  pattern of the group on the metal) and the drawing's skeleton, top group removed, is the named entry's skeleton,
  stereo included (`structures.skeleton_key`: the bonds and charges of the rings the metal closes compared as one
  conjugated system, everything else exactly). Every centre the record does specify must be the drawing's.
Neither field reaches the record. Today: hydroxocobalamin the reference (14 carbon centres, all its own; RDKit also
flags the phosphorus, which no record specifies and none draws); cyanocobalamin 13 of its own, all agreeing with the
reference, plus the anomeric carbon from it; vitamin B12 and methylcobalamin all 14 from it.
**One labelled carbon (2026-11-27, `COBALAMINS-DEPLOY-PROMPT.md` amendment 1):** methylcobalamin's entry carries
`top_label: "H3C"`, so the methyl on the cobalt reads "H3C" (the 3 a subscript, as in "H2N") and not as a short bare stub.
The build (`assemble.metal_bonds_for` -> `structures.labelled_top`) finds the atom by the entry's `top`, checks that the
label is that atom and its hydrogens, and writes it into the drawn SMILES as a CXSMILES `$...$` atom label
(`H<sub>3</sub>C`); the drawing engine and `RECIPE_VERSION` are untouched, and the other three entries and every other
shipped drawing carry no label and did not move.

**The layout test** (`tests/test_cobalamins.py`) reads the shipped SVG itself (`read_positions` from the SVG alone,
proven by a redraw): nothing closer than 0.65 bond lengths between atoms not bonded, or 0.40 between an atom and a bond
it is not part of; no label over a bond or a label; no carbon drawn with a label except methylcobalamin's one (a straight run); no close-contact
flag; exactly one crossing, the cobalt-benzimidazole bond over C14-C15. In screen pixels at the drawing's own 400 px,
at the molecule page's desktop size (464 x 348) and at its phone size (272 x 204, the 220 px stage below 720 px).

**After the pass, the weekly run's lines** are those of section 14 (896 / 723 / 147 / 4 carried, 33 with no drawing);
made or remade: none.

## Seeing a layer

`drawings.compose(record["structure_svg"], part["layer"])` returns the drawing with the part under
it. To look at one on this Mac, put a `<rect fill='#0e2233'>` after the header, write the SVG to a
file, and run `qlmanage -t -s 600 -o <dir> <file>.svg` (macOS Quick Look renders SVG to PNG; headless
Brave's `--screenshot` hangs on this Mac).
