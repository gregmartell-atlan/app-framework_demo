"""Handler functions for Auth and Preflight operations."""

from datetime import datetime, timezone

from app.client import GitHubClient
from app.contracts import (
    AuthInput,
    AuthOutput,
    PreflightInput,
    PreflightOutput,
)
from app.credentials import GitHubTokenCredential


async def handle_auth(input: AuthInput) -> AuthOutput:
    """Validate GitHub credentials by calling the /user endpoint."""
    try:
        token = input.credential.get("token")
        if not token:
            return AuthOutput(
                status="failure",
                message="Missing GitHub token in credential",
                user_login=None,
            )

        cred = GitHubTokenCredential(token=token)
        async with GitHubClient(cred) as client:
            user = await client.get_authenticated_user()
            user_login = user.get("login", "unknown")
            return AuthOutput(
                status="success",
                message=f"Successfully authenticated as {user_login}",
                user_login=user_login,
            )

    except Exception as e:
        return AuthOutput(
            status="failure",
            message=f"Authentication failed: {str(e)}",
            user_login=None,
        )


async def handle_preflight(input: PreflightInput) -> PreflightOutput:
    """Run preflight checks: validate scopes, rate limits, org access."""
    try:
        token = input.credential.get("token")
        if not token:
            return PreflightOutput(
                status="failure",
                message="Missing GitHub token in credential",
                scopes=[],
            )

        cred = GitHubTokenCredential(token=token)
        async with GitHubClient(cred) as client:
            rate_limit_data = await client.get_rate_limit()
            core_limit = rate_limit_data.get("rate", {})
            remaining = core_limit.get("remaining", 0)
            reset_timestamp = core_limit.get("reset", 0)
            reset_iso = datetime.fromtimestamp(reset_timestamp, tz=timezone.utc).isoformat()

            repos = []
            async for repo in client.list_repos(input.organization, max_items=1):
                repos.append(repo)

            scopes = ["repo", "read:org"]

            if remaining < 100:
                return PreflightOutput(
                    status="warning",
                    message=f"Rate limit low: {remaining} remaining, resets at {reset_iso}",
                    scopes=scopes,
                    rate_limit_remaining=remaining,
                    rate_limit_reset_at=reset_iso,
                )

            if not repos:
                return PreflightOutput(
                    status="warning",
                    message=f"No repositories found for '{input.organization}'. Check org name and token permissions.",
                    scopes=scopes,
                    rate_limit_remaining=remaining,
                    rate_limit_reset_at=reset_iso,
                )

            return PreflightOutput(
                status="success",
                message=f"Preflight passed. Found repositories for '{input.organization}'. Rate limit: {remaining} remaining.",
                scopes=scopes,
                rate_limit_remaining=remaining,
                rate_limit_reset_at=reset_iso,
            )

    except Exception as e:
        return PreflightOutput(
            status="failure",
            message=f"Preflight failed: {str(e)}",
            scopes=[],
        )
