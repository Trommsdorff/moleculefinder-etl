"""`mfetl` command-line entry point."""
from __future__ import annotations
import argparse
import logging
import os
from dotenv import load_dotenv
from .config import Settings
from . import pipeline

load_dotenv()  # pick up SUPABASE_URL / SUPABASE_SERVICE_KEY from a local .env

STAGES = {
    "seed": pipeline.stage_seed,
    "fetch": pipeline.stage_fetch,
    "transform": pipeline.stage_transform,
    "load": pipeline.stage_load,
    "export": pipeline.stage_export,
    "all": pipeline.run_all,
    # Offline: rebuild featured.json (molecule of the week) from the snapshot on disk.
    "featured": pipeline.stage_featured,
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mfetl", description="MoleculeFinder ETL")
    p.add_argument("stage", choices=[*STAGES, "migrate", "sync-inputs", "licences"], help="pipeline stage to run")
    p.add_argument("--target", type=int, default=None, help="canon size (default from env)")
    p.add_argument("--apply", action="store_true", help="migrate: apply pending migrations (default: list them)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    # Which inputs this run may use (moleculefinder_etl/inputs.py): the weekly GitHub run
    # refreshes them; every other run is pinned to the ones main was built from, so a rebuild
    # here reproduces main instead of drifting from it. MFETL_INPUTS=refresh overrides.
    if os.getenv("MFETL_INPUTS") not in ("pinned", "refresh"):
        os.environ["MFETL_INPUTS"] = "refresh" if os.getenv("GITHUB_ACTIONS") == "true" else "pinned"
    if args.stage == "sync-inputs":
        from . import inputs
        inputs.sync()
        return 0
    if args.stage == "licences":
        # Licence records from Drugs@FDA, the EMA and the hand-read MHRA file -> licences.yaml.
        # Deliberate and offline from the weekly run, which only reads the committed file.
        from . import licences
        return licences.run()
    if args.stage == "migrate":
        # Database migrations over SUPABASE_DB_URL; needs no REST keys.
        from . import migrate
        return migrate.run(apply=args.apply)
    settings = Settings.from_env()
    if args.target:
        settings = Settings(settings.supabase_url, settings.supabase_service_key, args.target)
    STAGES[args.stage](settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
