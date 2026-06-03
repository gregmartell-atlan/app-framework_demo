# QA Report — GitHub → Atlan Glossary App

**Reviewers:** Atlan Connector Engineer (build/CI/runtime) + App Framework PM (submittability/conventions/product)
**Branch:** `claude/review-and-setup-testing-GzGvk` @ `d0526a6`
**Reconciled against:** `atlanhq/application-sdk/docs/standards/v3-readiness.md`, the repo `README.md` v3 mapping table, `contract/app.pkl`, and the installed `application_sdk==3.4.0` API surface.

**Verdict:** Phase-1 glossary sync (Option A workflow + Option B script) is sound and shippable as standalone tooling. **Option C (the in-framework app) is NOT submittable** — it would fail `uv sync`, `poe generate`, the boot probe, and the v3-readiness check. Several README claims do not reconcile with the code.

---

## P0 — Blockers (CI is red on first step; nothing downstream runs)

### P0-1 · `pyatlan-v9` dependency does not exist on PyPI
`pyproject.toml` pins `pyatlan-v9>=2.0,<3`. The real distribution is **`pyatlan` (9.6.0)**; the *import module* is `pyatlan_v9`. Confirmed: `pip index versions pyatlan-v9` → "No matching distribution found."
- **Impact:** every CI job (`build.yaml`, `boot-probe.yaml`) starts with `uv sync` → fails immediately. Docker `uv sync --frozen` → fails.
- **Fix:** `pyproject.toml` → `"pyatlan>=9.6,<10"`. (The code already imports `pyatlan_v9`, which 9.6 provides.)

### P0-2 · `uv.lock` is missing
`Dockerfile:17` does `COPY pyproject.toml uv.lock ./` and `:22` runs `uv sync --frozen --no-dev`. No lockfile exists at repo root.
- **Impact:** image build fails at COPY; `--frozen` fails without a lock.
- **Fix:** `uv lock` then commit `uv.lock` (depends on P0-1 resolving first).

### P0-3 · Contract ↔ code task-name drift (manifest is wrong)
| `manifest.json` task | `name` emitted | Method in `connector.py`? |
|---|---|---|
| `extract` | `github:fetch_repos` | ✅ `fetch_repos` |
| `transform` | `github:transform` | ✅ `transform` |
| `publish` | **`github:publish`** | ❌ **no such method** |
| — | `github:fetch_sbom` | ✅ exists in code, **absent from contract/manifest** |
| — | `github:sync_glossary` | ✅ in code + `app.pkl`, **absent from `manifest.json`** |

