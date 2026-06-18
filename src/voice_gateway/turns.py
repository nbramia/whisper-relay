"""Voice turn pipeline orchestration."""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from voice_gateway.adapters.lifeos import LifeOSClient, LifeOSError
from voice_gateway.adapters.stt import STTAdapter
from voice_gateway.adapters.tts import TTSAdapter
from voice_gateway.audio import AudioNormalizationError, normalize_audio
from voice_gateway.config import Settings
from voice_gateway.logging import log_event
from voice_gateway.models import HandoffInfo, TimingsMs, VoiceTurnResponse
from voice_gateway.storage import TurnStorage

logger = logging.getLogger(__name__)


class TurnError(Exception):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


class TurnPipeline:
    def __init__(
        self,
        settings: Settings,
        storage: TurnStorage,
        stt: STTAdapter,
        lifeos: LifeOSClient,
        tts: TTSAdapter,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._stt = stt
        self._lifeos = lifeos
        self._tts = tts

    async def run_turn(
        self,
        audio_bytes: bytes,
        *,
        content_type: str | None,
        filename: str | None,
        conversation_id: str | None,
    ) -> VoiceTurnResponse:
        turn_id = str(uuid4())
        t_start = time.monotonic()
        timings = TimingsMs()
        status_audio_urls: list[str] = []
        status_idx = 0

        log_event(logger, "turn_started", turn_id=turn_id)

        t0 = time.monotonic()
        try:
            normalized = normalize_audio(
                audio_bytes,
                content_type=content_type,
                filename=filename,
                ffmpeg_bin=self._settings.ffmpeg_bin,
                max_duration_s=self._settings.max_audio_duration_s,
            )
        except AudioNormalizationError as exc:
            raise TurnError(str(exc), 400) from exc
        timings.normalize = int((time.monotonic() - t0) * 1000)

        t0 = time.monotonic()
        try:
            transcript, stt_timings = await self._stt.transcribe(
                normalized.pcm_bytes, turn_id=turn_id
            )
        except Exception as exc:
            logger.exception("STT failed turn_id=%s", turn_id)
            raise TurnError("STT engine unavailable", 503) from exc
        timings.stt = stt_timings.get("stt_ms", int((time.monotonic() - t0) * 1000))
        timings.polish = stt_timings.get("polish_ms", 0)

        if not transcript.strip():
            raise TurnError("no speech detected in audio", 400)

        tts_total_ms = 0

        async def on_status(message: str) -> None:
            nonlocal status_idx, tts_total_ms
            clip_id = f"status-{status_idx}"
            status_idx += 1
            out = self._storage.clip_path(turn_id, clip_id)
            t_s = time.monotonic()
            await self._tts.synthesize(message, turn_id=turn_id, out_path=out, clip_id=clip_id)
            tts_total_ms += int((time.monotonic() - t_s) * 1000)
            status_audio_urls.append(f"/api/voice/audio/{turn_id}/{clip_id}")

        t0 = time.monotonic()
        try:
            lifeos_result = await self._lifeos.ask(
                transcript,
                conversation_id=conversation_id,
                turn_id=turn_id,
                on_status=on_status,
            )
        except LifeOSError as exc:
            raise TurnError(str(exc), 502) from exc
        timings.lifeos = int((time.monotonic() - t0) * 1000)

        response_text = lifeos_result.answer or "No response generated."

        t0 = time.monotonic()
        main_path = self._storage.clip_path(turn_id, "main")
        await self._tts.synthesize(
            response_text, turn_id=turn_id, out_path=main_path, clip_id="main"
        )
        tts_total_ms += int((time.monotonic() - t0) * 1000)
        timings.tts = tts_total_ms
        timings.total = int((time.monotonic() - t_start) * 1000)

        handoff_info = None
        if lifeos_result.handoff:
            h = lifeos_result.handoff
            handoff_info = HandoffInfo(
                engine=h.engine,
                task=h.task,
                message=h.message,
                session_id=h.session_id,
            )

        meta = {
            "turn_id": turn_id,
            "transcript": transcript,
            "response_text": response_text,
            "conversation_id": lifeos_result.conversation_id,
            "status_audio_urls": status_audio_urls,
            "audio_url": f"/api/voice/audio/{turn_id}",
            "handoff": handoff_info.model_dump() if handoff_info else None,
            "timings_ms": timings.model_dump(),
        }
        self._storage.write_meta(turn_id, meta)

        log_event(
            logger,
            "turn_completed",
            turn_id=turn_id,
            duration_ms=timings.total,
            stt_ms=timings.stt,
            lifeos_ms=timings.lifeos,
            tts_ms=timings.tts,
        )

        return VoiceTurnResponse(
            turn_id=turn_id,
            transcript=transcript,
            response_text=response_text,
            audio_url=f"/api/voice/audio/{turn_id}",
            status_audio_urls=status_audio_urls,
            conversation_id=lifeos_result.conversation_id,
            handoff=handoff_info,
            timings_ms=timings,
        )
