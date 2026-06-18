# Standards — whisper-relay

Prescriptive rules for code and tests. Review agents and `/pr-check` cite these documents.

## Contents

| Document | Covers |
|----------|--------|
| [code-conventions.md](code-conventions.md) | Python style, adapters, logging, privacy |
| [testing-standards.md](testing-standards.md) | Test taxonomy, mocking, sacred tests |

## Key Principles

- Standards use **must** language — they're enforced by CI and review, not suggestions
- Machine-enforced: ruff, pytest (unit)
- Review-enforced: adapter boundaries, privacy logging, no agent logic in gateway

## Related Documents

- [../../development-principles.md](../../development-principles.md)
- [../../../AGENTS.md](../../../AGENTS.md)
