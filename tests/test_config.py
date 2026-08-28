"""Settings defaults (issues #22, #35 — port reconciliation; #41 — no shared-host default)."""

from voice_gateway.config import Settings


def test_default_voice_gateway_port_is_9788():
    settings = Settings.model_validate({})
    assert settings.port == 9788


def _code_defaults() -> Settings:
    """Settings as a fresh install sees them, ignoring this machine's .env."""
    return Settings(_env_file=None)


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


def test_lifeos_base_url_default_unchanged():
    """LifeOS is out of scope for #41: it has no *_enabled toggle, and both
    production deployments already set LIFEOS_BASE_URL explicitly."""
    assert _code_defaults().lifeos_base_url == "http://127.0.0.1:8000"
