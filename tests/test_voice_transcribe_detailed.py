from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import ANY, patch

import pytest
from httpx import ASGITransport, AsyncClient

from conftest import StubLifeOSClient
from voice_gateway.adapters.stt import (
    DetailedTranscription,
    RawSegment,
    STTDeadlineExceededError,
)
from voice_gateway.adapters.text_backend import TextBackendRouter
from voice_gateway.adapters.tts import NullTTSAdapter
from voice_gateway.audio import NormalizedAudio
from voice_gateway.config import Settings
from voice_gateway.main import create_app
from voice_gateway.storage import TurnStorage
from voice_gateway.turns import TurnPipeline

FIXTURES = Path(__file__).parent / "fixtures"


class DetailedSTT:
    @property
    def is_ready(self) -> bool:
        return True

    async def warmup(self) -> None:
        return

    async def transcribe(self, pcm_bytes: bytes, *, turn_id: str) -> tuple[str, dict[str, int]]:
        return "polished legacy result", {"stt_ms": 1, "polish_ms": 0}

    async def transcribe_detailed(
        self,
        pcm_bytes: bytes,
        *,
        turn_id: str,
        include_polished: bool,
    ) -> DetailedTranscription:
        return DetailedTranscription(
            raw_text="remind me to water the plants",
            segments=(RawSegment(text="remind me", start_ms=0, end_ms=500),),
            language=None,
            confidence=None,
            duration_ms=500,
            backend="whisper-cpp",
            model="synthetic-model",
            library="linux-whisper",
            revision=None,
            stt_ms=7,
            polished_text="Remind me to water the plants." if include_polished else None,
            polish_ms=2 if include_polished else 0,
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


class DeadlineSTT(DetailedSTT):
    async def try_transcribe_detailed(
        self,
        pcm_bytes: bytes,
        *,
        turn_id: str,
        include_polished: bool,
    ) -> DetailedTranscription | None:
        raise STTDeadlineExceededError("synthetic deadline")


def _normalized() -> NormalizedAudio:
    return NormalizedAudio(pcm_bytes=b"\x00\x00" * 8000, duration_s=0.5)


async def _client(tmp_path, stt: DetailedSTT, *, token: str | None = "synthetic-token"):
    settings = Settings(data_dir=tmp_path, tts_backend="null", raw_stt_token=token)
    storage = TurnStorage(settings.turns_dir)
    pipeline = TurnPipeline(
        settings,
        storage,
        stt,
        TextBackendRouter(StubLifeOSClient()),
        NullTTSAdapter(),
    )
    app = create_app(settings, pipeline=pipeline)
    transport = ASGITransport(app=app, client=("127.0.0.1", 12345))
    return app, AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_detailed_transcribe_returns_raw_provenance_without_polish(tmp_path):
    app, client = await _client(tmp_path, DetailedSTT())
    async with client:
        with patch("voice_gateway.routes.voice.normalize_audio", return_value=_normalized()):
            response = await client.post(
                "/api/voice/transcribe/detailed",
                headers={"X-Voice-Gateway-Token": "synthetic-token"},
                files={"audio": ("synthetic.m4a", b"fake-audio", "audio/mp4")},
            )

    assert response.status_code == 200
    expected = json.loads((FIXTURES / "raw_stt_detailed_v1.json").read_text())
    expected["timing"]["decode_ms"] = ANY
    expected["timing"]["total_ms"] = ANY
    assert response.json() == expected
    assert list(app.state.storage._turns_dir.iterdir()) == []
    assert app.state.turn_registry._active == {}


@pytest.mark.asyncio
async def test_detailed_transcribe_requires_configured_local_token(tmp_path):
    _app, client = await _client(tmp_path, DetailedSTT(), token=None)
    async with client:
        response = await client.post("/api/voice/transcribe/detailed")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_detailed_transcribe_rejects_invalid_token(tmp_path):
    _app, client = await _client(tmp_path, DetailedSTT())
    async with client:
        response = await client.post(
            "/api/voice/transcribe/detailed",
            headers={"X-Voice-Gateway-Token": "wrong"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_detailed_transcribe_marks_empty_raw_result_as_no_speech(tmp_path):
    class SilenceSTT(DetailedSTT):
        async def transcribe_detailed(self, *args, **kwargs) -> DetailedTranscription:
            return DetailedTranscription(
                raw_text="",
                segments=(),
                language=None,
                confidence=None,
                duration_ms=500,
                backend="whisper-cpp",
                model="synthetic-model",
                library="linux-whisper",
                revision=None,
                stt_ms=1,
            )

    _app, client = await _client(tmp_path, SilenceSTT())
    async with client:
        with patch("voice_gateway.routes.voice.normalize_audio", return_value=_normalized()):
            response = await client.post(
                "/api/voice/transcribe/detailed",
                headers={"X-Voice-Gateway-Token": "synthetic-token"},
                files={"audio": ("synthetic.m4a", b"fake-audio", "audio/mp4")},
            )

    assert response.status_code == 200
    assert response.json()["raw"] == {
        "outcome": "no_speech",
        "text": "",
        "segments": [],
        "language": None,
        "confidence": None,
    }


@pytest.mark.asyncio
async def test_detailed_transcribe_only_includes_polish_when_requested(tmp_path):
    _app, client = await _client(tmp_path, DetailedSTT())
    async with client:
        with patch("voice_gateway.routes.voice.normalize_audio", return_value=_normalized()):
            response = await client.post(
                "/api/voice/transcribe/detailed",
                headers={"X-Voice-Gateway-Token": "synthetic-token"},
                data={"include_polished": "true"},
                files={"audio": ("synthetic.m4a", b"fake-audio", "audio/mp4")},
            )

    assert response.status_code == 200
    assert response.json()["raw"]["text"] == "remind me to water the plants"
    assert response.json()["polished"] == "Remind me to water the plants."


@pytest.mark.asyncio
async def test_detailed_transcribe_maps_reaped_engine_deadline_to_retryable_504(tmp_path):
    _app, client = await _client(tmp_path, DeadlineSTT())
    async with client:
        with patch("voice_gateway.routes.voice.normalize_audio", return_value=_normalized()):
            response = await client.post(
                "/api/voice/transcribe/detailed",
                headers={"X-Voice-Gateway-Token": "synthetic-token"},
                files={"audio": ("synthetic.m4a", b"fake-audio", "audio/mp4")},
            )

    assert response.status_code == 504
    assert response.headers["retry-after"] == "1"
    assert response.json()["error"] == {
        "code": "deadline_exceeded",
        "message": "voice transcription unavailable",
        "retryable": True,
    }


@pytest.mark.asyncio
async def test_detailed_transcribe_rejects_when_admission_is_full(tmp_path):
    app, client = await _client(tmp_path, DetailedSTT())
    app.state.raw_stt_admission = asyncio.Semaphore(0)
    async with client:
        response = await client.post(
            "/api/voice/transcribe/detailed",
            headers={"X-Voice-Gateway-Token": "synthetic-token"},
            files={"audio": ("synthetic.m4a", b"fake-audio", "audio/mp4")},
        )

    assert response.status_code == 429
    assert response.json()["error"]["retryable"] is True


@pytest.mark.asyncio
async def test_detailed_transcribe_rejects_oversized_declared_upload_before_decode(tmp_path):
    app, client = await _client(tmp_path, DetailedSTT())
    app.state.settings.max_upload_bytes = 1
    async with client:
        with patch("voice_gateway.routes.voice.normalize_audio") as normalize:
            response = await client.post(
                "/api/voice/transcribe/detailed",
                headers={"X-Voice-Gateway-Token": "synthetic-token"},
                files={"audio": ("synthetic.m4a", b"fake-audio", "audio/mp4")},
            )

    assert response.status_code == 413
    assert normalize.call_count == 0


@pytest.mark.asyncio
async def test_detailed_transcribe_rejects_client_transcript_field(tmp_path):
    _app, client = await _client(tmp_path, DetailedSTT())
    async with client:
        response = await client.post(
            "/api/voice/transcribe/detailed",
            headers={"X-Voice-Gateway-Token": "synthetic-token"},
            data={"transcript": "seed this recognition"},
            files={"audio": ("synthetic.m4a", b"fake-audio", "audio/mp4")},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
