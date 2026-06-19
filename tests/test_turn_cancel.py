import asyncio
from unittest.mock import patch

import pytest

from voice_gateway.adapters.lifeos import LifeOSCancelled, LifeOSResult
from voice_gateway.audio import NormalizedAudio
from voice_gateway.cancel import TurnRegistry


class SlowStubLifeOS:
    async def ask(self, question, *, conversation_id, turn_id, on_status=None, cancel=None):
        if on_status:
            await on_status("Working on it…")
        for _ in range(200):
            if cancel is not None and cancel.is_set():
                raise LifeOSCancelled("turn cancelled")
            await asyncio.sleep(0.01)
        return LifeOSResult(answer="done", conversation_id=conversation_id or "conv-1")

    async def list_conversations(self):
        return {"conversations": []}

    async def get_conversation(self, conversation_id: str):
        return {"id": conversation_id, "messages": []}


@pytest.mark.asyncio
async def test_cancel_turn_endpoint_not_found(client):
    resp = await client.post("/api/voice/turn/missing-id/cancel")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_turn_during_stream(tmp_settings, tmp_path):
    from voice_gateway.adapters.stt import StubSTTAdapter
    from voice_gateway.adapters.tts import NullTTSAdapter
    from voice_gateway.storage import TurnStorage
    from voice_gateway.turns import TurnPipeline

    storage = TurnStorage(tmp_settings.turns_dir, tmp_settings.turn_retention_hours)
    pipeline = TurnPipeline(
        tmp_settings,
        storage,
        StubSTTAdapter("hello"),
        SlowStubLifeOS(),
        NullTTSAdapter(),
    )
    registry = TurnRegistry()
    pcm = b"\x00\x00" * 8000
    normalized = NormalizedAudio(pcm_bytes=pcm, duration_s=0.5)

    with patch("voice_gateway.turns.normalize_audio", return_value=normalized):
        events = []
        async for event in pipeline.run_turn_stream(
            b"x",
            content_type="audio/webm",
            filename="t.webm",
            conversation_id=None,
            registry=registry,
        ):
            events.append(event)
            if event["type"] == "started":
                registry.cancel(event["turn_id"])
            if event["type"] in {"cancelled", "done", "error"}:
                break

    assert any(e["type"] == "cancelled" for e in events)


def test_turn_registry_cancel():
    registry = TurnRegistry()
    cancel = registry.start("turn-1")
    assert registry.cancel("turn-1") is True
    assert cancel.is_set()
    registry.end("turn-1")
    assert registry.cancel("turn-1") is False
