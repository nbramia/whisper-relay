"""Voice API routes."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from voice_gateway.models import VoiceTurnResponse
from voice_gateway.turns import TurnError, TurnPipeline

router = APIRouter(prefix="/api/voice", tags=["voice"])


def _get_pipeline(request: Request) -> TurnPipeline:
    return request.app.state.pipeline


def _get_storage(request: Request):
    return request.app.state.storage


@router.post("/turn", response_model=VoiceTurnResponse)
async def voice_turn(
    request: Request,
    audio: UploadFile = File(...),
    conversation_id: str | None = Form(default=None),
) -> VoiceTurnResponse:
    settings = request.app.state.settings
    raw = await audio.read()
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="upload too large")

    pipeline = _get_pipeline(request)
    try:
        return await pipeline.run_turn(
            raw,
            content_type=audio.content_type,
            filename=audio.filename,
            conversation_id=conversation_id or None,
        )
    except TurnError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/audio/{turn_id}")
async def get_main_audio(turn_id: str, request: Request) -> FileResponse:
    return _serve_clip(turn_id, "main", request)


@router.get("/audio/{turn_id}/{clip_id}")
async def get_clip_audio(turn_id: str, clip_id: str, request: Request) -> FileResponse:
    return _serve_clip(turn_id, clip_id, request)


def _serve_clip(turn_id: str, clip_id: str, request: Request) -> FileResponse:
    try:
        UUID(turn_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="turn not found") from exc

    storage = _get_storage(request)
    path: Path = storage.clip_path(turn_id, clip_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="audio not found")
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Cache-Control": "private, max-age=3600"},
    )
