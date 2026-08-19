"""Text backend routing for LifeOS, OpenClaw voice-adapter, and Hermes."""

from __future__ import annotations

from voice_gateway.adapters.lifeos import LifeOSClient, LifeOSError

BACKEND_LIFEOS = "lifeos"
BACKEND_AGENT = "agent"
BACKEND_HERMES = "hermes"

_KNOWN_BACKENDS = (BACKEND_LIFEOS, BACKEND_AGENT, BACKEND_HERMES)


def normalize_backend(value: str | None) -> str:
    """Resolve a raw backend selector; unknown values fall back to LifeOS."""
    kind = value.strip().lower() if value else ""
    if kind in _KNOWN_BACKENDS:
        return kind
    return BACKEND_LIFEOS


class TextBackendUnavailableError(LifeOSError):
    """Requested backend is not configured."""


class TextBackendRouter:
    def __init__(
        self,
        lifeos: LifeOSClient,
        agent: LifeOSClient | None = None,
        hermes: LifeOSClient | None = None,
    ) -> None:
        self._lifeos = lifeos
        self._agent = agent
        self._hermes = hermes

    @property
    def lifeos(self) -> LifeOSClient:
        return self._lifeos

    @property
    def agent(self) -> LifeOSClient | None:
        return self._agent

    @property
    def hermes(self) -> LifeOSClient | None:
        return self._hermes

    def client_for(self, backend: str | None) -> LifeOSClient:
        kind = normalize_backend(backend)
        if kind == BACKEND_AGENT:
            if self._agent is None:
                raise TextBackendUnavailableError("agent backend is not configured")
            return self._agent
        if kind == BACKEND_HERMES:
            if self._hermes is None:
                raise TextBackendUnavailableError("hermes backend is not configured")
            return self._hermes
        return self._lifeos
