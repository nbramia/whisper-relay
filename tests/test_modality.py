"""Tests for sending modality=voice on voice turns (issues #27, #32).

Every turn through this gateway is spoken, so the LifeOS and Hermes adapters always
tell the backend to apply the selected persona's voice formatting rules
(LifeOS#390 Phase 3). The agent backend stays context-poor by design (ADR-004).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_gateway.adapters.agent_backend import HTTPAgentBackendClient
from voice_gateway.adapters.hermes_backend import HTTPHermesBackendClient
from voice_gateway.adapters.lifeos import HTTPLifeOSClient


def _mock_http(lifeos_sse_fixture):
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
    return mock_http


@pytest.mark.asyncio
async def test_lifeos_client_sends_modality_voice(lifeos_sse_fixture):
    client = HTTPLifeOSClient("http://lifeos.test")
    mock_http = _mock_http(lifeos_sse_fixture)
    with patch("voice_gateway.adapters.lifeos.httpx.AsyncClient", return_value=mock_http):
        await client.ask(
            "say something",
            conversation_id=None,
            turn_id="t1",
            persona_id="fitness",
            model_override="auto",
            parse_handoff=False,
        )
    body = mock_http.stream.call_args.kwargs["json"]
    assert body["modality"] == "voice"


@pytest.mark.asyncio
async def test_modality_sent_regardless_of_model_or_persona(lifeos_sse_fixture):
    # modality is intrinsic to the spoken surface — sent even with no persona,
    # and coexists with a pinned model.
    client = HTTPLifeOSClient("http://lifeos.test")
    mock_http = _mock_http(lifeos_sse_fixture)
    with patch("voice_gateway.adapters.lifeos.httpx.AsyncClient", return_value=mock_http):
        await client.ask(
            "no persona, pinned model",
            conversation_id=None,
            turn_id="t2",
            model_override="opus",
            parse_handoff=False,
        )
    body = mock_http.stream.call_args.kwargs["json"]
    assert body["modality"] == "voice"
    assert body["model_override"] == "opus"


@pytest.mark.asyncio
async def test_hermes_client_sends_modality_voice(lifeos_sse_fixture):
    # Hermes answers by default in the LifeOS client, so spoken turns must carry
    # modality too (issue #32) — otherwise replies are read aloud as screen prose.
    client = HTTPHermesBackendClient("http://hermes.test")
    mock_http = _mock_http(lifeos_sse_fixture)
    with patch("voice_gateway.adapters.hermes_backend.httpx.AsyncClient", return_value=mock_http):
        await client.ask(
            "say something",
            conversation_id=None,
            turn_id="t1",
            persona_id="fitness",
            model_override="auto",
        )
    body = mock_http.stream.call_args.kwargs["json"]
    assert body["modality"] == "voice"


@pytest.mark.asyncio
async def test_agent_client_sends_no_modality(lifeos_sse_fixture):
    # The agent backend stays deliberately context-poor (ADR-004).
    client = HTTPAgentBackendClient("http://agent.test")
    mock_http = _mock_http(lifeos_sse_fixture)
    with patch("voice_gateway.adapters.agent_backend.httpx.AsyncClient", return_value=mock_http):
        await client.ask(
            "say something",
            conversation_id=None,
            turn_id="t1",
            persona_id="fitness",
            model_override="opus",
        )
    body = mock_http.stream.call_args.kwargs["json"]
    assert body == {"question": "say something"}
