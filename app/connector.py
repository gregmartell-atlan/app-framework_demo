"""GitHub App Framework v3 connector.

Canonical structure (reconciled against atlanhq/application-sdk v3.4.0):
- App subclass exposes ONE triggerable Temporal workflow via @entrypoint
  (sync_glossary). Single-entrypoint apps need no ?entrypoint selection, which
  the bundled setup-form SPA relies on.
- @task methods are activities, invoked from the workflow via `await self.<task>()`.
  Activity names are bare; the SDK prepends the app name (-> github:<name>).
- auth/preflight are Handler operations (NOT @entrypoint) — implemented on
  GitHubConnectorHandler, auto-discovered by the `{AppClassName}Handler` convention.
"""

import asyncio
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, Optional

from pydantic import Field
from application_sdk.app import App, task, entrypoint, AtlanClientMixin, Input
from application_sdk.handler.base import DefaultHandler
from application_sdk.handler.contracts import (
    AuthInput as HandlerAuthInput,
    AuthOutput as HandlerAuthOutput,
    AuthStatus,
)

from app.api_types import RepoRecord, WikiPageRecord, YamlFileRecord, SbomDependencyRecord
from app.asset_mapper import (
    map_repository,
    map_wiki_page,
    map_yaml_file,
    map_sbom_dependency,
    map_sbom_relationship,
)
from app.glossary_mapper import (
    _infer_wiki_section,
    map_glossary,
    map_glossary_category,
    map_wiki_page_as_term,
    map_yaml_file_as_term,
)
from app.client import GitHubClient, SbomReportPending
from app.contracts import (
    AuthInput,
    GitHubExtractionInput,
    GitHubExtractionOutput,
    FetchSbomInput,
    FetchSbomOutput,
    SbomProgress,
    TransformInput,
    TransformOutput,
    FileReference,
    GlossarySyncInput,
    GlossarySyncOutput,
)
from app.credentials import GitHubTokenCredential
from app.handler import handle_auth, handle_glossary_sync


class SyncGlossaryFormInput(Input, allow_unbounded_fields=True):
    """Flat workflow input — fields match the setup form (app/generated/github.json).

    Kept flat (not nested credential dicts) so the playground form maps 1:1 onto
    the workflow start payload. The workflow assembles the nested GlossarySyncInput
    for the activity.
    """

    github_token: str = Field(..., description="GitHub PAT with repo + read:wiki scopes")
    atlan_base_url: str = Field(default="https://dsm.atlan.com", description="Atlan base URL")
    atlan_api_key: str = Field(..., description="Atlan API key")
    repo_full_name: str = Field(..., description="owner/repo whose wiki to sync")
    glossary_name: str = Field(default="sony_telemetry", description="Target Atlan glossary name")
    phase1_filter: bool = Field(default=True, description="Only Client + Shared Schemas pages")
    dry_run: bool = Field(default=False, description="Preview without writing to Atlan")


