-- Explicit Data API grants, table by table (standing order 17, 2026-10-18).
--
-- Supabase stops auto-granting Data API access to NEW tables in `public` on 2026-10-30.
-- Existing tables keep what they have, but this schema's only grants were 0003's blanket
-- `on all tables in schema public` plus `alter default privileges`, which name no table.
-- From here every table carries its grants by name, and every future migration that
-- creates a table grants it in the same file (tests/test_migration_grants.py fails
-- otherwise). Idempotent: a GRANT that is already held is a no-op, so this is safe to
-- apply to the live database and safe to apply twice.
--
-- anon reads the public catalog tables (RLS on the seven that have it still limits rows).
-- `event` (the /api/e beacon: paths, referrers, session ids) and `ingest_run` (the ETL's
-- audit trail) are NOT granted to anon here: only the service role reads or writes them.
-- 0003's blanket grant still gave anon SELECT on both; 0005_private_tables.sql revokes it.

-- ── Public catalog: anon reads, service role writes ─────────────────────────
grant select on table
  source, molecule, identifier, synonym, descriptor, property, toxicity_value,
  ghs_classification, category, molecule_category, similarity_edge,
  leaderboard, leaderboard_entry, hook, content_block
  to anon;

grant select, insert, update, delete on table
  source, molecule, identifier, synonym, descriptor, property, toxicity_value,
  ghs_classification, category, molecule_category, similarity_edge,
  leaderboard, leaderboard_entry, hook, content_block
  to service_role;

-- ── Service role only ───────────────────────────────────────────────────────
grant select, insert, update, delete on table event, ingest_run to service_role;

-- ── The bigserial sequences behind the service role's inserts ───────────────
grant usage, select on sequence
  source_id_seq, molecule_id_seq, identifier_id_seq, synonym_id_seq, property_id_seq,
  toxicity_value_id_seq, category_id_seq, leaderboard_id_seq, hook_id_seq,
  content_block_id_seq, ingest_run_id_seq, event_id_seq
  to service_role;
