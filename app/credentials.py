"""GitHub credential handling for App Framework v3.

Implements GitHubTokenCredential and registers it with the SDK's credential system.
Also implements AtlanCredential (base_url + api_key) for the glossary-sync task.
"""

from typing import Any

from pydantic import BaseModel, Field
from application_sdk.credentials import register_credential_type
from application_sdk.credentials.errors import CredentialValidationError


class GitHubTokenCredential(BaseModel):
    """GitHub Personal Access Token credential.

    Converts to HTTP headers for GitHub REST API v3.
    """

    token: str = Field(..., description="GitHub Personal Access Token")

    @property
    def credential_type(self) -> str:
        return "github_token"

    async def validate(self) -> None:
        if not self.token:
            raise CredentialValidationError(
                "GitHubTokenCredential.token must not be empty",
                credential_name="github_token",
            )

    def to_headers(self) -> dict[str, str]:
        """Convert credential to HTTP headers for GitHub API requests.

        Returns headers for GitHub REST API v3 (2022-11-28 version).
        """
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }


def _parse_github_token(data: dict[str, Any]) -> GitHubTokenCredential:
    return GitHubTokenCredential(token=data["token"])


# Register the credential type with the SDK
register_credential_type("github_token", GitHubTokenCredential, _parse_github_token)


class AtlanCredential(BaseModel):
    """Atlan tenant credential — base URL + API key.

    Used by the standalone script (Option B) and workflow (Option A) paths.
    Option C uses the framework's built-in atlan_api_token credential type instead.
    """

    base_url: str = Field(..., description="Atlan tenant base URL, e.g. https://dsm.atlan.com")
    api_key: str = Field(..., description="Atlan API key")

    async def validate(self) -> None:
        if not self.base_url:
            raise CredentialValidationError(
                "AtlanCredential.base_url must not be empty",
                credential_name="atlan_credential",
            )
        if not self.api_key:
            raise CredentialValidationError(
                "AtlanCredential.api_key must not be empty",
                credential_name="atlan_credential",
            )
