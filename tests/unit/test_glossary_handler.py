"""Unit tests for app.handler.handle_glossary_sync (Option C handler)."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from app.contracts import (
    GlossarySyncConfig,
    GlossarySyncInput,
    GlossarySyncOutput,
    GlossarySyncResult,
)
from app.handler import handle_glossary_sync


async def _fake_sync_success(cfg: GlossarySyncConfig, _client) -> GlossarySyncResult:
    return GlossarySyncResult(
        glossary_qn="g-qn",
        glossary_guid="g-guid",
        pages_scanned=4,
        pages_filtered_out=1,
        categories_created=2,
        terms_created=3,
        terms_updated=0,
        readmes_saved=3,
        relationships_linked=1,
        errors=[],
        dry_run=cfg.dry_run,
    )


@pytest.fixture
def base_input():
    return GlossarySyncInput(
        repo_full_name="acme/wiki-source",
        github_credential={"token": "ghp_fake"},
        atlan_credential={"base_url": "https://dsm.atlan.com", "api_key": "xxx"},
        glossary_name="ghost_tsushima",
        phase1_filter=True,
        dry_run=False,
    )


@pytest.mark.asyncio
async def test_handle_glossary_sync_returns_typed_output(base_input):
    with patch("app.glossary_sync.sync_wiki_to_glossary", side_effect=_fake_sync_success), \
         patch("pyatlan_v9.client.atlan.AtlanClient", return_value=MagicMock()):
        result = await handle_glossary_sync(base_input)

    assert isinstance(result, GlossarySyncOutput)
    assert result.glossary_qn == "g-qn"
    assert result.terms_created == 3
    assert "terms_created=3" in result.summary
    assert "dry_run=False" in result.summary


@pytest.mark.asyncio
async def test_handle_glossary_sync_dry_run_flag_propagates(base_input):
    dry_input = base_input.model_copy(update={"dry_run": True})

    captured = {}

    async def _capture(cfg: GlossarySyncConfig, _client):
        captured["dry_run"] = cfg.dry_run
        return await _fake_sync_success(cfg, _client)

    with patch("app.glossary_sync.sync_wiki_to_glossary", side_effect=_capture), \
         patch("pyatlan_v9.client.atlan.AtlanClient", return_value=MagicMock()):
        result = await handle_glossary_sync(dry_input)

    assert captured["dry_run"] is True
    assert result.dry_run is True
    assert "dry_run=True" in result.summary
