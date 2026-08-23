# Sanitized Microsoft Teams caption fixtures

These minimal fixtures preserve only semantic DOM signals observed in the private
2026-08-13 Teams Personal captures. Names, recognized speech, account identifiers,
generated Fluent classes, and unrelated meeting UI were replaced or omitted.

- `captions-off.html`: no caption root.
- `captions-on-empty.html`: enabled root and empty virtual list.
- `paused-utterances.html`: four separate same-speaker segments.
- `two-speakers.html`: stable author/text fields across a speaker change.
- `speaker-layout.html`: the same caption surface in Speaker layout.

Source analysis remains in the git-ignored diagnostic archive documented by
`output/playwright/caption-dom/microsoft-teams/2026-08-13-live/README.md`.
