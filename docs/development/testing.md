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

## Live tests

Paid provider tests remain opt-in:

- `ELSEWISE_RUN_CODEX_LIVE=1`
- `ELSEWISE_RUN_CLAUDE_LIVE=1`

They are smoke tests, not part of normal CI, and must use the fewest practical model
tokens.
