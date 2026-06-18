# Development Principles — whisper-relay

**Status:** Complete
**Last Updated:** 2026-06-18

Curated principles for this repo, adapted from personal Development principles notes at `~/Notes 2025/Development principles/` (distilled from the LifeDB engineering system). The full 13-document set lives in those notes; this file captures what applies to whisper-relay.

---

## Foundational Philosophy

### 1. Think before acting

State assumptions. Surface tradeoffs. Write ADRs before architectural decisions — especially adapter boundaries, TTS selection, and anything that touches LifeOS API contracts.

### 2. Simplicity first

Minimum code that solves the request. No speculative abstractions. No agent framework inside the transport layer.

*Test:* "Would a senior engineer say this is overcomplicated?"

### 3. Surgical changes

Touch only what the request requires. Every changed line should trace directly to it.

### 4. Goal-driven execution

GitHub issue acceptance criteria are the contract. Implementation is done when criteria are met and tested — not when code "seems to work."

### 5. Tests are sacred

Coverage only goes up. Failing tests mean your code is wrong until proven otherwise. Full standards: [specs/standards/testing-standards.md](specs/standards/testing-standards.md).

### 6. Privacy

Voice transcripts and LifeOS responses are personal data.

- Never log transcript/response text at INFO in production paths
- Use `turn_id` + timings in structured logs
- Synthetic utterances only in tests and documentation
- Turn audio files on disk are sensitive — document retention policy

---

## Architectural Principles (selected)

From Development principles § Architectural principles (`~/Notes 2025/Development principles/11 Architectural principles.md`). Applied here:

### Interfaces for infrastructure, simple implementations first

### Interfaces for infrastructure, simple implementations first

STT, LifeOS, and TTS are `typing.Protocol` adapters. TTS: [ADR-003](adr/003-kokoro-tts-bm-george.md). Project invariants: [AGENTS.md](../AGENTS.md).

### Ingestion consumes the public API

LifeOS integration is **HTTP-only** — the same APIs web chat uses. whisper-relay is an API consumer, not a LifeOS module. This mirrors LifeDB's "connectors consume the public API" principle.

### Speed is a design constraint

Voice is latency-sensitive. CPU-bound work (STT, polish, TTS, ffmpeg) runs in `asyncio.to_thread()`. Keep the STT engine warm. Don't add synchronous hops on the hot path without measuring.

### Make critical invariants structural

Transport-layer rules belong in architecture, not comments:

- Adapter protocols enforce swappable boundaries
- Turn pipeline has no imports from `agent_loop`, `agent_tools`, etc.
- Config validates at startup (fail-fast on missing `LIFEOS_BASE_URL`)

---

## Documentation

Six doc types by question answered:

| Type | Question | Location |
|------|----------|----------|
| README | What is this? | Root |
| ADR | Why did we decide? | `docs/adr/` |
| Standards | How must work be done? | `docs/specs/standards/` |
| Principles | What values govern us? | This file |
| Issues | What to build? | GitHub |
| Guides | How do I operate it? | README + future `docs/guides/` |

Full rules: [docs/AGENTS.md](AGENTS.md).

---

## Architecture Decision Records

- Append-only; supersede, don't edit
- Write for: new dependencies, adapter contract changes, security/privacy design

whisper-relay ADRs: [docs/adr/](adr/).

---

## Planning and Execution

Work flows: **issue → PR → review → merge**. Issues must have machine-testable acceptance criteria.

- One issue ≈ one PR where possible
- PR size target: ≤400 lines meaningful diff
- Branch: `feat/short-description`
- Commit: `feat:`, `fix:`, `docs:`, etc.

Traceability: issue → ADR (design authority) → spec/standard (how) → code.

---

## Quality Gates

Layered enforcement (adapted from LifeDB):

1. **Local:** `ruff` + `pytest` before commit
2. **CI:** lint, format check, unit tests (mocked adapters)
3. **Review:** `/review-pr` or `/implement` adversarial passes
4. **Docs:** did the change invalidate an ADR or standard?

Integration tests (real LifeOS, GPU STT) are `@pytest.mark.integration` — never required for CI green.

---

## Code Conventions (summary)

Full doc: [specs/standards/code-conventions.md](specs/standards/code-conventions.md).

- Python 3.12+; type hints on all public signatures
- `typing.Protocol` for adapters — not ABC
- `asyncio` for I/O; CPU-bound in `asyncio.to_thread()`
- Explicit wiring in app factory — no DI framework
- Structured logging; privacy-safe fields at INFO

---

## Related Documents

- [AGENTS.md](../AGENTS.md) — project constitution and boundaries table
- [CLAUDE.md](../CLAUDE.md) — Claude Code escalation rules
- [adr/001-voice-transport-layer.md](adr/001-voice-transport-layer.md)
- [adr/003-kokoro-tts-bm-george.md](adr/003-kokoro-tts-bm-george.md)
- [specs/standards/testing-standards.md](specs/standards/testing-standards.md)
- [specs/standards/code-conventions.md](specs/standards/code-conventions.md)

**Source:** `~/Notes 2025/Development principles/` (00 Overview through 12 Bootstrap checklist)
