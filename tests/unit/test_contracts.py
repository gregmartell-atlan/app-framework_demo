"""Unit tests for Pydantic contract models.

Validates that all Input/Output models serialize/deserialize correctly.
"""

import pytest
from pydantic import ValidationError

from app.contracts import (
    AuthInput,
    AuthOutput,
    PreflightInput,
    PreflightOutput,
    GitHubMetadataInput,
    GitHubMetadataOutput,
    FetchReposInput,
    FetchReposOutput,
    FetchSbomInput,
    FetchSbomOutput,
    SbomProgress,
    TransformInput,
    TransformOutput,
    FileReference,
    MaxItems,
)


# ---------------------------------------------------------------------------
# Handler contracts (plain BaseModel — HTTP boundary)
# ---------------------------------------------------------------------------

def test_auth_input_valid():
    data = {"credential": {"token": "ghp_test123"}, "extraction_method": "direct"}
    obj = AuthInput(**data)
    assert obj.credential["token"] == "ghp_test123"
    assert obj.extraction_method == "direct"


def test_auth_output_success():
    out = AuthOutput(status="success", message="Authenticated as octocat", user_login="octocat")
    assert out.status == "success"
    assert out.user_login == "octocat"


def test_preflight_output_with_rate_limit():
    out = PreflightOutput(
        status="success",
        message="Preflight passed",
        scopes=["repo", "read:org"],
        rate_limit_remaining=4500,
        rate_limit_reset_at="2026-04-30T15:00:00Z",
    )
    assert out.rate_limit_remaining == 4500
    assert len(out.scopes) == 2


# ---------------------------------------------------------------------------
# Workflow-level contracts (SDK Input/Output)
# ---------------------------------------------------------------------------

def test_github_metadata_input_defaults():
    obj = GitHubMetadataInput(organization="atlanhq", github_token="ghp_x")
    assert obj.extract_wiki is False
    assert obj.extract_yaml is False
    assert obj.extract_sbom is False
    assert obj.max_items == 1000
    assert obj.repositories == []


def test_github_metadata_input_full():
    obj = GitHubMetadataInput(
        github_token="ghp_test",
        organization="atlanhq",
        repositories=["repo1", "repo2"],
        extract_wiki=True,
        extract_yaml=True,
        extract_sbom=False,
        max_items=500,
    )
    assert obj.organization == "atlanhq"
    assert len(obj.repositories) == 2
    assert obj.extract_wiki is True


def test_github_metadata_output_defaults():
    out = GitHubMetadataOutput()
    assert out.repos_count == 0
    assert out.status == "succeeded"


# ---------------------------------------------------------------------------
# Task-level contracts
# ---------------------------------------------------------------------------

def test_fetch_repos_input_defaults():
    obj = FetchReposInput(organization="atlanhq", github_token="ghp_test")
    assert obj.extract_wiki is False
    assert obj.max_items == 1000
    assert obj.repositories == []


def test_fetch_repos_output():
    out = FetchReposOutput(
        repos_count=10,
        repos_file_path="/tmp/repos.jsonl",
        extraction_summary="Extracted 10 repos",
    )
    assert out.repos_count == 10
    assert out.repos_file_path == "/tmp/repos.jsonl"
    assert out.wiki_pages_count == 0


def test_sbom_progress_heartbeat():
    progress = SbomProgress(
        repo_full_name="atlanhq/atlan-python",
        report_id="report_123",
        started_at_iso="2026-04-30T12:00:00Z",
        poll_attempts=3,
    )
    assert progress.repo_full_name == "atlanhq/atlan-python"
    assert progress.poll_attempts == 3


def test_fetch_sbom_output():
    out = FetchSbomOutput(
        sbom_file_paths=["/tmp/repo1_sbom.json", "/tmp/repo2_sbom.json"],
        successful_repos=["atlanhq/repo1", "atlanhq/repo2"],
        failed_repos=["atlanhq/repo3"],
        summary="2 succeeded, 1 failed",
    )
    assert len(out.sbom_file_paths) == 2
    assert len(out.failed_repos) == 1


def test_transform_output_defaults():
    out = TransformOutput()
    assert out.assets_created == 0
    assert out.repos_count == 0


# ---------------------------------------------------------------------------
# Backward-compat aliases
# ---------------------------------------------------------------------------

def test_file_reference_required_fields():
    with pytest.raises(ValidationError):
        FileReference(retention="RETAINED")  # Missing path


def test_max_items_default():
    obj = MaxItems()
    assert obj.max_items == 1000
