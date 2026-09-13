import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { chromium } from "playwright";

const root = resolve(import.meta.dirname, "../..");
const extensionPath = join(root, "extension", "dist", "chrome");
const daemonPort = 38473;
const captureDocumentationScreenshots =
  process.env.ELSEWISE_E2E_SCREENSHOTS === "1";

async function assertPortAvailable(port) {
  await new Promise((resolvePromise, rejectPromise) => {
    const probe = createServer();
    probe.unref();
    probe.once("error", (error) => {
      rejectPromise(
        new Error(
          `Synthetic E2E requires 127.0.0.1:${port}, but the port is already in use. ` +
            "Stop the running Elsewise/test process and retry.",
          { cause: error },
        ),
      );
    });
    probe.listen({ host: "127.0.0.1", port, exclusive: true }, () => {
      probe.close((error) => {
        if (error) rejectPromise(error);
        else resolvePromise();
      });
    });
  });
}

async function allocateFixturePort() {
  return new Promise((resolvePromise, rejectPromise) => {
    const probe = createServer();
    probe.unref();
    probe.once("error", rejectPromise);
    probe.listen({ host: "127.0.0.1", port: 0, exclusive: true }, () => {
      const address = probe.address();
      if (!address || typeof address === "string") {
        probe.close();
        rejectPromise(
          new Error("Unable to allocate the synthetic fixture port."),
        );
        return;
      }
      probe.close((error) => {
        if (error) rejectPromise(error);
        else resolvePromise(address.port);
      });
    });
  });
}

async function stopChild(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  const gracefulExit = once(child, "exit");
  child.kill("SIGTERM");
  const graceful = await Promise.race([
    gracefulExit.then(() => true),
    new Promise((resolvePromise) =>
      setTimeout(() => resolvePromise(false), 5_000),
    ),
  ]);
  if (graceful || child.exitCode !== null || child.signalCode !== null) return;
  const forcedExit = once(child, "exit");
  child.kill("SIGKILL");
  await Promise.race([
    forcedExit,
    new Promise((resolvePromise) => setTimeout(resolvePromise, 2_000)),
  ]);
}

await assertPortAvailable(daemonPort);
const fixturePort = await allocateFixturePort();

const temporary = await mkdtemp(join(tmpdir(), "elsewise-e2e-"));
const daemon = spawn(
  "uv",
  [
    "run",
    "uvicorn",
    "elsewise.main:app",
    "--app-dir",
    "server/src",
    "--port",
    String(daemonPort),
  ],
  {
    cwd: root,
    env: {
      ...process.env,
      ELSEWISE_DATA_DIR: join(temporary, "data"),
      ELSEWISE_CONFIG_DIR: join(temporary, "config"),
      ELSEWISE_CACHE_DIR: join(temporary, "cache"),
      ELSEWISE_RUNTIME_DIR: join(temporary, "runtime"),
      ELSEWISE_DIAGNOSTICS_DIR: join(temporary, "diagnostics"),
      ELSEWISE_DATABASE_URL: `sqlite:///${join(temporary, "e2e.sqlite3")}`,
      ELSEWISE_AGENT_PROVIDER: "fake",
    },
    stdio: ["ignore", "pipe", "pipe"],
  },
);
const fixtureServer = spawn(
  process.platform === "win32" ? "python" : "python3",
  [
    "-m",
    "http.server",
    String(fixturePort),
    "--bind",
    "127.0.0.1",
    "--directory",
    "tests/fixtures/synthetic",
  ],
  { cwd: root, stdio: ["ignore", "pipe", "pipe"] },
);

let context;
const browserDiagnostics = [];
let daemonDiagnostics = "";
let fixtureDiagnostics = "";
for (const stream of [daemon.stdout, daemon.stderr]) {
  stream.setEncoding("utf8");
  stream.on("data", (chunk) => {
    daemonDiagnostics = `${daemonDiagnostics}${chunk}`.slice(-16_000);
  });
}
for (const stream of [fixtureServer.stdout, fixtureServer.stderr]) {
  stream.setEncoding("utf8");
  stream.on("data", (chunk) => {
    fixtureDiagnostics = `${fixtureDiagnostics}${chunk}`.slice(-8_000);
  });
}

async function waitFor(
  url,
  predicate = (response) => response.ok,
  timeout = 15_000,
) {
  const deadline = Date.now() + timeout;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (predicate(response)) return response;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 150));
  }
  throw new Error(`Timed out waiting for ${url}`, { cause: lastError });
}

async function jsonRequest(path, options = {}) {
  const response = await fetch(`http://127.0.0.1:${daemonPort}${path}`, {
    ...options,
    headers: { "content-type": "application/json", ...(options.headers ?? {}) },
  });
  if (!response.ok)
    throw new Error(
      `${path} returned ${response.status}: ${await response.text()}`,
    );
  return response.status === 204 ? null : response.json();
}

