"""Pure mapping functions from GitHub API records to pyatlan_v9 assets.

All mappers are stateless functions with no side effects.
"""

from typing import Optional

from pyatlan_v9.model.assets import Application, ApplicationField, Process, Readme

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

    app = Application.creator(
        name=repo.name,
        connection_qualified_name=connection_qn,
    )
    app.qualified_name = repo_qn
    app.description = repo.description or ""
    app.source_url = repo.html_url

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

    app_ref = Application.ref_by_qualified_name(repo_qn)
    readme = Readme.creator(
        asset=app_ref,
        content=readme_content,
        asset_name=repo.name,
    )
    readme.description = f"README for {repo.full_name}"

    return readme


def map_wiki_page(page: WikiPageRecord, connection_qn: str) -> ApplicationField:
    """Map a GitHub wiki page to an Atlan ApplicationField asset.

    Args:
        page: Wiki page record
        connection_qn: Atlan connection qualified name

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
    field.description = page.content[:500] + ("..." if len(page.content) > 500 else "")

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

    field = ApplicationField.creator(
        name=yaml.file_path.split("/")[-1],
        application_qualified_name=repo_qn,
        connection_qualified_name=connection_qn,
    )
    field.qualified_name = yaml_qn
    field.description = f"YAML configuration file: {yaml.file_path}"

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

    field = ApplicationField.creator(
        name=dep.package_name,
        application_qualified_name=repo_qn,
        connection_qualified_name=connection_qn,
    )
    field.qualified_name = dep_qn
    field.description = f"SBOM dependency: {dep.package_name} {dep.package_version or ''}"
    if dep.purl:
        field.source_url = dep.purl

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
    process.description = f"Dependency relationship: {parent_dep.package_name} depends on {dep.package_name}"

    return process
