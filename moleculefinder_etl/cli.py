"""`mfetl` command-line entry point."""
from __future__ import annotations
import argparse
import logging
import os
from dotenv import load_dotenv
from .config import Settings, weekly_run
from . import pipeline

load_dotenv()  # pick up SUPABASE_URL / SUPABASE_SERVICE_KEY from a local .env
# The Zenodo token is read only by `mfetl zenodo` (zenodo.token(), straight from the file), so no other stage, and
# no process a stage starts, carries it in its environment.
os.environ.pop("ZENODO_TOKEN", None)

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
    p.add_argument("stage", choices=[*STAGES, "migrate", "sync-inputs", "licences", "dataset", "zenodo"], help="pipeline stage to run")
    p.add_argument("--target", type=int, default=None, help="canon size (default from env)")
    p.add_argument("--apply", action="store_true", help="migrate: apply pending migrations (default: list them)")
    p.add_argument("--version", dest="dataset_version", default=None,
                   help="dataset: the version to stamp (default: the snapshot's YYYY.MM)")
    p.add_argument("--doi", dest="dataset_doi", default=None,
                   help="dataset: this version's own Zenodo DOI, recorded in dataset_published.yaml (needs --version)")
    p.add_argument("--card", dest="dataset_card", action="store_true",
                   help="dataset: write only the Hugging Face dataset card (data/dataset/huggingface/README.md) "
                        "from the committed package's MANIFEST.json; no rebuild, no pinned inputs needed")
    p.add_argument("--dry-run", dest="zenodo_dry_run", action="store_true",
                   help="zenodo: read Zenodo and check everything; create nothing (no token needed)")
    p.add_argument("--draft-only", dest="zenodo_draft_only", action="store_true",
                   help="zenodo: make the draft with its files and stop before publishing")
    p.add_argument("--discard", dest="zenodo_discard", action="store_true",
                   help="zenodo: delete this record's open draft")
    p.add_argument("--check", dest="zenodo_check", action="store_true",
                   help="zenodo: after a publish, check the public record, its files and the DOIs (read only)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    # Which inputs this run may use (moleculefinder_etl/inputs.py): the weekly run (GitHub's, or
    # the Mac mini's job with MFETL_WEEKLY=1) refreshes them; every other run is pinned to the ones
    # main was built from, so a rebuild here reproduces main instead of drifting from it.
    # MFETL_INPUTS=refresh overrides.
    if os.getenv("MFETL_INPUTS") not in ("pinned", "refresh"):
        os.environ["MFETL_INPUTS"] = "refresh" if weekly_run() else "pinned"
    if args.stage == "sync-inputs":
        from . import inputs
        inputs.sync()
        return 0
    if args.stage == "licences":
        # Licence records from Drugs@FDA, the EMA and the hand-read MHRA file -> licences.yaml.
        # Deliberate and offline from the weekly run, which only reads the committed file.
        from . import licences
        return licences.run()
    if args.stage == "dataset":
        # The CC0 dataset for Zenodo and Kaggle (run D), rebuilt from the committed snapshot into
        # data/dataset/. Offline; refuses unless data/raw_cache is main's pinned inputs.
        from . import dataset
        return dataset.run(version=args.dataset_version, doi=args.dataset_doi, card=args.dataset_card)
    if args.stage == "zenodo":
        # Publish the package in data/dataset/ as a new version of the Zenodo record (zenodo.py).
        from . import zenodo
        if sum([args.zenodo_dry_run, args.zenodo_draft_only, args.zenodo_discard, args.zenodo_check]) > 1:
            p.error("zenodo: --dry-run, --draft-only, --discard and --check go one at a time")
        return zenodo.run(dry_run=args.zenodo_dry_run, draft_only=args.zenodo_draft_only,
                          do_discard=args.zenodo_discard, check=args.zenodo_check)
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
