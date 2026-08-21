"""Explicit upstream cancel on barge-in (issue #37).

whisper-relay's cancel gesture used to be abandoning the LifeOS stream. LifeOS#611
makes a turn's lifetime server-owned, so a dropped connection no longer stops the
work — the intent to stop has to be stated. The key is the pipeline's own turn_id,
which exists before the request goes out, so a barge-in landing before the first
SSE frame is still cancellable.
"""

import asyncio
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
from voice_gateway.adapters.text_backend import TextBackendRouter, capabilities_for
from voice_gateway.adapters.tts import NullTTSAdapter
from voice_gateway.cancel import TurnRegistry
from voice_gateway.config import Settings
from voice_gateway.main import create_app
from voice_gateway.storage import TurnStorage
from voice_gateway.turns import TurnPipeline


class CancellableStub(StubLifeOSClient):
    """Records explicit cancels and blocks until one arrives."""

    def __init__(self, *, cancel_result: object = True) -> None:
        super().__init__()
        self.cancelled_keys: list[str] = []
        self._cancel_result = cancel_result
        self.turn_ids: list[str] = []

    async def ask(self, question, *, conversation_id, turn_id, on_status=None, cancel=None, **kw):
        self.turn_ids.append(turn_id)
        if on_status:
            await on_status("Working on it…")
        for _ in range(500):
            if cancel is not None and cancel.is_set():
                raise LifeOSCancelled("turn cancelled")
            await asyncio.sleep(0.01)
        return LifeOSResult(answer="done", conversation_id=conversation_id or "conv-1")

    async def cancel_turn(self, client_turn_id: str):
        self.cancelled_keys.append(client_turn_id)
        if isinstance(self._cancel_result, Exception):
            raise self._cancel_result
        return self._cancel_result


def _app_with(backend_client, backend: str, tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null")
    lifeos = backend_client if backend == "lifeos" else StubLifeOSClient()
    agent = backend_client if backend == "agent" else None
    hermes = backend_client if backend == "hermes" else None
    pipeline = TurnPipeline(
        settings,
        TurnStorage(settings.turns_dir),
        StubSTTAdapter("hello"),
        TextBackendRouter(lifeos, agent, hermes),
        NullTTSAdapter(),
    )
    return create_app(settings, pipeline=pipeline)


async def _cancel_active_turn(app, backend: str, turn_id: str = "turn-under-test"):
    """Register an in-flight turn on `backend`, then cancel it through the route.

    Seeding the registry rather than racing a live SSE stream is deliberate: the
    route is the unit under test, and a turn with no reader attached at all is the
    sharpest form of "the cancel POST is not gated on the next SSE line".
    """
    registry: TurnRegistry = app.state.turn_registry
    cancel_event = registry.start(turn_id, backend)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.post(f"/api/voice/turn/{turn_id}/cancel")
    return resp, cancel_event


# --- the key on the way out -------------------------------------------------


@pytest.mark.asyncio
async def test_lifeos_request_carries_turn_id_as_cancel_key(lifeos_sse_fixture):
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
        await client.ask("hello", conversation_id=None, turn_id="turn-abc", parse_handoff=False)

    body = mock_http.stream.call_args.kwargs["json"]
    assert body["client_turn_id"] == "turn-abc"


@pytest.mark.asyncio
async def test_hermes_request_carries_no_cancel_key(lifeos_sse_fixture):
    client = HTTPHermesBackendClient("http://hermes.test")

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

    with patch("voice_gateway.adapters.hermes_backend.httpx.AsyncClient", return_value=mock_http):
        await client.ask("hello", conversation_id=None, turn_id="turn-abc")

    assert "client_turn_id" not in mock_http.stream.call_args.kwargs["json"]


# --- the cancel call itself -------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_turn_posts_the_key():
    client = HTTPLifeOSClient("http://lifeos.test")
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"ok": True, "cancelled": True})

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("voice_gateway.adapters.lifeos.httpx.AsyncClient", return_value=mock_http):
        stopped = await client.cancel_turn("turn-abc")

    assert stopped is True
    assert mock_http.post.call_args.args[0] == "http://lifeos.test/api/chat/cancel"
    assert mock_http.post.call_args.kwargs["json"] == {"client_turn_id": "turn-abc"}


@pytest.mark.asyncio
async def test_cancel_turn_reports_nothing_in_flight_without_raising():
    client = HTTPLifeOSClient("http://lifeos.test")
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"ok": True, "cancelled": False})

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("voice_gateway.adapters.lifeos.httpx.AsyncClient", return_value=mock_http):
        assert await client.cancel_turn("stale-key") is False


