"""Application configuration from environment variables."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEFAULT_DATA = Path.home() / ".local/share/whisper-relay"
_DEFAULT_KOKORO_DIR = _DEFAULT_DATA / "tts/kokoro"

# Opt-in for the dotenv fallback (issue #46). Two co-located instances can share
# one checkout's WorkingDirectory — each systemd unit supplies its own
# EnvironmentFile=, which populates the *process* environment directly, so
# Settings sees those values either way. pydantic-settings' default dotenv
# fallback instead resolves `./.env` relative to the CWD, which is shared
# between such instances; on the live host that path is a symlink to one
# operator's own env file, so a second instance whose own environment omits a
# key would silently inherit the first operator's value for it. Dotenv is only
# needed for a bare local-dev invocation with no EnvironmentFile= at all, so it
# is opt-in rather than a default.
_DOTENV_OPT_IN_VAR = "VOICE_GATEWAY_DOTENV"
_DOTENV_PATH_VAR = "VOICE_GATEWAY_DOTENV_FILE"


def _resolve_env_file() -> str | None:
    """The dotenv path Settings() should read, or None to use process env only.

    Read from `os.environ` at each Settings() construction (not baked into
    model_config at class-definition time) so tests can toggle it per case.
    """
    if os.environ.get(_DOTENV_OPT_IN_VAR, "").strip().lower() not in {"1", "true", "yes"}:
        return None
    return os.environ.get(_DOTENV_PATH_VAR, ".env")


class RequiredSettingError(RuntimeError):
    """A required setting is missing or invalid. Raised at startup only.

    Named to avoid colliding with `pydantic_settings.SettingsError` (a
    different, unrelated exception from the library `Settings` inherits
    from) — an `except SettingsError` written against this module could
    otherwise silently catch the wrong one depending on import order.
    """


class TenantBackend(BaseModel):
    """One tenant's backend targets, for a process serving more than one person (#40).

    Keyed by a tenant id in TENANT_BACKENDS_JSON (e.g. "taylor") — a label only,
    safe to log. `tenant_token` is the operator-issued secret that a request must
    present to be routed here; it is never derived from a client-suppliable field.
    Agent/Hermes are available for this tenant only when their URL is set — there
    is no separate enabled flag, and no loopback default (same rationale as #41).

    `extra="forbid"`: a misspelled key in TENANT_BACKENDS_JSON must fail startup
    loudly rather than being silently dropped (#48) — e.g. `lifeos_base_ur` would
    otherwise leave `lifeos_base_url` unset with no indication why.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_token: str
    lifeos_base_url: str
    lifeos_timeout_s: float = 300.0
    agent_backend_url: str | None = None
    agent_backend_timeout_s: float = 300.0
    agent_backend_token: str | None = None
    hermes_backend_url: str | None = None
    hermes_backend_timeout_s: float = 300.0
    hermes_backend_token: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    def __init__(self, **values: object) -> None:
        # Resolved fresh on every construction rather than baked into
        # model_config (issue #46) — see _resolve_env_file().
        values.setdefault("_env_file", _resolve_env_file())
        try:
            super().__init__(**values)
        except ValidationError as exc:
            # Both "the key is absent" (type "missing") and "the key is set to
            # blank/whitespace" (the field_validator below, type "value_error")
            # mean the same thing here: no usable LIFEOS_BASE_URL was given.
            bad_lifeos_url = any(
                err["loc"] and err["loc"][0] in {"LIFEOS_BASE_URL", "lifeos_base_url"}
                for err in exc.errors()
            )
            if bad_lifeos_url:
                raise RequiredSettingError(
                    "LIFEOS_BASE_URL is required and has no default (#49) — a "
                    "same-host default risks silently answering as another "
                    "operator's LifeOS. Set LIFEOS_BASE_URL in the environment."
                ) from exc
            raise

    host: str = Field(default="127.0.0.1", alias="VOICE_GATEWAY_HOST")
    port: int = Field(default=9788, alias="VOICE_GATEWAY_PORT")
    data_dir: Path = Field(default=_DEFAULT_DATA, alias="VOICE_GATEWAY_DATA_DIR")

    # Required, no default (#49): a same-host default would risk silently
    # answering as another operator's LifeOS on a shared host — the same class
    # of bug #41 fixed for agent/hermes. Both production instances set this
    # explicitly already.
    lifeos_base_url: str = Field(alias="LIFEOS_BASE_URL")
    lifeos_timeout_s: float = Field(default=300.0, alias="LIFEOS_TIMEOUT_S")

    @field_validator("lifeos_base_url")
    @classmethod
    def _lifeos_base_url_not_blank(cls, v: str) -> str:
        # A present-but-blank value (LIFEOS_BASE_URL= with nothing after it)
        # is exactly as unusable as an absent one — reject it the same way,
        # rather than letting an empty string quietly become the LifeOS
        # client's base URL.
        if not v.strip():
            raise ValueError("LIFEOS_BASE_URL must not be blank")
        return v

    # No same-host default: agent_backend_enabled defaults to True, and a backend
    # reachable by more than one person's deployment must never guess a loopback
    # address (#41) — an enabled-but-unaddressed backend is treated as unavailable
    # by build_text_backend_router, not silently pointed at whatever answers this
    # port on the host.
    agent_backend_url: str | None = Field(default=None, alias="AGENT_BACKEND_URL")
    agent_backend_timeout_s: float = Field(default=300.0, alias="AGENT_BACKEND_TIMEOUT_S")
    agent_backend_token: str | None = Field(default=None, alias="AGENT_BACKEND_TOKEN")
    agent_backend_enabled: bool = Field(default=True, alias="AGENT_BACKEND_ENABLED")

    # Same rationale as agent_backend_url above (#41) — no same-host default.
    # 8790 remains the value operators should set explicitly: it's the Hermes
    # LifeOS-adapter's own default (`LIFEOS_ADAPTER_PORT` in hermes
    # `lifeos_adapter/config.py`, documented in that repo's docs/adapter-operations.md).
    # Two repos independently picking a number is what broke this before (#35) —
    # follow the service, don't restate a guess as this gateway's own default.
    hermes_backend_url: str | None = Field(default=None, alias="HERMES_BACKEND_URL")
    hermes_backend_timeout_s: float = Field(default=300.0, alias="HERMES_BACKEND_TIMEOUT_S")
    hermes_backend_token: str | None = Field(default=None, alias="HERMES_BACKEND_TOKEN")
    hermes_backend_enabled: bool = Field(default=True, alias="HERMES_BACKEND_ENABLED")

    linux_whisper_config: Path | None = Field(default=None, alias="LINUX_WHISPER_CONFIG")
    ffmpeg_bin: str = Field(default="ffmpeg", alias="FFMPEG_BIN")
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, alias="VOICE_GATEWAY_MAX_UPLOAD_BYTES")
    max_audio_duration_s: float = Field(default=120.0, alias="VOICE_GATEWAY_MAX_AUDIO_DURATION_S")
    decode_timeout_s: float = Field(default=30.0, alias="VOICE_GATEWAY_DECODE_TIMEOUT_S")
    stt_timeout_s: float = Field(default=120.0, alias="VOICE_GATEWAY_STT_TIMEOUT_S")
    raw_stt_token: str | None = Field(default=None, alias="VOICE_GATEWAY_RAW_STT_TOKEN")

    @field_validator("raw_stt_token")
    @classmethod
    def _raw_stt_token_ascii(cls, value: str | None) -> str | None:
        # ASGI exposes header bytes as latin-1 text, while compare_digest rejects
        # non-ASCII str values. Reject an unusable configured secret at startup;
        # non-ASCII request bytes continue to fail closed as ordinary 401s.
        if value and not value.isascii():
            raise ValueError("VOICE_GATEWAY_RAW_STT_TOKEN must contain only ASCII characters")
        return value

    tts_backend: str = Field(default="kokoro", alias="TTS_BACKEND")
    kokoro_model_path: Path = Field(
        default=_DEFAULT_KOKORO_DIR / "kokoro-v1.0.onnx", alias="KOKORO_MODEL_PATH"
    )
    kokoro_voices_path: Path = Field(
        default=_DEFAULT_KOKORO_DIR / "voices-v1.0.bin", alias="KOKORO_VOICES_PATH"
    )
    kokoro_voice: str = Field(default="bm_george", alias="KOKORO_VOICE")
    kokoro_lang: str = Field(default="en-gb", alias="KOKORO_LANG")
    kokoro_speed: float = Field(default=1.0, alias="KOKORO_SPEED")

    turn_retention_hours: int = Field(default=24, alias="TURN_RETENTION_HOURS")

    # Per-tenant backend targets for a process serving more than one person (#40).
    # Empty by default: a deployment that never sets this is single-tenant and
    # behaves exactly as before — the settings above are the only backend targets,
    # and no tenant token is required or checked on any request.
    tenant_backends: dict[str, TenantBackend] = Field(
        default_factory=dict, alias="TENANT_BACKENDS_JSON"
    )

    @property
    def turns_dir(self) -> Path:
        return self.data_dir / "turns"


def get_settings() -> Settings:
    env_file = _resolve_env_file()
    if env_file is not None:
        logger.info(
            "settings: dotenv fallback enabled (%s=1), reading %s", _DOTENV_OPT_IN_VAR, env_file
        )
    else:
        logger.info(
            "settings: process environment only — no dotenv fallback (set %s=1 to opt in)",
            _DOTENV_OPT_IN_VAR,
        )
    return Settings()
