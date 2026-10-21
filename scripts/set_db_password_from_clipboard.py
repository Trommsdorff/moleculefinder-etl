"""Put a database password reset in the Supabase dashboard into SUPABASE_DB_URL (.env).

Supabase does not let the `postgres` login change its own password (ALTER ROLE answers
InsufficientPrivilege), so a rotation is: dashboard -> Project Settings -> Database -> Reset database
password -> Generate -> Copy; then, from the ETL folder:

    ./.venv/bin/python3 scripts/set_db_password_from_clipboard.py

It reads the password from the clipboard, checks that it connects BEFORE touching .env, swaps it
in, re-checks, and clears the clipboard. It prints no password or connection string. Only
`mfetl migrate` uses this password; GitHub, Vercel and the site use the REST keys.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

from moleculefinder_etl.migrate import connect_kwargs  # noqa: E402

ENV = ROOT / ".env"


def connects(kwargs: dict) -> bool:
    try:
        with psycopg.connect(**kwargs, prepare_threshold=None, connect_timeout=15) as c:
            return c.execute("select 1").fetchone()[0] == 1
    except psycopg.OperationalError:
        return False


def main() -> int:
    password = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()
    if not password or any(ch.isspace() for ch in password) or len(password) < 12:
        print("the clipboard does not hold a password (copy it from the dashboard first); nothing changed")
        return 1

    old_url = (dotenv_values(ENV).get("SUPABASE_DB_URL") or "").strip().strip('"').strip("'")
    old = connect_kwargs(old_url)
    new = {**old, "password": password}
    if old["password"] == password:
        print("the clipboard holds the CURRENT password; nothing changed")
        return 1
    if not connects(new):
        print("the copied password does not connect yet; .env untouched "
              "(wait a minute after the reset and run this again)")
        return 1

    lines = ENV.read_text().split("\n")
    at = [i for i, line in enumerate(lines) if line.startswith("SUPABASE_DB_URL=")]
    if len(at) != 1:
        print("expected exactly one SUPABASE_DB_URL line in .env; nothing changed")
        return 1
    scheme, _, rest = old_url.partition("://")
    creds, _, hostpart = rest.rpartition("@")
    lines[at[0]] = f"SUPABASE_DB_URL={scheme}://{creds.partition(':')[0]}:{password}@{hostpart}"
    staged = ENV.with_name(".env.new")
    staged.write_text("\n".join(lines))
    os.chmod(staged, ENV.stat().st_mode & 0o777)
    os.replace(staged, ENV)
    subprocess.run(["pbcopy"], input="", text=True)

    reread = connect_kwargs(dotenv_values(ENV)["SUPABASE_DB_URL"])
    print(".env updated; new password connects:", connects(reread))
    print("old password refused:", not connects(old))
    print("clipboard cleared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
