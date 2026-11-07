"""Voice turns are server-owned: a client disconnect must not kill them."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from httpx import ASGITransport, AsyncClient

from voice_gateway.adapters.lifeos import LifeOSCancelled, LifeOSResult
from voice_gateway.adapters.stt import StubSTTAdapter
from voice_gateway.adapters.text_backend import TextBackendRouter
from voice_gateway.adapters.tts import NullTTSAdapter
from voice_gateway.audio import NormalizedAudio
from voice_gateway.detached import DetachedTurnRunner
from voice_gateway.main import create_app
from voice_gateway.storage import TurnStorage
from voice_gateway.turns import TurnPipeline


class GatedLifeOS:
    """Backend that waits on `release`, honours cancel, and records calls."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.asked = asyncio.Event()
        self.questions: list[str] = []
        self.cancelled = False
        self.running = False

    async def ask(self, question, *, conversation_id, turn_id, cancel=None, **_):
        self.questions.append(question)
        self.asked.set()
        self.running = True
        try:
            while not self.release.is_set():
                if cancel is not None and cancel.is_set():
                    self.cancelled = True
                    raise LifeOSCancelled("turn cancelled")
                await asyncio.sleep(0.005)
        finally:
            await asyncio.sleep(0.05)  # slow cleanup: only an awaited cancel sees it finish
            self.running = False
        return LifeOSResult(answer="the reply", conversation_id="conv-1")

    async def list_personas(self):
        return {"personas": [{"id": "primary", "label": "LifeOS", "capabilities": []}]}


def _build(tmp_settings, lifeos):
    storage = TurnStorage(tmp_settings.turns_dir, tmp_settings.turn_retention_hours)
    pipeline = TurnPipeline(
        tmp_settings,
        storage,
        StubSTTAdapter("hello there"),
        TextBackendRouter(lifeos),
        NullTTSAdapter(),
    )
    return create_app(tmp_settings, pipeline=pipeline), storage


async def _post_and_disconnect_after(app, marker: bytes) -> str:
    """POST a transcript turn, then send http.disconnect once `marker` is streamed.

    Returns the turn_id seen in the `started` frame.
    """
    body = urlencode({"transcript": "hello there"}).encode()
    inbox: asyncio.Queue = asyncio.Queue()
    inbox.put_nowait({"type": "http.request", "body": body, "more_body": False})
    seen = bytearray()
    saw_marker = asyncio.Event()

    async def receive():
        return await inbox.get()

    async def send(message):
        if message["type"] == "http.response.body":
            seen.extend(message.get("body", b""))
            if marker in seen:
                saw_marker.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/voice/turn/stream",
        "raw_path": b"/api/voice/turn/stream",
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"content-length", str(len(body)).encode()),
        ],
        "server": ("test", 80),
        "client": ("test", 1),
        "scheme": "http",
    }
    call = asyncio.create_task(app(scope, receive, send))
    await asyncio.wait_for(saw_marker.wait(), 5)
    inbox.put_nowait({"type": "http.disconnect"})
    await asyncio.wait_for(call, 5)
    line = next(ln for ln in seen.decode().split("\n\n") if '"started"' in ln)
    return json.loads(line[6:])["turn_id"]


async def _wait_for(predicate, timeout=5.0):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout)


@pytest.mark.asyncio
async def test_disconnect_after_started_still_completes_turn(tmp_settings):
    lifeos = GatedLifeOS()
    app, storage = _build(tmp_settings, lifeos)

    turn_id = await _post_and_disconnect_after(app, b'"started"')
    # Reader is gone; the backend must still be reached and then finish.
    await asyncio.wait_for(lifeos.asked.wait(), 5)
    assert lifeos.questions == ["hello there"]
    lifeos.release.set()
    await _wait_for(lambda: storage.read_meta(turn_id) is not None)

    meta = storage.read_meta(turn_id)
    assert meta["response_text"] == "the reply"
    assert meta["conversation_id"] == "conv-1"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get(f"/api/voice/audio/{turn_id}")).status_code == 200
    assert app.state.turn_registry.cancel(turn_id) is False  # turn ended and deregistered


