"""Unit tests for app.glossary_mapper."""

import pytest

from app.api_types import WikiPageRecord, YamlFileRecord
from app.glossary_mapper import (
    _contact_handles,
    _extract_section,
    _extract_template_field,
    _infer_wiki_section,
    map_glossary,
    map_glossary_category,
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

(only relevant in case of SERVICE_DATA classification)

Critical for Telemetry Service and Event QoS purposes.

## Structure

### Extends

### Includes
- consoleInfo
- nodeServerInfo
"""

WIKI_PAGE = WikiPageRecord(
    repo_full_name="sony/telemetry",
    page_path="client-baseClientEvent.md",
    page_name="client baseClientEvent",
    content=SONY_WIKI_CONTENT,
    file_sha="abc123",
    wiki_section="Client Events",
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

@pytest.mark.parametrize("page_name,expected", [
    ("client AdTracking", "Client Events"),
    ("client baseClientEvent", "Client Events"),
    ("CLIENT ExchangeTracking", "Client Events"),
    ("native Navigation", "Native Events"),
    ("tooling BuildPipeline", "Tooling Events"),
    ("Home", None),
    ("adtracking", None),
])
def test_infer_wiki_section(page_name, expected):
    assert _infer_wiki_section(page_name) == expected


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
