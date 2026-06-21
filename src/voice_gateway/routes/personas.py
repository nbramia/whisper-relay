"""Proxy LifeOS persona discovery for the mobile voice UI."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from voice_gateway.adapters.lifeos import LifeOSError

router = APIRouter(prefix="/api/voice", tags=["personas"])


@router.get("/personas")
async def list_personas(request: Request) -> dict:
    lifeos = request.app.state.lifeos_client
    try:
        data = await lifeos.list_personas()
    except LifeOSError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    request.app.state.lifeos_personas = data
    return data
