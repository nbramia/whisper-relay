"""Per-tenant backend routing (#40) — the fix for the wrong-tenant cross-wiring bug.

Two layers under test:
- voice_gateway.tenants: TenantRegistry / build_tenant_registry — resolves a
  per-request tenant token to that tenant's TextBackendRouter, or rejects.
- routes/voice.py wiring: single-tenant mode is unaffected; multi-tenant mode
  never falls through to the process-wide router for a missing/unrecognized
  token, and never cross-wires one tenant's turn to another tenant's backend.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from conftest import StubLifeOSClient
from voice_gateway.adapters.stt import StubSTTAdapter
from voice_gateway.adapters.text_backend import TextBackendRouter
from voice_gateway.adapters.tts import NullTTSAdapter
from voice_gateway.config import Settings, TenantBackend
from voice_gateway.main import create_app
from voice_gateway.storage import TurnStorage
from voice_gateway.tenants import (
    TENANT_TOKEN_HEADER,
    ResolvedTenant,
    TenantConfigError,
    TenantRegistry,
    build_tenant_registry,
)
from voice_gateway.turns import TurnPipeline

# --- voice_gateway.tenants: registry + config-building unit tests ----------------


def test_registry_disabled_when_no_tenants_configured():
    registry = build_tenant_registry(Settings(tenant_backends={}))
    assert registry.enabled is False
    assert registry.resolve("anything") is None
    assert registry.resolve(None) is None


def test_registry_resolves_matching_token(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        tenant_backends={
            "taylor": TenantBackend(
                tenant_token="secret-a", lifeos_base_url="http://127.0.0.1:8001"
            ),
        },
    )
    registry = build_tenant_registry(settings)
    assert registry.enabled is True

    resolved = registry.resolve("secret-a")
    assert resolved is not None
    assert resolved.tenant_id == "taylor"
    assert resolved.router.lifeos is not None


@pytest.mark.parametrize("bad_token", [None, "", "wrong-token", "secret-a-but-longer"])
def test_registry_rejects_missing_or_unrecognized_token(tmp_path, bad_token):
    settings = Settings(
        data_dir=tmp_path,
        tenant_backends={
            "taylor": TenantBackend(
                tenant_token="secret-a", lifeos_base_url="http://127.0.0.1:8001"
            ),
        },
    )
    registry = build_tenant_registry(settings)
    assert registry.resolve(bad_token) is None


def test_registry_omits_agent_and_hermes_when_tenant_leaves_them_unset(tmp_path):
    """No separate enabled flag per tenant — presence of the URL is the switch (#41's rationale)."""
    settings = Settings(
        data_dir=tmp_path,
        tenant_backends={
            "taylor": TenantBackend(
                tenant_token="secret-a", lifeos_base_url="http://127.0.0.1:8001"
            ),
        },
    )
    registry = build_tenant_registry(settings)
    router = registry.resolve("secret-a").router
    assert router.agent is None
    assert router.hermes is None


def test_registry_includes_agent_and_hermes_when_tenant_sets_urls(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        tenant_backends={
            "taylor": TenantBackend(
                tenant_token="secret-a",
                lifeos_base_url="http://127.0.0.1:8001",
                agent_backend_url="http://127.0.0.1:8101",
                hermes_backend_url="http://127.0.0.1:8791",
            ),
        },
    )
    registry = build_tenant_registry(settings)
    router = registry.resolve("secret-a").router
    assert router.agent is not None
    assert router.hermes is not None


def test_build_tenant_registry_rejects_blank_token(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        tenant_backends={
            "taylor": TenantBackend(tenant_token="   ", lifeos_base_url="http://127.0.0.1:8001"),
        },
    )
    with pytest.raises(TenantConfigError):
        build_tenant_registry(settings)


def test_build_tenant_registry_rejects_duplicate_token(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        tenant_backends={
            "taylor": TenantBackend(
                tenant_token="same-secret", lifeos_base_url="http://127.0.0.1:8001"
            ),
            "nathan": TenantBackend(
                tenant_token="same-secret", lifeos_base_url="http://127.0.0.1:8002"
            ),
        },
    )
    with pytest.raises(TenantConfigError):
        build_tenant_registry(settings)


# --- routes/voice.py wiring: end-to-end over the ASGI app -----------------------


def _make_app(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null", lifeos_base_url="http://testserver")
    storage = TurnStorage(settings.turns_dir, settings.turn_retention_hours)
    default_stub = StubLifeOSClient("default-router answer — must never be reached in tenant mode")
    pipeline = TurnPipeline(
        settings,
        storage,
        StubSTTAdapter("remind me to call mom"),
        TextBackendRouter(default_stub),
        NullTTSAdapter(),
    )
    app = create_app(settings, pipeline=pipeline)
    return app, default_stub


@pytest.mark.asyncio
async def test_single_tenant_mode_ignores_tenant_header(tmp_path):
    """#40 AC: with TENANT_BACKENDS_JSON unset, single-tenant path is unchanged —
    the header is inert, not even inspected."""
    app, default_stub = _make_app(tmp_path)
    assert app.state.tenant_registry.enabled is False

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/voice/turn",
            data={"transcript": "hello"},
            headers={TENANT_TOKEN_HEADER: "some-value-nobody-configured"},
        )

    assert resp.status_code == 200
    assert resp.json()["response_text"] == default_stub.answer


@pytest.mark.asyncio
async def test_multi_tenant_each_token_reaches_only_its_own_backend(tmp_path):
    """The core #40 regression check: tenant A's turn must never be answered by
    tenant B's backend, and neither reaches the process-wide default router."""
    app, default_stub = _make_app(tmp_path)
    stub_a = StubLifeOSClient("answer for tenant A")
    stub_b = StubLifeOSClient("answer for tenant B")
    app.state.tenant_registry = TenantRegistry(
        {
            "token-a": ResolvedTenant(tenant_id="tenant-a", router=TextBackendRouter(stub_a)),
            "token-b": ResolvedTenant(tenant_id="tenant-b", router=TextBackendRouter(stub_b)),
        }
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp_a = await ac.post(
            "/api/voice/turn",
            data={"transcript": "hello from A"},
            headers={TENANT_TOKEN_HEADER: "token-a"},
        )
        resp_b = await ac.post(
            "/api/voice/turn",
            data={"transcript": "hello from B"},
            headers={TENANT_TOKEN_HEADER: "token-b"},
        )

    assert resp_a.status_code == 200
    assert resp_a.json()["response_text"] == "answer for tenant A"
    assert stub_a.last_question == "hello from A"

    assert resp_b.status_code == 200
    assert resp_b.json()["response_text"] == "answer for tenant B"
    assert stub_b.last_question == "hello from B"

    # Neither tenant's turn ever reached the other tenant's client or the default.
    assert stub_a.last_question != "hello from B"
    assert stub_b.last_question != "hello from A"
    assert default_stub.last_question is None


@pytest.mark.asyncio
async def test_multi_tenant_rejects_missing_token(tmp_path):
    app, default_stub = _make_app(tmp_path)
    app.state.tenant_registry = TenantRegistry(
        {
            "token-a": ResolvedTenant(
                tenant_id="tenant-a", router=TextBackendRouter(StubLifeOSClient())
            )
        }
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/voice/turn", data={"transcript": "hello"})

    assert resp.status_code == 403
    assert default_stub.last_question is None


@pytest.mark.asyncio
async def test_multi_tenant_rejects_unrecognized_token(tmp_path):
    app, default_stub = _make_app(tmp_path)
    app.state.tenant_registry = TenantRegistry(
        {
            "token-a": ResolvedTenant(
                tenant_id="tenant-a", router=TextBackendRouter(StubLifeOSClient())
            )
        }
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/voice/turn",
            data={"transcript": "hello"},
            headers={TENANT_TOKEN_HEADER: "not-a-configured-token"},
        )

    assert resp.status_code == 403
    assert default_stub.last_question is None


@pytest.mark.asyncio
async def test_multi_tenant_stream_endpoint_also_rejects_unknown_token(tmp_path):
    app, _default_stub = _make_app(tmp_path)
    app.state.tenant_registry = TenantRegistry(
        {
            "token-a": ResolvedTenant(
                tenant_id="tenant-a", router=TextBackendRouter(StubLifeOSClient())
            )
        }
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/voice/turn/stream", data={"transcript": "hello"})

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cancel_is_best_effort_when_tenant_unresolved(tmp_path, caplog):
    """Local cancel must still succeed even if the upstream tenant can't be
    resolved — cancel is best-effort by design (issue #37's doc comment)."""
    app, _default_stub = _make_app(tmp_path)
    app.state.tenant_registry = TenantRegistry(
        {
            "token-a": ResolvedTenant(
                tenant_id="tenant-a", router=TextBackendRouter(StubLifeOSClient())
            )
        }
    )
    app.state.turn_registry.start("turn-under-test", "lifeos")

    transport = ASGITransport(app=app)
    with caplog.at_level("WARNING"):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/voice/turn/turn-under-test/cancel")

    assert resp.status_code == 200
    assert resp.json() == {"cancelled": True}
    assert any("tenant" in record.message.lower() for record in caplog.records)
