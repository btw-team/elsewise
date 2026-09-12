import type { PlatformAdapter } from "../adapters/base";
import { GoogleMeetAdapter } from "../adapters/google-meet";
import { MicrosoftTeamsAdapter } from "../adapters/microsoft-teams";
import { SyntheticAdapter } from "../adapters/synthetic";
import { ZoomAdapter } from "../adapters/zoom";

const extensionVersion = __EXTENSION_VERSION__;

let port: chrome.runtime.Port;
let adapter: PlatformAdapter | null = null;
let activeSourceEpochId: string | null = null;
const producerEpochId = crypto.randomUUID();
let lastDiscoveredActivity = "";

async function activityKey(): Promise<string> {
  const evidence = `${platform()}:${location.pathname}`;
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(evidence),
  );
  return [...new Uint8Array(digest)]
    .slice(0, 16)
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function createAdapter(): PlatformAdapter | null {
  const meet = new GoogleMeetAdapter(document);
  if (meet.matchesLocation(new URL(location.href))) return meet;
  const teams = new MicrosoftTeamsAdapter(document);
  if (teams.matchesLocation(new URL(location.href))) return teams;
  const zoom = new ZoomAdapter(document);
  if (zoom.matchesLocation(new URL(location.href))) return zoom;
  const synthetic = new SyntheticAdapter(document);
  if (synthetic.matchesLocation(new URL(location.href))) return synthetic;
  return null;
}

function platform(): string {
  if (location.hostname === "meet.google.com") return "google_meet";
  if (
    location.hostname === "teams.microsoft.com" ||
    location.hostname === "teams.live.com" ||
    location.hostname.endsWith(".teams.microsoft.com")
  ) {
    return "microsoft_teams";
  }
  if (location.hostname === "app.zoom.us") return "zoom";
  if (location.hostname === "127.0.0.1") return "synthetic";
  return "unsupported";
}

async function announceDiscovery(force = false): Promise<void> {
  const activity = `${platform()}:${location.pathname}`;
  if (!force && activity === lastDiscoveredActivity) return;
  lastDiscoveredActivity = activity;
  const key = await activityKey();
  const supported = createAdapter() !== null;
  port.postMessage({
    type: "adapter.discovered",
    producerEpochId,
    platform: platform(),
    activityKey: key,
    supported,
  });
}

function startSource(commandId: string, sourceEpochId: string): void {
  if (adapter && activeSourceEpochId === sourceEpochId) {
    port.postMessage({
      type: "adapter.command_ack",
      commandId,
      result: "started",
    });
    return;
  }
  adapter?.stop(false);
  adapter = createAdapter();
  if (!adapter) {
    port.postMessage({
      type: "adapter.status",
      platform: platform(),
      captionsStatus: "unavailable",
      speakerDetection: "unknown",
      confidence: 0,
    });
    port.postMessage({
      type: "adapter.command_ack",
      commandId,
      result: "failed",
      errorCode: "unsupported_source",
    });
    activeSourceEpochId = null;
    return;
  }
  activeSourceEpochId = sourceEpochId;
  adapter.start(
    (event) =>
      port.postMessage({
        type: "adapter.utterance",
        eventType: event.type,
        utteranceId: event.utteranceId,
        revision: event.revision,
        speaker: event.speaker,
        text: event.text,
        observedAt: event.observedAt,
      }),
    (status) =>
      port.postMessage({
        type: "adapter.status",
        ...status,
      }),
  );
  port.postMessage({
    type: "adapter.command_ack",
    commandId,
    result: "started",
  });
}

function stopSource(commandId: string, sourceEpochId: string): void {
  if (activeSourceEpochId !== sourceEpochId) {
    port.postMessage({
      type: "adapter.command_ack",
      commandId,
      result: "finalized",
    });
    return;
  }
  adapter?.stop(true);
  adapter = null;
  activeSourceEpochId = null;
  port.postMessage({
    type: "adapter.command_ack",
    commandId,
    result: "finalized",
  });
}

function connect(): void {
  port = chrome.runtime.connect({ name: "elsewise-content" });
  port.onDisconnect.addListener(() => {
    adapter?.stop(false);
    adapter = null;
    activeSourceEpochId = null;
    window.setTimeout(connect, 500);
  });
  port.onMessage.addListener((message: Record<string, unknown>) => {
    if (message.type === "source.start")
      startSource(String(message.commandId), String(message.sourceEpochId));
    if (message.type === "source.stop")
      stopSource(String(message.commandId), String(message.sourceEpochId));
    if (message.type === "diagnostics.dump") {
      const bundle = adapter?.dumpDiagnostics({
        redactText: message.redactText !== false,
        redactNames: message.redactNames !== false,
      });
      port.postMessage({
        type: "diagnostics.bundle",
        bundle: bundle ?? {
          adapter: "none",
          adapterVersion: extensionVersion,
          platform: platform(),
          sanitizedUrl: `${location.origin}${location.pathname}`,
          matchedSignals: [],
          subtree: null,
          recentMutations: [],
          warning: "No caption subtree was detected.",
        },
      });
    }
  });
  void announceDiscovery(true);
}

connect();
window.setInterval(() => void announceDiscovery(), 1_000);
