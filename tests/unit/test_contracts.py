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
    GitHubExtractionInput,
    GitHubExtractionOutput,
    FetchSbomInput,
    FetchSbomOutput,
    SbomProgress,
    FileReference,
    MaxItems,
)


def test_auth_input_valid():
    """Test AuthInput with valid data."""
    data = {
        "credential": {"token": "ghp_test123"},
        "extraction_method": "direct",
    }
    input_obj = AuthInput(**data)
    assert input_obj.credential["token"] == "ghp_test123"
    assert input_obj.extraction_method == "direct"


def test_auth_output_success():
    """Test AuthOutput for successful authentication."""
    output = AuthOutput(
        status="success",
        message="Authenticated as octocat",
        user_login="octocat",
    )
    assert output.status == "success"
    assert output.user_login == "octocat"


def test_preflight_output_with_rate_limit():
    """Test PreflightOutput with rate limit info."""
    output = PreflightOutput(
        status="success",
        message="Preflight passed",
        scopes=["repo", "read:org"],
        rate_limit_remaining=4500,
        rate_limit_reset_at="2026-04-30T15:00:00Z",
    )
    assert output.rate_limit_remaining == 4500
    assert len(output.scopes) == 2


def test_github_extraction_input_defaults():
    """Test GitHubExtractionInput with default values."""
    input_obj = GitHubExtractionInput(
        organization="atlanhq",
        credential={"token": "ghp_test"},
        connection_qualified_name="default/github/123",
    )
    assert input_obj.extract_wiki is False
    assert input_obj.extract_yaml is False
    assert input_obj.extract_sbom is False
    assert input_obj.sbom_poll_interval_seconds == 15
    assert input_obj.max_items.max_items == 1000


def test_github_extraction_output_with_files():
    """Test GitHubExtractionOutput with file references."""
    output = GitHubExtractionOutput(
        repos_file=FileReference(path="/tmp/repos.jsonl", retention="RETAINED", size_bytes=1024),
        wiki_file=None,
        yaml_file=None,
        sbom_file=None,
        extraction_summary="Extracted 10 repos",
        repos_count=10,
    )
    assert output.repos_file.path == "/tmp/repos.jsonl"
    assert output.repos_count == 10
    assert output.wiki_pages_count == 0


def test_sbom_progress_heartbeat():
    """Test SbomProgress typed heartbeat details."""
    progress = SbomProgress(
        repo_full_name="atlanhq/atlan-python",
        report_id="report_123",
        started_at_iso="2026-04-30T12:00:00Z",
        poll_attempts=3,
    )
    assert progress.repo_full_name == "atlanhq/atlan-python"
    assert progress.poll_attempts == 3


def test_fetch_sbom_output():
    """Test FetchSbomOutput with success and failure lists."""
    output = FetchSbomOutput(
        sbom_files=[
            FileReference(path="/tmp/repo1_sbom.json", retention="RETAINED", size_bytes=2048),
            FileReference(path="/tmp/repo2_sbom.json", retention="RETAINED", size_bytes=3072),
        ],
        successful_repos=["atlanhq/repo1", "atlanhq/repo2"],
        failed_repos=["atlanhq/repo3"],
        summary="2 succeeded, 1 failed",
    )
    assert len(output.sbom_files) == 2
    assert len(output.successful_repos) == 2
    assert len(output.failed_repos) == 1


def test_file_reference_required_fields():
    """Test FileReference requires path."""
    with pytest.raises(ValidationError):
        FileReference(retention="RETAINED")  # Missing path


def test_max_items_default():
    """Test MaxItems default value."""
    max_items = MaxItems()
    assert max_items.max_items == 1000
