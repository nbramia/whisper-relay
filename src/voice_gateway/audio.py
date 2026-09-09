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
    timeout_s: float = 30.0,
) -> NormalizedAudio:
    if not data:
        raise AudioNormalizationError("empty audio upload")

    ext = _guess_extension(content_type, filename)
    with tempfile.TemporaryDirectory() as tmp:
        inp = Path(tmp) / f"input{ext}"
        inp.write_bytes(data)
        output = Path(tmp) / "normalized.s16le"
        # Headerless PCM is deliberate: WAV permits arbitrary chunks before
        # ``data`` so slicing a presumed 44-byte header can send container
        # bytes to recognition. ``-t`` bounds expansion of hostile compressed
        # uploads before we read the decoded result into memory.
        decode_limit_s = max_duration_s + 1 / 16_000
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(inp),
            "-t",
            str(decode_limit_s),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "s16le",
            str(output),
        ]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout_s,
            )
        except FileNotFoundError as exc:
            raise AudioNormalizationError(f"ffmpeg not found: {ffmpeg_bin}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AudioNormalizationError("audio decoding timed out") from exc

        if proc.returncode != 0:
            stderr = proc.stderr.decode(errors="replace")[:500]
            raise AudioNormalizationError(f"ffmpeg failed: {stderr}")

        if not output.exists() or output.stat().st_size == 0:
            raise AudioNormalizationError("ffmpeg produced empty output")

        pcm = output.read_bytes()
        if len(pcm) % 2:
            raise AudioNormalizationError("ffmpeg produced invalid PCM")
        duration_s = len(pcm) / (16_000 * 2)
        if duration_s > max_duration_s:
            raise AudioNormalizationError(f"audio exceeds {max_duration_s}s limit")

        return NormalizedAudio(pcm_bytes=pcm, duration_s=duration_s)


def pcm_to_float32(pcm_bytes: bytes) -> np.ndarray:
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    return (samples.astype(np.float32) / 32767.0).copy()
