# Meeting capture

## Supported web platforms

- Google Meet
- Microsoft Teams Web
- Zoom Web Client

Elsewise does not access microphone audio. It observes the caption DOM already
rendered by the meeting platform, so captions must be enabled in the meeting itself.

## Capture lifecycle

Only one Elsewise session records at a time. A session may start before an
enabled source exists. Before recording begins, the enabled meeting tab can change;
during recording, switching to another meeting is rejected to prevent transcripts
from being mixed.

Partial utterances update in place. Finalization occurs when the platform marks a
caption final, replaces or removes its caption node, changes speakers, disables
captions, or reaches a conservative idle boundary.

## Speakers

Meet and Teams normally expose display names. Zoom speaker names are recovered from
the page's local client state where available; otherwise captions remain associated
with stable anonymous avatars.

Set your own Meet, Teams, and Zoom display names in web GUI Settings. Elsewise
uses them only to distinguish your utterances from other participants in the local
UI and prompt context.

## Segments

Every Start or Restart creates a new numbered segment containing date and time.
Stopping closes the current segment. After a daemon crash, startup recovery closes
the segment with `daemon_restart` and removes unfinished partial utterances.

## Diagnostics

The extension Debug section can copy bounded, redacted diagnostics or dump a
caption subtree for adapter development. Normal diagnostics omit caption text,
speaker names, meeting titles, credentials, and sensitive URL components.

Never attach a raw meeting DOM dump to a public issue. Create a minimized sanitized
fixture instead; see [Extension adapters](development/extension-adapters.md).
