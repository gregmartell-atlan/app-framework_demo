"""GitHub credential handling for App Framework v3.

Implements GitHubTokenCredential and registers it with the SDK's credential system.
"""

from pydantic import BaseModel, Field
from application_sdk.credentials import CredentialRef, register_credential_type


class GitHubTokenCredential(BaseModel):
    """GitHub Personal Access Token credential.

    Converts to HTTP headers for GitHub REST API v3.
    """

    token: str = Field(..., description="GitHub Personal Access Token")

    def to_headers(self) -> dict[str, str]:
        """Convert credential to HTTP headers for GitHub API requests.

        Returns headers for GitHub REST API v3 (2022-11-28 version).
        """
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }


# Register the credential type with the SDK
register_credential_type("github_token", GitHubTokenCredential)
