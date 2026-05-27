"""Push wiki glossary terms to dsm.atlan.com."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import git

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.api_types import WikiPageRecord
from app.glossary_mapper import (
    _infer_wiki_section,
    build_see_also_update,
    map_glossary,
    map_glossary_category,
    map_readme,
    map_wiki_page_as_term,
)
from pyatlan_v9.client.atlan import AtlanClient

ATLAN_BASE_URL = os.environ.get("ATLAN_BASE_URL", "https://dsm.atlan.com")
ATLAN_API_KEY  = os.environ["ATLAN_API_KEY"]
GITHUB_TOKEN   = os.environ["GITHUB_TOKEN"]
REPO           = os.environ.get("GITHUB_REPO", "gregmartell-atlan/app-framework_demo")
GLOSSARY_NAME  = os.environ.get("GLOSSARY_NAME", REPO.split("/")[0])


def is_schema_page(page: WikiPageRecord) -> bool:
    return "## Template Information" in page.content


async def clone_wiki() -> list[WikiPageRecord]:
    url = f"https://{GITHUB_TOKEN}@github.com/{REPO}.wiki.git"
    pages = []
    with tempfile.TemporaryDirectory() as tmp:
        clone_path = Path(tmp) / "wiki"
        repo = await asyncio.to_thread(lambda: git.Repo.clone_from(url, clone_path))
        for f in sorted(clone_path.glob("*.md")):
            commits = list(repo.iter_commits(paths=f.name))
            last  = commits[0]  if commits else None
            first = commits[-1] if commits else None
            pages.append(WikiPageRecord(
                repo_full_name=REPO,
                page_path=f.name,
                page_name=f.stem.replace("-", " "),
                content=f.read_text(encoding="utf-8", errors="replace"),
                file_sha=None,
                git_updated_at=int(last.committed_date  * 1000) if last  else None,
                git_updated_by=last.author.name                  if last  else None,
                git_created_at=int(first.committed_date * 1000) if first else None,
            ))
    return pages


def _saved_qn(resp) -> str | None:
    created = (resp.mutated_entities.CREATE or []) if resp.mutated_entities else []
    updated = (resp.mutated_entities.UPDATE or []) if resp.mutated_entities else []
    assets  = created + updated
    return assets[0].qualified_name if assets else None


def _saved_guid(resp) -> str | None:
    created = (resp.mutated_entities.CREATE or []) if resp.mutated_entities else []
    updated = (resp.mutated_entities.UPDATE or []) if resp.mutated_entities else []
    assets  = created + updated
    return assets[0].guid if assets else None


def push(pages: list[WikiPageRecord]):
    client = AtlanClient(base_url=ATLAN_BASE_URL, api_key=ATLAN_API_KEY)
    schema_pages = [p for p in pages if is_schema_page(p)]

    # ── 1. Save glossary ─────────────────────────────────────────────────────
    print(f"\nSaving glossary '{GLOSSARY_NAME}'...")
    glossary = map_glossary(GLOSSARY_NAME)
    resp = client.asset.save(glossary)
    glossary_qn   = _saved_qn(resp)   or glossary.qualified_name
    glossary_guid = _saved_guid(resp) or ""
    print(f"  ✓ QN: {glossary_qn}  GUID: {glossary_guid}")

    # ── 2. Save categories ────────────────────────────────────────────────────
    sections: dict[str, object] = {}
    for page in schema_pages:
        section = page.wiki_section or _infer_wiki_section(page.page_name)
        if section and section not in sections:
            print(f"Saving category '{section}'...")
            cat  = map_glossary_category(section, glossary_qn)
            resp = client.asset.save(cat)
            created = (resp.mutated_entities.CREATE or []) if resp.mutated_entities else []
            updated = (resp.mutated_entities.UPDATE or []) if resp.mutated_entities else []
            saved   = (created + updated)
            sections[section] = saved[0] if saved else cat
            print(f"  ✓ {section}")

    # ── 3. Save terms, build slug → QN map ───────────────────────────────────
    print(f"\nSaving {len(schema_pages)} terms...")
    slug_to_qn: dict[str, str] = {}   # e.g. "client-baseClientEvent" → "term@<uuid>"
    slug_to_page: dict[str, WikiPageRecord] = {}

    for page in schema_pages:
        section  = page.wiki_section or _infer_wiki_section(page.page_name)
        category = sections.get(section) if section else None
        term     = map_wiki_page_as_term(page, glossary_qn, category=category)
        resp     = client.asset.save(term)
        created  = (resp.mutated_entities.CREATE or []) if resp.mutated_entities else []
        updated  = (resp.mutated_entities.UPDATE or []) if resp.mutated_entities else []
        action   = "created" if created else "updated"
        saved_qn = _saved_qn(resp)
        saved    = (created + updated)
        if saved_qn and saved:
            slug = page.page_path.removesuffix(".md")
            slug_to_qn[slug]   = saved_qn
            slug_to_page[slug] = page
            readme = map_readme(saved[0], page.content, page.page_name)
            client.asset.save(readme)
        print(f"  ✓ [{action}] {page.page_name}")

    # ── 4. Link see_also (Extends / Includes) ─────────────────────────────────
    print("\nLinking cross-references (Extends / Includes)...")
    linked = 0
    for slug, page in slug_to_page.items():
        update = build_see_also_update(page, slug_to_qn[slug], glossary_guid, slug_to_qn)
        if update:
            client.asset.save(update)
            linked += 1
            print(f"  ✓ {page.page_name}")
    if not linked:
        print("  (no cross-references found)")

    print(f"\n✅ Done — {len(schema_pages)} terms pushed to {ATLAN_BASE_URL}")
    print(f"   View at: {ATLAN_BASE_URL}/glossary")


async def main():
    print(f"Cloning wiki for {REPO}...")
    pages = await clone_wiki()
    print(f"  {len(pages)} pages found, {sum(1 for p in pages if is_schema_page(p))} are schema pages.")
    push(pages)


asyncio.run(main())
