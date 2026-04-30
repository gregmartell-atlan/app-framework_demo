"""Multi-repo scenario tests.

Validates connector behaviour across three repo archetypes:
  1. Metadata-wiki repo  (data-catalog: no language, wiki=true, public)
  2. Active private repo (context-studio: Python, private, 26 open issues, wiki=true)
  3. Archived legacy repo (legacy-reports: SQL, archived, no wiki, no issues)

Also validates new content mode fields on contracts.
"""

import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from app.api_types import RepoRecord
from app.asset_mapper import map_repository
from app.client import GitHubClient
from app.contracts import GitHubExtractionInput, TransformInput
from app.credentials import GitHubTokenCredential

FIXTURES = Path(__file__).parent.parent / "fixtures" / "github_api"
CONN_QN = "default/app/1234567890"
TOKEN = "ghp_test_token_unit"


def make_client():
    return GitHubClient(GitHubTokenCredential(token=TOKEN), concurrency_limit=4)


def _load_multiscenario():
    return json.loads((FIXTURES / "repos_multiscenario.json").read_text())


# ---------------------------------------------------------------------------
# Client: list_repos returns all three scenario repos correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_list_repos_multiscenario_all_returned():
    repos_data = _load_multiscenario()

    call_count = 0

    def paginate(request):
        nonlocal call_count
        if request.url.params.get("per_page") == "1":
            return Response(200, json=[repos_data[0]])
        call_count += 1
        return Response(200, json=repos_data if call_count == 1 else [])

    respx.get("https://api.github.com/orgs/sony-data/repos").mock(side_effect=paginate)

    async with make_client() as client:
        repos = [r async for r in client.list_repos("sony-data")]

    assert len(repos) == 3
    names = {r.name for r in repos}
    assert names == {"data-catalog", "context-studio", "legacy-reports"}


@pytest.mark.asyncio
@respx.mock
async def test_list_repos_metadata_wiki_repo():
    """data-catalog: no language, wiki=true, topics set."""
    repos_data = _load_multiscenario()

    call_count = 0
    def paginate(request):
        nonlocal call_count
        if request.url.params.get("per_page") == "1":
            return Response(200, json=[repos_data[0]])
        call_count += 1
        return Response(200, json=repos_data if call_count == 1 else [])

    respx.get("https://api.github.com/orgs/sony-data/repos").mock(side_effect=paginate)

    async with make_client() as client:
        repos = [r async for r in client.list_repos("sony-data")]

    catalog = next(r for r in repos if r.name == "data-catalog")
    assert catalog.language is None
    assert catalog.has_wiki is True
    assert catalog.is_private is False
    assert catalog.topics == ["data-catalog", "metadata", "governance"]
    assert catalog.open_issues_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_list_repos_active_private_repo():
    """context-studio: private, 26 issues, Python, no topics."""
    repos_data = _load_multiscenario()

    call_count = 0
    def paginate(request):
        nonlocal call_count
        if request.url.params.get("per_page") == "1":
            return Response(200, json=[repos_data[0]])
        call_count += 1
        return Response(200, json=repos_data if call_count == 1 else [])

    respx.get("https://api.github.com/orgs/sony-data/repos").mock(side_effect=paginate)

    async with make_client() as client:
        repos = [r async for r in client.list_repos("sony-data")]

    studio = next(r for r in repos if r.name == "context-studio")
    assert studio.is_private is True
    assert studio.language == "Python"
    assert studio.open_issues_count == 26
    assert studio.license_name == "MIT License"
    assert studio.topics == []


@pytest.mark.asyncio
@respx.mock
async def test_list_repos_archived_repo():
    """legacy-reports: archived, no wiki, SQL, no issues."""
    repos_data = _load_multiscenario()

    call_count = 0
    def paginate(request):
        nonlocal call_count
        if request.url.params.get("per_page") == "1":
            return Response(200, json=[repos_data[0]])
        call_count += 1
        return Response(200, json=repos_data if call_count == 1 else [])

    respx.get("https://api.github.com/orgs/sony-data/repos").mock(side_effect=paginate)

    async with make_client() as client:
        repos = [r async for r in client.list_repos("sony-data")]

    legacy = next(r for r in repos if r.name == "legacy-reports")
    assert legacy.is_archived is True
    assert legacy.has_wiki is False
    assert legacy.language == "SQL"
    assert legacy.description is None


# ---------------------------------------------------------------------------
# Mapper: all three archetypes produce correct Application assets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_map_all_multiscenario_repos():
    """Each repo maps to an Application with correct user_description flags."""
    repos_data = _load_multiscenario()

    call_count = 0
    def paginate(request):
        nonlocal call_count
        if request.url.params.get("per_page") == "1":
            return Response(200, json=[repos_data[0]])
        call_count += 1
        return Response(200, json=repos_data if call_count == 1 else [])

    respx.get("https://api.github.com/orgs/sony-data/repos").mock(side_effect=paginate)

    async with make_client() as client:
        repos = [r async for r in client.list_repos("sony-data")]

    assets = [map_repository(r, CONN_QN) for r in repos]
    by_name = {a.name: a for a in assets}

    # data-catalog has topics → asset_tags
    assert by_name["data-catalog"].asset_tags == ["data-catalog", "metadata", "governance"]

    # context-studio is private → user_description flags it
    assert "visibility=private" in by_name["context-studio"].user_description

    # legacy-reports is archived → user_description flags it
    assert "archived=true" in by_name["legacy-reports"].user_description

    # SQL language preserved
    assert "language=SQL" in by_name["legacy-reports"].user_description


# ---------------------------------------------------------------------------
# Contracts: content mode fields default + validation
# ---------------------------------------------------------------------------

def test_extraction_input_content_mode_defaults():
    inp = GitHubExtractionInput(
        organization="sony-data",
        credential={"token": "ghp_test"},
        connection_qualified_name=CONN_QN,
    )
    assert inp.wiki_content_mode == "index"
    assert inp.yaml_content_mode == "index"


def test_extraction_input_accepts_all_content_modes():
    for mode in ("index", "full", "parse"):
        inp = GitHubExtractionInput(
            organization="sony-data",
            credential={"token": "ghp_test"},
            connection_qualified_name=CONN_QN,
            wiki_content_mode=mode,
            yaml_content_mode=mode,
        )
        assert inp.wiki_content_mode == mode
        assert inp.yaml_content_mode == mode


def test_extraction_input_rejects_invalid_content_mode():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        GitHubExtractionInput(
            organization="sony-data",
            credential={"token": "ghp_test"},
            connection_qualified_name=CONN_QN,
            wiki_content_mode="blob",  # not a valid literal
        )


def test_transform_input_content_mode_defaults():
    inp = TransformInput(connection_qualified_name=CONN_QN)
    assert inp.wiki_content_mode == "index"
    assert inp.yaml_content_mode == "index"


def test_transform_input_parse_mode_round_trips():
    inp = TransformInput(
        connection_qualified_name=CONN_QN,
        wiki_content_mode="parse",
        yaml_content_mode="parse",
    )
    assert inp.wiki_content_mode == "parse"
    assert inp.yaml_content_mode == "parse"
