"""Phase 2 custom typedef names + attribute keys for the GitHub connector.

These constants centralise every type name, attribute key, and relationship
attribute that the v2 mapper layer emits. They are the single point of
adjustment when the typedefs are rendered from `atlanhq/models` Pkl and the
final wire-format strings are known.

Why a separate module:
  - The Pkl skeleton (see typedef reference §6) declares
    `namespace = "GitHubV01"` with `attrPrefix = namespace.decapitalize()`
    ("gitHubV01"). The toolkit prepends attrPrefix to every attribute name
    declared in the Pkl, so e.g. `repositoryName` becomes
    `gitHubV01RepositoryName` in the generated JSON.
  - Type names render as `{namespace}{TypeName}` per BigID precedent
    (UnstructuredV2Container etc.).
  - When the V01 suffix is dropped at GA, only this file changes; mappers
    stay untouched.

Until the Pkl is rendered against a dev tenant we cannot verify the exact
strings. The current values match Atlas's standard rendering rules for the
Pkl in §6 of the typedef reference doc; adjust only after running
`pkl eval typedefs/GitHub.pkl -m .` and inspecting the JSON.
"""

# ─── Namespace ──────────────────────────────────────────────────────────────
NAMESPACE = "GitHubV01"
ATTR_PREFIX = "gitHubV01"  # namespace.decapitalize()

# ─── Type names ─────────────────────────────────────────────────────────────
TYPE_REPOSITORY = f"{NAMESPACE}Repository"
TYPE_WIKI_PAGE = f"{NAMESPACE}WikiPage"
TYPE_YAML_FILE = f"{NAMESPACE}YAMLFile"
TYPE_SBOM_PACKAGE = f"{NAMESPACE}SbomPackage"
TYPE_SBOM_DEPENDENCY = f"{NAMESPACE}SbomDependency"

# ─── Enum values ────────────────────────────────────────────────────────────
class RepoVisibility:
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    INTERNAL = "INTERNAL"


class SbomEcosystem:
    PYPI = "PYPI"
    NPM = "NPM"
    MAVEN = "MAVEN"
    GO = "GO"
    CARGO = "CARGO"
    RUBYGEMS = "RUBYGEMS"
    NUGET = "NUGET"
    DOCKER = "DOCKER"
    OTHER = "OTHER"


# ─── Supertype attributes (containment hierarchy) ───────────────────────────
ATTR_REPOSITORY_NAME = f"{ATTR_PREFIX}RepositoryName"
ATTR_REPOSITORY_QN = f"{ATTR_PREFIX}RepositoryQualifiedName"
ATTR_REPOSITORY_ORG = f"{ATTR_PREFIX}RepositoryOrg"

# ─── Repository attributes ──────────────────────────────────────────────────
ATTR_REPO_URL = f"{ATTR_PREFIX}RepositoryUrl"
ATTR_REPO_DEFAULT_BRANCH = f"{ATTR_PREFIX}DefaultBranch"
ATTR_REPO_VISIBILITY = f"{ATTR_PREFIX}Visibility"
ATTR_REPO_PRIMARY_LANGUAGE = f"{ATTR_PREFIX}PrimaryLanguage"
ATTR_REPO_STAR_COUNT = f"{ATTR_PREFIX}StarCount"
ATTR_REPO_FORK_COUNT = f"{ATTR_PREFIX}ForkCount"
ATTR_REPO_OPEN_ISSUE_COUNT = f"{ATTR_PREFIX}OpenIssueCount"
ATTR_REPO_TOPIC_TAGS = f"{ATTR_PREFIX}TopicTags"
ATTR_REPO_CREATED_AT = f"{ATTR_PREFIX}RepoCreatedAt"
ATTR_REPO_UPDATED_AT = f"{ATTR_PREFIX}RepoUpdatedAt"
ATTR_REPO_IS_ARCHIVED = f"{ATTR_PREFIX}IsArchived"

# ─── WikiPage attributes ────────────────────────────────────────────────────
ATTR_WIKI_PATH = f"{ATTR_PREFIX}WikiPath"
ATTR_WIKI_FRONTMATTER_OWNER = f"{ATTR_PREFIX}WikiFrontmatterOwner"
ATTR_WIKI_FRONTMATTER_DOMAIN = f"{ATTR_PREFIX}WikiFrontmatterDomain"
ATTR_WIKI_FRONTMATTER_TAGS = f"{ATTR_PREFIX}WikiFrontmatterTags"
ATTR_WIKI_BLOB_SHA = f"{ATTR_PREFIX}WikiBlobSha"

