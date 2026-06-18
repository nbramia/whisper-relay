from unittest.mock import MagicMock, patch

import pytest

from voice_gateway.audio import AudioNormalizationError, normalize_audio


def test_normalize_rejects_empty():
    with pytest.raises(AudioNormalizationError, match="empty"):
        normalize_audio(b"")


@patch("voice_gateway.audio.subprocess.run")
def test_normalize_happy_path(mock_run):
    # minimal wav: 44 byte header + 32000 bytes pcm = 1 second at 16kHz mono s16
    pcm = b"\x00\x00" * 16_000
    header = b"RIFF" + (36 + len(pcm)).to_bytes(4, "little") + b"WAVEfmt "
    mock_run.return_value = MagicMock(returncode=0, stdout=header + pcm, stderr=b"")
    result = normalize_audio(b"fake", content_type="audio/webm", filename="a.webm")
    assert result.sample_rate == 16_000
    assert result.duration_s == pytest.approx(1.0, rel=0.01)
