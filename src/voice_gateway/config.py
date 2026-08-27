"""Application configuration from environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_DATA = Path.home() / ".local/share/whisper-relay"
_DEFAULT_KOKORO_DIR = _DEFAULT_DATA / "tts/kokoro"


class TenantBackend(BaseModel):
    """One tenant's backend targets, for a process serving more than one person (#40).

    Keyed by a tenant id in TENANT_BACKENDS_JSON (e.g. "taylor") — a label only,
    safe to log. `tenant_token` is the operator-issued secret that a request must
    present to be routed here; it is never derived from a client-suppliable field.
    Agent/Hermes are available for this tenant only when their URL is set — there
    is no separate enabled flag, and no loopback default (same rationale as #41).
    """

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
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    host: str = Field(default="0.0.0.0", alias="VOICE_GATEWAY_HOST")
    port: int = Field(default=9788, alias="VOICE_GATEWAY_PORT")
    data_dir: Path = Field(default=_DEFAULT_DATA, alias="VOICE_GATEWAY_DATA_DIR")

    lifeos_base_url: str = Field(default="http://127.0.0.1:8000", alias="LIFEOS_BASE_URL")
    lifeos_timeout_s: float = Field(default=300.0, alias="LIFEOS_TIMEOUT_S")

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
    return Settings()
