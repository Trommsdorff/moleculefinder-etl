"""`mfetl` command-line entry point."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import pipeline
from .config import Settings, weekly_run

load_dotenv()  # pick up SUPABASE_URL / SUPABASE_SERVICE_KEY from a local .env
# The Zenodo token is read only by `mfetl zenodo` (zenodo.token(), straight from the file), so no other stage, and
# no process a stage starts, carries it in its environment.
os.environ.pop("ZENODO_TOKEN", None)
# The same for the dataset mirrors' logins (mirrors.py reads them straight from the file).
for _k in ("HF_TOKEN", "KAGGLE_API_TOKEN", "KAGGLE_USERNAME", "KAGGLE_KEY"):
    os.environ.pop(_k, None)

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
    p.add_argument("stage", choices=[*STAGES, "migrate", "sync-inputs", "licences", "dataset", "zenodo", "mirrors", "review"],
                   help="pipeline stage to run")
    p.add_argument("review_what", nargs="?", choices=["drawings", "facts", "findings"], default=None,
                   help="review: which trust review (drawings: moleculefinder_etl/review/drawings.py; facts: "
                        "moleculefinder_etl/review/facts.py; findings: moleculefinder_etl/review/findings.py)")
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
    p.add_argument("--whoami", dest="mirrors_whoami", action="store_true",
                   help="mirrors: check each login with a read-only call (never prints a token)")
    p.add_argument("--only", choices=["huggingface", "kaggle"], default=None, help="mirrors: just this mirror")
    p.add_argument("--check", dest="zenodo_check", action="store_true",
                   help="zenodo: after a publish, check the public record, its files and the DOIs (read only); "
                        "mirrors: check each mirror holds the package (read only)")
    p.add_argument("--release", dest="zenodo_release", action="store_true",
                   help="zenodo: publish dataset_published.yaml's release when it is newer than Zenodo's latest "
                        "(the Mac's weekly job); with --dry-run, build it in a temporary folder and check only")
    p.add_argument("--env-file", dest="zenodo_env_file", type=Path, default=None,
                   help="zenodo, mirrors: the file holding the logins (default: this repo's .env)")
    p.add_argument("-v", "--verbose", action="store_true")
    if argv is None:
        argv = sys.argv[1:]
    if argv[:2] == ["review", "drawings"]:
        # A trust review (read-only; its own options: `mfetl review drawings --help`). It loads no database key.
        from .review import drawings as review_drawings
        return review_drawings.main(argv[2:])
    if argv[:2] == ["review", "findings"]:
        # Trust review 5, findings arithmetic (read-only; `mfetl review findings --help`). No database key.
        from .review import findings as review_findings
        return review_findings.main(argv[2:])
    if argv[:2] == ["review", "facts"]:
        # Trust review 2, one fact on every surface (read-only; `mfetl review facts --help`). No database key.
        from .review import facts as review_facts
        return review_facts.main(argv[2:])
    args = p.parse_args(argv)
    if args.stage == "review":
        p.error("review: name the review (`mfetl review drawings`, `mfetl review facts` or `mfetl review findings`)")

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
        if args.zenodo_release and (args.zenodo_draft_only or args.zenodo_discard or args.zenodo_check):
            p.error("zenodo: --release goes alone or with --dry-run")
        rc = zenodo.run(dry_run=args.zenodo_dry_run, draft_only=args.zenodo_draft_only,
                        do_discard=args.zenodo_discard, check=args.zenodo_check, release=args.zenodo_release,
                        env_file=args.zenodo_env_file or zenodo.ENV_FILE)
        publishing = not (args.zenodo_dry_run or args.zenodo_draft_only or args.zenodo_discard or args.zenodo_check)
        if rc == 0 and publishing and not args.zenodo_release:   # the weekly job runs its own mirrors step
            # One word updates all three copies: a published version is followed by the mirrors (mirrors.py).
            from . import mirrors
            rc = mirrors.run(wait_for_zenodo=8)
            if rc:
                logging.getLogger("mfetl.mirrors").error(
                    "mirrors: Zenodo IS published; a mirror needs a second look: run `mfetl mirrors` again")
        return rc
    if args.stage == "mirrors":
        # Bring Hugging Face and Kaggle to the version Zenodo's latest record holds (mirrors.py).
        from . import mirrors
        if sum([args.zenodo_dry_run, args.zenodo_check, args.mirrors_whoami]) > 1:
            p.error("mirrors: --dry-run, --check and --whoami go one at a time")
        return mirrors.run(dry_run=args.zenodo_dry_run, check=args.zenodo_check, whoami=args.mirrors_whoami,
                           only=args.only, env_file=args.zenodo_env_file or mirrors.ENV_FILE)
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
