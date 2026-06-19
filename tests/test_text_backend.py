import pytest

from conftest import StubLifeOSClient
from voice_gateway.adapters.text_backend import (
    BACKEND_AGENT,
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
        ("codex", BACKEND_LIFEOS),
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
