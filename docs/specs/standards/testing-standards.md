# Testing standards — whisper-relay

**Status:** Complete
**Last Updated:** 2026-06-18
**Owner:** whisper-relay

Adapted from [Development principles § Testing philosophy](../../development-principles.md).

## Tests Are Sacred

- New code ships with new tests
- Full suite runs before every commit
- Coverage direction: **only goes up**
- Never delete, skip, or weaken a failing test to unblock without the three-question framework (below)

### Three-question framework

When an existing test fails after your change:

1. What was this test meant to verify?
2. What specific change caused the failure?
3. Is the fix (a) your code, (b) intentional behavior change in the test, or (c) remove obsolete test?

**(a) is the default.** (b) and (c) need explicit justification.

## Test Taxonomy

| Kind | Marker | Runs |
|------|--------|------|
| Unit | default | every `pytest` — CI included |
| Integration | `@pytest.mark.integration` | manual / optional CI job — requires LifeOS, GPU, or TTS |

**Default CI must pass without:** GPU, LifeOS running, linux-whisper models loaded, TTS installed, ffmpeg (mock subprocess where needed).

## Mocking Discipline

Mock at **adapter boundaries**:

- `STTAdapter` → return fixed transcript
- `LifeOSClient` → return canned answer or replay SSE fixture
- `TTSAdapter` → write silent/minimal WAV to path
- `ffmpeg` → mock subprocess in normalization tests

**Do not mock** the turn pipeline's own orchestration logic in its dedicated tests — mock the adapters it calls.

Never mock the thing under test.

## Fixtures

```
tests/
  conftest.py           # shared mocks, settings override
  fixtures/
    sample.webm           # ffmpeg-generated Chrome-style audio
    lifeos_sse.txt        # canned SSE stream
    lifeos_handoff.json   # handoff response
```

- Factory helpers: `make_turn_request()`, `make_normalized_audio()`
- **Synthetic data only** — fake utterances, fake responses
- Valid-by-default factories; tests override only what matters

## What to Test

| Module | Priority |
|--------|----------|
| `turns.py` pipeline | High — full turn with mocked adapters |
| `adapters/lifeos.py` | High — SSE parsing, handoff trigger, status callback |
| `adapters/agent_backend.py` | High — agent SSE (no handoff), bearer auth, conversation proxy |
| `adapters/text_backend.py` | Medium — backend normalization, router selection |
| `routes/health.py` | Medium — `/health/backends` reachability |
| `audio.py` | High — normalization, error cases |
| `adapters/stt.py` | Medium — mock `STTEngine` + `PolishPipeline` |
| `routes/voice.py` | Medium — HTTP status mapping |
| `adapters/tts.py` | Medium — markdown strip, file output |

### Change-impact rule

Each non-trivial PR includes at least one of:

1. Test that fails without the change and passes with it, or
2. Regression test for highest-risk behavior touched

If no test changes: PR description explains why existing tests suffice.

## Assertions

- Test **behavior contracts**, not implementation details
- Prefer `pytest.raises` for error paths with message checks
- Async tests: `pytest-asyncio` with `asyncio_mode = auto`

## Naming

```
tests/test_voice_turn.py
tests/test_lifeos_client.py
tests/test_agent_backend.py
tests/test_text_backend.py
tests/test_health_backends.py

def test_turn_returns_transcript_and_audio_url():
def test_handoff_called_on_claude_intent():
def test_agent_backend_ignores_claude_intent():
def test_normalize_rejects_empty_upload():
```

## Running

```bash
pytest                          # unit only (default)
pytest -m integration           # requires live deps
pytest -m "not integration"       # explicit unit filter
ruff check src tests
```

## Related Documents

- [code-conventions.md](code-conventions.md)
- [../../adr/001-voice-transport-layer.md](../../adr/001-voice-transport-layer.md)
- [../../../AGENTS.md](../../../AGENTS.md) — boundaries table
