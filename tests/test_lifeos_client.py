from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_gateway.adapters.lifeos import HTTPLifeOSClient


@pytest.mark.asyncio
async def test_lifeos_client_parses_sse(lifeos_sse_fixture):
    client = HTTPLifeOSClient("http://lifeos.test")
    statuses: list[str] = []

    async def on_status(msg: str) -> None:
        statuses.append(msg)

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
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.post = AsyncMock()

    with patch("voice_gateway.adapters.lifeos.httpx.AsyncClient", return_value=mock_http):
        result = await client.ask(
            "what meetings tomorrow",
            conversation_id=None,
            turn_id="t1",
            on_status=on_status,
        )

    assert "three meetings" in result.answer
    assert result.conversation_id == "conv-abc"
    assert statuses == ["Searching your calendar…"]


@pytest.mark.asyncio
async def test_lifeos_handoff_on_claude_intent(lifeos_sse_fixture, lifeos_handoff_fixture):
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

    handoff_resp = MagicMock()
    handoff_resp.status_code = 200
    handoff_resp.json = MagicMock(return_value=lifeos_handoff_fixture)

    mock_http = AsyncMock()
    mock_http.stream = MagicMock(return_value=mock_resp)
    mock_http.post = AsyncMock(return_value=handoff_resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("voice_gateway.adapters.lifeos.httpx.AsyncClient", return_value=mock_http):
        result = await client.ask("fix the bug", conversation_id="c1", turn_id="t2")

    assert result.handoff is not None
    assert result.handoff.engine == "claude_code"
    assert "Claude Code" in result.answer
