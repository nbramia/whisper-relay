"""Text-to-speech adapters — Kokoro and null stub."""

from __future__ import annotations

import asyncio
import logging
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from voice_gateway.config import Settings
from voice_gateway.text import strip_markdown_for_tts

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TTSResult:
    path: Path
    mime_type: str
    duration_s: float
    backend: str


@runtime_checkable
class TTSAdapter(Protocol):
    async def synthesize(
        self,
        text: str,
        *,
        turn_id: str,
        out_path: Path,
        clip_id: str = "main",
    ) -> TTSResult: ...

    async def warmup(self) -> None: ...


def _write_silent_wav(path: Path, duration_s: float = 0.25, sample_rate: int = 24_000) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(sample_rate * duration_s)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return duration_s


class NullTTSAdapter:
    """CI / dev stub — no Kokoro models required."""

    async def synthesize(
        self,
        text: str,
        *,
        turn_id: str,
        out_path: Path,
        clip_id: str = "main",
    ) -> TTSResult:
        clean = strip_markdown_for_tts(text)
        duration = min(0.5, 0.05 + len(clean) * 0.02)
        dur = await asyncio.to_thread(_write_silent_wav, out_path, duration)
        return TTSResult(path=out_path, mime_type="audio/wav", duration_s=dur, backend="null")

    async def warmup(self) -> None:
        return


class KokoroTTSAdapter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._kokoro = None
        self._lock = asyncio.Lock()

    def _ensure_loaded(self) -> None:
        if self._kokoro is not None:
            return
        model = self._settings.kokoro_model_path
        voices = self._settings.kokoro_voices_path
        if not model.is_file():
            raise FileNotFoundError(f"Kokoro model not found: {model}")
        if not voices.is_file():
            raise FileNotFoundError(f"Kokoro voices not found: {voices}")

        from kokoro_onnx import Kokoro

        self._kokoro = Kokoro(str(model), str(voices))
        logger.info("Kokoro TTS loaded voice=%s", self._settings.kokoro_voice)

    def _synthesize_sync(self, text: str, out_path: Path) -> TTSResult:
        import soundfile as sf

        self._ensure_loaded()
        assert self._kokoro is not None

        clean = strip_markdown_for_tts(text)
        if not clean:
            dur = _write_silent_wav(out_path, 0.1)
            return TTSResult(path=out_path, mime_type="audio/wav", duration_s=dur, backend="kokoro")

        t0 = time.monotonic()
        samples, sample_rate = self._kokoro.create(
            clean,
            voice=self._settings.kokoro_voice,
            speed=self._settings.kokoro_speed,
            lang=self._settings.kokoro_lang,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out_path), samples, sample_rate)
        duration_s = len(samples) / float(sample_rate)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.debug("kokoro synthesized %d chars in %dms", len(clean), elapsed_ms)
        return TTSResult(
            path=out_path,
            mime_type="audio/wav",
            duration_s=duration_s,
            backend="kokoro",
        )

    async def synthesize(
        self,
        text: str,
        *,
        turn_id: str,
        out_path: Path,
        clip_id: str = "main",
    ) -> TTSResult:
        async with self._lock:
            return await asyncio.to_thread(self._synthesize_sync, text, out_path)

    async def warmup(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._ensure_loaded)


def build_tts_adapter(settings: Settings) -> TTSAdapter:
    backend = settings.tts_backend.lower()
    if backend == "null":
        return NullTTSAdapter()
    if backend == "kokoro":
        return KokoroTTSAdapter(settings)
    raise ValueError(f"unknown TTS_BACKEND: {settings.tts_backend}")