async function pollSnapshot(predicate, timeout = 15_000) {
  const deadline = Date.now() + timeout;
  let latest = null;
  while (Date.now() < deadline) {
    const global = await jsonRequest("/api/snapshot");
    const selectedSession = global.sessions?.[0];
    const detail = selectedSession
      ? await jsonRequest(`/api/sessions/${selectedSession.id}/detail`)
      : null;
    latest = {
      ...global,
      utterances: detail?.utterances?.items ?? [],
      agentHistory: detail?.agent_history ?? null,
    };
    if (predicate(latest)) return latest;
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 150));
  }
  const summary = latest
    ? {
        sessions: latest.sessions?.map((session) => ({
          id: session.id,
          recording_status: session.recording_status,
          source_status: session.source_status,
          source_bindings: session.source_bindings,
        })),
        sources: latest.sources,
        utterances: latest.utterances,
        last_event_id: latest.last_event_id,
      }
    : null;
  throw new Error(
    `Timed out waiting for the expected daemon snapshot. Latest state: ${JSON.stringify(summary)}`,
  );
}

try {
  await waitFor(`http://127.0.0.1:${daemonPort}/api/health`);
  await waitFor(`http://127.0.0.1:${fixturePort}/?elsewise-synthetic=1`);

  const browserOptions = {
    channel: "chromium",
    headless: process.env.ELSEWISE_E2E_HEADED !== "1",
    args: [
      `--disable-extensions-except=${extensionPath}`,
      `--load-extension=${extensionPath}`,
    ],
  };
  if (process.env.CHROME_PATH) {
    browserOptions.executablePath = process.env.CHROME_PATH;
    delete browserOptions.channel;
  }
  context = await chromium.launchPersistentContext(
    join(temporary, "chrome-profile"),
    browserOptions,
  );
  const worker =
    context.serviceWorkers()[0] ??
    (await context.waitForEvent("serviceworker", { timeout: 15_000 }));
  worker.on("console", (message) =>
    browserDiagnostics.push(
      `service worker ${message.type()}: ${message.text()}`,
    ),
  );

  const page = await context.newPage();
  page.on("console", (message) =>
    browserDiagnostics.push(`fixture ${message.type()}: ${message.text()}`),
  );
  page.on("pageerror", (error) =>
    browserDiagnostics.push(`fixture pageerror: ${error.message}`),
  );
  const harnessUrl = `http://127.0.0.1:${fixturePort}/?elsewise-synthetic=1`;
  await page.goto(harnessUrl);
  await page.waitForSelector("[data-elsewise-captions]");
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 500));

  const extensionId = new URL(worker.url()).hostname;
  const extensionPage = await context.newPage();
  await extensionPage.setViewportSize({ width: 420, height: 720 });
  await extensionPage.goto(`chrome-extension://${extensionId}/popup.html`);
  await extensionPage.locator("#pair").click();
  const pendingRequest = await (async () => {
    const deadline = Date.now() + 15_000;
    while (Date.now() < deadline) {
      const requests = await jsonRequest("/api/pairing/requests");
      if (requests[0]) return requests[0];
      await new Promise((resolvePromise) => setTimeout(resolvePromise, 100));
    }
    throw new Error("Timed out waiting for the extension pairing request");
  })();
  await jsonRequest(`/api/pairing/requests/${pendingRequest.id}/approve`, {
    method: "POST",
  });
  await extensionPage.waitForFunction(async () => {
    const state = await chrome.runtime.sendMessage({ type: "popup.status" });
    return state.daemon === "connected" && state.pairing === "paired";
  });

  await pollSnapshot((snapshot) =>
    snapshot.sources.some(
      (source) =>
        source.platform === "synthetic" &&
        source.connected === true &&
        source.available === true,
    ),
  );
  const session = await jsonRequest("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ title: "Synthetic E2E" }),
  });
  await jsonRequest(`/api/sessions/${session.id}/start`, { method: "POST" });
  await pollSnapshot(
    (snapshot) =>
      snapshot.sessions[0]?.recording_status === "running" &&
      snapshot.sessions[0]?.source_bindings?.some(
        (binding) =>
          binding.role === "secondary" && typeof binding.source_id === "string",
      ),
  );

  await page.locator("[data-elsewise-captions]").evaluate((root) => {
    root.innerHTML = `
      <article data-utterance-id="e2e-1" data-speaker="Speaker A">
        <span data-caption-text>Hello</span>
      </article>`;
  });
  await pollSnapshot((snapshot) => snapshot.utterances[0]?.text === "Hello");

  await page.locator("[data-caption-text]").evaluate((node) => {
    node.textContent = "Hello from the real extension";
  });
  await page.locator("[data-utterance-id]").evaluate((node) => {
    node.setAttribute("data-final", "true");
  });
  const finalized = await pollSnapshot(
    (snapshot) =>
      snapshot.utterances[0]?.text === "Hello from the real extension" &&
      snapshot.utterances[0]?.final === true,
  );
  if (finalized.utterances[0].revision !== 3) {
    throw new Error(
      `Expected revision 3, got ${finalized.utterances[0].revision}`,
    );
  }

  const gui = await context.newPage();
  await gui.setViewportSize({ width: 1440, height: 900 });
  await gui.goto(`http://127.0.0.1:${daemonPort}/`);
  await gui.getByRole("heading", { name: "Synthetic E2E" }).waitFor();
  await gui
    .getByText("Hello from the real extension", { exact: false })
    .waitFor();
  await gui.getByRole("button", { name: "Summary" }).click();
  const summaryRun = gui.locator(".agent-run").filter({ hasText: "Summary" });
  await summaryRun.getByText("Готово", { exact: true }).waitFor();
  await summaryRun.getByText("Completed", { exact: true }).waitFor();
  if (captureDocumentationScreenshots) {
    await gui.screenshot({
      path: join(root, "docs", "assets", "screenshots", "web-gui.png"),
    });
    await extensionPage.reload();
    await extensionPage.waitForFunction(async () => {
      const state = await chrome.runtime.sendMessage({ type: "popup.status" });
      return state.daemon === "connected" && state.pairing === "paired";
    });
    await extensionPage.screenshot({
      path: join(root, "docs", "assets", "screenshots", "extension-popup.png"),
    });
  }
  await extensionPage.close();
  await gui.close();

  const browserSession = await context.newCDPSession(page);
  const targets = await browserSession.send("Target.getTargets");
  const serviceWorkerTarget = targets.targetInfos.find(
    (target) =>
      target.type === "service_worker" &&
      target.url.startsWith("chrome-extension://"),
  );
  if (!serviceWorkerTarget)
    throw new Error("Extension service worker target was not found");
  await browserSession.send("Target.closeTarget", {
    targetId: serviceWorkerTarget.targetId,
  });
  const wakePage = await context.newPage();
  await wakePage.goto(`chrome-extension://${extensionId}/popup.html`);
  await wakePage.waitForFunction(async () => {
    try {
      return Boolean(
        await chrome.runtime.sendMessage({ type: "popup.status" }),
      );
    } catch {
      return false;
    }
  });
  await wakePage.close();

  await page.locator("[data-elsewise-captions]").evaluate((root) => {
    root.insertAdjacentHTML(
      "beforeend",
      `<article data-utterance-id="e2e-2" data-speaker="Speaker B" data-final="true">
        <span data-caption-text>After restart</span>
      </article>`,
    );
  });
  const afterRestart = await pollSnapshot((snapshot) =>
    snapshot.utterances.some((item) => item.text === "After restart"),
  );
  if (afterRestart.utterances.length !== 2) {
    throw new Error(
      `Expected exactly two utterances, got ${afterRestart.utterances.length}`,
    );
  }
  await jsonRequest(`/api/sessions/${session.id}/stop`, { method: "POST" });
  const stopped = await pollSnapshot(
    (snapshot) => snapshot.sessions[0]?.recording_status === "stopped",
  );
  const stoppedUtteranceCount = stopped.utterances.length;
  await page.locator("[data-elsewise-captions]").evaluate((root) => {
    root.insertAdjacentHTML(
      "beforeend",
      `<article data-utterance-id="e2e-late" data-speaker="Speaker C" data-final="true">
        <span data-caption-text>After stop boundary</span>
      </article>`,
    );
  });
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 500));
  const afterStop = await pollSnapshot(
    (snapshot) => snapshot.sessions[0]?.recording_status === "stopped",
  );
  if (afterStop.utterances.length !== stoppedUtteranceCount) {
    throw new Error("Transcript changed after the session reached stopped");
  }
  process.stdout.write(
    "Synthetic E2E passed: pairing, captions, agent action, worker restart and bounded stop.\n",
  );
} catch (error) {
  throw new Error(
    `${error instanceof Error ? error.message : String(error)}` +
      `\nBrowser diagnostics:\n${browserDiagnostics.join("\n") || "(none)"}` +
      `\nDaemon diagnostics:\n${daemonDiagnostics.trim() || "(none)"}` +
      `\nFixture diagnostics:\n${fixtureDiagnostics.trim() || "(none)"}`,
    { cause: error },
  );
} finally {
  await context?.close();
  await Promise.all([stopChild(daemon), stopChild(fixtureServer)]);
  await rm(temporary, { recursive: true, force: true });
}
