from unittest.mock import patch

import pytest

from conftest import StubLifeOSClient
from voice_gateway.adapters.lifeos import LifeOSError
from voice_gateway.adapters.stt import StubSTTAdapter
from voice_gateway.adapters.text_backend import TextBackendRouter, capabilities_for
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
        model_override=None,
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


@pytest.mark.parametrize(
    ("backend", "persona", "model", "handoff"),
    [
        ("lifeos", True, True, True),
        ("agent", False, False, False),
        ("hermes", True, True, False),
        # Unknown selectors resolve to lifeos, capabilities included.
        ("codex", True, True, True),
    ],
)
def test_capabilities_per_backend(backend, persona, model, handoff):
    caps = capabilities_for(backend)
    assert (caps.persona, caps.model_override, caps.handoff) == (persona, model, handoff)


async def _run_turn(pipeline, **kwargs):
    async for _ in pipeline.run_turn_stream(
        None,
        content_type=None,
        filename=None,
        conversation_id=None,
        client_transcript="hello",
        **kwargs,
    ):
        pass


def _pipeline_with(tmp_path, backend_client, backend_kind):
    settings = Settings(data_dir=tmp_path, tts_backend="null")
    storage = TurnStorage(settings.turns_dir)
    lifeos = StubLifeOSClient()
    agent = backend_client if backend_kind == "agent" else None
    hermes = backend_client if backend_kind == "hermes" else None
    if backend_kind == "lifeos":
        lifeos = backend_client
    return TurnPipeline(
        settings,
        storage,
        StubSTTAdapter("hello"),
        TextBackendRouter(lifeos, agent, hermes),
        NullTTSAdapter(),
    )


@pytest.mark.asyncio
async def test_pipeline_forwards_context_to_hermes(tmp_path):
    hermes = StubLifeOSClient()
    pipeline = _pipeline_with(tmp_path, hermes, "hermes")
    await _run_turn(
        pipeline,
        backend="hermes",
        persona_id="fitness",
        model_override="opus",
        parse_handoff=True,
    )
    assert hermes.last_persona_id == "fitness"
    assert hermes.last_model_override == "opus"
    # Handoff is a LifeOS-orchestrator concept; hermes never parses claude_intent.
    assert hermes.last_parse_handoff is False


@pytest.mark.asyncio
async def test_pipeline_strips_context_for_agent(tmp_path):
    agent = StubLifeOSClient()
    pipeline = _pipeline_with(tmp_path, agent, "agent")
    await _run_turn(
        pipeline,
        backend="agent",
        persona_id="fitness",
        model_override="opus",
        parse_handoff=True,
    )
    assert agent.last_persona_id is None
    assert agent.last_model_override is None
    assert agent.last_parse_handoff is False


@pytest.mark.asyncio
async def test_pipeline_keeps_lifeos_context_unchanged(tmp_path):
    lifeos = StubLifeOSClient()
    pipeline = _pipeline_with(tmp_path, lifeos, "lifeos")
    await _run_turn(
        pipeline,
        backend="lifeos",
        persona_id="doctor",
        model_override="claude_code",
        parse_handoff=True,
    )
    assert lifeos.last_persona_id == "doctor"
    assert lifeos.last_model_override == "claude_code"
    assert lifeos.last_parse_handoff is True
