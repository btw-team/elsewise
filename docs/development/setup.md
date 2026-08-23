# Development setup

## Requirements

- Python 3.13
- [`uv`](https://docs.astral.sh/uv/)
- Node.js 22+ and npm 10+
- Chromium for the synthetic extension E2E
- optional Codex/Claude Code for opt-in live tests

## Install and verify

```bash
make install
make install-browsers
make check
```

On Windows without `make`, run the underlying commands from the Makefile using
PowerShell.

## Run from source

```bash
npm run build
uv run elsewise start
uv run elsewise-gui
```

For live development, `make dev-server` runs Uvicorn with reload and `make dev-web`
runs Vite. The production daemon remains on `127.0.0.1:38473`.

## Useful checks

```bash
make format
make lint
make typecheck
make test
make test-e2e
make coverage
make docs-check
make actionlint
```

Coverage is diagnostic and has no percentage gate. `actionlint` must be installed
separately for the local target; CI downloads a fixed actionlint release.

## Repository layout

- `server/src/elsewise/`: daemon, API, agents, persistence, launcher, runtime.
- `web/`: React web GUI.
- `extension/`: shared Chrome/Firefox MV3 extension.
- `protocol/`: shared JSON schemas and fixtures.
- `packaging/` and `scripts/`: PyInstaller and platform packaging.
- `tests/fixtures/`: sanitized browser DOM fixtures only.
