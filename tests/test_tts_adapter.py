import pytest

from voice_gateway.adapters.tts import NullTTSAdapter
from voice_gateway.text import strip_markdown_for_tts


@pytest.mark.asyncio
async def test_null_tts_writes_wav(tmp_path):
    adapter = NullTTSAdapter()
    out = tmp_path / "main.wav"
    result = await adapter.synthesize("**Hello** world", turn_id="t1", out_path=out)
    assert result.path.is_file()
    assert result.backend == "null"
    assert result.mime_type == "audio/wav"


def test_strip_markdown():
    assert strip_markdown_for_tts("**Hi** [link](http://x.com)") == "Hi link"
