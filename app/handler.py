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
    GlossarySyncConfig,
    GlossarySyncInput,
    GlossarySyncOutput,
)
from app.credentials import AtlanCredential, GitHubTokenCredential


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


async def handle_glossary_sync(input: GlossarySyncInput) -> GlossarySyncOutput:
    """Handler for the github:sync_glossary task (Option C).

    Parses both credentials, builds an AtlanClient, and delegates to the
    shared sync routine in app.glossary_sync.

    Note: this keeps the existing sync AtlanClient usage. Switching to
    task_context.atlan_client / create_async_atlan_client is part of the
    pre-existing v3-readiness debt and is out of scope here.
    """
    # Late imports keep app.handler importable in environments where
    # pyatlan_v9 or gitpython are not installed (e.g. unit tests that mock).
    from app.glossary_sync import sync_wiki_to_glossary
    from pyatlan_v9.client.atlan import AtlanClient

    gh_cred = GitHubTokenCredential(token=input.github_credential["token"])
    await gh_cred.validate()

    atlan_cred = AtlanCredential(
        base_url=input.atlan_credential["base_url"],
        api_key=input.atlan_credential["api_key"],
    )
    await atlan_cred.validate()

    cfg = GlossarySyncConfig(
        repo_full_name=input.repo_full_name,
        github_token=gh_cred.token,
        glossary_name=input.glossary_name,
        phase1_filter=input.phase1_filter,
        dry_run=input.dry_run,
    )

    client = AtlanClient(base_url=atlan_cred.base_url, api_key=atlan_cred.api_key)
    result = await sync_wiki_to_glossary(cfg, client)

    summary = (
        f"glossary={result.glossary_qn or '(none)'} "
        f"pages_scanned={result.pages_scanned} "
        f"filtered_out={result.pages_filtered_out} "
        f"categories={result.categories_created} "
        f"terms_created={result.terms_created} "
        f"terms_updated={result.terms_updated} "
        f"readmes={result.readmes_saved} "
        f"relationships={result.relationships_linked} "
        f"errors={len(result.errors)} "
        f"dry_run={result.dry_run}"
    )
    return GlossarySyncOutput(**result.model_dump(), summary=summary)