@pytest.mark.asyncio
async def test_cancel_turn_raises_on_422():
    client = HTTPLifeOSClient("http://lifeos.test")
    resp = MagicMock()
    resp.status_code = 422

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("voice_gateway.adapters.lifeos.httpx.AsyncClient", return_value=mock_http),
        pytest.raises(LifeOSError, match="422"),
    ):
        await client.cancel_turn("bad key")


# --- the route wiring -------------------------------------------------------


@pytest.mark.asyncio
async def test_route_cancel_calls_upstream_with_turn_id(tmp_path):
    stub = CancellableStub()
    app = _app_with(stub, "lifeos", tmp_path)
    resp, cancel_event = await _cancel_active_turn(app, "lifeos")

    assert resp.status_code == 200
    assert resp.json() == {"cancelled": True}
    assert cancel_event.is_set()
    assert stub.cancelled_keys == ["turn-under-test"]


@pytest.mark.asyncio
async def test_route_cancel_is_not_gated_on_the_stream(tmp_path):
    """No reader is attached at all, and the upstream cancel still fires promptly.

    Fired from inside the SSE read loop it would wait for a line that never comes;
    fired from the route it does not (issue #37).
    """
    stub = CancellableStub()
    app = _app_with(stub, "lifeos", tmp_path)
    resp, _ = await asyncio.wait_for(_cancel_active_turn(app, "lifeos"), timeout=2.0)

    assert resp.status_code == 200
    assert stub.cancelled_keys == ["turn-under-test"]


@pytest.mark.asyncio
async def test_route_cancel_survives_upstream_failure(tmp_path):
    stub = CancellableStub(cancel_result=OSError("connection refused"))
    app = _app_with(stub, "lifeos", tmp_path)
    resp, cancel_event = await _cancel_active_turn(app, "lifeos")

    # The local cancel already succeeded; a failed POST must not change the answer.
    assert resp.status_code == 200
    assert resp.json() == {"cancelled": True}
    assert cancel_event.is_set()
    assert stub.cancelled_keys == ["turn-under-test"]


@pytest.mark.asyncio
async def test_route_cancel_accepts_nothing_in_flight(tmp_path):
    stub = CancellableStub(cancel_result=False)
    app = _app_with(stub, "lifeos", tmp_path)
    resp, _ = await _cancel_active_turn(app, "lifeos")

    # cancelled: false upstream is a normal outcome, not an error worth surfacing.
    assert resp.status_code == 200
    assert resp.json() == {"cancelled": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["agent", "hermes"])
async def test_route_cancel_skips_backends_without_explicit_cancel(backend, tmp_path):
    stub = CancellableStub()
    app = _app_with(stub, backend, tmp_path)
    resp, cancel_event = await _cancel_active_turn(app, backend)

    assert resp.status_code == 200
    assert cancel_event.is_set()
    # These backends own their own cancel semantics; the LifeOS call must not reach them.
    assert stub.cancelled_keys == []


@pytest.mark.asyncio
async def test_cancel_unknown_turn_still_404(client):
    resp = await client.post("/api/voice/turn/missing-id/cancel")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_pipeline_records_backend_in_registry(tmp_path):
    """The route can only route the cancel if the pipeline recorded the backend."""
    stub = CancellableStub()
    settings = Settings(data_dir=tmp_path, tts_backend="null")
    pipeline = TurnPipeline(
        settings,
        TurnStorage(settings.turns_dir),
        StubSTTAdapter("hello"),
        TextBackendRouter(StubLifeOSClient(), None, stub),
        NullTTSAdapter(),
    )
    registry = TurnRegistry()
    seen: list[str | None] = []

    async for event in pipeline.run_turn_stream(
        None,
        content_type=None,
        filename=None,
        conversation_id=None,
        client_transcript="hello",
        registry=registry,
        backend="hermes",
    ):
        if event["type"] == "started":
            seen.append(registry.backend_for(event["turn_id"]))
            registry.cancel(event["turn_id"])
        if event["type"] in {"cancelled", "done", "error"}:
            break

    assert seen == ["hermes"]


# --- registry + capabilities ------------------------------------------------


def test_registry_records_backend_per_turn():
    registry = TurnRegistry()
    registry.start("t-lifeos", "lifeos")
    registry.start("t-hermes", "hermes")

    assert registry.backend_for("t-lifeos") == "lifeos"
    assert registry.backend_for("t-hermes") == "hermes"
    assert registry.backend_for("never-started") is None

    registry.end("t-lifeos")
    assert registry.backend_for("t-lifeos") is None


@pytest.mark.parametrize(
    ("backend", "explicit_cancel"),
    [("lifeos", True), ("agent", False), ("hermes", False)],
)
def test_explicit_cancel_capability(backend, explicit_cancel):
    assert capabilities_for(backend).explicit_cancel is explicit_cancel
