"""Pure mapping functions from GitHub API records to pyatlan_v9 assets.

All mappers are stateless functions with no side effects.

Attribute reference (pyatlan_v9 Application / ApplicationField):
  Type-specific scalars — Application : app_id, catalog_dataset_guid
  Type-specific scalars — ApplicationField : application_parent_qualified_name,
                                              app_id, catalog_dataset_guid
  Inherited from Asset (used here) : description, source_url, display_name,
                                      source_created_at (epoch ms), source_updated_at (epoch ms),
                                      source_created_by, asset_tags, user_description,
                                      connection_qualified_name, connector_name

  No applicationFieldType / applicationFieldFormat fields exist in the typedef.
  GitHub-specific metadata without a typedef field (language, star_count, is_private,
  forks_count, etc.) is stored in user_description as a compact key=value string so
  it is searchable in Atlan's UI full-text index.
"""

import json
import re
from datetime import datetime, timezone
from typing import Optional

import yaml as _yaml
from pyatlan_v9.model.assets import Application, ApplicationField, Process, Readme

from app.api_types import RepoRecord, WikiPageRecord, YamlFileRecord, SbomDependencyRecord


def _iso_to_epoch_ms(iso: Optional[str]) -> Optional[int]:
    """Convert ISO 8601 timestamp string to epoch milliseconds (int)."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (ValueError, AttributeError):
        return None


def _repo_user_description(repo: RepoRecord) -> str:
    """Pack GitHub-specific metadata that has no typedef field into a compact string."""
    parts = []
    if repo.language:
        parts.append(f"language={repo.language}")
    parts.append(f"stars={repo.stargazers_count}")
    parts.append(f"forks={repo.forks_count}")
    parts.append(f"open_issues={repo.open_issues_count}")
    if repo.is_private:
        parts.append("visibility=private")
    else:
        parts.append("visibility=public")
    if repo.is_archived:
        parts.append("archived=true")
    if repo.is_fork:
        parts.append("fork=true")
    if repo.license_name:
        parts.append(f"license={repo.license_name}")
    return " | ".join(parts)


def map_repository(repo: RepoRecord, connection_qn: str) -> Application:
    """Map a GitHub repository to an Atlan Application asset.

    Sets all available typedef fields:
    - app_id        → GitHub numeric repo ID (unique source identifier)
    - display_name  → full_name ("owner/repo") for UI clarity
    - description   → GitHub repo description
    - source_url    → HTML URL
    - source_created_at / source_updated_at → epoch ms timestamps
    - source_created_by → repo owner login
    - asset_tags    → GitHub topics
    - user_description → packed metadata (language, stars, forks, visibility, …)

    Args:
        repo: Repository record from GitHub API
        connection_qn: Atlan connection qualified name

    Returns:
        Application asset (not yet saved)
    """
    repo_qn = f"{connection_qn}/{repo.owner}/{repo.name}"

    app = Application.creator(
        name=repo.name,
        connection_qualified_name=connection_qn,
    )
    app.qualified_name = repo_qn

    # Core typedef fields
    app.app_id = str(repo.id) if repo.id else None
    app.display_name = repo.full_name
    app.description = repo.description or ""
    app.source_url = repo.html_url
    app.source_created_by = repo.owner
    app.source_created_at = _iso_to_epoch_ms(repo.created_at)
    # pushed_at reflects the last code push — more accurate for code currency than updated_at
    # (updated_at changes on metadata edits; pushed_at only changes when commits land)
    app.source_updated_at = _iso_to_epoch_ms(repo.pushed_at)

    # Private repos should not surface in Atlan's default discovery view
    if repo.is_private:
        app.is_discoverable = False

    # GitHub topics → Atlan asset_tags
    if repo.topics:
        app.asset_tags = repo.topics

    # Pack GitHub-specific metadata that has no dedicated typedef field
    app.user_description = _repo_user_description(repo)

    return app


def _parse_wiki_structured(content: str) -> dict:
    """Extract structured catalog fields from wiki markdown.

    Checks two conventions in order:
    1. YAML frontmatter  (--- key: value --- block at top of page)
    2. ## Header patterns  (## Owner\\nvalue\\n, ## Domain\\nvalue\\n, …)

    Returns a dict with any of: owner, domain, description, tags (list[str]).
    Unknown keys are ignored so callers don't have to guard every field.
    """
    result: dict = {}

    # 1. YAML frontmatter
    if content.lstrip().startswith("---"):
        body = content.lstrip()
        end = body.find("---", 3)
        if end != -1:
            try:
                fm = _yaml.safe_load(body[3:end])
                if isinstance(fm, dict):
                    result.update({k: v for k, v in fm.items() if v is not None})
            except Exception:
                pass

    # 2. ## Header patterns (supplement / override frontmatter)
    catalog_keys = {"owner", "domain", "description", "tags", "steward", "team"}
    for match in re.finditer(r"^##\s+(\w[\w\s]*\w|\w)\s*\n([^\n#]+)", content, re.MULTILINE):
        key = match.group(1).strip().lower().replace(" ", "_")
        value = match.group(2).strip()
        if key in catalog_keys and value:
            result[key] = value

    # Normalise tags to list[str]
    if "tags" in result and isinstance(result["tags"], str):
        result["tags"] = [t.strip() for t in result["tags"].split(",") if t.strip()]

    return result


def _parse_yaml_catalog(content: str) -> dict:
    """Extract catalog metadata fields from YAML content.

    Recognises common catalog-manifest key names used by teams who keep
    schema.yaml / catalog.yaml / ownership.yaml files in git:

        owner / team / maintainer  → owner
        domain / domain_area / business_domain → domain
        description / summary / purpose → description
        tags / labels  → tags (list[str])

    Returns only keys that have non-None values so callers can use .get().
    Falls back gracefully to {} on parse errors or non-dict YAML.
    """
    try:
        data = _yaml.safe_load(content)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}

    def _first(*keys):
        for k in keys:
            if data.get(k):
                return data[k]
        return None

    owner = _first("owner", "team", "maintainer")
    domain = _first("domain", "domain_area", "business_domain")
    description = _first("description", "summary", "purpose")
    tags = _first("tags", "labels")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    elif not isinstance(tags, list):
        tags = None

    return {k: v for k, v in {
        "owner": owner,
        "domain": domain,
        "description": description,
        "tags": tags,
    }.items() if v is not None}


def map_readme(repo: RepoRecord, readme_content: str, connection_qn: str) -> Readme:
    """Map a repository's README to an Atlan Readme asset.

    Readme.creator() requires the parent Application as a real instance (with
    a GUID), not a ref-by-qualified-name. We rebuild the Application object
    with the same identity used by map_repository so Atlan resolves them to
    the same asset on the server side.

    Args:
        repo: Repository record
        readme_content: README markdown content
        connection_qn: Atlan connection qualified name

    Returns:
        Readme asset attached to the repository (description = README content)
    """
    repo_qn = f"{connection_qn}/{repo.owner}/{repo.name}"

    app = Application.creator(
        name=repo.name,
        connection_qualified_name=connection_qn,
    )
    app.qualified_name = repo_qn

    # asset_name must NOT be passed when the parent Application already has a name
    readme = Readme.creator(asset=app, content=readme_content)

    return readme


def map_wiki_page(
    page: WikiPageRecord,
    connection_qn: str,
    content_mode: str = "index",
) -> ApplicationField:
    """Map a GitHub wiki page to an Atlan ApplicationField asset.

    - app_id       → git blob SHA (stable unique source ID for this page version)
    - description  → controlled by content_mode (see below)
    - user_description → "wiki_page | {repo_full_name}" (plus parsed fields in parse mode)

    content_mode values:
        "index" — truncates content to 500 chars (default, low storage cost)
        "full"  — stores complete markdown content
        "parse" — extracts structured fields from YAML frontmatter or ## Header
                  patterns (owner, domain, tags) and maps to Atlan attributes;
                  falls back to full content if no structure found

    Args:
        page: Wiki page record
        connection_qn: Atlan connection qualified name
        content_mode: One of "index", "full", "parse"

    Returns:
        ApplicationField asset representing the wiki page
    """
    repo_owner, repo_name = page.repo_full_name.split("/", 1)
    repo_qn = f"{connection_qn}/{repo_owner}/{repo_name}"
    page_qn = f"{connection_qn}/{page.repo_full_name}/wiki/{page.page_path}"

    field = ApplicationField.creator(
        name=page.page_name,
        application_qualified_name=repo_qn,
        connection_qualified_name=connection_qn,
    )
    field.qualified_name = page_qn
    field.app_id = page.file_sha

    if content_mode == "full":
        field.description = page.content
        field.user_description = f"wiki_page | {page.repo_full_name}"

    elif content_mode == "parse":
        parsed = _parse_wiki_structured(page.content)
        field.description = parsed.get("description") or page.content
        ud_parts = [f"wiki_page | {page.repo_full_name}"]
        if parsed.get("owner"):
            ud_parts.append(f"owner={parsed['owner']}")
        if parsed.get("domain"):
            ud_parts.append(f"domain={parsed['domain']}")
        field.user_description = " | ".join(ud_parts)
        if parsed.get("tags"):
            field.asset_tags = [str(t) for t in parsed["tags"]]

    else:  # index (default)
        field.description = page.content[:500] + ("..." if len(page.content) > 500 else "")
        field.user_description = f"wiki_page | {page.repo_full_name}"

    return field


def map_yaml_file(
    yaml: YamlFileRecord,
    connection_qn: str,
    content_mode: str = "index",
) -> ApplicationField:
    """Map a YAML configuration file to an Atlan ApplicationField asset.

    - app_id       → git blob SHA
    - description  → controlled by content_mode (see below)
    - user_description → "config_file | yaml | {repo_full_name}" (plus parsed fields)

    content_mode values:
        "index" — stores "YAML configuration file: {path}" as description (default)
        "full"  — stores the complete raw YAML content as description
        "parse" — extracts catalog metadata keys (owner, domain, description, tags)
                  from the YAML and maps them to Atlan attributes; ideal for
                  catalog.yaml / schema.yaml / ownership.yaml patterns

    Args:
        yaml: YAML file record
        connection_qn: Atlan connection qualified name
        content_mode: One of "index", "full", "parse"

    Returns:
        ApplicationField asset representing the YAML file
    """
    repo_owner, repo_name = yaml.repo_full_name.split("/", 1)
    repo_qn = f"{connection_qn}/{repo_owner}/{repo_name}"
    yaml_qn = f"{connection_qn}/{yaml.repo_full_name}/yaml/{yaml.file_path}"

    field = ApplicationField.creator(
        name=yaml.file_path.split("/")[-1],
        application_qualified_name=repo_qn,
        connection_qualified_name=connection_qn,
    )
    field.qualified_name = yaml_qn
    field.app_id = yaml.file_sha

    if content_mode == "full":
        field.description = yaml.content
        field.user_description = f"config_file | yaml | {yaml.repo_full_name}"

    elif content_mode == "parse":
        parsed = _parse_yaml_catalog(yaml.content)
        field.description = parsed.get("description") or f"YAML configuration file: {yaml.file_path}"
        ud_parts = [f"config_file | yaml | {yaml.repo_full_name}"]
        if parsed.get("owner"):
            ud_parts.append(f"owner={parsed['owner']}")
        if parsed.get("domain"):
            ud_parts.append(f"domain={parsed['domain']}")
        field.user_description = " | ".join(ud_parts)
        if parsed.get("tags"):
            field.asset_tags = [str(t) for t in parsed["tags"]]

    else:  # index (default)
        field.description = f"YAML configuration file: {yaml.file_path}"
        field.user_description = f"config_file | yaml | {yaml.repo_full_name}"

    return field


# ============================================================================
# SBOM mappers (Phase 2)
# ============================================================================

def map_sbom_dependency(dep: SbomDependencyRecord, connection_qn: str) -> ApplicationField:
    """Map an SBOM dependency to an Atlan ApplicationField asset.

    - app_id       → SPDX ID (stable source-system identifier)
    - description  → "SBOM dependency: {name} {version}"
    - source_url   → purl (package URL — most stable external identifier)
    - user_description → "sbom_dependency | spdx | {repo_full_name} | license={license}"

    Args:
        dep: SBOM dependency record (from SPDX JSON)
        connection_qn: Atlan connection qualified name

    Returns:
        ApplicationField asset representing the dependency package
    """
    repo_owner, repo_name = dep.repo_full_name.split("/", 1)
    repo_qn = f"{connection_qn}/{repo_owner}/{repo_name}"
    dep_qn = f"{connection_qn}/{dep.repo_full_name}/dep/{dep.spdx_id}"

    field = ApplicationField.creator(
        name=dep.package_name,
        application_qualified_name=repo_qn,
        connection_qualified_name=connection_qn,
    )
    field.qualified_name = dep_qn
    field.app_id = dep.spdx_id
    field.description = f"SBOM dependency: {dep.package_name} {dep.package_version or ''}"
    if dep.purl:
        field.source_url = dep.purl

    license_info = dep.license_concluded or dep.license_declared or "unknown"
    field.user_description = (
        f"sbom_dependency | spdx | {dep.repo_full_name} | license={license_info}"
    )

    return field


def map_sbom_relationship(
    dep: SbomDependencyRecord,
    parent_dep: Optional[SbomDependencyRecord],
    connection_qn: str,
) -> Optional[Process]:
    """Map an SBOM DEPENDS_ON relationship to an Atlan Process asset.

    Args:
        dep: Child dependency (the one that depends on parent)
        parent_dep: Parent dependency (None if this is a top-level dependency)
        connection_qn: Atlan connection qualified name

    Returns:
        Process asset representing the dependency edge, or None if no parent
    """
    if not parent_dep or dep.relationship_type != "DEPENDS_ON":
        return None

    parent_qn = f"{connection_qn}/{parent_dep.repo_full_name}/dep/{parent_dep.spdx_id}"
    child_qn = f"{connection_qn}/{dep.repo_full_name}/dep/{dep.spdx_id}"
    process_qn = f"{parent_qn}/depends_on/{dep.spdx_id}"

    process = Process.creator(
        name=f"{parent_dep.package_name} → {dep.package_name}",
        connection_qualified_name=connection_qn,
        inputs=[ApplicationField.ref_by_qualified_name(parent_qn)],
        outputs=[ApplicationField.ref_by_qualified_name(child_qn)],
    )
    process.qualified_name = process_qn
    process.description = (
        f"Dependency relationship: {parent_dep.package_name} depends on {dep.package_name}"
    )

    return process