@pytest.mark.asyncio
async def test_disconnect_mid_stt_still_reaches_backend(tmp_settings):
    lifeos = GatedLifeOS()
    lifeos.release.set()
    app, storage = _build(tmp_settings, lifeos)
    stt = app.state.pipeline.stt
    stt_started, stt_go = asyncio.Event(), asyncio.Event()
    real = stt.transcribe

    async def slow_transcribe(pcm, *, turn_id):
        stt_started.set()
        await stt_go.wait()
        return await real(pcm, turn_id=turn_id)

    normalized = NormalizedAudio(pcm_bytes=b"\x00\x00" * 8000, duration_s=0.5)
    body = (
        b'--b\r\nContent-Disposition: form-data; name="audio"; filename="t.webm"\r\n'
        b"Content-Type: audio/webm\r\n\r\nfake\r\n--b--\r\n"
    )
    inbox: asyncio.Queue = asyncio.Queue()
    inbox.put_nowait({"type": "http.request", "body": body, "more_body": False})
    seen = bytearray()
    started_seen = asyncio.Event()

    async def send(message):
        if message["type"] == "http.response.body":
            seen.extend(message.get("body", b""))
            if b'"started"' in seen:
                started_seen.set()

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "path": "/api/voice/turn/stream", "raw_path": b"/api/voice/turn/stream",
        "query_string": b"", "server": ("test", 80), "client": ("test", 1), "scheme": "http",
        "headers": [
            (b"content-type", b"multipart/form-data; boundary=b"),
            (b"content-length", str(len(body)).encode()),
        ],
    }  # fmt: skip
    with (
        patch("voice_gateway.turns.normalize_audio", return_value=normalized),
        patch.object(stt, "transcribe", slow_transcribe),
    ):
        call = asyncio.create_task(app(scope, inbox.get, send))
        await asyncio.wait_for(stt_started.wait(), 5)
        inbox.put_nowait({"type": "http.disconnect"})
        await asyncio.wait_for(call, 5)
        stt_go.set()
        await asyncio.wait_for(lifeos.asked.wait(), 5)

    assert lifeos.questions == ["hello there"]
    turn_id = json.loads(seen.decode().split("\n\n")[0][6:])["turn_id"]
    await _wait_for(lambda: storage.read_meta(turn_id) is not None)


@pytest.mark.asyncio
async def test_cancel_after_detach_stops_turn(tmp_settings):
    lifeos = GatedLifeOS()
    app, storage = _build(tmp_settings, lifeos)

    turn_id = await _post_and_disconnect_after(app, b'"started"')
    await asyncio.wait_for(lifeos.asked.wait(), 5)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post(f"/api/voice/turn/{turn_id}/cancel")
    assert resp.status_code == 200
    await _wait_for(lambda: lifeos.cancelled)
    await _wait_for(lambda: not app.state.turn_runner._tasks)
    assert storage.read_meta(turn_id) is None


@pytest.mark.asyncio
async def test_connected_client_event_sequence_unchanged(tmp_settings):
    lifeos = GatedLifeOS()
    lifeos.release.set()
    app, _ = _build(tmp_settings, lifeos)
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
        c.stream("POST", "/api/voice/turn/stream", data={"transcript": "hi"}) as r,
    ):
        events = [json.loads(ln[6:]) async for ln in r.aiter_lines() if ln.startswith("data: ")]
    assert [e["type"] for e in events] == [
        "started",
        "transcript",
        "response",
        "main_audio",
        "done",
    ]
    assert events[-1]["data"]["response_text"] == "the reply"


