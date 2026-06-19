from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from conftest import StubLifeOSClient
from voice_gateway.adapters.agent_backend import HTTPAgentBackendClient
from voice_gateway.adapters.lifeos import LifeOSResult
from voice_gateway.adapters.stt import StubSTTAdapter
from voice_gateway.adapters.text_backend import TextBackendRouter
from voice_gateway.adapters.tts import NullTTSAdapter
from voice_gateway.audio import NormalizedAudio
from voice_gateway.config import Settings
from voice_gateway.main import create_app
from voice_gateway.storage import TurnStorage
from voice_gateway.turns import TurnPipeline


class AgentStubClient:
    def __init__(self) -> None:
        self.last_question: str | None = None

    async def ask(self, question, *, conversation_id, turn_id, on_status=None, cancel=None):
        self.last_question = question
        if on_status:
            await on_status("Agent is thinking…")
        return LifeOSResult(
            answer="Agent path reply.",
            conversation_id=conversation_id or "agent-conv-1",
            statuses=["Agent is thinking…"],
        )

    async def list_conversations(self):
        return {"conversations": [{"id": "agent-conv-1", "title": "Agent thread"}]}

    async def get_conversation(self, conversation_id: str):
        return {"id": conversation_id, "messages": []}


@pytest.mark.asyncio
async def test_agent_backend_client_parses_sse(lifeos_sse_fixture):
    client = HTTPAgentBackendClient("http://agent.test", api_token="secret")

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

    with patch("voice_gateway.adapters.agent_backend.httpx.AsyncClient") as client_cls:
        client_cls.return_value = mock_http
        result = await client.ask("hello agent", conversation_id=None, turn_id="t1")

    assert "three meetings" in result.answer
    assert result.conversation_id == "conv-abc"
    assert result.handoff is None
    client_cls.assert_called_once()
    assert client_cls.call_args.kwargs["headers"]["Authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_turn_routes_agent_backend(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null", agent_backend_enabled=False)
    storage = TurnStorage(settings.turns_dir)
    lifeos = StubLifeOSClient("LifeOS reply")
    agent = AgentStubClient()
    pipeline = TurnPipeline(
        settings,
        storage,
        StubSTTAdapter("what is the weather"),
        TextBackendRouter(lifeos, agent),
        NullTTSAdapter(),
    )
    app = create_app(settings, pipeline=pipeline)
    normalized = NormalizedAudio(pcm_bytes=b"\x00\x00" * 100, duration_s=0.1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("voice_gateway.turns.normalize_audio", return_value=normalized):
            resp = await client.post(
                "/api/voice/turn",
                data={"backend": "agent", "transcript": "what is the weather"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["response_text"] == "Agent path reply."
    assert agent.last_question == "what is the weather"
    assert lifeos.last_question is None


@pytest.mark.asyncio
async def test_conversations_proxy_agent_backend(client):
    agent = AgentStubClient()
    app = client._transport.app
    app.state.text_backend_router = TextBackendRouter(StubLifeOSClient(), agent)

    resp = await client.get("/api/voice/conversations", params={"backend": "agent"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["conversations"][0]["id"] == "agent-conv-1"


@pytest.mark.asyncio
async def test_agent_backend_unconfigured_returns_503(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null", agent_backend_enabled=False)
    storage = TurnStorage(settings.turns_dir)
    pipeline = TurnPipeline(
        settings,
        storage,
        StubSTTAdapter("hi"),
        TextBackendRouter(StubLifeOSClient()),
        NullTTSAdapter(),
    )
    app = create_app(settings, pipeline=pipeline)
    normalized = NormalizedAudio(pcm_bytes=b"\x00\x00" * 100, duration_s=0.1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("voice_gateway.turns.normalize_audio", return_value=normalized):
            resp = await client.post(
                "/api/voice/turn",
                data={"backend": "agent", "transcript": "hi"},
            )
    assert resp.status_code == 503
