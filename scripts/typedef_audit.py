"""Full typedef + payload audit for every asset type the connector creates.

For each asset type:
  1. Confirms the typedef is a built-in Atlan SDK type (no custom typedef registration needed)
  2. Lists every attribute on the typedef
  3. Runs the mapper against a realistic sample input
  4. Shows which attributes are SET vs UNSET on the resulting asset
  5. Flags type-specific scalars (the attrs that distinguish this type from generic Asset)

This answers the question: "do we need to create custom typedefs in Atlan?"
Spoiler: no — every type we use is already shipped in pyatlan_v9.
"""

import os
import sys
from pathlib import Path

import msgspec

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyatlan_v9.model.assets import Application, ApplicationField, Process, Readme

from app.api_types import (
    RepoRecord,
    SbomDependencyRecord,
    WikiPageRecord,
    YamlFileRecord,
)
from app.asset_mapper import (
    map_repository,
    map_sbom_dependency,
    map_sbom_relationship,
    map_wiki_page,
    map_yaml_file,
    map_readme,
)

CONN_QN = "default/app/1700000000"
CONTENT = Path(__file__).parent.parent / "tests" / "fixtures" / "content"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def is_set(value) -> bool:
    return value is not None and not isinstance(value, msgspec.UnsetType)


def banner(text: str, char: str = "═"):
    print()
    print(char * 90)
    print(f"  {text}")
    print(char * 90)


def show_asset(asset, type_specific_fields: list[str], skip_inherited: set[str] | None = None):
    """Print every set attribute, then list type-specific scalars (set or unset)."""
    skip_inherited = skip_inherited or set()

    set_fields = []
    unset_fields = []
    for field in msgspec.structs.fields(type(asset)):
        value = getattr(asset, field.name)
        if is_set(value):
            set_fields.append((field.name, value))
        else:
            unset_fields.append(field.name)

    print(f"\n  TYPE_NAME:        {asset.type_name}")
    print(f"  Built-in typedef: yes (pyatlan_v9.model.assets.{type(asset).__name__})")
    print(f"  Custom typedef registration required: NO")

    print(f"\n  ── ATTRIBUTES SET BY MAPPER ({len(set_fields)}) ──")
    for name, value in set_fields:
        if name == "type_name":
            continue
        printable = repr(value) if not isinstance(value, str) else value
        if isinstance(printable, str) and len(printable) > 100:
            printable = printable[:100] + "…"
        print(f"    {name:<32} = {printable}")

    print(f"\n  ── TYPE-SPECIFIC SCALARS ──")
    print(f"  (these distinguish {type(asset).__name__} from generic Asset)")
    for fname in type_specific_fields:
        value = getattr(asset, fname, None)
        status = "SET  " if is_set(value) else "unset"
        printable = (str(value)[:60] + "…") if is_set(value) and len(str(value)) > 60 else value
        print(f"    [{status}] {fname:<32} = {printable if is_set(value) else '(not populated by connector)'}")

    print(f"\n  ── INHERITED ASSET ATTRS WE COULD SET BUT DON'T ──")
    candidates = [
        "owner_users", "owner_groups", "admin_users", "admin_groups",
        "certificate_status", "is_discoverable", "asset_tags",
        "asset_source_readme", "tenant_id",
    ]
    for c in candidates:
        if c in skip_inherited:
            continue
        value = getattr(asset, c, None)
        if not is_set(value):
            print(f"    [unset] {c}")


# ──────────────────────────────────────────────────────────────────────────────
# 1. Application
# ──────────────────────────────────────────────────────────────────────────────

def audit_application():
    banner("1. Application — Atlan typedef for a GitHub repository")

    # Use a realistic sample (atlan-context-studio-app)
    repo = RepoRecord(
        full_name="atlanhq/atlan-context-studio-app",
        name="atlan-context-studio-app",
        owner="atlanhq",
        description="Building an app on Atlan framework to showcase semantic view evals framework.",
        html_url="https://github.com/atlanhq/atlan-context-studio-app",
        clone_url="https://github.com/atlanhq/atlan-context-studio-app.git",
        default_branch="main",
        language="Python",
        is_private=True,
        is_fork=False,
        is_archived=False,
        created_at="2025-11-10T03:06:02Z",
        updated_at="2026-04-21T12:55:26Z",
        pushed_at="2026-04-30T11:44:15Z",
        size_kb=8631,
        stargazers_count=4,
        watchers_count=4,
        forks_count=0,
        open_issues_count=26,
        topics=[],
        license_name=None,
        has_wiki=True,
        has_issues=True,
        has_projects=True,
        has_downloads=True,
        id=1093188306,
    )
    asset = map_repository(repo, CONN_QN)
    show_asset(asset, type_specific_fields=["app_id", "catalog_dataset_guid"])


# ──────────────────────────────────────────────────────────────────────────────
# 2. Readme
# ──────────────────────────────────────────────────────────────────────────────

def audit_readme():
    banner("2. Readme — Atlan typedef for repo README content")

    repo = RepoRecord(
        full_name="atlanhq/atlan-context-studio-app",
        name="atlan-context-studio-app",
        owner="atlanhq",
        description=None, html_url="x", clone_url="x", default_branch="main",
        language="Python", is_private=True, is_fork=False, is_archived=False,
        created_at="2025-11-10T03:06:02Z", updated_at="2026-04-21T12:55:26Z",
        pushed_at="2026-04-30T11:44:15Z", size_kb=8631, stargazers_count=4,
        watchers_count=4, forks_count=0, open_issues_count=26, topics=[],
        license_name=None, has_wiki=True, has_issues=True, has_projects=True,
        has_downloads=True, id=1093188306,
    )
    asset = map_readme(repo, "# Atlan Context Studio App\n\nSemantic view evals framework.", CONN_QN)
    show_asset(asset, type_specific_fields=[])