class GitHubConnector(AtlanClientMixin, App):
    """Atlan GitHub connector — wiki -> Atlan glossary sync (+ repo/YAML/SBOM activities).

    v3-canonical:
    - Extends App; exposes the sync_glossary workflow via @entrypoint
    - @task methods are activities; the workflow invokes them with `await self.<task>()`
    - auth/preflight live on GitHubConnectorHandler (see below), not as @entrypoint
    - All methods have typed Input/Output (no bare Dict/Any)
    """

    name: ClassVar[str] = "github"
    version: ClassVar[str] = "1.0.0"

    # ─── Workflow (@entrypoint) ─────────────────────────────────────────

    @entrypoint
    async def sync_glossary(self, input: SyncGlossaryFormInput) -> GlossarySyncOutput:
        """Glossary-sync workflow: assemble the activity input and run it.

        Deterministic orchestration only — the flat form fields are folded into
        the nested GlossarySyncInput here, then the activity does all I/O.
        """
        nested = GlossarySyncInput(
            repo_full_name=input.repo_full_name,
            github_credential={"token": input.github_token},
            atlan_credential={"base_url": input.atlan_base_url, "api_key": input.atlan_api_key},
            glossary_name=input.glossary_name,
            phase1_filter=input.phase1_filter,
            dry_run=input.dry_run,
        )
        return await self.run_glossary_sync(nested)

    # ─── Activities (@task) ─────────────────────────────────────────

    @task(name="sync_glossary", timeout_seconds=1800, retry_max_attempts=2)
    async def run_glossary_sync(self, input: GlossarySyncInput) -> GlossarySyncOutput:
        """Activity: clone the wiki and upsert pages as Atlan glossary terms."""
        return await handle_glossary_sync(input)

    @task(name="fetch_repos")
    async def fetch_repos(self, input: GitHubExtractionInput) -> GitHubExtractionOutput:
        """Fetch repositories (and optionally wikis/YAML) from GitHub."""
        token = input.credential.get("token")
        cred = GitHubTokenCredential(token=token)

        output_dir = Path(tempfile.gettempdir()) / "atlan-github" / self.context.run_id / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        repos_file = output_dir / "repos.jsonl"
        wiki_file = output_dir / "wiki_pages.jsonl"
        yaml_file = output_dir / "yaml_files.jsonl"

        repos_count = 0
        wiki_pages_count = 0
        yaml_files_count = 0

        async with GitHubClient(cred, concurrency_limit=8) as client:
            with open(repos_file, "w") as rf:
                async for repo in client.list_repos(input.organization, max_items=input.max_items.max_items):
                    if input.repositories and repo.name not in input.repositories:
                        continue

                    rf.write(json.dumps(repo.__dict__) + "\n")
                    repos_count += 1

                    if input.extract_wiki and repo.has_wiki:
                        try:
                            async for wiki_page in client.clone_wiki(repo.full_name, self.task_context):
                                with open(wiki_file, "a") as wf:
                                    wf.write(json.dumps(wiki_page.__dict__) + "\n")
                                    wiki_pages_count += 1
                        except Exception as e:
                            self.logger.warning(f"Failed to clone wiki for {repo.full_name}: {e}")

                    if input.extract_yaml:
                        try:
                            async for yaml in client.list_yaml_files(repo.full_name):
                                with open(yaml_file, "a") as yf:
                                    yf.write(json.dumps(yaml.__dict__) + "\n")
                                    yaml_files_count += 1
                        except Exception as e:
                            self.logger.warning(f"Failed to fetch YAML files for {repo.full_name}: {e}")

        return GitHubExtractionOutput(
            repos_file=FileReference(path=str(repos_file), retention="RETAINED", size_bytes=repos_file.stat().st_size) if repos_file.exists() else None,
            wiki_file=FileReference(path=str(wiki_file), retention="RETAINED", size_bytes=wiki_file.stat().st_size) if wiki_file.exists() else None,
            yaml_file=FileReference(path=str(yaml_file), retention="RETAINED", size_bytes=yaml_file.stat().st_size) if yaml_file.exists() else None,
            sbom_file=None,
            extraction_summary=f"Extracted {repos_count} repos, {wiki_pages_count} wiki pages, {yaml_files_count} YAML files",
            repos_count=repos_count,
            wiki_pages_count=wiki_pages_count,
            yaml_files_count=yaml_files_count,
        )

    @task(
        name="fetch_sbom",
        timeout_seconds=3600,
        heartbeat_timeout_seconds=120,
        auto_heartbeat_seconds=10,
        retry_max_attempts=3,
    )
    async def fetch_sbom(self, input: FetchSbomInput) -> FetchSbomOutput:
        """Fetch SBOMs for repositories (typed heartbeat resume; backoff capped 300s)."""
        token = input.credential.get("token")
        cred = GitHubTokenCredential(token=token)

        output_dir = Path(input.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        successful_repos = []
        failed_repos = []
        sbom_files = []

        prev_progress: Optional[SbomProgress] = self.task_context.get_heartbeat_details(SbomProgress)
        skip_until = prev_progress.repo_full_name if prev_progress else None

        async with GitHubClient(cred, concurrency_limit=4) as client:
            for repo_full_name in input.repositories:
                if skip_until and repo_full_name != skip_until:
                    continue
                if skip_until == repo_full_name:
                    skip_until = None

                sbom_output_file = output_dir / f"{repo_full_name.replace('/', '_')}_sbom.json"

                if sbom_output_file.exists():
                    self.logger.info(f"SBOM for {repo_full_name} already exists, skipping")
                    successful_repos.append(repo_full_name)
                    sbom_files.append(FileReference(
                        path=str(sbom_output_file),
                        retention="RETAINED",
                        size_bytes=sbom_output_file.stat().st_size,
                    ))
                    continue

                try:
                    report_id = await client.start_sbom_report(repo_full_name)
                    started_at = datetime.now(timezone.utc).isoformat()

                    self.task_context.heartbeat(SbomProgress(
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
                            self.task_context.heartbeat(SbomProgress(
                                repo_full_name=repo_full_name,
                                report_id=report_id,
                                started_at_iso=started_at,
                                poll_attempts=poll_attempts,
                            ))
                            continue

                    await client.download_sbom_to_file(repo_full_name, sbom_output_file)

                    successful_repos.append(repo_full_name)
                    sbom_files.append(FileReference(
                        path=str(sbom_output_file),
                        retention="RETAINED",
                        size_bytes=sbom_output_file.stat().st_size,
                    ))

                except Exception as e:
                    self.logger.error(f"Failed to fetch SBOM for {repo_full_name}: {e}")
                    failed_repos.append(repo_full_name)

        return FetchSbomOutput(
            sbom_files=sbom_files,
            successful_repos=successful_repos,
            failed_repos=failed_repos,
            summary=f"SBOM generation: {len(successful_repos)} succeeded, {len(failed_repos)} failed",
        )

    @task(name="transform")
    async def transform(self, input: TransformInput) -> TransformOutput:
        """Transform GitHub records to Atlan assets (reads JSONL, writes via pyatlan)."""
        from pyatlan_v9.client.atlan import AtlanClient as _AtlanClient
        _cred = input.atlan_credential
        atlan_client = _AtlanClient(
            base_url=_cred.get("base_url", ""),
            api_key=_cred.get("api_key", ""),
        ) if _cred else None
        conn_qn = input.connection_qualified_name

        assets_created = 0
        repos_count = 0
        wiki_pages_count = 0
        yaml_files_count = 0
        sbom_dependencies_count = 0
        sbom_relationships_count = 0

        if input.repos_file:
            with open(input.repos_file.path, "r") as f:
                for line in f:
                    repo_data = json.loads(line)
                    repo = RepoRecord(**repo_data)
                    asset = map_repository(repo, conn_qn)
                    atlan_client.asset.save(asset)
                    assets_created += 1
                    repos_count += 1

        if input.wiki_file:
            if input.output_target == "glossary":
                wiki_pages_count = await self._transform_wiki_to_glossary(
                    atlan_client, input, assets_created
                )
                assets_created += wiki_pages_count
            else:
                with open(input.wiki_file.path, "r") as f:
                    for line in f:
                        page_data = json.loads(line)
                        page = WikiPageRecord(**page_data)
                        asset = map_wiki_page(page, conn_qn, content_mode=input.wiki_content_mode)
                        atlan_client.asset.save(asset)
                        assets_created += 1
                        wiki_pages_count += 1

        if input.yaml_file:
            if input.output_target == "glossary":
                glossary_qn = self._resolve_glossary_qn(atlan_client, input)
                with open(input.yaml_file.path, "r") as f:
                    for line in f:
                        yaml_data = json.loads(line)
                        yaml_rec = YamlFileRecord(**yaml_data)
                        term = map_yaml_file_as_term(yaml_rec, glossary_qn)
                        atlan_client.asset.save(term)
                        assets_created += 1
                        yaml_files_count += 1
            else:
                with open(input.yaml_file.path, "r") as f:
                    for line in f:
                        yaml_data = json.loads(line)
                        yaml_rec = YamlFileRecord(**yaml_data)
                        asset = map_yaml_file(yaml_rec, conn_qn, content_mode=input.yaml_content_mode)
                        atlan_client.asset.save(asset)
                        assets_created += 1
                        yaml_files_count += 1

        if input.sbom_file:
            with open(input.sbom_file.path, "r") as f:
                spdx_data = json.load(f)
                packages = spdx_data.get("packages", [])
                relationships = spdx_data.get("relationships", [])

                package_map = {}
                for pkg in packages:
                    dep = SbomDependencyRecord(
                        repo_full_name=spdx_data.get("name", "unknown/unknown"),
                        spdx_id=pkg.get("SPDXID"),
                        package_name=pkg.get("name"),
                        package_version=pkg.get("versionInfo"),
                        purl=pkg.get("externalRefs", [{}])[0].get("referenceLocator") if pkg.get("externalRefs") else None,
                        license_concluded=pkg.get("licenseConcluded"),
                        license_declared=pkg.get("licenseDeclared"),
                        supplier=pkg.get("supplier"),
                        download_location=pkg.get("downloadLocation"),
                        relationship_type="PACKAGE",
                        parent_spdx_id=None,
                    )
                    asset = map_sbom_dependency(dep, conn_qn)
                    atlan_client.asset.save(asset)
                    assets_created += 1
                    sbom_dependencies_count += 1
                    package_map[dep.spdx_id] = dep

                for rel in relationships:
                    if rel.get("relationshipType") == "DEPENDS_ON":
                        parent_id = rel.get("spdxElementId")
                        child_id = rel.get("relatedSpdxElement")

                        parent_dep = package_map.get(parent_id)
                        child_dep = package_map.get(child_id)

                        if parent_dep and child_dep:
                            child_dep_with_parent = SbomDependencyRecord(
                                **{**child_dep.__dict__, "parent_spdx_id": parent_id, "relationship_type": "DEPENDS_ON"}
                            )
                            process = map_sbom_relationship(child_dep_with_parent, parent_dep, conn_qn)
                            if process:
                                atlan_client.asset.save(process)
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

    # ─── Glossary helpers ─────────────────────────────────────────────

    def _org_from_wiki_file(self, wiki_file_path: str) -> Optional[str]:
        """Return the GitHub org from the first line of a wiki JSONL file."""
        try:
            with open(wiki_file_path, "r") as f:
                line = f.readline()
                if line:
                    data = json.loads(line)
                    full_name = data.get("repo_full_name", "")
                    return full_name.split("/")[0] if "/" in full_name else None
        except (OSError, json.JSONDecodeError, KeyError):
            return None
        return None

    def _resolve_glossary_qn(self, atlan_client, input: TransformInput) -> str:
        """Save (upsert) the glossary and return its server-assigned qualified_name."""
        org = input.glossary_name
        if not org and input.wiki_file:
            org = self._org_from_wiki_file(input.wiki_file.path)
        org = org or "github"
        glossary = map_glossary(org)
        response = atlan_client.asset.save(glossary)
        created = (response.mutated_entities.CREATE or []) if response.mutated_entities else []
        updated = (response.mutated_entities.UPDATE or []) if response.mutated_entities else []
        saved = (created + updated)
        if saved:
            return saved[0].qualified_name
        return glossary.qualified_name

    async def _transform_wiki_to_glossary(
        self, atlan_client, input: TransformInput, assets_so_far: int
    ) -> int:
        """Two-pass wiki -> glossary term transform."""
        glossary_qn = self._resolve_glossary_qn(atlan_client, input)

        sections: set[str] = set()
        pages: list[WikiPageRecord] = []
        with open(input.wiki_file.path, "r") as f:
            for line in f:
                page_data = json.loads(line)
                page = WikiPageRecord(**page_data)
                pages.append(page)
                section = page.wiki_section or _infer_wiki_section(page.page_name)
                if section:
                    sections.add(section)

        category_by_section: dict[str, object] = {}
        for section in sorted(sections):
            cat = map_glossary_category(section, glossary_qn)
            response = atlan_client.asset.save(cat)
            created = (response.mutated_entities.CREATE or []) if response.mutated_entities else []
            updated = (response.mutated_entities.UPDATE or []) if response.mutated_entities else []
            saved_cat = (created + updated)
            category_by_section[section] = saved_cat[0] if saved_cat else cat

        terms_created = 0
        for page in pages:
            section = page.wiki_section or _infer_wiki_section(page.page_name)
            category = category_by_section.get(section) if section else None
            term = map_wiki_page_as_term(page, glossary_qn, category=category)
            atlan_client.asset.save(term)
            terms_created += 1

        return terms_created


class GitHubConnectorHandler(DefaultHandler):
    """HTTP handler for the GitHub connector (auto-discovered by name convention).

    Canonical placement of auth/preflight: Handler operations, not workflow
    @entrypoints. Inherits DefaultHandler pass-through for preflight_check /
    fetch_metadata; overrides test_auth with real GitHub token validation.
    """

    async def test_auth(self, input: HandlerAuthInput) -> HandlerAuthOutput:
        """Validate a GitHub token from the submitted credentials."""
        token = ""
        for cred in input.credentials:
            if cred.key in ("token", "github_token", "password", "api_key"):
                token = cred.value
                break
        if not token and input.credentials:
            token = input.credentials[0].value

        result = await handle_auth(AuthInput(credential={"token": token}))
        status = AuthStatus.SUCCESS if result.status == "success" else AuthStatus.FAILED
        return HandlerAuthOutput(status=status)
