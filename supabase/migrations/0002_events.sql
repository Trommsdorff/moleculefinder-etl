-- Distribution-measurement event sink (ships in M0).
-- The web app's /api/e beacon writes here via the service role.
create table if not exists event (
  id          bigserial primary key,
  ts          timestamptz not null default now(),
  name        text not null,              -- 'share' | 'hook_interaction' | 'pageview'
  page_type   text,                       -- 'molecule'|'leaderboard'|'category'|'home'|'about'
  path        text,
  referrer_kind text,                     -- 'organic'|'direct'|'social'|'internal'
  session_id  text,
  meta        jsonb
);
create index if not exists event_ts_idx        on event (ts desc);
create index if not exists event_type_idx      on event (page_type, name);
create index if not exists event_referrer_idx  on event (referrer_kind);
