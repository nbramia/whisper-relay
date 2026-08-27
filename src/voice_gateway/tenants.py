"""Per-tenant backend routing (#40).

Backend-*kind* resolution (lifeos/agent/hermes) lives in adapters/text_backend.py
and is unchanged by this module. This module resolves a different question first:
*which tenant's* TextBackendRouter a request should use at all. In single-tenant
mode (the default — TENANT_BACKENDS_JSON unset) that question doesn't exist: every
request uses the one process-wide router built from top-level Settings, exactly as
before this issue.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass

from voice_gateway.adapters.agent_backend import HTTPAgentBackendClient
from voice_gateway.adapters.hermes_backend import HTTPHermesBackendClient
from voice_gateway.adapters.lifeos import HTTPLifeOSClient
from voice_gateway.adapters.text_backend import TextBackendRouter
from voice_gateway.config import Settings

logger = logging.getLogger(__name__)

# Presented by the client to select a tenant. Deliberately a header the operator's
# own network boundary controls the value of (an issued secret), never a
# client-suppliable free-text field — see #40's risk table.
TENANT_TOKEN_HEADER = "X-Whisper-Relay-Tenant-Token"


class TenantConfigError(ValueError):
    """TENANT_BACKENDS_JSON is invalid. Raised at startup only, never per-request."""


@dataclass(frozen=True)
class ResolvedTenant:
    tenant_id: str
    router: TextBackendRouter


class TenantRegistry:
    """Resolves a per-request tenant token to that tenant's TextBackendRouter.

    Empty (the default): single-tenant mode. `enabled` is False, and callers must
    use the process-wide TextBackendRouter directly — this class is not consulted
    at all, so an unset TENANT_BACKENDS_JSON has zero effect on request handling.

    Non-empty: per-tenant mode. Every voice-turn request must present a token
    matching exactly one configured tenant. There is deliberately no fallback to
    the process-wide router here — an unrecognized or missing token must be
    rejected by the caller, not silently routed anywhere (#40's fail-closed
    requirement).
    """

    def __init__(self, tenants_by_token: dict[str, ResolvedTenant]) -> None:
        self._by_token = tenants_by_token

    @property
    def enabled(self) -> bool:
        return bool(self._by_token)

    def resolve(self, token: str | None) -> ResolvedTenant | None:
        """None when `token` is missing/empty or matches no configured tenant.

        Compares against every candidate with `hmac.compare_digest` rather than a
        dict lookup, so a wrong guess doesn't get to key off dict-hash timing —
        cheap here since the tenant count is small and fixed at process startup.
        """
        if not token:
            return None
        for candidate, resolved in self._by_token.items():
            if hmac.compare_digest(candidate, token):
                return resolved
        return None


def _build_router(
    *,
    lifeos_base_url: str,
    lifeos_timeout_s: float,
    agent_backend_url: str | None,
    agent_backend_timeout_s: float,
    agent_backend_token: str | None,
    hermes_backend_url: str | None,
    hermes_backend_timeout_s: float,
    hermes_backend_token: str | None,
) -> TextBackendRouter:
    lifeos = HTTPLifeOSClient(lifeos_base_url, lifeos_timeout_s)
    agent = (
        HTTPAgentBackendClient(
            agent_backend_url, agent_backend_timeout_s, api_token=agent_backend_token
        )
        if agent_backend_url
        else None
    )
    hermes = (
        HTTPHermesBackendClient(
            hermes_backend_url, hermes_backend_timeout_s, api_token=hermes_backend_token
        )
        if hermes_backend_url
        else None
    )
    return TextBackendRouter(lifeos, agent, hermes)


def build_tenant_registry(settings: Settings) -> TenantRegistry:
    """Build the per-tenant router table from `settings.tenant_backends`.

    Fails loudly at startup — raises `TenantConfigError` — for a misconfiguration
    that would otherwise create ambiguity at request time: a blank token, or a
    token reused across two tenants. This must never be caught and downgraded to
    a warning; an ambiguous tenant table is exactly the failure mode #40 exists
    to close.
    """
    tenants_by_token: dict[str, ResolvedTenant] = {}
    tenant_id_by_token: dict[str, str] = {}

    for tenant_id, cfg in settings.tenant_backends.items():
        token = cfg.tenant_token.strip()
        if not token:
            raise TenantConfigError(
                f"TENANT_BACKENDS_JSON: tenant {tenant_id!r} has an empty tenant_token"
            )
        if token in tenant_id_by_token:
            raise TenantConfigError(
                f"TENANT_BACKENDS_JSON: tenant_token for {tenant_id!r} duplicates the one "
                f"configured for {tenant_id_by_token[token]!r} — each tenant needs its own token"
            )
        tenant_id_by_token[token] = tenant_id

        router = _build_router(
            lifeos_base_url=cfg.lifeos_base_url,
            lifeos_timeout_s=cfg.lifeos_timeout_s,
            agent_backend_url=cfg.agent_backend_url,
            agent_backend_timeout_s=cfg.agent_backend_timeout_s,
            agent_backend_token=cfg.agent_backend_token,
            hermes_backend_url=cfg.hermes_backend_url,
            hermes_backend_timeout_s=cfg.hermes_backend_timeout_s,
            hermes_backend_token=cfg.hermes_backend_token,
        )
        tenants_by_token[token] = ResolvedTenant(tenant_id=tenant_id, router=router)

    if tenants_by_token:
        logger.info(
            "tenant routing enabled: %d tenant(s) configured: %s",
            len(tenants_by_token),
            ", ".join(sorted(tenant_id_by_token.values())),
        )
    return TenantRegistry(tenants_by_token)
