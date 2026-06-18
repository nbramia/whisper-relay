# ADR-003: Kokoro TTS with bm_george voice

**Status:** Accepted
**Last Updated:** 2026-06-18
**Decision:** Accepted

## Context

whisper-relay must synthesize LifeOS response text and tool-status updates to audio for Chrome playback on a phone ([ADR-001](001-voice-transport-layer.md)). TTS backend selection was explicitly deferred in [ADR-002](002-upstream-integration-boundaries.md) pending voice quality and latency evaluation.

Requirements:

- **Local-only** — no cloud TTS; spoken content stays on the Linux workstation
- **Two clip types per turn** — short status phrases (low latency) and longer main responses (natural enough for daily use)
- **CPU-first** — GPU is already used by linux-whisper STT; avoid VRAM contention where possible
- **Adapter boundary** — implementation behind `TTSAdapter`; CI uses a null stub

Voice preference: **George** — British male (`bm_george` in Kokoro's voice naming).

## Alternatives Considered

### Piper (ONNX)

Pros: mature offline CLI, fast on CPU, simple subprocess integration.
Cons: rejected after voice audition — user prefers Kokoro's naturalness, specifically the George voice.

### espeak-ng

Pros: trivial install, instant synthesis.
Cons: too robotic for main responses; acceptable only as a dev/CI stub, not primary voice.

### Coqui TTS / XTTS

Pros: very natural, voice cloning.
Cons: PyTorch weight, GPU memory contention with whisper, overkill latency for push-to-talk.

### Cloud TTS (edge-tts, OpenAI, ElevenLabs)

Pros: highest quality.
Cons: violates local-first; network latency per clip; privacy. Ruled out for Phase 1.

## Decision

Use **[kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx)** (`pip install kokoro-onnx`) as the Phase 1 TTS backend.

| Setting | Value |
|---------|-------|
| Voice ID | `bm_george` |
| Language | `en-gb` (British English — Kokoro uses `b` prefix voices with `en-gb`) |
| Speed | `1.0` (configurable via env) |
| Model files | `kokoro-v1.0.onnx` + `voices-v1.0.bin` from [kokoro-onnx releases](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0) |
| Default model dir | `~/.local/share/whisper-relay/tts/kokoro/` |

### Implementation contract

`KokoroTTSAdapter` implements `TTSAdapter`:

```python
from kokoro_onnx import Kokoro

kokoro = Kokoro(model_path, voices_path)  # warm singleton in process
samples, sample_rate = kokoro.create(
    text,
    voice="bm_george",
    speed=1.0,
    lang="en-gb",
)
# write WAV via soundfile
```

- Run synthesis in `asyncio.to_thread()`
- Strip markdown before `create()`
- Support multiple `clip_id` files per `turn_id` (status clips + main)
- **NullTTSAdapter** for CI — writes minimal silent WAV; no model download required

### System dependencies

- **espeak-ng** — required by Kokoro for phoneme processing (`sudo apt install espeak-ng`)
- **soundfile** — WAV output (pulled in with kokoro-onnx usage)

### Configuration (env)

| Variable | Default |
|----------|---------|
| `TTS_BACKEND` | `kokoro` |
| `KOKORO_MODEL_PATH` | `~/.local/share/whisper-relay/tts/kokoro/kokoro-v1.0.onnx` |
| `KOKORO_VOICES_PATH` | `~/.local/share/whisper-relay/tts/kokoro/voices-v1.0.bin` |
| `KOKORO_VOICE` | `bm_george` |
| `KOKORO_LANG` | `en-gb` |
| `KOKORO_SPEED` | `1.0` |

## Rationale

- **Quality:** Kokoro-82M produces noticeably more natural speech than Piper/espeak for assistant-length responses; George matches the desired British male tone.
- **Local & licensed:** Apache 2.0 model, MIT engine — fits open-source sibling repos.
- **CPU ONNX:** onnxruntime inference stays off the ROCm GPU used by whisper STT.
- **Warm singleton:** model load once per process — same pattern as STT adapter.
- **Simple Python API:** no subprocess parsing; fits adapter protocol cleanly.

Accepted tradeoff: ~300 MB model files (quantized ~80 MB available if size matters later) and espeak-ng system dependency.

## Consequences

### Positive

- Consistent, natural voice across status clips and main responses
- TTS decision unblocks issue #6 implementation
- Null stub keeps CI fast without Kokoro installed

### Negative

- First-run setup: download model files + install espeak-ng
- Kokoro + onnxruntime adds Python dependencies (ask-first rule already satisfied by this ADR)
- British voice reads Americanisms from LifeOS naturally enough but won't localize US pronunciations
- Latency TBD until benchmarked on target hardware — monitor in structured logs

### Risks

| Risk | Mitigation |
|------|------------|
| Kokoro-onnx API changes | Pin version in `pyproject.toml` |
| Long responses slow | Log `tts_duration_ms`; chunking deferred to Phase 2 if needed |
| espeak-ng missing on deploy | Document in README; fail-fast at adapter init with clear error |

## Related Documents

- [ADR-001: Voice transport layer](001-voice-transport-layer.md)
- [ADR-002: Upstream integration boundaries](002-upstream-integration-boundaries.md)
- [Code conventions](../specs/standards/code-conventions.md)
- [GitHub issue #6](https://github.com/nbramia/whisper-relay/issues/6)
