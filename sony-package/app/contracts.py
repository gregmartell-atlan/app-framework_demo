"""Pydantic contracts for the wiki → glossary sync."""

from typing import Optional
from pydantic import BaseModel, Field


class GlossarySyncConfig(BaseModel):
    """Input config for the shared wiki → glossary sync routine."""

    repo_full_name: str = Field(..., description="GitHub repo (org/name) whose wiki to sync")
    github_token: str = Field(..., description="GitHub token used to clone the wiki")
    glossary_name: str = Field(default="sony_telemetry", description="Target Atlan glossary name")
    phase1_filter: bool = Field(
        default=True,
        description="If True, only push Client + Shared Schemas pages (Phase 1 scope)",
    )
    dry_run: bool = Field(
        default=False,
        description="If True, log what would be saved but never call client.asset.save()",
    )


class GlossarySyncResult(BaseModel):
    """Outcome of a wiki → glossary sync."""

    glossary_qn: Optional[str] = None
    glossary_guid: Optional[str] = None
    pages_scanned: int = 0
    pages_filtered_out: int = 0
    categories_created: int = 0
    terms_created: int = 0
    terms_updated: int = 0
    readmes_saved: int = 0
    relationships_linked: int = 0
    errors: list[str] = Field(default_factory=list)
    dry_run: bool = False
