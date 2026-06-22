import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from conftest import StubLifeOSClient
from voice_gateway.adapters.agent_backend import HTTPAgentBackendClient
from voice_gateway.adapters.lifeos import LifeOSCancelled, LifeOSError, LifeOSResult
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
        self.last_model_override: str | None = None

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
        self.last_question = question
        self.last_model_override = model_override
        if on_status:
            await on_status("Agent is thinking…")
        return LifeOSResult(
            answer="Agent path reply.",
            conversation_id=conversation_id or "agent-conv-1",
            statuses=["Agent is thinking…"],
        )

    async def list_personas(self):
        raise LifeOSError("agent backend has no LifeOS personas")

    async def list_conversations(self, *, persona_id=None):
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
async def test_agent_backend_client_invokes_on_status(lifeos_sse_fixture):
    client = HTTPAgentBackendClient("http://agent.test")
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

    with patch("voice_gateway.adapters.agent_backend.httpx.AsyncClient") as client_cls:
        client_cls.return_value = mock_http
        await client.ask("hello", conversation_id=None, turn_id="t1", on_status=on_status)

    assert statuses == ["Searching your calendar…"]


@pytest.mark.asyncio
async def test_agent_backend_ignores_claude_intent(lifeos_sse_fixture):
    sse = lifeos_sse_fixture.replace(
        'data: {"type": "done"}',
        'data: {"type": "claude_intent", "engine": "claude_code", "task": "fix"}\n\n'
        'data: {"type": "done"}',
    )
    client = HTTPAgentBackendClient("http://agent.test")

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

    with patch("voice_gateway.adapters.agent_backend.httpx.AsyncClient") as client_cls:
        client_cls.return_value = mock_http
        result = await client.ask("fix", conversation_id="c1", turn_id="t2")

    assert "three meetings" in result.answer
    mock_http.post.assert_not_called()


@pytest.mark.asyncio
async def test_agent_backend_list_and_get_conversations():
    client = HTTPAgentBackendClient("http://agent.test", api_token="tok")

    list_resp = MagicMock()
    list_resp.status_code = 200
    list_resp.json = MagicMock(return_value={"conversations": [{"id": "a1"}]})

    get_resp = MagicMock()
    get_resp.status_code = 200
    get_resp.json = MagicMock(return_value={"id": "a1", "messages": []})

    mock_http = AsyncMock()
    mock_http.get = AsyncMock(side_effect=[list_resp, get_resp])
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("voice_gateway.adapters.agent_backend.httpx.AsyncClient") as client_cls:
        client_cls.return_value = mock_http
        listed = await client.list_conversations()
        detail = await client.get_conversation("a1")

    assert listed["conversations"][0]["id"] == "a1"
    assert detail["id"] == "a1"
    assert mock_http.get.call_args_list[0].args[0] == "http://agent.test/api/conversations"
    assert mock_http.get.call_args_list[1].args[0] == "http://agent.test/api/conversations/a1"


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
async def test_agent_turn_ignores_persona_id(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null")
    storage = TurnStorage(settings.turns_dir)
    agent = AgentStubClient()
    pipeline = TurnPipeline(
        settings,
        storage,
        StubSTTAdapter("hello"),
        TextBackendRouter(StubLifeOSClient(), agent),
        NullTTSAdapter(),
    )
    app = create_app(settings, pipeline=pipeline)
    normalized = NormalizedAudio(pcm_bytes=b"\x00\x00" * 100, duration_s=0.1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("voice_gateway.turns.normalize_audio", return_value=normalized):
            resp = await client.post(
                "/api/voice/turn",
                data={"backend": "agent", "transcript": "hello", "persona_id": "fitness"},
            )
    assert resp.status_code == 200
    assert agent.last_question == "hello"


@pytest.mark.asyncio
async def test_agent_turn_ignores_model_override(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null")
    storage = TurnStorage(settings.turns_dir)
    agent = AgentStubClient()
    pipeline = TurnPipeline(
        settings,
        storage,
        StubSTTAdapter("hello"),
        TextBackendRouter(StubLifeOSClient(), agent),
        NullTTSAdapter(),
    )
    app = create_app(settings, pipeline=pipeline)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/voice/turn",
            data={
                "backend": "agent",
                "transcript": "hello",
                "model_override": "sonnet",
            },
        )
    assert resp.status_code == 200
    assert agent.last_model_override is None


@pytest.mark.asyncio
async def test_voice_turn_stream_agent_backend(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null")
    storage = TurnStorage(settings.turns_dir)
    agent = AgentStubClient()
    pipeline = TurnPipeline(
        settings,
        storage,
        StubSTTAdapter("remind me to call mom"),
        TextBackendRouter(StubLifeOSClient(), agent),
        NullTTSAdapter(),
    )
    app = create_app(settings, pipeline=pipeline)
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as http,
        http.stream(
            "POST",
            "/api/voice/turn/stream",
            data={"backend": "agent", "transcript": "remind me to call mom"},
        ) as resp,
    ):
        assert resp.status_code == 200
        events = []
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    types = [e["type"] for e in events]
    assert "status_audio" in types
    assert types[-1] == "done"
    assert events[-1]["data"]["response_text"] == "Agent path reply."


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


class SlowAgentStub:
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
        if on_status:
            await on_status("Working…")
        for _ in range(200):
            if cancel is not None and cancel.is_set():
                raise LifeOSCancelled("turn cancelled")
            await asyncio.sleep(0.01)
        return LifeOSResult(answer="done", conversation_id=conversation_id or "agent-1")

    async def list_personas(self):
        raise LifeOSError("agent backend has no LifeOS personas")

    async def list_conversations(self, *, persona_id=None):
        return {"conversations": []}

    async def get_conversation(self, conversation_id: str):
        return {"id": conversation_id, "messages": []}


@pytest.mark.asyncio
async def test_cancel_agent_turn_during_stream(tmp_settings, tmp_path):
    from voice_gateway.cancel import TurnRegistry
    from voice_gateway.storage import TurnStorage

    storage = TurnStorage(tmp_settings.turns_dir, tmp_settings.turn_retention_hours)
    pipeline = TurnPipeline(
        tmp_settings,
        storage,
        StubSTTAdapter("hello"),
        TextBackendRouter(StubLifeOSClient(), SlowAgentStub()),
        NullTTSAdapter(),
    )
    registry = TurnRegistry()
    normalized = NormalizedAudio(pcm_bytes=b"\x00\x00" * 100, duration_s=0.1)

    with patch("voice_gateway.turns.normalize_audio", return_value=normalized):
        events = []
        turn_id = None
        async for event in pipeline.run_turn_stream(
            b"x",
            content_type="audio/webm",
            filename="t.webm",
            conversation_id=None,
            registry=registry,
            backend="agent",
        ):
            events.append(event)
            if event["type"] == "started":
                turn_id = event["turn_id"]
            if event["type"] == "status_audio" and turn_id:
                registry.cancel(turn_id)
            if event["type"] in {"cancelled", "done", "error"}:
                break

    assert any(e["type"] == "cancelled" for e in events)
