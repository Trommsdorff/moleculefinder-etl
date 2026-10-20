"""`mfetl migrate`: the connection string and the pending list (no database needed)."""
from __future__ import annotations

from pathlib import Path

import pytest

from moleculefinder_etl import migrate


def test_supabase_pooler_string_parses():
    kw = migrate.connect_kwargs(
        "postgresql://postgres.nzhhjdbgogfidjrsuqiv:s3cret@aws-0-us-east-1.pooler.supabase.com:5432/postgres")
    assert kw == {"host": "aws-0-us-east-1.pooler.supabase.com", "port": 5432,
                  "user": "postgres.nzhhjdbgogfidjrsuqiv", "password": "s3cret", "dbname": "postgres"}


@pytest.mark.parametrize("password", ["p@ss#w$rd\\x", "a:b@c", "%40plain"])
def test_awkward_passwords_need_no_escaping(password):
    kw = migrate.connect_kwargs(f"postgresql://postgres.ref:{password}@host.example:6543/postgres?sslmode=require")
    assert (kw["password"], kw["port"], kw["dbname"]) == (password, 6543, "postgres")


@pytest.mark.parametrize("url", [
    "postgresql://postgres.ref:[YOUR-PASSWORD]@host:5432/postgres",
    "https://ref.supabase.co",
    "postgresql://host:5432/postgres",
])
def test_placeholders_and_wrong_strings_are_refused(url):
    with pytest.raises(ValueError):
        migrate.connect_kwargs(url)


def test_pending_is_in_file_order_and_skips_applied():
    files = [Path(n) for n in ("0005_b.sql", "0001_a.sql", "0004_c.sql")]
    assert [f.name for f in migrate.pending({"0001_a.sql"}, files)] == ["0004_c.sql", "0005_b.sql"]


def test_pre_log_files_exist_and_come_first():
    names = sorted(f.name for f in migrate.MIGRATIONS.glob("*.sql"))
    assert names[:len(migrate.PRE_LOG)] == list(migrate.PRE_LOG)


def test_migrate_needs_the_url(monkeypatch):
    pytest.importorskip("psycopg")
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    with pytest.raises(SystemExit, match="SUPABASE_DB_URL"):
        migrate.run()
