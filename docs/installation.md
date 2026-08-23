# Installing Elsewise

Packaged releases include the launcher, local server, web GUI, and extension
archives. Python and Node.js are not required on the target computer. Codex and
Claude Code remain optional external tools.

## Unsigned preview builds

Current artifacts are not code-signed or notarized. Download an artifact and
`SHA256SUMS` from the same [GitHub Release](https://github.com/btw-team/elsewise/releases/latest),
verify the SHA-256 digest, and expect an unknown-publisher warning.

Do not run a file whose checksum differs. Signing and notarization will be added
only after suitable identities and release infrastructure are available.

## Windows x64

Run `Elsewise-<version>-windows-x64-setup.exe`. The per-user installer does not
require administrator access. Its checked-by-default option adds only the public
`elsewise` command to the user `PATH`; the internal server helper is not exposed.

The launcher and detached server do not open console windows. CLI commands use the
PowerShell or Command Prompt window from which they are invoked.

## macOS

Choose the DMG matching Apple Silicon (`arm64`) or Intel (`x86_64`), drag
`Elsewise.app` to Applications, and use macOS's explicit Open action for the
first unsigned launch after verifying the checksum.

The Launcher Settings page can install or remove `/usr/local/bin/elsewise`. It
will not overwrite an unrelated file or symlink. Elsewise uses a DMG, not a PKG.

## Linux x64

- Ubuntu 22.04+: install the `.deb`.
- Portable use: make the AppImage executable and launch it.
- RPM-based systems: use the `.rpm` only on a baseline explicitly listed as tested
  in that release's notes.
- A portable onedir `.tar.gz` is provided mainly for diagnostics and development.

The AppImage may require FUSE; use the fallback documented by your distribution if
FUSE execution is unavailable.

## Browser extensions

Until public store listings are available, releases include Chrome and Firefox ZIP
archives. Extract the archive before loading it:

- Chrome: `chrome://extensions` → Developer mode → Load unpacked.
- Firefox: `about:debugging#/runtime/this-firefox` → Load Temporary Add-on → choose
  `manifest.json`.

Firefox temporary add-ons are removed when Firefox exits. Store installation will
replace this development flow later.

After loading the extension, copy the automatically generated token from **Browser
extension pairing** in the web GUI or launcher Settings and save it in the extension
popup. See [Browser extension pairing](pairing.md).

## Updates

The launcher checks only the latest stable GitHub Release and no more than once per
24 hours by default. It never downloads or installs an update automatically.

Continue with [Getting started](getting-started.md).
