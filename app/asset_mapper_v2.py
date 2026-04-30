"""Phase 2 asset mappers — target the GitHubV01 custom typedefs.

Outputs raw Atlas entity dicts (typeName + attributes + relationshipAttributes)
matching the wire format Atlan accepts. We use dicts rather than typed SDK
classes because the Python SDK bindings won't exist until the atlanhq/models
PR lands and `sync-python-sdk` runs.

Key differences from the v1 mappers:

  v1 (pyatlan_v9 built-in types)               v2 (custom typedefs)
  ────────────────────────────────────────     ───────────────────────────────
  Application                                  GitHubV01Repository
  ApplicationField (wiki/yaml/sbom)            GitHubV01WikiPage / YAMLFile / SbomPackage
  Process (DEPENDS_ON edges)                   GitHubV01SbomDependency (+ peer rel)
  app_id = numeric repo ID                     gitHubV01StarCount, etc. — typed scalars
  user_description = "k=v | k=v"               structured filter-ready attributes
  asset_tags = topics                          gitHubV01TopicTags = topics
  qualifiedName: default/app/{ts}/...          qualifiedName: default/github/{ts}/...

qualifiedName conventions (per typedef ref §4 Phase F):
  Repository    : {conn_qn}/{org}/{repo}
  WikiPage      : {conn_qn}/{org}/{repo}/wiki/{path}
  YAMLFile      : {conn_qn}/{org}/{repo}/yaml/{path}
  SbomPackage   : {conn_qn}/{org}/{repo}/sbom/{spdx_id}
  SbomDependency: {parent_pkg_qn}/depends_on/{child_spdx_id}

The connection qualified name is expected to use the new connector type:
  default/github/{ts}     (NOT default/app/{ts})
The caller is responsible for passing the correct connection_qn — see
contracts.connector_type.
"""

from typing import Optional

from app.api_types import (
    RepoRecord,
    SbomDependencyRecord,
    WikiPageRecord,
    YamlFileRecord,
)
from app.asset_mapper import (
    _iso_to_epoch_ms,
    _parse_wiki_structured,
    _parse_yaml_catalog,
)
from app.typedefs_v2 import (
    ATTR_DEP_SCOPE,
    ATTR_REPO_CREATED_AT,
    ATTR_REPO_DEFAULT_BRANCH,
    ATTR_REPO_FORK_COUNT,
    ATTR_REPO_IS_ARCHIVED,
    ATTR_REPO_OPEN_ISSUE_COUNT,
    ATTR_REPO_PRIMARY_LANGUAGE,
    ATTR_REPO_STAR_COUNT,
    ATTR_REPO_TOPIC_TAGS,
    ATTR_REPO_UPDATED_AT,
    ATTR_REPO_URL,
    ATTR_REPO_VISIBILITY,
    ATTR_REPOSITORY_NAME,
    ATTR_REPOSITORY_ORG,
    ATTR_REPOSITORY_QN,
    ATTR_SBOM_ECOSYSTEM,
    ATTR_SBOM_LICENSE,
    ATTR_SBOM_PURL,
    ATTR_SBOM_SPDX_ID,
    ATTR_SBOM_VERSION,
    ATTR_WIKI_BLOB_SHA,
    ATTR_WIKI_FRONTMATTER_DOMAIN,
    ATTR_WIKI_FRONTMATTER_OWNER,
    ATTR_WIKI_FRONTMATTER_TAGS,
    ATTR_WIKI_PATH,
    ATTR_YAML_BLOB_SHA,
    ATTR_YAML_DOMAIN,
    ATTR_YAML_OWNER,
    ATTR_YAML_PATH,
    ATTR_YAML_TAGS,
    TYPE_REPOSITORY,
    TYPE_SBOM_DEPENDENCY,
    TYPE_SBOM_PACKAGE,
    TYPE_WIKI_PAGE,
    TYPE_YAML_FILE,
    map_sbom_ecosystem,
    map_visibility,
)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _repo_qn(connection_qn: str, repo_full_name: str) -> str:
    """{conn_qn}/{org}/{repo}"""
    return f"{connection_qn}/{repo_full_name}"


def _drop_none(d: dict) -> dict:
    """Strip None values so we don't transmit empty attributes (Atlas rejects some)."""
    return {k: v for k, v in d.items() if v is not None}


def _entity(
    type_name: str,
    qualified_name: str,
    name: str,
    connection_qn: str,
    attributes: dict,
    relationship_attributes: Optional[dict] = None,
) -> dict:
    """Build an Atlas entity dict in the standard wire format.

    Produces the shape consumed by `/api/meta/entity/bulk` and by the
    asset-import utility:

        {
          "typeName": "GitHubV01Repository",
          "attributes": {
            "qualifiedName": "...",
            "name": "...",
            "connectionQualifiedName": "...",
            ...
          },
          "relationshipAttributes": { ... }
        }
    """
    attrs = _drop_none(
        {
            "qualifiedName": qualified_name,
            "name": name,
            "connectionQualifiedName": connection_qn,
            **attributes,
        }
    )
    entity: dict = {"typeName": type_name, "attributes": attrs}
    if relationship_attributes:
        entity["relationshipAttributes"] = _drop_none(relationship_attributes)
    return entity


