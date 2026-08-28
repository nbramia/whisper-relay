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
    TextBackendRouter,
    TextBackendUnavailableError,
    capabilities_for,
    normalize_backend,
)
from voice_gateway.audio import AudioNormalizationError, normalize_audio
from voice_gateway.cancel import TurnRegistry, TurnTenantMismatchError
from voice_gateway.models import VoiceTurnResponse
from voice_gateway.tenants import TENANT_TOKEN_HEADER, TenantRegistry
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


def _resolve_tenant_and_router(request: Request) -> tuple[str | None, TextBackendRouter]:
    """Which tenant this request belongs to, and that tenant's backend targets (#40).

    Single-tenant mode (the default — no TENANT_BACKENDS_JSON configured) returns
    (None, the one process-wide router) unchanged: today's two production
    deployments never reach any of the code below. Once per-tenant routing is
    configured, a request must present a token matching a configured tenant in
    the TENANT_TOKEN_HEADER header — an inbound value the operator's own network
    boundary controls, never a client-suppliable free-text field. A missing or
    unrecognized token is rejected outright; there is no fallback to the
    process-wide router for an ambiguous or unset tenant.
    """
    registry: TenantRegistry = request.app.state.tenant_registry
    if not registry.enabled:
        return None, request.app.state.text_backend_router

    resolved = registry.resolve(request.headers.get(TENANT_TOKEN_HEADER))
    if resolved is None:
        logger.warning(
            "voice turn rejected: missing or unrecognized tenant token (%s)",
            TENANT_TOKEN_HEADER,
        )
        raise HTTPException(status_code=403, detail="unknown or missing tenant")
    return resolved.tenant_id, resolved.router


def _resolve_text_backend_router(request: Request) -> TextBackendRouter:
    _tenant_id, router = _resolve_tenant_and_router(request)
    return router


def _resolve_tenant(request: Request) -> str | None:
    """Caller's tenant id, or None in single-tenant mode. Raises 403 (via
    `_resolve_tenant_and_router`) in multi-tenant mode when unresolved."""
    tenant_id, _router = _resolve_tenant_and_router(request)
    return tenant_id


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
    tenant_id, text_backend_router = _resolve_tenant_and_router(request)
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
            text_backend=text_backend_router,
            tenant_id=tenant_id,
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
    tenant_id, text_backend_router = _resolve_tenant_and_router(request)
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
            text_backend=text_backend_router,
            tenant_id=tenant_id,
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

    try:
        router_state = _resolve_text_backend_router(request)
    except HTTPException:
        # Same fail-closed tenant check as the turn itself (#40), but best-effort
        # here: the local cancel already succeeded, so a missing/unrecognized
        # tenant token on the cancel call just means the upstream call is skipped.
        logger.warning("upstream cancel skipped: tenant unresolved turn_id=%s", turn_id)
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
    """Resolves the caller's tenant *before* touching the turn registry (#48):
    the old order let any caller — one tenant's token, or none at all — cancel
    another tenant's in-flight turn by id, since the registry check ran first
    and ids share one flat namespace. `_resolve_tenant` 403s on an unresolved
    tenant in multi-tenant mode; single-tenant mode is unaffected (tenant_id is
    always None, matching every entry `start()` recorded).
    """
    tenant_id = _resolve_tenant(request)
    registry: TurnRegistry = request.app.state.turn_registry
    try:
        cancelled = registry.cancel(turn_id, tenant_id)
    except TurnTenantMismatchError as exc:
        # A caller can never cancel, or reach any detail of, a turn it
        # doesn't own — that's the property #48 requires. The 403-vs-404
        # split between this branch and the "no such turn" 404 below does let
        # a caller with a valid tenant token distinguish "that id belongs to
        # someone else" from "that id doesn't exist" for a turn_id it already
        # has in hand; turn ids are unguessable UUIDv4s (never enumerable),
        # so this is the same accepted-low-risk gap the review calls out for
        # the token-guessing case, not a new one.
        raise HTTPException(status_code=403, detail="turn not found or already finished") from exc
    if not cancelled:
        raise HTTPException(status_code=404, detail="turn not found or already finished")
    backend = registry.backend_for(turn_id, tenant_id)
    await _cancel_upstream(request, backend, turn_id)
    return {"cancelled": True}


@router.get("/audio/{turn_id}")
async def get_main_audio(turn_id: str, request: Request) -> FileResponse:
    return _serve_clip(turn_id, "main", request)


@router.get("/audio/{turn_id}/{clip_id}")
async def get_clip_audio(turn_id: str, clip_id: str, request: Request) -> FileResponse:
    return _serve_clip(turn_id, clip_id, request)


def _serve_clip(turn_id: str, clip_id: str, request: Request) -> FileResponse:
    """Resolves the caller's tenant *before* touching storage (#50), the same
    order cancel uses (#48): in multi-tenant mode, a missing or unrecognized
    token 403s via `_resolve_tenant` before `turn_id` is even validated.

    Single-tenant mode (`tenant_registry.enabled` is False) skips this block
    entirely and falls straight through to the pre-#50 checks — byte-identical
    to today for both running production instances.
    """
    registry: TenantRegistry = request.app.state.tenant_registry
    storage = _get_storage(request)
    # Token resolution happens even before `turn_id` is validated as a UUID —
    # a missing/unrecognized token 403s regardless of what turn_id was asked for.
    tenant_id = _resolve_tenant(request) if registry.enabled else None

    try:
        UUID(turn_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="turn not found") from exc

    # A clip with no recorded tenant — single-tenant-written before a mode
    # switch, or any other legacy clip — is never servable to anyone once
    # multi-tenant mode is on: `read_tenant_id` returns None, which can never
    # equal a resolved (always non-None) tenant_id, so it fails closed without
    # a special case. Same disclosure as cancel: a mismatch gets 403 with the
    # *same detail* as "doesn't exist", not a 404, so a caller holding a
    # turn_id it doesn't own learns nothing new.
    if registry.enabled and storage.read_tenant_id(turn_id) != tenant_id:
        raise HTTPException(status_code=403, detail="audio not found")

    path: Path = storage.clip_path(turn_id, clip_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="audio not found")
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Cache-Control": "private, max-age=3600"},
    )
