"""Health check routes."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Request

from voice_gateway.adapters.agent_backend import HTTPAgentBackendClient

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/backends")
async def health_backends(request: Request) -> dict:
    settings = request.app.state.settings
    text_backend = request.app.state.text_backend_router

    lifeos_ok = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.lifeos_base_url.rstrip('/')}/health/full")
            lifeos_ok = resp.status_code == 200
    except Exception:
        lifeos_ok = False

    agent_ok: bool | None = None
    agent_client = text_backend.agent
    if agent_client is not None and isinstance(agent_client, HTTPAgentBackendClient):
        try:
            agent_ok = await agent_client.health_check()
        except Exception:
            agent_ok = False

    return {
        "lifeos": {"reachable": lifeos_ok, "url": settings.lifeos_base_url},
        "agent": {
            "configured": agent_client is not None,
            "reachable": agent_ok,
            "url": settings.agent_backend_url if settings.agent_backend_enabled else None,
        },
    }
