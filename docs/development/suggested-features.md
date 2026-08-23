# Suggested features

This is a candidate backlog, not a release roadmap. An unchecked item means that
the idea may be implemented later, changed substantially, or declined. Before
implementation, move the item into a dated plan or issue with acceptance criteria,
security review where applicable, and tests.

Platform release verification is tracked in
[the platform validation matrix](../testing/platform-validation-matrix.md).

## Redacted diagnostic bundle

- [ ] Add an **Export diagnostics** action that creates a bounded local archive.
  - [ ] Include the Elsewise version and database schema revision.
  - [ ] Include operating-system and architecture information.
  - [ ] Include launcher and server runtime status.
  - [ ] Include a bounded tail of launcher and server logs.
  - [ ] Include configured and resolved Codex/Claude executable paths and health,
        without credentials.
  - [ ] Include web GUI and extension connection counters.
  - [ ] Exclude transcripts, prompts, agent responses, API keys, authorization
        headers, pairing tokens, runtime control tokens, and environment dumps.
  - [ ] Preserve the participant-name obfuscation used by normal logs.
  - [ ] Show the exact archive contents before saving.
  - [ ] Require an explicit user action and never upload the archive automatically.
  - [ ] Add automated redaction tests and a manual archive-inspection checklist.

## Configurable server address

- [ ] Allow the fixed loopback server address to be changed only after redesigning
      all dependent surfaces together.
  - [ ] Update Chrome and Firefox host permissions.
  - [ ] Update side-panel and new-tab URLs.
  - [ ] Review the web origin and CORS checks.
  - [ ] Update extension pairing and reconnect flows.
  - [ ] Update launcher control, health checks, and external-link handling.
  - [ ] Add collision detection and user-facing recovery.
  - [ ] Define migration from the fixed `127.0.0.1:38473` endpoint.
  - [ ] Keep the default loopback-only.
  - [ ] Treat LAN or public exposure as a separate security feature; a custom port
        must not imply remote access.

## Support and maintenance tools

- [ ] Design a dedicated launcher support section with independently reviewed
      actions.
  - [ ] Open the data directory.
  - [ ] Open the config directory.
  - [ ] Reset launcher settings.
  - [ ] Back up the database using SQLite-safe mechanisms.
  - [ ] Validate database integrity.
  - [ ] Copy a redacted status report.
  - [ ] Define exact mutation scope and in-app confirmations.
  - [ ] Provide recovery where practical.
  - [ ] Define behavior while recording or while agent work is active.

## Signed distribution

- [ ] Add release signing when identities and secure release infrastructure are
      available.
  - [ ] Keep signing jobs release-only and credentials outside the repository.
  - [ ] Preserve the current package layout so signing does not require an
        architectural change.

### Windows

- [ ] Sign the GUI, CLI, server helper, and installer.
- [ ] Use timestamped signatures.
- [ ] Validate signatures after installation and upgrade.
- [ ] Document the signed release flow and CI secret handling.

### macOS

- [ ] Sign nested helpers and frameworks from the inside out.
- [ ] Enable the hardened runtime with the minimum required entitlements.
- [ ] Notarize and staple the `.app` and `.dmg` release.
- [ ] Verify Gatekeeper behavior on a clean machine.
- [ ] Validate the installed artifact, not only the build directory.
