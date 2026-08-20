"""Settings defaults (issues #22, #35 — port reconciliation)."""

from voice_gateway.config import Settings


def test_default_voice_gateway_port_is_9788():
    settings = Settings.model_validate({})
    assert settings.port == 9788


def _code_defaults() -> Settings:
    """Settings as a fresh install sees them, ignoring this machine's .env."""
    return Settings(_env_file=None)


def test_default_hermes_backend_url_matches_adapter_port():
    """8790 is the Hermes LifeOS-adapter's own LIFEOS_ADAPTER_PORT default (issue #35).

    This repo follows that value; it does not pick one. Two repositories choosing
    independently is what left the backend configured-but-unreachable. A machine
    whose .env overrides this is a separate question — check the effective value
    with GET /health/backends, which reports reachability, not just configuration.
    """
    assert _code_defaults().hermes_backend_url == "http://127.0.0.1:8790"


def test_hermes_backend_url_honours_env_override():
    settings = Settings(_env_file=None, HERMES_BACKEND_URL="http://127.0.0.1:9999")
    assert settings.hermes_backend_url == "http://127.0.0.1:9999"


def test_other_backend_defaults_unchanged():
    settings = _code_defaults()
    assert settings.lifeos_base_url == "http://127.0.0.1:8000"
    assert settings.agent_backend_url == "http://127.0.0.1:8100"
