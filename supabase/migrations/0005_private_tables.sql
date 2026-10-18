-- Close the public-key read on the two private tables (Garrett, 2026-10-18).
--
-- 0003 granted SELECT on every table in `public` to anon and authenticated, and neither `event`
-- (the /api/e beacon: paths, referrers, session ids) nor `ingest_run` (the ETL's audit trail) has
-- row level security, so anyone holding the project's public (anon) key could read both through
-- the Data API. Only the service role uses them: /api/e inserts and /dashboard reads with the
-- service key, and the ETL writes ingest_run with it. 0004 already left them out of its anon grant.
-- Idempotent: revoking a privilege that is not held is a no-op.
--
-- tests/test_migration_grants.py fails if a later migration makes either table readable by anon or
-- authenticated again, and the local check in moleculefinder-etl/CLAUDE.md proved it end to end.
revoke all on table event, ingest_run from anon, authenticated;
revoke all on sequence event_id_seq, ingest_run_id_seq from anon, authenticated;
