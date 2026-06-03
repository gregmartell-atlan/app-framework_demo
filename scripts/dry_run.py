"""Dry-run the GitHub connector against a single repo and report what Atlan would receive.

Usage:
    GITHUB_TOKEN=ghp_xxx python3 scripts/dry_run.py owner/repo [--mode parse|full|index]

Exercises the real connector code (client + mapper) — no Atlan writes.
Prints a structured report of every asset that would be created.
"""

import asyncio
import base64
import json
import os
import sys
from typing import Optional

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api_types import RepoRecord, WikiPageRecord, YamlFileRecord, SbomDependencyRecord
from app.asset_mapper import (
    map_repository,
    map_wiki_page,
    map_yaml_file,
    map_sbom_dependency,
    _parse_wiki_structured,
    _parse_yaml_catalog,
)
from app.client import GitHubClient
from app.credentials import GitHubTokenCredential


CONN_QN = "default/app/1700000000"  # placeholder Atlan connection QN


def _box(title: str, char: str = "=", width: int = 80):
    print()
    print(char * width)
    print(f" {title}")
    print(char * width)


def _kv(label: str, value, width: int = 28):
    if value is None or value == "":
        value = "(none)"
    print(f"  {label:<{width}} {value}")


async def fetch_repo(client: httpx.AsyncClient, full_name: str) -> dict:
    r = await client.get(f"https://api.github.com/repos/{full_name}")
    r.raise_for_status()
    return r.json()


async def fetch_readme(client: httpx.AsyncClient, full_name: str) -> Optional[str]:
    r = await client.get(f"https://api.github.com/repos/{full_name}/readme")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    return base64.b64decode(data["content"]).decode("utf-8", errors="replace")


async def fetch_yaml_files(gh_client: GitHubClient, full_name: str) -> list[YamlFileRecord]:
    yamls = []
    async for y in gh_client.list_yaml_files(full_name):
        yamls.append(y)
    return yamls


async def fetch_branches(client: httpx.AsyncClient, full_name: str) -> list[dict]:
    r = await client.get(f"https://api.github.com/repos/{full_name}/branches", params={"per_page": 100})
    if r.status_code >= 400:
        return []
    return r.json()


async def fetch_contributors(client: httpx.AsyncClient, full_name: str) -> list[dict]:
    r = await client.get(f"https://api.github.com/repos/{full_name}/contributors", params={"per_page": 30})
    if r.status_code >= 400:
        return []
    return r.json() if isinstance(r.json(), list) else []


async def fetch_languages(client: httpx.AsyncClient, full_name: str) -> dict:
    r = await client.get(f"https://api.github.com/repos/{full_name}/languages")
    if r.status_code >= 400:
        return {}
    return r.json()


async def fetch_open_issues(client: httpx.AsyncClient, full_name: str) -> list[dict]:
    r = await client.get(
        f"https://api.github.com/repos/{full_name}/issues",
        params={"state": "open", "per_page": 100},
    )
    if r.status_code >= 400:
        return []
    # Filter out PRs (GitHub /issues includes both)
    return [i for i in r.json() if "pull_request" not in i]


def repo_record_from_api(data: dict) -> RepoRecord:
    return RepoRecord(
        full_name=data["full_name"],
        name=data["name"],
        owner=data["owner"]["login"],
        description=data.get("description"),
        html_url=data["html_url"],
        clone_url=data["clone_url"],
        default_branch=data.get("default_branch", "main"),
        language=data.get("language"),
        is_private=data["private"],
        is_fork=data["fork"],
        is_archived=data.get("archived", False),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        pushed_at=data.get("pushed_at", data["updated_at"]),
        size_kb=data["size"],
        stargazers_count=data["stargazers_count"],
        watchers_count=data["watchers_count"],
        forks_count=data["forks_count"],
        open_issues_count=data["open_issues_count"],
        topics=data.get("topics", []),
        license_name=data.get("license", {}).get("name") if data.get("license") else None,
        has_wiki=data.get("has_wiki", False),
        has_issues=data.get("has_issues", False),
        has_projects=data.get("has_projects", False),
        has_downloads=data.get("has_downloads", False),
        id=data.get("id", 0),
    )


