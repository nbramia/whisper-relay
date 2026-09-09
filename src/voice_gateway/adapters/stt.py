"""Speech-to-text via linux-whisper (STT + polish)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from voice_gateway.audio import pcm_to_float32
from voice_gateway.config import Settings

logger = logging.getLogger(__name__)


class STTUnavailableError(RuntimeError):
    """The engine failed without producing a recognition result."""


class STTDeadlineExceededError(STTUnavailableError):
    """The engine invalidated its worker after a bounded IPC deadline."""


@runtime_checkable
class STTAdapter(Protocol):
    async def transcribe(self, pcm_bytes: bytes, *, turn_id: str) -> tuple[str, dict[str, int]]: ...

    async def warmup(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RawSegment:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class DetailedTranscription:
    raw_text: str
    segments: tuple[RawSegment, ...]
    language: str | None
    confidence: float | None
    duration_ms: int
    backend: str
    model: str
    library: str
    revision: str | None
    stt_ms: int
    polished_text: str | None = None
    polish_ms: int = 0


@runtime_checkable
class DetailedSTTAdapter(Protocol):
    """Additive raw-result capability used only by the trusted local capture route."""

    @property
    def is_ready(self) -> bool: ...

    async def transcribe_detailed(
        self,
        pcm_bytes: bytes,
        *,
        turn_id: str,
        include_polished: bool,
    ) -> DetailedTranscription: ...

    async def try_transcribe_detailed(
        self,
        pcm_bytes: bytes,
        *,
        turn_id: str,
        include_polished: bool,
    ) -> DetailedTranscription | None: ...


class LinuxWhisperSTTAdapter:
    """STT + full polish pipeline — desktop parity."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = None
        self._polish = None
        self._config = None
        self._lock = asyncio.Lock()
        self._is_ready = False

    @property
    def is_ready(self) -> bool:
        return self._is_ready

    def _ensure_loaded(self) -> None:
        if self._engine is not None:
            return
        from linux_whisper.config import Config
        from linux_whisper.polish.pipeline import PolishPipeline
        from linux_whisper.stt.engine import create_engine

        if self._settings.linux_whisper_config:
            self._config = Config.load(self._settings.linux_whisper_config)
        else:
            self._config = Config.load()

        self._engine = create_engine(self._config)
        if self._config.polish.enabled:
            self._polish = PolishPipeline(self._config.polish)
        logger.info("linux-whisper STT engine loaded: %s", self._config.stt.backend)

    def _transcribe_raw_sync(self, pcm_bytes: bytes) -> DetailedTranscription:
        self._ensure_loaded()
        assert self._engine is not None
        assert self._config is not None

        t0 = time.monotonic()
        audio_float = pcm_to_float32(pcm_bytes)
        if len(audio_float) == 0:
            return DetailedTranscription(
                raw_text="",
                segments=(),
                language=None,
                confidence=None,
                duration_ms=0,
                backend=self._config.stt.backend,
                model=self._config.stt.model,
                library="linux-whisper",
                revision=None,
                stt_ms=0,
            )

        audio_int16 = (audio_float * 32767).astype(np.int16)
        audio_bytes = audio_int16.tobytes()

        set_timeout = getattr(self._engine, "set_operation_timeout", None)
        if callable(set_timeout):
            set_timeout(self._settings.stt_timeout_s)
        try:
            self._engine.start_stream()
            self._engine.feed_audio(audio_bytes)
            result = self._engine.finalize()
        except Exception as exc:
            self._is_ready = False
            if exc.__class__.__name__ == "GPUWorkerTimeoutError":
                raise STTDeadlineExceededError("STT operation exceeded its deadline") from exc
            raise STTUnavailableError("STT engine failed") from exc
        finally:
            self._engine.reset()
        stt_ms = int((time.monotonic() - t0) * 1000)
        self._is_ready = True

        return DetailedTranscription(
            raw_text=(result.full_text or "").strip(),
            segments=tuple(
                RawSegment(
                    text=segment.text,
                    start_ms=round(segment.start_time * 1000),
                    end_ms=round(segment.end_time * 1000),
                )
                for segment in result.segments
            ),
            language=result.language,
            confidence=None,
            duration_ms=round(result.duration * 1000),
            backend=self._config.stt.backend,
            model=self._config.stt.model,
            library="linux-whisper",
            revision=None,
            stt_ms=stt_ms,
        )

    def _transcribe_detailed_sync(
        self,
        pcm_bytes: bytes,
        *,
        include_polished: bool,
    ) -> DetailedTranscription:
        raw = self._transcribe_raw_sync(pcm_bytes)
        if not include_polished or not raw.raw_text or self._polish is None:
            return raw

        t0 = time.monotonic()
        polished = self._polish.process(raw.raw_text, app_context=None)
        return DetailedTranscription(
            raw_text=raw.raw_text,
            segments=raw.segments,
            language=raw.language,
            confidence=raw.confidence,
            duration_ms=raw.duration_ms,
            backend=raw.backend,
            model=raw.model,
            library=raw.library,
            revision=raw.revision,
            stt_ms=raw.stt_ms,
            polished_text=polished,
            polish_ms=int((time.monotonic() - t0) * 1000),
        )

    async def transcribe_detailed(
        self,
        pcm_bytes: bytes,
        *,
        turn_id: str,
        include_polished: bool,
    ) -> DetailedTranscription:
        async with self._lock:
            return await asyncio.to_thread(
                self._transcribe_detailed_sync,
                pcm_bytes,
                include_polished=include_polished,
            )

    async def try_transcribe_detailed(
        self,
        pcm_bytes: bytes,
        *,
        turn_id: str,
        include_polished: bool,
    ) -> DetailedTranscription | None:
        if self._lock.locked():
            return None
        async with self._lock:
            return await asyncio.to_thread(
                self._transcribe_detailed_sync,
                pcm_bytes,
                include_polished=include_polished,
            )

    async def transcribe(self, pcm_bytes: bytes, *, turn_id: str) -> tuple[str, dict[str, int]]:
        result = await self.transcribe_detailed(
            pcm_bytes,
            turn_id=turn_id,
            include_polished=True,
        )
        text = result.polished_text if result.polished_text is not None else result.raw_text
        return text, {"stt_ms": result.stt_ms, "polish_ms": result.polish_ms}

    def _warmup_sync(self) -> None:
        self._ensure_loaded()
        assert self._engine is not None
        # `create_engine` alone does not load the GPU subprocess model. Starting
        # and resetting a no-audio stream proves readiness without inference.
        self._engine.start_stream()
        self._engine.reset()
        self._is_ready = True

    async def warmup(self) -> None:
        async with self._lock:
            self._is_ready = False
            await asyncio.to_thread(self._warmup_sync)


class StubSTTAdapter:
    def __init__(self, transcript: str = "hello world") -> None:
        self.transcript = transcript

    @property
    def is_ready(self) -> bool:
        return True

    async def transcribe(self, pcm_bytes: bytes, *, turn_id: str) -> tuple[str, dict[str, int]]:
        return self.transcript, {"stt_ms": 1, "polish_ms": 0}

    async def transcribe_detailed(
        self,
        pcm_bytes: bytes,
        *,
        turn_id: str,
        include_polished: bool,
    ) -> DetailedTranscription:
        return DetailedTranscription(
            raw_text=self.transcript,
            segments=(),
            language=None,
            confidence=None,
            duration_ms=round(len(pcm_bytes) / (16_000 * 2) * 1000),
            backend="stub",
            model="stub",
            library="linux-whisper",
            revision=None,
            stt_ms=1,
            polished_text=self.transcript if include_polished else None,
        )

    async def try_transcribe_detailed(
        self,
        pcm_bytes: bytes,
        *,
        turn_id: str,
        include_polished: bool,
    ) -> DetailedTranscription | None:
        return await self.transcribe_detailed(
            pcm_bytes,
            turn_id=turn_id,
            include_polished=include_polished,
        )

    async def warmup(self) -> None:
        return
