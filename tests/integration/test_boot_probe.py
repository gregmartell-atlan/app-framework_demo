"""Integration test: boot probe for Temporal + Dapr + app subprocess.

This test verifies:
1. App starts successfully in combined mode
2. /health endpoint responds within 30s
3. /manifest endpoint returns valid JSON matching committed file
4. /workflows/v1/configmap/github endpoint returns valid JSON matching committed file

Runs in CI via .github/workflows/boot-probe.yaml
"""

import asyncio
import json
import subprocess
import time
from pathlib import Path

import httpx
import pytest


@pytest.fixture(scope="module")
def app_process():
    """Start the app in dev mode and yield the process."""
    # Start app subprocess
    proc = subprocess.Popen(
        ["uv", "run", "python", "-m", "app.run_dev"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait a bit for startup
    time.sleep(5)

    yield proc

    # Teardown: kill process
    proc.terminate()
    proc.wait(timeout=10)


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_health_endpoint(app_process):
    """Test /health endpoint responds within 30s."""
    start = time.time()
    health_url = "http://localhost:8000/health"

    async with httpx.AsyncClient() as client:
        for _ in range(30):  # Poll for 30 seconds
            try:
                response = await client.get(health_url, timeout=2.0)
                if response.status_code == 200:
                    elapsed = time.time() - start
                    assert elapsed < 30, f"Health check took {elapsed}s (should be < 30s)"
                    return
            except (httpx.ConnectError, httpx.TimeoutException):
                await asyncio.sleep(1)

        pytest.fail("Health endpoint did not respond within 30s")


@pytest.mark.asyncio
async def test_manifest_endpoint_matches_committed(app_process):
    """Test /manifest returns JSON matching app/generated/manifest.json."""
    manifest_url = "http://localhost:8000/manifest"

    async with httpx.AsyncClient() as client:
        response = await client.get(manifest_url, timeout=5.0)
        assert response.status_code == 200

        live_manifest = response.json()
        committed_manifest_path = Path(__file__).parent.parent.parent / "app/generated/manifest.json"
        committed_manifest = json.loads(committed_manifest_path.read_text())

        # Compare (allowing for minor differences like timestamps)
        assert live_manifest["name"] == committed_manifest["name"]
        assert live_manifest["tasks"] == committed_manifest["tasks"]


@pytest.mark.asyncio
async def test_configmap_github_endpoint(app_process):
    """Test /workflows/v1/configmap/github matches app/generated/github.json."""
    configmap_url = "http://localhost:8000/workflows/v1/configmap/github"

    async with httpx.AsyncClient() as client:
        response = await client.get(configmap_url, timeout=5.0)
        assert response.status_code == 200

        live_config = response.json()
        committed_config_path = Path(__file__).parent.parent.parent / "app/generated/github.json"
        committed_config = json.loads(committed_config_path.read_text())

        assert live_config == committed_config
