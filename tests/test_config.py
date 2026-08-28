"""Settings defaults (issues #22, #35 — port reconciliation; #41 — no shared-host default;
#49 — LIFEOS_BASE_URL required)."""

import pytest

from voice_gateway.config import RequiredSettingError, Settings


def test_default_voice_gateway_port_is_9788():
    settings = Settings.model_validate({"lifeos_base_url": "http://example.invalid"})
    assert settings.port == 9788


def _code_defaults() -> Settings:
    """Settings as a fresh install sees them, ignoring this machine's .env."""
    return Settings(_env_file=None, LIFEOS_BASE_URL="http://example.invalid")


def test_hermes_backend_url_has_no_default():
    """A backend reachable by more than one person's deployment must never carry a
    same-host default (#41): agent_backend_enabled/hermes_backend_enabled are both
    True out of the box, so a loopback default here would silently point a newly
    added tenant at whatever backend already answers that port on a shared host.
    8790 is still the value operators should set explicitly — it's the Hermes
    LifeOS-adapter's own LIFEOS_ADAPTER_PORT default (issue #35) — but this gateway
    must not guess it. Check the effective value with GET /health/backends, which
    reports reachability, not just configuration.
    """
    assert _code_defaults().hermes_backend_url is None


def test_agent_backend_url_has_no_default():
    """Same rationale as hermes above (#41)."""
    assert _code_defaults().agent_backend_url is None


def test_hermes_backend_url_honours_env_override():
    settings = Settings(_env_file=None, HERMES_BACKEND_URL="http://127.0.0.1:9999")
    assert settings.hermes_backend_url == "http://127.0.0.1:9999"


def test_agent_backend_url_honours_env_override():
    settings = Settings(_env_file=None, AGENT_BACKEND_URL="http://127.0.0.1:8100")
    assert settings.agent_backend_url == "http://127.0.0.1:8100"


def test_lifeos_base_url_is_required(monkeypatch: pytest.MonkeyPatch):
    """#49: the primary backend must never default to a same-host address —
    that's the exact #40 failure mode (a second instance silently answered by
    the first operator's LifeOS)."""
    monkeypatch.delenv("LIFEOS_BASE_URL", raising=False)
    with pytest.raises(RequiredSettingError, match="LIFEOS_BASE_URL"):
        Settings(_env_file=None)


def test_lifeos_base_url_honours_env_override():
    settings = Settings(_env_file=None, LIFEOS_BASE_URL="http://127.0.0.1:8002")
    assert settings.lifeos_base_url == "http://127.0.0.1:8002"


@pytest.mark.parametrize("blank", ["", "   "])
def test_lifeos_base_url_blank_is_rejected_same_as_missing(blank):
    """LIFEOS_BASE_URL= (present but empty) is exactly as unusable as an
    absent value — it must not quietly become the LifeOS client's base URL."""
    with pytest.raises(RequiredSettingError, match="LIFEOS_BASE_URL"):
        Settings(_env_file=None, LIFEOS_BASE_URL=blank)


def test_both_production_instances_key_sets_still_start():
    """Both live instances set LIFEOS_BASE_URL, HERMES_BACKEND_URL, and
    AGENT_BACKEND_ENABLED explicitly; Taylor's additionally sets
    AGENT_BACKEND_URL to an explicit empty string. Neither sets
    TENANT_BACKENDS_JSON. This must keep starting unchanged (#46, #49)."""
    maintainer_env = {
        "VOICE_GATEWAY_HOST": "127.0.0.1",
        "VOICE_GATEWAY_PORT": "9788",
        "LIFEOS_BASE_URL": "http://127.0.0.1:8000",
        "AGENT_BACKEND_URL": "http://127.0.0.1:8100",
        "AGENT_BACKEND_ENABLED": "true",
        "HERMES_BACKEND_URL": "http://127.0.0.1:8790",
        "HERMES_BACKEND_TOKEN": "maintainer-hermes-token",
        "HERMES_BACKEND_ENABLED": "true",
        "TTS_BACKEND": "null",
    }
    taylor_env = {
        "VOICE_GATEWAY_HOST": "0.0.0.0",
        "VOICE_GATEWAY_PORT": "9789",
        "LIFEOS_BASE_URL": "http://127.0.0.1:8002",
        "AGENT_BACKEND_ENABLED": "true",
        "AGENT_BACKEND_URL": "",
        "HERMES_BACKEND_URL": "http://127.0.0.1:8790",
        "HERMES_BACKEND_TOKEN": "taylor-hermes-token",
        "HERMES_BACKEND_ENABLED": "true",
        "TTS_BACKEND": "null",
    }

    maintainer = Settings(_env_file=None, **maintainer_env)
    taylor = Settings(_env_file=None, **taylor_env)

    assert maintainer.lifeos_base_url == "http://127.0.0.1:8000"
    assert maintainer.agent_backend_url == "http://127.0.0.1:8100"
    assert maintainer.tenant_backends == {}

    assert taylor.lifeos_base_url == "http://127.0.0.1:8002"
    # Explicit empty string, not the maintainer's URL — falsy, so
    # build_text_backend_router treats it as unavailable, same as unset.
    assert not taylor.agent_backend_url
    assert taylor.tenant_backends == {}

    from voice_gateway.main import build_text_backend_router

    taylor_router = build_text_backend_router(taylor)
    assert taylor_router.agent is None
