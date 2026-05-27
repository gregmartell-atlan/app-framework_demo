"""Mapping functions from GitHub wiki/YAML records to Atlan glossary assets.

Produces AtlasGlossary / AtlasGlossaryCategory / AtlasGlossaryTerm objects
using the pyatlan_v9 SDK's creator() helpers.

Hierarchy:
  AtlasGlossary      — one per GitHub org (e.g. "sony-telemetry")
  AtlasGlossaryCategory — one per wiki nav section (e.g. "Client Events")
  AtlasGlossaryTerm  — one per wiki page or YAML file

Wiki markdown parsing is best-effort. Pages that don't follow the Sony
telemetry template still produce a valid term; missing fields are omitted.
"""

import re
from typing import Optional

from pyatlan_v9.model.assets import AtlasGlossary, AtlasGlossaryCategory, AtlasGlossaryTerm, Readme

from app.api_types import WikiPageRecord, YamlFileRecord

# ─── Wiki nav section inference ─────────────────────────────────────────────
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
    pattern = rf"##\s+{re.escape(heading)}[ \t]*\n(.*?)(?=\n##(?!#)|\Z)"
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


def _parse_extends_includes(content: str) -> tuple[list[str], list[str]]:
    """Return (extends_slugs, includes_slugs) parsed from the Structure section.

    Slugs are the link targets in markdown like [text](slug), matching the
    page_path stem used as keys in the slug→QN map built during the push.
    """
    structure = _extract_section(content, "Structure")
    if not structure:
        return [], []

    extends_slugs: list[str] = []
    includes_slugs: list[str] = []
    in_extends = in_includes = False

    for line in structure.splitlines():
        stripped = line.strip()
        if stripped == "### Extends":
            in_extends, in_includes = True, False
        elif stripped == "### Includes":
            in_extends, in_includes = False, True
        elif stripped.startswith("### "):
            in_extends = in_includes = False
        elif stripped.startswith("- ") and (in_extends or in_includes):
            m = re.search(r"\(([^)]+)\)", stripped)
            slug = m.group(1) if m else stripped[2:].strip()
            if slug and not re.search(r"\*(none|root)\*|^\*", slug, re.IGNORECASE):
                if in_extends:
                    extends_slugs.append(slug)
                else:
                    includes_slugs.append(slug)

    return extends_slugs, includes_slugs


# ─── Glossary builders ───────────────────────────────────────────────────────

def map_glossary(org: str) -> AtlasGlossary:
    g = AtlasGlossary.creator(name=org)
    g.description = f"GitHub assets synced from the {org} organisation."
    return g


def map_glossary_category(section_name: str, glossary_qn: str) -> AtlasGlossaryCategory:
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

    Atlan field mapping:
      user_description  — ## Description prose
      long_description  — full markdown (Readme)
      owner_users       — @handles from Contact Person
      owner_groups      — Business owner team name
      usage             — Classification justification text
      source_url        — canonical GitHub wiki URL
      source_updated_at — ms timestamp of last git commit on this file
      source_updated_by — author name of last git commit
      source_created_at — ms timestamp of first git commit on this file
      categories        — wiki nav section category
    """
    cats = [category] if category else []

    term = AtlasGlossaryTerm.creator(
        name=page.page_name,
        glossary_qualified_name=glossary_qn,
        categories=cats or None,
    )

    description = _extract_section(page.content, "Description")
    if description:
        term.user_description = description

    term.long_description = page.content

    contact_raw = _extract_template_field(page.content, "Contact Person")
    handles = _contact_handles(contact_raw)
    if handles:
        term.owner_users = handles

    biz_owner = _extract_template_field(page.content, "Business owner")
    if biz_owner:
        term.owner_groups = {biz_owner}

    classification = _extract_section(page.content, "Classification justification")
    if classification and not classification.startswith("*(only relevant"):
        term.usage = classification

    if page.git_updated_at is not None:
        term.source_updated_at = page.git_updated_at
    if page.git_updated_by:
        term.source_updated_by = page.git_updated_by
    if page.git_created_at is not None:
        term.source_created_at = page.git_created_at

    org, repo = page.repo_full_name.split("/", 1)
    slug = page.page_path.removesuffix(".md")
    term.source_url = f"https://github.com/{org}/{repo}/wiki/{slug}"

    return term


def build_see_also_update(
    page: WikiPageRecord,
    term_qn: str,
    glossary_guid: str,
    slug_to_qn: dict[str, str],
) -> Optional[AtlasGlossaryTerm]:
    """Return a minimal term update that sets see_also from Extends/Includes.

    Returns None if the page has no resolvable cross-references.
    slug_to_qn maps page_path stems (e.g. 'client-baseClientEvent') to the
    saved term's qualified_name.
    """
    extends_slugs, includes_slugs = _parse_extends_includes(page.content)
    related_qns = [
        slug_to_qn[s]
        for s in (extends_slugs + includes_slugs)
        if s in slug_to_qn
    ]
    if not related_qns:
        return None

    update = AtlasGlossaryTerm.updater(
        qualified_name=term_qn,
        name=page.page_name,
        glossary_guid=glossary_guid,
    )
    update.see_also = [AtlasGlossaryTerm.ref_by_qualified_name(qn) for qn in related_qns]
    return update


def map_readme(saved_asset: AtlasGlossaryTerm, content: str, asset_name: str) -> Readme:
    """Create a Readme asset linked to an already-saved GlossaryTerm.

    saved_asset must have a guid (returned from client.asset.save()).
    asset_name is only passed when the saved stub has no name of its own,
    since Readme.creator rejects asset_name when the asset already has one.
    """
    if saved_asset.name and str(saved_asset.name) != "UNSET":
        return Readme.creator(asset=saved_asset, content=content)
    return Readme.creator(asset=saved_asset, content=content, asset_name=asset_name)


def map_yaml_file_as_term(yaml_file: YamlFileRecord, glossary_qn: str) -> AtlasGlossaryTerm:
    name = yaml_file.file_path.split("/")[-1]
    term = AtlasGlossaryTerm.creator(name=name, glossary_qualified_name=glossary_qn)
    term.long_description = yaml_file.content
    term.user_description = f"path={yaml_file.file_path} | blob_sha={yaml_file.file_sha}"

    org, repo = yaml_file.repo_full_name.split("/", 1)
    term.source_url = f"https://github.com/{org}/{repo}/blob/HEAD/{yaml_file.file_path}"
    return term
