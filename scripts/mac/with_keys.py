"""Run a command with the two database keys (scripts/mac/weekly-refresh.sh and scripts/mac/news.sh, 2026-11).

    python scripts/mac/with_keys.py <path/to/.env> --check          both keys present? (values never shown)
    python scripts/mac/with_keys.py <path/to/.env> -- <command...>  run <command> with them in its environment

The Mac mini's weekly refresh is the one thing on this machine that uses the REAL keys; every interactive
build blanks them. They are read from the ETL's gitignored .env with python-dotenv, never `source`d in a
shell (the file's unquoted password breaks shell parsing, and the error prints it), never printed and never
written to a log. Only SUPABASE_URL and SUPABASE_SERVICE_KEY are passed on: the weekly load needs nothing
else, so the database password (SUPABASE_DB_URL, migrations only) stays out of the run's environment.
Standard library plus python-dotenv, which the ETL already depends on.
"""
from __future__ import annotations

import os
import sys

from dotenv import dotenv_values

KEYS = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY")
USAGE = "usage: with_keys.py <.env> --check | with_keys.py <.env> -- <command...>"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(USAGE, file=sys.stderr)
        return 2
    path, rest = argv[0], argv[1:]
    if not os.path.isfile(path):
        print(f"with_keys: no file at {path}", file=sys.stderr)
        return 3
    values = dotenv_values(path)
    missing = [k for k in KEYS if not (values.get(k) or "").strip()]
    if missing:
        print(f"with_keys: {path} has no value for {', '.join(missing)}", file=sys.stderr)
        return 3
    if rest == ["--check"]:
        print(f"with_keys: {' and '.join(KEYS)} are present in {path} (values not shown)")
        return 0
    if rest[0] != "--" or len(rest) < 2:
        print(USAGE, file=sys.stderr)
        return 2
    env = {k: v for k, v in os.environ.items() if k != "SUPABASE_DB_URL"}
    env.update({k: str(values[k]) for k in KEYS})
    os.execvpe(rest[1], rest[1:], env)
    return 127  # not reached


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
