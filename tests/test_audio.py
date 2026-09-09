import shutil
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from voice_gateway.audio import AudioNormalizationError, normalize_audio


def test_normalize_rejects_empty():
    with pytest.raises(AudioNormalizationError, match="empty"):
        normalize_audio(b"")


@patch("voice_gateway.audio.subprocess.run")
def test_normalize_happy_path(mock_run):
    """The decoder requests headerless PCM rather than slicing a WAV header."""
    pcm = b"\x00\x00" * 16_000

    def fake_run(cmd, **kwargs):
        assert "s16le" in cmd
        Path(cmd[-1]).write_bytes(pcm)
        return MagicMock(returncode=0, stderr=b"")

    mock_run.side_effect = fake_run
    result = normalize_audio(b"fake", content_type="audio/webm", filename="a.webm")
    assert result.sample_rate == 16_000
    assert result.duration_s == pytest.approx(1.0, rel=0.01)


@patch("voice_gateway.audio.subprocess.run")
def test_normalize_rejects_duration_after_bounded_raw_pcm_decode(mock_run):
    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"\x00\x00" * 16_001)
        return MagicMock(returncode=0, stderr=b"")

    mock_run.side_effect = fake_run
    with pytest.raises(AudioNormalizationError, match="exceeds"):
        normalize_audio(b"fake", max_duration_s=1)


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_real_decoder_ignores_extra_riff_chunks():
    """A legal JUNK chunk means the PCM data does not start at byte 44."""
    pcm = b"\x01\x00\xfe\xff" * 100
    fmt = struct.pack("<HHIIHH", 1, 1, 16_000, 32_000, 2, 16)
    junk = b"test"
    wav = (
        b"RIFF"
        + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(junk) + 8 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"JUNK"
        + struct.pack("<I", len(junk))
        + junk
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )

    result = normalize_audio(wav, content_type="audio/wav", filename="synthetic.wav")

    assert result.pcm_bytes == pcm
