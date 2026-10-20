-- molecule_news + molecule_news_match: the catalogue's molecules named in recent headlines
-- (Run A, 2026-10-20; the audit table and the column-only public grant added the same day).
--
-- WHO WRITES THEM: .github/workflows/news.yml every six hours (moleculefinder_etl/news.py),
-- through PostgREST with the service key. WHO READS THEM: the same job, to rank the molecules
-- and build public-data/news/in-the-news.json, which the static site fetches in the browser.
-- The site never queries either table.
--
-- TWO TABLES, ONE PUBLIC FACE.
-- * molecule_news: one row per molecule, NAMES ONLY (slug, name, first and last seen, how many
--   headlines named it in the last seven days). The public (anon) key may read exactly those five
--   columns, nothing else: the same facts are in the public feed.
-- * molecule_news_match: one row per (molecule, headline), PRIVATE. The headline, the outlet, the
--   link and the query that found it, so a wrong match can be traced back to its headline. Only
--   the service role reads or writes it; the anon and authenticated keys get nothing (no grant,
--   and row level security with no policy). It also holds the history the ranking reads: a
--   molecule's count this week against its own weekly average over the four weeks before.
--   Rows are deleted 42 days after the headline's date.
--
-- 0003 set default privileges that grant SELECT on every new table to anon and authenticated,
-- so both tables REVOKE first and then grant exactly what they mean. Without the revoke the
-- column grant below would mean nothing (a table grant covers every column).
--
-- An ephemeral signal, not catalogue data: no foreign key to molecule, so no catalogue change can
-- trip over a row (the job only ever writes slugs from the committed snapshot).
--
-- Grants in this same file (standing order 17; tests/test_migration_grants.py). Idempotent.

create table if not exists molecule_news (
  slug        text        primary key,              -- /m/<slug>
  name        text        not null,                 -- the molecule's title
  first_seen  timestamptz not null,                 -- earliest matching headline still retained
  last_seen   timestamptz not null,                 -- most recent matching headline
  hits        integer     not null check (hits >= 1),   -- distinct headlines in the last 7 days
  updated_at  timestamptz not null default now(),   -- when the job last wrote the row
  check (first_seen <= last_seen)
);
create index if not exists molecule_news_last_seen_idx on molecule_news (last_seen desc);

create table if not exists molecule_news_match (
  slug          text        not null,             -- /m/<slug>
  story         text        not null,             -- the headline's identity: its text, normalised (copies count once)
  headline      text        not null,             -- the headline as matched (outlet suffix removed)
  outlet        text,                             -- the outlet Google News names
  url           text,                             -- the Google News link to the story
  query         text        not null,             -- the Google News query that found it
  published_at  timestamptz not null,             -- the headline's date
  found_at      timestamptz not null default now(),   -- the run that first matched it
  primary key (slug, story)
);
create index if not exists molecule_news_match_published_idx on molecule_news_match (published_at desc);

revoke all on table molecule_news from anon, authenticated;
grant select (slug, name, first_seen, last_seen, hits) on table molecule_news to anon;
grant select, insert, update, delete on table molecule_news to service_role;

revoke all on table molecule_news_match from anon, authenticated;
grant select, insert, update, delete on table molecule_news_match to service_role;

-- molecule_news: anyone may read its five public columns; nobody but the service role writes.
alter table molecule_news enable row level security;
drop policy if exists "public read molecule_news" on molecule_news;
create policy "public read molecule_news" on molecule_news for select using (true);

-- molecule_news_match: row level security on and NO policy, so even a grant added by mistake
-- would return no rows to any key but the service role (which bypasses RLS).
alter table molecule_news_match enable row level security;

-- The public bucket the feed lives in (public-data/news/in-the-news.json). Guarded so the file
-- still applies to a plain Postgres with no Supabase Storage schema (the local checks).
do $$
begin
  if to_regclass('storage.buckets') is not null then
    insert into storage.buckets (id, name, public)
    values ('public-data', 'public-data', true)
    on conflict (id) do update set public = true;
  end if;
end $$;

notify pgrst, 'reload schema';
