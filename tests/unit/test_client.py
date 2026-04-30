"""Unit tests for GitHubClient using respx to mock httpx calls."""

import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from app.client import GitHubClient
from app.credentials import GitHubTokenCredential

FIXTURES = Path(__file__).parent.parent / "fixtures" / "github_api"
CONN_QN = "default/github/1234567890"
TOKEN = "ghp_test_token_unit"


def make_client() -> GitHubClient:
    return GitHubClient(GitHubTokenCredential(token=TOKEN), concurrency_limit=4)


# ---------------------------------------------------------------------------
# list_repos — org account path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_list_repos_org_account():
    """Org endpoint returns 200 → repos fetched from /orgs/ URL."""
    repos_data = json.loads((FIXTURES / "orgs_repos.json").read_text())
    page_call_count = 0

    def paginate(request):
        nonlocal page_call_count
        # _resolve_repos_url probes with per_page=1; real pages use per_page=100
        if request.url.params.get("per_page") == "1":
            return Response(200, json=[repos_data[0]])  # probe succeeds
        page_call_count += 1
        return Response(200, json=repos_data if page_call_count == 1 else [])

    respx.get("https://api.github.com/orgs/my-org/repos").mock(side_effect=paginate)

    async with make_client() as client:
        repos = [r async for r in client.list_repos("my-org")]

    assert len(repos) == 3
    assert repos[0].name == "app-framework_demo"
    assert repos[0].owner == "gregmartell-atlan"
    assert repos[0].has_wiki is True
    assert repos[1].license_name == "MIT License"


@pytest.mark.asyncio
@respx.mock
async def test_list_repos_user_account_fallback():
    """Org endpoint returns 404 → falls back to /users/ URL."""
    repos_data = json.loads((FIXTURES / "orgs_repos.json").read_text())

    # Org probe returns 404 for any request to the org URL
    respx.get("https://api.github.com/orgs/greg-user/repos").mock(
        return_value=Response(404, json={"message": "Not Found"})
    )

    user_call_count = 0

    def paginate_user(request):
        nonlocal user_call_count
        user_call_count += 1
        return Response(200, json=repos_data if user_call_count == 1 else [])

    respx.get("https://api.github.com/users/greg-user/repos").mock(side_effect=paginate_user)

    async with make_client() as client:
        repos = [r async for r in client.list_repos("greg-user")]

    assert len(repos) == 3
    assert repos[0].full_name == "gregmartell-atlan/app-framework_demo"


@pytest.mark.asyncio
@respx.mock
async def test_list_repos_respects_max_items():
    """max_items cap is respected even when API returns more."""
    repos_data = json.loads((FIXTURES / "orgs_repos.json").read_text())

    respx.get("https://api.github.com/orgs/my-org/repos").mock(
        return_value=Response(200, json=repos_data)
    )

    async with make_client() as client:
        repos = [r async for r in client.list_repos("my-org", max_items=1)]

    assert len(repos) == 1


# ---------------------------------------------------------------------------
# list_yaml_files — tree API path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_list_yaml_files_uses_tree_api():
    """YAML discovery uses git tree endpoint, not code search."""
    tree_data = json.loads((FIXTURES / "tree_yaml.json").read_text())

    respx.get("https://api.github.com/repos/org/repo/git/trees/HEAD").mock(
        return_value=Response(200, json=tree_data)
    )
    # Mock content fetch for each YAML/YML blob
    respx.get("https://api.github.com/repos/org/repo/contents/components/pubsub.yaml").mock(
        return_value=Response(200, text="name: pubsub\nversion: v1\n")
    )
    respx.get("https://api.github.com/repos/org/repo/contents/components/statestore.yaml").mock(
        return_value=Response(200, text="name: statestore\n")
    )
    respx.get("https://api.github.com/repos/org/repo/contents/.github/workflows/ci.yml").mock(
        return_value=Response(200, text="name: CI\non: push\n")
    )

    async with make_client() as client:
        yamls = [y async for y in client.list_yaml_files("org/repo")]

    assert len(yamls) == 3
    paths = {y.file_path for y in yamls}
    assert "components/pubsub.yaml" in paths
    assert "components/statestore.yaml" in paths
    assert ".github/workflows/ci.yml" in paths

    pubsub = next(y for y in yamls if y.file_path == "components/pubsub.yaml")
    assert pubsub.content == "name: pubsub\nversion: v1\n"
    assert pubsub.file_size_bytes == len(pubsub.content.encode())
    assert pubsub.file_sha == "bbb1"


@pytest.mark.asyncio
@respx.mock
async def test_list_yaml_files_skips_non_yaml():
    """Tree entries that are not .yml/.yaml or are tree-type are skipped."""
    tree_data = json.loads((FIXTURES / "tree_yaml.json").read_text())

    respx.get("https://api.github.com/repos/org/repo/git/trees/HEAD").mock(
        return_value=Response(200, json=tree_data)
    )
    for path in ["components/pubsub.yaml", "components/statestore.yaml", ".github/workflows/ci.yml"]:
        respx.get(f"https://api.github.com/repos/org/repo/contents/{path}").mock(
            return_value=Response(200, text="content: test\n")
        )

    async with make_client() as client:
        yamls = [y async for y in client.list_yaml_files("org/repo")]

    file_paths = {y.file_path for y in yamls}
    assert "README.md" not in file_paths
    assert "src/main.py" not in file_paths
    assert "nested/dir" not in file_paths


@pytest.mark.asyncio
@respx.mock
async def test_list_yaml_files_empty_repo():
    """409 Conflict (empty repo) is handled gracefully — yields nothing."""
    respx.get("https://api.github.com/repos/org/empty-repo/git/trees/HEAD").mock(
        return_value=Response(409, json={"message": "Git Repository is empty."})
    )

    async with make_client() as client:
        yamls = [y async for y in client.list_yaml_files("org/empty-repo")]

    assert yamls == []


@pytest.mark.asyncio
@respx.mock
async def test_list_yaml_files_handles_404_content():
    """Files deleted between tree fetch and content fetch are skipped silently."""
    tree_data = {
        "sha": "abc",
        "tree": [{"path": "gone.yml", "type": "blob", "sha": "x1", "size": 100}],
        "truncated": False,
    }
    respx.get("https://api.github.com/repos/org/repo/git/trees/HEAD").mock(
        return_value=Response(200, json=tree_data)
    )
    respx.get("https://api.github.com/repos/org/repo/contents/gone.yml").mock(
        return_value=Response(404, json={"message": "Not Found"})
    )

    async with make_client() as client:
        yamls = [y async for y in client.list_yaml_files("org/repo")]

    assert yamls == []


# ---------------------------------------------------------------------------
# get_authenticated_user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_get_authenticated_user():
    user_data = json.loads((FIXTURES / "user.json").read_text())
    respx.get("https://api.github.com/user").mock(
        return_value=Response(200, json=user_data)
    )

    async with make_client() as client:
        user = await client.get_authenticated_user()

    assert user["login"] == "gregmartell-atlan"
    assert user["type"] == "User"
