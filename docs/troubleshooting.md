# Troubleshooting

## Server is unavailable

Run `elsewise status` and open `http://127.0.0.1:38473/api/health`. If another
process owns port 38473, Elsewise reports a conflict and will not kill or attach
to it. Use `elsewise logs --follow` for startup diagnostics.

## Extension is not paired

1. Open **Browser extension pairing** in the web GUI or launcher Settings.
2. Copy the saved token and replace the value in the extension popup.
3. If you entered a custom value, select **Save** before copying it.
4. If the values still do not match, select **Regenerate**, then copy the replacement
   into every extension installation. Regeneration immediately invalidates the
   previous token.
5. Confirm that the extension is connecting to `127.0.0.1:38473`, not another host
   or port.

The launcher can display or create the token while the server is stopped. The web
GUI requires the server to be running. A normal restart preserves the current token;
it does not require pairing again. See [Browser extension pairing](pairing.md).

## Captions are not detected

1. Enable captions in Meet, Teams, or Zoom Web.
2. Open the extension popup in the actual meeting tab and enable capture.
3. Check the popup platform, caption, source, and pending-event states.
4. Reload an unpacked extension after rebuilding it, then reload the meeting tab.
5. Use redacted diagnostics before collecting a sanitized fixture.

## Existing transcript is missing

Select the session and wait for its detail request. Stopped-session utterances are
not part of the global snapshot; they load from paginated session history.

## Agent is unavailable

Run the CLI health commands in [Codex and Claude Code](agents.md). Verify the path
shown in Launcher and Settings. Captions and exports work without an agent. There is
intentionally no automatic Codex/Claude fallback.

## Working-directory fallback

Choose an existing readable directory or explicitly create the missing path from
the session editor. The Agent header shows the directory name or **Fallback
directory**; full paths remain visible in session settings.

## Shutdown needs force

Normal Stop waits for bounded graceful provider/server shutdown. Force stop appears
only after timeout and requires confirmation because partial agent output may be
lost. If one Ctrl+C consistently produces a traceback, attach bounded logs and the
platform test case from the [validation matrix](testing/platform-validation-matrix.md).

## Update check fails

Update checks use the latest stable GitHub Release at most once per 24 hours. Offline
or rate-limited checks keep the current installation usable; download updates
manually from the release page.
