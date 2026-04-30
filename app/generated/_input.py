"""Auto-generated Pydantic models for workflow form inputs.

GENERATED FILE — DO NOT EDIT MANUALLY
Generated from: contract/app.pkl
Generated at: 2026-04-30

This file is excluded from ruff and pyright checks in pyproject.toml and .pre-commit-config.yaml.
"""

# ruff: noqa
# type: ignore

from typing import Optional, List
from pydantic import BaseModel, Field


class AuthStepInput(BaseModel):
    """Authentication step input."""

    credential: dict = Field(..., description="GitHub credential")
    extraction_method: str = Field(default="direct", description="Extraction routing mode")


class PreflightStepInput(BaseModel):
    """Preflight step input."""

    check_status: Optional[str] = Field(None, description="Preflight status (read-only)")


class MetadataStepInput(BaseModel):
    """Metadata extraction step input."""

    organization: str = Field(..., description="GitHub organization or user account")
    repositories: Optional[List[str]] = Field(None, description="Specific repos to extract")
    extract_wiki: bool = Field(default=False, description="Extract wiki pages")
    extract_yaml: bool = Field(default=False, description="Extract YAML files")
    extract_sbom: bool = Field(default=False, description="Extract SBOM dependencies")
    sbom_poll_interval_seconds: int = Field(default=15, description="SBOM polling interval")
    preflight_check: bool = Field(default=True, description="Run preflight check")


class WorkflowInput(BaseModel):
    """Complete workflow input (all steps combined)."""

    auth: AuthStepInput
    preflight: PreflightStepInput
    metadata: MetadataStepInput
