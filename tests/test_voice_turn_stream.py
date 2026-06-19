import json
from unittest.mock import patch

import pytest

from voice_gateway.audio import NormalizedAudio


@pytest.mark.asyncio
async def test_voice_turn_stream(client):
    pcm = b"\x00\x00" * 8000
    normalized = NormalizedAudio(pcm_bytes=pcm, duration_s=0.5)

    with patch("voice_gateway.turns.normalize_audio", return_value=normalized):
        files = {"audio": ("test.webm", b"fake-audio", "audio/webm")}
        async with client.stream("POST", "/api/voice/turn/stream", files=files) as resp:
            assert resp.status_code == 200
            events = []
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

    types = [e["type"] for e in events]
    assert types[0] == "started"
    assert "transcript" in types
    assert "status_audio" in types
    assert "response" in types
    assert "main_audio" in types
    assert types[-1] == "done"
    assert events[-1]["data"]["transcript"] == "remind me to call mom"

    status_idx = types.index("status_audio")
    done_idx = types.index("done")
    assert status_idx < done_idx
