# Glossary Sync Scripts

This directory hosts the thin CLI wrapper for syncing a GitHub wiki to an
Atlan glossary. It is **Option B** in the three-option deployment matrix:

- **Option A** — GitHub Actions workflow (`.github/workflows/push-glossary.yaml`)
- **Option B** — Standalone script (this file, `scripts/push_to_atlan.py`)
- **Option C** — Atlan App Framework task (`@task github:sync_glossary` on `GitHubConnector`)

All three call `app.glossary_sync.sync_wiki_to_glossary`, so behaviour is
identical across deployment options.

## Required env vars

| Var              | Default                                                | Notes                                  |
|------------------|--------------------------------------------------------|----------------------------------------|
| `ATLAN_BASE_URL` | `https://dsm.atlan.com`                                | Atlan tenant URL                       |
| `ATLAN_API_KEY`  | _(required)_                                           | Atlan API key                          |
| `GITHUB_TOKEN`   | _(required)_                                           | GitHub PAT — used to clone the wiki    |
| `GITHUB_REPO`    | `gregmartell-atlan/app-framework_demo`                 | `owner/repo` of the wiki source        |
| `GLOSSARY_NAME`  | `ghost_tsushima`                                       | Target Atlan glossary name             |

## CLI flags

```
python3 scripts/push_to_atlan.py [--dry-run] [--phase1 | --no-phase1]
```

| Flag           | Effect                                                                          |
|----------------|---------------------------------------------------------------------------------|
| `--dry-run`    | Log what would be saved; never call `client.asset.save()`. Exits 0 on success.  |
| `--phase1`     | Default. Only push Client + Shared Schemas pages.                               |
| `--no-phase1`  | Push every schema page (any track).                                             |

## Examples

Normal run (Phase 1 scope, writes to Atlan):

```bash
ATLAN_API_KEY=xxx GITHUB_TOKEN=ghp_yyy \
  python3 scripts/push_to_atlan.py
```

Dry run (no writes; useful for previewing what a PR would touch):

```bash
ATLAN_API_KEY=xxx GITHUB_TOKEN=ghp_yyy \
  python3 scripts/push_to_atlan.py --dry-run
```

Custom glossary name, full scope (no Phase 1 filter):

```bash
ATLAN_API_KEY=xxx GITHUB_TOKEN=ghp_yyy \
GLOSSARY_NAME=my_glossary \
  python3 scripts/push_to_atlan.py --no-phase1
```

## See also

- Option A — `/.github/workflows/push-glossary.yaml` (gollum trigger + cron safety net + dry-run toggle)
- Option C — `app/connector.py` `sync_glossary` task; `app/handler.py` `handle_glossary_sync`
