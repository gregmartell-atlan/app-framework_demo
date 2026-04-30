"""Preview the Phase 2 (custom typedef) outputs.

For each asset type, prints two artifacts:

  (A) The Atlas typedef JSON that `pkl eval typedefs/GitHub.pkl -m .`
      will emit into atlanhq/models/atlas/entityDefs/Referenceable/Asset/Catalog/.
      Hand-rendered here using the same conventions verified against
      AtlanAppInstalled.json (toolkit prepends attrPrefix, capitalises first
      letter, types/enums get the namespace+suffix prefix).

  (B) The entity payload our v2 mapper emits today — what the connector
      would POST to /api/meta/entity/bulk against a tenant that has the
      typedefs seeded.

(A) is what the platform team reviews in atlanhq/models PR.
(B) is what we already produce in this repo (no Atlan write needed).

Run:
    python3 scripts/v2_preview.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

CONN_QN = "default/github/1700000000"


def banner(text: str, char: str = "═"):
    print()
    print(char * 100)
    print(f" {text}")
    print(char * 100)


def show_pair(typedef_json: dict, payload: dict):
    print()
    print("  ── (A) Rendered typedef JSON  (atlas/entityDefs/.../<TypeName>.json) ──")
    print()
    for line in json.dumps(typedef_json, indent=2).splitlines():
        print(f"    {line}")
    print()
    print("  ── (B) Entity payload emitted by the connector  (POST /api/meta/entity/bulk) ──")
    print()
    for line in json.dumps(payload, indent=2).splitlines():
        print(f"    {line}")


# ──────────────────────────────────────────────────────────────────────────────
# Typedef JSON (hand-rendered to match what pkl eval would emit)
# ──────────────────────────────────────────────────────────────────────────────
# Conventions (verified against AtlanApp/AtlanAppInstalled.json + toolkit Pkl):
#   typeName      = "{namespace}{LocalName}"  (with V01 suffix while drafting)
#   attribute     = "{attrPrefix}{Capitalize(LocalName)}"
#   superTypes    = ["{namespace}"]            (the supertype name)
#   serviceType   = "atlan" for entity defs, "atlas_core" for enum defs
#   typeVersion   = matches `version` in the Pkl
#   indexType     = "STRING" for keyword strings (default for type=string)
#   skipScrubbing = true (default emitted by the toolkit)


def _str_attr(name: str, description: str, multi: bool = False, indexed: str = "STRING") -> dict:
    a = {
        "name": name,
        "description": description,
        "typeName": "array<string>" if multi else "string",
        "isOptional": True,
        "cardinality": "SET" if multi else "SINGLE",
        "isUnique": False,
        "isIndexable": False,
        "includeInNotification": True,
        "skipScrubbing": True,
    }
    if not multi:
        a["indexType"] = indexed
    return a


def _scalar_attr(name: str, description: str, type_name: str) -> dict:
    return {
        "name": name,
        "description": description,
        "typeName": type_name,
        "isOptional": True,
        "cardinality": "SINGLE",
        "isUnique": False,
        "isIndexable": False,
        "includeInNotification": True,
        "skipScrubbing": True,
    }


def repository_typedef() -> dict:
    return {
        "entityDefs": [{
            "name": "GitHubV01Repository",
            "category": "ENTITY",
            "description": "A GitHub repository.",
            "serviceType": "atlan",
            "typeVersion": "1.0",
            "superTypes": ["GitHubV01"],
            "attributeDefs": [
                _str_attr("gitHubV01RepositoryUrl", "HTML URL of the repository."),
                _str_attr("gitHubV01DefaultBranch", "Name of the repository's default branch."),
                {
                    "name": "gitHubV01Visibility",
                    "description": "Repository visibility (public / private / internal).",
                    "typeName": "GitHubV01RepoVisibility",
                    "isOptional": True, "cardinality": "SINGLE", "isUnique": False,
                    "isIndexable": False, "includeInNotification": True, "skipScrubbing": True,
                },
                _str_attr("gitHubV01PrimaryLanguage", "Dominant language detected by GitHub."),
                _scalar_attr("gitHubV01StarCount", "Number of stargazers.", "long"),
                _scalar_attr("gitHubV01ForkCount", "Number of forks.", "long"),
                _scalar_attr("gitHubV01OpenIssueCount", "Open issues + pull requests.", "long"),
                _str_attr("gitHubV01TopicTags", "GitHub topic tags applied to the repository.", multi=True),
                _scalar_attr("gitHubV01RepoCreatedAt", "Repository creation timestamp (epoch ms).", "date"),
                _scalar_attr("gitHubV01RepoUpdatedAt", "Repository last-pushed timestamp (epoch ms). Sourced from GitHub `pushed_at` for code-currency accuracy.", "date"),
                _scalar_attr("gitHubV01IsArchived", "Whether the repository is archived (read-only on GitHub).", "boolean"),
            ],
        }],
    }


def repo_visibility_enum() -> dict:
    return {
        "enumDefs": [{
            "name": "GitHubV01RepoVisibility",
            "category": "ENUM",
            "description": "Visibility level of a GitHub repository.",
            "serviceType": "atlas_core",
            "typeVersion": "1.0",
            "elementDefs": [
                {"ordinal": 0, "value": "PUBLIC", "description": "Publicly visible repository."},
                {"ordinal": 1, "value": "PRIVATE", "description": "Visible only to org members or collaborators."},
                {"ordinal": 2, "value": "INTERNAL", "description": "Visible only to enterprise members (GitHub Enterprise)."},
            ],
        }],
    }


def wiki_page_typedef() -> dict:
    return {
        "entityDefs": [{
            "name": "GitHubV01WikiPage",
            "category": "ENTITY",
            "description": "A wiki page or repo Markdown document.",
            "serviceType": "atlan",
            "typeVersion": "1.0",
            "superTypes": ["GitHubV01"],
            "attributeDefs": [
                _str_attr("gitHubV01WikiPath", "Path of the wiki page within the wiki tree."),
                _str_attr("gitHubV01WikiFrontmatterOwner", "Owner declared in YAML frontmatter (raw, verbatim from source)."),
                _str_attr("gitHubV01WikiFrontmatterDomain", "Domain declared in YAML frontmatter (raw, verbatim from source). Canonical resolution to a DataDomain is handled by a downstream enrichment job."),
                _str_attr("gitHubV01WikiFrontmatterTags", "Tags declared in YAML frontmatter.", multi=True),
                _str_attr("gitHubV01WikiBlobSha", "Git blob SHA — stable identifier for this version of the page."),
            ],
        }],
    }


def yaml_file_typedef() -> dict:
    return {
        "entityDefs": [{
            "name": "GitHubV01YAMLFile",
            "category": "ENTITY",
            "description": "A YAML configuration or catalog file in a GitHub repository.",
            "serviceType": "atlan",
            "typeVersion": "1.0",
            "superTypes": ["GitHubV01"],
            "attributeDefs": [
                _str_attr("gitHubV01YamlPath", "Path of the YAML file within the repository."),
                _str_attr("gitHubV01YamlSchemaPath", "JSON-Schema reference declared in the YAML, if present."),
                _str_attr("gitHubV01YamlOwner", "Owner declared in the YAML body (raw, verbatim from source)."),
                _str_attr("gitHubV01YamlDomain", "Domain declared in the YAML body (raw, verbatim from source). Canonical resolution to a DataDomain is handled by a downstream enrichment job."),
                _str_attr("gitHubV01YamlTags", "Tags declared in the YAML body.", multi=True),
                _str_attr("gitHubV01YamlBlobSha", "Git blob SHA — stable identifier for this version of the file."),
            ],
        }],
    }


def sbom_dependency_typedef() -> dict:
    return {
        "entityDefs": [{
            "name": "GitHubV01SbomDependency",
            "category": "ENTITY",
            "description": "A DEPENDS_ON edge between two SBOM packages.",
            "serviceType": "atlan",
            "typeVersion": "1.0",
            "superTypes": ["GitHubV01"],
            "attributeDefs": [
                _str_attr("gitHubV01DependencyScope", "Scope of the dependency (runtime, dev, optional, etc)."),
            ],
        }],
    }


def sbom_ecosystem_enum() -> dict:
    return {
        "enumDefs": [{
            "name": "GitHubV01SbomEcosystem",
            "category": "ENUM",
            "description": "Package ecosystem for an SBOM dependency.",
            "serviceType": "atlas_core",
            "typeVersion": "1.0",
            "elementDefs": [
                {"ordinal": i, "value": v, "description": d}
                for i, (v, d) in enumerate([
                    ("PYPI", "Python Package Index."),
                    ("NPM", "Node Package Manager."),
                    ("MAVEN", "Maven Central."),
                    ("GO", "Go modules."),
                    ("CARGO", "Rust Cargo."),
                    ("RUBYGEMS", "Ruby Gems."),
                    ("NUGET", "NuGet (.NET)."),
                    ("DOCKER", "Docker / OCI image."),
                    ("OTHER", "Other or unknown ecosystem."),
                ])
            ],
        }],
    }


def relationship_defs() -> dict:
    """Containment relationships emit into a separate _relationships.json file."""
    def _containment(name, parent_type, parent_attr, parent_desc, child_type, child_attr, child_desc):
        return {
            "name": name,
            "category": "RELATIONSHIP",
            "serviceType": "atlan",
            "typeVersion": "1.0",
            "relationshipCategory": "AGGREGATION",
            "propagateTags": "NONE",
            "endDef1": {
                "type": parent_type, "name": child_attr,
                "isContainer": True, "cardinality": "SET",
                "isLegacyAttribute": False, "description": child_desc,
            },
            "endDef2": {
                "type": child_type, "name": parent_attr,
                "isContainer": False, "cardinality": "SINGLE",
                "isLegacyAttribute": False, "description": parent_desc,
            },
        }
    return {
        "relationshipDefs": [
            _containment(
                "github_v01_repository_and_its_wiki_pages",
                "GitHubV01Repository", "repository", "Repository containing the wiki page.",
                "GitHubV01WikiPage", "wikiPages", "Wiki pages contained within this repository.",
            ),
            _containment(
                "github_v01_repository_and_its_yaml_files",
                "GitHubV01Repository", "repository", "Repository containing the YAML file.",
                "GitHubV01YAMLFile", "yamlFiles", "YAML files contained within this repository.",
            ),
            _containment(
                "github_v01_repository_and_its_sbom_packages",
                "GitHubV01Repository", "repository", "Repository declaring the SBOM package.",
                "GitHubV01SbomPackage", "sbomPackages", "SBOM packages declared by this repository.",
            ),
            _containment(
                "github_v01_sbom_package_dependencies",
                "GitHubV01SbomPackage", "dependsOn", "Package that depends on others.",
                "GitHubV01SbomDependency", "outgoingDependencies", "Outgoing DEPENDS_ON edges from this package.",
            ),
        ],
    }


def sbom_package_typedef() -> dict:
    return {
        "entityDefs": [{
            "name": "GitHubV01SbomPackage",
            "category": "ENTITY",
            "description": "A package declared in a Software Bill of Materials.",
            "serviceType": "atlan",
            "typeVersion": "1.0",
            "superTypes": ["GitHubV01"],
            "attributeDefs": [
                {
                    "name": "gitHubV01SbomEcosystem",
                    "description": "Package ecosystem (inferred from purl scheme).",
                    "typeName": "GitHubV01SbomEcosystem",
                    "isOptional": True, "cardinality": "SINGLE", "isUnique": False,
                    "isIndexable": False, "includeInNotification": True, "skipScrubbing": True,
                },
                _str_attr("gitHubV01SbomVersion", "Version pinned in the SBOM."),
                _str_attr("gitHubV01SbomLicense", "Declared or concluded license (SPDX ID)."),
                _str_attr("gitHubV01SbomPurl", "Canonical Package URL (purl)."),
                _str_attr("gitHubV01SbomSpdxId", "SPDX identifier from the SBOM document."),
                _scalar_attr("gitHubV01SbomVulnerabilityCount", "Count of known CVEs against this package version (populated by enrichment).", "long"),
            ],
        }],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Mapper inputs (realistic, based on captured atlan-context-studio-app metadata)
# ──────────────────────────────────────────────────────────────────────────────


def sample_repo() -> RepoRecord:
    return RepoRecord(
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
        stargazers_count=4, watchers_count=4, forks_count=0, open_issues_count=26,
        topics=["semantic-views", "evals", "atlan-app"],
        license_name=None,
        has_wiki=True, has_issues=True, has_projects=True, has_downloads=True,
        id=1093188306,
    )


def sample_wiki() -> WikiPageRecord:
    return WikiPageRecord(
        repo_full_name="atlanhq/atlan-context-studio-app",
        page_path="Customer-Orders.md",
        page_name="Customer Orders",
        content=(
            "---\n"
            "owner: data-platform-team\n"
            "domain: commerce\n"
            "tags: [orders, transactions, pii]\n"
            "---\n"
            "# Customer Orders\n"
            "Aggregated order data across regions.\n"
        ),
        file_sha="a1b2c3d4e5f6789",
    )


def sample_yaml() -> YamlFileRecord:
    content = (
        "# Catalog manifest for the orders dataset\n"
        "owner: data-platform-team\n"
        "domain: commerce\n"
        "description: Aggregated customer orders, refreshed nightly.\n"
        "tags: [orders, transactions, pii]\n"
        "schema: https://schemas.atlan.com/catalog/v1.json\n"
    )
    return YamlFileRecord(
        repo_full_name="atlanhq/atlan-context-studio-app",
        file_path="catalog/orders.yaml",
        content=content,
        file_sha="9z8y7x6w5v",
        file_size_bytes=len(content.encode()),
    )


def sample_sbom_parent() -> SbomDependencyRecord:
    return SbomDependencyRecord(
        repo_full_name="atlanhq/atlan-context-studio-app",
        spdx_id="SPDXRef-Package-pip-app-1.0.0",
        package_name="atlan-context-studio-app",
        package_version="1.0.0",
        purl=None,
        license_concluded=None, license_declared=None,
        supplier=None, download_location=None,
        relationship_type="PACKAGE", parent_spdx_id=None,
    )


def sample_sbom_edge_child() -> SbomDependencyRecord:
    return SbomDependencyRecord(
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


def sample_sbom_pkg() -> SbomDependencyRecord:
    return SbomDependencyRecord(
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


# ──────────────────────────────────────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────────────────────────────────────


def show_json(label: str, payload: dict):
    print()
    print(f"  ── {label} ──")
    print()
    for line in json.dumps(payload, indent=2).splitlines():
        print(f"    {line}")


def main():
    repo = sample_repo()
    wiki = sample_wiki()
    yaml = sample_yaml()
    pkg = sample_sbom_pkg()
    parent_pkg = sample_sbom_parent()
    child_pkg = sample_sbom_edge_child()

    banner("1. GitHubV01Repository — typedef JSON + entity payload")
    show_pair(repository_typedef(), map_repository_v2(repo, CONN_QN))

    banner("2. GitHubV01RepoVisibility — enum JSON")
    show_json("GitHubV01RepoVisibility.json", repo_visibility_enum())

    banner("3. GitHubV01WikiPage — typedef JSON + entity payload (parse mode)")
    show_pair(
        wiki_page_typedef(),
        map_wiki_page_v2(wiki, CONN_QN, content_mode="parse"),
    )

    banner("4. GitHubV01YAMLFile — typedef JSON + entity payload (parse mode)")
    show_pair(
        yaml_file_typedef(),
        map_yaml_file_v2(yaml, CONN_QN, content_mode="parse"),
    )

    banner("5. GitHubV01SbomPackage — typedef JSON + entity payload")
    show_pair(sbom_package_typedef(), map_sbom_package_v2(pkg, CONN_QN))

    banner("6. GitHubV01SbomEcosystem — enum JSON")
    show_json("GitHubV01SbomEcosystem.json", sbom_ecosystem_enum())

    banner("7. GitHubV01SbomDependency — typedef JSON + entity payload (DEPENDS_ON edge)")
    show_pair(
        sbom_dependency_typedef(),
        map_sbom_dependency_edge_v2(child_pkg, parent_pkg, CONN_QN),
    )

    banner("8. Relationship defs — GitHub_relationships.json")
    show_json("GitHub_relationships.json (4 containment relationships)", relationship_defs())

    banner("VERDICT", "═")
    print("""
  - The typedef JSON in (A) is what `pkl eval typedefs/GitHub.pkl -m .` will emit
    into atlanhq/models/atlas/entityDefs/Referenceable/Asset/Catalog/GitHub/.
    Confirmed against the toolkit's rendering rules and AtlanAppInstalled.json
    precedent.
  - The entity payloads in (B) are what this connector emits today via
    app/asset_mapper_v2.py. Once the typedefs in (A) are seeded on a tenant,
    POSTing the (B) payload to /api/meta/entity/bulk will create matching assets.
  - The Pkl source is checked in at docs/typedefs/GitHub.pkl. Copy that into
    atlanhq/models/typedefs/ when starting the Phase 2 PR.
""")


if __name__ == "__main__":
    main()
