"""Speech-to-text via linux-whisper (STT + polish)."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol, runtime_checkable

import numpy as np

from voice_gateway.audio import pcm_to_float32
from voice_gateway.config import Settings

logger = logging.getLogger(__name__)


@runtime_checkable
class STTAdapter(Protocol):
    async def transcribe(self, pcm_bytes: bytes, *, turn_id: str) -> tuple[str, dict[str, int]]: ...


class LinuxWhisperSTTAdapter:
    """STT + full polish pipeline — desktop parity."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = None
        self._polish = None
        self._config = None
        self._lock = asyncio.Lock()

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

    def _transcribe_sync(self, pcm_bytes: bytes) -> tuple[str, dict[str, int]]:
        import time

        self._ensure_loaded()
        assert self._engine is not None

        t0 = time.monotonic()
        audio_float = pcm_to_float32(pcm_bytes)
        if len(audio_float) == 0:
            return "", {"stt_ms": 0, "polish_ms": 0}

        audio_int16 = (audio_float * 32767).astype(np.int16)
        audio_bytes = audio_int16.tobytes()

        self._engine.start_stream()
        self._engine.feed_audio(audio_bytes)
        result = self._engine.finalize()
        self._engine.reset()
        stt_ms = int((time.monotonic() - t0) * 1000)

        text = (result.full_text or "").strip()
        if not text:
            return "", {"stt_ms": stt_ms, "polish_ms": 0}

        polish_ms = 0
        if self._polish is not None:
            t1 = time.monotonic()
            text = self._polish.process(text, app_context=None)
            polish_ms = int((time.monotonic() - t1) * 1000)

        return text, {"stt_ms": stt_ms, "polish_ms": polish_ms}

    async def transcribe(self, pcm_bytes: bytes, *, turn_id: str) -> tuple[str, dict[str, int]]:
        async with self._lock:
            return await asyncio.to_thread(self._transcribe_sync, pcm_bytes)


class StubSTTAdapter:
    def __init__(self, transcript: str = "hello world") -> None:
        self.transcript = transcript

    async def transcribe(self, pcm_bytes: bytes, *, turn_id: str) -> tuple[str, dict[str, int]]:
        return self.transcript, {"stt_ms": 1, "polish_ms": 0}
