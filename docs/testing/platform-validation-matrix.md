# Elsewise platform validation matrix

## Purpose

This document is the authoritative checklist for behavior that must be verified on
real Windows, macOS, and Linux systems. A result applies only to the recorded OS,
architecture, artifact, and commit. Never use a Linux pass as evidence for Windows
or macOS.

These are verification tasks, not product decisions. If a failure requires a
product or architecture decision, link a dedicated issue from the run log instead
of silently changing the expected result here.

## Recording results

Use one of these markers in the dashboard and the run log:

| Marker | Status         | Meaning                                                          |
| ------ | -------------- | ---------------------------------------------------------------- |
| ⬜     | NOT RUN        | No qualifying run is recorded.                                   |
| ✅     | PASS           | All steps and expected results passed.                           |
| ❌     | FAIL           | At least one expected result failed.                             |
| ⚠️     | PARTIAL        | Only part of the case or environment was exercised.              |
| ⛔     | BLOCKED        | The run could not proceed; state the blocker.                    |
| ➖     | NOT APPLICABLE | The case does not apply to the published artifact.               |
| 🟪     | WAIVED         | A release waiver exists; link its owner, issue, and retest date. |

When recording a run:

1. Append a row to the [test run log](#test-run-log); never overwrite earlier
   failure evidence.
2. Update the applicable dashboard cell to the latest result.
3. Keep different architectures or display servers in separate run-log rows even
   when they share a dashboard cell.

For every run record:

- Elsewise commit/tag and artifact checksum;
- operating system, version, architecture, and desktop/session type;
- clean install, upgrade, or source-checkout execution;
- exact test case ID and status;
- relevant bounded logs, screenshots, or CI job URL;
- issue link and retest result after a failure.

Do not mark a platform complete from a VM-only result if the test concerns native
security prompts, process detachment, high-DPI rendering, browser integration, or
installer behavior. VM results are still useful and should be labelled as such.

## Result dashboard

The dashboard is a quick view only. The run log is the source of evidence. A
platform-specific case is marked not applicable outside its platform.

| ID         | Test                                      | Linux      | Windows    | macOS      |
| ---------- | ----------------------------------------- | ---------- | ---------- | ---------- |
| PROC-01    | Foreground Ctrl+C shutdown                | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| PROC-02    | Graceful background shutdown              | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| PROC-03    | Stuck provider and escalation             | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| PROC-04    | Parent-independent lifetime               | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| PROC-05    | No unwanted terminal window               | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| LOCK-01    | Lifecycle and server locks                | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| LOCK-02    | Stale PID and descriptor                  | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| LOCK-03    | Port conflict                             | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| USER-01    | Multiple local users                      | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| GUI-01     | Frozen resources                          | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| GUI-02     | Rendering and high DPI                    | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| GUI-03     | Native integrations                       | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| GUI-04     | Launcher single instance                  | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| GUI-05     | Close during active recording             | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| GUI-06     | Terminal signal shutdown                  | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| LOG-01     | Rotation while Details is open            | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| LOG-02     | Bounded rendered buffer and log privacy   | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| STATUS-01  | WebSocket status and polling fallback     | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| NOTIFY-01  | Native notifications                      | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| AGENT-01   | Executable discovery from GUI environment | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |
| WIN-01     | Per-user installer                        | ➖ N/A     | ⬜ NOT RUN | ➖ N/A     |
| WIN-02     | CLI and process creation                  | ➖ N/A     | ⬜ NOT RUN | ➖ N/A     |
| WIN-03     | Update replacement                        | ➖ N/A     | ⬜ NOT RUN | ➖ N/A     |
| WIN-04     | Unsigned artifact experience              | ➖ N/A     | ⬜ NOT RUN | ➖ N/A     |
| MAC-01     | DMG installation                          | ➖ N/A     | ➖ N/A     | ⬜ NOT RUN |
| MAC-02     | Install command-line tool action          | ➖ N/A     | ➖ N/A     | ⬜ NOT RUN |
| MAC-03     | App and helper lifetime                   | ➖ N/A     | ➖ N/A     | ⬜ NOT RUN |
| LINUX-01   | Ubuntu 22.04 `.deb`                       | ⬜ NOT RUN | ➖ N/A     | ➖ N/A     |
| LINUX-02   | RPM                                       | ⬜ NOT RUN | ➖ N/A     | ➖ N/A     |
| LINUX-03   | AppImage                                  | ⬜ NOT RUN | ➖ N/A     | ➖ N/A     |
| BROWSER-01 | Browser integration smoke                 | ⬜ NOT RUN | ⬜ NOT RUN | ⬜ NOT RUN |

## Target platforms

| Platform  | Initial baseline                                           | Required artifacts                        | Current status              |
| --------- | ---------------------------------------------------------- | ----------------------------------------- | --------------------------- |
| Linux     | Ubuntu 22.04 x86_64; X11 and Wayland                       | `.deb`, AppImage                          | NOT RUN                     |
| RPM Linux | Fedora/RHEL-compatible baseline to be fixed before release | `.rpm`, AppImage where applicable         | BLOCKED: baseline selection |
| Windows   | x64 Windows versions declared supported for the release    | per-user installer and installed `onedir` | NOT RUN                     |
| macOS     | Each architecture for which an artifact is published       | unsigned `.dmg` containing `.app`         | NOT RUN                     |

If ARM64 artifacts are published for Windows or Linux, repeat the applicable suite
on ARM64. On macOS, test Apple Silicon natively and Intel natively or explicitly
document that no Intel artifact is shipped.

## Cross-platform process and server lifecycle

Run this section on every published operating system and architecture.

### PROC-01: foreground Ctrl+C shutdown

1. Start the server with `elsewise run`.
2. Connect the web GUI and extension.
3. Start and stop a short session, then repeat while an agent provider is idle.
4. Press Ctrl+C once.

Expected:

- one Ctrl+C begins and completes shutdown without requiring a second signal;
- `uvicorn.Server.should_exit` runs the complete FastAPI lifespan shutdown;
- database and settings stores close cleanly;
- Codex and Claude providers receive bounded shutdown;
- runtime descriptor, control token, port, and locks are released;
- process exits with code `0`, without a `KeyboardInterrupt` traceback or error output;
- final log lines are coherent.

### PROC-02: graceful background shutdown

1. Start with `elsewise start` and repeat from the launcher Start action.
2. Stop once with `elsewise stop` and once with the launcher Stop action.
3. Repeat with Codex and Claude child processes present but responsive.

Expected:

- the controller reaches the hidden loopback shutdown endpoint using the correct
  control token;
- provider child processes exit within their bounds;
- no orphan helper or agent process remains;
- the lifecycle reaches `stopped` and can immediately start again.

### PROC-03: stuck provider and escalation

Simulate stuck Codex and Claude subprocess trees separately.

Expected:

- graceful shutdown times out within the configured bound;
- the normal Stop action does not expose force-stop before the timeout;
- GUI force-stop requires explicit confirmation and warns that agent output may be
  lost;
- terminate and kill target only the verified Elsewise process tree;
- the GUI/CLI reports the escalation stage and logs a warning;
- unrelated processes are never terminated.

### PROC-04: parent-independent lifetime

Verify all of the following:

- closing the launcher normally leaves the server alive by default;
- crashing or force-closing the launcher leaves the server alive;
- closing the terminal after `elsewise start` leaves the server alive;
- reopening the launcher finds and manages the existing server;
- logging out or shutting down the OS terminates the per-user process normally.

### PROC-05: no unwanted terminal window

Expected:

- packaged GUI and detached server never open a terminal/console window;
- the public CLI uses the caller's current terminal;
- child agents do not flash transient console windows on Windows.

## Locking, process identity, and local-user isolation

### LOCK-01: lifecycle and server locks

Run simultaneous Start, Stop, and Restart requests from CLI and GUI.

Expected:

- `fcntl.flock` works on Linux/macOS and `msvcrt.locking` works on Windows;
- exactly one lifecycle mutation proceeds at a time;
- only one server owns `server.lock` and port 38473;
- lock handles are not inherited by unrelated children;
- a crash releases OS lock ownership.

### LOCK-02: stale PID and descriptor

Create stale runtime metadata and simulate PID reuse where practical.

Expected:

- PID and process creation time must both match before control or termination;
- Elsewise never kills an unrelated reused PID;
- stale descriptors are removed only after process identity is disproved.

### LOCK-03: port conflict

Bind another process to port 38473 and start Elsewise.

Expected:

- status is `port_conflict`;
- owner PID/name is shown only when it can be obtained safely;
- Elsewise never kills, replaces, or attaches to the owner.

### USER-01: multiple local users

Using two OS accounts, verify that data directories, runtime locks, control tokens,
settings, logs, and server ownership are isolated. One user's launcher must not
control or expose secrets from another user's server.

## Frozen application and GUI behavior

### GUI-01: frozen resources

Expected in every packaged artifact:

- CustomTkinter theme data, fonts, Tcl/Tk, Pillow images, web assets, migrations,
  LICENSE, NOTICE, CA bundle, logo, icons, and avatar are available;
- resource lookup does not depend on the source checkout or `extra/`;
- paths containing spaces and non-ASCII characters work;
- missing optional OS fonts fall back without unreadable or clipped text.

### GUI-02: rendering and high DPI

Verify window sizing, scaling, keyboard focus, scrollbars, dialogs, hover/disabled
states, status tags, and all six locales at 100%, 125%, 150%, and 200% scaling
where the OS supports them. Check Segoe UI fallback on Windows, system font on
macOS, and the configured Linux sans-serif fallback.

### GUI-03: native integrations

Expected:

- Open Web GUI uses the default browser;
- Open log folder opens the native file manager;
- Copy actions use the system clipboard;
- links open without blocking the Tk main loop;
- browser and folder launching work from both source and frozen execution.

### GUI-04: launcher single instance

Start the launcher twice.

Expected:

- the second process signals the first window to restore/focus and exits;
- server state is not changed;
- if the OS denies focus stealing, the existing window still receives the signal
  and the user receives a visible notification.

### GUI-05: close during active recording

With `Stop server when Elsewise GUI closes` disabled, closing the launcher must
leave the recording server running. With it enabled, verify all three modal
outcomes independently:

```text
Cancel
Close GUI and keep server running
Stop server and close GUI
```

Expected: Cancel changes nothing; keep-server closes only the launcher; stop-server
performs bounded graceful shutdown before closing and exposes the confirmed
force-stop path only after timeout.

### GUI-06: terminal signal shutdown

Start `elsewise-gui` from a terminal, wait until the window is responsive, and
press Ctrl+C once. Repeat with `Stop server when Elsewise GUI closes` both disabled
and enabled, and send the platform's normal process-termination signal once.

Expected:

- the launcher exits with code `0` without a traceback or error output;
- the single-instance descriptor and lock are released;
- background monitor, log-tail, and activation-listener threads stop within their bounds;
- the server remains running when stop-on-exit is disabled and follows the normal
  graceful shutdown/confirmation path when it is enabled.

### LOG-01: rotation while Details is open

Force `server.log` to rotate while the live viewer follows it.

Expected:

- Linux/macOS inode replacement and Windows rename/share semantics both work;
- the viewer continues with the new active file;
- no large block is duplicated or skipped;
- Pause/Resume and scroll preservation still work;
- all server log files remain within the configured total limit after restart.

### LOG-02: bounded rendered buffer and log privacy

Generate more than 1000 visible log lines, including diagnostic events associated
with several named participants.

Expected:

- the Details widget retains at most 1000 rendered lines and evicts the oldest;
- rotated files retain history within the configured storage bound;
- meeting/session titles may appear;
- participant names are replaced consistently by `Participant N` aliases for the
  session and the raw-name mapping never appears in any log;
- no transcript, prompt, agent response, credential, or token leaks through log
  messages, exceptions, or native notification content.

### STATUS-01: WebSocket status and polling fallback

Expected on every OS:

- launcher subscribes to bounded runtime status over the existing WebSocket;
- no transcript or agent-message content is delivered to the launcher;
- state changes update the launcher without waiting for polling;
- disconnect triggers bounded reconnect and adaptive polling fallback;
- recovery returns automatically to WebSocket without duplicate updates;
- the launcher still shows stopped/unreachable state when no server can host the
  WebSocket.

### NOTIFY-01: native notifications

Trigger an unexpected server exit, an available stable update, and a failed
restart separately.

Expected:

- each supported OS receives one native notification per event;
- repeated status refreshes do not duplicate it;
- notification permission denial or unavailable integration produces a persistent
  in-app notification and does not fail the launcher;
- notification actions never restart, download, or expose sensitive content.

### AGENT-01: executable discovery from GUI environment

Test Codex and Claude installed through each supported method, including paths with
spaces. On Windows include npm `.cmd` shims; on macOS verify discovery when GUI
apps do not inherit an interactive shell `PATH`.

Expected discovery order:

1. configured absolute executable;
2. `shutil.which` in the actual process environment;
3. documented platform-specific locations.

No test may rely on invoking a login shell or evaluating shell startup scripts.

## Windows tests

### WIN-01: per-user installer

- install without administrator rights;
- verify Start menu/uninstall entries and application icons;
- verify the checked-by-default user-PATH option adds only the public CLI directory;
- verify unchecking the option leaves PATH unchanged;
- verify uninstall removes only the PATH entry it owns;
- ensure `elsewise-server` is never placed on PATH;
- test install and upgrade paths containing spaces and non-ASCII characters.

### WIN-02: CLI and process creation

- run all CLI commands from PowerShell and `cmd.exe`;
- verify `CREATE_NO_WINDOW`, process-group behavior, handle inheritance, and
  `DEVNULL` stdin;
- verify Ctrl+C for foreground mode and bounded process-tree cleanup for detached
  mode;
- verify executable discovery for native `.exe` and npm `.cmd` agents.

### WIN-03: update replacement

Run the installer while the old server is active.

Expected: the installer detects the process and asks the user to stop it; it never
silently replaces a partial or in-use `onedir`.

### WIN-04: unsigned artifact experience

Record the exact SmartScreen/publisher warnings and tested user flow. Publish the
artifact checksum and do not describe bypass steps as security-neutral.

## macOS tests

### MAC-01: DMG installation

- mount the unsigned `.dmg` and copy `Elsewise.app` to Applications;
- verify no `.pkg` is required or referenced;
- launch GUI and detached server without a terminal window;
- repeat on every published architecture;
- record exact Gatekeeper behavior and the checksum-verification flow.

### MAC-02: Install command-line tool action

Expected:

- when run from the mounted DMG, the action asks the user to move the app first;
- from Applications, it creates `/usr/local/bin/elsewise` as a symlink to the
  bundled public CLI;
- standard macOS authorization is requested only when required;
- unrelated files or symlinks are never overwritten;
- the action detects, repairs, and removes only Elsewise-owned stale symlinks;
- moving or replacing the app produces a clear repair state;
- the installed command works in a new Terminal session.

If unsigned-app restrictions make the privileged flow unreliable, record the
failure and decide on a tested per-user destination before release. Do not silently
change the installation target.

### MAC-03: app and helper lifetime

Verify `start_new_session`, app-close behavior, launcher crash behavior, OS logout,
and provider process-group cleanup. Confirm that reopening the app reconnects to
the existing server.

## Linux tests

### LINUX-01: Ubuntu 22.04 `.deb`

- install on a clean Ubuntu 22.04 x86_64 system;
- verify declared Tcl/Tk and desktop dependencies;
- launch under both X11 and Wayland;
- verify desktop entry, icons, browser launch, log-folder launch, CLI, background
  server, uninstall, and upgrade;
- verify `fcntl` locks and process detachment.

### LINUX-02: RPM

Before execution, select and document one representative Fedora or
RHEL-compatible version as the release baseline. Then verify install, upgrade,
uninstall, Tcl/Tk, browser launch, agent discovery, desktop integration, locks, and
detached lifetime on that baseline.

### LINUX-03: AppImage

- run without installing system Python or Node.js;
- test on Ubuntu 22.04 and the selected RPM-family baseline;
- test normal FUSE execution and document/test the supported fallback when FUSE is
  unavailable;
- verify writable data/log/runtime locations are outside the mounted image;
- verify X11 and Wayland behavior where supported.

## Browser integration smoke tests

### BROWSER-01: Chrome and Firefox integration

On at least one supported Windows, macOS, and Linux target:

- open the web GUI through the launcher;
- remove `pairing.json`, then verify that starting either the launcher or server
  creates one token and that both Settings screens display the same value;
- copy the token from both Settings screens and pair Chrome/Chromium and Firefox;
- save a different valid manual token and verify that the old extension connections
  are rejected until the replacement is saved in their popups;
- regenerate the token, verify immediate old-token invalidation, and confirm the new
  token persists across launcher and server restarts;
- connect Chrome/Chromium and Firefox extensions to the local server;
- open the GUI in a new tab and side panel where the browser supports it;
- verify the offline `Start the Elsewise server` page;
- verify EN, RU, FR, ES, DE, and PT-BR extension locales and English fallback.

## Release gate

Before publishing an artifact for a platform:

- every applicable test in this document is PASS or explicitly waived in release
  notes with an issue link;
- no Windows/macOS result is inferred from Linux;
- packaging and unsigned-security behavior is documented for that exact artifact;
- failures with architectural impact have a linked design or implementation issue;
- completed results link to reproducible evidence.

## Test run log

Append one row per test case and environment. Use an immutable CI URL, issue,
screenshot path, or bounded log excerpt where possible. For a retest, add a new
row rather than editing the failed row.

| Date       | Test ID | Version / commit                       | Artifact and SHA-256                                                                                    | Environment                                          | Result     | Tester | Evidence / notes                                                                                                  |
| ---------- | ------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | ---------- | ------ | ----------------------------------------------------------------------------------------------------------------- |
| YYYY-MM-DD | TEST-ID | `vX.Y.Z` or commit                     | artifact name and SHA-256                                                                               | OS, version, architecture, native/VM, display server | ⬜ NOT RUN | name   | CI URL, issue, screenshot, or bounded notes                                                                       |

## Active release waivers

A waiver is not a pass. Add it here, mark the matching dashboard cell `🟪 WAIVED`,
and copy it into the release notes.

| Test ID | Platform / artifact | Risk accepted | Owner | Issue | Expiry or retest point |
| ------- | ------------------- | ------------- | ----- | ----- | ---------------------- |
| —       | —                   | —             | —     | —     | —                      |
