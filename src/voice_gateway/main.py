"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import logging

from voice_gateway.adapters.lifeos import HTTPLifeOSClient
from voice_gateway.adapters.stt import LinuxWhisperSTTAdapter
from voice_gateway.adapters.tts import build_tts_adapter
from voice_gateway.config import Settings, get_settings
from voice_gateway.logging import configure_logging
from voice_gateway.routes import conversations, health, voice
from voice_gateway.storage import TurnStorage
from voice_gateway.turns import TurnPipeline

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage: TurnStorage = app.state.storage
    storage.cleanup_expired()
    pipeline: TurnPipeline = app.state.pipeline
    try:
        await pipeline.warmup()
        logger.info("voice adapters warmed up")
    except Exception:
        logger.exception("adapter warmup failed — first turn may be slower")
    yield


def create_app(
    settings: Settings | None = None,
    *,
    pipeline: TurnPipeline | None = None,
) -> FastAPI:
    configure_logging()
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    storage = TurnStorage(settings.turns_dir, settings.turn_retention_hours)
    if pipeline is None:
        stt = LinuxWhisperSTTAdapter(settings)
        lifeos = HTTPLifeOSClient(settings.lifeos_base_url, settings.lifeos_timeout_s)
        tts = build_tts_adapter(settings)
        pipeline = TurnPipeline(settings, storage, stt, lifeos, tts)
    else:
        storage = pipeline._storage
        lifeos = pipeline._lifeos

    app = FastAPI(title="whisper-relay", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.storage = storage
    app.state.pipeline = pipeline
    app.state.lifeos_client = lifeos

    app.include_router(health.router)
    app.include_router(voice.router)
    app.include_router(conversations.router)

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


app = create_app()
