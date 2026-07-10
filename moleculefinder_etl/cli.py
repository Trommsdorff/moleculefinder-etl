"""`mfetl` command-line entry point."""
from __future__ import annotations
import argparse
import logging
from .config import Settings
from . import pipeline

STAGES = {
    "seed": pipeline.stage_seed,
    "fetch": pipeline.stage_fetch,
    "transform": pipeline.stage_transform,
    "load": pipeline.stage_load,
    "export": pipeline.stage_export,
    "all": pipeline.run_all,
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mfetl", description="MoleculeFinder ETL")
    p.add_argument("stage", choices=STAGES, help="pipeline stage to run")
    p.add_argument("--target", type=int, default=None, help="canon size (default from env)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    if args.target:
        settings = Settings(settings.supabase_url, settings.supabase_service_key, args.target)
    STAGES[args.stage](settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
