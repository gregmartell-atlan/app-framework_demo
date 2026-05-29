"""Atlan credential for the standalone script and GitHub Actions paths."""

from pydantic import BaseModel, Field


class AtlanCredential(BaseModel):
    """Atlan tenant credential — base URL + API key."""

    base_url: str = Field(..., description="Atlan tenant base URL, e.g. https://dsm.atlan.com")
    api_key: str = Field(..., description="Atlan API key")
