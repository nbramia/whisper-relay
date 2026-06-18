from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from conftest import StubLifeOSClient
from voice_gateway.adapters.agent_backend import HTTPAgentBackendClient
from voice_gateway.adapters.text_backend import TextBackendRouter
from voice_gateway.config import Settings
from voice_gateway.main import create_app


@pytest.mark.asyncio
async def test_health_backends_reports_reachability(client):
    app = client._transport.app
    agent = HTTPAgentBackendClient("http://agent.test")
    app.state.text_backend_router = TextBackendRouter(StubLifeOSClient(), agent)

    mock_lifeos_resp = MagicMock()
    mock_lifeos_resp.status_code = 200

    with (
        patch("voice_gateway.routes.health.httpx.AsyncClient") as lifeos_http_cls,
        patch.object(agent, "health_check", new=AsyncMock(return_value=True)),
    ):
        lifeos_http = AsyncMock()
        lifeos_http.get = AsyncMock(return_value=mock_lifeos_resp)
        lifeos_http.__aenter__ = AsyncMock(return_value=lifeos_http)
        lifeos_http.__aexit__ = AsyncMock(return_value=None)
        lifeos_http_cls.return_value = lifeos_http

        resp = await client.get("/health/backends")

    assert resp.status_code == 200
    data = resp.json()
    assert data["lifeos"]["reachable"] is True
    assert data["agent"]["configured"] is True
    assert data["agent"]["reachable"] is True


@pytest.mark.asyncio
async def test_health_backends_agent_not_configured(tmp_path):
    settings = Settings(data_dir=tmp_path, tts_backend="null", agent_backend_enabled=False)
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health/backends")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent"]["configured"] is False
    assert data["agent"]["reachable"] is None
