"""Unit tests for the Phase 2 (custom typedef) asset mappers.

Verifies the entity-dict shape, qualified-name conventions, attribute
prefixing, and parse/full/index content modes for each new type.
"""

import pytest
from pydantic import ValidationError

from app.api_types import (
    RepoRecord,
    SbomDependencyRecord,
    WikiPageRecord,
    YamlFileRecord,
)
from app.asset_mapper_v2 import (
    map_repository_v2,
    map_sbom_dependency_edge_v2,
    map_sbom_package_v2,
    map_wiki_page_v2,
    map_yaml_file_v2,
)
from app.contracts import GitHubExtractionInput
from app.typedefs_v2 import (
    ATTR_REPO_IS_ARCHIVED,
    ATTR_REPO_PRIMARY_LANGUAGE,
    ATTR_REPO_STAR_COUNT,
    ATTR_REPO_TOPIC_TAGS,
    ATTR_REPO_VISIBILITY,
    ATTR_REPOSITORY_ORG,
    ATTR_REPOSITORY_QN,
    ATTR_SBOM_ECOSYSTEM,
    ATTR_SBOM_LICENSE,
    ATTR_WIKI_FRONTMATTER_DOMAIN,
    ATTR_WIKI_FRONTMATTER_OWNER,
    ATTR_YAML_OWNER,
    NAMESPACE,
    SbomEcosystem,
    TYPE_REPOSITORY,
    TYPE_SBOM_DEPENDENCY,
    TYPE_SBOM_PACKAGE,
    TYPE_WIKI_PAGE,
    TYPE_YAML_FILE,
    map_sbom_ecosystem,
    map_visibility,
)


CONN_QN_V2 = "default/github/1700000000"


