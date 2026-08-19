"""Health check routes."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _probe(client: Any) -> bool | None:
    """Reachability for a configured backend client, or None when unavailable."""
    if client is None or not hasattr(client, "health_check"):
        return None
    try:
        return await client.health_check()
    except Exception:
        return False


@router.get("/health/backends")
async def health_backends(request: Request) -> dict:
    settings = request.app.state.settings
    text_backend = request.app.state.text_backend_router

    lifeos_ok = False
    try:
        # LifeOS /health/full runs ~12 service checks and can take 5-6s; give the
        # probe comfortable headroom so a healthy-but-slow backend isn't reported
        # unreachable here (whisper-relay#27 follow-up).
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.lifeos_base_url.rstrip('/')}/health/full")
            lifeos_ok = resp.status_code == 200
    except Exception:
        lifeos_ok = False

    agent_client = text_backend.agent
    hermes_client = text_backend.hermes

    return {
        "lifeos": {"reachable": lifeos_ok, "url": settings.lifeos_base_url},
        "agent": {
            "configured": agent_client is not None,
            "reachable": await _probe(agent_client),
            "url": settings.agent_backend_url if settings.agent_backend_enabled else None,
        },
        "hermes": {
            "configured": hermes_client is not None,
            "reachable": await _probe(hermes_client),
            "url": settings.hermes_backend_url if settings.hermes_backend_enabled else None,
        },
    }
