from httpx import ASGITransport, AsyncClient

from voice_gateway.main import create_app


async def test_health():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_stt_health_reports_readiness_without_warming(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health/stt")

    assert resp.status_code == 200
    assert resp.json() == {"ready": True}
