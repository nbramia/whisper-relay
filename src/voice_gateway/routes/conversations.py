"""Proxy conversation APIs for the mobile voice UI."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from voice_gateway.adapters.lifeos import LifeOSError
from voice_gateway.adapters.text_backend import TextBackendUnavailableError, normalize_backend

router = APIRouter(prefix="/api/voice/conversations", tags=["conversations"])


def _router(request: Request):
    return request.app.state.text_backend_router


@router.get("")
async def list_conversations(
    request: Request,
    backend: str = Query(default="lifeos"),
    persona_id: str | None = Query(default=None),
) -> dict:
    try:
        client = _router(request).client_for(backend)
        if normalize_backend(backend) == "lifeos":
            pid = (persona_id or "primary").strip() or "primary"
            return await client.list_conversations(persona_id=pid)
        return await client.list_conversations()
    except TextBackendUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LifeOSError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    request: Request,
    backend: str = Query(default="lifeos"),
) -> dict:
    try:
        client = _router(request).client_for(backend)
        return await client.get_conversation(conversation_id)
    except TextBackendUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LifeOSError as exc:
        status = 404 if "404" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
