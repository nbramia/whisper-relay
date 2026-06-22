import pytest


@pytest.mark.asyncio
async def test_root_redirects_to_lifeos_chat(client, tmp_settings):
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == f"{tmp_settings.lifeos_base_url.rstrip('/')}/chat"


@pytest.mark.asyncio
async def test_removed_personas_proxy_returns_404(client):
    resp = await client.get("/api/voice/personas")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_removed_conversations_proxy_returns_404(client):
    resp = await client.get("/api/voice/conversations")
    assert resp.status_code == 404
