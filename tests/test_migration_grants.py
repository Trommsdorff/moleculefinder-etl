"""Every table a migration creates carries explicit Data API grants (standing order 17).

Supabase stops auto-granting Data API access to new tables in `public` on 2026-10-30. A table
created after that with no grant is invisible to the REST API (42501 "permission denied"), and
this ETL loads through the REST API, so the first sign would be a failed Monday run. These tests
read the migration files as text, so they need nothing installed beyond pytest, and run in the
`migrations` workflow on any push or pull request that touches a migration.

The rule, per table:
* the service role holds SELECT, INSERT, UPDATE and DELETE on it, by name;
* anon holds SELECT on it by name, unless it is listed in PRIVATE below with a reason;
* a bigserial column's sequence is granted to the service role;
* for a table created after BASELINE, all of that is in the SAME migration file that creates it.

A blanket `on all tables in schema` grant does not count: it covers only the tables that exist
when it runs, which is exactly the gap the Oct 30 change opens.
"""
from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent.parent / "supabase" / "migrations"

# The migration that granted the pre-existing tables by name. Tables created in it or before
# it may take their grants from it; every later one grants in its own file.
BASELINE = "0004_explicit_grants.sql"

# Tables anon must NOT read, and why. Adding one is a deliberate edit to this file.
PRIVATE = {
    "event": "the /api/e beacon's rows: paths, referrers and session ids",
    "ingest_run": "the ETL's audit trail",
}

WRITE = {"select", "insert", "update", "delete"}

_CREATE = re.compile(r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?(\w+)\s*\((.*?)\);",
                     re.I | re.S)
_GRANT = re.compile(r"\bgrant\s+(.+?)\s+on\s+(table\s+|sequence\s+)?(?!all\s)(.+?)\s+to\s+(.+?);",
                    re.I | re.S)


def _sql(path: Path) -> str:
    """The file without comments, so a commented-out grant does not count."""
    return re.sub(r"--[^\n]*", "", path.read_text())


def _names(text: str) -> list[str]:
    return [n.strip().lower().removeprefix("public.") for n in text.split(",") if n.strip()]


def audit(migrations: Path, baseline: str = BASELINE) -> tuple[list[str], dict[str, dict]]:
    """Return (problems, tables) for a migrations directory. ``tables`` maps each created table
    to the file that creates it, the grants it holds by role, and its serial sequences."""
    files = sorted(migrations.glob("*.sql"))
    tables: dict[str, dict] = {}
    for f in files:
        for name, body in _CREATE.findall(_sql(f)):
            serial = [f"{name.lower()}_{col.lower()}_seq"
                      for col in re.findall(r"^\s*(\w+)\s+(?:big)?serial\b", body, re.I | re.M)]
            tables[name.lower()] = {"file": f.name, "grants": {}, "sequences": {}, "serial": serial}

    for f in files:
        for privs, kind, objects, roles in _GRANT.findall(_sql(f)):
            privs = {"select", "insert", "update", "delete", "usage"} if privs.strip().lower() == "all" \
                else {p.strip().lower() for p in privs.split(",")}
            for obj in _names(objects):
                for role in _names(roles):
                    if kind.strip().lower() == "sequence":
                        owner = next((t for t, v in tables.items() if obj in v["serial"]), None)
                        if owner:
                            tables[owner]["sequences"].setdefault(obj, {}).setdefault(role, set()).update(privs)
                            tables[owner]["sequences"][obj].setdefault("_files", set()).add(f.name)
                    elif obj in tables:
                        g = tables[obj]["grants"].setdefault(role, {"privs": set(), "files": set()})
                        g["privs"] |= privs
                        g["files"].add(f.name)

    problems: list[str] = []
    for name, t in sorted(tables.items()):
        # Before the baseline: grants may come from the baseline. After it: only from its own file.
        allowed = {t["file"]} if t["file"] > baseline else {t["file"], baseline}
        sr = t["grants"].get("service_role", {"privs": set(), "files": set()})
        if not WRITE <= sr["privs"] or not sr["files"] & allowed:
            problems.append(f"{name} ({t['file']}): service_role lacks "
                            f"{', '.join(sorted(WRITE - sr['privs'])) or 'a grant in ' + ' or '.join(sorted(allowed))}")
        anon = t["grants"].get("anon", {"privs": set(), "files": set()})
        if name in PRIVATE:
            if anon["privs"]:
                problems.append(f"{name} ({t['file']}): PRIVATE but granted to anon")
        elif "select" not in anon["privs"] or not anon["files"] & allowed:
            problems.append(f"{name} ({t['file']}): anon lacks select (or list it in PRIVATE with a reason)")
        for seq in t["serial"]:
            s = t["sequences"].get(seq, {})
            if "usage" not in s.get("service_role", set()) or not s.get("_files", set()) & allowed:
                problems.append(f"{name} ({t['file']}): sequence {seq} not granted usage to service_role")
    return problems, tables