# ─── YAMLFile attributes ────────────────────────────────────────────────────
ATTR_YAML_PATH = f"{ATTR_PREFIX}YamlPath"
ATTR_YAML_SCHEMA_PATH = f"{ATTR_PREFIX}YamlSchemaPath"
ATTR_YAML_OWNER = f"{ATTR_PREFIX}YamlOwner"
ATTR_YAML_DOMAIN = f"{ATTR_PREFIX}YamlDomain"
ATTR_YAML_TAGS = f"{ATTR_PREFIX}YamlTags"
ATTR_YAML_BLOB_SHA = f"{ATTR_PREFIX}YamlBlobSha"

# ─── SbomPackage attributes ─────────────────────────────────────────────────
ATTR_SBOM_ECOSYSTEM = f"{ATTR_PREFIX}SbomEcosystem"
ATTR_SBOM_VERSION = f"{ATTR_PREFIX}SbomVersion"
ATTR_SBOM_LICENSE = f"{ATTR_PREFIX}SbomLicense"
ATTR_SBOM_PURL = f"{ATTR_PREFIX}SbomPurl"
ATTR_SBOM_SPDX_ID = f"{ATTR_PREFIX}SbomSpdxId"
ATTR_SBOM_VULNERABILITY_COUNT = f"{ATTR_PREFIX}SbomVulnerabilityCount"

# ─── SbomDependency attributes ──────────────────────────────────────────────
ATTR_DEP_SCOPE = f"{ATTR_PREFIX}DependencyScope"

# ─── Relationship attribute names (containment) ─────────────────────────────
REL_REPO_TO_WIKI_PAGES = "wikiPages"
REL_REPO_TO_YAML_FILES = "yamlFiles"
REL_REPO_TO_SBOM_PACKAGES = "sbomPackages"
REL_BACKREF_REPOSITORY = "repository"

# ─── Relationship attribute names (peer-to-peer) ────────────────────────────
REL_SBOM_DEPENDS_ON = "dependsOn"
REL_SBOM_DEPENDED_ON_BY = "dependedOnBy"
REL_WIKI_DATA_DOMAIN = "wikiDataDomain"
REL_YAML_DATA_DOMAIN = "yamlDataDomain"
REL_YAML_REFS_SQL = "referencedSqlAssets"
REL_YAML_REFS_BI = "referencedBiAssets"


def map_visibility(is_private: bool) -> str:
    """Map GitHub `private` boolean to the RepoVisibility enum.

    GitHub's REST API does not surface 'internal' vs 'private' on the
    public /repos endpoint — both come back as private=true. Internal
    visibility is detectable via the `visibility` string field on
    enterprise-tier repos (visibility="internal"); callers that have
    that field should use it directly rather than this helper.
    """
    return RepoVisibility.PRIVATE if is_private else RepoVisibility.PUBLIC


def map_sbom_ecosystem(purl: str | None) -> str:
    """Infer SbomEcosystem enum from a Package URL (purl).

    purl format: pkg:{type}/{namespace}/{name}@{version}
    Examples:
        pkg:pypi/requests@2.28.0       → PYPI
        pkg:npm/lodash@4.17.21         → NPM
        pkg:maven/org.apache/log4j@2   → MAVEN
    """
    if not purl or not purl.startswith("pkg:"):
        return SbomEcosystem.OTHER

    type_part = purl[4:].split("/", 1)[0].lower()
    return {
        "pypi": SbomEcosystem.PYPI,
        "npm": SbomEcosystem.NPM,
        "maven": SbomEcosystem.MAVEN,
        "golang": SbomEcosystem.GO,
        "go": SbomEcosystem.GO,
        "cargo": SbomEcosystem.CARGO,
        "gem": SbomEcosystem.RUBYGEMS,
        "nuget": SbomEcosystem.NUGET,
        "docker": SbomEcosystem.DOCKER,
        "oci": SbomEcosystem.DOCKER,
    }.get(type_part, SbomEcosystem.OTHER)
