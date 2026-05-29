**To:** Sai (SIE Telemetry), Sony Engineering Team  
**From:** Greg Martell, Atlan  
**Subject:** GitHub Wiki → Atlan Glossary Sync — Ready to Use (3 Deployment Options)

---

Hi Sai,

Following up on our Phase 1 scoping conversation — we've built and tested the full GitHub wiki → Atlan glossary sync pipeline. Everything is in the repo linked below and ready to go live on your end. Three deployment options, all calling the same underlying logic; you pick what fits your team's workflow.

**Repo:** https://github.com/gregmartell-atlan/sony_git_connector

---

## What it does

Reads every markdown page in your GitHub wiki and upserts it as an Atlan **Glossary Term**, organised into the hierarchy we discussed:

```
sony_telemetry (Glossary)
├── Client
│   ├── Events         ← e.g. Client AdTracking, Client PlayerLogin
│   └── Event Templates
├── Native
│   ├── Events
│   └── Event Templates
├── Tooling
│   ├── Events
│   └── Event Templates
└── Shared Schemas     ← cross-track templates (consoleInfo, catalogInfo, …)
```

Each term gets:
- **Description** from the `## Description` section
- **Readme** with the full markdown content
- **Owner** (contact @handles → `owner_users`, business owner team → `owner_groups`)
- **Usage** from `## Classification justification`
- **Source URL** linking back to the wiki page
- **Last edited / created** timestamps from git history
- **Relationships**: Extends → `isA` hierarchy; Includes → `user_def_relationship_to`

**Phase 1 filter** (default ON): only Client + Shared Schemas pages are pushed. Native and Tooling are staged for Phase 1.5 once confirmed with your team.

---

## Option A — GitHub Actions (recommended, 5-minute setup)

The simplest path. One secret, merge, done — wiki edits auto-sync within ~2 minutes.

**Setup:**

1. Add one secret to your repo:
   ```
   Settings → Secrets → Actions → New repository secret
   Name:   ATLAN_API_KEY
   Value:  <your Atlan API key from dsm.atlan.com → Settings → API Keys>
   ```
   (`GITHUB_TOKEN` is provided automatically by GitHub — no action needed.)

2. Copy these files from our repo into yours:
   ```
   .github/workflows/push-glossary.yaml
   scripts/push_to_atlan.py
   app/glossary_sync.py
   app/glossary_mapper.py
   app/api_types.py
   app/contracts.py
   requirements.txt
   ```

3. The glossary name is already set to `sony_telemetry`. Change it in the workflow if needed.

4. Merge to main.

**How it runs after that:**
- Any wiki page edit → `gollum` event → workflow triggers automatically
- Daily at 06:00 UTC safety net (catches any missed edits)
- Manual trigger: `Actions → Sync Wiki to Atlan Glossary → Run workflow`
  - Toggle `dry_run = true` to preview without writing anything to Atlan
  - Toggle `phase1_filter = false` when you're ready to include Native + Tooling

---

## Option B — Standalone script (run from a laptop or your own CI)

No GitHub Actions required. Good if your security policy restricts outbound connections from CI.

**Requirements:**
```bash
pip install pyatlan gitpython
git clone https://github.com/gregmartell-atlan/sony_git_connector
```

**Dry run first (preview, no writes):**
```bash
ATLAN_BASE_URL=https://dsm.atlan.com \
ATLAN_API_KEY=<your-key> \
GITHUB_TOKEN=<your-ghp-token> \
GITHUB_REPO=sony-telemetry/schema-registry \
GLOSSARY_NAME=sony_telemetry \
  python3 scripts/push_to_atlan.py --dry-run
```

**Live run (writes to Atlan):**
```bash
ATLAN_BASE_URL=https://dsm.atlan.com \
ATLAN_API_KEY=<your-key> \
GITHUB_TOKEN=<your-ghp-token> \
GITHUB_REPO=sony-telemetry/schema-registry \
GLOSSARY_NAME=sony_telemetry \
  python3 scripts/push_to_atlan.py --phase1
```

The script is idempotent — run it as many times as you like, it will create missing terms and update existing ones without duplicating anything.

---

## Option C — Atlan App Framework (future state, no scripts at all)

Once the connector is certified and installed on your Atlan tenant, you'd configure everything through the Atlan UI — no scripts, no secrets to manage:

1. Open the GitHub connector in your Atlan marketplace
2. Enter your GitHub PAT and Atlan credential
3. Set the repo, glossary name, and Phase 1 toggle
4. Click **Run** — or set a schedule

This option is staged and ready; it requires Atlan's platform team to package and deploy the connector image. We'd recommend starting with Option A or B today and migrating to C once the connector is certified.

---

## Prerequisites (Atlan admin — one-time)

Before any option will show the full hierarchy in the UI:

1. **Enable isA/classifies term attributes:**
   ```
   Atlan → Admin → Labs → Glossary → Term attributes
   Toggle ON: isA, classifies
   ```
   Without this, the Extends → parent hierarchy won't render. The terms and categories will still sync correctly — you'll just see flat terms rather than the tree.

2. **Glossary name must match exactly** what you set in `GLOSSARY_NAME` / the workflow input. The sync will create the glossary on first run if it doesn't exist.

---

## What's NOT in scope yet (Phase 1.5)

- **Native + Tooling** pages: ready in the code (`--no-phase1`), pending your team's confirmation of the term count with Sai (666 vs 683 discrepancy to resolve)
- **CustomMetadataDef** for `schemaVersion`, `sourceUrl`, `sourceCommitSha` scoped to the glossary
- **YAML schema files** as separate glossary terms (the hook is there, just not enabled in Phase 1)

---

Let me know if you'd like a live walkthrough of Option A setup, or if you'd prefer to start with a dry run on a test glossary. Happy to jump on a call.

Best,  
Greg