def _repo(**overrides) -> RepoRecord:
    """Helper: minimum-viable RepoRecord with sensible defaults."""
    base = dict(
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
        updated_at="2026-04-21T14:20:00Z",
        pushed_at="2026-04-30T14:20:00Z",
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
    base.update(overrides)
    return RepoRecord(**base)


# ─── Typedef constants ──────────────────────────────────────────────────────


def test_namespace_and_type_names():
    assert NAMESPACE == "GitHubV01"
    assert TYPE_REPOSITORY == "GitHubV01Repository"
    assert TYPE_WIKI_PAGE == "GitHubV01WikiPage"
    assert TYPE_YAML_FILE == "GitHubV01YAMLFile"
    assert TYPE_SBOM_PACKAGE == "GitHubV01SbomPackage"
    assert TYPE_SBOM_DEPENDENCY == "GitHubV01SbomDependency"


def test_attribute_prefix():
    assert ATTR_REPO_STAR_COUNT == "gitHubV01StarCount"
    assert ATTR_WIKI_FRONTMATTER_OWNER == "gitHubV01WikiFrontmatterOwner"


def test_map_visibility():
    assert map_visibility(True) == "PRIVATE"
    assert map_visibility(False) == "PUBLIC"


@pytest.mark.parametrize(
    "purl,expected",
    [
        ("pkg:pypi/requests@2.28.0", SbomEcosystem.PYPI),
        ("pkg:npm/lodash@4.17.21", SbomEcosystem.NPM),
        ("pkg:maven/org.apache/log4j@2.14", SbomEcosystem.MAVEN),
        ("pkg:golang/github.com/foo/bar@v1.0.0", SbomEcosystem.GO),
        ("pkg:cargo/serde@1.0", SbomEcosystem.CARGO),
        ("pkg:gem/rails@7.0", SbomEcosystem.RUBYGEMS),
        ("pkg:nuget/Newtonsoft.Json@13.0", SbomEcosystem.NUGET),
        ("pkg:docker/library/postgres@15", SbomEcosystem.DOCKER),
        ("pkg:weird/unknown@1.0", SbomEcosystem.OTHER),
        (None, SbomEcosystem.OTHER),
        ("not-a-purl", SbomEcosystem.OTHER),
    ],
)
def test_map_sbom_ecosystem(purl, expected):
    assert map_sbom_ecosystem(purl) == expected


# ─── Repository mapper ──────────────────────────────────────────────────────


def test_map_repository_v2_shape():
    entity = map_repository_v2(_repo(), CONN_QN_V2)

    assert entity["typeName"] == TYPE_REPOSITORY
    attrs = entity["attributes"]
    assert attrs["qualifiedName"] == f"{CONN_QN_V2}/atlanhq/atlan-python"
    assert attrs["name"] == "atlan-python"
    assert attrs["connectionQualifiedName"] == CONN_QN_V2


def test_map_repository_v2_typed_scalars_populated():
    entity = map_repository_v2(_repo(), CONN_QN_V2)
    attrs = entity["attributes"]

    assert attrs[ATTR_REPO_STAR_COUNT] == 150
    assert attrs[ATTR_REPO_PRIMARY_LANGUAGE] == "Python"
    assert attrs[ATTR_REPO_VISIBILITY] == "PUBLIC"
    assert attrs[ATTR_REPO_IS_ARCHIVED] is False
    assert attrs[ATTR_REPO_TOPIC_TAGS] == ["python", "sdk", "atlan"]
    assert attrs[ATTR_REPOSITORY_QN] == f"{CONN_QN_V2}/atlanhq/atlan-python"
    assert attrs[ATTR_REPOSITORY_ORG] == "atlanhq"


def test_map_repository_v2_uses_pushed_at_for_source_updated():
    """source_updated_at must map from pushed_at, not updated_at (v1 fix carried forward)."""
    repo = _repo(updated_at="2026-04-21T00:00:00Z", pushed_at="2026-04-30T00:00:00Z")
    entity = map_repository_v2(repo, CONN_QN_V2)
    assert entity["attributes"]["sourceUpdatedAt"] != entity["attributes"]["sourceCreatedAt"]
    # 2026-04-30 in epoch ms (pushed_at)
    from app.asset_mapper import _iso_to_epoch_ms
    assert entity["attributes"]["sourceUpdatedAt"] == _iso_to_epoch_ms("2026-04-30T00:00:00Z")


def test_map_repository_v2_private_sets_visibility_and_discoverable():
    repo = _repo(is_private=True)
    entity = map_repository_v2(repo, CONN_QN_V2)
    assert entity["attributes"][ATTR_REPO_VISIBILITY] == "PRIVATE"
    assert entity["attributes"]["isDiscoverable"] is False


def test_map_repository_v2_public_does_not_set_isdiscoverable():
    """Public repos shouldn't carry an explicit isDiscoverable (None is dropped)."""
    entity = map_repository_v2(_repo(is_private=False), CONN_QN_V2)
    assert "isDiscoverable" not in entity["attributes"]


def test_map_repository_v2_drops_none_attributes():
    repo = _repo(language=None, topics=[])
    entity = map_repository_v2(repo, CONN_QN_V2)
    assert ATTR_REPO_PRIMARY_LANGUAGE not in entity["attributes"]
    assert ATTR_REPO_TOPIC_TAGS not in entity["attributes"]


# ─── WikiPage mapper ────────────────────────────────────────────────────────


def test_map_wiki_page_v2_index_mode():
    page = WikiPageRecord(
        repo_full_name="atlanhq/atlan-python",
        page_path="Getting-Started.md",
        page_name="Getting Started",
        content="x" * 600,
        file_sha="abc123",
    )
    entity = map_wiki_page_v2(page, CONN_QN_V2, content_mode="index")
    attrs = entity["attributes"]
    assert entity["typeName"] == TYPE_WIKI_PAGE
    assert attrs["qualifiedName"] == f"{CONN_QN_V2}/atlanhq/atlan-python/wiki/Getting-Started.md"
    assert attrs["description"].endswith("...")
    assert len(attrs["description"]) == 503
    assert ATTR_WIKI_FRONTMATTER_OWNER not in attrs
    assert entity["relationshipAttributes"]["repository"]["typeName"] == TYPE_REPOSITORY


def test_map_wiki_page_v2_parse_mode_extracts_frontmatter():
    content = """---
owner: data-platform-team
domain: commerce
tags: [orders, transactions]
---
# Customer Orders
Aggregated orders.
"""
    page = WikiPageRecord(
        repo_full_name="atlanhq/atlan-python",
        page_path="Orders.md",
        page_name="Orders",
        content=content,
        file_sha="sha1",
    )
    entity = map_wiki_page_v2(page, CONN_QN_V2, content_mode="parse")
    attrs = entity["attributes"]
    assert attrs[ATTR_WIKI_FRONTMATTER_OWNER] == "data-platform-team"
    assert attrs[ATTR_WIKI_FRONTMATTER_DOMAIN] == "commerce"


def test_map_wiki_page_v2_full_mode_stores_complete_content():
    page = WikiPageRecord(
        repo_full_name="atlanhq/atlan-python",
        page_path="Long.md",
        page_name="Long",
        content="x" * 600,
        file_sha="sha2",
    )
    entity = map_wiki_page_v2(page, CONN_QN_V2, content_mode="full")
    assert len(entity["attributes"]["description"]) == 600


# ─── YAMLFile mapper ────────────────────────────────────────────────────────


def test_map_yaml_file_v2_parse_mode():
    yaml = YamlFileRecord(
        repo_full_name="atlanhq/atlan-python",
        file_path="catalog/orders.yaml",
        content="owner: data-team\ndomain: commerce\ndescription: Orders catalog\ntags: [pii]\n",
        file_sha="yamlsha",
        file_size_bytes=80,
    )
    entity = map_yaml_file_v2(yaml, CONN_QN_V2, content_mode="parse")
    attrs = entity["attributes"]
    assert entity["typeName"] == TYPE_YAML_FILE
    assert attrs["qualifiedName"] == f"{CONN_QN_V2}/atlanhq/atlan-python/yaml/catalog/orders.yaml"
    assert attrs["name"] == "orders.yaml"
    assert attrs[ATTR_YAML_OWNER] == "data-team"
    assert attrs["description"] == "Orders catalog"


def test_map_yaml_file_v2_index_mode_no_parsed_attrs():
    yaml = YamlFileRecord(
        repo_full_name="atlanhq/atlan-python",
        file_path=".github/workflows/ci.yml",
        content="name: CI\non: push",
        file_sha="ci-sha",
        file_size_bytes=20,
    )
    entity = map_yaml_file_v2(yaml, CONN_QN_V2, content_mode="index")
    assert ATTR_YAML_OWNER not in entity["attributes"]


# ─── SbomPackage mapper ─────────────────────────────────────────────────────


def test_map_sbom_package_v2_pypi():
    dep = SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-python",
        spdx_id="SPDXRef-Package-pip-requests-2.28.0",
        package_name="requests",
        package_version="2.28.0",
        purl="pkg:pypi/requests@2.28.0",
        license_concluded="Apache-2.0",
        license_declared="Apache-2.0",
        supplier="Organization: PSF",
        download_location="https://pypi.org/project/requests/",
        relationship_type="PACKAGE",
        parent_spdx_id=None,
    )
    entity = map_sbom_package_v2(dep, CONN_QN_V2)
    attrs = entity["attributes"]
    assert entity["typeName"] == TYPE_SBOM_PACKAGE
    assert attrs["qualifiedName"] == (
        f"{CONN_QN_V2}/atlanhq/atlan-python/sbom/SPDXRef-Package-pip-requests-2.28.0"
    )
    assert attrs[ATTR_SBOM_ECOSYSTEM] == "PYPI"
    assert attrs[ATTR_SBOM_LICENSE] == "Apache-2.0"


