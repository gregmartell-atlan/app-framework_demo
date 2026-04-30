"""Unit tests for GitHub credential handling."""

import pytest

from app.credentials import GitHubTokenCredential


def test_credential_to_headers():
    """Test credential converts to correct HTTP headers."""
    cred = GitHubTokenCredential(token="ghp_test123abc")
    headers = cred.to_headers()

    assert headers["Authorization"] == "Bearer ghp_test123abc"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_credential_required_field():
    """Test that token is required."""
    with pytest.raises(Exception):  # Pydantic ValidationError
        GitHubTokenCredential()


def test_credential_serialization():
    """Test credential can be serialized to dict."""
    cred = GitHubTokenCredential(token="ghp_secret")
    data = cred.model_dump()

    assert data["token"] == "ghp_secret"
    assert isinstance(data, dict)


def test_credential_from_dict():
    """Test credential can be created from dict."""
    data = {"token": "ghp_from_dict"}
    cred = GitHubTokenCredential(**data)

    assert cred.token == "ghp_from_dict"
