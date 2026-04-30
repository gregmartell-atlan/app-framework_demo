"""Frozen dataclasses representing GitHub API response records.

These are pure data transfer objects with no business logic, used as
an intermediate representation between the GitHub REST API and Atlan assets.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RepoRecord:
    """GitHub repository metadata."""

    full_name: str  # e.g., "atlanhq/atlan-python"
    name: str  # e.g., "atlan-python"
    owner: str  # e.g., "atlanhq"
    description: Optional[str]
    html_url: str
    clone_url: str
    default_branch: str
    language: Optional[str]
    is_private: bool
    is_fork: bool
    is_archived: bool
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601
    pushed_at: str  # ISO 8601
    size_kb: int
    stargazers_count: int
    watchers_count: int
    forks_count: int
    open_issues_count: int
    topics: list[str]
    license_name: Optional[str]
    has_wiki: bool
    has_issues: bool
    has_projects: bool
    has_downloads: bool
    id: int = 0  # GitHub numeric repo ID — used as app_id in Atlan


@dataclass(frozen=True)
class WikiPageRecord:
    """GitHub wiki page content."""

    repo_full_name: str  # e.g., "atlanhq/atlan-python"
    page_path: str  # relative path within wiki, e.g., "Home.md"
    page_name: str  # e.g., "Home"
    content: str  # markdown content
    file_sha: Optional[str]  # git SHA if available


@dataclass(frozen=True)
class YamlFileRecord:
    """YAML configuration file from a repository."""

    repo_full_name: str
    file_path: str  # e.g., ".github/workflows/ci.yml"
    content: str  # raw YAML content
    file_sha: str  # git blob SHA
    file_size_bytes: int


@dataclass(frozen=True)
class SbomDependencyRecord:
    """SBOM dependency extracted from GitHub's SBOM API (SPDX format).

    Phase 2 addition: represents a package/dependency node and its relationships.
    """

    repo_full_name: str  # e.g., "atlanhq/atlan-python"
    spdx_id: str  # e.g., "SPDXRef-Package-pip-requests-2.28.0"
    package_name: str  # e.g., "requests"
    package_version: Optional[str]  # e.g., "2.28.0"
    purl: Optional[str]  # Package URL, e.g., "pkg:pypi/requests@2.28.0"
    license_concluded: Optional[str]  # e.g., "Apache-2.0"
    license_declared: Optional[str]
    supplier: Optional[str]  # e.g., "Organization: Python Software Foundation"
    download_location: Optional[str]  # e.g., "https://pypi.org/project/requests/"
    relationship_type: str  # e.g., "DEPENDS_ON", "CONTAINS"
    parent_spdx_id: Optional[str]  # SPDX ID of the parent package (for DEPENDS_ON relationships)
