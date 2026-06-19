"""Proxy LifeOS conversation APIs for the mobile voice UI."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from voice_gateway.adapters.lifeos import LifeOSError

router = APIRouter(prefix="/api/voice/conversations", tags=["conversations"])


def _lifeos(request: Request):
    return request.app.state.lifeos_client


@router.get("")
async def list_conversations(request: Request) -> dict:
    try:
        return await _lifeos(request).list_conversations()
    except LifeOSError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str, request: Request) -> dict:
    try:
        return await _lifeos(request).get_conversation(conversation_id)
    except LifeOSError as exc:
        status = 404 if "404" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
