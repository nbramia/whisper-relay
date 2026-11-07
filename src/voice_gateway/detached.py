"""Server-owned voice turns.

A turn's lifetime belongs to the server, not to the HTTP connection that
started it. `DetachedTurn` runs the pipeline's event generator as its own
asyncio task and writes events into a bounded queue; `reader()` is the
generator handed to `StreamingResponse`. Closing the reader (what a client
disconnect does) detaches without touching the task, so the turn still runs
STT, the text backend, and TTS and writes its meta and clips.

While no reader is attached, events are buffered up to the queue bound and then
dropped, so a detached producer never blocks on a full queue. `DetachedTurnRunner` owns the
tasks: it bounds each turn's lifetime and drains them on shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

from voice_gateway.config import Settings
from voice_gateway.logging import log_event

logger = logging.getLogger(__name__)

TERMINAL_EVENTS = frozenset({"done", "error", "cancelled"})
_QUEUE_MAX = 256
_SENTINEL: Any = object()


class DetachedTurn:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._attached = False
        self.task: asyncio.Task[None] | None = None

    async def _put(self, item: Any) -> None:
        if self._attached:
            # A reader that detaches while this put is parked on a full queue
            # drains the queue, which releases the put.
            await self._queue.put(item)
            return
        # No reader (not yet attached, or gone): buffer for a reader that may
        # still arrive, and drop once the buffer is full rather than block.
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(item)

    async def emit(self, event: dict[str, Any]) -> None:
        await self._put(event)

    async def close(self) -> None:
        await self._put(_SENTINEL)

    async def reader(self) -> AsyncIterator[dict[str, Any]]:
        self._attached = True
        try:
            while True:
                item = await self._queue.get()
                if item is _SENTINEL:
                    return
                yield item
        finally:
            self._attached = False
            while not self._queue.empty():
                self._queue.get_nowait()


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
