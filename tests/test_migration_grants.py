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

import pytest

MIGRATIONS = Path(__file__).resolve().parent.parent / "supabase" / "migrations"

# The migration that granted the pre-existing tables by name. Tables created in it or before
# it may take their grants from it; every later one grants in its own file.
BASELINE = "0004_explicit_grants.sql"

# Tables anon must NOT read, and why. Adding one is a deliberate edit to this file.
PRIVATE = {
    "event": "the /api/e beacon's rows: paths, referrers and session ids",
    "ingest_run": "the ETL's audit trail",
    "molecule_news_match": "the news job's audit trail: headline text, outlet, link and query per match",
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
            privs = re.sub(r"\([^)]*\)", "", privs)          # a column grant still grants the privilege
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
    assert len(tables) == 19, sorted(tables)
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
    d = _repo_plus(tmp_path, "0099_trivia.sql",
                   "create table molecule_trivia (id bigserial primary key, slug text not null);")
    problems, _ = audit(d)
    assert any(p.startswith("molecule_trivia (0099_trivia.sql): service_role lacks") for p in problems)
    assert any("molecule_trivia (0099_trivia.sql): anon lacks select" in p for p in problems)
    assert any("molecule_trivia_id_seq" in p for p in problems)


def test_a_new_table_with_grants_in_its_own_file_passes(tmp_path):
    d = _repo_plus(tmp_path, "0099_trivia.sql", """
        create table if not exists public.molecule_trivia (id bigserial primary key, slug text);
        grant select on table public.molecule_trivia to anon;
        grant select, insert, update, delete on table public.molecule_trivia to service_role;
        grant usage, select on sequence molecule_trivia_id_seq to service_role;
    """)
    assert audit(d)[0] == []


def test_a_grant_in_a_later_file_does_not_count_for_a_new_table(tmp_path):
    """The order says "in the same migration": a table created bare and granted later is
    exposed to the window in between, so it fails."""
    d = _repo_plus(tmp_path, "0099_trivia.sql", "create table molecule_trivia (slug text primary key);")
    (d / "0100_fix.sql").write_text("grant select on molecule_trivia to anon;\n"
                                    "grant all on molecule_trivia to service_role;")
    problems, _ = audit(d)
    assert any(p.startswith("molecule_trivia (0099_trivia.sql)") for p in problems)


def test_a_blanket_schema_grant_and_a_commented_grant_do_not_count(tmp_path):
    d = _repo_plus(tmp_path, "0099_trivia.sql", """
        create table molecule_trivia (slug text primary key);
        grant select on all tables in schema public to anon;
        -- grant select, insert, update, delete on table molecule_trivia to service_role;
    """)
    problems, _ = audit(d)
    assert any(p.startswith("molecule_trivia (0099_trivia.sql): service_role lacks") for p in problems)
    assert any(p.startswith("molecule_trivia (0099_trivia.sql): anon lacks") for p in problems)


def test_without_the_baseline_the_existing_tables_fail(tmp_path):
    """Load-bearing check on 0004: drop it and the 17 tables before it are reported. 0006's
    two news tables grant themselves in their own file, as every table after the baseline must."""
    for f in MIGRATIONS.glob("*.sql"):
        if f.name != BASELINE:
            (tmp_path / f.name).write_text(f.read_text())
    problems, tables = audit(tmp_path)
    reported = {p.split(" ", 1)[0] for p in problems}
    assert reported == set(tables) - {"molecule_news", "molecule_news_match"} and len(reported) == 17


# ── The private tables stay private (Garrett, 2026-10-18) ───────────────────
# 0003's blanket grant let anyone with the public (anon) key read `event` and `ingest_run`;
# 0005 revokes it. These replay every migration in order, blanket grants, default privileges and
# revokes included, and fail if either table ends up readable by anon or authenticated again.
_STMT = re.compile(r"[^;]+;")
PUBLIC_ROLES = ("anon", "authenticated")


def effective_privileges(migrations: Path) -> dict[str, dict[str, set[str]]]:
    """{table: {role: privileges}} after applying every migration in file order."""
    privs: dict[str, dict[str, set[str]]] = {}
    defaults: dict[str, set[str]] = {}

    def expand(text: str) -> set[str]:
        """A column grant is held as "select(col,col)": it is not the whole table."""
        text = text.strip().lower()
        if text.startswith("all"):
            return {"select", "insert", "update", "delete"}
        cols = {m.group(1): f"{m.group(1)}({','.join(sorted(_names(m.group(2))))})"
                for m in re.finditer(r"(\w+)\s*\(([^)]*)\)", text)}
        return {cols.get(p, p) for p in (q.strip() for q in re.sub(r"\([^)]*\)", "", text).split(","))}

    for f in sorted(migrations.glob("*.sql")):
        for stmt in _STMT.findall(_sql(f)):
            s = " ".join(stmt.split()).lower().rstrip(";")
            m = re.match(r"create table (?:if not exists )?(?:public\.)?(\w+)", s)
            if m:
                privs.setdefault(m.group(1), {r: set(p) for r, p in defaults.items()})
                continue
            m = re.match(r"alter default privileges in schema public grant (.+?) on tables to (.+)", s)
            if m:
                for role in _names(m.group(2)):
                    defaults.setdefault(role, set()).update(expand(m.group(1)))
                continue
            m = re.match(r"(grant|revoke) (.+?) on (?:table )?(all tables in schema public|(?!sequence|schema|all )[\w., ]+?) (?:to|from) (.+)", s)
            if not m:
                continue
            verb, what, objects, roles = m.groups()
            targets = list(privs) if objects.startswith("all tables") else [o for o in _names(objects) if o in privs]
            for t in targets:
                for role in _names(roles):
                    held = privs[t].setdefault(role, set())
                    held |= expand(what) if verb == "grant" else set()
                    if verb == "revoke":           # revoking a table privilege revokes its column grants too
                        gone = expand(what)
                        held -= gone | {h for h in held if h.split("(")[0] in gone}
    return privs


def test_event_and_ingest_run_are_not_readable_with_the_public_key():
    privs = effective_privileges(MIGRATIONS)
    for table in PRIVATE:
        for role in PUBLIC_ROLES:
            assert privs[table].get(role, set()) == set(), (table, role)
        assert {"select", "insert"} <= privs[table]["service_role"]      # /dashboard reads, /api/e inserts
    assert "select" in privs["molecule"]["anon"]                          # the catalog stays public


def test_without_0005_both_were_readable(tmp_path):
    """Load-bearing check: drop 0005 and 0003's blanket grant is back in force."""
    for f in MIGRATIONS.glob("*.sql"):
        if not f.name.startswith("0005"):
            (tmp_path / f.name).write_text(f.read_text())
    privs = effective_privileges(tmp_path)
    assert "select" in privs["event"]["anon"] and "select" in privs["ingest_run"]["authenticated"]


@pytest.mark.parametrize("sql", [
    "grant select on event to anon;",
    "grant select on table public.ingest_run to authenticated;",
    "grant select on all tables in schema public to anon;",
])
def test_a_later_grant_reopening_them_fails(tmp_path, sql):
    d = _repo_plus(tmp_path, "0099_oops.sql", sql)
    with pytest.raises(AssertionError):
        privs = effective_privileges(d)
        for table in PRIVATE:
            for role in PUBLIC_ROLES:
                assert privs[table].get(role, set()) == set(), (table, role)


def test_molecule_news_is_read_only_to_the_public_key_and_names_only():
    """Run A (0006): the feed's facts are public anyway, so anon may read the names-only table, and
    only its five public columns; only the service role (the news job) may write it. 0003's default
    privileges would have granted the whole table to anon and authenticated: 0006 revokes that
    first, or the column grant would mean nothing."""
    privs = effective_privileges(MIGRATIONS)
    assert privs["molecule_news"]["anon"] == {"select(first_seen,hits,last_seen,name,slug)"}
    assert privs["molecule_news"].get("authenticated", set()) == set()
    assert {"select", "insert", "update", "delete"} <= privs["molecule_news"]["service_role"]


def test_the_news_audit_trail_is_private():
    """Headline text, outlet, link and query live in molecule_news_match, which no public key may
    read, by grant AND by row level security with no policy."""
    privs = effective_privileges(MIGRATIONS)["molecule_news_match"]
    for role in PUBLIC_ROLES:
        assert privs.get(role, set()) == set(), role
    assert {"select", "insert", "update", "delete"} <= privs["service_role"]
    sql = _sql(MIGRATIONS / "0006_molecule_news.sql")
    assert "alter table molecule_news_match enable row level security" in " ".join(sql.split()).lower()
    assert "on molecule_news_match for" not in sql                         # no policy at all
    # Every coverage column is on the private table, none on the public one.
    tables = dict(_CREATE.findall(sql))
    public_cols = {c.lower() for c in re.findall(r"^\s*(\w+)\s", tables["molecule_news"], re.MULTILINE)}
    assert public_cols.isdisjoint({"headline", "outlet", "url", "query", "story"})
    assert {"headline", "outlet", "url", "query"} <= {c.lower() for c in re.findall(r"^\s*(\w+)\s", tables["molecule_news_match"], re.MULTILINE)}


def test_without_the_revoke_the_column_grant_would_mean_nothing(tmp_path):
    """Load-bearing check on 0006's revoke: 0003's default privileges grant every new table."""
    for f in MIGRATIONS.glob("*.sql"):
        (tmp_path / f.name).write_text(f.read_text().replace(
            "revoke all on table molecule_news from anon, authenticated;", "").replace(
            "revoke all on table molecule_news_match from anon, authenticated;", ""))
    privs = effective_privileges(tmp_path)
    assert "select" in privs["molecule_news"]["anon"] and "select" in privs["molecule_news_match"]["anon"]
