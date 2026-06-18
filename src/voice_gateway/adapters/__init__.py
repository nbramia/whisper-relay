"""Adapter protocols and implementations."""

from voice_gateway.adapters.lifeos import HTTPLifeOSClient, LifeOSClient, LifeOSResult
from voice_gateway.adapters.stt import LinuxWhisperSTTAdapter, STTAdapter, StubSTTAdapter
from voice_gateway.adapters.tts import TTSAdapter, TTSResult, build_tts_adapter

__all__ = [
    "HTTPLifeOSClient",
    "LifeOSClient",
    "LifeOSResult",
    "LinuxWhisperSTTAdapter",
    "STTAdapter",
    "StubSTTAdapter",
    "TTSAdapter",
    "TTSResult",
    "build_tts_adapter",
]
