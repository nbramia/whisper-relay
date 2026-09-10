# ADR-009: Trusted-local raw STT capture interface

**Status:** Complete
**Last Updated:** 2026-09-09
**Decision:** Accepted (whisper-relay #53; linux-whisper #56)

## Context

Pebble capture needs an independent recognition result to compare with its own
source text. The existing `POST /api/voice/transcribe` is a polished wake-word
check, and voice turns intentionally apply desktop polish before a text backend
sees their transcript. Replacing either behavior would make a capture client
silently change established voice semantics.

The service is a transport, not an action processor. Detailed STT therefore
must not create turns, retain turn files, call a text backend, synthesize TTS,
or accept an alternate transcript as a recognition prompt.

## Decision

Expose an additive `POST /api/voice/transcribe/detailed` endpoint for one
configured trusted-local capture consumer. It returns raw recognition first and
can additionally return server-side polish when `include_polished=true`; raw
recognition is always computed independently of polish.

### Boundary and admission

- The service defaults to `127.0.0.1`; the route additionally rejects a
  non-loopback peer even if an operator overrides the service listener.
- `VOICE_GATEWAY_RAW_STT_TOKEN` is required. It is supplied as
  `X-Voice-Gateway-Token` and compared in constant time. An unset token makes
  the endpoint return `404`; missing or invalid credentials return `401`.
- Forwarded identity and tenant headers do not grant access. This is not a
  public Pebble webhook and does not resolve a LifeOS tenant.
- One detailed request is admitted across upload handling, decode, and STT.
  A concurrent request receives `429`, `Retry-After: 1`, and may retry.

### Request and success result

The request is `multipart/form-data` with a required `audio` file. Version one
does not take language, transcript, or prompt fields: it must not accept a
value that the backend cannot honor. The frozen synthetic response shape is
[`tests/fixtures/raw_stt_detailed_v1.json`](../../tests/fixtures/raw_stt_detailed_v1.json).

`raw.outcome` is `recognized` or `no_speech`. A no-speech result is a `200`
with empty `raw.text`; it is not an engine failure. Segment times are available
only when the engine supplies them. `language`, `confidence`, and `engine.revision`
remain `null` when unavailable rather than being inferred. `engine.backend` and
`engine.model` describe the configured linux-whisper engine.

### Limits, failures, and recovery

The route checks declared and streamed upload bytes against
`VOICE_GATEWAY_MAX_UPLOAD_BYTES` before multipart spooling; it normalizes in a
worker thread through ffmpeg to headerless 16 kHz mono signed-16-bit PCM. The
decoder forces an approved audio demuxer, permits only local file/pipe protocols,
does not read stdin, writes bounded raw PCM, and has a process deadline
(`VOICE_GATEWAY_DECODE_TIMEOUT_S`) that reaps ffmpeg on expiry.
`VOICE_GATEWAY_MAX_AUDIO_DURATION_S` caps decoded duration.

The warm adapter owns one linux-whisper engine and serializes all inference.
Startup starts and resets a no-audio stream, which loads the GPU worker/model
without recognizing a request. linux-whisper #56 bounds startup, write, and
read IPC; a worker timeout, malformed response, exit, or inference failure
invalidates, terminates, and reaps that process before the next request can
construct a replacement. The relay does not use cancellation of an awaiting
thread as proof that the actual inference stopped.

| Status | Code | Retryable | Meaning |
|--------|------|-----------|---------|
| 413 | `upload_too_large` | no | Declared or streamed upload exceeds the cap |
| 415 | `unsupported_media` | no | The upload is not audio or permitted binary media |
| 422 | `invalid_audio` | no | Malformed, empty, or duration-limited audio |
| 429 | `busy` | yes | The single detailed admission is occupied |
| 504 | `deadline_exceeded` | yes | Decoder or reaped STT worker exceeded its deadline |
| 503 | `engine_unavailable` | yes | Startup, worker, or protocol failure |

All error bodies are `{ "error": { "code", "message", "retryable" } }`.
They contain no transcript, audio, authorization value, ffmpeg output, or
worker dump. Operational logs use identifiers and timing only.

### Compatibility and operations

`POST /api/voice/transcribe` keeps returning its existing polished
`{"transcript": ...}` result. Voice turns retain their desktop polish path.
The detailed endpoint exposes readiness through normal startup state; health
checks never run an inference. The upstream dependency is linux-whisper issue
[#56](https://github.com/nbramia/linux-whisper/issues/56). The tested compatible
revision is [`e838e6f`](https://github.com/nbramia/linux-whisper/commit/e838e6f6bab1d13adeb138461d9acc1ed275fdce);
deployments must use that revision or a later compatible release before enabling
the raw token.

The narrow rollout is: land linux-whisper #56, install that revision in the
relay environment, deploy the relay change, configure the token outside Git,
then deliberately restart only the relay unit after review. Existing relay and
desktop linux-whisper services remain running until that rollout; the desktop
service is a separate process and no strict GPU-priority guarantee is claimed.

## Consequences

- Pebble can preserve and compare independent raw recognition without turning
  off polish for existing voice consumers.
- The route is intentionally unsuitable for direct Internet use or arbitrary
  multi-tenant capture clients; a future exposure needs a separately reviewed
  authentication and caller-resolution design.
- Linux-whisper owns worker lifecycle behavior. The relay consumes its public
  engine and error behavior rather than copying an STT engine.

## Implementation verification — 2026-09-09

The final reviewed upstream pin is
[`e838e6f`](https://github.com/nbramia/linux-whisper/commit/e838e6f6bab1d13adeb138461d9acc1ed275fdce). Its
GPU-free process tests exercise startup hang, blocked audio writes, inference
hang, forced exit, malformed frames, terminate-to-kill escalation, reaping, and
replacement-worker recovery. Successful result frames must reproduce the
worker's joined segment text, reject boolean timestamps, and permit final
segment padding of at most one second beyond measured audio duration.

Relay regressions additionally prove that repeated cancellation retains decoder
and STT ownership until bounded work completes, multipart limit errors close
parser-owned upload files, and the polished legacy transcription route decodes
off the event loop. An ffmpeg-gated integration test sends a generated M4A
through the real multipart and decoder path while a synthetic STT adapter keeps
the test independent of models and GPUs. Raw STT tokens are ASCII-only at
configuration time; non-ASCII request header bytes fail closed with `401`.

## Related Documents

- [ADR-001](001-voice-transport-layer.md) — transport-only boundary
- [ADR-002](002-upstream-integration-boundaries.md) — linux-whisper seam
- [ADR-005](005-lifeos-owned-chat-client.md) — reverse-proxy client boundary
- [whisper-relay #53](https://github.com/nbramia/whisper-relay/issues/53)
- [linux-whisper #56](https://github.com/nbramia/linux-whisper/issues/56)
