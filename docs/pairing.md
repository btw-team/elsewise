# Browser extension pairing

Elsewise pairs each browser installation independently. No credential is displayed
or copied by the user.

## Pair a browser

1. Start the Elsewise server.
2. Open the extension popup and select **Pair**.
3. Open **Settings → Browser extension pairing** in the web GUI or desktop
   launcher.
4. Review the bounded browser name and family, then select **Allow** or **Deny**.
5. After approval, the extension stores its per-client credential in local browser
   storage and connects automatically.

The request expires after two minutes. **Cancel** withdraws a pending request. A
normal daemon or browser restart does not require pairing again.

## Manage paired browsers

The web GUI and launcher list paired clients without exposing credentials. Revoke a
client to close only that browser's active sockets and reject later reconnects.
Rename is available through the web GUI. Pairing the same installation again rotates
that client's credential.

The server stores only a SHA-256 digest of each secret. Plaintext is delivered once
over the nonce-bound pairing WebSocket to the requester and must not appear in logs,
diagnostics, URLs, UI snapshots, or API responses. This credential is distinct from
the short-lived runtime control credential used by the launcher.

See [Troubleshooting](troubleshooting.md#extension-is-not-paired) if approval does
not complete.
