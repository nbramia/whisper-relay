"""Text utilities for TTS input."""

from __future__ import annotations

import re

_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_HEADER = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_CODE_FENCE = re.compile(r"```[\s\S]*?```|`([^`]+)`")
_MD_BOLD_ITALIC = re.compile(r"[*_]{1,3}([^*_]+)[*_]{1,3}")
_HRULE = re.compile(r"^---+$", re.MULTILINE)


def strip_markdown_for_tts(text: str) -> str:
    """Remove markdown constructs before speech synthesis."""
    if not text:
        return ""
    t = _MD_CODE_FENCE.sub(r"\1", text)
    t = _MD_LINK.sub(r"\1", t)
    t = _MD_BOLD_ITALIC.sub(r"\1", t)
    t = _MD_HEADER.sub("", t)
    t = _HRULE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t
