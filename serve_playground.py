"""Minimal local server for previewing the App Framework config screen.

Serves the playground SPA static files plus the API endpoints the SPA polls
on load. No Dapr, no Temporal, no external services needed.

Usage:
    uv run python serve_playground.py

Then open http://localhost:8000

Response contract (reverse-engineered from the playground SPA bundle):
  GET  /workflows/v1/configmaps       -> {"data": ["<id>", ...]}   (id strings)
  GET  /workflows/v1/configmap/{id}   -> {"data": {id,name,logo,config}}
  GET  /workflows/v1/manifest         -> {...manifest...}          (read raw)
  POST /workflows/v1/auth             -> {"success": true, ...}    (credential test)
  POST /workflows/v1/dev/local-vault  -> {"credential_guid": ...}  (mock vault)
  POST /workflows/v1/start            -> {"workflow_id": ...}      (mock start)

The POST endpoints are mocks for preview only — they never touch GitHub or
Atlan. This server is for visually previewing the config form, not running
the actual sync (that needs the real Atlan App Framework runtime).
"""

import json
import uuid
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

BASE = Path(__file__).parent
STATIC_DIR = BASE / "frontend" / "static"
CONFIG_FILE = BASE / "frontend" / "config.json"
CRED_DIR = BASE / "frontend" / "credentials"
MANIFEST_FILE = BASE / "app" / "generated" / "manifest.json"

main_config = json.loads(CONFIG_FILE.read_text())
manifest = json.loads(MANIFEST_FILE.read_text())

# Registry of all configmaps keyed by id: the main workflow + every credential
# sub-form. The credential widget looks these up by ui.credentialType.
configmaps: dict[str, dict] = {main_config["id"]: main_config}
if CRED_DIR.exists():
    for cred_file in CRED_DIR.glob("*.json"):
        cred = json.loads(cred_file.read_text())
        configmaps[cred["id"]] = cred


async def list_configmaps(request: Request) -> JSONResponse:
    """GET /workflows/v1/configmaps — {data: [id strings]}."""
    return JSONResponse({"data": [main_config["id"]]})


async def get_manifest(request: Request) -> JSONResponse:
    """GET /workflows/v1/manifest — raw manifest (SPA reads body directly)."""
    return JSONResponse(manifest)


async def get_configmap(request: Request) -> JSONResponse:
    """GET /workflows/v1/configmap/{id} — {data: {id,name,logo,config}}."""
    config_id = request.path_params["config_id"]
    cfg = configmaps.get(config_id, main_config)
    return JSONResponse({"data": cfg})


async def test_auth(request: Request) -> JSONResponse:
    """POST /workflows/v1/auth — mock credential test (always succeeds)."""
    return JSONResponse({"success": True, "message": "Authentication successful (preview mock)"})


async def local_vault(request: Request) -> JSONResponse:
    """POST /workflows/v1/dev/local-vault — mock credential vaulting."""
    return JSONResponse({"credential_guid": f"preview-{uuid.uuid4()}"})


async def start_workflow(request: Request) -> JSONResponse:
    """POST /workflows/v1/start — mock workflow start (no real execution)."""
    return JSONResponse({
        "workflow_id": f"preview-{uuid.uuid4()}",
        "run_id": f"preview-{uuid.uuid4()}",
        "message": "Preview mock — no workflow was actually started",
    })


routes = [
    Route("/workflows/v1/configmaps", list_configmaps),
    Route("/workflows/v1/manifest", get_manifest),
    Route("/workflows/v1/configmap/{config_id}", get_configmap),
    Route("/workflows/v1/auth", test_auth, methods=["POST"]),
    Route("/workflows/v1/dev/local-vault", local_vault, methods=["POST"]),
    Route("/workflows/v1/start", start_workflow, methods=["POST"]),
    Mount("/", app=StaticFiles(directory=str(STATIC_DIR), html=True)),
]

app = Starlette(routes=routes)

if __name__ == "__main__":
    print("Config screen preview → http://localhost:8000")
    print(f"Loaded configmaps: {sorted(configmaps)}")
    uvicorn.run(app, host="127.0.0.1", port=8000)
