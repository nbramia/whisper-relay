from unittest.mock import patch

import pytest

from conftest import StubLifeOSClient
from voice_gateway.adapters.lifeos import LifeOSError
from voice_gateway.adapters.stt import StubSTTAdapter
from voice_gateway.adapters.text_backend import TextBackendRouter
from voice_gateway.adapters.tts import NullTTSAdapter
from voice_gateway.audio import AudioNormalizationError, NormalizedAudio
from voice_gateway.config import Settings
from voice_gateway.storage import TurnStorage
from voice_gateway.turns import TurnError, TurnPipeline

TURN_KWARGS = {
    "content_type": "audio/webm",
    "filename": "a.webm",
    "conversation_id": None,
}


class EmptySTT:
    async def transcribe(self, pcm_bytes, *, turn_id):
        return "", {"stt_ms": 0, "polish_ms": 0}

    async def warmup(self) -> None:
        return


class FailingLifeOS:
    async def ask(
        self,
        question,
        *,
        conversation_id,
        turn_id,
        on_status=None,
        cancel=None,
        persona_id=None,
        parse_handoff=True,
    ):
        raise LifeOSError("connection refused")

    async def list_personas(self):
        return {"personas": []}

    async def list_conversations(self, *, persona_id=None):
        return {"conversations": []}

    async def get_conversation(self, conversation_id: str):
        return {"id": conversation_id, "messages": []}


@pytest.mark.asyncio
async def test_turn_rejects_empty_transcript(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null")
    storage = TurnStorage(settings.turns_dir)
    pipeline = TurnPipeline(
        settings,
        storage,
        EmptySTT(),
        TextBackendRouter(StubLifeOSClient()),
        NullTTSAdapter(),
    )
    normalized = NormalizedAudio(pcm_bytes=b"\x00\x00" * 100, duration_s=0.1)
    with (
        patch("voice_gateway.turns.normalize_audio", return_value=normalized),
        pytest.raises(TurnError) as exc,
    ):
        await pipeline.run_turn(b"x", **TURN_KWARGS)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_turn_maps_lifeos_error_to_502(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null")
    storage = TurnStorage(settings.turns_dir)
    pipeline = TurnPipeline(
        settings,
        storage,
        StubSTTAdapter(),
        TextBackendRouter(FailingLifeOS()),
        NullTTSAdapter(),
    )
    normalized = NormalizedAudio(pcm_bytes=b"\x00\x00" * 100, duration_s=0.1)
    with (
        patch("voice_gateway.turns.normalize_audio", return_value=normalized),
        pytest.raises(TurnError) as exc,
    ):
        await pipeline.run_turn(b"x", **TURN_KWARGS)
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_turn_maps_normalize_error_to_400(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null")
    storage = TurnStorage(settings.turns_dir)
    pipeline = TurnPipeline(
        settings, storage, StubSTTAdapter(), TextBackendRouter(StubLifeOSClient()), NullTTSAdapter()
    )
    with (
        patch(
            "voice_gateway.turns.normalize_audio",
            side_effect=AudioNormalizationError("bad audio"),
        ),
        pytest.raises(TurnError) as exc,
    ):
        await pipeline.run_turn(b"", **TURN_KWARGS)
    assert exc.value.status_code == 400
