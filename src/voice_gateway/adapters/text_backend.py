"""Text backend routing for LifeOS, OpenClaw voice-adapter, and Hermes."""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class BackendCapabilities:
    """What per-turn context a backend accepts. The gateway forwards, never resolves."""

    persona: bool
    model_override: bool
    handoff: bool


_CAPABILITIES = {
    # LifeOS orchestrator: full context, including claude_intent handoffs.
    BACKEND_LIFEOS: BackendCapabilities(persona=True, model_override=True, handoff=True),
    # voice-adapter owns its own session, escalation, and formatting: deliberately
    # context-poor (ADR-004). Do not widen without an ADR.
    BACKEND_AGENT: BackendCapabilities(persona=False, model_override=False, handoff=False),
    # Hermes answers by default in the LifeOS client, so a spoken turn needs the
    # persona's speech-formatting rules. Handoff stays off: engine handoff is a
    # LifeOS-orchestrator concept and Hermes has its own delegation posture.
    BACKEND_HERMES: BackendCapabilities(persona=True, model_override=True, handoff=False),
}


def capabilities_for(backend: str | None) -> BackendCapabilities:
    """Per-turn context the selected backend accepts."""
    return _CAPABILITIES[normalize_backend(backend)]


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
