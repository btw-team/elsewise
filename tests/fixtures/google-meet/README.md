# Sanitized Google Meet caption fixtures

These minimal fixtures are manually derived from the Git-ignored live captures in
`output/playwright/caption-dom/google-meet/2026-08-13-live/`. Participant names,
meeting identifiers, chat messages, avatars, and spoken text were replaced. The
fixtures retain only the structural and lifecycle signals required by adapter tests.

Covered states: captions off, enabled/empty, incremental and non-monotonic text
revisions, multiple speakers, unknown speaker, localized Russian controls, region
removal/recreation, block reinsertion, and layout width changes.
