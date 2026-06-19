"""Voice turn pipeline orchestration."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any
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

    async def warmup(self) -> None:
        await self._stt.warmup()
        await self._tts.warmup()

    async def run_turn(
        self,
        audio_bytes: bytes | None,
        *,
        content_type: str | None,
        filename: str | None,
        conversation_id: str | None,
        client_transcript: str | None = None,
    ) -> VoiceTurnResponse:
        response: VoiceTurnResponse | None = None
        async for event in self.run_turn_stream(
            audio_bytes,
            content_type=content_type,
            filename=filename,
            conversation_id=conversation_id,
            client_transcript=client_transcript,
        ):
            if event["type"] == "done":
                response = VoiceTurnResponse(**event["data"])
            elif event["type"] == "error":
                raise TurnError(event["message"], event.get("status_code", 500))
        if response is None:
            raise TurnError("turn ended without response")
        return response

    async def run_turn_stream(
        self,
        audio_bytes: bytes | None,
        *,
        content_type: str | None,
        filename: str | None,
        conversation_id: str | None,
        client_transcript: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        turn_id = str(uuid4())
        t_start = time.monotonic()
        timings = TimingsMs()
        status_audio_urls: list[str] = []
        status_idx = 0

        log_event(logger, "turn_started", turn_id=turn_id)
        yield {"type": "started", "turn_id": turn_id}

        try:
            if client_transcript and client_transcript.strip():
                transcript = client_transcript.strip()
            elif audio_bytes:
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
            else:
                raise TurnError("audio or transcript required", 400)

            if not transcript.strip():
                raise TurnError("no speech detected", 400)

            yield {"type": "transcript", "text": transcript}

            tts_total_ms = 0
            event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

            async def on_status(message: str) -> None:
                nonlocal status_idx, tts_total_ms
                clip_id = f"status-{status_idx}"
                status_idx += 1
                out = self._storage.clip_path(turn_id, clip_id)
                t_s = time.monotonic()
                await self._tts.synthesize(message, turn_id=turn_id, out_path=out, clip_id=clip_id)
                tts_total_ms += int((time.monotonic() - t_s) * 1000)
                url = f"/api/voice/audio/{turn_id}/{clip_id}"
                status_audio_urls.append(url)
                await event_queue.put({"type": "status_audio", "url": url, "message": message})

            async def run_lifeos() -> None:
                try:
                    t0 = time.monotonic()
                    result = await self._lifeos.ask(
                        transcript,
                        conversation_id=conversation_id,
                        turn_id=turn_id,
                        on_status=on_status,
                    )
                    timings.lifeos = int((time.monotonic() - t0) * 1000)
                    await event_queue.put({"type": "_lifeos_done", "result": result})
                except Exception as exc:
                    await event_queue.put({"type": "_lifeos_error", "error": exc})
                finally:
                    await event_queue.put(None)

            lifeos_task = asyncio.create_task(run_lifeos())
            lifeos_result = None
            while True:
                item = await event_queue.get()
                if item is None:
                    break
                if item["type"] == "_lifeos_done":
                    lifeos_result = item["result"]
                    continue
                if item["type"] == "_lifeos_error":
                    err = item["error"]
                    if isinstance(err, LifeOSError):
                        raise TurnError(str(err), 502) from err
                    raise err
                yield item

            await lifeos_task
            if lifeos_result is None:
                raise TurnError("LifeOS did not return a response", 502)

            response_text = lifeos_result.answer or "No response generated."
            yield {"type": "response", "text": response_text}

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

            audio_url = f"/api/voice/audio/{turn_id}"
            yield {"type": "main_audio", "url": audio_url}

            response = VoiceTurnResponse(
                turn_id=turn_id,
                transcript=transcript,
                response_text=response_text,
                audio_url=audio_url,
                status_audio_urls=status_audio_urls,
                conversation_id=lifeos_result.conversation_id,
                handoff=handoff_info,
                timings_ms=timings,
            )

            meta = {
                "turn_id": turn_id,
                "transcript": transcript,
                "response_text": response_text,
                "conversation_id": lifeos_result.conversation_id,
                "status_audio_urls": status_audio_urls,
                "audio_url": audio_url,
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

            yield {"type": "done", "data": response.model_dump()}
        except TurnError as exc:
            yield {
                "type": "error",
                "message": str(exc),
                "status_code": exc.status_code,
            }