def _ref(type_name: str, qualified_name: str) -> dict:
    """A reference-by-qualifiedName for use in relationshipAttributes."""
    return {
        "typeName": type_name,
        "uniqueAttributes": {"qualifiedName": qualified_name},
    }


# ─── Repository ─────────────────────────────────────────────────────────────


def map_repository_v2(repo: RepoRecord, connection_qn: str) -> dict:
    """Map a GitHub repo to a GitHubV01Repository entity dict."""
    qn = _repo_qn(connection_qn, repo.full_name)

    return _entity(
        type_name=TYPE_REPOSITORY,
        qualified_name=qn,
        name=repo.name,
        connection_qn=connection_qn,
        attributes={
            "displayName": repo.full_name,
            "description": repo.description or "",
            "sourceURL": repo.html_url,
            "sourceCreatedBy": repo.owner,
            "sourceCreatedAt": _iso_to_epoch_ms(repo.created_at),
            # pushed_at — last commit, not last metadata edit (see v1 fix)
            "sourceUpdatedAt": _iso_to_epoch_ms(repo.pushed_at),
            "isDiscoverable": False if repo.is_private else None,
            # Containment hierarchy attrs (live on the supertype)
            ATTR_REPOSITORY_NAME: repo.name,
            ATTR_REPOSITORY_QN: qn,
            ATTR_REPOSITORY_ORG: repo.owner,
            # Repository-specific scalars
            ATTR_REPO_URL: repo.html_url,
            ATTR_REPO_DEFAULT_BRANCH: repo.default_branch,
            ATTR_REPO_VISIBILITY: map_visibility(repo.is_private),
            ATTR_REPO_PRIMARY_LANGUAGE: repo.language,
            ATTR_REPO_STAR_COUNT: repo.stargazers_count,
            ATTR_REPO_FORK_COUNT: repo.forks_count,
            ATTR_REPO_OPEN_ISSUE_COUNT: repo.open_issues_count,
            ATTR_REPO_TOPIC_TAGS: list(repo.topics) if repo.topics else None,
            ATTR_REPO_CREATED_AT: _iso_to_epoch_ms(repo.created_at),
            ATTR_REPO_UPDATED_AT: _iso_to_epoch_ms(repo.pushed_at),
            ATTR_REPO_IS_ARCHIVED: repo.is_archived,
        },
    )


# ─── WikiPage ───────────────────────────────────────────────────────────────


def map_wiki_page_v2(
    page: WikiPageRecord,
    connection_qn: str,
    content_mode: str = "index",
) -> dict:
    """Map a GitHub wiki page to a GitHubV01WikiPage entity dict.

    `content_mode` mirrors the v1 mapper:
      - "index" → description truncated to 500 chars
      - "full"  → description = full markdown
      - "parse" → frontmatter fields extracted into typed scalars; description
                  falls back to the parsed `description` key or full content
    """
    repo_qn = _repo_qn(connection_qn, page.repo_full_name)
    page_qn = f"{repo_qn}/wiki/{page.page_path}"
    org, repo_name = page.repo_full_name.split("/", 1)

    parsed: dict = {}
    if content_mode == "parse":
        parsed = _parse_wiki_structured(page.content)
        description = parsed.get("description") or page.content
    elif content_mode == "full":
        description = page.content
    else:  # index
        description = page.content[:500] + ("..." if len(page.content) > 500 else "")

    tags = parsed.get("tags") if content_mode == "parse" else None

    return _entity(
        type_name=TYPE_WIKI_PAGE,
        qualified_name=page_qn,
        name=page.page_name,
        connection_qn=connection_qn,
        attributes={
            "description": description,
            ATTR_REPOSITORY_NAME: repo_name,
            ATTR_REPOSITORY_QN: repo_qn,
            ATTR_REPOSITORY_ORG: org,
            ATTR_WIKI_PATH: page.page_path,
            ATTR_WIKI_BLOB_SHA: page.file_sha,
            ATTR_WIKI_FRONTMATTER_OWNER: parsed.get("owner") if content_mode == "parse" else None,
            # Raw verbatim string — DataDomain peer relationship is resolved by
            # a separate enrichment job (see typedef ref §8.4)
            ATTR_WIKI_FRONTMATTER_DOMAIN: parsed.get("domain") if content_mode == "parse" else None,
            ATTR_WIKI_FRONTMATTER_TAGS: [str(t) for t in tags] if tags else None,
        },
        relationship_attributes={
            "repository": _ref(TYPE_REPOSITORY, repo_qn),
        },
    )


# ─── YAMLFile ───────────────────────────────────────────────────────────────


