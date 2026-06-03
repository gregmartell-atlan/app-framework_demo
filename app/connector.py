"""GitHub App Framework v3 connector.

Structure:
  - GitHubConnector(App)           — Temporal workflows (@entrypoint) and activities (@task)
  - GitHubConnectorHandler(...)    — HTTP handler for auth/preflight (auto-discovered by SDK)

Activity naming: SDK prepends app name automatically.
  @task(name="fetch_repos")  →  Temporal activity "github:fetch_repos"
  @task(name="fetch_sbom")   →  Temporal activity "github:fetch_sbom"
  @task(name="transform")    →  Temporal activity "github:transform"
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from application_sdk.app import App, task, entrypoint
from application_sdk.handler import (
    DefaultHandler,
    AuthInput as HandlerAuthInput,
    AuthOutput as HandlerAuthOutput,
    AuthStatus,
    PreflightInput as HandlerPreflightInput,
    PreflightOutput as HandlerPreflightOutput,
    PreflightStatus,
    MetadataInput as HandlerMetadataInput,
    MetadataOutput as HandlerMetadataOutput,
    SqlMetadataOutput,
)

from app.api_types import RepoRecord, WikiPageRecord, YamlFileRecord, SbomDependencyRecord
from app.client import GitHubClient, SbomReportPending
from app.contracts import (
    GitHubMetadataInput,
    GitHubMetadataOutput,
    FetchReposInput,
    FetchReposOutput,
    FetchSbomInput,
    FetchSbomOutput,
    SbomProgress,
    TransformInput,
    TransformOutput,
    AuthInput,
    AuthOutput,
    PreflightInput,
    PreflightOutput,
)
from app.credentials import GitHubTokenCredential
from app.handler import handle_auth, handle_preflight


class GitHubConnector(App):
    """Atlan GitHub connector — extracts repos, wikis, YAML files, and SBOMs.

    Single @entrypoint `fetch_metadata` orchestrates:
      1. fetch_repos — GitHub API extraction
      2. (optional) fetch_sbom — SBOM generation
      Publish step is handled by AE after this workflow completes.
    """

    name = "github"

    @entrypoint
    async def fetch_metadata(self, input: GitHubMetadataInput) -> GitHubMetadataOutput:
        """Main extraction workflow — called from the UI 'Start' button.

        Orchestrates fetch_repos (and optionally fetch_sbom) as Temporal activities.
        """
        run_id = input.workflow_id or "local"
        output_dir = os.path.join(tempfile.gettempdir(), f"github_extract_{run_id}")

        repos_result = await self.fetch_repos(FetchReposInput(
            github_token=input.github_token,
            organization=input.organization,
            repositories=input.repositories,
            extract_wiki=input.extract_wiki,
            extract_yaml=input.extract_yaml,
            max_items=input.max_items,
            output_dir=output_dir,
            workflow_id=input.workflow_id,
            correlation_id=input.correlation_id,
        ))

        sbom_count = 0
        if input.extract_sbom and repos_result.repos_count > 0:
            repo_names_from_file = _read_repo_names(repos_result.repos_file_path)
            if repo_names_from_file:
                sbom_result = await self.fetch_sbom(FetchSbomInput(
                    repositories=repo_names_from_file,
                    organization=input.organization,
                    github_token=input.github_token,
                    poll_interval_seconds=input.sbom_poll_interval_seconds,
                    output_dir=output_dir,
                    workflow_id=input.workflow_id,
                    correlation_id=input.correlation_id,
                ))
                sbom_count = len(sbom_result.sbom_file_paths)

        summary = (
            f"Extracted {repos_result.repos_count} repos, "
            f"{repos_result.wiki_pages_count} wiki pages, "
            f"{repos_result.yaml_files_count} YAML files, "
            f"{sbom_count} SBOM files"
        )

        return GitHubMetadataOutput(
            repos_count=repos_result.repos_count,
            wiki_pages_count=repos_result.wiki_pages_count,
            yaml_files_count=repos_result.yaml_files_count,
            sbom_dependencies_count=sbom_count,
            extraction_summary=summary,
            status="succeeded",
        )

    @task(name="fetch_repos")
    async def fetch_repos(self, input: FetchReposInput) -> FetchReposOutput:
        """Fetch repositories, wikis, and YAML files from GitHub."""
        cred = GitHubTokenCredential(token=input.github_token)

        output_dir = Path(input.output_dir or tempfile.mkdtemp(prefix="github_repos_"))
        output_dir.mkdir(parents=True, exist_ok=True)

        repos_file = output_dir / "repos.jsonl"
        wiki_file = output_dir / "wiki_pages.jsonl"
        yaml_file = output_dir / "yaml_files.jsonl"

        repos_count = 0
        wiki_pages_count = 0
        yaml_files_count = 0

        async with GitHubClient(cred, concurrency_limit=8) as client:
            with open(repos_file, "w") as rf:
                async for repo in client.list_repos(
                    input.organization, max_items=input.max_items
                ):
                    if input.repositories and repo.name not in input.repositories:
                        continue

                    rf.write(json.dumps(repo.__dict__) + "\n")
                    repos_count += 1

                    if input.extract_wiki and repo.has_wiki:
                        try:
                            async for wiki_page in client.clone_wiki(
                                repo.full_name, self.task_context
                            ):
                                with open(wiki_file, "a") as wf:
                                    wf.write(json.dumps(wiki_page.__dict__) + "\n")
                                wiki_pages_count += 1
                        except Exception as e:
                            self.task_context.app_context.logger.warning(
                                "Wiki clone failed for %s: %s", repo.full_name, e
                            )

                    if input.extract_yaml:
                        try:
                            async for yaml in client.list_yaml_files(repo.full_name):
                                with open(yaml_file, "a") as yf:
                                    yf.write(json.dumps(yaml.__dict__) + "\n")
                                yaml_files_count += 1
                        except Exception as e:
                            self.task_context.app_context.logger.warning(
                                "YAML fetch failed for %s: %s", repo.full_name, e
                            )

        return FetchReposOutput(
            repos_count=repos_count,
            wiki_pages_count=wiki_pages_count,
            yaml_files_count=yaml_files_count,
            repos_file_path=str(repos_file) if repos_file.exists() else "",
            wiki_file_path=str(wiki_file) if wiki_file.exists() else "",
            yaml_file_path=str(yaml_file) if yaml_file.exists() else "",
            extraction_summary=(
                f"Extracted {repos_count} repos, {wiki_pages_count} wiki pages, "
                f"{yaml_files_count} YAML files"
            ),
        )

    @task(
        name="fetch_sbom",
        timeout_seconds=3600,
        heartbeat_timeout_seconds=120,
        auto_heartbeat_seconds=10,
        retry_max_attempts=3,
    )
    async def fetch_sbom(self, input: FetchSbomInput) -> FetchSbomOutput:
        """Fetch SBOM (Software Bill of Materials) for repositories.

        Uses typed heartbeat for resume support on timeout/retry.
        """
        cred = GitHubTokenCredential(token=input.github_token)
        output_dir = Path(input.output_dir or tempfile.mkdtemp(prefix="github_sbom_"))
        output_dir.mkdir(parents=True, exist_ok=True)

        successful_repos: list[str] = []
        failed_repos: list[str] = []
        sbom_file_paths: list[str] = []

        prev = self.get_heartbeat_details(SbomProgress)
        skip_until = prev.repo_full_name if prev else None

        async with GitHubClient(cred, concurrency_limit=4) as client:
            for repo_full_name in input.repositories:
                if skip_until and repo_full_name != skip_until:
                    continue
                if skip_until == repo_full_name:
                    skip_until = None

                sbom_file = output_dir / f"{repo_full_name.replace('/', '_')}_sbom.json"
                if sbom_file.exists():
                    successful_repos.append(repo_full_name)
                    sbom_file_paths.append(str(sbom_file))
                    continue

                try:
                    report_id = await client.start_sbom_report(repo_full_name)
                    from datetime import datetime, timezone
                    started_at = datetime.now(tz=timezone.utc).isoformat()

                    self.heartbeat(SbomProgress(
                        repo_full_name=repo_full_name,
                        report_id=report_id,
                        started_at_iso=started_at,
                        poll_attempts=0,
                    ))

                    initial_interval = input.poll_interval_seconds
                    poll_attempts = 0
                    max_attempts = 20

                    while poll_attempts < max_attempts:
                        await asyncio.sleep(min(initial_interval * (2 ** poll_attempts), 300))
                        try:
                            status = await client.get_sbom_report_status(repo_full_name)
                            if status == "complete":
                                break
                        except SbomReportPending:
                            poll_attempts += 1
                            self.heartbeat(SbomProgress(
                                repo_full_name=repo_full_name,
                                report_id=report_id,
                                started_at_iso=started_at,
                                poll_attempts=poll_attempts,
                            ))

                    await client.download_sbom_to_file(repo_full_name, sbom_file)
                    successful_repos.append(repo_full_name)
                    sbom_file_paths.append(str(sbom_file))

                except Exception as e:
                    self.task_context.app_context.logger.error(
                        "SBOM failed for %s: %s", repo_full_name, e
                    )
                    failed_repos.append(repo_full_name)

        return FetchSbomOutput(
            sbom_file_paths=sbom_file_paths,
            successful_repos=successful_repos,
            failed_repos=failed_repos,
            summary=f"SBOM: {len(successful_repos)} succeeded, {len(failed_repos)} failed",
        )

    @task(name="transform")
    async def transform(self, input: TransformInput) -> TransformOutput:
        """Transform extracted files to Atlan assets and write via pyatlan."""
        from pyatlan_v9.client.atlan import AtlanClient

        client = AtlanClient(
            base_url=input.atlan_base_url,
            api_key=input.atlan_api_key,
        )
        conn_qn = input.connection_qualified_name

        from app.asset_mapper import (
            map_repository, map_wiki_page, map_yaml_file,
            map_sbom_dependency, map_sbom_relationship,
        )
        from app.api_types import RepoRecord, WikiPageRecord, YamlFileRecord, SbomDependencyRecord

        assets_created = 0
        repos_count = wiki_pages_count = yaml_files_count = 0
        sbom_dependencies_count = sbom_relationships_count = 0

        if input.repos_file_path:
            with open(input.repos_file_path) as f:
                for line in f:
                    repo = RepoRecord(**json.loads(line))
                    client.asset.save(map_repository(repo, conn_qn))
                    assets_created += 1
                    repos_count += 1

        if input.wiki_file_path:
            with open(input.wiki_file_path) as f:
                for line in f:
                    page = WikiPageRecord(**json.loads(line))
                    client.asset.save(map_wiki_page(page, conn_qn))
                    assets_created += 1
                    wiki_pages_count += 1

        if input.yaml_file_path:
            with open(input.yaml_file_path) as f:
                for line in f:
                    yf = YamlFileRecord(**json.loads(line))
                    client.asset.save(map_yaml_file(yf, conn_qn))
                    assets_created += 1
                    yaml_files_count += 1

        if input.sbom_file_path:
            with open(input.sbom_file_path) as f:
                spdx = json.load(f)
            packages = spdx.get("packages", [])
            relationships = spdx.get("relationships", [])
            pkg_map: dict = {}
            for pkg in packages:
                dep = SbomDependencyRecord(
                    repo_full_name=spdx.get("name", "unknown/unknown"),
                    spdx_id=pkg.get("SPDXID"),
                    package_name=pkg.get("name"),
                    package_version=pkg.get("versionInfo"),
                    purl=(pkg.get("externalRefs") or [{}])[0].get("referenceLocator"),
                    license_concluded=pkg.get("licenseConcluded"),
                    license_declared=pkg.get("licenseDeclared"),
                    supplier=pkg.get("supplier"),
                    download_location=pkg.get("downloadLocation"),
                    relationship_type="PACKAGE",
                    parent_spdx_id=None,
                )
                client.asset.save(map_sbom_dependency(dep, conn_qn))
                assets_created += 1
                sbom_dependencies_count += 1
                pkg_map[dep.spdx_id] = dep

            for rel in relationships:
                if rel.get("relationshipType") == "DEPENDS_ON":
                    parent_dep = pkg_map.get(rel.get("spdxElementId"))
                    child_dep = pkg_map.get(rel.get("relatedSpdxElement"))
                    if parent_dep and child_dep:
                        child_with_parent = SbomDependencyRecord(
                            **{**child_dep.__dict__, "parent_spdx_id": rel["spdxElementId"],
                               "relationship_type": "DEPENDS_ON"}
                        )
                        process = map_sbom_relationship(child_with_parent, parent_dep, conn_qn)
                        if process:
                            client.asset.save(process)
                            assets_created += 1
                            sbom_relationships_count += 1

        return TransformOutput(
            assets_created=assets_created,
            assets_updated=0,
            repos_count=repos_count,
            wiki_pages_count=wiki_pages_count,
            yaml_files_count=yaml_files_count,
            sbom_dependencies_count=sbom_dependencies_count,
            sbom_relationships_count=sbom_relationships_count,
        )


def _read_repo_names(repos_file_path: str) -> list[str]:
    """Read full_name values from a repos.jsonl file."""
    if not repos_file_path or not Path(repos_file_path).exists():
        return []
    names = []
    with open(repos_file_path) as f:
        for line in f:
            try:
                data = json.loads(line)
                name = data.get("full_name", "")
                if name:
                    names.append(name)
            except json.JSONDecodeError:
                pass
    return names


class GitHubConnectorHandler(DefaultHandler):
    """HTTP handler for auth/preflight — auto-discovered by SDK as GitHubConnector + 'Handler'."""

    async def test_auth(self, input: HandlerAuthInput) -> HandlerAuthOutput:
        token = ""
        for cred in input.credentials:
            if cred.key in ("token", "github_token", "password", "api_key"):
                token = cred.value
                break
        if not token and input.credentials:
            token = input.credentials[0].value

        result = await handle_auth(AuthInput(credential={"token": token}))
        status = AuthStatus.SUCCESS if result.status == "success" else AuthStatus.FAILED
        return HandlerAuthOutput(status=status, message=result.message)

    async def preflight_check(self, input: HandlerPreflightInput) -> HandlerPreflightOutput:
        token = ""
        org = ""
        for cred in input.credentials:
            if cred.key in ("token", "github_token"):
                token = cred.value
                break
        if not token and input.credentials:
            token = input.credentials[0].value
        if hasattr(input, "connection") and input.connection:
            org = input.connection.get("organization", "")

        result = await handle_preflight(PreflightInput(
            organization=org, credential={"token": token}
        ))
        s = PreflightStatus.READY if result.status == "success" else PreflightStatus.FAILED
        return HandlerPreflightOutput(status=s, message=result.message)
