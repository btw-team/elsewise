# Getting started

## 1. Start the server

Open the Elsewise launcher. The server starts automatically by default. The
Overview page should show **Server · Running**, a PID, and the web GUI address.

The same lifecycle is available from a terminal:

```text
elsewise start
elsewise status
elsewise open
elsewise restart
elsewise logs --follow
elsewise stop
```

Closing the launcher normally leaves the server running. This behavior can be
changed in Launcher Settings.

### Interface theme

Elsewise starts in the dark theme. Choose **Light** or **Dark** under
**Settings → Interface** in either the web GUI or desktop launcher. The selection
is stored in the shared global settings and is applied to both surfaces
automatically, including when the other surface changes it while open.

The browser extension popup has its own Light/Dark control in the upper-right
corner. This preference is stored only by the extension and themes the popup and
the side-panel loading/error shell. It does not override the web GUI displayed
inside the side panel.

## 2. Pair the browser extension

The server and launcher create a shared local extension pairing token automatically
when one does not exist. Open **Settings** in either the web GUI or launcher, find
**Browser extension pairing**, select **Copy token**, and paste the value into the
extension popup.

The Settings section also accepts a manually entered token through **Save** and can
create a replacement through **Regenerate**. Save manual edits before copying them.
Changing the saved token immediately invalidates the previous credential, while the
unchanged token persists across restarts. See
[Browser extension pairing](pairing.md) for the complete lifecycle and security
notes.

The popup should report the daemon as **Connected**. Use **Open side panel** or
**Open in new tab** to display the same web GUI.

## 3. Create a session

Choose **New session** and configure:

- title, description, and meeting language;
- action preset;
- Codex or Claude Code;
- optional model, effort, initial prompt, and working directory;
- workspace-write and network permissions.

The provider, language, preset, initial prompt, and working directory become locked
after the first start. Title, description, and permissions remain editable while
the session is not actively recording.

## 4. Enable capture

Open a supported meeting, enable the meeting platform's own captions, open the
Elsewise popup in that tab, and choose **Enable**. Then start the session in the
web GUI. Starting before a source appears is valid; the session waits for capture.

## 5. Use the transcript and agent

Utterances appear in the center column. Use preset actions in the lower bar or send
a free prompt from the Agent column. Requests execute FIFO in one provider-specific
thread per session.

Stop and restart create separate capture segments while preserving transcript and
agent history. Export writes `captions.md` and `agent.md` to a session-specific
local directory.

See [Meeting capture](meeting-capture.md) and
[Sessions, actions, and presets](sessions-and-actions.md) next.
