"""Server-owned voice turns.

A turn's lifetime belongs to the server, not to the HTTP connection that
started it. `DetachedTurn` runs the pipeline's event generator as its own
asyncio task and writes events into a bounded buffer; `reader()` is the
generator handed to `StreamingResponse`. Closing the reader (what a client
disconnect does) detaches without touching the task, so the turn still runs
STT, the text backend, and TTS and writes its meta and clips.

The buffer is bounded and the producer never blocks on it: when it is full the
oldest non-terminal frame is dropped, so a detached or stalled reader cannot
hold the turn up. `DetachedTurnRunner` owns the
tasks: it bounds each turn's lifetime and drains them on shutdown.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from voice_gateway.config import Settings
from voice_gateway.logging import log_event

logger = logging.getLogger(__name__)

TERMINAL_EVENTS = frozenset({"done", "error", "cancelled"})
_QUEUE_MAX = 256
_SENTINEL: Any = object()


def _is_terminal(item: Any) -> bool:
    return item is _SENTINEL or item.get("type") in TERMINAL_EVENTS


class DetachedTurn:
    """Event buffer between the turn task and at most one reader.

    `emit`/`close` never block: when the buffer is full the oldest
    non-terminal frame is dropped, so terminal events and the close sentinel
    always land, with or without a reader.
    """

    def __init__(self) -> None:
        self._buf: deque[Any] = deque()
        self._wake = asyncio.Event()
        self.task: asyncio.Task[None] | None = None

    def _push(self, item: Any) -> None:
        if len(self._buf) >= _QUEUE_MAX:
            for i, queued in enumerate(self._buf):
                if not _is_terminal(queued):
                    del self._buf[i]
                    break
        self._buf.append(item)
        self._wake.set()

    async def emit(self, event: dict[str, Any]) -> None:
        self._push(event)

    async def close(self) -> None:
        self._push(_SENTINEL)

    async def reader(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            while not self._buf:
                self._wake.clear()
                await self._wake.wait()
            item = self._buf.popleft()
            if item is _SENTINEL:
                return
            yield item


class DetachedTurnRunner:
    def __init__(self, settings: Settings) -> None:
        # Upper bound for a turn nobody is watching: decode + STT + the slowest
        # text backend, each already capped by its own setting.
        self._max_lifetime_s = (
            settings.decode_timeout_s
            + settings.stt_timeout_s
            + max(
                settings.lifeos_timeout_s,
                settings.agent_backend_timeout_s,
                settings.hermes_backend_timeout_s,
            )
        )
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, events: AsyncIterator[dict[str, Any]]) -> DetachedTurn:
        turn = DetachedTurn()
        task = asyncio.create_task(self._run(turn, events))
        turn.task = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return turn

    async def _run(self, turn: DetachedTurn, events: AsyncIterator[dict[str, Any]]) -> None:
        try:
            async with asyncio.timeout(self._max_lifetime_s):
                async for event in events:
                    await turn.emit(event)
                    if event.get("type") in TERMINAL_EVENTS:
                        break
        except TimeoutError:
            log_event(logger, "turn_deadline_exceeded", max_lifetime_s=self._max_lifetime_s)
            await turn.emit({"type": "error", "message": "turn timed out", "status_code": 504})
        except Exception:
            logger.exception("voice turn failed unexpectedly")
            await turn.emit({"type": "error", "message": "internal error", "status_code": 500})
        finally:
            aclose = getattr(events, "aclose", None)
            if aclose is not None:
                await asyncio.shield(aclose())
            await turn.close()

    async def shutdown(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
