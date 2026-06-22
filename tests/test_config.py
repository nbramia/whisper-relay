"""Settings defaults (issue #22 — port reconciliation)."""

from voice_gateway.config import Settings


def test_default_voice_gateway_port_is_9788():
    settings = Settings.model_validate({})
    assert settings.port == 9788
