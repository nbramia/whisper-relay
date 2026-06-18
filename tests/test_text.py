from voice_gateway.text import strip_markdown_for_tts


def test_strip_markdown_links_and_bold():
    text = "See [docs](https://example.com) for **details**."
    assert strip_markdown_for_tts(text) == "See docs for details."


def test_strip_markdown_code_blocks():
    text = "Run `pip install` then:\n```python\nprint('hi')\n```"
    assert "pip install" in strip_markdown_for_tts(text)
    assert "print" not in strip_markdown_for_tts(text)
