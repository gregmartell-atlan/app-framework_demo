"""Pure mapping functions from GitHub API records to pyatlan_v9 assets.

All mappers are stateless functions with no side effects.
"""

from typing import Optional

from pyatlan_v9.model.assets import Application, ApplicationField, Process, Readme
from pyatlan_v9.model.enums import AtlanConnectorType

from app.api_types import RepoRecord, WikiPageRecord, YamlFileRecord, SbomDependencyRecord


def map_repository(repo: RepoRecord, connection_qn: str) -> Application:
    """Map a GitHub repository to an Atlan Application asset.

    Args:
        repo: Repository record from GitHub API
        connection_qn: Atlan connection qualified name

    Returns:
        Application asset (not yet saved)
    """
    repo_qn = f"{connection_qn}/{repo.owner}/{repo.name}"

    app = Application.create(
        name=repo.name,
        connection_qualified_name=connection_qn,
    )
    app.qualified_name = repo_qn
    app.description = repo.description or ""
    app.application_type = "GitHub Repository"
    app.application_sub_type = repo.language or "Unknown"
    app.application_url = repo.html_url
    app.application_is_private = repo.is_private
    app.application_is_archived = repo.is_archived
    app.application_fork_count = repo.forks_count
    app.application_star_count = repo.stargazers_count
    app.application_watcher_count = repo.watchers_count
    app.application_open_issue_count = repo.open_issues_count
    app.source_url = repo.clone_url

    # Topics as tags
    if repo.topics:
        app.atlan_tags = repo.topics

    # Created/updated timestamps (if supported by pyatlan_v9)
    # app.created_at = repo.created_at  # Uncomment if available
    # app.updated_at = repo.updated_at

    return app


def map_readme(repo: RepoRecord, readme_content: str, connection_qn: str) -> Readme:
    """Map a repository's README to an Atlan Readme asset.

    Args:
        repo: Repository record
        readme_content: README markdown content
        connection_qn: Atlan connection qualified name

    Returns:
        Readme asset attached to the repository
    """
    repo_qn = f"{connection_qn}/{repo.owner}/{repo.name}"

    readme = Readme.create(
        name=f"{repo.name} README",
        connection_qualified_name=connection_qn,
        asset_qualified_name=repo_qn,  # Attach to the repo Application asset
    )
    readme.description = f"README for {repo.full_name}"
    readme.readme_content = readme_content

    return readme


def map_wiki_page(page: WikiPageRecord, connection_qn: str) -> ApplicationField:
    """Map a GitHub wiki page to an Atlan ApplicationField asset.

    Args:
        page: Wiki page record
        connection_qn: Atlan connection qualified name

    Returns:
        ApplicationField asset representing the wiki page
    """
    # Parent repo QN
    repo_owner, repo_name = page.repo_full_name.split("/", 1)
    repo_qn = f"{connection_qn}/{repo_owner}/{repo_name}"

    # Wiki page QN
    page_qn = f"{connection_qn}/{page.repo_full_name}/wiki/{page.page_path}"

    field = ApplicationField.create(
        name=page.page_name,
        connection_qualified_name=connection_qn,
        application_qualified_name=repo_qn,  # Parent is the repo Application
    )
    field.qualified_name = page_qn
    field.description = f"Wiki page: {page.page_path}"
    field.application_field_type = "wiki_page"
    field.application_field_format = "markdown"

    # Store markdown content (if ApplicationField supports a raw content field)
    # Otherwise, use description or a custom attribute
    if hasattr(field, "application_field_value"):
        field.application_field_value = page.content
    else:
        # Fallback: truncate for description
        field.description = page.content[:500] + ("..." if len(page.content) > 500 else "")

    # Reference parent via uniqueAttributes.qualifiedName (V2 verification rule)
    field.application = Application.ref_by_qualified_name(repo_qn)

    return field


def map_yaml_file(yaml: YamlFileRecord, connection_qn: str) -> ApplicationField:
    """Map a YAML configuration file to an Atlan ApplicationField asset.

    Args:
        yaml: YAML file record
        connection_qn: Atlan connection qualified name

    Returns:
        ApplicationField asset representing the YAML file
    """
    repo_owner, repo_name = yaml.repo_full_name.split("/", 1)
    repo_qn = f"{connection_qn}/{repo_owner}/{repo_name}"

    yaml_qn = f"{connection_qn}/{yaml.repo_full_name}/yaml/{yaml.file_path}"

    field = ApplicationField.create(
        name=yaml.file_path.split("/")[-1],  # Just the filename
        connection_qualified_name=connection_qn,
        application_qualified_name=repo_qn,
    )
    field.qualified_name = yaml_qn
    field.description = f"YAML configuration file: {yaml.file_path}"
    field.application_field_type = "config_file"
    field.application_field_format = "yaml"

    # Store YAML content
    if hasattr(field, "application_field_value"):
        field.application_field_value = yaml.content
    else:
        field.description = yaml.content[:500] + ("..." if len(yaml.content) > 500 else "")

    # Reference parent
    field.application = Application.ref_by_qualified_name(repo_qn)

    return field


# ============================================================================
# SBOM mappers (Phase 2)
# ============================================================================

def map_sbom_dependency(dep: SbomDependencyRecord, connection_qn: str) -> ApplicationField:
    """Map an SBOM dependency to an Atlan ApplicationField asset.

    Args:
        dep: SBOM dependency record (from SPDX JSON)
        connection_qn: Atlan connection qualified name

    Returns:
        ApplicationField asset representing the dependency package
    """
    repo_owner, repo_name = dep.repo_full_name.split("/", 1)
    repo_qn = f"{connection_qn}/{repo_owner}/{repo_name}"

    dep_qn = f"{connection_qn}/{dep.repo_full_name}/dep/{dep.spdx_id}"

    field = ApplicationField.create(
        name=dep.package_name,
        connection_qualified_name=connection_qn,
        application_qualified_name=repo_qn,
    )
    field.qualified_name = dep_qn
    field.description = f"SBOM dependency: {dep.package_name} {dep.package_version or ''}"
    field.application_field_type = "sbom_dependency"
    field.application_field_format = "spdx"

    # Store structured metadata (if supported)
    # Custom attributes: purl, license, supplier, etc.
    if hasattr(field, "application_field_value"):
        field.application_field_value = dep.purl or dep.spdx_id

    # Reference parent repo
    field.application = Application.ref_by_qualified_name(repo_qn)

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

    repo_owner, repo_name = dep.repo_full_name.split("/", 1)
    repo_qn = f"{connection_qn}/{repo_owner}/{repo_name}"

    parent_qn = f"{connection_qn}/{parent_dep.repo_full_name}/dep/{parent_dep.spdx_id}"
    child_qn = f"{connection_qn}/{dep.repo_full_name}/dep/{dep.spdx_id}"

    # Process QN includes both parent and child
    process_qn = f"{parent_qn}/depends_on/{dep.spdx_id}"

    process = Process.create(
        name=f"{parent_dep.package_name} → {dep.package_name}",
        connection_qualified_name=connection_qn,
    )
    process.qualified_name = process_qn
    process.description = f"Dependency relationship: {parent_dep.package_name} depends on {dep.package_name}"

    # Process inputs/outputs via uniqueAttributes.qualifiedName refs (V2 verification rule)
    process.inputs = [ApplicationField.ref_by_qualified_name(parent_qn)]
    process.outputs = [ApplicationField.ref_by_qualified_name(child_qn)]

    return process
