# Elsewise documentation

Elsewise is a real-time AI advisor for live conversations. Its browser extension
follows captions already displayed by supported call platforms, while the local
desktop application, server, and web GUI turn that context into role-specific,
editable AI-assisted workflows.

This documentation covers the free and open-source edition published in the
[`btw-team/elsewise`](https://github.com/btw-team/elsewise) repository.

## User guides

- [Installation](installation.md) - packaged artifacts, unsigned-build warnings,
  platform behavior, and updates.
- [Getting started](getting-started.md) - first launch, extension pairing, and the
  first recorded session.
- [Browser extension pairing](pairing.md) - token creation, copy, manual save,
  regeneration, and reconnect behavior.
- [Meeting capture](meeting-capture.md) - Meet, Teams, Zoom Web, speakers, and
  capture lifecycle.
- [Sessions, actions, and presets](sessions-and-actions.md) - role-specific
  workflows, context strategies, customization, transcript history, and exports.
- [Codex and Claude Code](agents.md) - CLI discovery, authentication, models,
  effort, working directories, and permissions.
- [Privacy and data](privacy-and-data.md) - local storage, cloud boundaries,
  retention, diagnostics, and deletion.
- [Troubleshooting](troubleshooting.md) - common server, extension, capture, and
  agent problems.

## Developer guides

- [Contributing](../CONTRIBUTING.md)
- [Development setup](development/setup.md)
- [Architecture](development/architecture.md)
- [Extension adapters](development/extension-adapters.md)
- [Testing strategy](development/testing.md)
- [Packaging and releases](development/packaging-and-releases.md)
- [Stable API errors](development/api-errors.md)
- [Suggested features](development/suggested-features.md)
- [Release checklist](release-checklist.md)
- [Platform validation matrix](testing/platform-validation-matrix.md)
