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
    map_glossary,
    map_glossary_category,
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
        await asyncio.to_thread(lambda: git.Repo.clone_from(url, clone_path))
        for f in sorted(clone_path.glob("*.md")):
            pages.append(WikiPageRecord(
                repo_full_name=REPO,
                page_path=f.name,
                page_name=f.stem.replace("-", " "),
                content=f.read_text(encoding="utf-8", errors="replace"),
                file_sha=None,
            ))
    return pages


def push(pages: list[WikiPageRecord]):
    client = AtlanClient(base_url=ATLAN_BASE_URL, api_key=ATLAN_API_KEY)
    schema_pages = [p for p in pages if is_schema_page(p)]

    # ── 1. Save glossary ─────────────────────────────────────────────────────
    print(f"\nSaving glossary '{GLOSSARY_NAME}'...")
    glossary = map_glossary(GLOSSARY_NAME)
    resp = client.asset.save(glossary)
    created = (resp.mutated_entities.CREATE or []) if resp.mutated_entities else []
    updated = (resp.mutated_entities.UPDATE or []) if resp.mutated_entities else []
    glossary_qn = (created + updated)[0].qualified_name if (created + updated) else glossary.qualified_name
    print(f"  ✓ Glossary QN: {glossary_qn}")

    # ── 2. Collect sections + save categories ─────────────────────────────────
    sections: dict[str, object] = {}
    for page in schema_pages:
        section = page.wiki_section or _infer_wiki_section(page.page_name)
        if section and section not in sections:
            print(f"Saving category '{section}'...")
            cat = map_glossary_category(section, glossary_qn)
            resp = client.asset.save(cat)
            created = (resp.mutated_entities.CREATE or []) if resp.mutated_entities else []
            updated = (resp.mutated_entities.UPDATE or []) if resp.mutated_entities else []
            saved_cat = (created + updated)
            sections[section] = saved_cat[0] if saved_cat else cat
            print(f"  ✓ {section}")

    # ── 3. Save terms ─────────────────────────────────────────────────────────
    print(f"\nSaving {len(schema_pages)} terms...")
    for page in schema_pages:
        section = page.wiki_section or _infer_wiki_section(page.page_name)
        category = sections.get(section) if section else None
        term = map_wiki_page_as_term(page, glossary_qn, category=category)
        resp = client.asset.save(term)
        created = (resp.mutated_entities.CREATE or []) if resp.mutated_entities else []
        updated = (resp.mutated_entities.UPDATE or []) if resp.mutated_entities else []
        action = "created" if created else "updated"
        print(f"  ✓ [{action}] {page.page_name}")

    print(f"\n✅ Done — {len(schema_pages)} terms pushed to {ATLAN_BASE_URL}")
    print(f"   View at: {ATLAN_BASE_URL}/glossary")


async def main():
    print(f"Cloning wiki for {REPO}...")
    pages = await clone_wiki()
    print(f"  {len(pages)} pages found, {sum(1 for p in pages if is_schema_page(p))} are schema pages.")
    push(pages)


asyncio.run(main())
