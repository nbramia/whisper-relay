"""Tests for per-turn model_override on voice turns (issue #24)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_gateway.adapters.lifeos import (
    HTTPLifeOSClient,
    LifeOSResult,
    handoff_override_for_model,
    normalize_model_override,
)


def test_normalize_model_override_omits_auto_and_empty():
    assert normalize_model_override(None) is None
    assert normalize_model_override("") is None
    assert normalize_model_override("  ") is None
    assert normalize_model_override("auto") is None
    assert normalize_model_override(" Auto ") is None


def test_normalize_model_override_passes_pinned_values():
    assert normalize_model_override("sonnet") == "sonnet"
    assert normalize_model_override(" Opus ") == "opus"
    assert normalize_model_override("gemma") == "gemma"
    assert normalize_model_override("claude_code") == "claude_code"


def test_handoff_override_for_model():
    assert handoff_override_for_model("claude_code") is True
    assert handoff_override_for_model("codex") is True
    assert handoff_override_for_model("sonnet") is False
    assert handoff_override_for_model("auto") is False


@pytest.mark.asyncio
async def test_lifeos_client_sends_model_override(lifeos_sse_fixture):
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
            "pin sonnet",
            conversation_id=None,
            turn_id="t1",
            model_override="sonnet",
            parse_handoff=False,
        )

    body = mock_http.stream.call_args.kwargs["json"]
    assert body["model_override"] == "sonnet"


@pytest.mark.asyncio
async def test_lifeos_client_omits_model_override_for_auto(lifeos_sse_fixture):
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
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("voice_gateway.adapters.lifeos.httpx.AsyncClient", return_value=mock_http):
        await client.ask(
            "default path",
            conversation_id=None,
            turn_id="t1",
            model_override="auto",
            parse_handoff=False,
        )

    body = mock_http.stream.call_args.kwargs["json"]
    assert "model_override" not in body


@pytest.mark.asyncio
async def test_turn_stream_forwards_model_override(client, pipeline):
    lifeos = pipeline._text_backend.lifeos
    resp = await client.post(
        "/api/voice/turn/stream",
        data={
            "transcript": "hello",
            "backend": "lifeos",
            "persona_id": "fitness",
            "model_override": "opus",
        },
    )
    assert resp.status_code == 200
    assert lifeos.last_model_override == "opus"


@pytest.mark.asyncio
async def test_turn_omits_model_override_when_auto(client, pipeline):
    lifeos = pipeline._text_backend.lifeos
    resp = await client.post(
        "/api/voice/turn",
        data={
            "transcript": "hello",
            "backend": "lifeos",
            "model_override": "auto",
        },
    )
    assert resp.status_code == 200
    assert lifeos.last_model_override is None


@pytest.mark.asyncio
async def test_claude_code_override_enables_handoff_on_no_handoff_persona(client, pipeline):
    lifeos = pipeline._text_backend.lifeos

    async def mock_ask(*args, **kwargs):
        lifeos.last_parse_handoff = kwargs.get("parse_handoff")
        lifeos.last_model_override = kwargs.get("model_override")
        return LifeOSResult(answer="ok", conversation_id="conv-1")

    lifeos.ask = mock_ask  # type: ignore[method-assign]

    resp = await client.post(
        "/api/voice/turn/stream",
        data={
            "transcript": "refactor auth",
            "backend": "lifeos",
            "persona_id": "fitness",
            "model_override": "claude_code",
        },
    )
    assert resp.status_code == 200
    assert lifeos.last_model_override == "claude_code"
    assert lifeos.last_parse_handoff is True
