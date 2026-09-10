import asyncio
import threading
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from conftest import StubLifeOSClient
from voice_gateway.adapters.text_backend import TextBackendRouter
from voice_gateway.adapters.tts import NullTTSAdapter
from voice_gateway.audio import NormalizedAudio
from voice_gateway.config import Settings
from voice_gateway.main import create_app
from voice_gateway.storage import TurnStorage
from voice_gateway.turns import TurnPipeline


class FailingSTT:
    async def transcribe(self, pcm_bytes, *, turn_id):
        raise RuntimeError("engine crashed")

    async def warmup(self) -> None:
        return


def _normalized() -> NormalizedAudio:
    return NormalizedAudio(pcm_bytes=b"\x00\x00" * 8000, duration_s=0.5)


@pytest.mark.asyncio
async def test_transcribe_happy_path(client):
    with patch("voice_gateway.routes.voice.normalize_audio", return_value=_normalized()):
        files = {"audio": ("clip.webm", b"fake-audio", "audio/webm")}
        resp = await client.post("/api/voice/transcribe", files=files)

    assert resp.status_code == 200
    assert resp.json() == {"transcript": "remind me to call mom"}


@pytest.mark.asyncio
async def test_transcribe_missing_audio_field(client):
    resp = await client.post("/api/voice/transcribe", data={})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_transcribe_empty_audio_body(client):
    files = {"audio": ("clip.webm", b"", "audio/webm")}
    resp = await client.post("/api/voice/transcribe", files=files)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_transcribe_stt_failure_returns_5xx(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null")
    storage = TurnStorage(settings.turns_dir)
    pipeline = TurnPipeline(
        settings,
        storage,
        FailingSTT(),
        TextBackendRouter(StubLifeOSClient()),
        NullTTSAdapter(),
    )
    app = create_app(settings, pipeline=pipeline)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("voice_gateway.routes.voice.normalize_audio", return_value=_normalized()):
            files = {"audio": ("clip.webm", b"fake-audio", "audio/webm")}
            resp = await ac.post("/api/voice/transcribe", files=files)

    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_transcribe_creates_no_turn_artifacts(client, pipeline):
    with patch("voice_gateway.routes.voice.normalize_audio", return_value=_normalized()):
        files = {"audio": ("clip.webm", b"fake-audio", "audio/webm")}
        resp = await client.post("/api/voice/transcribe", files=files)

    assert resp.status_code == 200
    # No turn directories were written to storage (no write_meta / clip files).
    assert list(pipeline._storage._turns_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_transcribe_leaves_turn_registry_untouched(app, client):
    registry = app.state.turn_registry
    with patch("voice_gateway.routes.voice.normalize_audio", return_value=_normalized()):
        files = {"audio": ("clip.webm", b"fake-audio", "audio/webm")}
        resp = await client.post("/api/voice/transcribe", files=files)

    assert resp.status_code == 200
    assert registry._active == {}


@pytest.mark.asyncio
async def test_transcribe_decode_does_not_block_unrelated_async_requests(client):
    started = threading.Event()
    release = threading.Event()

    def blocking_normalize(*args, **kwargs):
        started.set()
        assert release.wait(timeout=1)
        return _normalized()

    loop = asyncio.get_running_loop()
    began = loop.time()
    timer = threading.Timer(0.5, release.set)
    timer.start()
    try:
        with patch("voice_gateway.routes.voice.normalize_audio", blocking_normalize):
            transcribe = asyncio.create_task(
                client.post(
                    "/api/voice/transcribe",
                    files={"audio": ("clip.webm", b"fake-audio", "audio/webm")},
                )
            )
            assert await asyncio.to_thread(started.wait, 1)

            health = await client.get("/health")
            unrelated_latency = loop.time() - began
            release.set()
            response = await transcribe
    finally:
        release.set()
        timer.cancel()

    assert health.status_code == 200
    assert unrelated_latency < 0.25
    assert response.status_code == 200
    assert response.json() == {"transcript": "remind me to call mom"}
