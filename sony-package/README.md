# Sony Telemetry — GitHub Wiki → Atlan Glossary Sync

Syncs every markdown page from your GitHub wiki into an Atlan **Glossary**,
organised into the telemetry hierarchy discussed with the Atlan team:

```
sony_telemetry (Glossary)
├── Client
│   ├── Events
│   └── Event Templates
├── Native
│   ├── Events
│   └── Event Templates
├── Tooling
│   ├── Events
│   └── Event Templates
└── Shared Schemas
```

Three deployment options — all calling the same `sync_wiki_to_glossary()` core.

---

## Option A — GitHub Actions (recommended)

**Setup (5 minutes):**

1. Add one repo secret (`Settings → Secrets → Actions`):
   ```
   Name:  ATLAN_API_KEY
   Value: <your key from dsm.atlan.com → Settings → API Keys>
   ```
   `GITHUB_TOKEN` is provided automatically by GitHub.

2. Copy these files into your repo:
   ```
   .github/workflows/push-glossary.yaml
   scripts/push_to_atlan.py
   app/glossary_sync.py
   app/glossary_mapper.py
   app/api_types.py
   app/contracts.py
   requirements.txt
   ```

3. The glossary name is already set to `sony_telemetry` in the workflow. Change it if needed.

4. Merge to main.

The workflow fires on every wiki edit (`gollum`), daily at 06:00 UTC, and
on manual dispatch with optional `dry_run` and `phase1_filter` toggles.

---

## Option B — Standalone Script

```bash
pip install pyatlan gitpython
```

**Dry run (preview, no writes):**
```bash
ATLAN_BASE_URL=https://dsm.atlan.com \
ATLAN_API_KEY=<your-key> \
GITHUB_TOKEN=<your-ghp-token> \
GITHUB_REPO=sony-telemetry/schema-registry \
GLOSSARY_NAME=sony_telemetry \
  python3 scripts/push_to_atlan.py --dry-run
```

**Live run:**
```bash
ATLAN_BASE_URL=https://dsm.atlan.com \
ATLAN_API_KEY=<your-key> \
GITHUB_TOKEN=<your-ghp-token> \
  python3 scripts/push_to_atlan.py --phase1
```

The script is idempotent — run it as many times as you like.

---

## Option C — Atlan App Framework

Once the connector is certified on your Atlan tenant:

1. Open the GitHub connector in the Atlan marketplace
2. Enter your GitHub PAT and Atlan credential
3. Set the repo, glossary name, and Phase 1 toggle
4. Click **Run** — or set a schedule

Start with Option A or B today; migrate to C once the connector is certified.

---

## Atlan admin prerequisites (one-time)

Before the full hierarchy renders in the UI:

```
Atlan → Admin → Labs → Glossary → Term attributes
Toggle ON: isA, classifies
```

Without this the Extends parent hierarchy won't render. Terms still sync correctly;
you'll just see flat terms rather than the tree.

---

## Phase 1 scope

| Flag | Behaviour |
|------|----------|
| `--phase1` (default) | Only Client + Shared Schemas pages |
| `--no-phase1` | All schema pages (Client + Native + Tooling + Shared Schemas) |

## Requirements

- Python 3.11+
- `pyatlan>=9.6,<10`
- `gitpython>=3.1,<4`
