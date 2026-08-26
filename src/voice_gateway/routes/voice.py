"""Voice API routes."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from voice_gateway.adapters.lifeos import (
    handoff_override_for_model,
    normalize_model_override,
    persona_supports_handoff,
)
from voice_gateway.adapters.text_backend import (
    TextBackendUnavailableError,
    capabilities_for,
    normalize_backend,
)
from voice_gateway.audio import AudioNormalizationError, normalize_audio
from voice_gateway.cancel import TurnRegistry
from voice_gateway.models import VoiceTurnResponse
from voice_gateway.turns import TurnError, TurnPipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])


def _personas_cache(request: Request) -> list[dict]:
    cached = getattr(request.app.state, "lifeos_personas", None) or {}
    personas = cached.get("personas")
    if personas:
        return personas
    return [{"id": "primary", "label": "LifeOS", "capabilities": ["handoff", "agent"]}]


def _resolve_persona_id(backend: str, persona_id: str | None) -> str | None:
    """Persona for backends that accept one; None for the context-poor ones."""
    if not capabilities_for(backend).persona:
        return None
    return (persona_id or "primary").strip() or "primary"


def _parse_handoff_enabled(
    request: Request,
    backend: str,
    persona_id: str | None,
    model_override: str | None = None,
) -> bool:
    if not capabilities_for(backend).handoff:
        return False
    if handoff_override_for_model(model_override):
        return True
    pid = (persona_id or "primary").strip() or "primary"
    return persona_supports_handoff(_personas_cache(request), pid)


def _get_pipeline(request: Request) -> TurnPipeline:
    return request.app.state.pipeline


def _get_storage(request: Request):
    return request.app.state.storage


@router.post("/transcribe")
async def voice_transcribe(
    request: Request,
    audio: UploadFile | None = File(default=None),
) -> dict[str, str]:
    """Bare STT for the "Listening" wake-word check (LifeOS #710).

    Deliberately stops after normalize + transcribe: no LLM call, no TTS, no
    turn registry entry, no storage write, no SSE — a wake check must never
    look like a turn to anything downstream, including LifeOS #711's
    persistence tee (which keys off `turn/stream`'s `done` events, never
    emitted here).
    """
    if audio is None or not audio.filename:
        raise HTTPException(status_code=400, detail="audio required")

    settings = request.app.state.settings
    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="audio required")
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="upload too large")

    try:
        normalized = normalize_audio(
            raw,
            content_type=audio.content_type,
            filename=audio.filename,
            ffmpeg_bin=settings.ffmpeg_bin,
            max_duration_s=settings.max_audio_duration_s,
        )
    except AudioNormalizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stt = _get_pipeline(request).stt
    try:
        transcript, _ = await stt.transcribe(normalized.pcm_bytes, turn_id=str(uuid4()))
    except Exception as exc:
        logger.exception("wake-check STT failed")
        raise HTTPException(status_code=503, detail="STT engine unavailable") from exc

    return {"transcript": transcript}


async def _read_turn_upload(
    request: Request,
    audio: UploadFile | None,
    transcript: str | None,
    conversation_id: str | None,
) -> tuple[bytes | None, str | None, str | None, str | None, str | None]:
    settings = request.app.state.settings
    client_transcript = transcript.strip() if transcript else None
    raw: bytes | None = None
    content_type: str | None = None
    filename: str | None = None

    if audio is not None and audio.filename:
        raw = await audio.read()
        content_type = audio.content_type
        filename = audio.filename
        if len(raw) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="upload too large")

    if not client_transcript and not raw:
        raise HTTPException(status_code=400, detail="audio or transcript required")

    return raw, content_type, filename, conversation_id or None, client_transcript


@router.post("/turn", response_model=VoiceTurnResponse)
async def voice_turn(
    request: Request,
    audio: UploadFile | None = File(default=None),
    transcript: str | None = Form(default=None),
    conversation_id: str | None = Form(default=None),
    backend: str = Form(default="lifeos"),
    persona_id: str | None = Form(default=None),
    model_override: str | None = Form(default=None),
) -> VoiceTurnResponse:
    pipeline = _get_pipeline(request)
    raw, content_type, filename, conv_id, client_transcript = await _read_turn_upload(
        request, audio, transcript, conversation_id
    )
    backend_kind = normalize_backend(backend)
    pid = _resolve_persona_id(backend_kind, persona_id)
    model = normalize_model_override(model_override)

    try:
        return await pipeline.run_turn(
            raw,
            content_type=content_type,
            filename=filename,
            conversation_id=conv_id,
            client_transcript=client_transcript,
            backend=backend_kind,
            persona_id=pid,
            model_override=model,
            parse_handoff=_parse_handoff_enabled(request, backend_kind, pid, model),
        )
    except TurnError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/turn/stream")
async def voice_turn_stream(
    request: Request,
    audio: UploadFile | None = File(default=None),
    transcript: str | None = Form(default=None),
    conversation_id: str | None = Form(default=None),
    backend: str = Form(default="lifeos"),
    persona_id: str | None = Form(default=None),
    model_override: str | None = Form(default=None),
) -> StreamingResponse:
    pipeline = _get_pipeline(request)
    raw, content_type, filename, conv_id, client_transcript = await _read_turn_upload(
        request, audio, transcript, conversation_id
    )
    backend_kind = normalize_backend(backend)
    pid = _resolve_persona_id(backend_kind, persona_id)
    model = normalize_model_override(model_override)
    parse_handoff = _parse_handoff_enabled(request, backend_kind, pid, model)

    async def event_stream():
        registry: TurnRegistry = request.app.state.turn_registry
        async for event in pipeline.run_turn_stream(
            raw,
            content_type=content_type,
            filename=filename,
            conversation_id=conv_id,
            client_transcript=client_transcript,
            registry=registry,
            backend=backend_kind,
            persona_id=pid,
            model_override=model,
            parse_handoff=parse_handoff,
        ):
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") in {"done", "error", "cancelled"}:
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def _cancel_upstream(request: Request, backend: str | None, turn_id: str) -> None:
    """Tell the backend to stop, for backends that accept an explicit cancel.

    Best effort by design: the local cancel has already succeeded by the time this
    runs, so nothing here may turn a clean cancel into an error. Fired from the
    route rather than the SSE read loop, which only notices the cancel flag between
    lines — a quiet stream would otherwise delay the call (issue #37).
    """
    if backend is None or not capabilities_for(backend).explicit_cancel:
        return

    router_state = getattr(request.app.state, "text_backend_router", None)
    if router_state is None:
        return
    try:
        client = router_state.client_for(backend)
    except TextBackendUnavailableError:
        return

    cancel_turn = getattr(client, "cancel_turn", None)
    if cancel_turn is None:
        return

    try:
        stopped = await cancel_turn(turn_id)
    except Exception:
        # Unreachable backend, 422, malformed body: the turn is cancelled locally
        # either way, and the caller gets its normal answer.
        logger.warning("upstream cancel failed turn_id=%s backend=%s", turn_id, backend)
        return
    # cancelled: false means nothing was in flight — a normal outcome, not a failure.
    logger.info("upstream cancel turn_id=%s backend=%s stopped=%s", turn_id, backend, stopped)


@router.post("/turn/{turn_id}/cancel")
async def cancel_voice_turn(turn_id: str, request: Request) -> dict[str, bool]:
    registry: TurnRegistry = request.app.state.turn_registry
    backend = registry.backend_for(turn_id)
    if not registry.cancel(turn_id):
        raise HTTPException(status_code=404, detail="turn not found or already finished")
    await _cancel_upstream(request, backend, turn_id)
    return {"cancelled": True}


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
