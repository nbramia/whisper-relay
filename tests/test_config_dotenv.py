"""Co-located instances must not inherit each other's .env (issue #46).

Two systemd units can share one checkout's `WorkingDirectory=` while each
supplies its own `EnvironmentFile=` directly into the process environment.
pydantic-settings' default dotenv fallback resolves `./.env` relative to the
CWD, which both instances share — on the live host that path is a symlink to
one operator's real env file. Settings must never fall back to it to fill in
a key an instance's own environment omits; `VOICE_GATEWAY_DOTENV=1` opts a
*local dev* invocation with no `EnvironmentFile=` into that fallback, and
production units never set it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from voice_gateway.config import Settings


@pytest.fixture
def other_operators_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A `.env` in the CWD carrying a value from a different, unrelated deployment —
    standing in for the maintainer's real `.env` symlinked into the shared
    WorkingDirectory on the live host."""
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("AGENT_BACKEND_URL=http://other-operators-backend:9999\n")
    return env_file


def test_missing_key_gets_code_default_not_the_other_files_value(
    other_operators_dotenv, monkeypatch: pytest.MonkeyPatch
):
    """The #46 regression check: an instance whose own environment omits
    AGENT_BACKEND_URL must get the code default (None), never the value that
    happens to sit in a `.env` file in the shared CWD."""
    monkeypatch.delenv("AGENT_BACKEND_URL", raising=False)
    monkeypatch.delenv("VOICE_GATEWAY_DOTENV", raising=False)
    monkeypatch.setenv("LIFEOS_BASE_URL", "http://127.0.0.1:8002")

    settings = Settings()

    assert settings.agent_backend_url is None


def test_own_environment_value_still_wins_over_dotenv(
    other_operators_dotenv, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("AGENT_BACKEND_URL", "http://this-instances-own-backend:8100")
    monkeypatch.delenv("VOICE_GATEWAY_DOTENV", raising=False)
    monkeypatch.setenv("LIFEOS_BASE_URL", "http://127.0.0.1:8002")

    settings = Settings()

    assert settings.agent_backend_url == "http://this-instances-own-backend:8100"


def test_dotenv_fallback_requires_explicit_opt_in(
    other_operators_dotenv, monkeypatch: pytest.MonkeyPatch
):
    """VOICE_GATEWAY_DOTENV=1 is documented for a bare local-dev invocation with
    no EnvironmentFile= at all — only then should the shared-directory .env be
    consulted."""
    monkeypatch.delenv("AGENT_BACKEND_URL", raising=False)
    monkeypatch.setenv("VOICE_GATEWAY_DOTENV", "1")
    monkeypatch.setenv("LIFEOS_BASE_URL", "http://127.0.0.1:8002")

    settings = Settings()

    assert settings.agent_backend_url == "http://other-operators-backend:9999"


def test_two_instance_env_dicts_never_cross_wire(
    other_operators_dotenv, monkeypatch: pytest.MonkeyPatch
):
    """Load Settings from env dicts shaped like each of the two live instances'
    key sets (synthetic values) with dotenv disabled — one omits
    AGENT_BACKEND_URL, and must never see the other's."""
    monkeypatch.delenv("VOICE_GATEWAY_DOTENV", raising=False)

    instance_a_keys = {
        "VOICE_GATEWAY_HOST": "127.0.0.1",
        "VOICE_GATEWAY_PORT": "9788",
        "LIFEOS_BASE_URL": "http://127.0.0.1:8000",
        "AGENT_BACKEND_URL": "http://127.0.0.1:8100",
        "AGENT_BACKEND_ENABLED": "true",
        "HERMES_BACKEND_URL": "http://127.0.0.1:8790",
        "HERMES_BACKEND_TOKEN": "instance-a-token",
        "HERMES_BACKEND_ENABLED": "true",
        "TTS_BACKEND": "null",
    }
    # instance_b omits AGENT_BACKEND_URL entirely — the pre-fix live incident.
    instance_b_keys = {
        "VOICE_GATEWAY_HOST": "0.0.0.0",
        "VOICE_GATEWAY_PORT": "9789",
        "VOICE_GATEWAY_DATA_DIR": str(other_operators_dotenv.parent / "data-b"),
        "LIFEOS_BASE_URL": "http://127.0.0.1:8002",
        "AGENT_BACKEND_ENABLED": "true",
        "HERMES_BACKEND_URL": "http://127.0.0.1:8790",
        "HERMES_BACKEND_TOKEN": "instance-b-token",
        "HERMES_BACKEND_ENABLED": "true",
        "TTS_BACKEND": "null",
    }

    for key in instance_a_keys:
        monkeypatch.delenv(key, raising=False)
    with monkeypatch.context() as m:
        for key, value in instance_a_keys.items():
            m.setenv(key, value)
        settings_a = Settings()

    for key in instance_a_keys:
        monkeypatch.delenv(key, raising=False)
    with monkeypatch.context() as m:
        for key, value in instance_b_keys.items():
            m.setenv(key, value)
        settings_b = Settings()

    assert settings_a.agent_backend_url == "http://127.0.0.1:8100"
    assert settings_b.agent_backend_url is None
    assert settings_b.hermes_backend_token == "instance-b-token"


def test_startup_logs_no_dotenv_fallback_by_default(monkeypatch, caplog):
    monkeypatch.delenv("VOICE_GATEWAY_DOTENV", raising=False)
    monkeypatch.setenv("LIFEOS_BASE_URL", "http://127.0.0.1:8000")
    from voice_gateway.config import get_settings

    with caplog.at_level("INFO"):
        get_settings()

    assert any("no dotenv fallback" in r.message for r in caplog.records)


def test_startup_logs_dotenv_source_when_opted_in(other_operators_dotenv, monkeypatch, caplog):
    monkeypatch.setenv("VOICE_GATEWAY_DOTENV", "1")
    monkeypatch.setenv("LIFEOS_BASE_URL", "http://127.0.0.1:8000")
    from voice_gateway.config import get_settings

    with caplog.at_level("INFO"):
        get_settings()

    assert any("dotenv fallback enabled" in r.message for r in caplog.records)
