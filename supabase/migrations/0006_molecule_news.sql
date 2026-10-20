-- molecule_news: the catalogue's molecules named in recent headlines (Run A, 2026-10-20).
--
-- WHO WRITES IT: .github/workflows/news.yml every six hours (moleculefinder_etl/news.py), through
-- PostgREST with the service key: one upsert per matched molecule, and rows deleted 21 days after
-- their last headline. WHO READS IT: the same job, to build public-data/news/in-the-news.json,
-- which the static site fetches in the browser. The site never queries this table.
--
-- NAMES ONLY. Slug, name, when it was first and last seen, and how many headlines named it. No
-- headline text, no outlet, no link: not on the site, not in the feed, and not here either.
--
-- An ephemeral 21-day signal, not catalogue data: no foreign key to molecule, so no catalogue
-- change can trip over a row (the job only ever writes slugs from the committed snapshot).
--
-- Grants in this same file (standing order 17; tests/test_migration_grants.py). Idempotent.

create table if not exists molecule_news (
  slug        text        primary key,              -- /m/<slug>
  name        text        not null,                 -- the molecule's title
  first_seen  timestamptz not null,                 -- earliest matching headline still retained
  last_seen   timestamptz not null,                 -- most recent matching headline
  hits        integer     not null check (hits >= 1),   -- distinct headlines in the run's 7-day window
  updated_at  timestamptz not null default now(),   -- when the job last wrote the row
  check (first_seen <= last_seen)
);
create index if not exists molecule_news_last_seen_idx on molecule_news (last_seen desc);

grant select on table molecule_news to anon;
grant select, insert, update, delete on table molecule_news to service_role;

-- Anyone may read (the same facts are in the public feed); nobody but the service role writes.
alter table molecule_news enable row level security;
drop policy if exists "public read molecule_news" on molecule_news;
create policy "public read molecule_news" on molecule_news for select using (true);

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
