import type { PlatformAdapter } from "../adapters/base";
import { GoogleMeetAdapter } from "../adapters/google-meet";
import { MicrosoftTeamsAdapter } from "../adapters/microsoft-teams";
import { SyntheticAdapter } from "../adapters/synthetic";
import { ZoomAdapter } from "../adapters/zoom";

const extensionVersion = __EXTENSION_VERSION__;

let port: chrome.runtime.Port;
let adapter: PlatformAdapter | null = null;

function meetingKey(): string {
  return (
    location.pathname.split("/").filter(Boolean).slice(0, 2).join("/") ||
    location.hostname
  );
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

function enableCapture(): void {
  adapter?.stop();
  adapter = createAdapter();
  if (!adapter) {
    port.postMessage({
      type: "adapter.status",
      platform: platform(),
      captionsStatus: "unavailable",
      speakerDetection: "unknown",
      confidence: 0,
      meetingKey: meetingKey(),
    });
    return;
  }
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
        meetingKey: meetingKey(),
      }),
    (status) =>
      port.postMessage({
        type: "adapter.status",
        ...status,
        meetingKey: meetingKey(),
      }),
  );
}

function connect(): void {
  port = chrome.runtime.connect({ name: "elsewise-content" });
  port.onDisconnect.addListener(() => {
    adapter?.stop();
    adapter = null;
    window.setTimeout(connect, 500);
  });
  port.onMessage.addListener((message: Record<string, unknown>) => {
    if (message.type === "capture.enable") enableCapture();
    if (message.type === "capture.disable") {
      adapter?.stop();
      adapter = null;
    }
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
}

connect();
