"""Frozen dataclasses representing GitHub wiki records."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class WikiPageRecord:
    """GitHub wiki page content."""

    repo_full_name: str  # e.g., "sony-telemetry/schema-registry"
    page_path: str       # relative path within wiki, e.g., "Client-PlayerLogin.md"
    page_name: str       # e.g., "Client PlayerLogin"
    content: str         # markdown content
    file_sha: Optional[str]
    wiki_section: Optional[str] = None    # nav section, inferred from title if absent
    git_updated_at: Optional[int] = None  # unix timestamp (ms) of most recent commit
    git_updated_by: Optional[str] = None  # author name of most recent commit
    git_created_at: Optional[int] = None  # unix timestamp (ms) of first commit


@dataclass(frozen=True)
class YamlFileRecord:
    """YAML configuration file from a repository."""

    repo_full_name: str
    file_path: str       # e.g., "schemas/consoleInfo.yaml"
    content: str         # raw YAML content
    file_sha: str        # git blob SHA
    file_size_bytes: int