def test_map_sbom_package_v2_unknown_purl_falls_back_to_other():
    dep = SbomDependencyRecord(
        repo_full_name="atlanhq/x",
        spdx_id="SPDXRef-x",
        package_name="x",
        package_version=None,
        purl=None,
        license_concluded=None,
        license_declared=None,
        supplier=None,
        download_location=None,
        relationship_type="PACKAGE",
        parent_spdx_id=None,
    )
    entity = map_sbom_package_v2(dep, CONN_QN_V2)
    assert entity["attributes"][ATTR_SBOM_ECOSYSTEM] == "OTHER"


# ─── SbomDependency edge mapper ─────────────────────────────────────────────


def test_map_sbom_dependency_edge_v2_creates_typed_edge():
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
        supplier=None,
        download_location=None,
        relationship_type="DEPENDS_ON",
        parent_spdx_id="SPDXRef-Package-pip-app-1.0.0",
    )
    entity = map_sbom_dependency_edge_v2(child, parent, CONN_QN_V2)
    assert entity is not None
    assert entity["typeName"] == TYPE_SBOM_DEPENDENCY
    assert entity["attributes"]["name"] == "app → requests"
    rel_attrs = entity["relationshipAttributes"]
    assert rel_attrs["dependsOnSource"]["typeName"] == TYPE_SBOM_PACKAGE
    assert rel_attrs["dependsOnTarget"]["uniqueAttributes"]["qualifiedName"].endswith(
        "/SPDXRef-Package-pip-requests-2.28.0"
    )


def test_map_sbom_dependency_edge_v2_returns_none_for_non_depends_on():
    parent = SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-python", spdx_id="P", package_name="p",
        package_version="1.0", purl=None, license_concluded=None, license_declared=None,
        supplier=None, download_location=None, relationship_type="PACKAGE", parent_spdx_id=None,
    )
    child = SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-python", spdx_id="C", package_name="c",
        package_version="1.0", purl=None, license_concluded=None, license_declared=None,
        supplier=None, download_location=None, relationship_type="CONTAINS", parent_spdx_id="P",
    )
    assert map_sbom_dependency_edge_v2(child, parent, CONN_QN_V2) is None


def test_map_sbom_dependency_edge_v2_returns_none_with_no_parent():
    child = SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-python", spdx_id="C", package_name="c",
        package_version="1.0", purl=None, license_concluded=None, license_declared=None,
        supplier=None, download_location=None, relationship_type="DEPENDS_ON", parent_spdx_id=None,
    )
    assert map_sbom_dependency_edge_v2(child, None, CONN_QN_V2) is None


# ─── Contract: typedef_version ──────────────────────────────────────────────


def test_extraction_input_accepts_typedef_versions():
    for version in ["v1", "v2"]:
        inp = GitHubExtractionInput(
            organization="atlanhq",
            credential={"token": "t"},
            connection_qualified_name="default/github/123",
            typedef_version=version,
        )
        assert inp.typedef_version == version


def test_extraction_input_defaults_to_v1():
    inp = GitHubExtractionInput(
        organization="atlanhq",
        credential={"token": "t"},
        connection_qualified_name="default/app/123",
    )
    assert inp.typedef_version == "v1"


def test_extraction_input_rejects_invalid_typedef_version():
    with pytest.raises(ValidationError):
        GitHubExtractionInput(
            organization="atlanhq",
            credential={"token": "t"},
            connection_qualified_name="default/app/123",
            typedef_version="v3",
        )
