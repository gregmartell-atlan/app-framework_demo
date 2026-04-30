"""GitHub REST API client with async httpx and GitPython.

Handles:
- Paginated GitHub REST API calls
- Wiki cloning via GitPython (with low-speed timeout protection)
- SBOM generation and polling (Phase 2)
"""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx
import git
from git.exc import GitCommandError

from app.api_types import RepoRecord, WikiPageRecord, YamlFileRecord
from app.credentials import GitHubTokenCredential


class SbomReportPending(Exception):
    """Raised when SBOM report is still being generated (not ready yet)."""

    pass


class GitHubClient:
    """Async GitHub REST API client.

    Uses httpx for REST calls and GitPython for wiki cloning.
    """

    BASE_URL = "https://api.github.com"

    def __init__(self, credential: GitHubTokenCredential, concurrency_limit: int = 8):
        """Initialize the client.

        Args:
            credential: GitHub token credential
            concurrency_limit: Max concurrent requests (default 8 per spec)
        """
        self.credential = credential
        self.headers = credential.to_headers()
        self.semaphore = asyncio.Semaphore(concurrency_limit)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """Async context manager entry."""
        self._client = httpx.AsyncClient(
            headers=self.headers,
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()

    async def get_authenticated_user(self) -> dict:
        """Get the authenticated user's info.

        Used by the auth handler to verify credentials.

        Returns:
            User data dict with 'login', 'name', etc.

        Raises:
            httpx.HTTPStatusError: If auth fails (401, 403)
        """
        async with self.semaphore:
            response = await self._client.get(f"{self.BASE_URL}/user")
            response.raise_for_status()
            return response.json()

    async def get_rate_limit(self) -> dict:
        """Get current rate limit status.

        Returns:
            Rate limit data with 'rate' → 'remaining', 'reset'
        """
        async with self.semaphore:
            response = await self._client.get(f"{self.BASE_URL}/rate_limit")
            response.raise_for_status()
            return response.json()

    async def _resolve_repos_url(self, org: str) -> str:
        """Return the correct repos list URL for an org or user account.

        Tries /orgs/{org}/repos first (works for GitHub orgs). Falls back to
        /users/{org}/repos when the account is a plain user (HTTP 404 on the
        org endpoint is the canonical signal).
        """
        org_url = f"{self.BASE_URL}/orgs/{org}/repos"
        async with self.semaphore:
            probe = await self._client.get(
                org_url, params={"per_page": 1, "page": 1}
            )
        if probe.status_code == 404:
            return f"{self.BASE_URL}/users/{org}/repos"
        probe.raise_for_status()
        return org_url

    async def list_repos(self, org: str, max_items: int = 1000) -> AsyncIterator[RepoRecord]:
        """List repositories for an organization or user account.

        Auto-detects whether `org` is a GitHub Organisation or a plain user
        account and uses the appropriate endpoint.

        Args:
            org: Organisation login or personal account login
            max_items: Maximum repos to fetch

        Yields:
            RepoRecord instances
        """
        url = await self._resolve_repos_url(org)
        per_page = 100
        page = 1
        fetched = 0

        while fetched < max_items:
            async with self.semaphore:
                response = await self._client.get(
                    url,
                    params={"per_page": per_page, "page": page, "sort": "updated", "direction": "desc"},
                )
                response.raise_for_status()
                repos = response.json()

                if not repos:
                    break

                for repo_data in repos:
                    if fetched >= max_items:
                        return

                    yield RepoRecord(
                        full_name=repo_data["full_name"],
                        name=repo_data["name"],
                        owner=repo_data["owner"]["login"],
                        description=repo_data.get("description"),
                        html_url=repo_data["html_url"],
                        clone_url=repo_data["clone_url"],
                        id=repo_data.get("id", 0),
                        default_branch=repo_data.get("default_branch", "main"),
                        language=repo_data.get("language"),
                        is_private=repo_data["private"],
                        is_fork=repo_data["fork"],
                        is_archived=repo_data.get("archived", False),
                        created_at=repo_data["created_at"],
                        updated_at=repo_data["updated_at"],
                        pushed_at=repo_data.get("pushed_at", repo_data["updated_at"]),
                        size_kb=repo_data["size"],
                        stargazers_count=repo_data["stargazers_count"],
                        watchers_count=repo_data["watchers_count"],
                        forks_count=repo_data["forks_count"],
                        open_issues_count=repo_data["open_issues_count"],
                        topics=repo_data.get("topics", []),
                        license_name=repo_data.get("license", {}).get("name") if repo_data.get("license") else None,
                        has_wiki=repo_data.get("has_wiki", False),
                        has_issues=repo_data.get("has_issues", False),
                        has_projects=repo_data.get("has_projects", False),
                        has_downloads=repo_data.get("has_downloads", False),
                    )
                    fetched += 1

                page += 1

    async def clone_wiki(self, repo_full_name: str, task_context) -> AsyncIterator[WikiPageRecord]:
        """Clone a repository's wiki and extract markdown pages.

        Uses GitPython in a background thread (blocking I/O). Sets low-speed timeout
        env vars to prevent hangs on slow networks.

        Args:
            repo_full_name: e.g., "atlanhq/atlan-python"
            task_context: App task context for run_in_thread

        Yields:
            WikiPageRecord instances

        Raises:
            GitCommandError: If clone fails (wiki doesn't exist, network error, etc.)
        """
        wiki_url = f"https://github.com/{repo_full_name}.wiki.git"

        # Set Git low-speed timeout env vars (per v3 compliance rule 11)
        env = os.environ.copy()
        env["GIT_HTTP_LOW_SPEED_LIMIT"] = "1000"  # bytes/sec
        env["GIT_HTTP_LOW_SPEED_TIME"] = "120"  # seconds

        with tempfile.TemporaryDirectory() as tmpdir:
            clone_path = Path(tmpdir) / "wiki"

            # Clone in background thread (blocking I/O)
            try:
                await task_context.run_in_thread(
                    lambda: git.Repo.clone_from(
                        wiki_url,
                        clone_path,
                        env=env,
                    )
                )
            except GitCommandError as e:
                # Wiki not initialized or network error — log and skip
                # (Per spec: catch per-repo and continue, don't fail the whole task)
                raise

            # Read all .md files
            for md_file in clone_path.rglob("*.md"):
                rel_path = md_file.relative_to(clone_path)
                page_name = md_file.stem

                content = md_file.read_text(encoding="utf-8", errors="replace")

                # Try to get file SHA from git
                try:
                    repo = git.Repo(clone_path)
                    file_sha = repo.git.rev_parse(f"HEAD:{rel_path}")
                except Exception:
                    file_sha = None

                yield WikiPageRecord(
                    repo_full_name=repo_full_name,
                    page_path=str(rel_path),
                    page_name=page_name,
                    content=content,
                    file_sha=file_sha,
                )

    async def list_yaml_files(self, repo_full_name: str) -> AsyncIterator[YamlFileRecord]:
        """Discover and fetch YAML files in a repository.

        Uses the git tree API (recursive) to enumerate all .yml/.yaml blobs,
        then fetches raw content via the contents API.  This approach consumes
        the high-capacity *core* rate limit (5 000/hr) rather than the
        *code_search* limit (10/min) that the previous Code Search approach
        used.

        Args:
            repo_full_name: e.g., "atlanhq/atlan-python"

        Yields:
            YamlFileRecord instances with full content
        """
        tree_url = f"{self.BASE_URL}/repos/{repo_full_name}/git/trees/HEAD"

        async with self.semaphore:
            response = await self._client.get(tree_url, params={"recursive": "1"})

        if response.status_code == 409:
            # Empty repository — no tree exists yet
            return
        response.raise_for_status()

        data = response.json()
        yaml_blobs = [
            entry for entry in data.get("tree", [])
            if entry["type"] == "blob"
            and entry["path"].endswith((".yml", ".yaml"))
        ]

        for entry in yaml_blobs:
            file_path = entry["path"]
            file_sha = entry["sha"]

            # Fetch raw content via contents API (returns base64 by default)
            contents_url = f"{self.BASE_URL}/repos/{repo_full_name}/contents/{file_path}"
            async with self.semaphore:
                content_response = await self._client.get(
                    contents_url,
                    headers={**self.headers, "Accept": "application/vnd.github.raw+json"},
                )

            if content_response.status_code == 404:
                continue  # file deleted between tree fetch and content fetch
            content_response.raise_for_status()
            content = content_response.text

            yield YamlFileRecord(
                repo_full_name=repo_full_name,
                file_path=file_path,
                content=content,
                file_sha=file_sha,
                file_size_bytes=len(content.encode("utf-8")),
            )

    # ========================================================================
    # SBOM methods (Phase 2)
    # ========================================================================

    async def start_sbom_report(self, repo_full_name: str) -> str:
        """Kick off SBOM generation for a repository.

        GitHub generates SBOMs asynchronously. This starts the generation and returns a report ID.

        Args:
            repo_full_name: e.g., "atlanhq/atlan-python"

        Returns:
            SBOM report ID (used for polling)

        Raises:
            httpx.HTTPStatusError: If API call fails
        """
        url = f"{self.BASE_URL}/repos/{repo_full_name}/dependency-graph/sbom"
        async with self.semaphore:
            response = await self._client.post(url)
            response.raise_for_status()
            data = response.json()
            return data["sbom"]["creationInfo"]["created"]  # Use timestamp as pseudo-ID

    async def get_sbom_report_status(self, repo_full_name: str) -> str:
        """Check SBOM generation status.

        Args:
            repo_full_name: e.g., "atlanhq/atlan-python"

        Returns:
            "complete" if ready, raises SbomReportPending if still generating

        Raises:
            SbomReportPending: If SBOM is not ready yet
            httpx.HTTPStatusError: If repo doesn't support SBOM or network error
        """
        # GitHub's SBOM API doesn't have explicit status polling — we just try to fetch
        # and see if it 404s or succeeds
        url = f"{self.BASE_URL}/repos/{repo_full_name}/dependency-graph/sbom"
        async with self.semaphore:
            response = await self._client.get(url)

            if response.status_code == 202:
                # SBOM is being generated
                raise SbomReportPending(f"SBOM for {repo_full_name} is still being generated")

            response.raise_for_status()
            return "complete"

    async def download_sbom_to_file(self, repo_full_name: str, output_path: Path) -> None:
        """Download SBOM (SPDX JSON format) to a file.

        Streams the response to avoid loading large SBOMs into memory.

        Args:
            repo_full_name: e.g., "atlanhq/atlan-python"
            output_path: Where to write the SPDX JSON file

        Raises:
            httpx.HTTPStatusError: If SBOM not ready or network error
        """
        url = f"{self.BASE_URL}/repos/{repo_full_name}/dependency-graph/sbom"
        async with self.semaphore:
            async with self._client.stream("GET", url) as response:
                response.raise_for_status()

                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
