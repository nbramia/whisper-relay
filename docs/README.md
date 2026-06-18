# whisper-relay documentation

## Start here

| Audience | Document |
|----------|----------|
| Anyone | [README.md](../README.md) — project intent and sibling repos |
| AI agents / contributors | [AGENTS.md](../AGENTS.md) — constitution, boundaries, invariants |
| Claude Code | [CLAUDE.md](../CLAUDE.md) — escalation rules, common mistakes |
| Documentation rules | [AGENTS.md](AGENTS.md) — taxonomy, ADR rules, maintenance |

## Engineering principles

Adapted from personal [Development principles](~/Notes 2025/Development principles/) notes (LifeDB-derived):

- [development-principles.md](development-principles.md) — curated principles for this repo

## Architecture Decision Records

| ADR | Title | Summary |
|-----|-------|---------|
| [001](adr/001-voice-transport-layer.md) | Voice transport layer | Client surface of LifeOS, not an agent |
| [002](adr/002-upstream-integration-boundaries.md) | Upstream integration | linux-whisper + LifeOS HTTP boundaries |

ADR rules: [adr/AGENTS.md](adr/AGENTS.md)

## Standards

| Document | Summary |
|----------|---------|
| [code-conventions.md](specs/standards/code-conventions.md) | Python, adapters, logging, privacy |
| [testing-standards.md](specs/standards/testing-standards.md) | Unit vs integration, mocking, sacred tests |

## Related repos

- [linux-whisper](https://github.com/nbramia/linux-whisper) — local STT + polish
- [LifeOS](https://github.com/nbramia/LifeOS) — orchestrator and agent harness

Implementation: [GitHub issues](https://github.com/nbramia/whisper-relay/issues)
