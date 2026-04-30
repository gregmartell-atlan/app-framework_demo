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
    )

    conn_qn = "default/github/1234567890"
    asset = map_repository(repo, conn_qn)

    assert asset.name == "atlan-python"
    assert asset.qualified_name == f"{conn_qn}/atlanhq/atlan-python"
    assert asset.description == "Python SDK for Atlan"
    assert asset.application_type == "GitHub Repository"
    assert asset.application_sub_type == "Python"
    assert asset.application_url == "https://github.com/atlanhq/atlan-python"
    assert asset.application_is_private is False
    assert asset.application_star_count == 150


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
    assert asset.application_field_type == "wiki_page"
    assert asset.application_field_format == "markdown"


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
    assert asset.application_field_type == "config_file"
    assert asset.application_field_format == "yaml"


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
    assert asset.application_field_type == "sbom_dependency"
    assert asset.description.startswith("SBOM dependency: requests 2.28.0")


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
