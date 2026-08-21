"""Tests for the Hermes text backend client and routing (issue #32)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from conftest import StubLifeOSClient
from voice_gateway.adapters.hermes_backend import HTTPHermesBackendClient
from voice_gateway.adapters.lifeos import (
    HTTPLifeOSClient,
    LifeOSCancelled,
    LifeOSError,
    LifeOSResult,
)
from voice_gateway.adapters.stt import StubSTTAdapter
from voice_gateway.adapters.text_backend import TextBackendRouter
from voice_gateway.adapters.tts import NullTTSAdapter
from voice_gateway.audio import NormalizedAudio
from voice_gateway.config import Settings
from voice_gateway.main import create_app
from voice_gateway.storage import TurnStorage
from voice_gateway.turns import TurnPipeline


class HermesStubClient:
    def __init__(self) -> None:
        self.last_question: str | None = None
        self.last_persona_id: str | None = None
        self.last_model_override: str | None = None
        self.last_parse_handoff: bool = True

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
        self.last_persona_id = persona_id
        self.last_model_override = model_override
        self.last_parse_handoff = parse_handoff
        if on_status:
            await on_status("Hermes is thinking…")
        return LifeOSResult(
            answer="Hermes path reply.",
            conversation_id=conversation_id or "hermes-conv-1",
            statuses=["Hermes is thinking…"],
        )

    async def list_personas(self):
        raise LifeOSError("hermes backend has no LifeOS personas")

    async def list_conversations(self, *, persona_id=None):
        return {"conversations": [{"id": "hermes-conv-1", "title": "Hermes thread"}]}

    async def get_conversation(self, conversation_id: str):
        return {"id": conversation_id, "messages": []}


def _mock_http(sse: str):
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
    return mock_http


@pytest.mark.asyncio
async def test_hermes_backend_client_parses_sse(lifeos_sse_fixture):
    client = HTTPHermesBackendClient("http://hermes.test", api_token="secret")
    mock_http = _mock_http(lifeos_sse_fixture)

    with patch("voice_gateway.adapters.hermes_backend.httpx.AsyncClient") as client_cls:
        client_cls.return_value = mock_http
        result = await client.ask("hello hermes", conversation_id=None, turn_id="t1")

    assert "three meetings" in result.answer
    assert result.conversation_id == "conv-abc"
    assert result.handoff is None
    assert client_cls.call_args.kwargs["headers"]["Authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_hermes_backend_client_omits_auth_header_without_token(lifeos_sse_fixture):
    client = HTTPHermesBackendClient("http://hermes.test")
    mock_http = _mock_http(lifeos_sse_fixture)

    with patch("voice_gateway.adapters.hermes_backend.httpx.AsyncClient") as client_cls:
        client_cls.return_value = mock_http
        await client.ask("hello hermes", conversation_id=None, turn_id="t1")

    assert client_cls.call_args.kwargs["headers"] == {}


@pytest.mark.asyncio
async def test_hermes_backend_client_invokes_on_status(lifeos_sse_fixture):
    client = HTTPHermesBackendClient("http://hermes.test")
    statuses: list[str] = []

    async def on_status(msg: str) -> None:
        statuses.append(msg)

    mock_http = _mock_http(lifeos_sse_fixture)
    with patch("voice_gateway.adapters.hermes_backend.httpx.AsyncClient") as client_cls:
        client_cls.return_value = mock_http
        await client.ask("hello", conversation_id=None, turn_id="t1", on_status=on_status)

    assert statuses == ["Searching your calendar…"]


@pytest.mark.asyncio
async def test_hermes_backend_ignores_claude_intent(lifeos_sse_fixture):
    sse = lifeos_sse_fixture.replace(
        'data: {"type": "done"}',
        'data: {"type": "claude_intent", "engine": "claude_code", "task": "fix"}\n\n'
        'data: {"type": "done"}',
    )
    client = HTTPHermesBackendClient("http://hermes.test")
    mock_http = _mock_http(sse)

    with patch("voice_gateway.adapters.hermes_backend.httpx.AsyncClient") as client_cls:
        client_cls.return_value = mock_http
        result = await client.ask("fix", conversation_id="c1", turn_id="t2", parse_handoff=True)

    assert "three meetings" in result.answer
    mock_http.post.assert_not_called()


@pytest.mark.asyncio
async def test_hermes_backend_raises_on_http_error():
    client = HTTPHermesBackendClient("http://hermes.test")

    mock_resp = AsyncMock()
    mock_resp.status_code = 502
    mock_resp.aread = AsyncMock(return_value=b"upstream down")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_http = AsyncMock()
    mock_http.stream = MagicMock(return_value=mock_resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("voice_gateway.adapters.hermes_backend.httpx.AsyncClient", return_value=mock_http),
        pytest.raises(LifeOSError, match="502"),
    ):
        await client.ask("hi", conversation_id=None, turn_id="t1")


@pytest.mark.asyncio
async def test_hermes_backend_list_and_get_conversations():
    client = HTTPHermesBackendClient("http://hermes.test", api_token="tok")

    list_resp = MagicMock()
    list_resp.status_code = 200
    list_resp.json = MagicMock(return_value={"conversations": [{"id": "h1"}]})

    get_resp = MagicMock()
    get_resp.status_code = 200
    get_resp.json = MagicMock(return_value={"id": "h1", "messages": []})

    mock_http = AsyncMock()
    mock_http.get = AsyncMock(side_effect=[list_resp, get_resp])
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("voice_gateway.adapters.hermes_backend.httpx.AsyncClient") as client_cls:
        client_cls.return_value = mock_http
        listed = await client.list_conversations()
        detail = await client.get_conversation("h1")

    assert listed["conversations"][0]["id"] == "h1"
    assert detail["id"] == "h1"
    assert mock_http.get.call_args_list[0].args[0] == "http://hermes.test/api/conversations"
    assert mock_http.get.call_args_list[1].args[0] == "http://hermes.test/api/conversations/h1"


@pytest.mark.asyncio
async def test_hermes_backend_has_no_lifeos_personas():
    client = HTTPHermesBackendClient("http://hermes.test")
    with pytest.raises(LifeOSError):
        await client.list_personas()


@pytest.mark.asyncio
async def test_turn_routes_hermes_backend(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null")
    storage = TurnStorage(settings.turns_dir)
    lifeos = StubLifeOSClient("LifeOS reply")
    hermes = HermesStubClient()
    pipeline = TurnPipeline(
        settings,
        storage,
        StubSTTAdapter("what is the weather"),
        TextBackendRouter(lifeos, None, hermes),
        NullTTSAdapter(),
    )
    app = create_app(settings, pipeline=pipeline)
    normalized = NormalizedAudio(pcm_bytes=b"\x00\x00" * 100, duration_s=0.1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("voice_gateway.turns.normalize_audio", return_value=normalized):
            resp = await client.post(
                "/api/voice/turn",
                data={"backend": "hermes", "transcript": "what is the weather"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["response_text"] == "Hermes path reply."
    assert hermes.last_question == "what is the weather"
    assert lifeos.last_question is None


@pytest.mark.asyncio
async def test_voice_turn_stream_hermes_backend(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null")
    storage = TurnStorage(settings.turns_dir)
    hermes = HermesStubClient()
    pipeline = TurnPipeline(
        settings,
        storage,
        StubSTTAdapter("remind me to call mom"),
        TextBackendRouter(StubLifeOSClient(), None, hermes),
        NullTTSAdapter(),
    )
    app = create_app(settings, pipeline=pipeline)
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as http,
        http.stream(
            "POST",
            "/api/voice/turn/stream",
            data={"backend": "hermes", "transcript": "remind me to call mom"},
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
    assert events[-1]["data"]["response_text"] == "Hermes path reply."


@pytest.mark.asyncio
async def test_hermes_backend_unconfigured_returns_503(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null", hermes_backend_enabled=False)
    storage = TurnStorage(settings.turns_dir)
    pipeline = TurnPipeline(
        settings,
        storage,
        StubSTTAdapter("hi"),
        TextBackendRouter(StubLifeOSClient()),
        NullTTSAdapter(),
    )
    app = create_app(settings, pipeline=pipeline)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/voice/turn",
            data={"backend": "hermes", "transcript": "hi"},
        )
    assert resp.status_code == 503


class SlowHermesStub:
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
        return LifeOSResult(answer="done", conversation_id=conversation_id or "hermes-1")

    async def list_personas(self):
        raise LifeOSError("hermes backend has no LifeOS personas")

    async def list_conversations(self, *, persona_id=None):
        return {"conversations": []}

    async def get_conversation(self, conversation_id: str):
        return {"id": conversation_id, "messages": []}


@pytest.mark.asyncio
async def test_cancel_hermes_turn_during_stream(tmp_settings):
    from voice_gateway.cancel import TurnRegistry

    storage = TurnStorage(tmp_settings.turns_dir, tmp_settings.turn_retention_hours)
    pipeline = TurnPipeline(
        tmp_settings,
        storage,
        StubSTTAdapter("hello"),
        TextBackendRouter(StubLifeOSClient(), None, SlowHermesStub()),
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
            backend="hermes",
        ):
            events.append(event)
            if event["type"] == "started":
                turn_id = event["turn_id"]
            if event["type"] == "status_audio" and turn_id:
                registry.cancel(turn_id)
            if event["type"] in {"cancelled", "done", "error"}:
                break

    assert any(e["type"] == "cancelled" for e in events)


@pytest.mark.asyncio
async def test_hermes_request_body_matches_lifeos(lifeos_sse_fixture):
    """Hermes gets the same per-turn *context* LifeOS does (issue #32).

    Parity covers persona, modality, and model. It deliberately stops short of
    `client_turn_id`: that is LifeOS's cancel key (issue #37), and hermes owns its
    own cancel semantics, so the key is not sent there.

    Doubles as the LifeOS regression: both bodies are spelled out, so a change to
    what either backend receives fails here rather than passing silently.
    """
    shared_context = {
        "question": "what is on my calendar",
        "conversation_id": "c1",
        "persona_id": "fitness",
        "model_override": "opus",
        "modality": "voice",
    }
    lifeos_expected = {**shared_context, "client_turn_id": "t1"}

    lifeos_http = _mock_http(lifeos_sse_fixture)
    with patch("voice_gateway.adapters.lifeos.httpx.AsyncClient", return_value=lifeos_http):
        await HTTPLifeOSClient("http://lifeos.test").ask(
            "what is on my calendar",
            conversation_id="c1",
            turn_id="t1",
            persona_id="fitness",
            model_override="opus",
            parse_handoff=False,
        )

    hermes_http = _mock_http(lifeos_sse_fixture)
    with patch("voice_gateway.adapters.hermes_backend.httpx.AsyncClient", return_value=hermes_http):
        await HTTPHermesBackendClient("http://hermes.test").ask(
            "what is on my calendar",
            conversation_id="c1",
            turn_id="t1",
            persona_id="fitness",
            model_override="opus",
        )

    assert lifeos_http.stream.call_args.kwargs["json"] == lifeos_expected
    assert hermes_http.stream.call_args.kwargs["json"] == shared_context


@pytest.mark.asyncio
async def test_hermes_turn_forwards_persona_and_model(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null")
    hermes = HermesStubClient()
    pipeline = TurnPipeline(
        settings,
        TurnStorage(settings.turns_dir),
        StubSTTAdapter("hello"),
        TextBackendRouter(StubLifeOSClient(), None, hermes),
        NullTTSAdapter(),
    )
    app = create_app(settings, pipeline=pipeline)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/voice/turn",
            data={
                "backend": "hermes",
                "transcript": "hello",
                "persona_id": "fitness",
                "model_override": "opus",
            },
        )

    assert resp.status_code == 200
    assert hermes.last_persona_id == "fitness"
    assert hermes.last_model_override == "opus"
    assert hermes.last_parse_handoff is False


@pytest.mark.asyncio
async def test_hermes_turn_defaults_persona_to_primary(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null")
    hermes = HermesStubClient()
    pipeline = TurnPipeline(
        settings,
        TurnStorage(settings.turns_dir),
        StubSTTAdapter("hello"),
        TextBackendRouter(StubLifeOSClient(), None, hermes),
        NullTTSAdapter(),
    )
    app = create_app(settings, pipeline=pipeline)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/voice/turn",
            data={"backend": "hermes", "transcript": "hello"},
        )

    assert resp.status_code == 200
    assert hermes.last_persona_id == "primary"
