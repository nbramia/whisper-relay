"""Cancellation-safe ownership helpers for bounded blocking work."""

from __future__ import annotations

import asyncio
from contextlib import suppress


async def await_bounded_task[T](task: asyncio.Task[T]) -> T:
    """Keep the caller alive until *task* ends, then preserve cancellation.

    Blocking decoder and STT operations have their own process deadlines. Once
    they start, the surrounding coroutine must retain its semaphore or engine
    lock until the real operation finishes, even if more than one cancellation
    request arrives while cleanup is in progress.
    """
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError as cancellation:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            with suppress(Exception):
                task.result()
        raise cancellation
