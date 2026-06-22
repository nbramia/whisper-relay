"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from voice_gateway.adapters.agent_backend import HTTPAgentBackendClient
from voice_gateway.adapters.lifeos import HTTPLifeOSClient
from voice_gateway.adapters.stt import LinuxWhisperSTTAdapter
from voice_gateway.adapters.text_backend import TextBackendRouter
from voice_gateway.adapters.tts import build_tts_adapter
from voice_gateway.cancel import TurnRegistry
from voice_gateway.config import Settings, get_settings
from voice_gateway.logging import configure_logging
from voice_gateway.routes import health, root, voice
from voice_gateway.storage import TurnStorage
from voice_gateway.turns import TurnPipeline

logger = logging.getLogger(__name__)


def build_text_backend_router(settings: Settings) -> TextBackendRouter:
    lifeos = HTTPLifeOSClient(settings.lifeos_base_url, settings.lifeos_timeout_s)
    agent: HTTPAgentBackendClient | None = None
    if settings.agent_backend_enabled:
        agent = HTTPAgentBackendClient(
            settings.agent_backend_url,
            settings.agent_backend_timeout_s,
            api_token=settings.agent_backend_token,
        )
    return TextBackendRouter(lifeos, agent)


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

    router: TextBackendRouter = app.state.text_backend_router
    if router.agent is not None and isinstance(router.agent, HTTPAgentBackendClient):
        try:
            ok = await router.agent.health_check()
            if ok:
                logger.info("agent backend health check ok")
            else:
                logger.warning("agent backend health check returned not ok")
        except Exception:
            logger.warning("agent backend unreachable at startup — Agent mode may fail")

    try:
        app.state.lifeos_personas = await router.lifeos.list_personas()
    except Exception:
        logger.warning("LifeOS personas unavailable at startup — using primary default")
        app.state.lifeos_personas = {
            "personas": [
                {"id": "primary", "label": "LifeOS", "capabilities": ["handoff", "agent"]},
            ]
        }

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
    text_backend = build_text_backend_router(settings)
    if pipeline is None:
        stt = LinuxWhisperSTTAdapter(settings)
        tts = build_tts_adapter(settings)
        pipeline = TurnPipeline(settings, storage, stt, text_backend, tts)
    else:
        storage = pipeline._storage
        text_backend = pipeline._text_backend

    app = FastAPI(title="whisper-relay", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.storage = storage
    app.state.pipeline = pipeline
    app.state.text_backend_router = text_backend
    app.state.lifeos_client = text_backend.lifeos
    app.state.lifeos_personas = {
        "personas": [
            {"id": "primary", "label": "LifeOS", "capabilities": ["handoff", "agent"]},
        ]
    }
    app.state.turn_registry = TurnRegistry()

    app.include_router(health.router)
    app.include_router(voice.router)
    app.include_router(root.router)

    return app


app = create_app()
