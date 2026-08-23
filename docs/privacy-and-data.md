# Privacy and local data

## Local-first boundary

Elsewise has no hosted application backend. The extension connects to a daemon
bound to `127.0.0.1:38473`; canonical sessions, transcripts, settings, exports, and
agent history remain on the current computer.

When an agent action runs, the selected prompt and bounded transcript excerpt are
sent by the user's Codex or Claude Code CLI to that provider. Elsewise cannot make
cloud model use local-only.

## Data locations

Elsewise uses OS-native per-user directories through `platformdirs`:

- Linux: normally `~/.local/share/Elsewise` and `~/.config/Elsewise`;
- macOS: `~/Library/Application Support/Elsewise` and corresponding config/cache;
- Windows: the applicable `%LOCALAPPDATA%` and `%APPDATA%` Elsewise directories.

`GET /api/health` reports the resolved data directory.

## Pairing credential

The browser extension pairing token is a local credential stored in `pairing.json`
under the per-user config directory and in the paired extension's local browser
storage. The web GUI and launcher show the same value in Settings. The token is not
included in URLs and must not appear in logs or diagnostic bundles.

Regenerating or manually replacing the token immediately invalidates the previous
credential. It does not delete transcripts or other application data. The pairing
token is separate from the short-lived runtime control token used for private
launcher-to-server lifecycle requests.

## Browser buffer

Pending extension events use `storage.session`. They survive service-worker restart
but are not guaranteed after the browser closes. Caption events are scoped to the
running session and are discarded rather than delivered to a different session.

## Diagnostics and retention

Rejected/orphan diagnostics store identifiers, protocol metadata, result, and reason
codes without caption text, speaker, or meeting title. Tombstones and diagnostics
are bounded and pruned at server startup; aggregate counters remain.

Server and launcher logs rotate within the configured total limit. Debug DOM dumps
are explicit development actions and may contain sensitive page structure; inspect
and sanitize them before sharing.

## Consent and deletion

Users are responsible for participant consent and applicable workplace, privacy,
and recording rules for each conversation. Permanently deleting a session has no
recovery step. Uninstalling the application does not promise to erase user data
automatically; remove the platform data/config directories separately if complete
erasure is required.
