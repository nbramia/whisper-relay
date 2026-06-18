"""Audio normalization via ffmpeg."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_EXT_BY_MIME: dict[str, str] = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/mpeg": ".mp3",
    "application/octet-stream": ".m4a",
}


@dataclass(frozen=True, slots=True)
class NormalizedAudio:
    pcm_bytes: bytes
    sample_rate: int = 16_000
    duration_s: float = 0.0


class AudioNormalizationError(Exception):
    """Uploaded audio could not be normalized."""


def _guess_extension(content_type: str | None, filename: str | None) -> str:
    if filename and "." in filename:
        return Path(filename).suffix
    if content_type:
        base = content_type.split(";")[0].strip().lower()
        if base in _EXT_BY_MIME:
            return _EXT_BY_MIME[base]
    return ".webm"


def normalize_audio(
    data: bytes,
    *,
    content_type: str | None = None,
    filename: str | None = None,
    ffmpeg_bin: str = "ffmpeg",
    max_duration_s: float = 120.0,
) -> NormalizedAudio:
    if not data:
        raise AudioNormalizationError("empty audio upload")

    ext = _guess_extension(content_type, filename)
    with tempfile.TemporaryDirectory() as tmp:
        inp = Path(tmp) / f"input{ext}"
        inp.write_bytes(data)
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(inp),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "wav",
            "pipe:1",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, check=False)
        except FileNotFoundError as exc:
            raise AudioNormalizationError(f"ffmpeg not found: {ffmpeg_bin}") from exc

        if proc.returncode != 0:
            stderr = proc.stderr.decode(errors="replace")[:500]
            raise AudioNormalizationError(f"ffmpeg failed: {stderr}")

        wav = proc.stdout
        if len(wav) < 44:
            raise AudioNormalizationError("ffmpeg produced empty output")

        pcm = wav[44:]
        duration_s = len(pcm) / (16_000 * 2)
        if duration_s > max_duration_s:
            raise AudioNormalizationError(f"audio exceeds {max_duration_s}s limit")

        return NormalizedAudio(pcm_bytes=pcm, duration_s=duration_s)


def pcm_to_float32(pcm_bytes: bytes) -> np.ndarray:
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    return (samples.astype(np.float32) / 32767.0).copy()
