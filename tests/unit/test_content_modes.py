"""Tests for wiki_content_mode and yaml_content_mode across all three values.

Fixtures live in tests/fixtures/content/ and represent two archetypes:
  - Structured catalog content (frontmatter/headers, catalog.yaml) → parse mode extracts fields
  - Plain prose content (ci workflow, plain wiki page)             → parse mode falls back gracefully
"""

from pathlib import Path

import pytest

from app.api_types import WikiPageRecord, YamlFileRecord
from app.asset_mapper import map_wiki_page, map_yaml_file

CONTENT = Path(__file__).parent.parent / "fixtures" / "content"
CONN_QN = "default/app/1234567890"
REPO = "sony-data/context-studio"


def _wiki(page_name: str, filename: str, sha: str = "abc123") -> WikiPageRecord:
    return WikiPageRecord(
        repo_full_name=REPO,
        page_path=filename,
        page_name=page_name,
        content=(CONTENT / filename).read_text(),
        file_sha=sha,
    )


def _yaml_record(file_path: str, sha: str = "def456") -> YamlFileRecord:
    content = (CONTENT / file_path.split("/")[-1]).read_text()
    return YamlFileRecord(
        repo_full_name=REPO,
        file_path=file_path,
        content=content,
        file_sha=sha,
        file_size_bytes=len(content.encode()),
    )


# ---------------------------------------------------------------------------
# Wiki — index mode (default behaviour, no regressions)
# ---------------------------------------------------------------------------

def test_wiki_index_mode_truncates():
    page = _wiki("Customer Orders", "wiki_catalog_page.md")
    asset = map_wiki_page(page, CONN_QN, content_mode="index")

    assert len(asset.description) <= 503  # 500 + "..."
    assert asset.user_description == f"wiki_page | {REPO}"
    # parse attributes should NOT be set in index mode
    assert not asset.asset_tags


def test_wiki_index_mode_plain_page():
    page = _wiki("Getting Started", "wiki_plain_page.md")
    asset = map_wiki_page(page, CONN_QN, content_mode="index")

    assert "Getting Started" in asset.description or "Welcome" in asset.description
    assert asset.user_description == f"wiki_page | {REPO}"


# ---------------------------------------------------------------------------
# Wiki — full mode
# ---------------------------------------------------------------------------

def test_wiki_full_mode_stores_complete_content():
    page = _wiki("Customer Orders", "wiki_catalog_page.md")
    asset = map_wiki_page(page, CONN_QN, content_mode="full")

    assert asset.description == page.content  # no truncation
    assert "## Upstream" in asset.description  # full markdown preserved
    assert asset.user_description == f"wiki_page | {REPO}"


# ---------------------------------------------------------------------------
# Wiki — parse mode: structured catalog page (frontmatter)
# ---------------------------------------------------------------------------

def test_wiki_parse_mode_extracts_frontmatter_owner():
    page = _wiki("Customer Orders", "wiki_catalog_page.md")
    asset = map_wiki_page(page, CONN_QN, content_mode="parse")

    assert "owner=data-platform-team" in asset.user_description


def test_wiki_parse_mode_extracts_frontmatter_domain():
    page = _wiki("Customer Orders", "wiki_catalog_page.md")
    asset = map_wiki_page(page, CONN_QN, content_mode="parse")

    assert "domain=commerce" in asset.user_description


def test_wiki_parse_mode_extracts_frontmatter_tags():
    page = _wiki("Customer Orders", "wiki_catalog_page.md")
    asset = map_wiki_page(page, CONN_QN, content_mode="parse")

    assert asset.asset_tags is not None
    assert "orders" in asset.asset_tags
    assert "pii" in asset.asset_tags


def test_wiki_parse_mode_plain_page_falls_back_gracefully():
    """A page with no structured metadata should not fail — just return content."""
    page = _wiki("Getting Started", "wiki_plain_page.md")
    asset = map_wiki_page(page, CONN_QN, content_mode="parse")

    # No owner/domain extracted — user_description has no extra pipes
    assert asset.user_description == f"wiki_page | {REPO}"
    # Description falls back to full content when no 'description' field found
    assert "Getting Started" in asset.description or "Welcome" in asset.description
    assert not asset.asset_tags


# ---------------------------------------------------------------------------
# YAML — index mode (default)
# ---------------------------------------------------------------------------

def test_yaml_index_mode_stores_file_reference():
    rec = _yaml_record("catalog.yaml")
    asset = map_yaml_file(rec, CONN_QN, content_mode="index")

    assert asset.description == "YAML configuration file: catalog.yaml"
    assert asset.user_description == f"config_file | yaml | {REPO}"
    assert not asset.asset_tags


def test_yaml_index_mode_ci_workflow():
    rec = _yaml_record(".github/workflows/ci_workflow.yaml", sha="fff999")
    # Override file_path to look like a CI file
    from app.api_types import YamlFileRecord as YR
    rec2 = YR(
        repo_full_name=REPO,
        file_path=".github/workflows/ci.yml",
        content=rec.content,
        file_sha="fff999",
        file_size_bytes=rec.file_size_bytes,
    )
    asset = map_yaml_file(rec2, CONN_QN, content_mode="index")
    assert "ci.yml" in asset.description
    assert asset.user_description == f"config_file | yaml | {REPO}"


# ---------------------------------------------------------------------------
# YAML — full mode
# ---------------------------------------------------------------------------

def test_yaml_full_mode_stores_raw_content():
    rec = _yaml_record("catalog.yaml")
    asset = map_yaml_file(rec, CONN_QN, content_mode="full")

    assert asset.description == rec.content
    assert "data-platform-team" in asset.description
    assert asset.user_description == f"config_file | yaml | {REPO}"


# ---------------------------------------------------------------------------
# YAML — parse mode: catalog.yaml with owner/domain/description/tags
# ---------------------------------------------------------------------------

def test_yaml_parse_mode_extracts_description():
    rec = _yaml_record("catalog.yaml")
    asset = map_yaml_file(rec, CONN_QN, content_mode="parse")

    assert "Order processing pipeline" in asset.description


def test_yaml_parse_mode_extracts_owner():
    rec = _yaml_record("catalog.yaml")
    asset = map_yaml_file(rec, CONN_QN, content_mode="parse")

    assert "owner=data-platform-team" in asset.user_description


def test_yaml_parse_mode_extracts_domain():
    rec = _yaml_record("catalog.yaml")
    asset = map_yaml_file(rec, CONN_QN, content_mode="parse")

    assert "domain=commerce" in asset.user_description


def test_yaml_parse_mode_extracts_tags():
    rec = _yaml_record("catalog.yaml")
    asset = map_yaml_file(rec, CONN_QN, content_mode="parse")

    assert asset.asset_tags is not None
    assert "orders" in asset.asset_tags
    assert "etl" in asset.asset_tags


def test_yaml_parse_mode_ci_workflow_falls_back_gracefully():
    """A CI workflow YAML has no catalog keys — should not fail or invent metadata."""
    rec = _yaml_record("ci_workflow.yaml")
    asset = map_yaml_file(rec, CONN_QN, content_mode="parse")

    # Falls back to default description when no catalog keys found
    assert "ci_workflow.yaml" in asset.description or "YAML configuration" in asset.description
    assert asset.user_description.startswith("config_file | yaml |")
    # No owner/domain extracted from a CI workflow
    assert "owner=" not in asset.user_description
    assert not asset.asset_tags
