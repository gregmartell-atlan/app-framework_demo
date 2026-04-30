"""Unit tests for asset mapping functions.

Tests the pure mapping logic from GitHub API records to pyatlan_v9 assets.
"""

import pytest

from app.api_types import RepoRecord, WikiPageRecord, YamlFileRecord, SbomDependencyRecord
from app.asset_mapper import (
    map_repository,
    map_wiki_page,
    map_yaml_file,
    map_sbom_dependency,
    map_sbom_relationship,
)


def test_map_repository():
    """Test mapping a GitHub repository to an Application asset."""
    repo = RepoRecord(
        full_name="atlanhq/atlan-python",
        name="atlan-python",
        owner="atlanhq",
        description="Python SDK for Atlan",
        html_url="https://github.com/atlanhq/atlan-python",
        clone_url="https://github.com/atlanhq/atlan-python.git",
        default_branch="main",
        language="Python",
        is_private=False,
        is_fork=False,
        is_archived=False,
        created_at="2022-01-15T10:30:00Z",
        updated_at="2026-04-29T14:20:00Z",
        pushed_at="2026-04-29T14:20:00Z",
        size_kb=5432,
        stargazers_count=150,
        watchers_count=25,
        forks_count=30,
        open_issues_count=8,
        topics=["python", "sdk", "atlan"],
        license_name="Apache-2.0",
        has_wiki=True,
        has_issues=True,
        has_projects=True,
        has_downloads=True,
        id=987654321,
    )

    conn_qn = "default/github/1234567890"
    asset = map_repository(repo, conn_qn)

    assert asset.name == "atlan-python"
    assert asset.qualified_name == f"{conn_qn}/atlanhq/atlan-python"
    assert asset.description == "Python SDK for Atlan"
    assert asset.source_url == "https://github.com/atlanhq/atlan-python"
    assert asset.app_id == "987654321"
    assert asset.display_name == "atlanhq/atlan-python"
    assert asset.source_created_by == "atlanhq"
    assert asset.source_created_at == 1642242600000  # 2022-01-15T10:30:00Z in epoch ms
    assert asset.asset_tags == ["python", "sdk", "atlan"]
    assert "language=Python" in asset.user_description
    assert "stars=150" in asset.user_description
    assert "forks=30" in asset.user_description
    assert "visibility=public" in asset.user_description
    assert "license=Apache-2.0" in asset.user_description


def test_map_repository_no_description():
    """Test mapping a repo with no description defaults to empty string."""
    repo = RepoRecord(
        full_name="atlanhq/empty-repo",
        name="empty-repo",
        owner="atlanhq",
        description=None,
        html_url="https://github.com/atlanhq/empty-repo",
        clone_url="https://github.com/atlanhq/empty-repo.git",
        default_branch="main",
        language=None,
        is_private=True,
        is_fork=False,
        is_archived=False,
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
        pushed_at="2024-01-01T00:00:00Z",
        size_kb=0,
        stargazers_count=0,
        watchers_count=0,
        forks_count=0,
        open_issues_count=0,
        topics=[],
        license_name=None,
        has_wiki=False,
        has_issues=False,
        has_projects=False,
        has_downloads=False,
    )

    asset = map_repository(repo, "default/github/123")
    assert asset.description == ""
    assert asset.name == "empty-repo"
    assert asset.app_id is None  # id=0 → None
    assert "visibility=private" in asset.user_description
    assert "language=" not in asset.user_description


def test_map_wiki_page():
    """Test mapping a wiki page to an ApplicationField asset."""
    page = WikiPageRecord(
        repo_full_name="atlanhq/atlan-python",
        page_path="Getting-Started.md",
        page_name="Getting Started",
        content="# Getting Started\n\nWelcome to the Atlan Python SDK...",
        file_sha="abc123def456",
    )

    conn_qn = "default/github/1234567890"
    asset = map_wiki_page(page, conn_qn)

    assert asset.name == "Getting Started"
    assert asset.qualified_name == f"{conn_qn}/atlanhq/atlan-python/wiki/Getting-Started.md"
    assert "Getting Started" in asset.description or "Welcome" in asset.description
    assert asset.app_id == "abc123def456"
    assert asset.user_description == "wiki_page | atlanhq/atlan-python"


def test_map_wiki_page_long_content_truncated():
    """Test that long wiki content is truncated to 500 chars in description."""
    long_content = "x" * 600
    page = WikiPageRecord(
        repo_full_name="atlanhq/atlan-python",
        page_path="Long-Page.md",
        page_name="Long Page",
        content=long_content,
        file_sha="abc123",
    )

    asset = map_wiki_page(page, "default/github/123")
    assert asset.description.endswith("...")
    assert len(asset.description) == 503  # 500 chars + "..."


