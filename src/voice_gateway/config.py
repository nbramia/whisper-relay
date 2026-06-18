"""Application configuration from environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_DATA = Path.home() / ".local/share/whisper-relay"
_DEFAULT_KOKORO_DIR = _DEFAULT_DATA / "tts/kokoro"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    host: str = Field(default="0.0.0.0", alias="VOICE_GATEWAY_HOST")
    port: int = Field(default=8888, alias="VOICE_GATEWAY_PORT")
    data_dir: Path = Field(default=_DEFAULT_DATA, alias="VOICE_GATEWAY_DATA_DIR")

    lifeos_base_url: str = Field(default="http://127.0.0.1:8000", alias="LIFEOS_BASE_URL")
    lifeos_timeout_s: float = Field(default=300.0, alias="LIFEOS_TIMEOUT_S")

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

    @property
    def turns_dir(self) -> Path:
        return self.data_dir / "turns"


def get_settings() -> Settings:
    return Settings()
