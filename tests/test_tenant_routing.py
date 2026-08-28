"""Per-tenant backend routing (#40) — the fix for the wrong-tenant cross-wiring bug.

Two layers under test:
- voice_gateway.tenants: TenantRegistry / build_tenant_registry — resolves a
  per-request tenant token to that tenant's TextBackendRouter, or rejects.
- routes/voice.py wiring: single-tenant mode is unaffected; multi-tenant mode
  never falls through to the process-wide router for a missing/unrecognized
  token, and never cross-wires one tenant's turn to another tenant's backend.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

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


def test_build_tenant_registry_rejects_non_ascii_token(tmp_path):
    """A configured token that TenantRegistry.resolve() could never match
    anyway (it rejects non-ASCII candidates, see below) should fail startup,
    not silently configure an unreachable tenant (#48)."""
    settings = Settings(
        data_dir=tmp_path,
        tenant_backends={
            "taylor": TenantBackend(tenant_token="tok\xffen", lifeos_base_url="http://x"),
        },
    )
    with pytest.raises(TenantConfigError, match="non-ASCII"):
        build_tenant_registry(settings)


def test_build_tenant_registry_warns_on_empty_tenant_table(tmp_path, caplog):
    """TENANT_BACKENDS_JSON={} is distinct from unset: present but empty is
    likely a truncated or malformed edit, and should warn even though it still
    behaves as single-tenant (#48)."""
    settings = Settings(data_dir=tmp_path, tenant_backends={})

    with caplog.at_level("WARNING"):
        registry = build_tenant_registry(settings)

    assert registry.enabled is False
    assert any("TENANT_BACKENDS_JSON" in record.message for record in caplog.records)


def test_build_tenant_registry_no_warning_when_unset(tmp_path, caplog):
    """The default, unconfigured case — every production instance today —
    must not warn on every startup."""
    settings = Settings(data_dir=tmp_path)

    with caplog.at_level("WARNING"):
        build_tenant_registry(settings)

    assert not any("TENANT_BACKENDS_JSON" in record.message for record in caplog.records)


def test_tenant_backend_rejects_unknown_key():
    """extra='forbid' (#48): a misspelled key must fail loudly instead of being
    silently dropped — e.g. `lifeos_base_ur` would otherwise leave
    lifeos_base_url unset with no indication why."""
    with pytest.raises(ValidationError):
        TenantBackend(
            tenant_token="secret-a",
            lifeos_base_ur="http://127.0.0.1:8001",  # typo, missing required field too
        )


def test_registry_resolve_rejects_non_ascii_token(tmp_path):
    """A raw non-ASCII header byte used to raise inside hmac.compare_digest,
    surfacing as a 500 instead of the usual 403 for an unrecognized token (#48)."""
    settings = Settings(
        data_dir=tmp_path,
        tenant_backends={
            "taylor": TenantBackend(tenant_token="secret-a", lifeos_base_url="http://x"),
        },
    )
    registry = build_tenant_registry(settings)
    assert registry.resolve("\xff\xfe") is None


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
async def test_cancel_rejects_missing_token_before_touching_registry(tmp_path):
    """#48: cancel used to check the turn registry before any tenant check at
    all, so a caller with no token (or another tenant's token) could cancel
    another tenant's in-flight turn by id. Tenant resolution must now happen
    first, exactly like a voice turn — no fallback, no best-effort here."""
    app, _default_stub = _make_app(tmp_path)
    app.state.tenant_registry = TenantRegistry(
        {
            "token-a": ResolvedTenant(
                tenant_id="tenant-a", router=TextBackendRouter(StubLifeOSClient())
            )
        }
    )
    app.state.turn_registry.start("turn-under-test", "lifeos", tenant_id="tenant-a")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/voice/turn/turn-under-test/cancel")

    assert resp.status_code == 403
    # Nothing was cancelled or forwarded — the turn is still active.
    assert app.state.turn_registry.backend_for("turn-under-test", "tenant-a") == "lifeos"


@pytest.mark.asyncio
async def test_cancel_rejects_cross_tenant_turn_id(tmp_path):
    """The review's exact repro: tenant A's token presented against tenant B's
    turn id must 403 and forward nothing to either backend."""
    app, _default_stub = _make_app(tmp_path)
    stub_a = StubLifeOSClient("alice's backend")
    stub_b = StubLifeOSClient("bob's backend")
    app.state.tenant_registry = TenantRegistry(
        {
            "alice-token": ResolvedTenant(tenant_id="alice", router=TextBackendRouter(stub_a)),
            "bob-token": ResolvedTenant(tenant_id="bob", router=TextBackendRouter(stub_b)),
        }
    )
    app.state.turn_registry.start("bobs-turn", "lifeos", tenant_id="bob")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/voice/turn/bobs-turn/cancel",
            headers={TENANT_TOKEN_HEADER: "alice-token"},
        )

    assert resp.status_code == 403
    # Bob's turn is still active — alice's request never reached it, and
    # neither backend received an upstream cancel call.
    assert app.state.turn_registry.backend_for("bobs-turn", "bob") == "lifeos"
    assert stub_a.last_question is None
    assert stub_b.last_question is None


