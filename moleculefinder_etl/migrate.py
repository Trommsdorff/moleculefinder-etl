"""`mfetl migrate`: apply supabase/migrations/*.sql to the live database, so nobody has to paste
SQL into the Supabase dashboard (Garrett, 2026-10-19).

The REST keys in .env cannot do this: the Data API reads and writes rows, it cannot GRANT, REVOKE
or CREATE. A migration needs a real Postgres connection, which is `SUPABASE_DB_URL` in .env (the
dashboard's Connect -> Session pooler string, password filled in). Gitignored like the keys.

`mfetl migrate` only lists what is pending. `mfetl migrate --apply` runs each pending file in its
own transaction together with its row in `mfetl.migration_log`, so a file is either applied and
recorded or not applied at all. The log lives in its own schema, which the Data API does not
expose, so neither key can read it and tests/test_migration_grants.py does not count it.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from .config import REPO_ROOT

log = logging.getLogger("mfetl")

MIGRATIONS = REPO_ROOT / "supabase" / "migrations"

# Applied by hand before the log existed. The first run against a database that already holds
# the catalog records these as applied instead of running them again.
PRE_LOG = ("0001_init.sql", "0002_events.sql", "0003_grants.sql")

# Printed after every run: what the public (anon) key may read. The catalog stays readable,
# the two private tables do not (0005).
CHECK_TABLES = ("molecule", "event", "ingest_run")

_LOG_DDL = """
create schema if not exists mfetl;
revoke all on schema mfetl from public, anon, authenticated;
create table if not exists mfetl.migration_log (
  name        text primary key,
  applied_at  timestamptz not null default now(),
  note        text
);
"""


def connect_kwargs(url: str) -> dict:
    """psycopg kwargs from a postgres URL. Split on the LAST '@' and the first ':' so a password
    holding @ # $ \\ : (Supabase generates them) needs no escaping."""
    url = url.strip().strip('"').strip("'")
    scheme, sep, rest = url.partition("://")
    if not sep or scheme not in ("postgres", "postgresql"):
        raise ValueError("SUPABASE_DB_URL must start with postgresql://")
    creds, sep, hostpart = rest.rpartition("@")
    if not sep:
        raise ValueError("SUPABASE_DB_URL has no user:password@ part")
    user, _, password = creds.partition(":")
    if not password or password.strip("[]").upper() == "YOUR-PASSWORD":
        raise ValueError("SUPABASE_DB_URL still has the [YOUR-PASSWORD] placeholder")
    hostport, _, dbname = hostpart.partition("/")
    host, _, port = hostport.partition(":")
    return {"host": host, "port": int(port or 5432), "user": user, "password": password,
            "dbname": dbname.split("?", 1)[0] or "postgres"}


def pending(applied: set[str], files: list[Path]) -> list[Path]:
    return [f for f in sorted(files) if f.name not in applied]


def run(apply: bool = False, url: str | None = None) -> int:
    import psycopg

    url = url or os.environ.get("SUPABASE_DB_URL", "")
    if not url:
        raise SystemExit("SUPABASE_DB_URL is not set in moleculefinder-etl/.env "
                         "(Supabase dashboard -> Connect -> Session pooler).")
    files = sorted(MIGRATIONS.glob("*.sql"))
    # prepare_threshold=None: no server-side prepared statements, so the transaction pooler works too.
    with psycopg.connect(**connect_kwargs(url), prepare_threshold=None, connect_timeout=15) as conn:
        cur = conn.cursor()
        has_log = cur.execute("select to_regclass('mfetl.migration_log') is not null").fetchone()[0]
        applied = {r[0] for r in cur.execute("select name from mfetl.migration_log")} if has_log else set()
        live = cur.execute("select to_regclass('public.molecule') is not null").fetchone()[0]
        baseline = [n for n in PRE_LOG if n not in applied] if live and not applied else []
        todo = pending(applied | set(baseline), files)

        log.info("migrate: %d file(s) in the repo, %d recorded as applied%s",
                 len(files), len(applied),
                 f"; {', '.join(baseline)} predate the log and will be recorded as applied" if baseline else "")
        for f in todo:
            log.info("migrate: pending %s", f.name)
        if not todo and not baseline:
            log.info("migrate: the database is up to date")
        if not apply:
            if todo or baseline:
                log.info("migrate: nothing changed. Run `mfetl migrate --apply` to apply.")
            conn.rollback()
            return 0

        with conn.transaction():
            cur.execute(_LOG_DDL)
            for name in baseline:
                cur.execute("insert into mfetl.migration_log (name, note) values (%s, %s) "
                            "on conflict do nothing", (name, "applied by hand before the log existed"))
        for f in todo:
            with conn.transaction():
                cur.execute(f.read_text())          # no parameters, so several statements are allowed
                cur.execute("insert into mfetl.migration_log (name) values (%s)", (f.name,))
            log.info("migrate: applied %s", f.name)

        for t in CHECK_TABLES:
            if cur.execute("select to_regclass(%s) is not null", (f"public.{t}",)).fetchone()[0]:
                can = cur.execute("select has_table_privilege('anon', %s, 'select')", (f"public.{t}",)).fetchone()[0]
                log.info("migrate: public key %s read %s", "CAN" if can else "can NOT", t)
        conn.commit()
    return 0
