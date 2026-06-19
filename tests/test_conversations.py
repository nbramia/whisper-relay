import pytest


@pytest.mark.asyncio
async def test_list_conversations(client):
    resp = await client.get("/api/voice/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["conversations"]) == 1
    assert data["conversations"][0]["id"] == "conv-test-1"


@pytest.mark.asyncio
async def test_get_conversation(client):
    resp = await client.get("/api/voice/conversations/conv-test-1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "conv-test-1"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
