"""Minimal local server for previewing the App Framework config screen.

Serves the playground SPA static files plus the three API endpoints the
SPA polls on load. No Dapr, no Temporal, no external services needed.

Usage:
    uv run python serve_playground.py

Then open http://localhost:8000

Response contract (reverse-engineered from the playground SPA bundle):
  GET /workflows/v1/configmaps        -> {"data": ["<id>", ...]}   (id strings)
  GET /workflows/v1/configmap/{id}    -> {"data": {id,name,logo,config}}
  GET /workflows/v1/manifest          -> {...manifest...}          (read raw)

The SPA reads e.value.data off the configmap fetches (useAsyncData style),
but reads the manifest body directly — hence the asymmetric wrapping.
"""

import json
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
MANIFEST_FILE = BASE / "app" / "generated" / "manifest.json"

config_map = json.loads(CONFIG_FILE.read_text())
manifest = json.loads(MANIFEST_FILE.read_text())


async def list_configmaps(request: Request) -> JSONResponse:
    """GET /workflows/v1/configmaps — {data: [id strings]}."""
    return JSONResponse({"data": [config_map["id"]]})


async def get_manifest(request: Request) -> JSONResponse:
    """GET /workflows/v1/manifest — raw manifest (SPA reads body directly)."""
    return JSONResponse(manifest)


async def get_configmap(request: Request) -> JSONResponse:
    """GET /workflows/v1/configmap/{id} — {data: {id,name,logo,config}}."""
    return JSONResponse({"data": config_map})


routes = [
    Route("/workflows/v1/configmaps", list_configmaps),
    Route("/workflows/v1/manifest", get_manifest),
    Route("/workflows/v1/configmap/{config_id}", get_configmap),
    Mount("/", app=StaticFiles(directory=str(STATIC_DIR), html=True)),
]

app = Starlette(routes=routes)

if __name__ == "__main__":
    print("Config screen preview → http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
