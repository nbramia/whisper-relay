"""Root redirect — client UI lives in LifeOS /chat (ADR-005)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter(tags=["root"])


@router.get("/", include_in_schema=False)
async def redirect_to_lifeos_chat(request: Request) -> RedirectResponse:
    settings = request.app.state.settings
    target = f"{settings.lifeos_base_url.rstrip('/')}/chat"
    return RedirectResponse(url=target, status_code=301)
