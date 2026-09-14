# Testing strategy

Tests are organized by public behavior rather than raw line coverage. Coverage
reports help locate gaps but do not impose a numerical gate.

## Test map

| Component        | Public behavior                                                     | Primary tests                                              |
| ---------------- | ------------------------------------------------------------------- | ---------------------------------------------------------- |
| Protocol         | Python and TypeScript accept/reject the same fixtures               | `test_protocol_contracts.py`, `protocol-contracts.test.ts` |
| Capture          | revisions, finalize grace, source binding, privacy-safe diagnostics | utterance/session state, persistence API, ingest WebSocket |
| Persistence      | initial migration, factory data, recovery, retention, pagination    | migration, maintenance, persistence API                    |
| Agents           | prompts, context, permissions, FIFO, resume/cancel, timeouts        | agent provider and fake Claude tests                       |
| Web GUI          | live reducers, drawers, actions, accessibility, pagination          | thematic web integration tests                             |
| Extension        | platform DOM behavior, buffer, transport, frame election            | adapter, soak, buffer, transport tests                     |
| Runtime/launcher | detached lifecycle, locking, logging, updates, Tk behavior          | runtime and launcher tests                                 |
| Product          | real built extension → daemon → GUI flow                            | synthetic Playwright E2E                                   |
| Packaging        | frozen resources/lifecycle and release inventory                    | frozen smoke and release tooling tests                     |

Cross-runtime protocol tests, adapter soaks, state-machine unit tests, and transport
integration are intentionally retained even when their scenarios overlap at a high
level: they identify failures at different boundaries.

## Commands

`make check` is the required local and CI gate. It runs formatting, lint, strict
types, docs links, unit/integration tests, production builds, wheel verification,
adapter soaks, and the synthetic extension E2E.

`make coverage` writes Python reports to `coverage/python`, extension reports to
`extension/coverage`, and web reports to `web/coverage`.

## Fixtures and sensitive data

All committed meeting fixtures must be fictional and minimized. Remove participant
names, organizations, URLs, tokens, emails, meeting IDs, avatars, captions from real
conversations, and unrelated page markup. A fixture README should state the behavior
it preserves.

## Native audio and speech model smoke

Build the Rust helper before running the transport integration tests:

```bash
cargo build --workspace
uv run pytest server/tests/test_audio_helper.py server/tests/test_audio_multiplexer.py -m integration
```

The helper uses separate user-private control and PCM Unix sockets on macOS/Linux.
Its integration suite covers two simultaneous streams, idempotent lifecycle commands,
bounded backpressure, explicit per-lane overflow, and restart after a process crash.

On macOS 14.6 or newer, list the discovered microphone, process, and system-audio
targets and run a bounded RAM-only capture smoke with:

```bash
cargo build --workspace
uv run python scripts/smoke-native-audio.py list --helper target/debug/elsewise-audio
uv run python scripts/smoke-native-audio.py microphone --helper target/debug/elsewise-audio
uv run python scripts/smoke-native-audio.py system --helper target/debug/elsewise-audio
uv run python scripts/smoke-native-audio.py process \
  --target bundle:com.example.MeetingApp \
  --helper target/debug/elsewise-audio
```

The process smoke chooses the first actively producing Core Audio process when
`--target` is omitted. These commands print only counters and signal level; they do
not persist PCM. macOS may request Microphone or System Audio Recording permission.

After the helper and development models are available, exercise the complete Session
lifecycle (default microphone + default system audio → Silero/Whisper → bounded Stop)
with:

```bash
uv run python scripts/smoke-native-session.py --seconds 10 --language en
```

Use `--remote-target bundle:<bundle-id>` to select a discovered process tap. The JSON
result contains only aggregate lane counters and an utterance count; it never emits or
persists PCM or transcript text.

After `uv run python scripts/build-frozen.py`, repeat the same source harness against
the unsigned Intel macOS bundle executables:

```bash
uv run python scripts/smoke-native-session.py --seconds 10 --language en \
  --helper dist/frozen/Elsewise/_internal/elsewise/bin/elsewise-audio \
  --speech-worker dist/frozen/Elsewise/elsewise-speech-worker
```

Downloaded models live in the ignored `models_loaded/` development inventory. Run each
model smoke in its own process so load time and peak RSS remain attributable:

```bash
uv run python scripts/smoke-speech-models.py whisper
```

Valid model names are `silero`, `whisper`, `nemotron`, `parakeet`, `campplus`, and
`pyannote`. The command prints one JSON evidence record; `--wav`, `--language`, and
`--threads` make corpus and hardware comparisons explicit. The sherpa runtime and its
native core are pinned in the project lock; downloaded model files remain a local,
ignored development inventory until production manifests are approved.

## Live tests

Paid provider tests remain opt-in:

- `ELSEWISE_RUN_CODEX_LIVE=1`
- `ELSEWISE_RUN_CLAUDE_LIVE=1`

They are smoke tests, not part of normal CI, and must use the fewest practical model
tokens.