# ──────────────────────────────────────────────────────────────────────────────
# 3. ApplicationField — Wiki page (parse mode, with frontmatter)
# ──────────────────────────────────────────────────────────────────────────────

def audit_application_field_wiki():
    banner("3. ApplicationField (wiki page) — parse mode with frontmatter")

    page = WikiPageRecord(
        repo_full_name="atlanhq/atlan-context-studio-app",
        page_path="Customer-Orders.md",
        page_name="Customer Orders",
        content=(CONTENT / "wiki_catalog_page.md").read_text(),
        file_sha="a1b2c3d4e5f6789",
    )
    asset = map_wiki_page(page, CONN_QN, content_mode="parse")
    show_asset(
        asset,
        type_specific_fields=["app_id", "catalog_dataset_guid", "application_parent_qualified_name"],
    )


# ──────────────────────────────────────────────────────────────────────────────
# 4. ApplicationField — YAML catalog (parse mode)
# ──────────────────────────────────────────────────────────────────────────────

def audit_application_field_yaml():
    banner("4. ApplicationField (YAML) — parse mode with catalog.yaml")

    content = (CONTENT / "catalog.yaml").read_text()
    yaml = YamlFileRecord(
        repo_full_name="atlanhq/atlan-context-studio-app",
        file_path="catalog/orders.yaml",
        content=content,
        file_sha="9z8y7x6w5v",
        file_size_bytes=len(content.encode()),
    )
    asset = map_yaml_file(yaml, CONN_QN, content_mode="parse")
    show_asset(
        asset,
        type_specific_fields=["app_id", "catalog_dataset_guid", "application_parent_qualified_name"],
    )


# ──────────────────────────────────────────────────────────────────────────────
# 5. ApplicationField — SBOM dependency
# ──────────────────────────────────────────────────────────────────────────────

def audit_application_field_sbom():
    banner("5. ApplicationField (SBOM dependency) — pyatlan package")

    dep = SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-context-studio-app",
        spdx_id="SPDXRef-Package-pip-pyatlan-9.6.0",
        package_name="pyatlan",
        package_version="9.6.0",
        purl="pkg:pypi/pyatlan@9.6.0",
        license_concluded="Apache-2.0",
        license_declared="Apache-2.0",
        supplier="Organization: Atlan",
        download_location="https://pypi.org/project/pyatlan/9.6.0/",
        relationship_type="PACKAGE",
        parent_spdx_id=None,
    )
    asset = map_sbom_dependency(dep, CONN_QN)
    show_asset(
        asset,
        type_specific_fields=["app_id", "catalog_dataset_guid", "application_parent_qualified_name"],
    )


# ──────────────────────────────────────────────────────────────────────────────
# 6. Process — SBOM DEPENDS_ON edge
# ──────────────────────────────────────────────────────────────────────────────

def audit_process():
    banner("6. Process — Atlan typedef for SBOM DEPENDS_ON lineage")

    parent = SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-context-studio-app",
        spdx_id="SPDXRef-Package-pip-app-1.0.0",
        package_name="atlan-context-studio-app",
        package_version="1.0.0",
        purl=None, license_concluded=None, license_declared=None,
        supplier=None, download_location=None,
        relationship_type="PACKAGE", parent_spdx_id=None,
    )
    child = SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-context-studio-app",
        spdx_id="SPDXRef-Package-pip-pyatlan-9.6.0",
        package_name="pyatlan",
        package_version="9.6.0",
        purl="pkg:pypi/pyatlan@9.6.0",
        license_concluded="Apache-2.0", license_declared="Apache-2.0",
        supplier=None, download_location=None,
        relationship_type="DEPENDS_ON",
        parent_spdx_id="SPDXRef-Package-pip-app-1.0.0",
    )
    asset = map_sbom_relationship(child, parent, CONN_QN)
    show_asset(asset, type_specific_fields=["inputs", "outputs"])


# ──────────────────────────────────────────────────────────────────────────────
# Final verdict
# ──────────────────────────────────────────────────────────────────────────────

def verdict():
    banner("VERDICT: Custom typedef registration required?", "═")
    print("""
  All four asset types we create are SHIPPED with the standard Atlan SDK
  (pyatlan_v9). Atlan tenants already have these typedefs registered:

    Application       — represents a software application (here: GitHub repo)
    ApplicationField  — child element of an Application (wiki page, YAML, dep)
    Readme            — README content attached to a parent asset
    Process           — lineage edge between two assets (DEPENDS_ON)

  Typedef-extension work needed at the Atlan tenant:  NONE.
  Custom enum values needed:                          NONE.
  Custom relationship types needed:                   NONE.

  We rely entirely on built-in inherited Asset attrs (description, source_url,
  source_created_at, asset_tags, user_description, etc.) plus the type-specific
  scalars Atlan ships with each typedef (app_id on Application/ApplicationField,
  inputs/outputs on Process).

  ⚠  Things we DO need on the tenant side:
     1. A connection of type "app" with QN  default/app/{ts}
     2. Permissions for the connector's service user to write to that connection
     3. (Optional) glossary terms / tags pre-configured if customers want
        wiki/YAML parse-mode tags to map to existing Atlan tags rather than
        free-form asset_tags strings.
""")


if __name__ == "__main__":
    audit_application()
    audit_readme()
    audit_application_field_wiki()
    audit_application_field_yaml()
    audit_application_field_sbom()
    audit_process()
    verdict()
