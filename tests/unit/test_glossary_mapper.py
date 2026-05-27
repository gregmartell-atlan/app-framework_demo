"""Unit tests for app.glossary_mapper."""

import pytest

from app.api_types import WikiPageRecord, YamlFileRecord
from app.glossary_mapper import (
    _contact_handles,
    _extract_section,
    _extract_template_field,
    _infer_wiki_section,
    _parse_extends_includes,
    build_relationship_updates,
    build_see_also_update,
    map_glossary,
    map_glossary_category,
    map_glossary_subcategory,
    map_wiki_page_as_term,
    map_yaml_file_as_term,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────

SONY_WIKI_CONTENT = """\
## Template Information

Business owner: Ghost Team
Contact Person: Srdjan Boskovic; @sboskovic
Schema Version: 2.8.2

Changelog:
- [1.0.0] - 2019-10-01 - Improved file structure #59

## Description

Base class of every Client Event. Contains properties common to all events.

## Classification justification

Critical for Telemetry Service and Event QoS purposes.

## Structure

### Extends

*(root — no parent)*

### Includes

- [consoleInfo](client-template-consoleInfo)
- [nodeServerInfo](client-template-nodeServerInfo)
"""

WIKI_PAGE = WikiPageRecord(
    repo_full_name="sony/telemetry",
    page_path="client-baseClientEvent.md",
    page_name="client baseClientEvent",
    content=SONY_WIKI_CONTENT,
    file_sha="abc123",
    wiki_section="Client Events",
    git_updated_at=1700000000000,
    git_updated_by="sboskovic",
    git_created_at=1571000000000,
)

YAML_FILE = YamlFileRecord(
    repo_full_name="sony/config-repo",
    file_path="schemas/event-definitions/adtracking.yaml",
    content="name: AdTracking\nversion: 1.0\n",
    file_sha="def456",
    file_size_bytes=512,
)

GLOSSARY_QN = "-1779832499412"


# ─── Section inference ────────────────────────────────────────────────────────

@pytest.mark.parametrize("page_name,page_path,expected", [
    ("client AdTracking",      "client-AdTracking.md",      ("Client",  "Events")),
    ("client baseClientEvent", "client-baseClientEvent.md", ("Client",  "Event Templates")),
    ("CLIENT ExchangeTracking","client-ExchangeTracking.md",("Client",  "Events")),
    ("native Navigation",      "native-Navigation.md",      ("Native",  "Events")),
    ("tooling BuildPipeline",  "tooling-BuildPipeline.md",  ("Tooling", "Events")),
    ("client template consoleInfo", "client-template-consoleInfo.md", ("Client", "Event Templates")),
    ("tooling template serviceInfo","tooling-template-serviceInfo.md",("Tooling","Event Templates")),
    ("Home",       "Home.md",       (None, None)),
    ("adtracking", "adtracking.md", (None, None)),
])
def test_infer_wiki_section(page_name, page_path, expected):
    assert _infer_wiki_section(page_name, page_path) == expected


# ─── Markdown extraction ──────────────────────────────────────────────────────

def test_extract_section_description():
    result = _extract_section(SONY_WIKI_CONTENT, "Description")
    assert result == "Base class of every Client Event. Contains properties common to all events."


def test_extract_section_missing_returns_none():
    assert _extract_section(SONY_WIKI_CONTENT, "NonExistent") is None


def test_extract_section_empty_body_returns_none():
    content = "## Description\n\n## Structure\n"
    assert _extract_section(content, "Description") is None


def test_extract_template_field_business_owner():
    assert _extract_template_field(SONY_WIKI_CONTENT, "Business owner") == "Ghost Team"


def test_extract_template_field_schema_version():
    assert _extract_template_field(SONY_WIKI_CONTENT, "Schema Version") == "2.8.2"


def test_extract_template_field_missing_returns_none():
    assert _extract_template_field(SONY_WIKI_CONTENT, "Nonexistent Field") is None


def test_contact_handles_extracts_at_handles():
    assert _contact_handles("Srdjan Boskovic; @sboskovic") == {"sboskovic"}


def test_contact_handles_multiple():
    assert _contact_handles("@alice; @bob") == {"alice", "bob"}


def test_contact_handles_no_handles_returns_none():
    assert _contact_handles("Ghost Team") is None


def test_contact_handles_none_input():
    assert _contact_handles(None) is None


# ─── map_glossary ─────────────────────────────────────────────────────────────

def test_map_glossary_name():
    g = map_glossary("sony-telemetry")
    assert g.name == "sony-telemetry"


def test_map_glossary_description_mentions_org():
    g = map_glossary("sony-telemetry")
    assert "sony-telemetry" in g.description


# ─── map_glossary_category ────────────────────────────────────────────────────

def test_map_glossary_category_name():
    cat = map_glossary_category("Client Events", GLOSSARY_QN)
    assert cat.name == "Client Events"


def test_map_glossary_category_anchor_qn():
    cat = map_glossary_category("Native Events", GLOSSARY_QN)
    assert cat.anchor.unique_attributes["qualifiedName"] == GLOSSARY_QN


# ─── map_wiki_page_as_term ────────────────────────────────────────────────────

def test_wiki_term_name():
    term = map_wiki_page_as_term(WIKI_PAGE, GLOSSARY_QN)
    assert term.name == "client baseClientEvent"


def test_wiki_term_description_extracted_from_markdown():
    term = map_wiki_page_as_term(WIKI_PAGE, GLOSSARY_QN)
    assert "Base class of every Client Event" in term.user_description


def test_wiki_term_long_description_is_full_content():
    term = map_wiki_page_as_term(WIKI_PAGE, GLOSSARY_QN)
    assert term.long_description == SONY_WIKI_CONTENT


def test_wiki_term_owner_users_from_contact_person():
    term = map_wiki_page_as_term(WIKI_PAGE, GLOSSARY_QN)
    assert "sboskovic" in term.owner_users


def test_wiki_term_user_description_is_wiki_description():
    term = map_wiki_page_as_term(WIKI_PAGE, GLOSSARY_QN)
    assert "Base class of every Client Event" in term.user_description


def test_wiki_term_source_url():
    term = map_wiki_page_as_term(WIKI_PAGE, GLOSSARY_QN)
    assert term.source_url == "https://github.com/sony/telemetry/wiki/client-baseClientEvent"


def test_wiki_term_source_url_strips_md_extension():
    page = WikiPageRecord(
        repo_full_name="sony/telemetry",
        page_path="client-AdTracking.md",
        page_name="client AdTracking",
        content="## Description\nAd tracking event.\n",
        file_sha=None,
    )
    term = map_wiki_page_as_term(page, GLOSSARY_QN)
    assert term.source_url.endswith("/wiki/client-AdTracking")
    assert ".md" not in term.source_url


def test_wiki_term_category_assigned_when_provided():
    cat = map_glossary_category("Client Events", GLOSSARY_QN)
    term = map_wiki_page_as_term(WIKI_PAGE, GLOSSARY_QN, category=cat)
    assert any(c.name == "Client Events" for c in term.categories)


def test_wiki_term_no_category_when_omitted():
    term = map_wiki_page_as_term(WIKI_PAGE, GLOSSARY_QN)
    assert not term.categories


def test_wiki_term_uses_wiki_section_field_over_inference():
    page = WikiPageRecord(
        repo_full_name="sony/telemetry",
        page_path="client-AdTracking.md",
        page_name="client AdTracking",
        content="## Description\nAd tracking.\n",
        file_sha=None,
        wiki_section="Native Events",
    )
    term = map_wiki_page_as_term(page, GLOSSARY_QN)
    assert term.user_description == "Ad tracking."


def test_wiki_term_no_user_description_when_section_missing():
    page = WikiPageRecord(
        repo_full_name="sony/telemetry",
        page_path="Home.md",
        page_name="Home",
        content="Welcome to the Telemetry wiki.",
        file_sha=None,
    )
    term = map_wiki_page_as_term(page, GLOSSARY_QN)
    assert not term.user_description  # UNSET when no Description section


def test_wiki_term_owner_groups_from_business_owner():
    term = map_wiki_page_as_term(WIKI_PAGE, GLOSSARY_QN)
    assert "Ghost Team" in term.owner_groups


def test_wiki_term_usage_from_classification_justification():
    term = map_wiki_page_as_term(WIKI_PAGE, GLOSSARY_QN)
    assert "Telemetry Service" in term.usage


def test_wiki_term_usage_skipped_for_placeholder_text():
    page = WikiPageRecord(
        repo_full_name="sony/telemetry",
        page_path="client-AdTracking.md",
        page_name="client AdTracking",
        content="## Classification justification\n\n*(only relevant in case of SERVICE_DATA classification)*\n",
        file_sha=None,
    )
    term = map_wiki_page_as_term(page, GLOSSARY_QN)
    assert not term.usage


def test_wiki_term_git_timestamps_set():
    term = map_wiki_page_as_term(WIKI_PAGE, GLOSSARY_QN)
    assert term.source_updated_at == 1700000000000
    assert term.source_updated_by == "sboskovic"
    assert term.source_created_at == 1571000000000


def test_wiki_term_git_timestamps_omitted_when_absent():
    page = WikiPageRecord(
        repo_full_name="sony/telemetry",
        page_path="Home.md",
        page_name="Home",
        content="Welcome.",
        file_sha=None,
    )
    term = map_wiki_page_as_term(page, GLOSSARY_QN)
    assert not term.source_updated_at
    assert not term.source_updated_by
    assert not term.source_created_at


# ─── _parse_extends_includes ─────────────────────────────────────────────────

def test_parse_extends_root_returns_empty():
    extends, includes = _parse_extends_includes(SONY_WIKI_CONTENT)
    assert extends == []


def test_parse_includes_slugs():
    _, includes = _parse_extends_includes(SONY_WIKI_CONTENT)
    assert "client-template-consoleInfo" in includes
    assert "client-template-nodeServerInfo" in includes


def test_parse_extends_with_parent():
    content = """\
## Structure

### Extends

- [tooling baseToolingEvent](tooling-baseToolingEvent)

### Includes

*(none)*
"""
    extends, includes = _parse_extends_includes(content)
    assert extends == ["tooling-baseToolingEvent"]
    assert includes == []


def test_parse_extends_includes_no_structure_section():
    extends, includes = _parse_extends_includes("## Description\nHello.")
    assert extends == [] and includes == []


# ─── build_see_also_update ────────────────────────────────────────────────────

def test_build_see_also_update_links_resolved_slugs():
    slug_to_qn = {
        "client-template-consoleInfo":    "consoleInfo@abc",
        "client-template-nodeServerInfo": "nodeServerInfo@abc",
    }
    update = build_see_also_update(WIKI_PAGE, "baseEvent@xyz", "glossary-guid-1", slug_to_qn)
    assert update is not None
    linked_qns = {t.qualified_name for t in update.see_also}
    assert "consoleInfo@abc" in linked_qns
    assert "nodeServerInfo@abc" in linked_qns


def test_build_see_also_update_returns_none_when_no_refs_resolvable():
    update = build_see_also_update(WIKI_PAGE, "baseEvent@xyz", "glossary-guid-1", {})
    assert update is None


# ─── map_yaml_file_as_term ────────────────────────────────────────────────────

def test_yaml_term_name_is_filename():
    term = map_yaml_file_as_term(YAML_FILE, GLOSSARY_QN)
    assert term.name == "adtracking.yaml"


def test_yaml_term_long_description_is_raw_content():
    term = map_yaml_file_as_term(YAML_FILE, GLOSSARY_QN)
    assert term.long_description == YAML_FILE.content


def test_yaml_term_user_description_packs_path_and_sha():
    term = map_yaml_file_as_term(YAML_FILE, GLOSSARY_QN)
    assert "path=schemas/event-definitions/adtracking.yaml" in term.user_description
    assert "blob_sha=def456" in term.user_description


def test_yaml_term_source_url():
    term = map_yaml_file_as_term(YAML_FILE, GLOSSARY_QN)
    assert term.source_url == "https://github.com/sony/config-repo/blob/HEAD/schemas/event-definitions/adtracking.yaml"


def test_yaml_term_not_categorized():
    term = map_yaml_file_as_term(YAML_FILE, GLOSSARY_QN)
    assert not term.categories
