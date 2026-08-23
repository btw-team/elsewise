# Browser extension pairing

Elsewise uses one local pairing token to authorize caption ingestion from the
Chrome and Firefox extensions. The web GUI and desktop launcher display and manage
the same token.

## Initial pairing

The server and launcher each check for a pairing token at startup. If the token file
does not exist or is damaged, Elsewise generates and saves a new token. Starting
either component first is sufficient; later starts reuse the saved value.

To pair an extension:

1. Open **Settings** in the web GUI or desktop launcher.
2. Find **Browser extension pairing**.
3. Select **Copy token**.
4. Open the Elsewise extension popup in the browser.
5. Paste the value into **Pairing token** and save it.

The extension stores the credential in its local browser storage. It sends the token
only in the first message of the local ingest WebSocket connection and never places
it in a URL. A successful connection changes the extension daemon status to
**Connected**.

## Change the token

Both Settings screens provide the same actions:

- **Copy token** copies the value currently shown in the field.
- **Regenerate** creates a random token, immediately replaces the saved value, and
  updates the field.
- **Save** trims and saves a manually entered token containing 16 to 4096 characters.

After editing the field manually, select **Save** before copying it to an extension.
Saving the unchanged token is a no-op. Saving a different token or selecting
**Regenerate** immediately invalidates the previous credential and disconnects
extensions that still use it. Copy the new value into every extension installation
that should reconnect.

The token persists across normal server and launcher restarts, so routine
regeneration is unnecessary.

## Local storage and security

The token is stored in `pairing.json` in the OS-native per-user Elsewise config
directory. The credential file is written atomically with owner-only permissions on
platforms that support POSIX modes. Server and launcher writers coordinate through a
local file lock.

Treat the token as a local credential: do not include it in logs, screenshots,
diagnostic bundles, issue reports, or shared shell output. The pairing token is
separate from the private runtime control token used by the launcher to manage the
server.

See [Troubleshooting](troubleshooting.md#extension-is-not-paired) if the extension
does not connect after saving the token.
