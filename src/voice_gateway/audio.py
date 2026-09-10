"""Audio normalization via ffmpeg."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from voice_gateway.async_utils import await_bounded_task

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

_INPUT_FORMAT_BY_MIME: dict[str, str] = {
    "audio/webm": "matroska",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mp4": "mov",
    "audio/x-m4a": "mov",
    "audio/aac": "aac",
    "audio/mpeg": "mp3",
    "application/octet-stream": "mov",
}
_INPUT_FORMAT_BY_EXTENSION: dict[str, str] = {
    ".webm": "matroska",
    ".ogg": "ogg",
    ".wav": "wav",
    ".m4a": "mov",
    ".mp4": "mov",
    ".aac": "aac",
    ".mp3": "mp3",
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


def _input_format(content_type: str | None, filename: str | None) -> str:
    if content_type:
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type in _INPUT_FORMAT_BY_MIME:
            return _INPUT_FORMAT_BY_MIME[media_type]
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in _INPUT_FORMAT_BY_EXTENSION:
            return _INPUT_FORMAT_BY_EXTENSION[suffix]
    raise AudioNormalizationError("unsupported audio type")


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
    input_format = _input_format(content_type, filename)
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
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-f",
            input_format,
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
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=timeout_s,
            )
        except FileNotFoundError as exc:
            raise AudioNormalizationError(f"ffmpeg not found: {ffmpeg_bin}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AudioNormalizationError("audio decoding timed out") from exc

        if proc.returncode != 0:
            raise AudioNormalizationError("ffmpeg failed to decode audio")

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


async def normalize_audio_off_event_loop(
    data: bytes,
    *,
    content_type: str | None = None,
    filename: str | None = None,
    ffmpeg_bin: str = "ffmpeg",
    max_duration_s: float = 120.0,
    timeout_s: float = 30.0,
    normalizer: Callable[..., NormalizedAudio] | None = None,
) -> NormalizedAudio:
    """Wait for a self-bounded decoder even if the request task is cancelled."""
    task = asyncio.create_task(
        asyncio.to_thread(
            normalizer or normalize_audio,
            data,
            content_type=content_type,
            filename=filename,
            ffmpeg_bin=ffmpeg_bin,
            max_duration_s=max_duration_s,
            timeout_s=timeout_s,
        )
    )
    return await await_bounded_task(task)
