# Browser extension adapters

The extension has one TypeScript source tree and browser-specific manifests. Each
meeting adapter detects its supported origin, discovers caption roots, emits stable
revisioned utterances, finalizes conservatively, and produces bounded redacted
diagnostics.

## Platform notes

- Google Meet exposes caption blocks and speaker labels in the rendered DOM.
- Microsoft Teams uses virtualized lists and may temporarily remove/reinsert nodes.
- Zoom Web may identify speakers through avatar-local React state; the main-world
  bridge copies only a normalized display name into a root-scoped attribute.

Adapters must tolerate layout changes, captions off/on, root recreation, corrections,
retractions, overlapping speakers, and historical DOM restoration without duplicate
utterances.

## Adding or changing an adapter

1. Add a minimized sanitized fixture for every new DOM shape.
2. Keep platform-specific selectors and reconciliation inside the adapter.
3. Never emit raw URLs, avatar sources, caption text, speaker names, or meeting titles
   through normal diagnostics.
4. Add focused adapter tests and an accelerated soak when identity/reconciliation
   rules change.
5. Update both manifests only through the shared manifest build structure.
6. Run the real synthetic extension E2E after production building Chrome.

Raw research captures belong under ignored `output/playwright/`. Do not commit them.
