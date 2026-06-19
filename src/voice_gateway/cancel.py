"""In-flight turn cancellation registry."""

from __future__ import annotations

import asyncio


class TurnRegistry:
    def __init__(self) -> None:
        self._active: dict[str, asyncio.Event] = {}

    def start(self, turn_id: str) -> asyncio.Event:
        cancel = asyncio.Event()
        self._active[turn_id] = cancel
        return cancel

    def cancel(self, turn_id: str) -> bool:
        event = self._active.get(turn_id)
        if event is None:
            return False
        event.set()
        return True

    def end(self, turn_id: str) -> None:
        self._active.pop(turn_id, None)
