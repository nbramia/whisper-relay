@AGENTS.md

# Claude Code — whisper-relay

## Workflow

- Use plan mode for non-trivial tasks (3+ files, adapter boundary changes, unclear requirements).
- Read [ADR-001](docs/adr/001-voice-transport-layer.md) and [ADR-002](docs/adr/002-upstream-integration-boundaries.md) before any adapter or pipeline work.
- After modifying docs, verify compliance with [docs/AGENTS.md](docs/AGENTS.md).
- When creating new modules under `src/voice_gateway/`, check if an `AGENTS.md` + `CLAUDE.md` pair is warranted (3+ files or distinct rules).

## Skills

Available in `.claude/skills/`:

| Skill | Purpose |
|-------|---------|
| `/implement` | Full lifecycle: plan → implement → PR → review → merge |
| `/draft-issue` | Create GitHub issues with machine-testable acceptance criteria |
| `/review-pr` | Adversarial PR review |
| `/address-review` | Address review feedback with verification |
| `/merge-pr` | Merge PR, update linked issues |
| `/pr-check` | Validate PR against standards |

## Escalation Rules

Stop and ask a human before proceeding if any of these apply:

| Trigger | Why |
|---------|-----|
| Adding agent tools, intent classification, or orchestrator logic | Violates transport-layer invariant ([ADR-001](docs/adr/001-voice-transport-layer.md)) |
| Disabling linux-whisper polish or gateway-specific STT overrides | Breaks desktop parity ([ADR-002](docs/adr/002-upstream-integration-boundaries.md)) |
| Importing LifeOS or linux-whisper internals beyond public adapter surfaces | Breaks deploy boundary; couple repos |
| Changing `STTAdapter`, `LifeOSClient`, or `TTSAdapter` protocol signatures | Affects all backends simultaneously |
| Adding a dependency to `pyproject.toml` | GPU/shared-lib conflicts are real (see linux-whisper ROCm isolation) |
| Selecting or implementing a TTS backend | Requires ADR — explicitly deferred |
| Blocking `claude_intent` / handoffs locally instead of calling `/api/chat/handoff` | Breaks LifeOS client parity |
| Logging transcript or response text at INFO in production paths | Voice data is personal |
| Acceptance criteria are ambiguous or untestable | Wastes implementation effort |

## Latency Awareness

Voice turns are user-perceived end-to-end. When touching the pipeline, be aware of typical budgets (GPU path):

| Stage | Target |
|-------|--------|
| ffmpeg normalize | < 100ms |
| STT + polish (linux-whisper) | ~300–500ms |
| LifeOS orchestrator | 2–30s (tool-dependent) |
| TTS (per clip) | TBD |

Don't add synchronous work on the hot path without justification. CPU-bound stages belong in `asyncio.to_thread()`.

## Common Mistakes

1. **Building an agent in whisper-relay** → submit text to LifeOS; LifeOS reasons. See [ADR-001](docs/adr/001-voice-transport-layer.md).
2. **Raw STT without polish** → use full `PolishPipeline` with desktop config. See [ADR-002](docs/adr/002-upstream-integration-boundaries.md).
3. **Importing `lifeos` Python package** → HTTP client only (`/api/ask/stream`, `/api/chat/handoff`).
4. **Spoken fallback on `claude_intent` instead of handoff** → call `/api/chat/handoff` like `LifeOS/web/index.html`.
5. **Cold-starting STT per request** → keep warm singleton engine across turns.
6. **Modifying an accepted ADR** → ADRs are append-only; write a new superseding ADR.
7. **Putting task lists in ADRs or specs** → tasks live in GitHub issues.
8. **Tests that require GPU, LifeOS running, or real TTS** → mock adapters; mark `@pytest.mark.integration`.
9. **Logging full transcripts at INFO** → log `turn_id` + timings; text at DEBUG or in turn storage only.
10. **Deleting or weakening a failing test to unblock** → your code is wrong until proven otherwise ([testing standards](docs/specs/standards/testing-standards.md)).

## Quick Reference

```bash
pip install -e ".[dev]"
pip install -e ../linux-whisper
ruff check src tests
pytest
uvicorn voice_gateway.main:app --host 127.0.0.1 --port 8888
```

LifeOS must be running separately: `http://127.0.0.1:8000/health/full`
