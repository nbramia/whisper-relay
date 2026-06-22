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


class LifeOSCancelled(LifeOSError):  # noqa: N818
    """LifeOS stream cancelled."""


@runtime_checkable
class LifeOSClient(Protocol):
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
    ) -> LifeOSResult: ...

    async def list_personas(self) -> dict[str, Any]: ...

    async def list_conversations(self, *, persona_id: str | None = None) -> dict[str, Any]: ...

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]: ...


@dataclass(slots=True)
class AskStreamState:
    full_text: str = ""
    conv_id: str | None = None
    statuses: list[str] = field(default_factory=list)
    pending_engine: str | None = None
    pending_task: str | None = None


def _apply_sse_event(
    state: AskStreamState,
    event: dict[str, Any],
    *,
    parse_handoff: bool,
    turn_id: str,
    fallback_question: str,
) -> None:
    etype = event.get("type")
    if etype == "content":
        state.full_text += event.get("content", "")
    elif etype == "self_correction":
        state.full_text = ""
    elif etype == "conversation_id":
        state.conv_id = event.get("conversation_id", state.conv_id)
    elif etype == "status":
        msg = event.get("message", "")
        if msg:
            state.statuses.append(msg)
    elif etype == "claude_intent" and parse_handoff:
        state.pending_engine = event.get("engine", "claude_code")
        state.pending_task = event.get("task", fallback_question)
    elif etype == "error":
        err = event.get("message", "Unknown error")
        logger.error("text backend SSE error turn_id=%s: %s", turn_id, err)
        state.full_text += f"\n\nError: {err}" if state.full_text else f"Error: {err}"


async def consume_ask_sse_stream(
    resp: Any,
    *,
    question: str,
    conversation_id: str | None,
    turn_id: str,
    on_status: StatusCallback | None,
    cancel: Any,
    parse_handoff: bool,
) -> AskStreamState:
    state = AskStreamState(conv_id=conversation_id)
    async for line in resp.aiter_lines():
        if cancel is not None and getattr(cancel, "is_set", None) and cancel.is_set():
            await resp.aclose()
            raise LifeOSCancelled("turn cancelled")

        if not line.startswith("data: "):
            continue
        try:
            event = json.loads(line[6:])
        except json.JSONDecodeError:
            continue

        _apply_sse_event(
            state,
            event,
            parse_handoff=parse_handoff,
            turn_id=turn_id,
            fallback_question=question,
        )

        if event.get("type") == "status":
            msg = event.get("message", "")
            if msg and on_status:
                await on_status(msg)

    return state


def persona_supports_handoff(personas: list[dict[str, Any]], persona_id: str) -> bool:
    """True when LifeOS advertises handoff capability for this persona id."""
    for entry in personas:
        if entry.get("id") == persona_id:
            capabilities = entry.get("capabilities") or []
            return "handoff" in capabilities
    return persona_id == "primary"


def normalize_model_override(value: str | None) -> str | None:
    """Return a model_override for LifeOS, or None when unset/auto (omit from body)."""
    if not value:
        return None
    normalized = value.strip().lower()
    if not normalized or normalized == "auto":
        return None
    return normalized


def handoff_override_for_model(model_override: str | None) -> bool:
    """Explicit engine picks must parse claude_intent even on no-handoff personas."""
    return normalize_model_override(model_override) in ("claude_code", "codex")


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
        cancel: Any = None,
        persona_id: str | None = None,
        model_override: str | None = None,
        parse_handoff: bool = True,
    ) -> LifeOSResult:
        body: dict[str, Any] = {"question": question}
        if conversation_id:
            body["conversation_id"] = conversation_id
        if persona_id:
            body["persona_id"] = persona_id
        override = normalize_model_override(model_override)
        if override:
            body["model_override"] = override
        # Every turn this gateway handles is spoken (the reply is sent to TTS), so
        # tell LifeOS to apply the selected persona's voice formatting rules
        # (LifeOS#390 Phase 3). Unconditional: there is no text-only path into ask().
        body["modality"] = "voice"

        handoff: HandoffResult | None = None

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/api/ask/stream",
                json=body,
            ) as resp:
                if resp.status_code != 200:
                    raw = await resp.aread()
                    raise LifeOSError(f"LifeOS returned HTTP {resp.status_code}: {raw[:500]!r}")

                state = await consume_ask_sse_stream(
                    resp,
                    question=question,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    on_status=on_status,
                    cancel=cancel,
                    parse_handoff=parse_handoff,
                )

            if parse_handoff and state.pending_engine and state.pending_task:
                handoff = await self._handoff(
                    client, state.pending_engine, state.pending_task, state.conv_id
                )
                state.full_text = handoff.message

        return LifeOSResult(
            answer=state.full_text.strip(),
            conversation_id=state.conv_id,
            handoff=handoff,
            statuses=state.statuses,
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

    async def list_personas(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._base_url}/api/personas")
            if resp.status_code != 200:
                raise LifeOSError(f"LifeOS returned HTTP {resp.status_code}")
            return resp.json()

    async def list_conversations(self, *, persona_id: str | None = None) -> dict[str, Any]:
        params: dict[str, str] = {}
        if persona_id:
            params["persona_id"] = persona_id
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{self._base_url}/api/conversations", params=params or None)
            if resp.status_code != 200:
                raise LifeOSError(f"LifeOS returned HTTP {resp.status_code}")
            return resp.json()

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{self._base_url}/api/conversations/{conversation_id}")
            if resp.status_code != 200:
                raise LifeOSError(f"LifeOS returned HTTP {resp.status_code}")
            return resp.json()
