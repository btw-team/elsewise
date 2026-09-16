# Safari development extension

The Safari build uses the same TypeScript protocol, adapters, popup, and content
scripts as the Chrome and Firefox builds. During Stage 2 development it is loaded
directly into Safari as a temporary extension; the repository does not contain or
build a separate Safari containing app.

On the Intel macOS development machine:

```bash
npm run build:safari --workspace extension
```

Then open **Safari → Settings → Developer → Add Temporary Extension…** and select
`extension/dist/safari`. Enable Elsewise, grant access only to the meeting sites
being tested, then pair it through the same popup flow as Chrome and Firefox.
Start the daemon first with `uv run elsewise start`.

Safari removes a temporary extension after 24 hours or when Safari quits, so add
the folder again for the next live test. This is intentionally a development-only
workflow.

When macOS artifacts are implemented, the Safari Web Extension is built as an
`.appex` and embedded into the single main `Elsewise.app`. It must not be shipped
as a second standalone application. Signing, notarization, and final packaging
remain release work.

Manual acceptance still requires Safari load/pair/reconnect and one-producer
checks against the available Meet, Teams Web, and Zoom Web flows.
