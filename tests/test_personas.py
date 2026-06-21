"""Tests for LifeOS persona discovery and pass-through (issue #19)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_gateway.adapters.lifeos import HTTPLifeOSClient, LifeOSResult, persona_supports_handoff


def test_persona_supports_handoff_primary_and_specialized():
    personas = [
        {"id": "primary", "label": "LifeOS", "capabilities": ["handoff", "agent"]},
        {"id": "fitness", "label": "Fitness", "capabilities": []},
        {"id": "doctor", "label": "Doctor", "capabilities": ["handoff"]},
    ]
    assert persona_supports_handoff(personas, "primary") is True
    assert persona_supports_handoff(personas, "fitness") is False
    assert persona_supports_handoff(personas, "doctor") is True
    assert persona_supports_handoff(personas, "missing") is False


@pytest.mark.asyncio
async def test_lifeos_client_list_personas():
    client = HTTPLifeOSClient("http://lifeos.test")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(
        return_value={
            "personas": [{"id": "primary", "label": "LifeOS", "capabilities": ["handoff"]}],
        }
    )
    mock_http = AsyncMock()
    mock_http.get = AsyncMock(return_value=mock_resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("voice_gateway.adapters.lifeos.httpx.AsyncClient", return_value=mock_http):
        data = await client.list_personas()

    assert data["personas"][0]["id"] == "primary"
    mock_http.get.assert_awaited_once_with("http://lifeos.test/api/personas")


@pytest.mark.asyncio
async def test_lifeos_client_sends_persona_id(lifeos_sse_fixture):
    client = HTTPLifeOSClient("http://lifeos.test")

    async def fake_aiter_lines():
        for line in lifeos_sse_fixture.splitlines():
            yield line

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = fake_aiter_lines
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_http = AsyncMock()
    mock_http.stream = MagicMock(return_value=mock_resp)
    mock_http.post = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("voice_gateway.adapters.lifeos.httpx.AsyncClient", return_value=mock_http):
        await client.ask(
            "log squats",
            conversation_id=None,
            turn_id="t1",
            persona_id="fitness",
            parse_handoff=False,
        )

    body = mock_http.stream.call_args.kwargs["json"]
    assert body["persona_id"] == "fitness"
    mock_http.post.assert_not_called()


@pytest.mark.asyncio
async def test_lifeos_client_skips_handoff_when_disabled(lifeos_sse_fixture):
    sse = lifeos_sse_fixture.replace(
        'data: {"type": "done"}',
        'data: {"type": "claude_intent", "engine": "claude_code", "task": "fix the bug"}\n\n'
        'data: {"type": "done"}',
    )
    client = HTTPLifeOSClient("http://lifeos.test")

    async def fake_aiter_lines():
        for line in sse.splitlines():
            yield line

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = fake_aiter_lines
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_http = AsyncMock()
    mock_http.stream = MagicMock(return_value=mock_resp)
    mock_http.post = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("voice_gateway.adapters.lifeos.httpx.AsyncClient", return_value=mock_http):
        result = await client.ask(
            "fix the bug",
            conversation_id="c1",
            turn_id="t2",
            persona_id="fitness",
            parse_handoff=False,
        )

    assert result.handoff is None
    mock_http.post.assert_not_called()


@pytest.mark.asyncio
async def test_lifeos_client_list_conversations_persona_filter():
    client = HTTPLifeOSClient("http://lifeos.test")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={"conversations": []})
    mock_http = AsyncMock()
    mock_http.get = AsyncMock(return_value=mock_resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("voice_gateway.adapters.lifeos.httpx.AsyncClient", return_value=mock_http):
        await client.list_conversations(persona_id="fitness")

    mock_http.get.assert_awaited_once_with(
        "http://lifeos.test/api/conversations",
        params={"persona_id": "fitness"},
    )


@pytest.mark.asyncio
async def test_personas_proxy(client):
    resp = await client.get("/api/voice/personas")
    assert resp.status_code == 200
    data = resp.json()
    assert any(p["id"] == "primary" for p in data["personas"])


@pytest.mark.asyncio
async def test_conversations_proxy_persona_filter(client, pipeline):
    lifeos = pipeline._text_backend.lifeos
    resp = await client.get("/api/voice/conversations", params={"persona_id": "fitness"})
    assert resp.status_code == 200
    assert lifeos.last_list_persona_id == "fitness"


@pytest.mark.asyncio
async def test_turn_stream_includes_persona_id(client, pipeline):
    lifeos = pipeline._text_backend.lifeos
    resp = await client.post(
        "/api/voice/turn/stream",
        data={"transcript": "hello", "backend": "lifeos", "persona_id": "fitness"},
    )
    assert resp.status_code == 200
    assert lifeos.last_persona_id == "fitness"
    assert lifeos.last_parse_handoff is False


@pytest.mark.asyncio
async def test_turn_stream_handoff_for_primary_persona(client, pipeline):
    lifeos = pipeline._text_backend.lifeos

    async def mock_ask(*args, **kwargs):
        lifeos.last_persona_id = kwargs.get("persona_id")
        lifeos.last_parse_handoff = kwargs.get("parse_handoff")
        return LifeOSResult(answer="ok", conversation_id="conv-1")

    lifeos.ask = mock_ask  # type: ignore[method-assign]

    resp = await client.post(
        "/api/voice/turn/stream",
        data={"transcript": "hello", "backend": "lifeos", "persona_id": "primary"},
    )
    assert resp.status_code == 200
    assert lifeos.last_persona_id == "primary"
    assert lifeos.last_parse_handoff is True
