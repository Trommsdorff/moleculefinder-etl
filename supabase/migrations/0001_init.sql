-- ── Extensions ─────────────────────────────────────────────────────────────
create extension if not exists pg_trgm;      -- fuzzy name search
create extension if not exists vector;        -- optional: semantic search later

-- ── Enums ──────────────────────────────────────────────────────────────────
create type mol_tier   as enum ('marquee', 'canon');
create type confidence as enum ('from_source', 'computed', 'inferred');
create type hook_type  as enum (
  'still_in_system', 'dose_poison', 'bac', 'scoville',
  'sweetness', 'smell_card', 'structure', 'similar'
);
create type tox_route  as enum ('oral', 'dermal', 'inhalation', 'iv', 'other');

-- ── Provenance registry ────────────────────────────────────────────────────
create table source (
  id                 bigserial primary key,
  key                text not null unique,        -- 'pubchem', 'wikidata', 'rdkit', 'curated'
  name               text not null,
  license            text not null,               -- 'Public Domain', 'CC0', 'BSD', 'curated'
  license_url        text,
  homepage           text,
  commercial_ok      boolean not null default true,
  attribution_required boolean not null default false
);

-- ── Core entity ────────────────────────────────────────────────────────────
create table molecule (
  id                 bigserial primary key,
  cid                bigint unique,               -- PubChem CID (natural key)
  slug               text not null unique,        -- URL slug, e.g. 'caffeine'
  title              text not null,               -- display name
  preferred_name     text,
  iupac_name         text,
  molecular_formula  text,
  molecular_weight   numeric(12,4),
  canonical_smiles   text,
  isomeric_smiles    text,
  inchi              text,
  inchikey           char(27),
  tier               mol_tier not null default 'canon',
  summary            text,                        -- CC0 Wikidata description ONLY
  summary_source_id  bigint references source(id),
  wikidata_qid       text,
  wikipedia_title    text,
  pageviews_monthly  integer default 0,           -- demand proxy / popularity
  structure_svg      text,                        -- build-time RDKit 2D SVG (SEO/no-JS)
  search_tsv         tsvector,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
create index molecule_tier_idx        on molecule (tier);
create index molecule_popularity_idx  on molecule (pageviews_monthly desc);
create index molecule_inchikey_idx    on molecule (inchikey);
create index molecule_search_idx      on molecule using gin (search_tsv);

-- ── External identifiers (CAS, ChEMBL, ChEBI, KEGG, UNII, RxCUI, MeSH…) ──────
create table identifier (
  id            bigserial primary key,
  molecule_id   bigint not null references molecule(id) on delete cascade,
  scheme        text not null,                    -- 'cas','chembl','chebi','kegg',...
  value         text not null,
  source_id     bigint references source(id),
  unique (molecule_id, scheme, value)
);
create index identifier_lookup_idx on identifier (scheme, value);

-- ── Names / synonyms (drives search + display) ──────────────────────────────
create table synonym (
  id            bigserial primary key,
  molecule_id   bigint not null references molecule(id) on delete cascade,
  name          text not null,
  kind          text not null default 'common',   -- 'common','iupac','brand','systematic'
  is_primary    boolean not null default false,
  source_id     bigint references source(id)
);
create index synonym_name_trgm_idx on synonym using gin (name gin_trgm_ops);
create index synonym_mol_idx       on synonym (molecule_id);

-- ── Stable physicochemical descriptors (all from PubChem = from_source) ──────
create table descriptor (
  molecule_id       bigint primary key references molecule(id) on delete cascade,
  xlogp             numeric,
  tpsa              numeric,
  h_bond_donors     integer,
  h_bond_acceptors  integer,
  rotatable_bonds   integer,
  heavy_atoms       integer,
  complexity        numeric,
  formal_charge     integer,
  source_id         bigint references source(id)
);

-- ── Labeled properties (hook inputs & anything needing a trust chip) ─────────
create table property (
  id            bigserial primary key,
  molecule_id   bigint not null references molecule(id) on delete cascade,
  key           text not null,                    -- 'half_life_hours','relative_sweetness',
                                                   -- 'scoville_shu','bioavailability',...
  value_num     numeric,
  value_text    text,
  unit          text,
  confidence    confidence not null,
  source_id     bigint references source(id),
  source_url    text,
  as_of         date,
  unique (molecule_id, key)
);
create index property_key_idx on property (key);

-- ── Toxicity (LD50/LC50; can be multiple rows per molecule) ──────────────────
create table toxicity_value (
  id            bigserial primary key,
  molecule_id   bigint not null references molecule(id) on delete cascade,
  endpoint      text not null default 'LD50',     -- 'LD50','LC50',...
  value_num     numeric,
  unit          text default 'mg/kg',
  route         tox_route not null default 'oral',
  species       text,                             -- 'rat','mouse',...
  confidence    confidence not null default 'from_source',
  source_id     bigint references source(id),
  source_url    text
);
create index toxicity_mol_idx on toxicity_value (molecule_id);

-- ── GHS classification ──────────────────────────────────────────────────────
create table ghs_classification (
  molecule_id   bigint primary key references molecule(id) on delete cascade,
  signal_word   text,                             -- 'Danger','Warning'
  pictograms    text[],
  h_statements  jsonb,
  source_id     bigint references source(id)
);

-- ── Categories & memberships (roaming: foods, drug classes, groups) ──────────
create table category (
  id            bigserial primary key,
  slug          text not null unique,
  name          text not null,
  kind          text not null,                    -- 'food','drug_class','functional_group',
                                                   -- 'use','neurotransmitter','poison','element'
  description   text,                              -- CC0 / curated only
  source_id     bigint references source(id)
);
create table molecule_category (
  molecule_id   bigint not null references molecule(id) on delete cascade,
  category_id   bigint not null references category(id) on delete cascade,
  confidence    confidence not null default 'from_source',
  source_id     bigint references source(id),
  primary key (molecule_id, category_id)
);
create index molcat_by_category_idx on molecule_category (category_id);

-- ── Precomputed structural similarity (Morgan r2, 2048-bit, Tanimoto) ────────
create table similarity_edge (
  molecule_id   bigint not null references molecule(id) on delete cascade,
  neighbor_id   bigint not null references molecule(id) on delete cascade,
  tanimoto      numeric(5,4) not null,
  method        text not null default 'morgan_r2_2048',
  primary key (molecule_id, neighbor_id)
);
create index simedge_rank_idx on similarity_edge (molecule_id, tanimoto desc);

-- ── Leaderboards (materialized by ETL for determinism) ──────────────────────
create table leaderboard (
  id            bigserial primary key,
  slug          text not null unique,             -- 'deadliest','sweetest','hottest',...
  title         text not null,
  metric_key    text not null,                    -- which property/toxicity feeds it
  direction     text not null default 'desc',
  unit          text,
  description    text
);
create table leaderboard_entry (
  leaderboard_id bigint not null references leaderboard(id) on delete cascade,
  molecule_id    bigint not null references molecule(id) on delete cascade,
  rank           integer not null,
  value_num      numeric,
  primary key (leaderboard_id, molecule_id)
);
create index lbentry_rank_idx on leaderboard_entry (leaderboard_id, rank);

-- ── Which interactive hooks render on a page, + their parameters ─────────────
create table hook (
  id            bigserial primary key,
  molecule_id   bigint not null references molecule(id) on delete cascade,
  type          hook_type not null,
  enabled       boolean not null default true,
  params        jsonb,                            -- {half_life_hours:5, serving_mg:95,...}
  confidence    confidence not null,
  source_id     bigint references source(id),
  unique (molecule_id, type)
);
create index hook_mol_idx on hook (molecule_id);

-- ── Hand-authored editorial (marquee tier) ──────────────────────────────────
create table content_block (
  id            bigserial primary key,
  molecule_id   bigint not null references molecule(id) on delete cascade,
  block_type    text not null,                    -- 'everyday_hook','how_it_works','editorial'
  body_md       text not null,
  updated_at    timestamptz not null default now()
);
create index content_mol_idx on content_block (molecule_id);

-- ── ETL audit trail ─────────────────────────────────────────────────────────
create table ingest_run (
  id            bigserial primary key,
  git_sha       text,
  stage         text,
  status        text,                             -- 'ok','partial','failed'
  rows_upserted integer,
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  notes         text
);

-- ── Row-level security: public read-only, writes via service role only ───────
alter table molecule           enable row level security;
alter table synonym            enable row level security;
alter table property           enable row level security;
alter table toxicity_value     enable row level security;
alter table similarity_edge    enable row level security;
alter table leaderboard_entry  enable row level security;
alter table molecule_category  enable row level security;
-- (repeat for the remaining content tables)
create policy public_read on molecule          for select to anon using (true);
create policy public_read on synonym           for select to anon using (true);
create policy public_read on property          for select to anon using (true);
create policy public_read on toxicity_value    for select to anon using (true);
create policy public_read on similarity_edge   for select to anon using (true);
create policy public_read on leaderboard_entry for select to anon using (true);
create policy public_read on molecule_category for select to anon using (true);
