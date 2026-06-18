import pytest
from httpx import ASGITransport, AsyncClient

from conftest import StubLifeOSClient
from voice_gateway.adapters.stt import StubSTTAdapter
from voice_gateway.adapters.text_backend import TextBackendRouter
from voice_gateway.adapters.tts import NullTTSAdapter
from voice_gateway.config import Settings
from voice_gateway.main import create_app
from voice_gateway.storage import TurnStorage
from voice_gateway.turns import TurnPipeline


@pytest.mark.asyncio
async def test_audio_404_for_unknown_turn(client):
    resp = await client.get("/api/voice/audio/00000000-0000-4000-8000-000000000099")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_audio_404_invalid_uuid(client):
    resp = await client.get("/api/voice/audio/not-a-uuid")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upload_too_large(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null", max_upload_bytes=10)
    storage = TurnStorage(settings.turns_dir)

    pipeline = TurnPipeline(
        settings,
        storage,
        StubSTTAdapter(),
        TextBackendRouter(StubLifeOSClient()),
        NullTTSAdapter(),
    )
    app = create_app(settings, pipeline=pipeline)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        files = {"audio": ("big.webm", b"x" * 20, "audio/webm")}
        resp = await client.post("/api/voice/turn", files=files)
    assert resp.status_code == 413
