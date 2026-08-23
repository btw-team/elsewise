# Elsewise release checklist

This checklist applies to one coordinated product version containing the server,
launcher, web GUI, Chrome extension, and Firefox extension.

## Prepare the tag

- Review open release-blocking issues, deferred work, and the platform test
  matrix; do not silently treat a deferred or untested gate as passed.
- Set the version with `uv run python scripts/version.py --set X.Y.Z`.
- Run `uv run python scripts/version.py --check` and inspect the resulting diff.
- Run `make check` from a clean checkout.
- Confirm LICENSE, NOTICE, and THIRD_PARTY_NOTICES are current.
- Tag the exact reviewed commit as `vX.Y.Z`.

## Automated release workflow

The tag workflow must succeed on:

- Ubuntu 22.04 x86_64: frozen smoke, `.deb`, `.rpm`, AppImage, portable archive,
  and Chrome/Firefox extension archives;
- Windows 2022 x64: frozen smoke, per-user Inno installer, installed CLI, user-PATH
  addition, and uninstall cleanup;
- macOS Apple Silicon and Intel runners: frozen smoke and architecture-specific
  unsigned DMGs.

The publish job merges only successful job artifacts, generates `SHA256SUMS`, and
creates the GitHub release. It does not sign, notarize, download, or deploy an
update to users.

## Platform gates

- Record the commit, artifact checksum, OS, architecture, status, and evidence for
  every applicable case in
  [`docs/testing/platform-validation-matrix.md`](testing/platform-validation-matrix.md).
- Do not infer a Windows/macOS result from Linux or a VM-only result for native
  prompts, process detachment, DPI, browser integration, or installer behavior.
- A waiver must name its risk, owner, expiry/retest point, and issue URL in the
  platform document and release notes.
- Select and publish the RPM compatibility baseline before describing the RPM as
  supported.

## Manual product smoke

- Open the launcher, start/stop/restart the daemon, close/reopen the launcher, and
  verify the default leave-running behavior.
- Verify the web GUI, Chrome extension, and Firefox extension connect to the same
  packaged daemon.
- Exercise one caption session for Meet, Teams, and Zoom where platform access is
  available.
- Verify all six locales in Launcher, web GUI, session language/initial prompt,
  Chrome, and Firefox.
- Verify both themes in the web GUI and launcher, confirm live synchronization in
  both directions, then verify the extension's independent theme in its popup and
  side-panel loading/error states.
- Exercise Codex and Claude discovery; recording must remain usable when either is
  unavailable.
- Inspect current and rotated logs for transcript, prompt, response, credential,
  token, environment, and participant-name leakage.
- Verify update status uses the stable channel and opens GitHub without downloading
  anything.
- Confirm the unsigned-warning and checksum instructions match observed behavior.

## Publish

- Review generated release notes and list exact supported OS/architecture baselines.
- Publish all artifacts together with `SHA256SUMS` and the unsigned-build warning.
- Install each published artifact from the release page, not from the build folder,
  and repeat the shortest lifecycle/web GUI smoke.
- Create issues for every accepted waiver and link them from the release notes.
