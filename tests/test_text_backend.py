import pytest

from conftest import StubLifeOSClient
from voice_gateway.adapters.text_backend import (
    BACKEND_AGENT,
    BACKEND_HERMES,
    BACKEND_LIFEOS,
    TextBackendRouter,
    TextBackendUnavailableError,
    normalize_backend,
)
from voice_gateway.config import Settings
from voice_gateway.main import build_text_backend_router


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, BACKEND_LIFEOS),
        ("", BACKEND_LIFEOS),
        ("lifeos", BACKEND_LIFEOS),
        ("LIFEOS", BACKEND_LIFEOS),
        ("agent", BACKEND_AGENT),
        (" Agent ", BACKEND_AGENT),
        ("hermes", BACKEND_HERMES),
        ("HERMES", BACKEND_HERMES),
        (" Hermes ", BACKEND_HERMES),
        ("codex", BACKEND_LIFEOS),
        ("hermes-2", BACKEND_LIFEOS),
    ],
)
def test_normalize_backend(raw, expected):
    assert normalize_backend(raw) == expected


def test_text_backend_router_agent_missing_raises():
    router = TextBackendRouter(StubLifeOSClient())
    with pytest.raises(TextBackendUnavailableError):
        router.client_for("agent")


def test_build_text_backend_router_includes_agent_when_enabled(tmp_path):
    settings = Settings(data_dir=tmp_path, agent_backend_enabled=True)
    router = build_text_backend_router(settings)
    assert router.agent is not None
    assert router.client_for("agent") is router.agent


def test_build_text_backend_router_omits_agent_when_disabled(tmp_path):
    settings = Settings(data_dir=tmp_path, agent_backend_enabled=False)
    router = build_text_backend_router(settings)
    assert router.agent is None


def test_text_backend_router_hermes_missing_raises():
    router = TextBackendRouter(StubLifeOSClient())
    with pytest.raises(TextBackendUnavailableError):
        router.client_for("hermes")


def test_build_text_backend_router_includes_hermes_when_enabled(tmp_path):
    settings = Settings(data_dir=tmp_path, hermes_backend_enabled=True)
    router = build_text_backend_router(settings)
    assert router.hermes is not None
    assert router.client_for("hermes") is router.hermes


def test_build_text_backend_router_omits_hermes_when_disabled(tmp_path):
    settings = Settings(data_dir=tmp_path, hermes_backend_enabled=False)
    router = build_text_backend_router(settings)
    assert router.hermes is None
    with pytest.raises(TextBackendUnavailableError):
        router.client_for("hermes")


def test_unknown_backend_still_routes_to_lifeos(tmp_path):
    lifeos = StubLifeOSClient()
    router = TextBackendRouter(lifeos)
    assert router.client_for("codex") is lifeos
