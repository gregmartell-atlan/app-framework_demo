"""Pydantic contracts for GitHub connector inputs and outputs.

All @entrypoint and @task methods use these typed contracts.
Handler-level contracts (AuthInput etc.) remain plain BaseModel since they
are HTTP boundary types, not Temporal payloads.
"""

from typing import Optional
from pydantic import BaseModel, Field

from application_sdk.app import Input, Output
from application_sdk.contracts.base import HeartbeatDetails


# ============================================================================
# Handler-level contracts (HTTP boundary — plain BaseModel)
# ============================================================================

class AuthInput(BaseModel):
    """Input for the auth handler (HTTP boundary, not Temporal)."""

    credential: dict = Field(default_factory=dict, description="GitHub credential")
    extraction_method: str = Field(default="direct")


class AuthOutput(BaseModel):
    """Output from the auth handler."""

    status: str
    message: str
    user_login: Optional[str] = None


class PreflightInput(BaseModel):
    """Input for the preflight handler (HTTP boundary, not Temporal)."""

    organization: str = Field(default="", description="GitHub org or user")
    credential: dict = Field(default_factory=dict, description="GitHub credential")


class PreflightOutput(BaseModel):
    """Output from the preflight handler."""

    status: str
    message: str
    scopes: list[str] = Field(default_factory=list)
    rate_limit_remaining: Optional[int] = None
    rate_limit_reset_at: Optional[str] = None


# ============================================================================
# Top-level workflow contracts (Temporal — must extend Input / Output)
# ============================================================================

class GitHubMetadataInput(Input, allow_unbounded_fields=True):
    """Form input for the fetch_metadata @entrypoint workflow.

    Field names match github.json form properties exactly so the SPA can
    post them directly as the workflow payload.
    """

    github_token: str = Field(default="", description="GitHub Personal Access Token")
    organization: str = Field(default="", description="GitHub org or user account")
    repositories: list[str] = Field(default_factory=list, description="Specific repos (empty = all)")
    extract_wiki: bool = Field(default=False, description="Extract wiki pages")
    extract_yaml: bool = Field(default=False, description="Extract YAML files")
    extract_sbom: bool = Field(default=False, description="Extract SBOM dependencies")
    sbom_poll_interval_seconds: int = Field(default=15, description="SBOM polling interval")
    max_items: int = Field(default=1000, description="Max repositories to fetch")


class GitHubMetadataOutput(Output):
    """Workflow output from fetch_metadata."""

    repos_count: int = 0
    wiki_pages_count: int = 0
    yaml_files_count: int = 0
    sbom_dependencies_count: int = 0
    extraction_summary: str = ""
    status: str = "succeeded"


# ============================================================================
# Task-level contracts (Temporal activities — must extend Input / Output)
# ============================================================================

class FetchReposInput(Input, allow_unbounded_fields=True):
    """Input for the fetch_repos @task."""

    github_token: str = Field(default="", description="GitHub PAT")
    organization: str = Field(default="", description="GitHub org or user account")
    repositories: list[str] = Field(default_factory=list, description="Filter list (empty = all)")
    extract_wiki: bool = False
    extract_yaml: bool = False
    max_items: int = 1000
    output_dir: str = Field(default="", description="Output directory path")


class FetchReposOutput(Output):
    """Output from the fetch_repos @task."""

    repos_count: int = 0
    wiki_pages_count: int = 0
    yaml_files_count: int = 0
    repos_file_path: str = ""
    wiki_file_path: str = ""
    yaml_file_path: str = ""
    extraction_summary: str = ""


class FetchSbomInput(Input, allow_unbounded_fields=True):
    """Input for the fetch_sbom @task."""

    repositories: list[str] = Field(default_factory=list, description="Repo full names")
    organization: str = Field(default="", description="GitHub org")
    github_token: str = Field(default="", description="GitHub PAT")
    poll_interval_seconds: int = Field(default=15)
    output_dir: str = Field(default="", description="Output directory path")


class FetchSbomOutput(Output, allow_unbounded_fields=True):
    """Output from the fetch_sbom @task."""

    sbom_file_paths: list[str] = Field(default_factory=list)
    successful_repos: list[str] = Field(default_factory=list)
    failed_repos: list[str] = Field(default_factory=list)
    summary: str = ""


class SbomProgress(HeartbeatDetails):
    """Typed heartbeat for the fetch_sbom task — enables resume after timeout."""

    repo_full_name: str
    report_id: Optional[str] = None
    started_at_iso: str
    poll_attempts: int = 0


class TransformInput(Input, allow_unbounded_fields=True):
    """Input for the transform @task."""

    repos_file_path: str = ""
    wiki_file_path: str = ""
    yaml_file_path: str = ""
    sbom_file_path: str = ""
    connection_qualified_name: str = ""
    atlan_base_url: str = ""
    atlan_api_key: str = ""


class TransformOutput(Output):
    """Output from the transform @task."""

    assets_created: int = 0
    assets_updated: int = 0
    repos_count: int = 0
    wiki_pages_count: int = 0
    yaml_files_count: int = 0
    sbom_dependencies_count: int = 0
    sbom_relationships_count: int = 0


# ============================================================================
# Backward-compat aliases — keep legacy tests passing
# ============================================================================

class FileReference(BaseModel):
    """Local file reference (used in unit tests and legacy code)."""

    path: str
    retention: str = "RETAINED"
    size_bytes: Optional[int] = None


class MaxItems(BaseModel):
    """Pagination/limit control (legacy helper)."""

    max_items: int = 1000


# Aliases for legacy test imports
GitHubExtractionInput = FetchReposInput
GitHubExtractionOutput = FetchReposOutput
