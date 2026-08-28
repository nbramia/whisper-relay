"""In-flight turn cancellation registry."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(slots=True)
class ActiveTurn:
    cancel: asyncio.Event
    backend: str
    tenant_id: str | None = None


class TurnTenantMismatchError(Exception):
    """`turn_id` exists but was started under a different tenant (#48).

    Raised by `cancel()` rather than folded into its bool return so the route
    layer can tell "no such turn" (404) apart from "that turn isn't yours"
    (403) — a caller can never cancel, or act on, another tenant's turn by any
    means, including by guessing a turn_id. The status-code split does let a
    caller who already holds a specific (unguessable, UUIDv4) turn_id learn
    that it belongs to someone else rather than not existing at all; that's
    the same accepted-low-risk gap issue #48 itself calls out for token
    guessing, not a new one.
    """


class TurnRegistry:
    """Tracks in-flight turns so a cancel request can reach them.

    The backend is recorded alongside the event because the cancel route needs it:
    an explicit upstream cancel is a LifeOS-orchestrator call and must not be sent
    to the other backends, which own their own cancel semantics (issue #37).

    `tenant_id` is recorded too (#48): single-tenant mode never passes one, so
    every entry's tenant_id is None and lookups behave exactly as before — a
    turn_id alone is enough. In multi-tenant mode, a cancel must present the
    same tenant_id `start()` recorded for that turn, so one tenant's token can
    never reach another tenant's turn even though ids share one flat namespace.
    """

    def __init__(self) -> None:
        self._active: dict[str, ActiveTurn] = {}

    def start(
        self, turn_id: str, backend: str = "lifeos", tenant_id: str | None = None
    ) -> asyncio.Event:
        cancel = asyncio.Event()
        self._active[turn_id] = ActiveTurn(cancel=cancel, backend=backend, tenant_id=tenant_id)
        return cancel

    def backend_for(self, turn_id: str, tenant_id: str | None = None) -> str | None:
        entry = self._active.get(turn_id)
        if entry is None or entry.tenant_id != tenant_id:
            return None
        return entry.backend

    def cancel(self, turn_id: str, tenant_id: str | None = None) -> bool:
        """False when there's no such turn; raises TurnTenantMismatchError when there
        is one, but under a different tenant than `tenant_id`."""
        entry = self._active.get(turn_id)
        if entry is None:
            return False
        if entry.tenant_id != tenant_id:
            raise TurnTenantMismatchError(turn_id)
        entry.cancel.set()
        return True

    def end(self, turn_id: str) -> None:
        self._active.pop(turn_id, None)
