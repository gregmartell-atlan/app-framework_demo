"""Local end-to-end runner for the GitHub fetch_metadata entrypoint.

Drives the real extraction pipeline WITHOUT a Temporal worker or Dapr — the
@entrypoint/@task decorators only attach metadata, so the methods are directly
awaitable. This isolates the actual GitHub extraction (the part that was
previously not running) from the workflow plumbing.

Usage:
    GITHUB_TOKEN=ghp_xxx GITHUB_ORG=some-org \
        uv run python -m scripts.run_local_extract

Optional env:
    GITHUB_MAX_ITEMS   (default 10)  cap repos fetched for a quick smoke run
    GITHUB_EXTRACT_WIKI / _YAML / _SBOM  set to "1" to enable
"""

import asyncio
import json
import os
import sys

from app.connector import GitHubConnector
from app.contracts import GitHubMetadataInput


async def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    org = os.environ.get("GITHUB_ORG", "")
    if not token or not org:
        print("ERROR: set GITHUB_TOKEN and GITHUB_ORG env vars", file=sys.stderr)
        return 2

    input = GitHubMetadataInput(
        github_token=token,
        organization=org,
        max_items=int(os.environ.get("GITHUB_MAX_ITEMS", "10")),
        extract_wiki=os.environ.get("GITHUB_EXTRACT_WIKI") == "1",
        extract_yaml=os.environ.get("GITHUB_EXTRACT_YAML") == "1",
        extract_sbom=os.environ.get("GITHUB_EXTRACT_SBOM") == "1",
    )

    print(f"[run] fetch_metadata org={org!r} max_items={input.max_items} "
          f"wiki={input.extract_wiki} yaml={input.extract_yaml} sbom={input.extract_sbom}")

    connector = GitHubConnector()
    result = await connector.fetch_metadata(input)

    print("\n[result]")
    print(json.dumps(result.model_dump(), indent=2, default=str))
    print(f"\n[summary] {result.extraction_summary}")
    return 0 if result.repos_count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