@pytest.mark.asyncio
async def test_cancel_succeeds_for_the_owning_tenant(tmp_path):
    app, _default_stub = _make_app(tmp_path)
    app.state.tenant_registry = TenantRegistry(
        {
            "alice-token": ResolvedTenant(
                tenant_id="alice", router=TextBackendRouter(StubLifeOSClient())
            ),
        }
    )
    cancel_event = app.state.turn_registry.start("alices-turn", "lifeos", tenant_id="alice")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/voice/turn/alices-turn/cancel",
            headers={TENANT_TOKEN_HEADER: "alice-token"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"cancelled": True}
    assert cancel_event.is_set()


@pytest.mark.asyncio
async def test_cancel_non_ascii_token_header_rejected_not_500(tmp_path):
    """A raw non-ASCII header byte used to raise inside hmac.compare_digest,
    surfacing as a 500 instead of the usual 403 for an unrecognized token (#48)."""
    app, _default_stub = _make_app(tmp_path)
    app.state.tenant_registry = TenantRegistry(
        {
            "alice-token": ResolvedTenant(
                tenant_id="alice", router=TextBackendRouter(StubLifeOSClient())
            ),
        }
    )
    app.state.turn_registry.start("turn-under-test", "lifeos", tenant_id="alice")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # httpx rejects a non-ASCII `str` header outright; pass raw bytes to
        # reach the server the way a raw non-ASCII header byte actually would
        # (Starlette decodes header bytes as latin-1).
        resp = await ac.post(
            "/api/voice/turn/turn-under-test/cancel",
            headers={TENANT_TOKEN_HEADER: b"\xff\xfe"},
        )

    assert resp.status_code == 403


# --- audio endpoints: tenant scoping (#50) --------------------------------------
#
# Stored-audio serving performs no tenant check at all before this fix: any
# caller who holds another tenant's turn id could fetch that tenant's audio.
# These tests mirror the cancel-scoping tests above — same #48 pattern, applied
# to `GET /api/voice/audio/{turn_id}` and `/{turn_id}/{clip_id}`.


