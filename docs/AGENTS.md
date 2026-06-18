# Documentation standards — whisper-relay

> **Audience:** Contributors and AI agents editing documentation
> **Status:** Complete
> **Last Updated:** 2026-06-18

Documentation is a governing artifact, not an afterthought. Specs and ADRs are written before (or alongside) implementation; code is reviewed against them.

Adapted from [Development principles § Documentation system](development-principles.md#documentation).

## Taxonomy

```
docs/
├── AGENTS.md              # This file — documentation rules
├── README.md              # Docs index
├── development-principles.md   # Curated engineering principles
├── adr/                   # WHY (decisions) — immutable ADRs
└── specs/
    └── standards/         # HOW (work) — code and testing conventions
```

| Question | Location |
|----------|----------|
| Why does whisper-relay exist? | Root `README.md` |
| Why was X decided? | `docs/adr/` |
| How should code be written? | `docs/specs/standards/` |
| What to build next? | GitHub issues (not docs) |

**Specs vs issues:** specs and ADRs describe **target state**. Tasks, progress, and backlogs live in **GitHub issues** — never in `backlog.md` or "Next Steps" sections in ADRs.

**Plans:** when `docs/plans/` is needed for a multi-issue effort, use dated filenames and archive when complete.

## Frontmatter

Bold fields at the top of every doc (not YAML):

```
**Status:** Draft | Partial | Complete
**Last Updated:** YYYY-MM-DD
```

ADRs also carry: `**Decision:** Accepted | Superseded | Deprecated`

## ADR Rules

- **Append-only** — never edit an accepted ADR's decision text. Supersede with a new numbered ADR.
- Naming: `NNN-short-title.md`
- Target 150–400 lines; max 800
- Every ADR ends with `## Related Documents` (bidirectional where possible)

See [development-principles.md § ADRs](development-principles.md#architecture-decision-records).

## Writing for AI Readability

- State requirements explicitly. Ban "we should consider…" — decide, defer with reason, or ask.
- Prefer tables and bullets over narrative for enumerable facts.
- Link instead of duplicating — one source of truth per fact.
- Keep documents focused on one concern (context window efficiency).

## Maintenance

When design changes land in a PR:

1. Update the relevant doc in the **same PR**
2. Bump `Last Updated`
3. Check bidirectional links in Related Documents

Don't over-document routine changes. Update docs when the **design** changes, not when a task checkbox flips.

## Privacy in Documentation

Voice interfaces handle personal speech. In all docs, examples, and test fixture descriptions:

- Use synthetic utterances ("remind me to call Alex tomorrow")
- Never use real names, emails, or transcript content from production
- Don't document internal Tailscale hostnames in public-facing material

## Instruction File Pairs

Per-directory `AGENTS.md` + `CLAUDE.md` (`@AGENTS.md`) when a directory has 3+ files or distinct rules. Current pairs:

- `docs/adr/`
- `docs/specs/standards/`

## Related Documents

- [development-principles.md](development-principles.md) — source principles
- [adr/001-voice-transport-layer.md](adr/001-voice-transport-layer.md)
- [Root AGENTS.md](../AGENTS.md) — project constitution
