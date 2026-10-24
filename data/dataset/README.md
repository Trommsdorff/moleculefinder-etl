# MoleculeFinder: the molecules in everyday foods, drinks and products

The molecules in everyday foods, drinks and products, with their structures, properties and the products that list them, from
[MoleculeFinder](https://moleculefinder.com). Released under **CC0 1.0** (public domain dedication): use it for
anything, no permission or credit needed. A citation is welcome (below).

| | |
|---|---|
| **Version** | 2026.10.1 |
| **Snapshot** | MoleculeFinder data of 2026-10-21 |
| **Molecules** | 915 |
| **Products** | 405 |
| **Licence** | CC0 1.0 (`LICENSE.txt`) |
| **Website** | https://moleculefinder.com |

## Files

| file | rows | what it holds |
|---|---:|---|
| `molecules.csv` | 915 | one row per molecule |
| `products.csv` | 405 | one row per food, drink, product or class page |
| `product_molecules.csv` | 2,367 | which molecules each product lists |
| `categories.csv` | 167 | MoleculeFinder's groups, families, food and product hubs, functional groups |
| `molecule_categories.csv` | 5,066 | which molecules each category holds |
| `relationships.csv` | 16 | curated molecule-to-molecule links (becomes, affects) |
| `similarity.csv` | 3,302 | structural neighbours (Tanimoto, Morgan fingerprints) |
| `worlds.csv` | 10 | the ten everyday worlds |
| `world_molecules.csv` | 60 | which molecules each world holds |
| `licences.csv` | 296 | the FDA marketing record for each approved medicine (Drugs@FDA) |
| `moleculefinder.json` | | every table above in one JSON file (`tables.<name>` is a list of rows) |
| `MANIFEST.json` | | row counts, file sizes and SHA-256 checksums |

CSV files are UTF-8 with a header row; an empty cell means no value. Lists inside a cell are
separated by ` | `. Every `*_slug` column joins to the `slug` of the table it names, and every
slug is a page on the site (https://moleculefinder.com/m/caffeine, https://moleculefinder.com/whats-in/coffee).

## Column dictionary and provenance

### `molecules.csv`

| column | type | description | source |
|---|---|---|---|
| `slug` | string | MoleculeFinder's identifier; the page is https://moleculefinder.com/m/<slug>. | MoleculeFinder |
| `name` | string | The name MoleculeFinder uses (its page title). | MoleculeFinder, from PubChem and Wikidata |
| `pubchem_cid` | integer | PubChem Compound ID. Blank for the 18 hand-modelled biopolymers and mixtures, which have no single PubChem compound. | PubChem |
| `wikidata_qid` | string | Wikidata item. | Wikidata (CC0) |
| `wikipedia_title` | string | English Wikipedia article title (the title only, no Wikipedia text). | Wikidata sitelink (CC0) |
| `molecular_formula` | string | Molecular formula (Hill order). | PubChem (computed) |
| `molecular_weight` | number | Molecular weight, g/mol. | PubChem (computed) |
| `canonical_smiles` | string | SMILES without stereochemistry (PubChem ConnectivitySMILES). | PubChem (computed) |
| `isomeric_smiles` | string | SMILES with stereochemistry. | PubChem (computed) |
| `inchi` | string | Standard InChI. | PubChem (computed) |
| `inchikey` | string | Standard InChIKey. | PubChem (computed) |
| `xlogp` | number | XLogP3 partition coefficient. | PubChem (computed) |
| `tpsa` | number | Topological polar surface area, square angstroms. | PubChem (computed) |
| `h_bond_donors` | integer | Hydrogen bond donor count. | PubChem (computed) |
| `h_bond_acceptors` | integer | Hydrogen bond acceptor count. | PubChem (computed) |
| `rotatable_bonds` | integer | Rotatable bond count. | PubChem (computed) |
| `complexity` | number | Bertz/Hendrickson complexity. | PubChem (computed) |
| `formal_charge` | integer | Formal charge. | PubChem (computed) |
| `wikidata_description` | string | Wikidata's short English description. | Wikidata (CC0) |
| `other_names` | string | Up to four other names, the Wikidata label then aliases, separated by ' | '. | Wikidata (CC0), filtered by MoleculeFinder |
| `brand_names` | string | Curated brand names, separated by ' | '. | MoleculeFinder curated |
| `description` | string | MoleculeFinder's one-line description of the molecule (the page's own). | MoleculeFinder curated (CC0 in this dataset) |
| `why_it_matters` | string | MoleculeFinder's curated line on why the molecule matters in everyday life. | MoleculeFinder curated (CC0 in this dataset) |
| `group` | string | MoleculeFinder's everyday group (food-flavor, sweetener, prescription-medicine...). | MoleculeFinder curated |
| `family` | string | Chemical or drug family (alkaloid, ssri, terpenoid...). | MoleculeFinder curated |
| `is_otc` | boolean | Sold over the counter in the US (MoleculeFinder's allowlist). | MoleculeFinder curated |
| `dual_use` | boolean | Also has a common use outside medicine or food. | MoleculeFinder curated |
| `macromolecule` | boolean | A biopolymer or mixture with no single structure drawing. | MoleculeFinder |
| `ld50_mg_per_kg` | number | The molecule page's one LD50 (oral rat, then oral mouse, then any oral, then any route), mg/kg. An animal study measurement, not a dose for a person. Blank when no US government source reports it (see ld50_sources). | US government sources via PubChem |
| `ld50_species` | string | Species of that LD50. | US government sources via PubChem |
| `ld50_route` | string | Route of that LD50 (oral, dermal, inhalation, iv, other). | US government sources via PubChem |
| `ld50_sources` | string | The US government sources reporting that LD50, separated by ' | '. | PubChem PUG-View references |
| `half_life_hours` | number | Elimination half-life in people, hours (8 molecules). | MoleculeFinder curated |
| `relative_sweetness` | number | Sweetness relative to sucrose = 1. | MoleculeFinder curated |
| `scoville_shu` | number | Pungency of the pure compound, Scoville heat units. | MoleculeFinder curated |
| `odor_threshold_ng_m3` | number | Odor detection threshold, ng per cubic metre of air. | MoleculeFinder curated |
| `pageviews_monthly` | integer | English Wikipedia page views per month, the demand signal MoleculeFinder ranks by. | Wikimedia Pageviews (CC0) |
| `catalog_batch` | string | The tranche that added the molecule (blank: the original everyday core). | MoleculeFinder |
| `url` | string | The molecule's MoleculeFinder page. | MoleculeFinder |

### `products.csv`

| column | type | description | source |
|---|---|---|---|
| `slug` | string | MoleculeFinder's identifier; the page is https://moleculefinder.com/whats-in/<slug>. | MoleculeFinder |
| `name` | string | Product, food or drink name, used only to name it. | DailyMed label, Wikidata or MoleculeFinder |
| `kind` | string | food, drink, medicine, cosmetic, household, chemistry (a class such as PFAS) or moment (an everyday world). | MoleculeFinder |
| `source_type` | string | Where the ingredient list comes from: dailymed, wikidata, world, curated or class. | MoleculeFinder |
| `source_id` | string | The DailyMed set id, Wikidata QID, world slug, curated hub or class slug. | DailyMed / Wikidata / MoleculeFinder |
| `source_url` | string | The label or item the list was read from. | DailyMed / Wikidata / MoleculeFinder |
| `also_from` | string | Further sources a food or drink combines, as type:id, separated by ' | '. | MoleculeFinder |
| `labeler` | string | The label's labeler (DailyMed products). | DailyMed (US public domain) |
| `document_type` | string | The label's document type (DailyMed products). | DailyMed (US public domain) |
| `label_effective` | string | The label version's effective date, YYYYMMDD (DailyMed products). | DailyMed (US public domain) |
| `ingredients_listed` | integer | Ingredients the source lists. | DailyMed / Wikidata / MoleculeFinder |
| `molecules_in_dataset` | integer | Of those, the molecules in this dataset (rows in product_molecules.csv). | MoleculeFinder |
| `url` | string | The product's MoleculeFinder page. | MoleculeFinder |

### `product_molecules.csv`

| column | type | description | source |
|---|---|---|---|
| `product_slug` | string | products.slug | MoleculeFinder |
| `molecule_slug` | string | molecules.slug | MoleculeFinder |
| `role` | string | active, inactive (label ingredients), part (Wikidata), curated, world or class. | DailyMed / Wikidata / MoleculeFinder |
| `listed_as` | string | The ingredient's name on the label, where it differs in form (sertraline hydrochloride). | DailyMed (US public domain) |
| `purpose` | string | The label's own purpose line for an active ingredient. | DailyMed (US public domain) |
| `matched_by` | string | How the ingredient was matched to the molecule: unii, moiety, parent, skeleton or alias (labels); qid, curated, world or class otherwise. Never by name. | MoleculeFinder |

### `categories.csv`

| column | type | description | source |
|---|---|---|---|
| `slug` | string | MoleculeFinder's identifier; the hub is https://moleculefinder.com/in/<slug>. | MoleculeFinder |
| `name` | string | Category name. | MoleculeFinder |
| `kind` | string | bucket, family, food, product, use, type, functional_group (RDKit SMARTS), element or size. | MoleculeFinder (curated, or computed from PubChem and RDKit) |
| `molecules` | integer | Members (rows in molecule_categories.csv). | MoleculeFinder |

### `molecule_categories.csv`

| column | type | description | source |
|---|---|---|---|
| `molecule_slug` | string | molecules.slug | MoleculeFinder |
| `category_slug` | string | categories.slug | MoleculeFinder |
| `note` | string | The curated note, where there is one (caffeine in coffee: ~95 mg per 8 oz cup). | MoleculeFinder curated |

### `relationships.csv`

| column | type | description | source |
|---|---|---|---|
| `from_slug` | string | molecules.slug | MoleculeFinder curated |
| `relation` | string | becomes (a metabolite or product) or affects (acts on). | MoleculeFinder curated |
| `to_slug` | string | molecules.slug | MoleculeFinder curated |
| `note` | string | What the relation is (major metabolite, receptor antagonist). | MoleculeFinder curated |
| `confidence` | string | from_source or inferred, as the site labels it. | MoleculeFinder curated |

### `similarity.csv`

| column | type | description | source |
|---|---|---|---|
| `molecule_slug` | string | molecules.slug | MoleculeFinder |
| `neighbor_slug` | string | molecules.slug of a structural neighbour. | MoleculeFinder |
| `tanimoto` | number | Tanimoto similarity of Morgan fingerprints (radius 2, 2048 bits). | Computed with RDKit from PubChem SMILES |

### `worlds.csv`

| column | type | description | source |
|---|---|---|---|
| `slug` | string | MoleculeFinder's identifier; the page is https://moleculefinder.com/roam/<slug>. | MoleculeFinder |
| `title` | string | The everyday world (Morning coffee, After the rain...). | MoleculeFinder curated |
| `blurb` | string | One line about it. | MoleculeFinder curated (CC0 in this dataset) |

### `world_molecules.csv`

| column | type | description | source |
|---|---|---|---|
| `world_slug` | string | worlds.slug | MoleculeFinder curated |
| `molecule_slug` | string | molecules.slug | MoleculeFinder curated |

### `licences.csv`

| column | type | description | source |
|---|---|---|---|
| `molecule_slug` | string | molecules.slug | MoleculeFinder |
| `regulator` | string | US Food and Drug Administration. | Drugs@FDA (US public domain) |
| `application` | string | The application (NDA, ANDA or BLA number). | Drugs@FDA (US public domain) |
| `product` | string | A product marketed under it. | Drugs@FDA (US public domain) |
| `authorised` | string | Original approval date, YYYY-MM-DD. | Drugs@FDA (US public domain) |
| `holder` | string | The application holder. | Drugs@FDA (US public domain) |
| `combination_only` | boolean | Marketed only in combination with another active ingredient. | Drugs@FDA (US public domain) |
| `source_url` | string | The application's Drugs@FDA page. | Drugs@FDA (US public domain) |

## Sources

| source | what it supplies | status |
|---|---|---|
| PubChem (NCBI, US National Library of Medicine) | identity and computed properties (formula, weight, SMILES, InChI, descriptors) | US government computations, public domain |
| US government toxicology sources, read through PubChem (HSDB, ChemIDplus, the EPA, the FDA, NIOSH, NTP, ATSDR, USGS, USDA) | the LD50 values kept | public domain (17 U.S.C. 105) |
| Wikidata | items, descriptions, other names | CC0 |
| Wikimedia Pageviews | monthly page views | CC0 |
| DailyMed (US National Library of Medicine) | product labels: ingredients, roles, purposes | public domain |
| Drugs@FDA | FDA approval records | public domain |
| RDKit | similarity fingerprints, functional groups | BSD software; the outputs are facts |
| MoleculeFinder (137 Finder LLC) | descriptions, groups, hubs, product lists, worlds, relationships | released CC0 1.0 in this dataset |

## What is not in the dataset, and why

The dataset is CC0, so it carries only fields whose sources are public domain or CC0. Where a
source asks for attribution, restricts reuse, or its terms could not be confirmed, the field is
left out, even though MoleculeFinder's pages show it with the source named.

- **GHS hazard classification** (signal word, pictograms, H-statements; on 645 molecules on the
  site) and the 10 hazard categories built from it (acutely-toxic, compressed-gas, corrosive, environmental-hazard, flammable, ghs-danger, ghs-warning, health-hazard, irritant, oxidizing). PubChem
  aggregates it from the European Chemicals Agency's C&L Inventory and EUR-Lex (reuse with the source
  acknowledged) and Safe Work Australia (CC BY 4.0); the site shows it with that attribution, which a
  CC0 release cannot carry. Japan's NITE classifications are used nowhere (NITE reserves publication).
- **LD50 values from sources that are not US government works.** None is withheld: since
  2026-10-23 MoleculeFinder shows an LD50 only from a source whose terms allow it, and every LD50
  on the site is a US government value, so the dataset's LD50 columns match the site's. Every
  LD50 kept names its sources.
- **29 licence records** from the MHRA (Open Government Licence, attribution), the
  European Medicines Agency (reproduction with the source acknowledged) and national registers
  (Italy's AIFA, Latvia's medicines agency). Drugs@FDA records are kept.
- **CAS Registry Numbers.** The CAS Registry is maintained by the American Chemical Society, which
  requires a licence to publish its numbers; since 2026-10-23 neither the site nor the dataset
  carries them. Each row carries the PubChem CID, InChIKey and Wikidata QID instead.
- **PubChem synonyms.** Depositors supply them under their own terms; the dataset's names come from
  Wikidata (`other_names`) and MoleculeFinder's curated brand list.
- **Serving sizes**, a dosing figure, which MoleculeFinder keeps out of anything it publishes as data.
- **Prose that is not a structured field**: the written comparisons, the short answers, and the
  structure drawings (SMILES and InChI carry the structure).

## Notes

- An LD50 is an animal study measurement, not a dose for a person. Nothing here is medical advice.
- Product names are used only to name the products. Ingredient lists are the labels' own; a
  product lists only the ingredients that are MoleculeFinder molecules (`ingredients_listed` is
  the label's full count).
- Ingredients are matched to molecules by code (a label's UNII, its active moiety, PubChem's parent
  compound for a salt or hydrate, a Wikidata QID), never by name.

## Citation

MoleculeFinder (137 Finder LLC) (2026). *MoleculeFinder: the molecules in everyday foods, drinks and products* (Version 2026.10.1) [Data set]. Zenodo. https://doi.org/10.5281/zenodo.23605767

- Every version (always the latest): https://doi.org/10.5281/zenodo.23605767
- Version 2026.10: https://doi.org/10.5281/zenodo.23605768
- Zenodo: https://zenodo.org/records/23605768
- Kaggle: https://www.kaggle.com/datasets/trommsdorff/moleculefinder-molecules-in-everyday-products
- Website: https://moleculefinder.com/about/methodology

## Rebuilding

`mfetl dataset` in the MoleculeFinder ETL rebuilds this folder from the site's snapshot, checks
every table's row count against it, and writes the checksums in `MANIFEST.json`.
