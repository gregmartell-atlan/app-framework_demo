"""Wiki → Atlan Glossary sync module.

Shared business logic used by:
- Option A: GitHub Actions workflow (via scripts/push_to_atlan.py)
- Option B: standalone CLI (scripts/push_to_atlan.py)
- Option C: Atlan App Framework task

All three deployment options call sync_wiki_to_glossary() so behaviour is identical.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any, Optional

import git
from pyatlan.errors import NotFoundError

from app.api_types import WikiPageRecord
from app.contracts import GlossarySyncConfig, GlossarySyncResult
from app.glossary_mapper import (
    _infer_wiki_section,
    build_relationship_updates,
    map_glossary,
    map_glossary_category,
    map_glossary_subcategory,
    map_readme,
    map_wiki_page_as_term,
)

logger = logging.getLogger(__name__)


def _is_schema_page(page: WikiPageRecord) -> bool:
    return "## Template Information" in page.content


def _classify(page: WikiPageRecord) -> tuple[Optional[str], Optional[str]]:
    return _infer_wiki_section(page.page_name, page.page_path)


def _saved_qn(resp) -> Optional[str]:
    created = (resp.mutated_entities.CREATE or []) if resp.mutated_entities else []
    updated = (resp.mutated_entities.UPDATE or []) if resp.mutated_entities else []
    assets = created + updated
    return assets[0].qualified_name if assets else None


def _saved_guid(resp) -> Optional[str]:
    created = (resp.mutated_entities.CREATE or []) if resp.mutated_entities else []
    updated = (resp.mutated_entities.UPDATE or []) if resp.mutated_entities else []
    assets = created + updated
    return assets[0].guid if assets else None


def _saved_asset(resp):
    created = (resp.mutated_entities.CREATE or []) if resp.mutated_entities else []
    updated = (resp.mutated_entities.UPDATE or []) if resp.mutated_entities else []
    assets = created + updated
    return assets[0] if assets else None


async def _clone_wiki(
    repo_full_name: str, github_token: str, clone_root: Optional[Path] = None
) -> list[WikiPageRecord]:
    """Clone the GitHub wiki for repo_full_name and return WikiPageRecord list."""
    url = f"https://{github_token}@github.com/{repo_full_name}.wiki.git"

    def _do_clone(target: Path) -> list[WikiPageRecord]:
        repo = git.Repo.clone_from(url, target)
        result: list[WikiPageRecord] = []
        for f in sorted(target.glob("*.md")):
            try:
                commits = list(repo.iter_commits(paths=f.name))
            except Exception:
                commits = []
            last = commits[0] if commits else None
            first = commits[-1] if commits else None
            result.append(WikiPageRecord(
                repo_full_name=repo_full_name,
                page_path=f.name,
                page_name=f.stem.replace("-", " "),
                content=f.read_text(encoding="utf-8", errors="replace"),
                file_sha=None,
                git_updated_at=int(last.committed_date * 1000) if last else None,
                git_updated_by=last.author.name if last else None,
                git_created_at=int(first.committed_date * 1000) if first else None,
            ))
        return result

    if clone_root is not None:
        clone_root.mkdir(parents=True, exist_ok=True)
        return await asyncio.to_thread(_do_clone, clone_root)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "wiki"
            return await asyncio.to_thread(_do_clone, target)


async def sync_wiki_to_glossary(
    cfg: GlossarySyncConfig,
    atlan_client: Any,
) -> GlossarySyncResult:
    """Clone the wiki, classify pages, and write glossary/categories/terms to Atlan.

    When cfg.dry_run is True: no .save() calls are issued for glossary, categories,
    terms, readmes, or relationships. find_glossary_by_name (read-only) is still
    called to surface any existing QN.
    """
    result = GlossarySyncResult(dry_run=cfg.dry_run)

    try:
        pages = await _clone_wiki(cfg.repo_full_name, cfg.github_token)
    except Exception as e:
        result.errors.append(f"wiki clone failed: {e}")
        return result

    schema_pages = [p for p in pages if _is_schema_page(p)]
    result.pages_scanned = len(schema_pages)

    if cfg.phase1_filter:
        target_pages = [p for p in schema_pages if _classify(p)[0] in ("Client", "Shared Schemas")]
    else:
        target_pages = list(schema_pages)

    result.pages_filtered_out = len(schema_pages) - len(target_pages)

    # 1. Find-or-create glossary
    glossary_qn: Optional[str] = None
    glossary_guid: Optional[str] = None
    try:
        existing = atlan_client.asset.find_glossary_by_name(name=cfg.glossary_name)
        glossary_qn = existing.qualified_name
        glossary_guid = existing.guid
        logger.info(f"Reusing existing glossary '{cfg.glossary_name}' QN={glossary_qn}")
    except NotFoundError:
        if cfg.dry_run:
            logger.info(f"[dry-run] would create glossary '{cfg.glossary_name}'")
            glossary_qn = f"__dryrun_glossary__/{cfg.glossary_name}"
            glossary_guid = "__dryrun__"
        else:
            resp = atlan_client.asset.save(map_glossary(cfg.glossary_name))
            glossary_qn = _saved_qn(resp)
            glossary_guid = _saved_guid(resp) or ""
            logger.info(f"Created glossary QN={glossary_qn}")
    except Exception as e:
        result.errors.append(f"glossary resolve failed: {e}")
        return result

    result.glossary_qn = glossary_qn
    result.glossary_guid = glossary_guid

    # 2. Top-level categories
    needed_tracks: set[str] = set()
    for page in target_pages:
        track, _ = _classify(page)
        if track:
            needed_tracks.add(track)

    top_cats: dict[str, Any] = {}
    for track in sorted(needed_tracks):
        cat = map_glossary_category(track, glossary_qn)
        if cfg.dry_run:
            logger.info(f"[dry-run] would save top-level category '{track}'")
            top_cats[track] = cat
        else:
            resp = atlan_client.asset.save(cat)
            saved = _saved_asset(resp)
            top_cats[track] = saved if saved else cat
            result.categories_created += 1

    # 3. Sub-categories
    needed_subcats: set[tuple[str, str]] = set()
    for page in target_pages:
        track, page_type = _classify(page)
        if track and page_type:
            needed_subcats.add((track, page_type))

    sub_cats: dict[tuple[str, str], Any] = {}
    for track, page_type in sorted(needed_subcats):
        parent = top_cats.get(track)
        if parent is None:
            continue
        sub = map_glossary_subcategory(page_type, glossary_qn, parent_category=parent)
        if cfg.dry_run:
            logger.info(f"[dry-run] would save sub-category '{track} > {page_type}'")
            sub_cats[(track, page_type)] = sub
        else:
            resp = atlan_client.asset.save(sub)
            saved = _saved_asset(resp)
            sub_cats[(track, page_type)] = saved if saved else sub
            result.categories_created += 1

    # 4. Save terms + readmes
    slug_to_qn: dict[str, str] = {}
    slug_to_page: dict[str, WikiPageRecord] = {}

    for page in target_pages:
        track, page_type = _classify(page)
        if track and page_type:
            category = sub_cats.get((track, page_type)) or top_cats.get(track)
        elif track:
            category = top_cats.get(track)
        else:
            category = None

        term = map_wiki_page_as_term(page, glossary_qn, category=category)
        slug = page.page_path.removesuffix(".md")

        if cfg.dry_run:
            logger.info(f"[dry-run] would save term '{page.page_name}'")
            result.terms_created += 1
            slug_to_qn[slug] = f"__dryrun_term__/{slug}"
            slug_to_page[slug] = page
            continue

        resp = atlan_client.asset.save(term)
        created = (resp.mutated_entities.CREATE or []) if resp.mutated_entities else []
        updated = (resp.mutated_entities.UPDATE or []) if resp.mutated_entities else []
        if created:
            result.terms_created += 1
        elif updated:
            result.terms_updated += 1
        saved_qn = _saved_qn(resp)
        saved = _saved_asset(resp)
        if saved_qn and saved is not None:
            slug_to_qn[slug] = saved_qn
            slug_to_page[slug] = page
            readme = map_readme(saved, page.content, page.page_name)
            atlan_client.asset.save(readme)
            result.readmes_saved += 1

    # 5. Cross-references
    for slug, page in slug_to_page.items():
        update = build_relationship_updates(page, slug_to_qn[slug], glossary_guid or "", slug_to_qn)
        if update:
            if cfg.dry_run:
                logger.info(f"[dry-run] would link relationships for '{page.page_name}'")
            else:
                atlan_client.asset.save(update)
            result.relationships_linked += 1

    return result
