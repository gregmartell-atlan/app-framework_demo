"""Unit tests for app.glossary_sync.sync_wiki_to_glossary."""

from __future__ import annotations

import shutil
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.contracts import GlossarySyncConfig
from app.glossary_sync import sync_wiki_to_glossary
from pyatlan.errors import ErrorCode, NotFoundError


FIXTURE_WIKI = Path(__file__).parent.parent / "fixtures" / "wiki"


# ─── Fixtures ────────────────────────────────────────────────────────────────


class _FakeCommit:
    def __init__(self, ts: int = 1_700_000_000, author_name: str = "ci"):
        self.committed_date = ts
        self.author = types.SimpleNamespace(name=author_name)


class _FakeRepo:
    """Stand-in for git.Repo returned by clone_from."""

    def __init__(self, dest: Path):
        self._dest = dest

    def iter_commits(self, paths=None):
        # Deterministic single commit for every path
        return iter([_FakeCommit()])


def _fake_clone_from(_url: str, dest, *_args, **_kwargs):
    """Replacement for git.Repo.clone_from — copies fixture wiki into dest."""
    dest_p = Path(dest)
    if dest_p.exists():
        shutil.rmtree(dest_p)
    shutil.copytree(FIXTURE_WIKI, dest_p)
    return _FakeRepo(dest_p)


def _make_saved_asset(name: str, qn: str, guid: str):
    """Create a stand-in saved asset with the attributes glossary_mapper expects."""
    obj = types.SimpleNamespace()
    obj.qualified_name = qn
    obj.guid = guid
    obj.name = name
    return obj


class _SaveResponse:
    """Imitates pyatlan_v9 save() responses with mutated_entities."""

    def __init__(self, asset, action: str = "CREATE"):
        if action == "CREATE":
            self.mutated_entities = types.SimpleNamespace(CREATE=[asset], UPDATE=[])
        else:
            self.mutated_entities = types.SimpleNamespace(CREATE=[], UPDATE=[asset])


def _make_mock_client(glossary_exists: bool = False) -> MagicMock:
    """Build an AtlanClient mock with asset.save and asset.find_glossary_by_name."""
    client = MagicMock()

    counter = {"n": 0}

    def _save(asset):
        counter["n"] += 1
        # Carry forward the input asset's name/qn where possible
        name = getattr(asset, "name", None) or f"asset-{counter['n']}"
        qn = getattr(asset, "qualified_name", None) or f"qn-{counter['n']}"
        # AtlasGlossaryTerm.creator() uses sentinel values; coerce to strings.
        try:
            name_str = str(name) if name and str(name) != "UNSET" else f"asset-{counter['n']}"
        except Exception:
            name_str = f"asset-{counter['n']}"
        try:
            qn_str = str(qn)
        except Exception:
            qn_str = f"qn-{counter['n']}"
        saved = _make_saved_asset(name_str, qn_str, f"guid-{counter['n']}")
        return _SaveResponse(saved, action="CREATE")

    client.asset.save.side_effect = _save

    if glossary_exists:
        existing = types.SimpleNamespace(qualified_name="glossary-existing-qn", guid="g-1")
        client.asset.find_glossary_by_name.return_value = existing
    else:
        client.asset.find_glossary_by_name.side_effect = NotFoundError(
            ErrorCode.ASSET_NOT_FOUND_BY_NAME, "ghost_tsushima", "AtlasGlossary"
        )
    return client


@pytest.fixture
def cfg_default():
    return GlossarySyncConfig(
        repo_full_name="acme/wiki-source",
        github_token="ghp_fake",
        glossary_name="ghost_tsushima",
        phase1_filter=True,
        dry_run=False,
    )


# ─── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_dry_run_does_not_save(cfg_default):
    cfg = cfg_default.model_copy(update={"dry_run": True})
    client = _make_mock_client()
    with patch("app.glossary_sync.git.Repo.clone_from", side_effect=_fake_clone_from):
        result = await sync_wiki_to_glossary(cfg, client)

    assert result.dry_run is True
    # Nothing should be persisted in dry-run mode.
    client.asset.save.assert_not_called()
    # Phase 1 filter still classifies pages — counts should be > 0
    assert result.pages_scanned >= 3
    assert result.terms_created >= 2  # at least the two Client + one Shared term


@pytest.mark.asyncio
async def test_sync_real_run_saves_glossary_categories_terms(cfg_default):
    client = _make_mock_client()
    with patch("app.glossary_sync.git.Repo.clone_from", side_effect=_fake_clone_from):
        result = await sync_wiki_to_glossary(cfg_default, client)

    # Glossary + at least one category + at least one term must have been saved
    assert client.asset.save.called
    assert result.glossary_qn is not None
    assert result.categories_created >= 1
    assert result.terms_created >= 1


@pytest.mark.asyncio
async def test_sync_phase1_filter_drops_native_tooling(cfg_default):
    client = _make_mock_client()
    with patch("app.glossary_sync.git.Repo.clone_from", side_effect=_fake_clone_from):
        result = await sync_wiki_to_glossary(cfg_default, client)

    # Fixture has 4 schema pages: 2 Client, 1 Shared, 1 Native — phase1 drops Native.
    assert result.pages_filtered_out >= 1
    # No term named like the Native page should appear in save calls
    saved_term_names = []
    for call in client.asset.save.call_args_list:
        asset = call.args[0] if call.args else None
        name = getattr(asset, "name", None)
        if name:
            saved_term_names.append(name)
    assert not any("Native" in n for n in saved_term_names if "NativeBoot" in n)


@pytest.mark.asyncio
async def test_sync_result_counts_are_accurate(cfg_default):
    client = _make_mock_client()
    with patch("app.glossary_sync.git.Repo.clone_from", side_effect=_fake_clone_from):
        result = await sync_wiki_to_glossary(cfg_default, client)

    # 3 Phase 1 pages (2 Client + 1 Shared Schema template) → 3 terms
    assert result.pages_scanned == 4  # 4 schema pages in fixture
    assert result.pages_filtered_out == 1  # the Native page
    assert result.terms_created == 3
    assert result.readmes_saved == 3
    # categories_created should be > 0 (at least 1 top-level + 1 sub for Client)
    assert result.categories_created >= 2
