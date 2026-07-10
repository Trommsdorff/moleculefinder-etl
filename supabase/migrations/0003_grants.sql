-- Grant the Supabase API roles access to the public schema.
-- Supabase's SQL Editor applies these automatically on table creation; a schema
-- applied over a raw psql/psycopg connection needs them run explicitly.
grant usage on schema public to anon, authenticated, service_role;
grant all    on all tables    in schema public to service_role;
grant all    on all sequences in schema public to service_role;
grant select on all tables    in schema public to anon, authenticated;
grant usage, select on all sequences in schema public to anon, authenticated;
alter default privileges in schema public grant all    on tables    to service_role;
alter default privileges in schema public grant all    on sequences to service_role;
alter default privileges in schema public grant select on tables    to anon, authenticated;
