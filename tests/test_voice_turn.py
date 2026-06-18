from unittest.mock import patch

import pytest

from voice_gateway.audio import NormalizedAudio


@pytest.mark.asyncio
async def test_voice_turn_pipeline(client):
    pcm = b"\x00\x00" * 8000
    normalized = NormalizedAudio(pcm_bytes=pcm, duration_s=0.5)

    with patch("voice_gateway.turns.normalize_audio", return_value=normalized):
        files = {"audio": ("test.webm", b"fake-audio", "audio/webm")}
        resp = await client.post("/api/voice/turn", files=files)

    assert resp.status_code == 200
    data = resp.json()
    assert data["transcript"] == "remind me to call mom"
    assert data["response_text"]
    assert data["audio_url"].startswith("/api/voice/audio/")
    assert len(data["status_audio_urls"]) == 1

    audio_resp = await client.get(data["audio_url"])
    assert audio_resp.status_code == 200
    assert "audio" in audio_resp.headers["content-type"]
