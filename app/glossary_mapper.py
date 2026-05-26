"""Mapping functions from GitHub wiki/YAML records to Atlan glossary assets.

Produces AtlasGlossary / AtlasGlossaryCategory / AtlasGlossaryTerm objects
using the pyatlan_v9 SDK's creator() helpers.

Hierarchy:
  AtlasGlossary      — one per GitHub org (e.g. "sony-telemetry")
  AtlasGlossaryCategory — one per wiki nav section (e.g. "Client Events")
  AtlasGlossaryTerm  — one per wiki page or YAML file

Wiki markdown parsing is best-effort: Description section and Template
Information fields (business owner, contact person) are extracted when
present using the Sony telemetry wiki page template. Pages that don't
follow the template still produce a valid term; missing fields are omitted.
"""

import re
from typing import Optional

from pyatlan_v9.model.assets import AtlasGlossary, AtlasGlossaryCategory, AtlasGlossaryTerm

from app.api_types import WikiPageRecord, YamlFileRecord

# ─── Wiki nav section inference ─────────────────────────────────────────────
# Maps title prefix (lowercase) → canonical category name used in the wiki nav.
# Covers the six sections visible in the Sony Telemetry wiki sidebar.
_TITLE_PREFIX_TO_SECTION: list[tuple[str, str]] = [
    ("client ", "Client Events"),
    ("native ", "Native Events"),
    ("tooling ", "Tooling Events"),
]


def _infer_wiki_section(page_name: str) -> Optional[str]:
    lower = page_name.lower()
    for prefix, section in _TITLE_PREFIX_TO_SECTION:
        if lower.startswith(prefix):
            return section
    return None


# ─── Markdown field extraction ───────────────────────────────────────────────

def _extract_section(content: str, heading: str) -> Optional[str]:
    """Return the text under a ## heading, stripped, or None if absent."""
    # Use [ \t]* (not \s*) so trailing spaces on the heading line don't consume
    # the following blank line and bleed into the next heading's content.
    pattern = rf"##\s+{re.escape(heading)}[ \t]*\n(.*?)(?=\n##|\Z)"
    m = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip() or None


def _extract_template_field(content: str, field: str) -> Optional[str]:
    """Extract a 'Field: value' line from the Template Information section."""
    section = _extract_section(content, "Template Information")
    if not section:
        return None
    m = re.search(rf"^{re.escape(field)}:\s*(.+)$", section, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else None


def _contact_handles(raw: Optional[str]) -> Optional[set[str]]:
    """Extract @handle tokens from a raw contact string like 'Jane; @jdoe'."""
    if not raw:
        return None
    handles = set(re.findall(r"@(\w+)", raw))
    return handles or None


# ─── Glossary builders ───────────────────────────────────────────────────────

def map_glossary(org: str) -> AtlasGlossary:
    """Create or upsert a glossary for a GitHub org."""
    g = AtlasGlossary.creator(name=org)
    g.description = f"GitHub assets synced from the {org} organisation."
    return g


def map_glossary_category(
    section_name: str,
    glossary_qn: str,
) -> AtlasGlossaryCategory:
    """Create a category corresponding to a wiki nav section."""
    return AtlasGlossaryCategory.creator(
        name=section_name,
        glossary_qualified_name=glossary_qn,
    )


def map_wiki_page_as_term(
    page: WikiPageRecord,
    glossary_qn: str,
    category: Optional[AtlasGlossaryCategory] = None,
) -> AtlasGlossaryTerm:
    """Map a wiki page to a GlossaryTerm.

    Fields populated:
      name             — page title (page_name)
      description      — Description section from the wiki template
      long_description — full markdown content (searchable)
      owner_users      — @handle(s) from Contact Person line
      user_description — Business owner + schema version packed string
      source_url       — canonical wiki page URL constructed from repo + page path
      categories       — [category] when the nav section is known
    """
    section = page.wiki_section or _infer_wiki_section(page.page_name)
    cats = [category] if category else []

    term = AtlasGlossaryTerm.creator(
        name=page.page_name,
        glossary_qualified_name=glossary_qn,
        categories=cats or None,
    )

    description = _extract_section(page.content, "Description")
    if description:
        term.description = description

    term.long_description = page.content

    contact_raw = _extract_template_field(page.content, "Contact Person")
    handles = _contact_handles(contact_raw)
    if handles:
        term.owner_users = handles

    biz_owner = _extract_template_field(page.content, "Business owner")
    schema_ver = _extract_template_field(page.content, "Schema Version")
    meta_parts = []
    if biz_owner:
        meta_parts.append(f"owner={biz_owner}")
    if section:
        meta_parts.append(f"section={section}")
    if schema_ver:
        meta_parts.append(f"schema_version={schema_ver}")
    if page.file_sha:
        meta_parts.append(f"blob_sha={page.file_sha}")
    if meta_parts:
        term.user_description = " | ".join(meta_parts)

    org, repo = page.repo_full_name.split("/", 1)
    slug = page.page_path.removesuffix(".md")
    term.source_url = f"https://github.com/{org}/{repo}/wiki/{slug}"

    return term


def map_yaml_file_as_term(
    yaml_file: YamlFileRecord,
    glossary_qn: str,
) -> AtlasGlossaryTerm:
    """Map a YAML file to an uncategorized GlossaryTerm.

    Category assignment is deferred until Sai confirms whether Sony YAML files
    belong in the wiki nav hierarchy or a separate category.
    """
    name = yaml_file.file_path.split("/")[-1]

    term = AtlasGlossaryTerm.creator(
        name=name,
        glossary_qualified_name=glossary_qn,
    )

    term.long_description = yaml_file.content

    meta_parts = [f"path={yaml_file.file_path}", f"blob_sha={yaml_file.file_sha}"]
    term.user_description = " | ".join(meta_parts)

    org, repo = yaml_file.repo_full_name.split("/", 1)
    term.source_url = f"https://github.com/{org}/{repo}/blob/HEAD/{yaml_file.file_path}"

    return term