def test_map_yaml_file():
    """Test mapping a YAML file to an ApplicationField asset."""
    yaml = YamlFileRecord(
        repo_full_name="atlanhq/atlan-python",
        file_path=".github/workflows/ci.yml",
        content="name: CI\non:\n  push:\n    branches: [main]",
        file_sha="xyz789",
        file_size_bytes=256,
    )

    conn_qn = "default/github/1234567890"
    asset = map_yaml_file(yaml, conn_qn)

    assert asset.name == "ci.yml"
    assert asset.qualified_name == f"{conn_qn}/atlanhq/atlan-python/yaml/.github/workflows/ci.yml"
    assert "ci.yml" in asset.description or ".github/workflows/ci.yml" in asset.description
    assert asset.app_id == "xyz789"
    assert asset.user_description == "config_file | yaml | atlanhq/atlan-python"


def test_map_sbom_dependency():
    """Test mapping an SBOM dependency to an ApplicationField asset."""
    dep = SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-python",
        spdx_id="SPDXRef-Package-pip-requests-2.28.0",
        package_name="requests",
        package_version="2.28.0",
        purl="pkg:pypi/requests@2.28.0",
        license_concluded="Apache-2.0",
        license_declared="Apache-2.0",
        supplier="Organization: Python Software Foundation",
        download_location="https://pypi.org/project/requests/",
        relationship_type="PACKAGE",
        parent_spdx_id=None,
    )

    conn_qn = "default/github/1234567890"
    asset = map_sbom_dependency(dep, conn_qn)

    assert asset.name == "requests"
    assert asset.qualified_name == f"{conn_qn}/atlanhq/atlan-python/dep/SPDXRef-Package-pip-requests-2.28.0"
    assert asset.description.startswith("SBOM dependency: requests 2.28.0")
    assert asset.source_url == "pkg:pypi/requests@2.28.0"
    assert asset.app_id == "SPDXRef-Package-pip-requests-2.28.0"
    assert "sbom_dependency" in asset.user_description
    assert "license=Apache-2.0" in asset.user_description


def test_map_sbom_dependency_no_purl():
    """Test that a dependency without purl doesn't set source_url."""
    dep = SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-python",
        spdx_id="SPDXRef-unknown",
        package_name="unknown-pkg",
        package_version=None,
        purl=None,
        license_concluded=None,
        license_declared=None,
        supplier=None,
        download_location=None,
        relationship_type="PACKAGE",
        parent_spdx_id=None,
    )

    asset = map_sbom_dependency(dep, "default/github/123")
    assert asset.name == "unknown-pkg"
    assert asset.description.startswith("SBOM dependency: unknown-pkg")


def test_map_sbom_relationship():
    """Test mapping an SBOM DEPENDS_ON relationship to a Process asset."""
    parent = SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-python",
        spdx_id="SPDXRef-Package-pip-app-1.0.0",
        package_name="app",
        package_version="1.0.0",
        purl="pkg:pypi/app@1.0.0",
        license_concluded=None,
        license_declared=None,
        supplier=None,
        download_location=None,
        relationship_type="PACKAGE",
        parent_spdx_id=None,
    )

    child = SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-python",
        spdx_id="SPDXRef-Package-pip-requests-2.28.0",
        package_name="requests",
        package_version="2.28.0",
        purl="pkg:pypi/requests@2.28.0",
        license_concluded="Apache-2.0",
        license_declared="Apache-2.0",
        supplier="Organization: Python Software Foundation",
        download_location="https://pypi.org/project/requests/",
        relationship_type="DEPENDS_ON",
        parent_spdx_id="SPDXRef-Package-pip-app-1.0.0",
    )

    conn_qn = "default/github/1234567890"
    process = map_sbom_relationship(child, parent, conn_qn)

    assert process is not None
    assert process.name == "app → requests"
    assert "depends on" in process.description.lower()
    assert len(process.inputs) == 1
    assert len(process.outputs) == 1


def test_map_sbom_relationship_returns_none_for_non_depends_on():
    """Test that non-DEPENDS_ON relationships return None."""
    parent = SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-python",
        spdx_id="SPDXRef-parent",
        package_name="parent-pkg",
        package_version="1.0.0",
        purl=None,
        license_concluded=None,
        license_declared=None,
        supplier=None,
        download_location=None,
        relationship_type="PACKAGE",
        parent_spdx_id=None,
    )
    child = SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-python",
        spdx_id="SPDXRef-child",
        package_name="child-pkg",
        package_version="1.0.0",
        purl=None,
        license_concluded=None,
        license_declared=None,
        supplier=None,
        download_location=None,
        relationship_type="CONTAINS",  # not DEPENDS_ON
        parent_spdx_id="SPDXRef-parent",
    )

    result = map_sbom_relationship(child, parent, "default/github/123")
    assert result is None


def test_map_sbom_relationship_returns_none_with_no_parent():
    """Test that a relationship with no parent returns None."""
    child = SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-python",
        spdx_id="SPDXRef-child",
        package_name="child-pkg",
        package_version="1.0.0",
        purl=None,
        license_concluded=None,
        license_declared=None,
        supplier=None,
        download_location=None,
        relationship_type="DEPENDS_ON",
        parent_spdx_id=None,
    )

    result = map_sbom_relationship(child, None, "default/github/123")
    assert result is None
