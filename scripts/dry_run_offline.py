"""Offline dry-run: take a captured GitHub API payload and run it through the connector.

Used when we have repo metadata but cannot fetch live (private repo, no access).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api_types import RepoRecord
from app.asset_mapper import map_repository

CONN_QN = "default/app/1700000000"

# Payload captured from the GitHub MCP search at runtime.
PAYLOAD = {
    "id": 1093188306,
    "name": "atlan-context-studio-app",
    "full_name": "atlanhq/atlan-context-studio-app",
    "owner": {"login": "atlanhq"},
    "description": "Building an app on Atlan framework to showcase semantic view evals framework to our customers. This app will be deployed to internal instances first, and then to some select customers.",
    "html_url": "https://github.com/atlanhq/atlan-context-studio-app",
    "clone_url": "https://github.com/atlanhq/atlan-context-studio-app.git",
    "default_branch": "main",
    "language": "Python",
    "private": True,
    "fork": False,
    "archived": False,
    "created_at": "2025-11-10T03:06:02Z",
    "updated_at": "2026-04-21T12:55:26Z",
    "pushed_at": "2026-04-30T11:44:15Z",
    "size": 8631,
    "stargazers_count": 4,
    "watchers_count": 4,
    "forks_count": 0,
    "open_issues_count": 26,
    "topics": [],
    "license": None,
    "has_wiki": True,
    "has_issues": True,
    "has_projects": True,
    "has_downloads": True,
    "allow_forking": False,
    "has_pages": False,
    "has_discussions": False,
}


def to_record(d: dict) -> RepoRecord:
    return RepoRecord(
        full_name=d["full_name"],
        name=d["name"],
        owner=d["owner"]["login"],
        description=d.get("description"),
        html_url=d["html_url"],
        clone_url=d["clone_url"],
        default_branch=d["default_branch"],
        language=d.get("language"),
        is_private=d["private"],
        is_fork=d["fork"],
        is_archived=d["archived"],
        created_at=d["created_at"],
        updated_at=d["updated_at"],
        pushed_at=d["pushed_at"],
        size_kb=d["size"],
        stargazers_count=d["stargazers_count"],
        watchers_count=d["watchers_count"],
        forks_count=d["forks_count"],
        open_issues_count=d["open_issues_count"],
        topics=d.get("topics", []),
        license_name=(d.get("license") or {}).get("name"),
        has_wiki=d["has_wiki"],
        has_issues=d["has_issues"],
        has_projects=d["has_projects"],
        has_downloads=d["has_downloads"],
        id=d["id"],
    )


def kv(label, value, w=24):
    print(f"  {label:<{w}} {value if value not in (None, '') else '(unset)'}")


def main():
    repo = to_record(PAYLOAD)
    asset = map_repository(repo, CONN_QN)

    print("=" * 78)
    print(f" Application asset for {repo.full_name}")
    print("=" * 78)
    kv("type_name", asset.type_name)
    kv("name", asset.name)
    kv("display_name", asset.display_name)
    kv("qualified_name", asset.qualified_name)
    kv("connection_qualified_name", asset.connection_qualified_name)
    kv("connector_name", asset.connector_name)
    kv("app_id", asset.app_id)
    kv("description", (asset.description or "")[:90] + ("…" if len(asset.description or "") > 90 else ""))
    kv("source_url", asset.source_url)
    kv("source_created_by", asset.source_created_by)
    kv("source_created_at", f"{asset.source_created_at}  (epoch ms)")
    kv("source_updated_at", f"{asset.source_updated_at}  (epoch ms)")
    kv("asset_tags", list(asset.asset_tags) if asset.asset_tags else "(empty — no GitHub topics set)")
    kv("user_description", asset.user_description)
    print()

    print("-" * 78)
    print(" pushed_at vs updated_at — accuracy check")
    print("-" * 78)
    kv("GitHub pushed_at", repo.pushed_at)
    kv("GitHub updated_at", repo.updated_at)
    kv("Connector source_updated_at maps from", "updated_at (BUG: should be pushed_at)")
    days_diff = "9"  # Apr 30 vs Apr 21
    kv("⚠️  staleness gap", f"~{days_diff} days; repo was pushed today but Atlan will show Apr 21")

    print()
    print("-" * 78)
    print(" Signals collected by GitHub but DROPPED by current connector")
    print("-" * 78)
    kv("open_issues_count", f"{PAYLOAD['open_issues_count']} (untracked — no Issue assets created)")
    kv("allow_forking", f"{PAYLOAD['allow_forking']} (org policy — not captured)")
    kv("has_discussions", PAYLOAD["has_discussions"])
    kv("has_pages", PAYLOAD["has_pages"])
    kv("private", f"{PAYLOAD['private']} (is_discoverable not set False)")
    kv("contributors", "not fetched — could populate owner_users")
    kv("branches", "not fetched (default=main)")
    kv("languages breakdown", "only primary language captured (Python)")


if __name__ == "__main__":
    main()
