"""GitHub App Framework v3 connector.

Main App subclass with @entrypoint and @task decorated methods.
Activity naming: github:task_name (verified by v3-readiness workflow).
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

from typing import ClassVar

from application_sdk.app import App, task, entrypoint
from pyatlan_v9.client.atlan import AtlanClient

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
    AuthOutput,
    PreflightInput,
    PreflightOutput,
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
from app.handler import handle_auth, handle_preflight, handle_glossary_sync


class GitHubConnector(App):
    """Atlan GitHub connector — extracts repos, wikis, YAML files, and SBOMs.

    v3-compliant:
    - Extends App (BaseMetadataExtractor pattern)
    - Uses @entrypoint for handlers
    - Uses @task for async activities
    - All methods have typed Input/Output (no bare Dict/Any)
    """

    name: ClassVar[str] = "github"
    version: ClassVar[str] = "1.0.0"

    @entrypoint
    async def auth(self, input: AuthInput) -> AuthOutput:
        """Authentication handler.

        Validates GitHub credentials by calling the /user endpoint.
        """
        return await handle_auth(input)

    @entrypoint
    async def preflight(self, input: PreflightInput) -> PreflightOutput:
        """Preflight handler.

        Validates organization access, scopes, and rate limits.
        """
        return await handle_preflight(input)

    @task(name="github:fetch_repos")
    async def fetch_repos(self, input: GitHubExtractionInput) -> GitHubExtractionOutput:
        """Fetch repositories from GitHub.

        Extracts repos, and optionally wikis/YAML files based on input flags.
        Does NOT handle SBOM (that's a separate task due to async generation).

        Args:
            input: GitHubExtractionInput with org, repo filter, extraction flags

        Returns:
            GitHubExtractionOutput with file references and counts
        """
        token = input.credential.get("token")
        cred = GitHubTokenCredential(token=token)

        output_dir = Path(self.task_context.working_directory) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        repos_file = output_dir / "repos.jsonl"
        wiki_file = output_dir / "wiki_pages.jsonl"
        yaml_file = output_dir / "yaml_files.jsonl"

        repos_count = 0
        wiki_pages_count = 0
        yaml_files_count = 0

        async with GitHubClient(cred, concurrency_limit=8) as client:
            # Fetch repos
            with open(repos_file, "w") as rf:
                async for repo in client.list_repos(input.organization, max_items=input.max_items.max_items):
                    # Filter by specific repos if provided
                    if input.repositories and repo.name not in input.repositories:
                        continue

                    rf.write(json.dumps(repo.__dict__) + "\n")
                    repos_count += 1

                    # Extract wiki if enabled
                    if input.extract_wiki and repo.has_wiki:
                        try:
                            async for wiki_page in client.clone_wiki(repo.full_name, self.task_context):
                                with open(wiki_file, "a") as wf:
                                    wf.write(json.dumps(wiki_page.__dict__) + "\n")
                                    wiki_pages_count += 1
                        except Exception as e:
                            # Wiki clone failed (not initialized, network error, etc.) — log and continue
                            self.logger.warning(f"Failed to clone wiki for {repo.full_name}: {e}")

                    # Extract YAML files if enabled
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
            sbom_file=None,  # SBOM handled separately
            extraction_summary=f"Extracted {repos_count} repos, {wiki_pages_count} wiki pages, {yaml_files_count} YAML files",
            repos_count=repos_count,
            wiki_pages_count=wiki_pages_count,
            yaml_files_count=yaml_files_count,
        )

    @task(
        name="github:fetch_sbom",
        timeout_seconds=3600,
        heartbeat_timeout_seconds=120,
        auto_heartbeat_seconds=10,
        retry_max_attempts=3,
    )
    async def fetch_sbom(self, input: FetchSbomInput) -> FetchSbomOutput:
        """Fetch SBOM (Software Bill of Materials) for repositories.

        Phase 2 addition. Uses typed heartbeat (SbomProgress) for resume support.
        Implements exponential backoff polling capped at 300s per design debate Topic 3.

        Args:
            input: FetchSbomInput with repos list, credential, poll interval

        Returns:
            FetchSbomOutput with SBOM file references and summary
        """
        token = input.credential.get("token")
        cred = GitHubTokenCredential(token=token)

        output_dir = Path(input.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        successful_repos = []
        failed_repos = []
        sbom_files = []

        # Check for previous heartbeat (resume support)
        prev_progress: Optional[SbomProgress] = await self.task_context.get_heartbeat_details(SbomProgress)
        skip_until = prev_progress.repo_full_name if prev_progress else None

        async with GitHubClient(cred, concurrency_limit=4) as client:  # Lower concurrency for SBOM (heavy operation)
            for repo_full_name in input.repositories:
                # Skip already-completed repos on resume
                if skip_until and repo_full_name != skip_until:
                    continue
                if skip_until == repo_full_name:
                    skip_until = None  # Start processing from here

                sbom_output_file = output_dir / f"{repo_full_name.replace('/', '_')}_sbom.json"

                # Skip if already downloaded (idempotent resume)
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
                    # Kick off SBOM generation
                    report_id = await client.start_sbom_report(repo_full_name)
                    started_at = self.task_context.current_time_iso()

                    # Heartbeat with current progress
                    await self.task_context.heartbeat(SbomProgress(
                        repo_full_name=repo_full_name,
                        report_id=report_id,
                        started_at_iso=started_at,
                        poll_attempts=0,
                    ))

                    # Poll for completion with exponential backoff
                    initial_interval = input.poll_interval_seconds
                    poll_attempts = 0
                    max_attempts = 20  # ~1 hour with exponential backoff

                    while poll_attempts < max_attempts:
                        await asyncio.sleep(min(initial_interval * (2 ** poll_attempts), 300))  # Cap at 300s

                        try:
                            status = await client.get_sbom_report_status(repo_full_name)
                            if status == "complete":
                                break
                        except SbomReportPending:
                            poll_attempts += 1
                            await self.task_context.heartbeat(SbomProgress(
                                repo_full_name=repo_full_name,
                                report_id=report_id,
                                started_at_iso=started_at,
                                poll_attempts=poll_attempts,
                            ))
                            continue

                    # Download SBOM to file
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

    @task(name="github:transform")
    async def transform(self, input: TransformInput) -> TransformOutput:
        """Transform GitHub records to Atlan assets.

        Reads JSONL files from extraction, maps to pyatlan_v9 assets, and writes them
        to Atlan via the client.

        Args:
            input: TransformInput with file references and connection QN

        Returns:
            TransformOutput with asset counts
        """
        atlan_client = self.task_context.atlan_client
        conn_qn = input.connection_qualified_name

        assets_created = 0
        repos_count = 0
        wiki_pages_count = 0
        yaml_files_count = 0
        sbom_dependencies_count = 0
        sbom_relationships_count = 0

        # Transform repos
        if input.repos_file:
            with open(input.repos_file.path, "r") as f:
                for line in f:
                    repo_data = json.loads(line)
                    repo = RepoRecord(**repo_data)
                    asset = map_repository(repo, conn_qn)

                    # Save to Atlan
                    response = atlan_client.asset.save(asset)
                    assets_created += 1
                    repos_count += 1

        # Transform wiki pages
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

        # Transform YAML files
        if input.yaml_file:
            if input.output_target == "glossary":
                # Requires glossary to exist — resolve QN then emit uncategorized terms
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

        # Transform SBOM dependencies (Phase 2)
        if input.sbom_file:
            # Parse SPDX JSON and extract packages + relationships
            # This is a simplified version — real SPDX parsing is more complex
            with open(input.sbom_file.path, "r") as f:
                spdx_data = json.load(f)
                packages = spdx_data.get("packages", [])
                relationships = spdx_data.get("relationships", [])

                # Map packages to ApplicationField assets
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
                    response = atlan_client.asset.save(asset)
                    assets_created += 1
                    sbom_dependencies_count += 1
                    package_map[dep.spdx_id] = dep

                # Map relationships to Process assets
                for rel in relationships:
                    if rel.get("relationshipType") == "DEPENDS_ON":
                        parent_id = rel.get("spdxElementId")
                        child_id = rel.get("relatedSpdxElement")

                        parent_dep = package_map.get(parent_id)
                        child_dep = package_map.get(child_id)

                        if parent_dep and child_dep:
                            # Create child dep with parent reference
                            child_dep_with_parent = SbomDependencyRecord(
                                **{**child_dep.__dict__, "parent_spdx_id": parent_id, "relationship_type": "DEPENDS_ON"}
                            )
                            process = map_sbom_relationship(child_dep_with_parent, parent_dep, conn_qn)
                            if process:
                                response = atlan_client.asset.save(process)
                                assets_created += 1
                                sbom_relationships_count += 1

        return TransformOutput(
            assets_created=assets_created,
            assets_updated=0,  # For now, assuming all are creates (no upsert logic yet)
            repos_count=repos_count,
            wiki_pages_count=wiki_pages_count,
            yaml_files_count=yaml_files_count,
            sbom_dependencies_count=sbom_dependencies_count,
            sbom_relationships_count=sbom_relationships_count,
        )

    # ─── Glossary helpers ────────────────────────────────────────────────────

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
        """Two-pass wiki → glossary term transform.

        Pass 1: collect all unique wiki sections → save glossary + one category per section.
        Pass 2: save one GlossaryTerm per wiki page, linked to its category.

        Returns the number of terms created.
        """
        glossary_qn = self._resolve_glossary_qn(atlan_client, input)

        # Pass 1: collect unique sections
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

        # Save categories and build lookup
        category_by_section: dict[str, object] = {}
        for section in sorted(sections):
            cat = map_glossary_category(section, glossary_qn)
            response = atlan_client.asset.save(cat)
            created = (response.mutated_entities.CREATE or []) if response.mutated_entities else []
            updated = (response.mutated_entities.UPDATE or []) if response.mutated_entities else []
            saved_cat = (created + updated)
            category_by_section[section] = saved_cat[0] if saved_cat else cat

        # Pass 2: save terms
        terms_created = 0
        for page in pages:
            from app.glossary_mapper import _infer_wiki_section
            section = page.wiki_section or _infer_wiki_section(page.page_name)
            category = category_by_section.get(section) if section else None
            term = map_wiki_page_as_term(page, glossary_qn, category=category)
            atlan_client.asset.save(term)
            terms_created += 1

        return terms_created

    # ─── Option C: standalone glossary sync task ────────────────────────────
    #
    # Additive task — does not touch the existing extract/transform DAG.
    # Calls the shared sync routine in app.glossary_sync so behaviour matches
    # Option A (workflow) and Option B (script) exactly.

    @task(name="github:sync_glossary", timeout_seconds=1800, retry_max_attempts=2)
    async def sync_glossary(self, input: GlossarySyncInput) -> GlossarySyncOutput:
        """Sync a GitHub wiki to an Atlan glossary (additive, side-effect-free of existing DAG)."""
        return await handle_glossary_sync(input)
