"""Thin CLI wrapper around app.glossary_sync.sync_wiki_to_glossary.

This is Option B in the three-option deployment matrix. The business logic
lives in app/glossary_sync.py — this script just parses CLI flags / env vars,
builds the GlossarySyncConfig + AtlanClient, runs the sync, and prints the
result.

Env vars (required unless noted):
  ATLAN_BASE_URL   default: https://dsm.atlan.com
  ATLAN_API_KEY    required
  GITHUB_TOKEN     required (used to clone the wiki)
  GITHUB_REPO      default: gregmartell-atlan/app-framework_demo
  GLOSSARY_NAME    default: ghost_tsushima

CLI flags:
  --dry-run                Preview without writing to Atlan.
  --phase1 / --no-phase1   Filter pages (default: --phase1).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.contracts import GlossarySyncConfig
from app.glossary_sync import sync_wiki_to_glossary
from pyatlan_v9.client.atlan import AtlanClient


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sync a GitHub wiki to an Atlan glossary.")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be saved but never call client.asset.save().",
    )
    phase1 = p.add_mutually_exclusive_group()
    phase1.add_argument(
        "--phase1",
        dest="phase1_filter",
        action="store_true",
        default=True,
        help="Only push Client + Shared Schemas pages (default).",
    )
    phase1.add_argument(
        "--no-phase1",
        dest="phase1_filter",
        action="store_false",
        help="Push all schema pages (disables the Phase 1 filter).",
    )
    return p.parse_args()


async def _amain() -> int:
    args = _parse_args()

    base_url = os.environ.get("ATLAN_BASE_URL", "https://dsm.atlan.com")
    api_key = os.environ.get("ATLAN_API_KEY")
    github_token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO", "gregmartell-atlan/app-framework_demo")
    glossary_name = os.environ.get("GLOSSARY_NAME", "ghost_tsushima")

    if not api_key:
        print("ERROR: ATLAN_API_KEY is required", file=sys.stderr)
        return 2
    if not github_token:
        print("ERROR: GITHUB_TOKEN is required", file=sys.stderr)
        return 2

    cfg = GlossarySyncConfig(
        repo_full_name=repo,
        github_token=github_token,
        glossary_name=glossary_name,
        phase1_filter=args.phase1_filter,
        dry_run=args.dry_run,
    )

    print(f"Syncing wiki for {repo} -> glossary '{glossary_name}' on {base_url}")
    print(f"  dry_run={cfg.dry_run}  phase1_filter={cfg.phase1_filter}")

    client = AtlanClient(base_url=base_url, api_key=api_key)
    result = await sync_wiki_to_glossary(cfg, client)

    print("\nResult:")
    print(f"  glossary_qn        = {result.glossary_qn}")
    print(f"  pages_scanned      = {result.pages_scanned}")
    print(f"  pages_filtered_out = {result.pages_filtered_out}")
    print(f"  categories_created = {result.categories_created}")
    print(f"  terms_created      = {result.terms_created}")
    print(f"  terms_updated      = {result.terms_updated}")
    print(f"  readmes_saved      = {result.readmes_saved}")
    print(f"  relationships      = {result.relationships_linked}")
    if result.errors:
        print(f"  errors             = {result.errors}")

    # Dry-run intentionally exits 0 so the workflow's dry_run toggle works.
    return 0 if not result.errors else 1


def main() -> None:
    rc = asyncio.run(_amain())
    sys.exit(rc)


if __name__ == "__main__":
    main()