async def _run_turn(ac: AsyncClient, token: str | None, transcript: str = "hello"):
    headers = {TENANT_TOKEN_HEADER: token} if token else {}
    resp = await ac.post("/api/voice/turn", data={"transcript": transcript}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_single_tenant_audio_unaffected(tmp_path):
    """Governing constraint: single-tenant mode must serve audio exactly as
    before #50 — same routes, same status codes, no tenant check performed."""
    app, _default_stub = _make_app(tmp_path)
    assert app.state.tenant_registry.enabled is False

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        turn = await _run_turn(ac, token=None)
        audio_resp = await ac.get(turn["audio_url"])

    assert audio_resp.status_code == 200
    assert "audio" in audio_resp.headers["content-type"]


@pytest.mark.asyncio
async def test_multi_tenant_audio_owning_tenant_succeeds(tmp_path):
    app, _default_stub = _make_app(tmp_path)
    app.state.tenant_registry = TenantRegistry(
        {
            "alice-token": ResolvedTenant(
                tenant_id="alice", router=TextBackendRouter(StubLifeOSClient())
            ),
        }
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        turn = await _run_turn(ac, token="alice-token")
        audio_resp = await ac.get(turn["audio_url"], headers={TENANT_TOKEN_HEADER: "alice-token"})
        # Status-clip variant of the same endpoint family, same owning tenant.
        status_resp = await ac.get(
            turn["status_audio_urls"][0], headers={TENANT_TOKEN_HEADER: "alice-token"}
        )

    assert audio_resp.status_code == 200
    assert "audio" in audio_resp.headers["content-type"]
    assert status_resp.status_code == 200


@pytest.mark.asyncio
async def test_multi_tenant_audio_rejects_cross_tenant_turn_id(tmp_path):
    """The review's exact repro, applied to audio: tenant A's token presented
    against tenant B's turn id must 403 and serve no bytes."""
    app, _default_stub = _make_app(tmp_path)
    app.state.tenant_registry = TenantRegistry(
        {
            "alice-token": ResolvedTenant(
                tenant_id="alice", router=TextBackendRouter(StubLifeOSClient())
            ),
            "bob-token": ResolvedTenant(
                tenant_id="bob", router=TextBackendRouter(StubLifeOSClient())
            ),
        }
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        bobs_turn = await _run_turn(ac, token="bob-token")
        resp = await ac.get(bobs_turn["audio_url"], headers={TENANT_TOKEN_HEADER: "alice-token"})
        clip_resp = await ac.get(
            bobs_turn["status_audio_urls"][0], headers={TENANT_TOKEN_HEADER: "alice-token"}
        )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "audio not found"
    assert "audio" not in resp.headers.get("content-type", "")
    assert clip_resp.status_code == 403

    # The owning tenant can still fetch its own audio afterward — the mismatch
    # check for someone else didn't consume or corrupt anything.
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        own_resp = await ac.get(bobs_turn["audio_url"], headers={TENANT_TOKEN_HEADER: "bob-token"})
    assert own_resp.status_code == 200


@pytest.mark.asyncio
async def test_multi_tenant_audio_rejects_missing_token(tmp_path):
    app, _default_stub = _make_app(tmp_path)
    app.state.tenant_registry = TenantRegistry(
        {
            "alice-token": ResolvedTenant(
                tenant_id="alice", router=TextBackendRouter(StubLifeOSClient())
            ),
        }
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        turn = await _run_turn(ac, token="alice-token")
        resp = await ac.get(turn["audio_url"])

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_multi_tenant_audio_rejects_unrecognized_token(tmp_path):
    app, _default_stub = _make_app(tmp_path)
    app.state.tenant_registry = TenantRegistry(
        {
            "alice-token": ResolvedTenant(
                tenant_id="alice", router=TextBackendRouter(StubLifeOSClient())
            ),
        }
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        turn = await _run_turn(ac, token="alice-token")
        resp = await ac.get(
            turn["audio_url"], headers={TENANT_TOKEN_HEADER: "not-a-configured-token"}
        )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_multi_tenant_audio_invalid_uuid_still_404s_with_valid_token(tmp_path):
    """A well-formed token but a malformed turn_id should fail the same way it
    always has (404), not surface a 403 or a 500 from the tenant check."""
    app, _default_stub = _make_app(tmp_path)
    app.state.tenant_registry = TenantRegistry(
        {
            "alice-token": ResolvedTenant(
                tenant_id="alice", router=TextBackendRouter(StubLifeOSClient())
            ),
        }
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/voice/audio/not-a-uuid", headers={TENANT_TOKEN_HEADER: "alice-token"}
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_multi_tenant_audio_legacy_clip_with_no_tenant_tag_is_fail_closed(tmp_path):
    """A clip written with no tenant tag at all — e.g. one written while the
    process ran in single-tenant mode, before TENANT_BACKENDS_JSON was
    introduced on this host — must not become reachable by anyone once
    multi-tenant mode is turned on (#50's documented fail-closed decision for
    legacy clips), even by the operator who presents a perfectly valid token."""
    app, _default_stub = _make_app(tmp_path)

    # Write a turn directly through storage with no tenant.json, simulating a
    # pre-existing clip from before multi-tenant mode existed on this host.
    storage: TurnStorage = app.state.storage
    legacy_turn_id = str(uuid4())
    clip_path = storage.clip_path(legacy_turn_id, "main")
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    clip_path.write_bytes(b"RIFF....WAVEfmt ")
    assert storage.read_tenant_id(legacy_turn_id) is None

    app.state.tenant_registry = TenantRegistry(
        {
            "alice-token": ResolvedTenant(
                tenant_id="alice", router=TextBackendRouter(StubLifeOSClient())
            ),
        }
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            f"/api/voice/audio/{legacy_turn_id}", headers={TENANT_TOKEN_HEADER: "alice-token"}
        )

    assert resp.status_code == 403


@pytest.mark.parametrize("raw", ["null", "[]"])
@pytest.mark.asyncio
async def test_multi_tenant_audio_corrupted_tenant_sidecar_is_fail_closed(tmp_path, raw):
    """A tenant.json that parses as valid JSON but isn't the expected object
    shape (e.g. `null` or `[]` from a corrupted or hand-edited write) must
    403, not 500 (#50 review follow-up) — same fail-closed outcome as a
    missing sidecar, and zero clip bytes served either way."""
    app, _default_stub = _make_app(tmp_path)

    storage: TurnStorage = app.state.storage
    turn_id = str(uuid4())
    clip_path = storage.clip_path(turn_id, "main")
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    clip_path.write_bytes(b"RIFF....WAVEfmt ")
    (storage.turn_path(turn_id) / "tenant.json").write_text(raw, encoding="utf-8")
    assert storage.read_tenant_id(turn_id) is None

    app.state.tenant_registry = TenantRegistry(
        {
            "alice-token": ResolvedTenant(
                tenant_id="alice", router=TextBackendRouter(StubLifeOSClient())
            ),
        }
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            f"/api/voice/audio/{turn_id}", headers={TENANT_TOKEN_HEADER: "alice-token"}
        )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "audio not found"
    assert "audio" not in resp.headers.get("content-type", "")
