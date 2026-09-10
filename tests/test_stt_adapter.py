from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from linux_whisper.stt.engine import TranscriptResult, TranscriptSegment

from voice_gateway.adapters.stt import (
    DetailedTranscription,
    LinuxWhisperSTTAdapter,
    STTDeadlineExceededError,
)


def _adapter(tmp_settings) -> LinuxWhisperSTTAdapter:
    adapter = LinuxWhisperSTTAdapter(tmp_settings)
    adapter._config = SimpleNamespace(
        stt=SimpleNamespace(backend="whisper-cpp", model="synthetic-model"),
    )
    return adapter


def test_warmup_starts_and_resets_engine_without_inference(tmp_settings):
    adapter = _adapter(tmp_settings)
    engine = MagicMock()
    adapter._engine = engine

    adapter._warmup_sync()

    engine.start_stream.assert_called_once_with()
    engine.reset.assert_called_once_with()
    engine.finalize.assert_not_called()
    assert adapter.is_ready is True


def test_detailed_transcription_keeps_raw_before_optional_polish(tmp_settings):
    adapter = _adapter(tmp_settings)
    engine = MagicMock()
    engine.finalize.return_value = TranscriptResult(
        full_text="raw words",
        segments=[TranscriptSegment(text="raw words", start_time=0.0, end_time=0.5)],
        duration=0.5,
    )
    adapter._engine = engine
    polish = MagicMock()
    polish.process.return_value = "Polished words."
    adapter._polish = polish

    result = adapter._transcribe_detailed_sync(
        b"\x00\x00" * 8_000,
        include_polished=True,
    )

    assert result.raw_text == "raw words"
    assert result.polished_text == "Polished words."
    assert result.segments[0].start_ms == 0
    assert result.segments[0].end_ms == 500
    engine.set_operation_timeout.assert_called_once_with(tmp_settings.stt_timeout_s)
    engine.reset.assert_called_once_with()


def test_upstream_reaped_worker_deadline_maps_to_relay_deadline(tmp_settings):
    from linux_whisper.stt.whisper_gpu import GPUWorkerTimeoutError

    adapter = _adapter(tmp_settings)
    engine = MagicMock()
    engine.start_stream.side_effect = GPUWorkerTimeoutError("synthetic worker deadline")
    adapter._engine = engine

    with pytest.raises(STTDeadlineExceededError, match="deadline"):
        adapter._transcribe_raw_sync(b"\x00\x00" * 8_000)

    engine.reset.assert_called_once_with()


@pytest.mark.asyncio
async def test_cancelled_detailed_request_keeps_engine_lock_until_thread_finishes(tmp_settings):
    adapter = _adapter(tmp_settings)
    started = threading.Event()
    release = threading.Event()

    def blocking_transcription(*args, **kwargs) -> DetailedTranscription:
        started.set()
        assert release.wait(timeout=1)
        return DetailedTranscription(
            raw_text="synthetic",
            segments=(),
            language=None,
            confidence=None,
            duration_ms=1,
            backend="whisper-cpp",
            model="synthetic-model",
            library="linux-whisper",
            revision=None,
            stt_ms=1,
        )

    adapter._transcribe_detailed_sync = blocking_transcription
    first = asyncio.create_task(
        adapter.transcribe_detailed(b"\x00\x00", turn_id="one", include_polished=False)
    )
    await asyncio.to_thread(started.wait, 1)
    first.cancel()
    await asyncio.sleep(0)

    assert first.done() is False
    first.cancel()
    await asyncio.sleep(0)
    assert first.done() is False
    assert adapter._lock.locked() is True
    assert (
        await adapter.try_transcribe_detailed(
            b"\x00\x00",
            turn_id="two",
            include_polished=False,
        )
    ) is None

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
