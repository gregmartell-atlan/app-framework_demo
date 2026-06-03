"""Minimal local server for previewing the App Framework config screen.

Serves the playground SPA static files plus the three API endpoints the
SPA polls on load. No Dapr, no Temporal, no external services needed.

Usage:
    uv run python serve_playground.py

Then open http://localhost:8000
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
    """GET /workflows/v1/configmaps — list of config map id strings.

    The SPA calls .startsWith() on each item, so these MUST be strings.
    """
    return JSONResponse([config_map["id"]])


async def get_manifest(request: Request) -> JSONResponse:
    """GET /workflows/v1/manifest — connector manifest."""
    return JSONResponse(manifest)


async def get_configmap(request: Request) -> JSONResponse:
    """GET /workflows/v1/configmap/{id} — full config map (id/name/logo/config)."""
    return JSONResponse(config_map)


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
