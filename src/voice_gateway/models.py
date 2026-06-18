"""Pydantic response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TimingsMs(BaseModel):
    normalize: int = 0
    stt: int = 0
    polish: int = 0
    lifeos: int = 0
    tts: int = 0
    total: int = 0


class HandoffInfo(BaseModel):
    engine: str
    task: str
    message: str
    session_id: str = ""


class VoiceTurnResponse(BaseModel):
    turn_id: str
    transcript: str
    response_text: str
    audio_url: str
    status_audio_urls: list[str] = Field(default_factory=list)
    conversation_id: str | None = None
    handoff: HandoffInfo | None = None
    timings_ms: TimingsMs