@pytest.mark.asyncio
async def test_detached_turn_has_hard_deadline(tmp_settings):
    lifeos = GatedLifeOS()  # never released
    app, storage = _build(tmp_settings, lifeos)
    runner: DetachedTurnRunner = app.state.turn_runner
    runner._max_lifetime_s = 0.2

    turn_id = await _post_and_disconnect_after(app, b'"started"')
    await _wait_for(lambda: not runner._tasks)
    assert storage.read_meta(turn_id) is None
    assert app.state.turn_registry.cancel(turn_id) is False


@pytest.mark.asyncio
async def test_shutdown_cancels_running_turns(tmp_settings):
    lifeos = GatedLifeOS()
    app, _ = _build(tmp_settings, lifeos)
    await _post_and_disconnect_after(app, b'"started"')
    await asyncio.wait_for(lifeos.asked.wait(), 5)
    assert lifeos.running
    await app.state.turn_runner.shutdown()
    assert not app.state.turn_runner._tasks
    assert not lifeos.running  # the backend call itself is gone, not just the turn task


@pytest.mark.asyncio
async def test_detached_producer_does_not_block_on_full_queue(tmp_settings):
    runner = DetachedTurnRunner(tmp_settings)

    async def many():
        for i in range(1000):
            yield {"type": "status_audio", "url": str(i), "message": ""}
        yield {"type": "done", "data": {}}

    turn = runner.start(many())
    reader = turn.reader()
    await anext(reader)  # attach, read one frame, then walk away
    await reader.aclose()
    await asyncio.wait_for(turn.task, 5)


@pytest.mark.asyncio
async def test_head_audio_404_before_clip_then_200(tmp_settings):
    lifeos = GatedLifeOS()
    lifeos.release.set()
    app, storage = _build(tmp_settings, lifeos)
    turn_id = "6f1c2f0e-8d2b-4b7e-9a51-3c1d2e4f5a6b"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.head(f"/api/voice/audio/{turn_id}")).status_code == 404
        assert (await c.head(f"/api/voice/audio/{turn_id}/status-0")).status_code == 404
        storage.turn_path(turn_id).mkdir(parents=True, exist_ok=True)
        storage.clip_path(turn_id, "main").write_bytes(b"RIFF....WAVE")
        storage.clip_path(turn_id, "status-0").write_bytes(b"RIFF....WAVE")
        assert (await c.head(f"/api/voice/audio/{turn_id}")).status_code == 200
        assert (await c.head(f"/api/voice/audio/{turn_id}/status-0")).status_code == 200
        assert (await c.get(f"/api/voice/audio/{turn_id}")).status_code == 200


def _status_events(n):
    async def gen():
        for i in range(n):
            yield {"type": "status_audio", "url": str(i), "message": ""}
        yield {"type": "done", "data": {}}

    return gen()


@pytest.mark.asyncio
async def test_late_reader_after_overflow_still_gets_terminal_event(tmp_settings):
    runner = DetachedTurnRunner(tmp_settings)
    turn = runner.start(_status_events(1000))
    await asyncio.wait_for(turn.task, 5)  # no reader yet; producer never blocks
    events = [e async for e in turn.reader()]  # ends: sentinel survived
    assert events[-1]["type"] == "done"
    assert len(events) <= 256


@pytest.mark.asyncio
async def test_stalled_reader_does_not_block_deadline_or_shutdown(tmp_settings):
    runner = DetachedTurnRunner(tmp_settings)
    runner._max_lifetime_s = 0.2

    async def endless():
        while True:
            yield {"type": "status_audio", "url": "x", "message": ""}
            await asyncio.sleep(0)

    turn = runner.start(endless())
    reader = turn.reader()
    await anext(reader)  # attached, then stalls and never reads again
    await asyncio.wait_for(turn.task, 5)  # deadline fires despite a full buffer
    assert not runner._tasks

    turn2 = runner.start(endless())
    reader2 = turn2.reader()
    await anext(reader2)
    await asyncio.sleep(0.05)
    await asyncio.wait_for(runner.shutdown(), 5)
    assert not runner._tasks
