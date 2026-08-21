"""In-flight turn cancellation registry."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(slots=True)
class ActiveTurn:
    cancel: asyncio.Event
    backend: str


class TurnRegistry:
    """Tracks in-flight turns so a cancel request can reach them.

    The backend is recorded alongside the event because the cancel route needs it:
    an explicit upstream cancel is a LifeOS-orchestrator call and must not be sent
    to the other backends, which own their own cancel semantics (issue #37).
    """

    def __init__(self) -> None:
        self._active: dict[str, ActiveTurn] = {}

    def start(self, turn_id: str, backend: str = "lifeos") -> asyncio.Event:
        cancel = asyncio.Event()
        self._active[turn_id] = ActiveTurn(cancel=cancel, backend=backend)
        return cancel

    def backend_for(self, turn_id: str) -> str | None:
        entry = self._active.get(turn_id)
        return entry.backend if entry else None

    def cancel(self, turn_id: str) -> bool:
        entry = self._active.get(turn_id)
        if entry is None:
            return False
        entry.cancel.set()
        return True

    def end(self, turn_id: str) -> None:
        self._active.pop(turn_id, None)
