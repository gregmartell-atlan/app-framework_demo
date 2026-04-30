# Running Live E2E Tests (Mac)

One-paste instructions for running the full live E2E test suite on macOS.

## Prerequisites

- Python 3.11+ installed
- `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- GitHub Personal Access Token with `repo` and `read:org` scopes
- Atlan API key (if testing full publish workflow)

## Quick Start

```bash
# 1. Clone and navigate to repo
cd app-framework_demo

# 2. Install dependencies
uv sync

# 3. Set environment variables (replace with your values)
export GITHUB_TOKEN="ghp_your_real_token_here"
export GITHUB_ORG="gregmartell-atlan"
export ATLAN_API_KEY="your_atlan_api_key"
export ATLAN_BASE_URL="https://your-tenant.atlan.com"

# 4. Run live tests (scenarios 1-5)
uv run pytest tests/e2e/test_github_app.py -k live -v --tb=short

# 5. Run all unit + integration tests
uv run pytest tests/unit/ tests/integration/ -v

# 6. (Optional) Run full connector locally
uv run python -m app.run_dev
# Then in another terminal:
curl http://localhost:8000/health
curl http://localhost:8000/manifest | jq
```

## Expected Output

✅ **Scenario 1** (auth valid PAT): `PASSED` — Returns authenticated user login  
✅ **Scenario 2** (auth invalid PAT): `PASSED` — Returns auth failure message  
✅ **Scenario 3** (preflight sufficient scopes): `PASSED` — Lists scopes + rate limit  
⏭️ **Scenario 4** (preflight missing scope): `SKIPPED` — Requires restricted token  
✅ **Scenario 5** (metadata list repos): `PASSED` — Fetches repos from org  

## Troubleshooting

### Rate Limit Errors

If you hit the GitHub API rate limit (5000 requests/hour for authenticated users):

```bash
# Check current rate limit
curl -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/rate_limit
```

Wait for the limit to reset (shown in `reset` timestamp) or reduce `max_items` in the test inputs.

### Wiki Clone Failures

If wiki cloning times out:

```bash
# Increase Git timeout
export GIT_HTTP_LOW_SPEED_TIME=300
```

### Atlan Connection Errors

If publishing to Atlan fails:

- Verify `ATLAN_API_KEY` is valid
- Ensure `ATLAN_BASE_URL` is correct (no trailing slash)
- Check that the connection exists in Atlan and you have write permissions

## CI/CD

Live tests are **NOT** run in CI (require secrets). Only mocked and replay tests run in GitHub Actions.

To enable live tests in CI, add these secrets to your GitHub repo:
- `GITHUB_TOKEN`
- `GITHUB_ORG`
- `ATLAN_API_KEY`
- `ATLAN_BASE_URL`

Then update `.github/workflows/build.yaml` to run `pytest tests/e2e/ -k live` in a separate job.

## Cleaning Up

Test runs create temporary files in `/tmp/atlan-github-*`. These are auto-cleaned by the OS, but you can manually remove them:

```bash
rm -rf /tmp/atlan-github-*
```

## Next Steps

After live tests pass:
1. Capture HTTP fixtures for replay tests (see `tests/e2e/README.md`)
2. Generate workflow histories for scenario 6-9, 14
3. Run full integration test suite including Temporal workflows
