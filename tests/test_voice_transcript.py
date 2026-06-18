import pytest


@pytest.mark.asyncio
async def test_voice_turn_transcript_only(client):
    data = {"transcript": "what is on my calendar tomorrow"}
    resp = await client.post("/api/voice/turn", data=data)

    assert resp.status_code == 200
    body = resp.json()
    assert body["transcript"] == "what is on my calendar tomorrow"
    assert body["response_text"]
    assert body["audio_url"].startswith("/api/voice/audio/")


@pytest.mark.asyncio
async def test_voice_turn_requires_audio_or_transcript(client):
    resp = await client.post("/api/voice/turn", data={})
    assert resp.status_code == 400
