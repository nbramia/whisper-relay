"""Text backend routing for LifeOS vs OpenClaw voice-adapter."""

from __future__ import annotations

from voice_gateway.adapters.lifeos import LifeOSClient, LifeOSError

BACKEND_LIFEOS = "lifeos"
BACKEND_AGENT = "agent"


def normalize_backend(value: str | None) -> str:
    if value and value.strip().lower() == BACKEND_AGENT:
        return BACKEND_AGENT
    return BACKEND_LIFEOS


class TextBackendUnavailableError(LifeOSError):
    """Requested backend is not configured."""


class TextBackendRouter:
    def __init__(self, lifeos: LifeOSClient, agent: LifeOSClient | None = None) -> None:
        self._lifeos = lifeos
        self._agent = agent

    @property
    def lifeos(self) -> LifeOSClient:
        return self._lifeos

    @property
    def agent(self) -> LifeOSClient | None:
        return self._agent

    def client_for(self, backend: str | None) -> LifeOSClient:
        kind = normalize_backend(backend)
        if kind == BACKEND_AGENT:
            if self._agent is None:
                raise TextBackendUnavailableError("agent backend is not configured")
            return self._agent
        return self._lifeos
