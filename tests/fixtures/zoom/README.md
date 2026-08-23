# Sanitized Zoom Web caption fixtures

These minimal fixtures preserve only semantic DOM signals observed in the private
2026-08-16 Zoom Web captures. Meeting identifiers, participant names, account data,
raw avatar URLs, video, generated presentation markup, and recognized speech were
replaced or omitted.

- `captions-off.html`: persistent wrapper and `Show Captions`, with no overlay.
- `captions-on-empty.html`: enabled empty overlay and `Hide Captions`.
- `one-speaker.html`: one visible incremental caption root with a synthetic avatar.
- `two-speakers.html`: two simultaneous roots with distinct synthetic avatars.

Tests construct teardown, re-enable replay, root replacement, layout survival, and
display/overlay hiding transitions from these semantic surfaces. Source analysis
remains in the Git-ignored archive documented by
`output/playwright/caption-dom/zoom/2026-08-16-live/README.md`.
