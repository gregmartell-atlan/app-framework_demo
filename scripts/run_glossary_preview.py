"""Dry-run: extract wiki pages from a GitHub repo and print glossary term output.

Usage:
    GITHUB_TOKEN=ghp_... python scripts/run_glossary_preview.py
    GITHUB_TOKEN=ghp_... python scripts/run_glossary_preview.py --repo gregmartell-atlan/app-framework_demo
    GITHUB_TOKEN=ghp_... python scripts/run_glossary_preview.py --repo myorg/myrepo --glossary myorg
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import git
from git.exc import GitCommandError

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.api_types import WikiPageRecord
from app.credentials import GitHubTokenCredential
from app.glossary_mapper import (
    _infer_wiki_section,
    map_glossary,
    map_glossary_category,
    map_wiki_page_as_term,
)


async def _clone_wiki_standalone(repo_full_name: str, token: str) -> list[WikiPageRecord]:
    """Clone wiki directly without task_context, using asyncio.to_thread."""
    wiki_url = f"https://{token}@github.com/{repo_full_name}.wiki.git"
    env = os.environ.copy()
    env["GIT_HTTP_LOW_SPEED_LIMIT"] = "1000"
    env["GIT_HTTP_LOW_SPEED_TIME"] = "120"

    pages = []
    with tempfile.TemporaryDirectory() as tmpdir:
        clone_path = Path(tmpdir) / "wiki"
        await asyncio.to_thread(
            lambda: git.Repo.clone_from(wiki_url, clone_path, env=env)
        )
        for md_file in sorted(clone_path.glob("*.md")):
            content = md_file.read_text(encoding="utf-8", errors="replace")
            page_name = md_file.stem.replace("-", " ")
            pages.append(WikiPageRecord(
                repo_full_name=repo_full_name,
                page_path=md_file.name,
                page_name=page_name,
                content=content,
                file_sha=None,
            ))
    return pages


def _term_to_dict(term) -> dict:
    """Extract the printable fields from an AtlasGlossaryTerm."""
    return {
        "type": "AtlasGlossaryTerm",
        "name": term.name,
        "description": term.description if term.description else None,
        "user_description": term.user_description if term.user_description else None,
        "source_url": term.source_url if term.source_url else None,
        "owner_users": sorted(term.owner_users) if term.owner_users else None,
        "categories": [c.name for c in term.categories] if term.categories else [],
        "long_description_chars": len(term.long_description) if term.long_description else 0,
    }


async def run(repo_full_name: str, glossary_name: str, token: str):
    credential = GitHubTokenCredential(token=token)

    print(f"\n{'='*60}")
    print(f"  Glossary dry-run: {repo_full_name}")
    print(f"  Glossary name:    {glossary_name}")
    print(f"{'='*60}\n")

    # ── Glossary shell ───────────────────────────────────────────────────────
    glossary = map_glossary(glossary_name)
    print(json.dumps({
        "type": "AtlasGlossary",
        "name": glossary.name,
        "description": glossary.description,
    }, indent=2))
    print()

    # ── Extract wiki pages ───────────────────────────────────────────────────
    pages = []
    print(f"Cloning wiki for {repo_full_name}...")
    try:
        pages = await _clone_wiki_standalone(repo_full_name, token)
    except Exception as e:
        print(f"  Wiki clone failed: {e}")
        print("  (repo may have no wiki, or token lacks access)")
        return

    print(f"  Found {len(pages)} wiki page(s)\n")

    if not pages:
        print("No wiki pages found — nothing to map.")
        return

    # ── Collect sections → categories ────────────────────────────────────────
    # Use a placeholder QN since we're not actually saving
    PLACEHOLDER_QN = f"preview-{glossary_name}"

    sections: dict[str, object] = {}
    for page in pages:
        section = page.wiki_section or _infer_wiki_section(page.page_name)
        if section and section not in sections:
            cat = map_glossary_category(section, PLACEHOLDER_QN)
            sections[section] = cat
            print(json.dumps({
                "type": "AtlasGlossaryCategory",
                "name": cat.name,
                "glossary": glossary_name,
            }, indent=2))
            print()

    if not sections:
        print("(no nav sections inferred from page titles)\n")

    # ── Terms ────────────────────────────────────────────────────────────────
    print(f"{'─'*60}")
    print(f"  Terms ({len(pages)} total)")
    print(f"{'─'*60}\n")

    for page in pages:
        section = page.wiki_section or _infer_wiki_section(page.page_name)
        category = sections.get(section) if section else None
        term = map_wiki_page_as_term(page, PLACEHOLDER_QN, category=category)
        print(json.dumps(_term_to_dict(term), indent=2))
        print()


def main():
    import os

    parser = argparse.ArgumentParser(description="Glossary dry-run preview")
    parser.add_argument(
        "--repo",
        default="gregmartell-atlan/app-framework_demo",
        help="GitHub repo full name (org/repo)",
    )
    parser.add_argument(
        "--glossary",
        default=None,
        help="Glossary name (defaults to org from --repo)",
    )
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("ERROR: GITHUB_TOKEN environment variable is required.")
        print("  export GITHUB_TOKEN=ghp_...")
        sys.exit(1)

    org = args.repo.split("/")[0]
    glossary_name = args.glossary or org

    asyncio.run(run(args.repo, glossary_name, token))


if __name__ == "__main__":
    main()