async def main():
    if len(sys.argv) < 2:
        print("Usage: dry_run.py owner/repo [--mode index|full|parse]")
        sys.exit(1)
    full_name = sys.argv[1]
    mode = "parse"
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1]

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN env var not set")
        sys.exit(1)

    cred = GitHubTokenCredential(token=token)
    headers = cred.to_headers()

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as http:
        _box(f"DRY-RUN: {full_name}  (content_mode={mode})")

        # ── Repo ────────────────────────────────────────────────────────────
        try:
            repo_data = await fetch_repo(http, full_name)
        except httpx.HTTPStatusError as e:
            print(f"ERROR fetching repo: {e.response.status_code} {e.response.text[:200]}")
            sys.exit(1)

        repo = repo_record_from_api(repo_data)
        app_asset = map_repository(repo, CONN_QN)

        _box("1. Application asset (Atlan)", "─")
        _kv("type_name", app_asset.type_name)
        _kv("name", app_asset.name)
        _kv("display_name", app_asset.display_name)
        _kv("qualified_name", app_asset.qualified_name)
        _kv("app_id", app_asset.app_id)
        _kv("description", (app_asset.description or "")[:80])
        _kv("source_url", app_asset.source_url)
        _kv("source_created_by", app_asset.source_created_by)
        _kv("source_created_at", app_asset.source_created_at)
        _kv("source_updated_at", app_asset.source_updated_at)
        _kv("asset_tags", list(app_asset.asset_tags) if app_asset.asset_tags else None)
        _kv("user_description", app_asset.user_description)

        # ── README ─────────────────────────────────────────────────────────
        readme = await fetch_readme(http, full_name)
        _box(f"2. Readme asset", "─")
        if readme:
            _kv("name", repo.name)
            _kv("content_size", f"{len(readme)} chars")
            _kv("preview", readme[:120].replace("\n", " ") + "…")
        else:
            print("  (no README found)")

        # ── YAML files ──────────────────────────────────────────────────────
        async with GitHubClient(cred, concurrency_limit=4) as gh:
            try:
                yamls = await fetch_yaml_files(gh, full_name)
            except Exception as e:
                yamls = []
                print(f"  ERROR fetching YAMLs: {e}")

        _box(f"3. ApplicationField (YAML) — {len(yamls)} files", "─")
        catalog_yamls = []
        for y in yamls[:20]:
            parsed = _parse_yaml_catalog(y.content) if mode == "parse" else {}
            field = map_yaml_file(y, CONN_QN, content_mode=mode)
            tag = "📋" if parsed.get("owner") or parsed.get("domain") else "  "
            print(f"  {tag} {y.file_path}")
            print(f"      sha={y.file_sha[:10]}  size={y.file_size_bytes}b")
            if parsed.get("owner") or parsed.get("domain") or parsed.get("description"):
                catalog_yamls.append((y.file_path, parsed))
                print(f"      → owner={parsed.get('owner')}  domain={parsed.get('domain')}")
                if parsed.get("tags"):
                    print(f"      → tags={parsed['tags']}")
        if len(yamls) > 20:
            print(f"  … and {len(yamls) - 20} more")

        if catalog_yamls:
            _box("3a. YAMLs that LOOK like catalog metadata (parse-mode hits)", "─")
            for path, parsed in catalog_yamls:
                print(f"  {path}")
                for k, v in parsed.items():
                    _kv(f"    {k}", v, width=15)

        # ── Wiki ────────────────────────────────────────────────────────────
        _box("4. Wiki pages (ApplicationField)", "─")
        if not repo.has_wiki:
            print("  has_wiki=false — would skip")
        else:
            print(f"  has_wiki=true — connector would clone https://github.com/{full_name}.wiki.git")
            print("  (skipping live clone in dry-run; would yield N WikiPageRecords)")

        # ── What we DON'T capture today ─────────────────────────────────────
        _box("5. Signals available from GitHub but NOT mapped today", "─")

        branches = await fetch_branches(http, full_name)
        contributors = await fetch_contributors(http, full_name)
        languages = await fetch_languages(http, full_name)
        open_issues = await fetch_open_issues(http, full_name)

        _kv("branches", f"{len(branches)} (default={repo.default_branch}) — not modeled")
        _kv("contributors", f"{len(contributors)} — could populate owner_users")
        if contributors:
            top5 = ", ".join(c["login"] for c in contributors[:5])
            _kv("  top 5", top5)
        _kv("languages_breakdown", f"{len(languages)} languages — only primary captured")
        if languages:
            _kv("  bytes-by-lang", json.dumps(languages))
        _kv("open_issues", f"{len(open_issues)} — completely untracked")
        if open_issues:
            for issue in open_issues[:5]:
                print(f"      #{issue['number']}: {issue['title'][:70]}")
            if len(open_issues) > 5:
                print(f"      … and {len(open_issues) - 5} more")
        _kv("pushed_at vs updated_at",
            f"pushed={repo.pushed_at}  updated={repo.updated_at}")
        if repo.pushed_at != repo.updated_at:
            _kv("  ⚠️  mapping bug",
                "we use updated_at; pushed_at is more accurate for code currency")
        _kv("private repo", repo.is_private)
        if repo.is_private:
            _kv("  ⚠️  governance gap",
                "is_discoverable should be False for private repos but isn't set")
        _kv("allow_forking", repo_data.get("allow_forking"))
        _kv("has_pages", repo_data.get("has_pages"))
        _kv("has_discussions", repo_data.get("has_discussions"))

        # ── Summary ─────────────────────────────────────────────────────────
        _box("SUMMARY", "═")
        wiki_assets_estimated = "~unknown (depends on wiki clone)" if repo.has_wiki else "0"
        print(f"  {full_name}")
        print(f"    Application asset     : 1")
        print(f"    Readme asset          : {1 if readme else 0}")
        print(f"    YAML ApplicationFields: {len(yamls)}")
        print(f"      └─ catalog-like YAMLs (parse mode hits): {len(catalog_yamls)}")
        print(f"    Wiki ApplicationFields: {wiki_assets_estimated}")
        print(f"    SBOM ApplicationFields: (separate task — not exercised here)")
        print(f"    Total estimated assets: {1 + (1 if readme else 0) + len(yamls)} +/- wiki/SBOM")
        print()


if __name__ == "__main__":
    asyncio.run(main())
