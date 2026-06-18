"""LifeOS HTTP client — /api/ask/stream and /api/chat/handoff."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str], Awaitable[None]]


@dataclass(slots=True)
class HandoffResult:
    engine: str
    task: str
    message: str
    session_id: str = ""


@dataclass(slots=True)
class LifeOSResult:
    answer: str
    conversation_id: str | None
    handoff: HandoffResult | None = None
    statuses: list[str] = field(default_factory=list)


class LifeOSError(Exception):
    """LifeOS request failed."""


@runtime_checkable
class LifeOSClient(Protocol):
    async def ask(
        self,
        question: str,
        *,
        conversation_id: str | None,
        turn_id: str,
        on_status: StatusCallback | None = None,
    ) -> LifeOSResult: ...


class HTTPLifeOSClient:
    def __init__(self, base_url: str, timeout_s: float = 300.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s

    async def ask(
        self,
        question: str,
        *,
        conversation_id: str | None,
        turn_id: str,
        on_status: StatusCallback | None = None,
    ) -> LifeOSResult:
        body: dict[str, Any] = {"question": question}
        if conversation_id:
            body["conversation_id"] = conversation_id

        full_text = ""
        conv_id = conversation_id
        statuses: list[str] = []
        handoff: HandoffResult | None = None
        pending_engine: str | None = None
        pending_task: str | None = None

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/api/ask/stream",
                json=body,
            ) as resp:
                if resp.status_code != 200:
                    raw = await resp.aread()
                    raise LifeOSError(f"LifeOS returned HTTP {resp.status_code}: {raw[:500]!r}")

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type")
                    if etype == "content":
                        full_text += event.get("content", "")
                    elif etype == "self_correction":
                        full_text = ""
                    elif etype == "conversation_id":
                        conv_id = event.get("conversation_id", conv_id)
                    elif etype == "status":
                        msg = event.get("message", "")
                        if msg:
                            statuses.append(msg)
                            if on_status:
                                await on_status(msg)
                    elif etype == "claude_intent":
                        pending_engine = event.get("engine", "claude_code")
                        pending_task = event.get("task", question)
                    elif etype == "error":
                        err = event.get("message", "Unknown error")
                        logger.error("LifeOS SSE error turn_id=%s: %s", turn_id, err)
                        full_text += f"\n\nError: {err}" if full_text else f"Error: {err}"

            if pending_engine and pending_task:
                handoff = await self._handoff(client, pending_engine, pending_task, conv_id)
                full_text = handoff.message

        return LifeOSResult(
            answer=full_text.strip(),
            conversation_id=conv_id,
            handoff=handoff,
            statuses=statuses,
        )

    async def _handoff(
        self,
        client: httpx.AsyncClient,
        engine: str,
        task: str,
        conversation_id: str | None,
    ) -> HandoffResult:
        payload: dict[str, Any] = {"engine": engine, "task": task}
        if conversation_id:
            payload["conversation_id"] = conversation_id

        resp = await client.post(f"{self._base_url}/api/chat/handoff", json=payload)
        if resp.status_code != 200:
            label = "Codex" if engine == "codex" else "Claude Code"
            return HandoffResult(
                engine=engine,
                task=task,
                message=f"Handoff to {label} failed.",
            )
        data = resp.json()
        message = data.get("message") or data.get("ack") or ""
        if not message:
            label = "Codex" if engine == "codex" else "Claude Code"
            session_id = data.get("session_id", "")
            message = f"Handed off to {label}."
            if session_id:
                message += f" Session {session_id[:12]}."
        return HandoffResult(
            engine=engine,
            task=task,
            message=message,
            session_id=data.get("session_id", ""),
        )