- **Impact:** v3-readiness naming check fails (`github:publish` has no task); boot-probe `/manifest` diff fails (live manifest won't match committed; and `sync_glossary` you added to `app.pkl` was never regenerated into `manifest.json`).
- **Fix:** reconcile to one set. Either add a `publish` task method or drop `publish` from the contract; add `fetch_sbom` + `sync_glossary` to the contract; re-run `poe generate`; commit `app/generated/*`.

### P0-4 · Generated artifacts are stale vs `app.pkl`
`app.pkl` now has a `sync_glossary` form step, a `sync_glossary` task, and an `atlanCredentialType`. None of this is in `app/generated/manifest.json`, `github.json`, or `_input.py` (`_input.py` has no `SyncGlossaryStepInput`; `WorkflowInput` omits it).
- **Impact:** `poe generate` + `git diff --exit-code app/generated/` (the v3 drift gate) fails; boot-probe configmap diff fails.
- **Fix:** regenerate after P0-5 is resolved.

### P0-5 · `atlanCredentialType` is almost certainly invalid Pkl
`app.pkl:1` does `amends ".../Application.pkl"`. The toolkit schema defines `credentialType` — there is no `atlanCredentialType` property. A bare new key on an `amends` module is a Pkl "cannot find property" error.
- **Impact:** `pkl eval` (`poe generate`) errors out → no artifacts can be regenerated → P0-3/P0-4 unfixable until this is corrected.
- **Fix:** verify the toolkit's `Application.pkl` shape. Most likely credential types are a **listing/mapping** under one property; declare both `github_token` and the Atlan credential there. **Better:** drop the custom Atlan credential entirely — see P1-2.

---

## P1 — Major (would fail certification even with CI green)

### P1-1 · Sync Atlan client instead of the v3 async pattern
`handler.py:196` and `connector.py` `transform` use `pyatlan_v9.client.atlan.AtlanClient` (sync) and `self.task_context.atlan_client`. v3-readiness §1 mandates the async client. The SDK ships the intended path: `AtlanClientMixin.get_or_create_async_atlan_client(credential)` (confirmed in `application_sdk.app`).
- **Fix:** `class GitHubConnector(AtlanClientMixin, App)` and `client = await self.get_or_create_async_atlan_client(...)`.

### P1-2 · Re-inventing a credential the framework already ships
We register a custom `atlan_api_key` cred. The SDK already provides **`atlan_api_token`** (`AtlanApiToken` with `token` / `base_url` / `expires_at`) — confirmed in the registry. v3 expects `AtlanApiToken`.
- **Fix:** use the built-in `atlan_api_token` (resolves P0-5 too — no second custom credentialType needed) and feed it to `get_or_create_async_atlan_client`.

### P1-3 · `task_context` API surface mismatch (runtime AttributeError risk)
The installed `TaskExecutionContext` exposes only `heartbeat`, `get_heartbeat_details`, `get_last_heartbeat_details`, `run_in_thread`. The code calls `self.task_context.working_directory`, `.atlan_client`, `.current_time_iso()` in `fetch_repos` / `fetch_sbom` / `transform`.
- **Impact:** these tasks would raise at runtime. **Needs runtime verification** (the App base may inject a richer context object than the bare dataclass), but the public API does not match.
- **Fix:** confirm the real context object; route Atlan access through the mixin (P1-1) and file I/O through the SDK's working-dir API.

### P1-4 · Dead / stub code at contract boundaries
- `handle_metadata_extraction` (`handler.py:141`) is an unreferenced stub returning zero counts.
- `TransformSbomInput` / `TransformSbomOutput` are defined but used by no task.
- **Fix:** delete both, or wire them in.

### P1-5 · A few task-boundary-ish contracts still on raw `BaseModel`
Fixed the 12 live Input/Output classes (now inherit SDK `Input`/`Output`). Still raw `BaseModel`: `TransformSbomInput/Output` (dead → delete), and `GlossarySyncConfig`/`GlossarySyncResult` (internal, not task boundaries → acceptable as-is, but document the distinction).

---

## P2 — Documentation reconciliation (PM credibility)

| README claim | Reality | 
|---|---|
| "`app/connector.py` extends **`BaseMetadataExtractor`**" (§Why-this-layout & repo-layout) | Extends **`App`**. `BaseMetadataExtractor` does not exist in `application_sdk` 3.4.0. |
| "§1 **`create_async_atlan_client`** + typed credentials" | Code uses the **sync** `AtlanClient`. No `create_async_atlan_client` symbol in the SDK; the real API is `AtlanClientMixin.get_or_create_async_atlan_client`. |
| "What was tested where → Boot probe / manifest endpoints ✅" | Boot probe currently **cannot pass** (P0-1..P0-4). Table overstates status. |
| `poe check-v3` → `tools.migrate_v3.check_migration` | Not importable in this SDK install (runs only via the reusable CI workflow). Note it as CI-only so contributors don't expect it locally. |
| Credential shape | `GitHubTokenCredential.credential_type` is a `@property`; `AtlanCredential.credential_type` is a `ClassVar`. Pick one convention. |

---

## PM lens — product & architecture coherence

1. **Three-option strategy is the right call for Sony** — A (workflow) and B (script) are self-contained and ship today; C is the certification track. The PR already states this clearly. ✅
2. **Option C overloads one app with two unrelated jobs.** The GitHub *metadata extractor* (repos/wiki/SBOM → Application/ApplicationField, extract→transform→publish DAG) and the *wiki→glossary sync* (its own credentials, its own DAG-less task) are really two connectors. Cramming `sync_glossary` + a second tenant credential into the metadata-extractor manifest is what forces P0-5. **Recommendation:** ship glossary sync as its own small app, or as an explicit second workflow within the contract — don't bolt a second credential onto the extractor.
3. **Demo defaults leak into the contract.** `glossary_name` default `ghost_tsushima` and `ATLAN_BASE_URL` default `https://dsm.atlan.com` are committed. For a real submission, `glossary_name` should be required-no-default and base URL should come from the resolved Atlan credential, not a hardcoded tenant.
4. **`certified=false` / `previewStatus=false`** are correct for now; flip per the submission checklist when C is ready.

---

## Recommended fix order (to get Option C submittable)
1. P0-1 `pyatlan` dep → P0-2 `uv lock` & commit.
2. P1-2 swap to built-in `atlan_api_token`; P0-5 fix/remove `atlanCredentialType`.
3. P0-3 reconcile task names (decide on `publish`; add `fetch_sbom`/`sync_glossary`); P1-1 async client via mixin.
4. `poe generate`; commit `app/generated/*` → clears P0-4 + boot-probe.
5. P1-3 verify context API live; P1-4 delete stubs.
6. P2 correct README claims.
7. Run `poe check-v3` + boot probe in CI until green.

**What's already solid:** glossary mapper logic, the shared `glossary_sync` module, Phase-1 filter, relationship model, and the 182 passing unit tests (incl. the 25 new v3-shape tests). The standalone paths (A/B) are unaffected by every P0 above except the `pyatlan` dep name, which they share — so **fixing P0-1 alone makes A and B fully runnable.**
