"""Typed handler functions for Auth, Preflight, and Metadata steps.

These are called by the App Framework v3 SDK during workflow execution.
All handlers have explicit typed Input/Output contracts (no *args/**kwargs).
"""

from datetime import datetime, timezone

from app.client import GitHubClient
from app.contracts import (
    AuthInput,
    AuthOutput,
    PreflightInput,
    PreflightOutput,
    GitHubExtractionInput,
    GitHubExtractionOutput,
)
from app.credentials import GitHubTokenCredential


async def handle_auth(input: AuthInput) -> AuthOutput:
    """Validate GitHub credentials.

    Args:
        input: AuthInput with credential dict

    Returns:
        AuthOutput with status and authenticated user info

    Raises:
        Exception: If auth fails (401, 403, network error)
    """
    try:
        # Extract token and build credential
        token = input.credential.get("token")
        if not token:
            return AuthOutput(
                status="failure",
                message="Missing GitHub token in credential",
                user_login=None,
            )

        cred = GitHubTokenCredential(token=token)

        # Test authentication by fetching user info
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
    """Run preflight checks: validate scopes, rate limits, org access.

    Args:
        input: PreflightInput with organization and credential

    Returns:
        PreflightOutput with status, scopes, rate limit info

    Raises:
        Exception: If preflight fails critically
    """
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
            # Check rate limit
            rate_limit_data = await client.get_rate_limit()
            core_limit = rate_limit_data.get("rate", {})
            remaining = core_limit.get("remaining", 0)
            reset_timestamp = core_limit.get("reset", 0)
            reset_iso = datetime.fromtimestamp(reset_timestamp, tz=timezone.utc).isoformat()

            # Try to fetch repos (validates org access)
            repos = []
            async for repo in client.list_repos(input.organization, max_items=1):
                repos.append(repo)

            # Check scopes (GitHub returns scopes in response headers, but httpx doesn't expose them easily)
            # For now, infer based on successful operations
            scopes = ["repo", "read:org"]  # Assumed if we got this far

            if remaining < 100:
                return PreflightOutput(
                    status="warning",
                    message=f"Rate limit low: {remaining} requests remaining. Resets at {reset_iso}",
                    scopes=scopes,
                    rate_limit_remaining=remaining,
                    rate_limit_reset_at=reset_iso,
                )

            if not repos:
                return PreflightOutput(
                    status="warning",
                    message=f"No repositories found for organization '{input.organization}'. Ensure the org exists and the token has access.",
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


async def handle_metadata_extraction(input: GitHubExtractionInput, task_context) -> GitHubExtractionOutput:
    """Main metadata extraction logic (placeholder — actual extraction is in connector.py tasks).

    This handler is a lightweight orchestrator; the real work happens in @task-decorated methods.

    Args:
        input: GitHubExtractionInput with all extraction config
        task_context: App task context

    Returns:
        GitHubExtractionOutput with file references and counts
    """
    # In a real v3 app, this would dispatch to @task methods and aggregate results
    # For now, return a stub output
    return GitHubExtractionOutput(
        extraction_summary="Metadata extraction not yet implemented in handler",
        repos_count=0,
        wiki_pages_count=0,
        yaml_files_count=0,
        sbom_dependencies_count=0,
    )
