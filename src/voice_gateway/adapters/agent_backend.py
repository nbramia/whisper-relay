"""HTTP client for OpenClaw voice-adapter (LifeOS-compatible SSE subset)."""

from __future__ import annotations

from typing import Any

import httpx

from voice_gateway.adapters.lifeos import (
    LifeOSError,
    LifeOSResult,
    StatusCallback,
    consume_ask_sse_stream,
)


class HTTPAgentBackendClient:
    """voice-adapter at AGENT_BACKEND_URL — no LifeOS handoff path."""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 300.0,
        *,
        api_token: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s
        self._api_token = api_token.strip() if api_token else None

    def _headers(self) -> dict[str, str]:
        if not self._api_token:
            return {}
        return {"Authorization": f"Bearer {self._api_token}"}

    async def ask(
        self,
        question: str,
        *,
        conversation_id: str | None,
        turn_id: str,
        on_status: StatusCallback | None = None,
        cancel: Any = None,
        persona_id: str | None = None,
        model_override: str | None = None,
        parse_handoff: bool = True,
    ) -> LifeOSResult:
        body: dict[str, Any] = {"question": question}
        if conversation_id:
            body["conversation_id"] = conversation_id

        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers()) as client:  # noqa: SIM117
            async with client.stream(
                "POST",
                f"{self._base_url}/api/ask/stream",
                json=body,
            ) as resp:
                if resp.status_code != 200:
                    raw = await resp.aread()
                    raise LifeOSError(
                        f"agent backend returned HTTP {resp.status_code}: {raw[:500]!r}"
                    )

                state = await consume_ask_sse_stream(
                    resp,
                    question=question,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    on_status=on_status,
                    cancel=cancel,
                    parse_handoff=False,
                )

        return LifeOSResult(
            answer=state.full_text.strip(),
            conversation_id=state.conv_id,
            statuses=state.statuses,
        )

    async def list_personas(self) -> dict[str, Any]:
        raise LifeOSError("agent backend has no LifeOS personas")

    async def list_conversations(self, *, persona_id: str | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0, headers=self._headers()) as client:
            resp = await client.get(f"{self._base_url}/api/conversations")
            if resp.status_code != 200:
                raise LifeOSError(f"agent backend returned HTTP {resp.status_code}")
            return resp.json()

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0, headers=self._headers()) as client:
            resp = await client.get(f"{self._base_url}/api/conversations/{conversation_id}")
            if resp.status_code != 200:
                raise LifeOSError(f"agent backend returned HTTP {resp.status_code}")
            return resp.json()

    async def health_check(self) -> bool:
        async with httpx.AsyncClient(timeout=5.0, headers=self._headers()) as client:
            resp = await client.get(f"{self._base_url}/healthz")
            if resp.status_code != 200:
                return False
            data = resp.json()
            return bool(data.get("ok"))
