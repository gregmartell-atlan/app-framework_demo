# Running the connector on a real local Temporal + Dapr stack

The config-screen **preview** (`serve_playground.py`) only renders the form — it
mocks the backend. To actually execute the `@task` workflow (clone the wiki,
build glossary terms, write to Atlan) you need the real runtime:

- **Temporal** — runs the workflow + activities (`localhost:7233`, UI on `8233`)
- **Dapr** — provides state store, secret store, object store to the SDK

`run_dev_combined` (`uv run poe dev`) boots a Temporal **worker + handler** in one
process, but it refuses to start unless a Dapr sidecar is present
(`DAPR_HTTP_PORT` set) and the three components below exist.

Everything here uses **zero external infra** — in-memory state, env-var secrets,
local-disk object store. No Redis, no S3, no Docker containers required.

---

## 0. Prerequisites (one-time)

### a) Python 3.12 (NOT 3.14)

`pyatlan` 9.x uses Pydantic V1 compatibility shims that are **broken on Python
3.14**. The workflow builds `AtlasGlossaryTerm` objects via pyatlan, so it will
crash on 3.14. Recreate the venv on 3.12 (uv auto-downloads it):

```bash
uv venv --python 3.12 --clear
uv sync
```

(The committed `.python-version` pins 3.12, so `uv` will pick it up.)

### b) Temporal CLI

```bash
brew install temporal
```

### c) Dapr CLI + slim runtime (no Docker)

```bash
brew install dapr/tap/dapr-cli
dapr init --slim          # installs the daprd binary + placement; no containers
dapr --version            # confirm runtime is installed
```

---

## 1. Start Temporal (terminal 1)

```bash
uv run poe start-temporal
```

This runs `temporal server start-dev` — Temporal on `localhost:7233`, web UI on
http://localhost:8233. Leave it running.

---

## 2. Start the app under Dapr (terminal 2)

```bash
uv run poe dev-dapr
```

This wraps the app in `dapr run`, which:
- starts a Dapr sidecar (sets `DAPR_HTTP_PORT` for the app)
- loads `./components/*.yaml` (statestore / secretstore / objectstore)
- launches `python -m app.run_dev` → Temporal worker + handler

The handler serves the **real** config screen + `/workflows/v1/*` API on
http://localhost:8000 (no mock this time).

---

## 3. Run the sync

1. Open http://localhost:8000 — fill in the 3-step form.
2. Before submitting, export the secrets the credential GUIDs resolve to
   (secretstores.local.env reads them from the environment of terminal 2):
   ```bash
   export GITHUB_TOKEN=ghp_xxx
   export ATLAN_API_KEY=xxx
   ```
3. Click **Start Workflow**.
4. Watch it execute in the Temporal UI: http://localhost:8233 — you'll see the
   `sync_glossary` workflow, its activities, retries, and result.

---

## Architecture recap

```
Browser (config form, :8000)
      |  POST /workflows/v1/start
      v
SDK handler  --->  Temporal (:7233)  --->  worker runs @task sync_glossary
      |                                            |
      |                                            v
   Dapr sidecar (:3500) <----- state / secrets / object store
      |
  components/*.yaml  (in-memory, env, local disk)
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Dapr sidecar not detected (DAPR_HTTP_PORT not set)` | You ran `poe dev` instead of `poe dev-dapr`. Use the Dapr wrapper. |
| `No Dapr component named 'objectstore'` | `./components/*.yaml` missing or wrong CWD. Run from repo root. |
| `Connection refused` to `localhost:7233` | Temporal isn't running — start terminal 1 first. |
| pyatlan `Pydantic V1 ... not compatible with Python 3.14` | venv is on 3.14. Recreate on 3.12 (step 0a). |
| Credential resolves empty | Export the secret env vars in terminal 2 before submitting. |
