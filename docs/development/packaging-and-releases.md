# Packaging and releases

## Product version

One stable version is shared by Python, the root npm package, web, extension, and
the lockfile. Update and verify it with:

```bash
uv run python scripts/version.py --set X.Y.Z
uv run python scripts/version.py --check
```

## Local frozen build

`uv run python scripts/build-frozen.py` builds the web GUI, prepares packaging
assets, creates a PyInstaller onedir with launcher/CLI/server executables, then
starts and stops the frozen server against isolated temporary data directories.

Platform packaging wraps that onedir in Inno Setup, DMG, DEB/RPM, or AppImage.

## GitHub Actions

**Build artifacts** is a manual workflow restricted to `main` and also a reusable
workflow called by Release. It runs the full source gate before native platform
jobs, verifies the complete artifact inventory, creates `SHA256SUMS`, and uploads a
14-day `release-bundle`.

**Release** runs for `v*` tags. The tag must match the product version and point to
a commit contained in `main`. A successful build is published immediately as a
stable GitHub Release with generated notes.

Current artifacts are unsigned. Workflows do not publish to PyPI or browser stores.

## Required release assets

- Linux x64 DEB, RPM, AppImage, and portable onedir archive;
- Windows x64 per-user installer;
- macOS ARM64 and Intel DMGs;
- Chrome and Firefox extension ZIPs;
- Python wheel and source distribution;
- `SHA256SUMS` covering every downloadable binary/archive.

Follow the [release checklist](../release-checklist.md) and record native evidence
in the [platform validation matrix](../testing/platform-validation-matrix.md).
