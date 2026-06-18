# Code conventions — whisper-relay

**Status:** Complete
**Last Updated:** 2026-06-18
**Owner:** whisper-relay

Python conventions for this repo. Adapted from [Development principles § Code conventions](../../development-principles.md) and aligned with [linux-whisper](https://github.com/nbramia/linux-whisper) where applicable.

## Language and Style

- Python **3.12+**
- Type hints on all function signatures, return types, and public class attributes
- `X | Y` unions; `match` where it clarifies
- `@dataclass(frozen=True, slots=True)` for config and value objects
- **`typing.Protocol`** for adapter interfaces — not ABC
- Line length **100** (ruff)
- Ruff rules: `E, F, I, N, W, UP, B, SIM, TCH`

## Module Layout

Organize by **concern**, not horizontal layers:

```
src/voice_gateway/
  adapters/     # STT, LifeOS client, TTS — protocol + impl
  routes/       # FastAPI routers
  audio.py      # ffmpeg normalization
  turns.py      # turn pipeline orchestration
  config.py     # pydantic-settings
  main.py       # app factory
```

No `utils/` junk drawer. No `services/agent/` — if you're tempted, it belongs in LifeOS.

## Adapter Pattern

Adapters are the primary extension points:

```python
class STTAdapter(Protocol):
    async def transcribe(self, pcm_bytes: bytes, *, turn_id: str) -> str: ...
```

- Turn pipeline accepts protocols; concrete adapters wired in `main.py` or a small `deps.py`
- Constructors return concrete types; functions accept protocols
- **Consumer defines the protocol** (turn pipeline), provider implements it

## Async Discipline

- FastAPI routes and LifeOS SSE client: `async`
- STT, polish, ffmpeg, TTS: `asyncio.to_thread()` — they block
- Don't spawn background tasks from adapters without explicit lifecycle ownership
- `httpx.AsyncClient` for LifeOS; reuse client across requests (app lifespan)

## Configuration

- `pydantic-settings` `BaseSettings` with env prefixes
- Validate at startup; **fail fast** with clear errors
- Pass config into constructors — no global config singletons
- Secrets via env / `~/Code/Sync/envs/whisper-relay/.env` — never committed

## Logging

Structured JSON-friendly logging via `logging.getLogger(__name__)`.

| Level | Content |
|-------|---------|
| INFO | `turn_id`, stage, `duration_ms`, `backend`, HTTP status |
| DEBUG | transcript/response previews (truncated), ffmpeg stderr |
| ERROR | exceptions with `turn_id`; no full audio bytes |

**Never** log full transcripts or LifeOS responses at INFO — voice data is personal.

## Errors

- Raise domain exceptions in adapters; map to HTTP status in routes
- Wrap upstream errors with context: `LifeOSUnavailableError`, `STTError`, `NormalizationError`
- Don't catch-and-ignore in the pipeline — log and return appropriate 4xx/5xx

## Dependencies

- Standard library + minimal deps: FastAPI, httpx, pydantic-settings, numpy (via linux-whisper)
- **linux-whisper:** editable path dependency — public STT/polish API only
- **LifeOS:** HTTP only — never add as Python dependency
- New `pyproject.toml` dependency → **ask first** (often needs ADR)

## Privacy

- Turn storage paths include `turn_id` only — no user identifiers in filenames for Phase 1
- Synthetic data in all tests: `"remind me to water the plants"`, not real utterances
- Don't persist uploads beyond configured retention without documenting why

## Enforcement

| Machine (CI) | Review |
|--------------|--------|
| `ruff check`, `ruff format --check` | adapter boundary respect |
| `pytest` | no agent logic in gateway |
| | privacy logging rules |
| | protocol placement |

## Related Documents

- [testing-standards.md](testing-standards.md)
- [../../adr/002-upstream-integration-boundaries.md](../../adr/002-upstream-integration-boundaries.md)
- [../../development-principles.md](../../development-principles.md)
- [../../../AGENTS.md](../../../AGENTS.md)
