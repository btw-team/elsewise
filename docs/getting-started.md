# Getting started

Elsewise combines a desktop application, a browser extension, and an external AI
agent. The desktop package runs the local server and provides the launcher and web
GUI. The extension supplies live captions from the browser, while the agent turns
that context into real-time assistance.

## Product surfaces

| Desktop launcher                                                | Browser extension                                                                               |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| ![Elsewise launcher overview](assets/screenshots/launcher.webp) | ![Elsewise extension connected to a live conversation](assets/screenshots/extension-popup.webp) |

## 1. Install Elsewise and the browser extension

Download the application package for your operating system from the
[latest GitHub Release](https://github.com/btw-team/elsewise/releases/latest) and
follow the [platform installation instructions](installation.md). The package
includes the local Elsewise server, the web GUI, and the desktop launcher used to
start and manage them.

Install the matching extension archive from the same release. The extension is
required because it captures captions already rendered by the meeting platform and
sends them to the local server. Elsewise currently supports:

- Google Chrome 116 or later;
- Mozilla Firefox 140 or later.

Other Chromium-based browsers are not currently part of the tested support matrix.
See [Browser extensions](installation.md#browser-extensions) for loading
instructions.

## 2. Install and authenticate an AI agent

Real-time advice requires at least one supported local agent: Codex CLI or Claude
Code. If neither is installed, choose one, install it using its official setup
guide, and complete its authentication flow:

- [Install and sign in to Codex CLI](https://developers.openai.com/codex/cli/)
- [Install and authenticate Claude Code](https://code.claude.com/docs/en/getting-started)

Run `codex` or `claude` once after installation and follow the sign-in prompts.
Elsewise uses the agent already installed and authenticated for your local user; it
does not bundle an agent or its credentials.

Without an available agent, Elsewise can still capture platform captions, assemble
the live transcript, retain session history, and export it. Preset actions, free
prompts, and real-time AI advice remain unavailable until an agent is configured.

## 3. Start the server

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

## 4. Pair the browser extension

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

The popup should report the daemon as **Connected**.

## 5. Open the web GUI

Before the conversation begins, open the web GUI so the transcript and assistance
controls are ready. Use **Open side panel** or **Open in new tab** in the extension,
select **Open web GUI** in the launcher, or navigate directly to
[`http://127.0.0.1:38473/`](http://127.0.0.1:38473/).

The browser side panel is usually the most convenient option during a live
conversation because it keeps Elsewise beside the meeting tab.

## 6. Explore and choose a preset

Before creating a session, review the built-in workflows and identify the preset
that matches your role and use case. Select the four-square **Actions** button in
the lower-right corner of the web GUI, then open the **Action presets** tab.

A preset determines which focused action buttons will be available during the
conversation. You can use a built-in preset as-is, edit its actions, or create a
workflow of your own. See [Sessions, actions, and presets](sessions-and-actions.md)
for the available presets and customization model.

## 7. Prepare a session context folder (optional)

Each session can use an **Agent working directory** as an additional source of
context. When the agent starts its initial warm-up, it briefly inspects the folder
structure and selectively reads the most relevant text documents and configuration
files.

A focused context folder can contain:

- background information about you, your role, or the project;
- a brief about the other participants or organization;
- documents and reference material relevant to the conversation;
- goals, constraints, terminology, and conditions the agent should consider.

Keep the folder small and purpose-specific, and do not place credentials or other
secrets in it. Elsewise instructs the agent to treat files as supporting context,
not as unconditionally trusted instructions. The directory is read-only by default;
allowing the agent to write into it requires an explicit session permission.

Enter the folder path in **Agent working directory** when creating the session. If
you leave it empty, Elsewise uses a safe empty fallback directory instead.

## 8. Create a session

Choose **New session** and configure:

- title, description, and meeting language;
- the action preset you selected;
- Codex or Claude Code;
- optional model, effort, initial prompt, and the context folder you prepared;
- workspace-write and network permissions.

The provider, language, preset, initial prompt, and working directory become locked
after the first start. Title, description, and permissions remain editable while
the session is not actively recording.

## 9. Enable capture

Open a supported meeting, enable the meeting platform's own captions, open the
Elsewise popup in that tab, and choose **Enable**. Then start the session in the web
GUI. Starting before a source appears is valid; the session waits for capture.

## 10. Use the transcript and agent

Utterances appear in the center column. Use preset actions in the lower bar or send
a free prompt from the Agent column. Requests execute FIFO in one provider-specific
thread per session.

Stop and restart create separate capture segments while preserving transcript and
agent history. Export writes `captions.md` and `agent.md` to a session-specific
local directory.

See [Meeting capture](meeting-capture.md) and
[Sessions, actions, and presets](sessions-and-actions.md) next.