def map_yaml_file_v2(
    yaml: YamlFileRecord,
    connection_qn: str,
    content_mode: str = "index",
) -> dict:
    """Map a YAML config file to a GitHubV01YAMLFile entity dict."""
    repo_qn = _repo_qn(connection_qn, yaml.repo_full_name)
    yaml_qn = f"{repo_qn}/yaml/{yaml.file_path}"
    org, repo_name = yaml.repo_full_name.split("/", 1)
    file_name = yaml.file_path.split("/")[-1]

    parsed: dict = {}
    if content_mode == "parse":
        parsed = _parse_yaml_catalog(yaml.content)
        description = parsed.get("description") or f"YAML configuration file: {yaml.file_path}"
    elif content_mode == "full":
        description = yaml.content
    else:
        description = f"YAML configuration file: {yaml.file_path}"

    tags = parsed.get("tags") if content_mode == "parse" else None

    return _entity(
        type_name=TYPE_YAML_FILE,
        qualified_name=yaml_qn,
        name=file_name,
        connection_qn=connection_qn,
        attributes={
            "description": description,
            ATTR_REPOSITORY_NAME: repo_name,
            ATTR_REPOSITORY_QN: repo_qn,
            ATTR_REPOSITORY_ORG: org,
            ATTR_YAML_PATH: yaml.file_path,
            ATTR_YAML_BLOB_SHA: yaml.file_sha,
            ATTR_YAML_OWNER: parsed.get("owner") if content_mode == "parse" else None,
            ATTR_YAML_DOMAIN: parsed.get("domain") if content_mode == "parse" else None,
            ATTR_YAML_TAGS: [str(t) for t in tags] if tags else None,
        },
        relationship_attributes={
            "repository": _ref(TYPE_REPOSITORY, repo_qn),
        },
    )


# ─── SbomPackage ────────────────────────────────────────────────────────────


def map_sbom_package_v2(dep: SbomDependencyRecord, connection_qn: str) -> dict:
    """Map an SBOM package declaration to a GitHubV01SbomPackage entity dict.

    Note: the same SbomDependencyRecord type is reused from v1 — it carries
    both the package metadata (used here) and the relationship to its parent
    (used in `map_sbom_dependency_edge_v2`).
    """
    repo_qn = _repo_qn(connection_qn, dep.repo_full_name)
    pkg_qn = f"{repo_qn}/sbom/{dep.spdx_id}"
    org, repo_name = dep.repo_full_name.split("/", 1)

    license_info = dep.license_concluded or dep.license_declared

    return _entity(
        type_name=TYPE_SBOM_PACKAGE,
        qualified_name=pkg_qn,
        name=dep.package_name,
        connection_qn=connection_qn,
        attributes={
            "description": (
                f"SBOM package: {dep.package_name} {dep.package_version or ''}"
            ).rstrip(),
            "sourceURL": dep.purl,
            ATTR_REPOSITORY_NAME: repo_name,
            ATTR_REPOSITORY_QN: repo_qn,
            ATTR_REPOSITORY_ORG: org,
            ATTR_SBOM_SPDX_ID: dep.spdx_id,
            ATTR_SBOM_PURL: dep.purl,
            ATTR_SBOM_VERSION: dep.package_version,
            ATTR_SBOM_LICENSE: license_info,
            ATTR_SBOM_ECOSYSTEM: map_sbom_ecosystem(dep.purl),
        },
        relationship_attributes={
            "repository": _ref(TYPE_REPOSITORY, repo_qn),
        },
    )


# ─── SbomDependency edge ────────────────────────────────────────────────────


def map_sbom_dependency_edge_v2(
    child: SbomDependencyRecord,
    parent: Optional[SbomDependencyRecord],
    connection_qn: str,
) -> Optional[dict]:
    """Map an SBOM DEPENDS_ON relationship.

    Per the typedef ref §6, the dependency graph is modelled two ways:
      1. A typed `GitHubV01SbomDependency` entity carrying scope/etc.
      2. A peer-to-peer relationship `sbomPackageDependencies` between
         the two `SbomPackage` entities (dependsOn / dependedOnBy).

    This mapper emits the typed dependency entity AND populates its
    relationshipAttributes so Atlas creates the peer edge in the same call.

    Returns None when the input is not a DEPENDS_ON edge or has no parent
    (matches v1 `map_sbom_relationship` semantics).
    """
    if not parent or child.relationship_type != "DEPENDS_ON":
        return None

    parent_qn = f"{_repo_qn(connection_qn, parent.repo_full_name)}/sbom/{parent.spdx_id}"
    child_qn = f"{_repo_qn(connection_qn, child.repo_full_name)}/sbom/{child.spdx_id}"
    edge_qn = f"{parent_qn}/depends_on/{child.spdx_id}"

    return _entity(
        type_name=TYPE_SBOM_DEPENDENCY,
        qualified_name=edge_qn,
        name=f"{parent.package_name} → {child.package_name}",
        connection_qn=connection_qn,
        attributes={
            "description": (
                f"Dependency: {parent.package_name} depends on {child.package_name}"
            ),
            ATTR_DEP_SCOPE: None,  # populated when GitHub SBOM exposes scope (runtime/dev)
        },
        relationship_attributes={
            # Peer-to-peer edge between the two packages — Atlas creates the
            # back-pointers (dependedOnBy) automatically from the Pkl.
            "dependsOnSource": _ref(TYPE_SBOM_PACKAGE, parent_qn),
            "dependsOnTarget": _ref(TYPE_SBOM_PACKAGE, child_qn),
        },
    )
