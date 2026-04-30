"""Pydantic contracts for GitHub connector inputs and outputs.

All handler and task methods use these typed contracts (no bare Dict/Any at boundaries).
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# ============================================================================
# Reusable helper types
# ============================================================================

class MaxItems(BaseModel):
    """Pagination/limit control."""

    max_items: int = Field(default=1000, description="Maximum items to fetch")


class FileReference(BaseModel):
    """Reference to a file stored in the app's file system or object storage.

    Files marked as RETAINED are preserved across task retries.
    """

    path: str = Field(..., description="File path relative to task working directory")
    retention: str = Field(default="RETAINED", description="File retention policy")
    size_bytes: Optional[int] = Field(None, description="File size in bytes")


class HeartbeatDetails(BaseModel):
    """Base class for typed heartbeat payloads.

    Tasks can subclass this to store custom resume state.
    """

    pass


# ============================================================================
# Auth handler contracts
# ============================================================================

class AuthInput(BaseModel):
    """Input for the auth handler."""

    credential: dict = Field(..., description="GitHub credential (token)")
    extraction_method: str = Field(default="direct", description="Extraction routing mode")


class AuthOutput(BaseModel):
    """Output from the auth handler."""

    status: str = Field(..., description="Authentication status (success/failure)")
    message: str = Field(..., description="Human-readable status message")
    user_login: Optional[str] = Field(None, description="Authenticated GitHub user login")


# ============================================================================
# Preflight handler contracts
# ============================================================================

class PreflightInput(BaseModel):
    """Input for the preflight handler."""

    organization: str = Field(..., description="GitHub organization or user account")
    credential: dict = Field(..., description="GitHub credential")


class PreflightOutput(BaseModel):
    """Output from the preflight handler."""

    status: str = Field(..., description="Preflight status (success/warning/failure)")
    message: str = Field(..., description="Human-readable status message")
    scopes: list[str] = Field(default_factory=list, description="Detected token scopes")
    rate_limit_remaining: Optional[int] = Field(None, description="GitHub API rate limit remaining")
    rate_limit_reset_at: Optional[str] = Field(None, description="Rate limit reset time (ISO 8601)")


# ============================================================================
# Metadata extraction contracts
# ============================================================================

class GitHubExtractionInput(BaseModel):
    """Input for the main metadata extraction task."""

    organization: str = Field(..., description="GitHub organization or user account")
    repositories: Optional[list[str]] = Field(None, description="Specific repos (None = all)")
    extract_wiki: bool = Field(default=False, description="Extract wiki pages")
    extract_yaml: bool = Field(default=False, description="Extract YAML files")
    extract_sbom: bool = Field(default=False, description="Extract SBOM dependencies")
    sbom_poll_interval_seconds: int = Field(default=15, description="SBOM polling interval")
    credential: dict = Field(..., description="GitHub credential")
    connection_qualified_name: str = Field(..., description="Atlan connection QN")
    max_items: MaxItems = Field(default_factory=MaxItems, description="Pagination limits")
    wiki_content_mode: Literal["index", "full", "parse"] = Field(
        default="index",
        description=(
            "How wiki page content is stored in Atlan. "
            "'index' truncates to 500 chars (default, low storage); "
            "'full' stores the complete markdown content; "
            "'parse' extracts structured fields (owner, domain, tags) from "
            "YAML frontmatter or ## Header patterns and maps them to Atlan attributes."
        ),
    )
    yaml_content_mode: Literal["index", "full", "parse"] = Field(
        default="index",
        description=(
            "How YAML file content is stored in Atlan. "
            "'index' stores only the file path reference (default); "
            "'full' stores the complete raw YAML content; "
            "'parse' extracts catalog metadata keys (owner, domain, description, tags) "
            "and maps them to Atlan attributes — useful for catalog.yaml / schema.yaml patterns."
        ),
    )


class GitHubExtractionOutput(BaseModel):
    """Output from the main metadata extraction task."""

    repos_file: Optional[FileReference] = Field(None, description="Repository data file")
    wiki_file: Optional[FileReference] = Field(None, description="Wiki pages data file")
    yaml_file: Optional[FileReference] = Field(None, description="YAML files data file")
    sbom_file: Optional[FileReference] = Field(None, description="SBOM dependencies data file")
    extraction_summary: str = Field(..., description="Summary of extraction results")
    repos_count: int = Field(default=0, description="Number of repositories extracted")
    wiki_pages_count: int = Field(default=0, description="Number of wiki pages extracted")
    yaml_files_count: int = Field(default=0, description="Number of YAML files extracted")
    sbom_dependencies_count: int = Field(default=0, description="Number of SBOM dependencies extracted")


# ============================================================================
# SBOM-specific contracts (Phase 2)
# ============================================================================

class SbomProgress(HeartbeatDetails):
    """Typed heartbeat for SBOM fetch task (supports resume after timeout).

    Stores current progress so the task can resume from where it left off
    if it times out or is retried.
    """

    repo_full_name: str = Field(..., description="Current repository being processed")
    report_id: Optional[str] = Field(None, description="GitHub SBOM report ID (if generation started)")
    started_at_iso: str = Field(..., description="When SBOM generation started (ISO 8601)")
    poll_attempts: int = Field(default=0, description="Number of polling attempts so far")


class FetchSbomInput(BaseModel):
    """Input for the fetch_sbom task."""

    repositories: list[str] = Field(..., description="List of repo full names to generate SBOMs for")
    organization: str = Field(..., description="GitHub organization or user account")
    credential: dict = Field(..., description="GitHub credential")
    poll_interval_seconds: int = Field(default=15, description="How often to poll SBOM status")
    output_dir: str = Field(..., description="Directory to write SBOM files to")


class FetchSbomOutput(BaseModel):
    """Output from the fetch_sbom task."""

    sbom_files: list[FileReference] = Field(default_factory=list, description="Generated SBOM files")
    successful_repos: list[str] = Field(default_factory=list, description="Repos with successful SBOM generation")
    failed_repos: list[str] = Field(default_factory=list, description="Repos that failed SBOM generation")
    summary: str = Field(..., description="Summary of SBOM generation results")


class TransformSbomInput(BaseModel):
    """Input for transforming SBOM data to Atlan assets."""

    sbom_file: FileReference = Field(..., description="SBOM dependencies file")
    connection_qualified_name: str = Field(..., description="Atlan connection QN")


class TransformSbomOutput(BaseModel):
    """Output from SBOM transformation."""

    dependencies_created: int = Field(default=0, description="ApplicationField assets created for dependencies")
    relationships_created: int = Field(default=0, description="Process assets created for DEPENDS_ON relationships")
    summary: str = Field(..., description="Transformation summary")


# ============================================================================
# Transform task contracts
# ============================================================================

class TransformInput(BaseModel):
    """Input for the transform task."""

    repos_file: Optional[FileReference] = Field(None, description="Repository data file")
    wiki_file: Optional[FileReference] = Field(None, description="Wiki pages data file")
    yaml_file: Optional[FileReference] = Field(None, description="YAML files data file")
    sbom_file: Optional[FileReference] = Field(None, description="SBOM dependencies data file")
    connection_qualified_name: str = Field(..., description="Atlan connection QN")
    wiki_content_mode: Literal["index", "full", "parse"] = Field(
        default="index",
        description="Wiki content mode — must match the value used during extraction.",
    )
    yaml_content_mode: Literal["index", "full", "parse"] = Field(
        default="index",
        description="YAML content mode — must match the value used during extraction.",
    )


class TransformOutput(BaseModel):
    """Output from the transform task."""

    assets_created: int = Field(default=0, description="Total assets created")
    assets_updated: int = Field(default=0, description="Total assets updated")
    repos_count: int = Field(default=0, description="Repository assets")
    wiki_pages_count: int = Field(default=0, description="Wiki page assets")
    yaml_files_count: int = Field(default=0, description="YAML file assets")
    sbom_dependencies_count: int = Field(default=0, description="SBOM dependency assets")
    sbom_relationships_count: int = Field(default=0, description="SBOM relationship assets")