# ── The repository ──────────────────────────────────────────────────────────
def test_every_table_in_the_repo_has_explicit_grants():
    problems, tables = audit(MIGRATIONS)
    assert len(tables) == 17, sorted(tables)
    assert problems == []


def test_private_tables_are_real_tables():
    _, tables = audit(MIGRATIONS)
    assert set(PRIVATE) <= set(tables)


# ── The checker itself: a future migration without grants fails ─────────────
def _repo_plus(tmp_path: Path, name: str, sql: str) -> Path:
    for f in MIGRATIONS.glob("*.sql"):
        (tmp_path / f.name).write_text(f.read_text())
    (tmp_path / name).write_text(sql)
    return tmp_path


def test_a_new_table_without_grants_fails(tmp_path):
    d = _repo_plus(tmp_path, "0005_news.sql",
                   "create table molecule_news (id bigserial primary key, slug text not null);")
    problems, _ = audit(d)
    assert any(p.startswith("molecule_news (0005_news.sql): service_role lacks") for p in problems)
    assert any("molecule_news (0005_news.sql): anon lacks select" in p for p in problems)
    assert any("molecule_news_id_seq" in p for p in problems)


def test_a_new_table_with_grants_in_its_own_file_passes(tmp_path):
    d = _repo_plus(tmp_path, "0005_news.sql", """
        create table if not exists public.molecule_news (id bigserial primary key, slug text);
        grant select on table public.molecule_news to anon;
        grant select, insert, update, delete on table public.molecule_news to service_role;
        grant usage, select on sequence molecule_news_id_seq to service_role;
    """)
    assert audit(d)[0] == []


def test_a_grant_in_a_later_file_does_not_count_for_a_new_table(tmp_path):
    """The order says "in the same migration": a table created bare and granted later is
    exposed to the window in between, so it fails."""
    d = _repo_plus(tmp_path, "0005_news.sql", "create table molecule_news (slug text primary key);")
    (d / "0006_fix.sql").write_text("grant select on molecule_news to anon;\n"
                                    "grant all on molecule_news to service_role;")
    problems, _ = audit(d)
    assert any(p.startswith("molecule_news (0005_news.sql)") for p in problems)


def test_a_blanket_schema_grant_and_a_commented_grant_do_not_count(tmp_path):
    d = _repo_plus(tmp_path, "0005_news.sql", """
        create table molecule_news (slug text primary key);
        grant select on all tables in schema public to anon;
        -- grant select, insert, update, delete on table molecule_news to service_role;
    """)
    problems, _ = audit(d)
    assert any(p.startswith("molecule_news (0005_news.sql): service_role lacks") for p in problems)
    assert any(p.startswith("molecule_news (0005_news.sql): anon lacks") for p in problems)


def test_without_the_baseline_the_existing_tables_fail(tmp_path):
    """Load-bearing check on 0004: drop it and all 17 tables are reported."""
    for f in MIGRATIONS.glob("*.sql"):
        if f.name != BASELINE:
            (tmp_path / f.name).write_text(f.read_text())
    problems, tables = audit(tmp_path)
    assert {p.split(" ", 1)[0] for p in problems} == set(tables) and len(tables) == 17
