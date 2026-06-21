"""Shared pytest fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from voice_gateway.adapters.lifeos import LifeOSResult
from voice_gateway.adapters.stt import StubSTTAdapter
from voice_gateway.adapters.text_backend import TextBackendRouter
from voice_gateway.adapters.tts import NullTTSAdapter
from voice_gateway.config import Settings
from voice_gateway.main import create_app
from voice_gateway.storage import TurnStorage
from voice_gateway.turns import TurnPipeline

FIXTURES = Path(__file__).parent / "fixtures"


class StubLifeOSClient:
    def __init__(self, answer: str = "Here is your answer.") -> None:
        self.answer = answer
        self.last_question: str | None = None
        self.last_persona_id: str | None = None
        self.last_parse_handoff: bool = True
        self.last_list_persona_id: str | None = None

    async def ask(
        self,
        question,
        *,
        conversation_id,
        turn_id,
        on_status=None,
        cancel=None,
        persona_id=None,
        parse_handoff=True,
    ):
        self.last_question = question
        self.last_persona_id = persona_id
        self.last_parse_handoff = parse_handoff
        if on_status:
            await on_status("Searching your calendar…")
        return LifeOSResult(
            answer=self.answer,
            conversation_id=conversation_id or "conv-test-1",
            statuses=["Searching your calendar…"],
        )

    async def list_personas(self):
        return {
            "personas": [
                {"id": "primary", "label": "LifeOS", "capabilities": ["handoff", "agent"]},
                {"id": "fitness", "label": "Fitness", "capabilities": []},
                {"id": "doctor", "label": "Doctor", "capabilities": ["handoff"]},
            ]
        }

    async def list_conversations(self, *, persona_id=None):
        self.last_list_persona_id = persona_id
        return {
            "conversations": [
                {
                    "id": "conv-test-1",
                    "title": "Test conversation",
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-02T00:00:00",
                    "message_count": 2,
                    "persona_id": persona_id or "primary",
                }
            ]
        }

    async def get_conversation(self, conversation_id: str):
        return {
            "id": conversation_id,
            "title": "Test conversation",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-02T00:00:00",
            "messages": [
                {
                    "id": "m1",
                    "role": "user",
                    "content": "Hello",
                    "created_at": "2026-01-01T00:00:00",
                },
                {
                    "id": "m2",
                    "role": "assistant",
                    "content": "Hi there",
                    "created_at": "2026-01-01T00:01:00",
                },
            ],
        }


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, tts_backend="null", lifeos_base_url="http://testserver")


@pytest.fixture
def pipeline(tmp_settings: Settings) -> TurnPipeline:
    storage = TurnStorage(tmp_settings.turns_dir, tmp_settings.turn_retention_hours)
    stub = StubLifeOSClient()
    return TurnPipeline(
        tmp_settings,
        storage,
        StubSTTAdapter("remind me to call mom"),
        TextBackendRouter(stub),
        NullTTSAdapter(),
    )


@pytest.fixture
def app(tmp_settings: Settings, pipeline: TurnPipeline):
    return create_app(tmp_settings, pipeline=pipeline)


@pytest.fixture
async def client(app, pipeline):
    app.state.lifeos_personas = await pipeline._text_backend.lifeos.list_personas()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def lifeos_sse_fixture() -> str:
    return (FIXTURES / "lifeos_sse.txt").read_text(encoding="utf-8")


@pytest.fixture
def lifeos_handoff_fixture() -> dict:
    return json.loads((FIXTURES / "lifeos_handoff.json").read_text(encoding="utf-8"))
